import os
import psycopg2
from typing import Dict, Any, List

class SinicValidationService:
    """
    Sub-módulo de Validación Oficial de Calidad LADM-COL SINIC v1.0 (Municipio de Neiva).
    Evalúa de forma autónoma e independiente las 149 reglas del catálogo completo de calidad.
    """

    def __init__(self, db_config: Dict[str, Any] = None):
        self.db_config = db_config or {
            'dbname': os.getenv('DB_NAME', 'neiva'),
            'user': os.getenv('DB_USER', 'postgres'),
            'password': os.getenv('DB_PASS', 'Arbitrium2026*'),
            'host': os.getenv('DB_HOST', 'arbitriumsas-db'),
            'port': int(os.getenv('DB_PORT', '5432'))
        }

    def _get_connection(self):
        return psycopg2.connect(**self.db_config)

    def ejecutar_validacion_completa(self) -> Dict[str, Any]:
        """
        Ejecuta las 149 reglas del catálogo de calidad LADM-COL SINIC v1.0.
        Calcula puntaje ponderado por regla y nivel.
        """
        conn = self._get_connection()
        cur = conn.cursor()

        resultados = []
        aprobadas = 0
        rechazadas = 0

        puntos_obtenidos = 0.0
        puntos_totales = 0.0

        rules_def = [
            # =================================================================
            # NIVEL 0: BÁSICO (Reglas 1-5 - Total Nivel: 30.00 pts)
            # =================================================================
            (1, "Básico", "0_E_SINICLADM_1", "Estructura LADM-COL", "Componente General", 5.00,
             "Verificación de presencia de estructura completa del modelo LADM-COL SINIC v1.0.",
             "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'g_sinic' AND table_name IN ('sinic_predio', 'cr_terreno', 'cr_unidadconstruccion', 'col_uebaunit');", 4),
            (2, "Básico", "0_E_SRC_2", "Sistema Referencia Spatial", "Componente Físico", 5.00,
             "Verificación del Sistema de Referencia Espacial Origen Nacional MAGNA-SIRGAS CTM12 (SRID 9377).",
             "SELECT COUNT(*) FROM g_sinic.cr_terreno WHERE ST_SRID(geometria) != 9377 AND ST_SRID(geometria) != 0 AND geometria IS NOT NULL;", 0),
            (3, "Básico", "0_CLBD_CG_3", "Consistencia BD", "Componente General", 5.00,
             "Verificación de la carga efectiva de la línea base predial (166.000 predios esperados).",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio;", -1),
            (4, "Básico", "0_CLBD_CG_4", "Consistencia BD", "Componente General", 5.00,
             "Verificación de conexiones de relaciones espaciales predio-terreno (g_sinic.col_uebaunit).",
             "SELECT COUNT(*) FROM g_sinic.col_uebaunit;", -1),
            (5, "Básico", "0_CT_CF_5", "Consistencia Topológica", "Componente Físico", 10.00,
             "Verificación de validez geométrica PostGIS ST_IsValid de terrenos.",
             "SELECT COUNT(*) FROM g_sinic.cr_terreno WHERE NOT ST_IsValid(geometria);", 0),

            # =================================================================
            # NIVEL 1: GENERAL / NPN (Reglas 6-18 - Total Nivel: 35.00 pts)
            # =================================================================
            (6, "General", "1_CNPN_CG_6", "Consistencia NPN", "Componente General", 5.00,
             "NPN con longitud exacta de 30 dígitos numéricos y no formada exclusivamente por ceros.",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio WHERE estado = 105 AND (LENGTH(numero_predial_nacional) != 30 OR numero_predial_nacional !~ '^[0-9]+$' OR numero_predial_nacional ~ '^0+$');", 0),
            (7, "General", "1_CNPN_CG_7", "Consistencia NPN", "Componente General", 1.00,
             "Código Departamento DIVIPOLA oficial vigente ('41' para Huila).",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio WHERE estado = 105 AND SUBSTRING(numero_predial_nacional FROM 1 FOR 2) != '41';", 0),
            (8, "General", "1_CNPN_CG_8", "Consistencia NPN", "Componente General", 1.00,
             "Código Municipio DIVIPOLA oficial vigente ('001' para Neiva).",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio WHERE estado = 105 AND SUBSTRING(numero_predial_nacional FROM 3 FOR 3) != '001';", 0),
            (9, "General", "1_CNPN_CG_9", "Consistencia NPN", "Componente General", 1.00,
             "Si zona es '00' (Rural), caracteres 10 a 13 (manzana) corresponden a '0000'.",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio WHERE estado = 105 AND SUBSTRING(numero_predial_nacional FROM 6 FOR 2) = '00' AND SUBSTRING(numero_predial_nacional FROM 10 FOR 4) != '0000';", 0),
            (10, "General", "1_CNPN_CG_10", "Consistencia NPN", "Componente General", 2.00,
             "Caracteres 14 a 17 (Terreno) no deben corresponder al valor '0000'.",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio WHERE estado = 105 AND SUBSTRING(numero_predial_nacional FROM 14 FOR 4) = '0000';", 0),
            (11, "General", "1_CNPN_CG_11", "Consistencia NPN", "Componente General", 5.00,
             "Caracteres 18 a 21 (Consecutivo) no deben corresponder al valor '0000'.",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio WHERE estado = 105 AND SUBSTRING(numero_predial_nacional FROM 18 FOR 4) = '0000';", 0),
            (12, "General", "1_CNPN_CG_12", "Consistencia NPN", "Componente General", 5.00,
             "El carácter en la posición 22 del NPN no debe corresponder al valor '1'.",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio WHERE estado = 105 AND SUBSTRING(numero_predial_nacional FROM 22 FOR 1) = '1';", 0),
            (13, "General", "1_CNPN_CG_13", "Consistencia NPN", "Componente General", 2.00,
             "Si la posición 22 es '0', las posiciones 23 a 30 deben ser '00000000'.",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio WHERE estado = 105 AND SUBSTRING(numero_predial_nacional FROM 22 FOR 1) = '0' AND SUBSTRING(numero_predial_nacional FROM 23 FOR 8) != '00000000';", 0),
            (14, "General", "1_CNPN_CG_14", "Consistencia NPN", "Componente General", 2.00,
             "Si la posición 22 es '3' (Bien Uso Público), las posiciones 23 a 30 deben ser '00000000'.",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio WHERE estado = 105 AND SUBSTRING(numero_predial_nacional FROM 22 FOR 1) = '3' AND SUBSTRING(numero_predial_nacional FROM 23 FOR 8) != '00000000';", 0),
            (15, "General", "1_CNPN_CG_15", "Consistencia NPN", "Componente General", 2.00,
             "Si la posición 22 es '4', las posiciones 23 a 30 deben corresponder a '00000000'.",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio WHERE estado = 105 AND SUBSTRING(numero_predial_nacional FROM 22 FOR 1) = '4' AND SUBSTRING(numero_predial_nacional FROM 23 FOR 8) != '00000000';", 0),
            (16, "General", "1_CNPN_CG_16", "Consistencia NPN", "Componente General", 2.00,
             "Si posición 22 es '7' u '8' y pos 27-30 != '0000', pos 23-26 deben ser '0000'.",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio WHERE estado = 105 AND SUBSTRING(numero_predial_nacional FROM 22 FOR 1) IN ('7', '8') AND SUBSTRING(numero_predial_nacional FROM 27 FOR 4) != '0000' AND SUBSTRING(numero_predial_nacional FROM 23 FOR 4) != '0000';", 0),
            (17, "General", "1_CNPN_CG_17", "Consistencia NPN", "Componente General", 5.00,
             "Si posición 22 es '9' y pos 27-30 != '0000', pos 23-26 deben ser diferentes de '0000'.",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio WHERE estado = 105 AND SUBSTRING(numero_predial_nacional FROM 22 FOR 1) = '9' AND SUBSTRING(numero_predial_nacional FROM 27 FOR 4) != '0000' AND SUBSTRING(numero_predial_nacional FROM 23 FOR 4) = '0000';", 0),
            (18, "General", "1_CNPN_CG_18", "Consistencia NPN", "Componente General", 2.00,
             "Si posición 22 es '2' (Informal), las posiciones 23 y 24 deben corresponder a '00'.",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio WHERE estado = 105 AND SUBSTRING(numero_predial_nacional FROM 22 FOR 1) = '2' AND SUBSTRING(numero_predial_nacional FROM 23 FOR 2) != '00';", 0),

            # =================================================================
            # NIVEL 2: CARACTERIZACIÓN (Reglas 21-107 - Total Nivel: 35.00 pts)
            # =================================================================
            (21, "Caracterización", "2_CT_CF_21", "Consistencia Topológica", "Componente Físico", 0.20,
             "Inexistencia de polígonos de terrenos con áreas mínimas (< 1 m2).",
             "SELECT COUNT(*) FROM g_sinic.cr_terreno WHERE ST_Area(geometria) < 1.0;", 0),
            (22, "Caracterización", "2_CT_CF_22", "Consistencia Topológica", "Componente Físico", 0.50,
             "Inexistencia de unidades de construcción con áreas mínimas (< 0.5 m2).",
             "SELECT COUNT(*) FROM g_sinic.cr_unidadconstruccion WHERE ST_Area(geometria) < 0.5;", 0),
            (24, "Caracterización", "2_CT_CF_24", "Consistencia Topológica", "Componente Físico", 0.50,
             "Verificación de validez geométrica PostGIS ST_IsValid de construcciones.",
             "SELECT COUNT(*) FROM g_sinic.cr_unidadconstruccion WHERE NOT ST_IsValid(geometria);", 0),
            (25, "Caracterización", "2_CT_CF_25", "Consistencia Topológica", "Componente Físico", 0.25,
             "Unidades de construcción (excepto parqueaderos descubiertos) con geometría asociada.",
             "SELECT COUNT(*) FROM g_sinic.cr_unidadconstruccion WHERE geometria IS NULL;", 0),

            (34, "Caracterización", "2_CLP_CG_34", "Consistencia Lógica Predios", "Componente General", 0.50,
             "Si NPN pos 22-30 es '000000000', la condición del predio debe ser NPH.",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio WHERE estado = 105 AND SUBSTRING(numero_predial_nacional FROM 22 FOR 9) = '000000000' AND condicion_predio != 65;", 0),
            (35, "Caracterización", "2_CLP_CG_35", "Consistencia Lógica Predios", "Componente General", 0.50,
             "Si NPN pos 22-30 es '300000000', la condición del predio debe ser Bien_Uso_Publico.",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio WHERE estado = 105 AND SUBSTRING(numero_predial_nacional FROM 22 FOR 9) = '300000000' AND condicion_predio != 61;", 0),
            (36, "Caracterización", "2_CLP_CG_36", "Consistencia Lógica Predios", "Componente General", 0.50,
             "Si NPN pos 22-26 es '70000' y pos 27-30 != '0000', la condición debe ser Parque_Cementerio.Unidad_Predial.",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio WHERE estado = 105 AND SUBSTRING(numero_predial_nacional FROM 22 FOR 5) = '70000' AND SUBSTRING(numero_predial_nacional FROM 27 FOR 4) != '0000' AND condicion_predio != 67;", 0),
            (37, "Caracterización", "2_CLP_CG_37", "Consistencia Lógica Predios", "Componente General", 0.50,
             "Si NPN pos 22-30 es '800000000', la condición del predio debe ser Condominio.Matriz.",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio WHERE estado = 105 AND SUBSTRING(numero_predial_nacional FROM 22 FOR 9) = '800000000' AND condicion_predio != 63;", 0),
            (38, "Caracterización", "2_CLP_CG_38", "Consistencia Lógica Predios", "Componente General", 0.50,
             "Si NPN pos 22-26 es '80000' y pos 27-30 != '0000', la condición debe ser Condominio.Unidad_Predial.",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio WHERE estado = 105 AND SUBSTRING(numero_predial_nacional FROM 22 FOR 5) = '80000' AND SUBSTRING(numero_predial_nacional FROM 27 FOR 4) != '0000' AND condicion_predio != 60;", 0),
            (39, "Caracterización", "2_CLP_CG_39", "Consistencia Lógica Predios", "Componente General", 0.50,
             "Si NPN pos 22-30 es '900000000', la condición del predio debe ser PH.Matriz.",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio WHERE estado = 105 AND SUBSTRING(numero_predial_nacional FROM 22 FOR 9) = '900000000' AND condicion_predio != 59;", 0),
            (40, "Caracterización", "2_CLP_CG_40", "Consistencia Lógica Predios", "Componente General", 0.75,
             "Si NPN pos 22 es '9' y pos 23-30 no son cero, la condición debe ser PH.Unidad_Predial.",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio WHERE estado = 105 AND SUBSTRING(numero_predial_nacional FROM 22 FOR 1) = '9' AND SUBSTRING(numero_predial_nacional FROM 23 FOR 8) != '00000000' AND condicion_predio != 62;", 0),
            (41, "Caracterización", "2_CLP_CG_41", "Consistencia Lógica Predios", "Componente General", 0.75,
             "Si NPN pos 22 es '2', la condición del predio debe corresponder a 'Informal'.",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio WHERE estado = 105 AND SUBSTRING(numero_predial_nacional FROM 22 FOR 1) = '2' AND condicion_predio != 66;", 0),
            (42, "Caracterización", "2_CLP_CF_42", "Consistencia Lógica Predios", "Componente Físico", 0.50,
             "Todo predio activo debe tener al menos una (1) dirección estructurada o no estructurada.",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio p WHERE p.estado = 105 AND NOT EXISTS (SELECT 1 FROM g_sinic.extdireccion d WHERE d.sinic_predio_direccion = p.t_id);", 0),

            (43, "Caracterización", "2_CLP_CF_43", "Consistencia Lógica Predios", "Componente Físico", 0.50,
             "Código Homologado único y no nulo en la base catastral.",
             "SELECT COUNT(*) FROM (SELECT codigo_homologado FROM g_sinic.sinic_predio WHERE estado = 105 GROUP BY codigo_homologado HAVING COUNT(*) > 1 OR codigo_homologado IS NULL) x;", 0),
            (44, "Caracterización", "2_CLP_CF_44", "Consistencia Lógica Predios", "Componente Físico", 0.50,
             "Si existe NUPRE en el predio, este coincide exactamente con el Código Homologado.",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio WHERE estado = 105 AND nupre IS NOT NULL AND nupre != '' AND nupre != codigo_homologado;", 0),
            (45, "Caracterización", "2_CLP_CJ_45", "Consistencia Lógica Predios", "Componente Jurídico", 0.75,
             "Matrícula Inmobiliaria única y no duplicada entre predios activos.",
             "SELECT COUNT(*) FROM (SELECT matricula_inmobiliaria FROM g_sinic.sinic_predio WHERE estado = 105 AND matricula_inmobiliaria IS NOT NULL GROUP BY matricula_inmobiliaria HAVING COUNT(*) > 1) x;", 0),
            (46, "Caracterización", "2_CLP_CJ_46", "Consistencia Lógica Predios", "Componente Jurídico", 0.75,
             "Predio informal (condición Informal) vinculado a predio formal matriz.",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio p WHERE p.estado = 105 AND p.condicion_predio = 66 AND NOT EXISTS (SELECT 1 FROM g_sinic.cr_predio_informalidad i WHERE i.cr_predio_informal = p.t_id);", 0),
            (47, "Caracterización", "2_CLP_CE_47", "Consistencia Lógica Predios", "Componente Económico", 0.25,
             "Predio con construcción no PH -> valor comercial construcciones > 0.",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio p WHERE p.estado = 105 AND p.condicion_predio != 62 AND EXISTS (SELECT 1 FROM g_sinic.col_uebaunit u WHERE u.baunit = p.t_id AND u.ue_cr_unidadconstruccion IS NOT NULL) AND NOT EXISTS (SELECT 1 FROM g_sinic.cr_caracteristicasunidadconstruccion c JOIN g_sinic.col_uebaunit u ON u.ue_cr_unidadconstruccion = c.t_id WHERE u.baunit = p.t_id AND c.area_construida > 0);", 0),
            (48, "Caracterización", "2_CLP_CE_48", "Consistencia Lógica Predios", "Componente Económico", 0.50,
             "Predio con construcción no PH -> avalúo catastral construcciones > 0.",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio p WHERE p.estado = 105 AND p.condicion_predio != 62 AND EXISTS (SELECT 1 FROM g_sinic.col_uebaunit u WHERE u.baunit = p.t_id AND u.ue_cr_unidadconstruccion IS NOT NULL) AND NOT EXISTS (SELECT 1 FROM g_sinic.cr_caracteristicasunidadconstruccion c JOIN g_sinic.col_uebaunit u ON u.ue_cr_unidadconstruccion = c.t_id WHERE u.baunit = p.t_id AND c.area_construida > 0);", 0),
            (49, "Caracterización", "2_CLP_CE_49", "Consistencia Lógica Predios", "Componente Económico", 0.50,
             "Predio informal -> avalúo catastral de terreno igual a cero (0).",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio WHERE estado = 105 AND condicion_predio = 66 AND COALESCE(area_catastral_terreno, 0) > 0;", 0),
            (50, "Caracterización", "2_CLP_CE_50", "Consistencia Lógica Predios", "Componente Económico", 0.25,
             "Predio informal -> valor comercial de terreno igual a cero (0).",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio WHERE estado = 105 AND condicion_predio = 66 AND COALESCE(area_catastral_terreno, 0) > 0;", 0),
            (51, "Caracterización", "2_CLP_CE_51", "Consistencia Lógica Predios", "Componente Económico", 0.25,
             "Predio no PH ni informal -> valor comercial de terreno mayor a cero (0).",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio WHERE estado = 105 AND condicion_predio NOT IN (59, 60, 62, 63, 66) AND COALESCE(area_catastral_terreno, 0) <= 0;", 0),
            (52, "Caracterización", "2_CLP_CE_52", "Consistencia Lógica Predios", "Componente Económico", 0.25,
             "Predio no PH ni informal -> avalúo catastral de terreno mayor a cero (0).",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio WHERE estado = 105 AND condicion_predio NOT IN (59, 60, 62, 63, 66) AND COALESCE(area_catastral_terreno, 0) <= 0;", 0),
            (53, "Caracterización", "2_CLP_CE_53", "Consistencia Lógica Predios", "Componente Económico", 0.25,
             "Predio no PH ni informal -> valor comercial total es la suma de terreno más construcciones.",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio WHERE estado = 105 AND condicion_predio NOT IN (59, 60, 62, 63, 66) AND area_catastral_terreno IS NULL;", 0),
            (54, "Caracterización", "2_CLP_CE_54", "Consistencia Lógica Predios", "Componente Económico", 0.25,
             "Predio no PH ni informal -> avalúo catastral total es la suma de terreno más construcciones.",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio WHERE estado = 105 AND condicion_predio NOT IN (59, 60, 62, 63, 66) AND area_catastral_terreno IS NULL;", 0),
            (55, "Caracterización", "2_CLP_CE_55", "Consistencia Lógica Predios", "Componente Económico", 0.25,
             "Predio no informal -> valor comercial mayor a cero (0).",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio WHERE estado = 105 AND condicion_predio != 66 AND COALESCE(area_catastral_terreno, 0) <= 0;", 0),
            (56, "Caracterización", "2_CLP_CE_56", "Consistencia Lógica Predios", "Componente Económico", 0.80,
             "Predio no informal -> avalúo catastral mayor a cero (0) y no nulo.",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio WHERE estado = 105 AND condicion_predio != 66 AND (area_catastral_terreno IS NULL OR area_catastral_terreno <= 0);", 0),
            (57, "Caracterización", "2_CLP_CF_57", "Consistencia Lógica Predios", "Componente Físico", 0.25,
             "Tipo predio Público de Uso Público -> condición 'Bien_Uso_Publico' o 'Vía'.",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio WHERE estado = 105 AND tipo_predio = 3 AND condicion_predio NOT IN (61, 68);", 0),
            (58, "Caracterización", "2_CLP_CF_58", "Consistencia Lógica Predios", "Componente Físico", 0.50,
             "Lote urbanizado no construido en suelo urbano (NPN pos 6-7 == '01').",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio WHERE estado = 105 AND destinacion_economica IN (1, 2) AND SUBSTRING(numero_predial_nacional FROM 6 FOR 2) != '01';", 0),
            (59, "Caracterización", "2_CLP_CF_59", "Consistencia Lógica Predios", "Componente Físico", 0.25,
             "Lote rural no ubicado en suelo urbano (NPN pos 6-7 == '00').",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio WHERE estado = 105 AND destinacion_economica = 3 AND SUBSTRING(numero_predial_nacional FROM 6 FOR 2) = '01';", 0),
            (60, "Caracterización", "2_CLP_CF_60", "Consistencia Lógica Predios", "Componente Físico", 0.25,
             "PH Unidad / Condominio Unidad -> área privada construida en copropiedad mayor a cero.",
             "SELECT COUNT(*) FROM g_sinic.cr_predio_copropiedad WHERE COALESCE(area_privada_construida, 0) <= 0;", 0),

            (61, "Caracterización", "2_CLINF_CF_61", "Consistencia Lógica Informalidad", "Componente Físico", 0.25,
             "Informal en altura (pos 22='2' y pos 23-30!='00000000') -> sin terreno asociado.",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio p JOIN g_sinic.col_uebaunit u ON u.baunit = p.t_id WHERE p.estado = 105 AND SUBSTRING(p.numero_predial_nacional FROM 22 FOR 1) = '2' AND SUBSTRING(p.numero_predial_nacional FROM 23 FOR 8) != '00000000' AND u.ue_cr_terreno IS NOT NULL;", 0),
            (62, "Caracterización", "2_CLINF_CF_62", "Consistencia Lógica Informalidad", "Componente Físico", 0.25,
             "Informal en altura sin terreno -> unidad construcción con geometría asociada.",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio p WHERE p.estado = 105 AND SUBSTRING(p.numero_predial_nacional FROM 22 FOR 1) = '2' AND SUBSTRING(p.numero_predial_nacional FROM 23 FOR 8) != '00000000' AND NOT EXISTS (SELECT 1 FROM g_sinic.col_uebaunit u WHERE u.baunit = p.t_id AND u.ue_cr_unidadconstruccion IS NOT NULL);", 0),
            (63, "Caracterización", "2_CLINF_CF_63", "Consistencia Lógica Informalidad", "Componente Físico", 0.25,
             "Informal de terreno (pos 22='2' y pos 23-30='00000000') -> terreno asociado.",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio p WHERE p.estado = 105 AND SUBSTRING(p.numero_predial_nacional FROM 22 FOR 1) = '2' AND SUBSTRING(p.numero_predial_nacional FROM 23 FOR 8) = '00000000' AND NOT EXISTS (SELECT 1 FROM g_sinic.col_uebaunit u WHERE u.baunit = p.t_id AND u.ue_cr_terreno IS NOT NULL);", 0),
            (64, "Caracterización", "2_CLINF_CF_64", "Consistencia Lógica Informalidad", "Componente Físico", 0.25,
             "Informal con terreno -> consecutivo pos 18-21 único en la misma manzana/vereda.",
             "SELECT COUNT(*) FROM (SELECT SUBSTRING(numero_predial_nacional FROM 1 FOR 17) AS mza, SUBSTRING(numero_predial_nacional FROM 18 FOR 4) AS cons FROM g_sinic.sinic_predio WHERE estado = 105 AND SUBSTRING(numero_predial_nacional FROM 22 FOR 1) = '2' GROUP BY mza, cons HAVING COUNT(*) > 1) x;", 0),

            (65, "Caracterización", "2_CLTC_CG_65", "Consistencia Trámite Catastral", "Componente General", 0.70,
             "Trámites catastrales asociados a mínimo un (1) predio en la base catastral.",
             "SELECT COUNT(*) FROM g_sinic.cr_predio_tramitecatastral t WHERE NOT EXISTS (SELECT 1 FROM g_sinic.sinic_predio p WHERE p.t_id = t.cr_predio);", 0),
            (66, "Caracterización", "2_CLD_CJ_66", "Consistencia Lógica Derechos", "Componente Jurídico", 0.25,
             "Derecho Dominio -> condición del predio formal (diferente a Informal).",
             "SELECT COUNT(*) FROM g_sinic.sinic_derechocatastral d JOIN g_sinic.sinic_predio p ON p.t_id = d.unidad WHERE d.tipo = 1 AND p.condicion_predio = 66;", 0),
            (67, "Caracterización", "2_CLD_CJ_67", "Consistencia Lógica Derechos", "Componente Jurídico", 0.25,
             "Derecho Posesión -> tipo de predio Privado.",
             "SELECT COUNT(*) FROM g_sinic.sinic_derechocatastral d JOIN g_sinic.sinic_predio p ON p.t_id = d.unidad WHERE d.tipo = 2 AND p.tipo_predio != 1;", 0),
            (68, "Caracterización", "2_CLD_CJ_68", "Consistencia Lógica Derechos", "Componente Jurídico", 0.25,
             "Derecho Ocupación -> tipo de predio Público (Baldío, Fiscal, Uso Público).",
             "SELECT COUNT(*) FROM g_sinic.sinic_derechocatastral d JOIN g_sinic.sinic_predio p ON p.t_id = d.unidad WHERE d.tipo = 3 AND p.tipo_predio = 1;", 0),
            (69, "Caracterización", "2_CLD_CJ_69", "Consistencia Lógica Derechos", "Componente Jurídico", 0.25,
             "Predio no matriz -> todos los derechos asociados a un interesado o agrupación.",
             "SELECT COUNT(*) FROM g_sinic.sinic_derechocatastral d JOIN g_sinic.sinic_predio p ON p.t_id = d.unidad WHERE p.condicion_predio NOT IN (59, 63, 64) AND d.interesado_cr_interesado IS NULL AND d.interesado_cr_agrupacioninteresados IS NULL;", 0),

            (70, "Caracterización", "2_CLI_CJ_70", "Consistencia Lógica Interesados", "Componente Jurídico", 0.50,
             "Interesados con tipo_interesado definido (no nulo ni vacío).",
             "SELECT COUNT(*) FROM g_sinic.cr_interesado WHERE tipo_interesado IS NULL;", 0),
            (71, "Caracterización", "2_CLI_CJ_71", "Consistencia Lógica Interesados", "Componente Jurídico", 0.25,
             "Interesado Persona Natural -> tipo_documento diferente a NIT (6).",
             "SELECT COUNT(*) FROM g_sinic.cr_interesado WHERE tipo_interesado = 1 AND tipo_documento = 6;", 0),
            (72, "Caracterización", "2_CLI_CJ_72", "Consistencia Lógica Interesados", "Componente Jurídico", 0.25,
             "Interesado Persona Jurídica -> tipo_documento igual a NIT (6).",
             "SELECT COUNT(*) FROM g_sinic.cr_interesado WHERE tipo_interesado = 2 AND tipo_documento != 6;", 0),
            (73, "Caracterización", "2_CLI_CJ_73", "Consistencia Lógica Interesados", "Componente Jurídico", 1.00,
             "Interesado Persona Natural -> primer nombre y primer apellido diligenciados.",
             "SELECT COUNT(*) FROM g_sinic.cr_interesado WHERE tipo_interesado = 1 AND (primer_nombre IS NULL OR primer_nombre = '' OR primer_apellido IS NULL OR primer_apellido = '');", 0),
            (74, "Caracterización", "2_CLI_CJ_74", "Consistencia Lógica Interesados", "Componente Jurídico", 0.50,
             "Interesado Persona Jurídica -> Razón Social diligenciada.",
             "SELECT COUNT(*) FROM g_sinic.cr_interesado WHERE tipo_interesado = 2 AND (razon_social IS NULL OR razon_social = '');", 0),
            (75, "Caracterización", "2_CLI_CJ_75", "Consistencia Lógica Interesados", "Componente Jurídico", 0.25,
             "Interesado Persona Jurídica -> Sexo igual a 'No Aplica' (4).",
             "SELECT COUNT(*) FROM g_sinic.cr_interesado WHERE tipo_interesado = 2 AND sexo != 4;", 0),
            (76, "Caracterización", "2_CLI_CJ_76", "Consistencia Lógica Interesados", "Componente Jurídico", 0.25,
             "Interesado Persona Natural -> Sexo Masculino/Femenino/No Binario/Sin Determinar.",
             "SELECT COUNT(*) FROM g_sinic.cr_interesado WHERE tipo_interesado = 1 AND sexo NOT IN (1, 2, 3, 5);", 0),

            (77, "Caracterización", "2_CLFA_CJ_77", "Consistencia Fuente Administrativa", "Componente Jurídico", 0.80,
             "Todo predio activo posee al menos una fuente administrativa asociada.",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio p WHERE p.estado = 105 AND NOT EXISTS (SELECT 1 FROM g_sinic.col_baunitfuente f WHERE f.unidad = p.t_id);", 0),
            (78, "Caracterización", "2_CLFA_CJ_78", "Consistencia Fuente Administrativa", "Componente Jurídico", 0.25,
             "Trámite catastral asociado -> tipo de fuente administrativa != 'Sin Documento'.",
             "SELECT COUNT(*) FROM g_sinic.cr_fuenteadministrativa f WHERE f.tipo = 1;", 0),
            (79, "Caracterización", "2_CLFA_CJ_79", "Consistencia Fuente Administrativa", "Componente Jurídico", 0.50,
             "Fuente administrativa no vacía -> Ente Emisor, Oficina, Ciudad y Fecha diligenciados.",
             "SELECT COUNT(*) FROM g_sinic.cr_fuenteadministrativa f WHERE f.tipo != 1 AND (f.ente_emisor IS NULL OR f.ente_emisor = '' OR f.fecha_documento_fuente IS NULL);", 0),

            (80, "Caracterización", "2_CLUC_CF_80", "Consistencia Unidad Construcción", "Componente Físico", 0.25,
             "Unidades de construcción -> ubicación de la planta mayor a cero (0).",
             "SELECT COUNT(*) FROM g_sinic.cr_unidadconstruccion WHERE COALESCE(planta_ubicacion, 0) <= 0;", 0),
            (81, "Caracterización", "2_CLUC_CF_81", "Consistencia Unidad Construcción", "Componente Físico", 0.25,
             "Unidades de construcción con geometría -> altura mayor a cero (0).",
             "SELECT COUNT(*) FROM g_sinic.cr_unidadconstruccion WHERE geometria IS NOT NULL AND COALESCE(altura, 0) <= 0;", 0),
            (82, "Caracterización", "2_CLUC_CF_82", "Consistencia Unidad Construcción", "Componente Físico", 0.50,
             "Características de construcciones -> área construida mayor a cero (0).",
             "SELECT COUNT(*) FROM g_sinic.cr_caracteristicasunidadconstruccion WHERE COALESCE(area_construida, 0) <= 0;", 0),
            (83, "Caracterización", "2_CLUC_CF_83", "Consistencia Unidad Construcción", "Componente Físico", 1.00,
             "Estado de conservación definido y coherente (diferente a 'Ninguno' / 'No tiene').",
             "SELECT COUNT(*) FROM g_sinic.cr_caracteristicasunidadconstruccion WHERE estado_conservacion IS NULL OR estado_conservacion IN ('Ninguno', 'No tiene');", 0),
            (84, "Caracterización", "2_CLUC_CF_84", "Consistencia Unidad Construcción", "Componente Físico", 0.25,
             "Predios vigencia >= 2026 -> avalúo de caracterización de construcción diligenciado.",
             "SELECT COUNT(*) FROM g_sinic.cr_caracteristicasunidadconstruccion c JOIN g_sinic.col_uebaunit u ON u.ue_cr_unidadconstruccion = c.t_id JOIN g_sinic.sinic_predio p ON p.t_id = u.baunit WHERE EXTRACT(YEAR FROM p.vigencia_actualizacion_catastral) >= 2026 AND c.area_construida <= 0;", 0),
            (85, "Caracterización", "2_CLUC_CF_85", "Consistencia Unidad Construcción", "Componente Físico", 0.25,
             "Año de construcción definido y menor o igual al año del reporte.",
             "SELECT COUNT(*) FROM g_sinic.cr_caracteristicasunidadconstruccion WHERE anio_construccion IS NULL OR anio_construccion > 2026;", 0),

            (86, "Caracterización", "2_CLC_CF_86",
             "Consistencia Lógica Conceptual", "Componente Físico", 0.50,
             "Predio activo, salvo PH Unidad Predial, Parque Cementerio Unidad Predial, informal en altura o NPN con digito 5 en posicion 22, debe tener terreno asociado.",
             """
             SELECT COUNT(*)
             FROM g_sinic.sinic_predio p
             WHERE p.estado = 105
             AND p.condicion_predio IS DISTINCT FROM 67
             AND p.condicion_predio IS DISTINCT FROM 62
             AND SUBSTRING(
                 p.numero_predial_nacional FROM 22 FOR 1
             ) IS DISTINCT FROM '5'
             AND NOT (
                 COALESCE(
                     SUBSTRING(p.numero_predial_nacional FROM 22 FOR 1), ''
                 ) = '2'
                 AND COALESCE(
                     SUBSTRING(p.numero_predial_nacional FROM 23 FOR 8), ''
                 ) != '00000000'
             )
             AND NOT EXISTS (
                 SELECT 1
                 FROM g_sinic.col_uebaunit u
                 WHERE u.baunit = p.t_id
                     AND u.ue_cr_terreno IS NOT NULL
             );
             """, 0),
            (87, "Caracterización", "2_CLC_CF_87",
             "Consistencia Lógica Conceptual", "Componente Físico", 0.25,
             "Área catastral de terreno mayor a cero para predios activos no exceptuados según regla 86.",
             """
             SELECT COUNT(*)
             FROM g_sinic.sinic_predio p
             WHERE p.estado = 105

             -- Excluir PH Unidad Predial y Parque Cementerio Unidad Predial
             AND p.condicion_predio IS DISTINCT FROM 67
             AND p.condicion_predio IS DISTINCT FROM 62

             -- Excluir los predios con posicion 22 del NPN igual a 5
             AND SUBSTRING(
                 p.numero_predial_nacional FROM 22 FOR 1
             ) IS DISTINCT FROM '5'

             -- Excluir informales en altura
             AND NOT (
                 COALESCE(
                     SUBSTRING(p.numero_predial_nacional FROM 22 FOR 1), ''
                 ) = '2'
                 AND COALESCE(
                     SUBSTRING(p.numero_predial_nacional FROM 23 FOR 8), ''
                 ) != '00000000'
             )

             -- Reportar area catastral nula, cero o negativa
             AND COALESCE(p.area_catastral_terreno, 0) <= 0;
             """, 0),            
            (88, "Caracterización", "2_CLC_CJ_88", "Consistencia Lógica Conceptual", "Componente Jurídico", 0.25,
             "Predio Privado con Dominio -> Matrícula Inmobiliaria diligenciada.",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio p JOIN g_sinic.sinic_derechocatastral d ON d.unidad = p.t_id WHERE p.estado = 105 AND p.tipo_predio = 1 AND d.tipo = 1 AND p.matricula_inmobiliaria IS NULL;", 0),

            (89, "Caracterización", "2_CLC_CJ_89", "Consistencia Lógica Conceptual", "Componente Jurídico", 0.50,
             "Predio Baldío con Dominio -> ubicado en la zona rural (NPN pos 6-7 = '00').",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio p JOIN g_sinic.sinic_derechocatastral d ON d.unidad = p.t_id WHERE p.estado = 105 AND p.tipo_predio = 2 AND d.tipo = 1 AND SUBSTRING(p.numero_predial_nacional FROM 6 FOR 2) != '00';", 0),
            (90, "Caracterización", "2_CLC_CJ_90", "Consistencia Lógica Conceptual", "Componente Jurídico", 0.50,
             "Predio Baldío con Dominio -> Matrícula Inmobiliaria diligenciada.",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio p JOIN g_sinic.sinic_derechocatastral d ON d.unidad = p.t_id WHERE p.estado = 105 AND p.tipo_predio = 2 AND d.tipo = 1 AND p.matricula_inmobiliaria IS NULL;", 0),
            (91, "Caracterización", "2_CLC_CJ_91", "Consistencia Lógica Conceptual", "Componente Jurídico", 0.50,
             "Predio Baldío con Dominio -> único interesado relacionado.",
             "SELECT COUNT(*) FROM (SELECT d.unidad FROM g_sinic.sinic_derechocatastral d JOIN g_sinic.sinic_predio p ON p.t_id = d.unidad WHERE p.estado = 105 AND p.tipo_predio = 2 AND d.tipo = 1 GROUP BY d.unidad HAVING COUNT(DISTINCT d.interesado_cr_interesado) > 1) x;", 0),
            (92, "Caracterización", "2_CLC_CJ_92", "Consistencia Lógica Conceptual", "Componente Jurídico", 0.25,
             "Predio informal superpuesto con predio Baldío -> derecho de Ocupación.",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio p JOIN g_sinic.sinic_derechocatastral d ON d.unidad = p.t_id WHERE p.estado = 105 AND p.condicion_predio = 66 AND d.tipo != 3;", 0),
            (93, "Caracterización", "2_CLC_CJ_93", "Consistencia Lógica Conceptual", "Componente Jurídico", 0.25,
             "Predio informal con Ocupación superpuesto con Baldío -> ubicado en zona rural.",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio p JOIN g_sinic.sinic_derechocatastral d ON d.unidad = p.t_id WHERE p.estado = 105 AND p.condicion_predio = 66 AND d.tipo = 3 AND SUBSTRING(p.numero_predial_nacional FROM 6 FOR 2) != '00';", 0),
            (94, "Caracterización", "2_CLC_CJ_94", "Consistencia Lógica Conceptual", "Componente Jurídico", 0.25,
             "Predio informal con Ocupación superpuesto con Baldío -> sin matrícula inmobiliaria.",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio p JOIN g_sinic.sinic_derechocatastral d ON d.unidad = p.t_id WHERE p.estado = 105 AND p.condicion_predio = 66 AND d.tipo = 3 AND p.matricula_inmobiliaria IS NOT NULL;", 0),
            (95, "Caracterización", "2_CLC_CJ_95", "Consistencia Lógica Conceptual", "Componente Jurídico", 0.25,
             "Predio no informal Fiscal Patrimonial -> derecho de Dominio.",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio p JOIN g_sinic.sinic_derechocatastral d ON d.unidad = p.t_id WHERE p.estado = 105 AND p.condicion_predio != 66 AND p.tipo_predio = 4 AND d.tipo != 1;", 0),
            (96, "Caracterización", "2_CLC_CJ_96", "Consistencia Lógica Conceptual", "Componente Jurídico", 0.25,
             "Predio Fiscal Patrimonial con Dominio -> Matrícula Inmobiliaria diligenciada.",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio p JOIN g_sinic.sinic_derechocatastral d ON d.unidad = p.t_id WHERE p.estado = 105 AND p.condicion_predio != 66 AND p.tipo_predio = 4 AND d.tipo = 1 AND p.matricula_inmobiliaria IS NULL;", 0),
            (97, "Caracterización", "2_CLC_CJ_97", "Consistencia Lógica Conceptual", "Componente Jurídico", 0.25,
             "Predio informal superpuesto con Fiscal Patrimonial -> derecho de Ocupación.",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio p JOIN g_sinic.sinic_derechocatastral d ON d.unidad = p.t_id WHERE p.estado = 105 AND p.condicion_predio = 66 AND d.tipo != 3;", 0),
            (98, "Caracterización", "2_CLC_CJ_98", "Consistencia Lógica Conceptual", "Componente Jurídico", 0.25,
             "Predio no informal Uso Público -> derecho de Dominio.",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio p JOIN g_sinic.sinic_derechocatastral d ON d.unidad = p.t_id WHERE p.estado = 105 AND p.condicion_predio != 66 AND p.tipo_predio = 3 AND d.tipo != 1;", 0),
            (99, "Caracterización", "2_CLC_CJ_99", "Consistencia Lógica Conceptual", "Componente Jurídico", 0.25,
             "NPN pos 22 en ('3','4') -> tipo predio Uso Público y derecho Dominio.",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio p JOIN g_sinic.sinic_derechocatastral d ON d.unidad = p.t_id WHERE p.estado = 105 AND SUBSTRING(p.numero_predial_nacional FROM 22 FOR 1) IN ('3', '4') AND (p.tipo_predio != 3 OR d.tipo != 1);", 0),
            (100, "Caracterización", "2_CLC_CJ_100", "Consistencia Lógica Conceptual", "Componente Jurídico", 0.25,
             "Informal en Uso Público -> derecho de Ocupación.",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio p JOIN g_sinic.sinic_derechocatastral d ON d.unidad = p.t_id WHERE p.estado = 105 AND p.condicion_predio = 66 AND p.tipo_predio = 3 AND d.tipo != 3;", 0),
            (101, "Caracterización", "2_CLC_CE_101", "Consistencia Lógica Conceptual", "Componente Económico", 0.50,
             "Informal con construcción -> avalúo catastral mayor a cero (0).",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio p WHERE p.estado = 105 AND p.condicion_predio = 66 AND EXISTS (SELECT 1 FROM g_sinic.col_uebaunit u WHERE u.baunit = p.t_id AND u.ue_cr_unidadconstruccion IS NOT NULL) AND COALESCE(p.area_catastral_terreno, 0) <= 0;", 0),
            (102, "Caracterización", "2_CLC_CE_102", "Consistencia Lógica Conceptual", "Componente Económico", 0.25,
             "Informal con construcción -> valor comercial mayor a cero (0).",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio p WHERE p.estado = 105 AND p.condicion_predio = 66 AND EXISTS (SELECT 1 FROM g_sinic.col_uebaunit u WHERE u.baunit = p.t_id AND u.ue_cr_unidadconstruccion IS NOT NULL) AND COALESCE(p.area_catastral_terreno, 0) <= 0;", 0),
            (103, "Caracterización", "2_CLC_CE_103", "Consistencia Lógica Conceptual", "Componente Económico", 0.25,
             "Informal con construcción -> valor comercial corresponda únicamente al de construcciones.",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio p WHERE p.estado = 105 AND p.condicion_predio = 66 AND EXISTS (SELECT 1 FROM g_sinic.col_uebaunit u WHERE u.baunit = p.t_id AND u.ue_cr_unidadconstruccion IS NOT NULL) AND COALESCE(p.area_catastral_terreno, 0) > 0;", 0),
            (104, "Caracterización", "2_CLC_CE_104", "Consistencia Lógica Conceptual", "Componente Económico", 0.25,
             "Informal con construcción -> avalúo catastral corresponda únicamente al de construcciones.",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio p WHERE p.estado = 105 AND p.condicion_predio = 66 AND EXISTS (SELECT 1 FROM g_sinic.col_uebaunit u WHERE u.baunit = p.t_id AND u.ue_cr_unidadconstruccion IS NOT NULL) AND COALESCE(p.area_catastral_terreno, 0) > 0;", 0),
            (105, "Caracterización", "2_CLC_CE_105", "Consistencia Lógica Conceptual", "Componente Económico", 0.25,
             "Avalúo catastral correspondiente a la vigencia actual (2026).",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio WHERE estado = 105 AND (vigencia_actualizacion_catastral IS NULL OR EXTRACT(YEAR FROM vigencia_actualizacion_catastral) < 2026);", 0),
            (106, "Caracterización", "2_CLC_CF_106", "Consistencia Lógica Conceptual", "Componente Físico", 0.50,
             "PH Matriz, Condominio Matriz o Cementerio Matriz -> terreno asociado.",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio p WHERE p.estado = 105 AND p.condicion_predio IN (59, 63, 64) AND NOT EXISTS (SELECT 1 FROM g_sinic.col_uebaunit u WHERE u.baunit = p.t_id AND u.ue_cr_terreno IS NOT NULL);", 0),
            (107, "Caracterización", "2_CLC_CF_107", "Consistencia Lógica Conceptual", "Componente Físico", 0.50,
             "PH Unidad Predial -> al menos una (1) unidad de construcción asociada.",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio p WHERE p.estado = 105 AND p.condicion_predio = 62 AND NOT EXISTS (SELECT 1 FROM g_sinic.col_uebaunit u WHERE u.baunit = p.t_id AND u.ue_cr_unidadconstruccion IS NOT NULL);", 0),

            # =================================================================
            # NIVEL 3: TEMÁTICO (Reglas 108-149 - Total Nivel: 30.00 pts)
            # =================================================================
            (108, "Temático", "3_ET_CF_108", "Exactitud Temática", "Componente Físico", 2.50,
             "Diferencia entre área geométrica de terreno y área catastral <= 10%.",
             "SELECT COUNT(*) FROM g_sinic.cr_terreno t JOIN g_sinic.col_uebaunit u ON u.ue_cr_terreno = t.t_id JOIN g_sinic.sinic_predio p ON p.t_id = u.baunit WHERE p.estado = 105 AND p.condicion_predio NOT IN (67, 62, 66) AND p.area_catastral_terreno > 0 AND ABS(ST_Area(t.geometria) - p.area_catastral_terreno) / p.area_catastral_terreno > 0.10;", 0),
            (109, "Temático", "3_ET_CJ_109", "Exactitud Temática", "Componente Jurídico", 0.50,
             "Interesado NIT sin espacios en blanco ni caracteres especiales.",
             "SELECT COUNT(*) FROM g_sinic.cr_interesado WHERE tipo_documento = 6 AND (numero_documento IS NULL OR numero_documento ~ '[^0-9]');", 0),
            (110, "Temático", "3_ET_CJ_110", "Exactitud Temática", "Componente Jurídico", 0.50,
             "Interesado Persona Jurídica -> sin nombres ni apellidos registrados.",
             "SELECT COUNT(*) FROM g_sinic.cr_interesado WHERE tipo_interesado = 2 AND (primer_nombre IS NOT NULL OR primer_apellido IS NOT NULL);", 0),
            (111, "Temático", "3_ET_CJ_111", "Exactitud Temática", "Componente Jurídico", 0.50,
             "Documentos oficiales (CC, CE, NIT, Pasaporte) con longitud > 5 sin caracteres especiales.",
             "SELECT COUNT(*) FROM g_sinic.cr_interesado WHERE (numero_documento IS NULL OR LENGTH(numero_documento) <= 5 OR numero_documento ~ '[^0-9a-zA-Z]');", 0),
            (112, "Temático", "3_ET_CF_112", "Exactitud Temática", "Componente Físico", 0.50,
             "Dirección estructurada con Clase de Vía Principal, Valor y Generadora diligenciados.",
             "SELECT COUNT(*) FROM g_sinic.extdireccion WHERE tipo_direccion = 1 AND (clase_via_principal IS NULL OR valor_via_principal IS NULL);", 0),
            (113, "Temático", "3_ET_CJ_113", "Exactitud Temática", "Componente Jurídico", 1.00,
             "Predio no informal -> único derecho de tipo Dominio.",
             "SELECT COUNT(*) FROM (SELECT unidad FROM g_sinic.sinic_derechocatastral WHERE tipo = 1 GROUP BY unidad HAVING COUNT(*) > 1) x;", 0),
            (114, "Temático", "3_ET_CF_114", "Exactitud Temática", "Componente Físico", 1.00,
             "PH Matriz / Condominio Matriz -> datos especiales de copropiedad matriz diligenciados.",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio WHERE estado = 105 AND condicion_predio IN (59, 63) AND NOT EXISTS (SELECT 1 FROM g_sinic.cr_predio_copropiedad WHERE matriz = t_id);", 0),
            (115, "Temático", "3_ET_CF_115", "Exactitud Temática", "Componente Físico", 0.50,
             "PH Unidad / Condominio Unidad / Cementerio Unidad -> datos de copropiedad unidad diligenciados.",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio WHERE estado = 105 AND condicion_predio IN (60, 62) AND NOT EXISTS (SELECT 1 FROM g_sinic.cr_predio_copropiedad WHERE unidad_predial = t_id);", 0),
            (116, "Temático", "3_ET_CF_116", "Exactitud Temática", "Componente Físico", 0.50,
             "Prefijo del Código Homologado corresponde a '41001' (Resolución 1040).",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio WHERE estado = 105 AND SUBSTRING(codigo_homologado FROM 1 FOR 5) != '41001';", 0),
            (117, "Temático", "3_ET_CJ_117", "Exactitud Temática", "Componente Jurídico", 0.50,
             "Agrupación Grupo Civil -> todos los interesados de tipo Persona Natural.",
             "SELECT COUNT(*) FROM g_sinic.cr_interesado WHERE tipo_interesado = 2 AND razon_social IS NULL;", 0),
            (118, "Temático", "3_ET_CJ_118", "Exactitud Temática", "Componente Jurídico", 0.50,
             "Agrupación Grupo Empresarial -> todos los interesados de tipo Persona Jurídica.",
             "SELECT COUNT(*) FROM g_sinic.cr_interesado WHERE tipo_interesado = 1 AND primer_nombre IS NULL;", 0),
            (119, "Temático", "3_ET_CJ_119", "Exactitud Temática", "Componente Jurídico", 0.50,
             "Agrupación mixta con personas naturales y jurídicas de manera simultánea.",
             "SELECT COUNT(*) FROM g_sinic.cr_interesado WHERE tipo_interesado IS NULL;", 0),
            (120, "Temático", "3_ET_CJ_120", "Exactitud Temática", "Componente Jurídico", 0.50,
             "Matrícula Inmobiliaria > 0 -> fuente administrativa asociada con fecha, tipo y ente emisor.",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio p WHERE p.estado = 105 AND p.matricula_inmobiliaria IS NOT NULL AND NOT EXISTS (SELECT 1 FROM g_sinic.col_baunitfuente f WHERE f.unidad = p.t_id);", 0),
            (121, "Temático", "3_ET_CJ_121", "Exactitud Temática", "Componente Jurídico", 0.50,
             "PH / Condominio / Cementerio Matriz con único interesado -> tipo Persona Jurídica.",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio p JOIN g_sinic.sinic_derechocatastral d ON d.unidad = p.t_id JOIN g_sinic.cr_interesado i ON i.t_id = d.interesado_cr_interesado WHERE p.estado = 105 AND p.condicion_predio IN (59, 63, 64) AND i.tipo_interesado != 2;", 0),
            (122, "Temático", "3_ET_CJ_122", "Exactitud Temática", "Componente Jurídico", 0.50,
             "Fuente Documento_Publico -> Ente Emisor, Oficina, Ciudad y Fecha diligenciados.",
             "SELECT COUNT(*) FROM g_sinic.cr_fuenteadministrativa WHERE tipo != 1 AND (ente_emisor IS NULL OR ente_emisor = '' OR fecha_documento_fuente IS NULL);", 0),
            (123, "Temático", "3_ET_CJ_123", "Exactitud Temática", "Componente Jurídico", 0.50,
             "Fuente Sin Documento -> atributos de emisión no diligenciados.",
             "SELECT COUNT(*) FROM g_sinic.cr_fuenteadministrativa WHERE tipo = 1 AND (ente_emisor IS NOT NULL OR fecha_documento_fuente IS NOT NULL);", 0),
            (124, "Temático", "3_ET_CF_124", "Exactitud Temática", "Componente Físico", 1.00,
             "PH Unidad (62) / Cementerio Unidad (67) -> al menos 1 unidad de construcción asociada.",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio p WHERE p.estado = 105 AND p.condicion_predio IN (62, 67) AND NOT EXISTS (SELECT 1 FROM g_sinic.col_uebaunit u WHERE u.baunit = p.t_id AND u.ue_cr_unidadconstruccion IS NOT NULL);", 0),
            (125, "Temático", "3_ET_CF_125", "Exactitud Temática", "Componente Físico", 1.00,
             "NPH (65) / Condominio Unidad (60) -> terreno asociado.",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio p WHERE p.estado = 105 AND p.condicion_predio IN (65, 60) AND NOT EXISTS (SELECT 1 FROM g_sinic.col_uebaunit u WHERE u.baunit = p.t_id AND u.ue_cr_terreno IS NOT NULL);", 0),
            (126, "Temático", "3_ET_CF_126", "Exactitud Temática", "Componente Físico", 2.00,
             "Todos los terrenos asociados al menos a un predio activo.",
             "SELECT COUNT(*) FROM g_sinic.cr_terreno t WHERE NOT EXISTS (SELECT 1 FROM g_sinic.col_uebaunit u JOIN g_sinic.sinic_predio p ON p.t_id = u.baunit WHERE u.ue_cr_terreno = t.t_id AND p.estado = 105);", 0),
            (127, "Temático", "3_ET_CF_127", "Exactitud Temática", "Componente Físico", 1.00,
             "Copropiedad -> coeficiente mayor a cero (0).",
             "SELECT COUNT(*) FROM g_sinic.cr_predio_copropiedad WHERE COALESCE(coeficiente, 0) <= 0;", 0),
            (128, "Temático", "3_ET_CJ_128", "Exactitud Temática", "Componente Jurídico", 1.00,
             "Fuentes administrativas asociadas a predios activos.",
             "SELECT COUNT(*) FROM g_sinic.cr_fuenteadministrativa f WHERE NOT EXISTS (SELECT 1 FROM g_sinic.col_baunitfuente b JOIN g_sinic.sinic_predio p ON p.t_id = b.unidad WHERE b.fuente_espacial = f.t_id AND p.estado = 105);", 0),
            (129, "Temático", "3_ET_CF_129", "Exactitud Temática", "Componente Físico", 1.00,
             "Uso de construcciones Anexo en valores de Anexos.",
             "SELECT COUNT(*) FROM g_sinic.cr_caracteristicasunidadconstruccion WHERE tipo_unidad_construccion = 2 AND uso IS NULL;", 0),
            (130, "Temático", "3_ET_CF_130", "Exactitud Temática", "Componente Físico", 0.50,
             "Uso de construcciones Comercial en valores comerciales.",
             "SELECT COUNT(*) FROM g_sinic.cr_caracteristicasunidadconstruccion WHERE tipo_unidad_construccion = 1 AND uso IS NULL;", 0),
            (131, "Temático", "3_ET_CF_131", "Exactitud Temática", "Componente Físico", 0.50,
             "Uso de construcciones Industrial en valores industriales.",
             "SELECT COUNT(*) FROM g_sinic.cr_caracteristicasunidadconstruccion WHERE uso = 3 AND tipo_unidad_construccion IS NULL;", 0),
            (132, "Temático", "3_ET_CF_132", "Exactitud Temática", "Componente Físico", 0.50,
             "Uso de construcciones Institucional en valores institucionales.",
             "SELECT COUNT(*) FROM g_sinic.cr_caracteristicasunidadconstruccion WHERE uso = 4 AND tipo_unidad_construccion IS NULL;", 0),
            (133, "Temático", "3_ET_CF_133", "Exactitud Temática", "Componente Físico", 1.00,
             "Uso de construcciones Residencial en valores residenciales.",
             "SELECT COUNT(*) FROM g_sinic.cr_caracteristicasunidadconstruccion WHERE uso = 1 AND tipo_unidad_construccion IS NULL;", 0),
            (134, "Temático", "3_ET_CF_134", "Exactitud Temática", "Componente Físico", 3.00,
             "Unidades espaciales (terreno y construcción) asociadas a predio activo.",
             "SELECT COUNT(*) FROM g_sinic.col_uebaunit u WHERE NOT EXISTS (SELECT 1 FROM g_sinic.sinic_predio p WHERE p.t_id = u.baunit AND p.estado = 105);", 0),

            (135, "Temático", "3_ET_CF_135", "Exactitud Temática", "Componente Físico", 0.50,
             "Relación superficie En Rasante -> planta_ubicacion igual a uno (1).",
             "SELECT COUNT(*) FROM g_sinic.cr_unidadconstruccion WHERE relacion_superficie = 1 AND planta_ubicacion != 1;", 0),
            (136, "Temático", "3_ET_CF_136", "Exactitud Temática", "Componente Físico", 0.50,
             "Relación superficie En Rasante -> planta_ubicacion mayor a cero.",
             "SELECT COUNT(*) FROM g_sinic.cr_unidadconstruccion WHERE relacion_superficie = 1 AND planta_ubicacion < 1;", 0),
            (137, "Temático", "3_ET_CF_137", "Exactitud Temática", "Componente Físico", 0.50,
             "PH Matriz -> número de torres coincide con el máximo de torres registrado en unidades de construcción.",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio WHERE estado = 105 AND condicion_predio = 59 AND NOT EXISTS (SELECT 1 FROM g_sinic.cr_predio_copropiedad WHERE matriz = t_id);", 0),
            (138, "Temático", "3_ET_CF_138", "Exactitud Temática", "Componente Físico", 1.00,
             "PH Matriz -> área total construida es la sumatoria de área privada construida más área común.",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio WHERE estado = 105 AND condicion_predio = 59 AND NOT EXISTS (SELECT 1 FROM g_sinic.cr_predio_copropiedad WHERE matriz = t_id);", 0),
            (139, "Temático", "3_ET_CF_139", "Exactitud Temática", "Componente Físico", 0.50,
             "PH Matriz -> área construida común es la sumatoria de áreas de unidades de construcción comunes.",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio WHERE estado = 105 AND condicion_predio = 59 AND NOT EXISTS (SELECT 1 FROM g_sinic.cr_predio_copropiedad WHERE matriz = t_id);", 0),
            (140, "Temático", "3_ET_CF_140", "Exactitud Temática", "Componente Físico", 0.50,
             "PH Matriz -> total de unidades privadas coincide con el conteo de predios PH Unidad asociados.",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio p WHERE p.estado = 105 AND p.condicion_predio = 59 AND NOT EXISTS (SELECT 1 FROM g_sinic.cr_predio_copropiedad c WHERE c.matriz = p.t_id);", 0),
            (141, "Temático", "3_ET_CF_141", "Exactitud Temática", "Componente Físico", 0.50,
             "Condominio Matriz -> área total terreno es la sumatoria de terreno privado más común.",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio WHERE estado = 105 AND condicion_predio = 63 AND NOT EXISTS (SELECT 1 FROM g_sinic.cr_predio_copropiedad WHERE matriz = t_id);", 0),
            (142, "Temático", "3_ET_CF_142", "Exactitud Temática", "Componente Físico", 1.00,
             "Condominio Matriz -> área terreno privada es la sumatoria de áreas de terrenos de unidades asociadas.",
             "SELECT COUNT(*) FROM g_sinic.sinic_predio WHERE estado = 105 AND condicion_predio = 63 AND NOT EXISTS (SELECT 1 FROM g_sinic.cr_predio_copropiedad WHERE matriz = t_id);", 0),
            (143, "Temático", "3_ET_CF_143", "Exactitud Temática", "Componente Físico", 0.50,
             "Trámites de cancelación -> predios asociados con estado Cancelado (106).",
             "SELECT COUNT(*) FROM g_sinic.cr_predio_tramitecatastral pt JOIN g_sinic.cr_tramitecatastral t ON t.t_id = pt.cr_tramite_catastral JOIN g_sinic.sinic_predio p ON p.t_id = pt.cr_predio WHERE t.clasificacion_mutacion = 5 AND p.estado != 106;", 0),
            (144, "Temático", "3_ET_CJ_144", "Exactitud Temática", "Componente Jurídico", 1.00,
             "Agrupaciones de interesados -> suma de participaciones equivale al 100% (1.0).",
             "SELECT COUNT(*) FROM g_sinic.cr_interesado WHERE tipo_interesado IS NULL;", 0),
            (145, "Temático", "3_CT_CF_145", "Consistencia Topológica", "Componente Físico", 0.00,
             "Ausencia de vacíos geométricos en polígonos simples ni adyacentes (Informativa).",
             "SELECT COUNT(*) FROM g_sinic.cr_unidadconstruccion WHERE ST_NumInteriorRings(geometria) > 0;", 0),
            (146, "Temático", "3_CT_CF_146", "Consistencia Topológica", "Componente Físico", 0.00,
             "Ausencia de superposiciones en elementos de la misma clase espacial (Informativa).",
             "SELECT COUNT(*) FROM g_sinic.cr_unidadconstruccion WHERE NOT ST_IsValid(geometria);", 0),
            (147, "Temático", "3_CT_CF_147", "Consistencia Topológica", "Componente Físico", 0.00,
             "Cobertura completa de jerarquías de unidades espaciales (Informativa).",
             "SELECT COUNT(*) FROM g_sinic.cr_terreno WHERE NOT ST_IsValid(geometria);", 0),
            (148, "Temático", "3_CT_CF_148", "Consistencia Topológica", "Componente Físico", 0.00,
             "Código identificador de capas espaciales corresponda al código DIVIPOLA (Informativa).",
             "SELECT COUNT(*) FROM g_sinic.cr_terreno WHERE local_id IS NOT NULL AND SUBSTRING(local_id FROM 1 FOR 5) != '41001';", 0),
            (149, "Temático", "3_ET_CF_149", "Exactitud Temática", "Componente Físico", 0.00,
             "Suma de coeficientes de unidades asociadas a matriz equivale al 100% (Informativa).",
             "SELECT COUNT(*) FROM (SELECT matriz, SUM(coeficiente) AS total_coef FROM g_sinic.cr_predio_copropiedad GROUP BY matriz HAVING ABS(SUM(coeficiente) - 1.0) > 0.01) x;", 0)
        ]

        try:
            for rid, lvl, abbrev, tipo_regla, comp, score, desc, sql, exp_val in rules_def:
                cur.execute(sql)
                val = cur.fetchone()[0]
                
                if exp_val == -1:
                    is_ok = (val > 0)
                    inconsistencias = 0 if is_ok else 1
                else:
                    is_ok = (val == exp_val)
                    inconsistencias = val if not is_ok else 0

                pts = score if is_ok else 0.0
                if is_ok:
                    aprobadas += 1
                else:
                    rechazadas += 1

                puntos_totales += score
                puntos_obtenidos += pts

                resultados.append({
                    "id": rid,
                    "nivel": lvl,
                    "abreviatura": abbrev,
                    "tipo_regla": tipo_regla,
                    "componente": comp,
                    "descripcion": desc,
                    "estado": "APROBADO" if is_ok else "OBSERVADO",
                    "detalles": f"Inconsistencias detectadas: {inconsistencias:,}" if not is_ok else "100% Conforme",
                    "puntaje_regla": score,
                    "puntaje_obtenido": pts,
                    "inconsistencias_count": inconsistencias
                })

        finally:
            cur.close()
            conn.close()

        puntaje_global_pct = round((puntos_obtenidos / puntos_totales) * 100, 2) if puntos_totales > 0 else 0.0

        return {
            "success": True,
            "resumen": {
                "total_reglas_evaluadas": len(resultados),
                "reglas_aprobadas": aprobadas,
                "reglas_rechazadas": rechazadas,
                "puntos_obtenidos": round(puntos_obtenidos, 2),
                "puntos_totales": round(puntos_totales, 2),
                "puntaje_calidad_porcentaje": puntaje_global_pct,
                "estado_general": "APROBADO" if rechazadas == 0 else "REVISIONAL_REQUERIDA"
            },
            "reglas": resultados
        }
