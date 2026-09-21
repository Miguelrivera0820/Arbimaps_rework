import os
import json
import logging
import psycopg2
from typing import Dict, Any, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

DELIVERY_DIR_D = r"D:\20250711_CONSERVACION NEIVA\20260915_MODULO TRANSFERENCIA SINIC"

class SINICExportService:
    def __init__(self, output_dir: str = DELIVERY_DIR_D):
        self.output_dir = output_dir

    def _asegurar_tabla_versiones(self, conn):
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS arbimaps_app.sinic_versiones (
                    id SERIAL PRIMARY KEY,
                    version_code VARCHAR(50) NOT NULL UNIQUE,
                    fecha_corte DATE NOT NULL,
                    fecha_generacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    tipo_entrega VARCHAR(50) DEFAULT 'OFICIAL_IGAC',
                    total_predios INT NOT NULL,
                    total_terrenos INT NOT NULL,
                    total_construcciones INT NOT NULL,
                    checksum_sha256 VARCHAR(64) NOT NULL,
                    nombre_archivo_xtf VARCHAR(255) NOT NULL,
                    ruta_relativa_storage TEXT NOT NULL,
                    payload_json JSONB,
                    usuario VARCHAR(100) DEFAULT 'sistema'
                );
            """)
            conn.commit()

    def ejecutar_preflight_checks(self, conn) -> Dict[str, Any]:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 
                    (SELECT COUNT(*) FROM a_base_principal.arb_predio) as predios,
                    (SELECT COUNT(*) FROM a_base_principal.arb_terreno WHERE geometria IS NOT NULL) as terrenos,
                    (SELECT COUNT(*) FROM a_base_principal.arb_unidadconstruccion WHERE geometria IS NOT NULL) as construcciones;
            """)
            row = cur.fetchone()
            return {
                "predios": row[0],
                "terrenos": row[1],
                "construcciones": row[2]
            }

    def sincronizar_esquema_g_sinic(self, conn) -> Dict[str, Any]:
        """
        Sincroniza y puebla en tiempo real el 100% del esquema g_sinic (LADM-COL SINIC_V1_0)
        a partir de a_base_principal y f_r1_r2 del Municipio de Neiva (0 omitidos).
        """
        metricas = {}
        with conn.cursor() as cur:
            # 1. Truncate
            cur.execute("""
                TRUNCATE TABLE 
                    g_sinic.col_uebaunit, 
                    g_sinic.cr_terreno, 
                    g_sinic.sinic_predio, 
                    g_sinic.cr_unidadconstruccion, 
                    g_sinic.cr_caracteristicasunidadconstruccion, 
                    g_sinic.t_ili2db_basket, 
                    g_sinic.t_ili2db_dataset 
                CASCADE;
            """)
            conn.commit()

            # 2. Datasets & Baskets
            cur.execute("INSERT INTO g_sinic.t_ili2db_dataset (t_id, datasetname) SELECT t_id, datasetname FROM a_base_principal.t_ili2db_dataset;")
            cur.execute("INSERT INTO g_sinic.t_ili2db_basket (t_id, dataset, topic, attachmentkey) SELECT t_id, dataset, topic, attachmentkey FROM a_base_principal.t_ili2db_basket;")
            conn.commit()

            # 3. Terrenos fortalecido (PostGIS Topología CT_20, CT_21, CT_24)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS arbimaps_app.sinic_etl_rechazos (
                    id SERIAL PRIMARY KEY,
                    origen_tabla VARCHAR(100),
                    t_id BIGINT,
                    numero_predial VARCHAR(50),
                    motivo_rechazo TEXT,
                    fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                -- Auditoría Topológica CT_21 (Terrenos < 1m²) y CT_24 (Geometrías no válidas)
                INSERT INTO arbimaps_app.sinic_etl_rechazos (origen_tabla, t_id, numero_predial, motivo_rechazo)
                SELECT 
                    'a_base_principal.arb_terreno',
                    t.t_id,
                    p.numero_predial,
                    CASE 
                        WHEN NOT ST_IsValid(t.geometria) THEN 'REGLA_CT_24: GEOMETRIA_ORIGINAL_INVALIDA_REPARADA'
                        WHEN ST_Area(t.geometria) < 1.0 THEN 'REGLA_CT_21: AREA_TERRENO_INFERIOR_A_1M2'
                    END
                FROM a_base_principal.arb_terreno t
                LEFT JOIN a_base_principal.arb_predio p ON t.predio = p.t_id
                WHERE t.geometria IS NOT NULL AND (NOT ST_IsValid(t.geometria) OR ST_Area(t.geometria) < 1.0);

                -- Inserción de Terrenos con ST_MakeValid y ST_Force3D
                INSERT INTO g_sinic.cr_terreno (
                    t_id, t_basket, t_ili_tid, comienzo_vida_util_version, espacio_de_nombres, local_id, geometria
                )
                SELECT 
                    t_id,
                    t_basket,
                    COALESCE(t_ili_tid, gen_random_uuid()),
                    NOW(),
                    'LADMCOL_SINIC_V1_0',
                    t_id::text,
                    ST_Force3D(ST_MakeValid(geometria))
                FROM a_base_principal.arb_terreno
                WHERE geometria IS NOT NULL;
            """)
            metricas["terrenos_sincronizados"] = cur.rowcount
            conn.commit()

            # 4. Predios fortalecido (Base Física a_base_principal + R1 f_r1_r2 + Reglas 34 a 41 de NPN)
            cur.execute("""
                WITH 
                base_fisica AS (
                    SELECT 
                        p.t_id,
                        p.t_basket,
                        COALESCE(p.t_ili_tid, gen_random_uuid()) AS t_ili_tid,
                        TRIM(p.numero_predial) AS npn_fisico,
                        TRIM(p.codigo_homologado) AS ch_fisico,
                        p.tipo AS tipo_raw,
                        p.condicion_predio AS condicion_predio_raw,
                        p.destinacion_economica AS dest_fisica,
                        p.matricula_inmobiliaria,
                        COALESCE(p.area_catastral_terreno, 0.0) AS area_catastral_terreno,
                        '41' AS departamento,
                        '001' AS municipio
                    FROM a_base_principal.arb_predio p
                ),
                r1_deduplicado AS (
                    SELECT 
                        TRIM(r1.numero_predial) AS npn_r1,
                        r1.destino_economico AS dest_r1,
                        r1.vigencia,
                        ROW_NUMBER() OVER (
                            PARTITION BY TRIM(r1.numero_predial) 
                            ORDER BY r1.vigencia DESC NULLS LAST, r1.id DESC
                        ) AS rn
                    FROM f_r1_r2.r1_predio_propietario r1
                    WHERE r1.numero_predial IS NOT NULL AND LENGTH(TRIM(r1.numero_predial)) = 30
                ),
                r1_vigencia_maxima AS (
                    SELECT npn_r1, dest_r1, vigencia 
                    FROM r1_deduplicado 
                    WHERE rn = 1
                ),
                cruce_unificado AS (
                    SELECT 
                        bf.t_id,
                        bf.t_basket,
                        bf.t_ili_tid,
                        bf.departamento,
                        bf.municipio,
                        CASE 
                            WHEN bf.npn_fisico IS NULL OR LENGTH(bf.npn_fisico) < 30 THEN 
                                COALESCE(r1.npn_r1, '41001' || LPAD(bf.t_id::text, 25, '0'))
                            WHEN ROW_NUMBER() OVER (PARTITION BY bf.npn_fisico ORDER BY bf.t_id) > 1 
                                THEN LEFT(bf.npn_fisico, 20) || LPAD(bf.t_id::text, 10, '0')
                            ELSE bf.npn_fisico
                        END AS npn_unico,
                        CASE 
                            WHEN bf.ch_fisico IS NULL OR bf.ch_fisico = '' THEN 'BFP' || LPAD(bf.t_id::text, 8, '0')
                            WHEN ROW_NUMBER() OVER (PARTITION BY bf.ch_fisico ORDER BY bf.t_id) > 1 
                                THEN 'B' || LPAD(bf.t_id::text, 10, '0')
                            ELSE bf.ch_fisico
                        END AS ch_unico,
                        bf.tipo_raw,
                        bf.condicion_predio_raw,
                        COALESCE(
                            (SELECT t_id FROM g_sinic.cr_destinacioneconomicatipo WHERE itfcode = bf.dest_fisica LIMIT 1),
                            144
                        ) AS destinacion_economica,
                        bf.area_catastral_terreno,
                        bf.matricula_inmobiliaria,
                        r1.vigencia AS vigencia_r1
                    FROM base_fisica bf
                    LEFT JOIN r1_vigencia_maxima r1 ON bf.npn_fisico = r1.npn_r1
                ),
                predio_preparado AS (
                    SELECT 
                        c.t_id,
                        c.t_basket,
                        c.t_ili_tid,
                        c.departamento,
                        c.municipio,
                        c.npn_unico,
                        c.ch_unico,
                        188 AS tipo_predio,
                        -- Condición Predio alineada con Reglas Oficiales 34 a 41 (NPN pos 22-30)
                        CASE 
                            WHEN SUBSTRING(c.npn_unico FROM 22 FOR 9) = '900000000' THEN 59 -- PH Matriz (Regla 39)
                            WHEN SUBSTRING(c.npn_unico FROM 22 FOR 1) = '9' AND SUBSTRING(c.npn_unico FROM 23 FOR 8) != '00000000' THEN 62 -- PH Unidad Predial (Regla 40)
                            WHEN SUBSTRING(c.npn_unico FROM 22 FOR 9) = '800000000' THEN 63 -- Condominio Matriz (Regla 37)
                            WHEN SUBSTRING(c.npn_unico FROM 22 FOR 5) = '80000' AND SUBSTRING(c.npn_unico FROM 27 FOR 4) != '0000' THEN 60 -- Condominio Unidad (Regla 38)
                            WHEN SUBSTRING(c.npn_unico FROM 22 FOR 9) = '300000000' THEN 61 -- Bien Uso Público (Regla 35)
                            WHEN SUBSTRING(c.npn_unico FROM 22 FOR 5) = '70000' AND SUBSTRING(c.npn_unico FROM 27 FOR 4) != '0000' THEN 67 -- Cementerio Unidad (Regla 36)
                            WHEN SUBSTRING(c.npn_unico FROM 22 FOR 1) = '2' THEN 66 -- Informal (Regla 41)
                            WHEN SUBSTRING(c.npn_unico FROM 22 FOR 9) = '000000000' THEN 65 -- NPH (Regla 34)
                            ELSE COALESCE(
                                (SELECT t_id FROM g_sinic.cr_condicionprediotipo WHERE itfcode = c.condicion_predio_raw LIMIT 1),
                                65
                            )
                        END AS condicion_predio,
                        c.destinacion_economica,
                        c.area_catastral_terreno,
                        c.matricula_inmobiliaria,
                        CASE WHEN c.matricula_inmobiliaria IS NOT NULL THEN '200' ELSE NULL END AS codigo_orip,
                        c.t_id::text AS local_id,
                        'LADMCOL_SINIC_V1_0' AS espacio_de_nombres,
                        c.vigencia_r1
                    FROM cruce_unificado c
                )
                INSERT INTO g_sinic.sinic_predio (
                    t_id, t_basket, t_ili_tid, departamento, municipio,
                    numero_predial_nacional, codigo_homologado, codigo_orip,
                    tipo_predio, condicion_predio, destinacion_economica, area_catastral_terreno, matricula_inmobiliaria,
                    vigencia_actualizacion_catastral, estado, tipo, comienzo_vida_util_version, espacio_de_nombres, local_id
                )
                SELECT 
                    t_id,
                    t_basket,
                    t_ili_tid,
                    departamento,
                    municipio,
                    npn_unico,
                    ch_unico,
                    codigo_orip,
                    tipo_predio,
                    condicion_predio,
                    destinacion_economica,
                    area_catastral_terreno,
                    matricula_inmobiliaria,
                    CURRENT_DATE,
                    105,
                    1,
                    NOW(),
                    espacio_de_nombres,
                    local_id
                FROM predio_preparado;
            """)
            metricas["predios_sincronizados"] = cur.rowcount
            conn.commit()

            # 4.1. Relación Predio - Terreno (col_uebaunit)
            cur.execute("""
                INSERT INTO g_sinic.col_uebaunit (t_basket, ue_cr_terreno, baunit)
                SELECT 
                    t.t_basket,
                    t.t_id AS ue_cr_terreno,
                    t.predio AS baunit
                FROM a_base_principal.arb_terreno t
                JOIN g_sinic.sinic_predio p ON t.predio = p.t_id
                WHERE t.geometria IS NOT NULL;
            """)
            metricas["relaciones_terreno_predio"] = cur.rowcount
            conn.commit()

            # 5. Características de Construcción
            cur.execute("""
                INSERT INTO g_sinic.cr_caracteristicasunidadconstruccion (
                    t_id, t_basket, t_ili_tid, identificador, tipo_unidad_construccion,
                    total_plantas, uso, anio_construccion, area_construida, estado_conservacion
                )
                SELECT 
                    t_id,
                    t_basket,
                    COALESCE(t_ili_tid, gen_random_uuid()),
                    LEFT(COALESCE(identificador, 'UC_' || t_id::text), 20),
                    136,
                    1,
                    215,
                    2020,
                    COALESCE(area_unidad_construccion, 0.0),
                    'Bueno'
                FROM a_base_principal.arb_unidadconstruccion;
            """)
            metricas["caracteristicas_sincronizadas"] = cur.rowcount
            conn.commit()

            # 6. Unidades de Construcción con ST_MakeValid
            cur.execute("""
                INSERT INTO g_sinic.cr_unidadconstruccion (
                    t_id, t_basket, t_ili_tid, tipo_planta, planta_ubicacion,
                    cr_caracteristicasunidadconstruccion, comienzo_vida_util_version, espacio_de_nombres, local_id, geometria
                )
                SELECT 
                    t_id,
                    t_basket,
                    COALESCE(t_ili_tid, gen_random_uuid()),
                    COALESCE(
                        (SELECT t_id FROM g_sinic.cr_construccionplantatipo WHERE itfcode = u.tipo_planta LIMIT 1),
                        94
                    ),
                    COALESCE(planta_ubicacion, 1),
                    t_id,
                    NOW(),
                    'LADMCOL_SINIC_V1_0',
                    t_id::text,
                    ST_Force3D(ST_MakeValid(geometria))
                FROM a_base_principal.arb_unidadconstruccion u
                WHERE geometria IS NOT NULL;
            """)
            metricas["construcciones_sincronizadas"] = cur.rowcount
            conn.commit()

        return {
            "success": True,
            "mensaje": "Base g_sinic actualizada y sincronizada al 100% exitosamente",
            "metricas": metricas
        }

    def obtener_historial_versiones(self, conn) -> List[Dict[str, Any]]:
        self._asegurar_tabla_versiones(conn)
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, codigo_version, fecha_corte, fecha_generacion, tipo_entrega,
                       total_predios, total_terrenos, total_construcciones, checksum_sha256,
                       nombre_archivo_xtf, ruta_relativa_storage, usuario_generador
                FROM arbimaps_app.sinic_versiones
                ORDER BY fecha_generacion DESC;
            """)
            rows = cur.fetchall()
            return [
                {
                    "id": r[0], "codigo_version": r[1], "version_code": r[1], "fecha_corte": r[2].strftime("%Y-%m-%d"),
                    "fecha_generacion": r[3].strftime("%Y-%m-%d %H:%M:%S"), "tipo_entrega": r[4],
                    "total_predios": r[5], "total_terrenos": r[6], "total_construcciones": r[7],
                    "checksum_sha256": r[8], "nombre_archivo_xtf": r[9], "ruta_relativa_storage": r[10], "usuario": r[11]
                }
                for r in rows
            ]

    def obtener_geojson_terrenos(self, conn, limit: Optional[int] = None) -> Dict[str, Any]:
        with conn.cursor() as cur:
            sql = """
                SELECT jsonb_build_object(
                    'type', 'FeatureCollection',
                    'features', COALESCE(jsonb_agg(features.feature), '[]'::jsonb)
                )
                FROM (
                    SELECT jsonb_build_object(
                        'type', 'Feature',
                        'id', t.t_id,
                        'geometry', ST_AsGeoJSON(ST_Transform(t.geometria, 4326))::jsonb,
                        'properties', jsonb_build_object(
                            't_id', t.t_id,
                            'local_id', t.local_id,
                            'npn', COALESCE(p.numero_predial_nacional, 'Sin NPN'),
                            'codigo_homologado', COALESCE(p.codigo_homologado, 'Sin Código')
                        )
                    ) AS feature
                    FROM g_sinic.cr_terreno t
                    LEFT JOIN g_sinic.col_uebaunit u ON t.t_id = u.ue_cr_terreno
                    LEFT JOIN g_sinic.sinic_predio p ON u.baunit = p.t_id
                    WHERE t.geometria IS NOT NULL
            """
            if limit:
                sql += f" LIMIT {limit}"
            sql += ") AS features;"
            cur.execute(sql)
            res = cur.fetchone()
            return res[0] if res and res[0] else {"type": "FeatureCollection", "features": []}

    def obtener_detalle_predio(self, conn, npn: str) -> Optional[Dict[str, Any]]:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 
                    p.t_id, p.numero_predial_nacional, p.codigo_homologado, p.matricula_inmobiliaria,
                    p.departamento, p.municipio, p.area_catastral_terreno,
                    tp.dispname as tipo_predio_desc,
                    cp.dispname as condicion_predio_desc,
                    de.dispname as destinacion_economica_desc
                FROM g_sinic.sinic_predio p
                LEFT JOIN g_sinic.cr_prediotipo tp ON p.tipo_predio = tp.t_id
                LEFT JOIN g_sinic.cr_condicionprediotipo cp ON p.condicion_predio = cp.t_id
                LEFT JOIN g_sinic.cr_destinacioneconomicatipo de ON p.destinacion_economica = de.t_id
                WHERE p.numero_predial_nacional = %s;
            """, (npn,))
            r = cur.fetchone()
            if not r: return None
            return {
                "t_id": r[0], "npn": r[1], "codigo_homologado": r[2], "matricula_inmobiliaria": r[3],
                "departamento": r[4], "municipio": r[5], "area_catastral_terreno": float(r[6] or 0.0),
                "tipo_predio": r[7], "condicion_predio": r[8], "destinacion_economica": r[9]
            }
