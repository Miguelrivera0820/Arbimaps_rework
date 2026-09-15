import logging
from typing import List, Optional
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from psycopg2.extras import RealDictCursor

from routers.auth import (
    get_current_tenant,
    get_current_user,
    get_user_role,
    normalize_role,
)
from tenants import TenantContext, get_tenant_db_connection

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/predios-generador", tags=["predios-generador"])

# =========================================================
# MODELOS DE ENTRADA Y SALIDA
# =========================================================
class GenerarNpnRequest(BaseModel):
    predio_matriz: str = Field(..., description="NPN de 30 dígitos o identificador del predio matriz de referencia")
    cantidad: int = Field(1, ge=1, le=500, description="Cantidad de nuevos números prediales a generar")
    tipo_mutacion: str = Field("DESENGLOBE", description="Tipo de trámite: DESENGLOBE, PH, MEJORA, SEGREGACION")
    condicion_propiedad: Optional[str] = Field(None, description="Condición de propiedad (00=NPH, 01-89=PH, 88=Mejora, 99=Bien común)")
    edificio: Optional[str] = Field(None, description="Edificio o Torre (2 dígitos, por defecto '00')")
    piso: Optional[str] = Field(None, description="Piso (2 dígitos, por defecto '00')")
    consecutivo_tramite: Optional[str] = Field(None, description="Identificador o radicado del trámite")
    observaciones: Optional[str] = Field(None, description="Notas u observaciones adicionales")

class ItemPredioGenerado(BaseModel):
    id_inventario: int
    codigo_homologado: str
    numero_predial: str
    departamento: str
    municipio: str
    sector: str
    comuna: str
    barrio: str
    manzana: str
    terreno: str
    condicion: str
    edificio: str
    piso: str
    unidad: str
    estado: str
    fecha_reserva: str

class GenerarNpnResponse(BaseModel):
    success: bool
    cantidad_generada: int
    predio_matriz_base: str
    consecutivo_tramite: Optional[str]
    items: List[ItemPredioGenerado]

class LiberarInactivasRequest(BaseModel):
    dias_antiguedad: int = Field(30, description="Días de inactividad para considerar la reserva huérfana (por defecto 30)")

class LiberarHomologadosRequest(BaseModel):
    codigos: List[str] = Field(..., description="Lista de códigos homologados a liberar/desmarcar de la reserva")

class AsignarHomologadoExistenteRequest(BaseModel):
    numeros_prediales: List[str] = Field(..., description="Lista de números prediales de 30 dígitos existentes")
    consecutivo_tramite: Optional[str] = Field(None, description="Identificador o radicado del trámite")
    observaciones: Optional[str] = Field(None, description="Notas u observaciones adicionales")

class ItemPredioExistenteAsignado(BaseModel):
    id_inventario: Optional[int] = None
    codigo_homologado: str
    numero_predial: str
    estado: str
    es_nueva_reserva: bool
    origen_base: str
    fecha_reserva: str

class AsignarHomologadoExistenteResponse(BaseModel):
    success: bool
    total_solicitados: int
    total_asignados: int
    consecutivo_tramite: Optional[str]
    items: List[ItemPredioExistenteAsignado]

class ConsultarNpnsExistentesRequest(BaseModel):
    numeros_prediales: List[str] = Field(..., description="Lista de números prediales de 30 dígitos a consultar")

class ItemDiagnosticoNpn(BaseModel):
    numero_predial: str
    existe_base_principal: bool
    existe_r1: bool
    origen_base: str
    tiene_homologado: bool
    codigo_homologado_actual: Optional[str] = None
    estado_homologado_actual: Optional[str] = None
    fecha_homologacion: Optional[str] = None
    requiere_nuevo_homologado: bool

class ConsultarNpnsExistentesResponse(BaseModel):
    success: bool
    total_consultados: int
    total_sin_homologado: int
    total_con_homologado: int
    items: List[ItemDiagnosticoNpn]

# =========================================================
# VALIDACIÓN DE ACCESO POR ROL
# =========================================================
def _verificar_rol_autorizado(user: dict = Depends(get_current_user)) -> dict:
    role = normalize_role(get_user_role(user or {}))
    # Permitir a coordinador, coordinacion_tecnica, soporte y admin
    if role not in {"coordinador", "coordinacion_tecnica", "soporte", "admin", "administrador"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Acceso denegado: El rol '{role}' no tiene permisos para generar números prediales ni reservar códigos homologados."
        )
    return user

# =========================================================
# REGLAS CATASTRALES DE 30 DÍGITOS (Resolución IGAC / Neiva)
# Pos 1-13:  Prefijo Territorial (Depto 2, Mpio 3, Sector 2, Comuna 2, Barrio 4) -> 13 dígitos
# Pos 14-17: Manzana (4 dígitos)
# Pos 18-21: Terreno / Predio en la Manzana (4 dígitos)
# Pos 22:    Condición del Predio (1 dígito: 0, 9, 8, 7, 5, 4, 3, 2)
# Pos 23-24: Edificio / Torre (2 dígitos: 00 a 99)
# Pos 25-26: Piso (2 dígitos: 00 a 99)
# Pos 27-30: Unidad Predial en PH/Condominio (4 dígitos: 0001 a 9999) o '0000' en NPH
# Total: 13 + 4 + 4 + 1 + 2 + 2 + 4 = 30 dígitos
# =========================================================
def _desglosar_npn(npn: str) -> dict:
    npn_limpio = "".join([c for c in str(npn).strip() if c.isdigit()])
    if len(npn_limpio) != 30:
        raise HTTPException(
            status_code=400,
            detail=f"El número predial matriz '{npn}' debe tener exactamente 30 dígitos numéricos (actualmente tiene {len(npn_limpio)})."
        )
    return {
        "prefijo_13": npn_limpio[0:13],      # Pos 1-13
        "manzana": npn_limpio[13:17],        # Pos 14-17 (4 dígitos)
        "terreno": npn_limpio[17:21],        # Pos 18-21 (4 dígitos)
        "condicion": npn_limpio[21:22],      # Pos 22 (1 dígito)
        "edificio": npn_limpio[22:24],       # Pos 23-24 (2 dígitos)
        "piso": npn_limpio[24:26],           # Pos 25-26 (2 dígitos)
        "unidad": npn_limpio[26:30],         # Pos 27-30 (4 dígitos)
    }

def _construir_npn(d: dict) -> str:
    prefijo_13 = str(d["prefijo_13"]).zfill(13)[:13]
    manzana = str(d["manzana"]).zfill(4)[:4]
    terreno = str(d["terreno"]).zfill(4)[:4]
    condicion = str(d["condicion"]).strip()[:1] or "0"
    edificio = str(d["edificio"]).zfill(2)[:2]
    piso = str(d["piso"]).zfill(2)[:2]
    unidad = str(d["unidad"]).zfill(4)[:4]
    return f"{prefijo_13}{manzana}{terreno}{condicion}{edificio}{piso}{unidad}"

# =========================================================
# ENDPOINTS
# =========================================================

@router.get("/inventario-resumen")
def resumen_inventario(
    user: dict = Depends(_verificar_rol_autorizado),
    tenant: TenantContext = Depends(get_current_tenant),
    conn=Depends(get_tenant_db_connection),
):
    """Retorna el estado en tiempo real del inventario de códigos homologados."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT 
                COUNT(*) FILTER (WHERE estado = 'DISPONIBLE') AS disponibles,
                COUNT(*) FILTER (WHERE estado = 'RESERVADO') AS reservados,
                COUNT(*) FILTER (WHERE estado = 'ASIGNADO') AS asignados,
                COUNT(*) AS total
            FROM arbimaps_app.codigos_homologados;
        """)
        row = cur.fetchone() or {"disponibles": 0, "reservados": 0, "asignados": 0, "total": 0}
        disp = row["disponibles"] or 0
        umbral = 500
        nivel = "OPTIMO"
        if disp < 200:
            nivel = "CRITICO"
        elif disp < umbral:
            nivel = "ADVERTENCIA"

        return {
            "success": True,
            "resumen": {
                "disponibles": disp,
                "reservados": row["reservados"] or 0,
                "asignados": row["asignados"] or 0,
                "total": row["total"] or 0,
                "umbral_alerta": umbral,
                "es_stock_bajo": disp < umbral,
                "nivel_alerta": nivel
            }
        }


@router.get("/sugerir-consecutivos-territoriales")
def sugerir_consecutivos_territoriales(
    sector: str = Query("01", description="Sector territorial (01=Urbano, 00=Rural)"),
    comuna: str = Query("01", description="Comuna o Corregimiento (2 dígitos)"),
    barrio: str = Query("0000", description="Barrio o Vereda (4 dígitos)"),
    user: dict = Depends(_verificar_rol_autorizado),
    tenant: TenantContext = Depends(get_current_tenant),
    conn=Depends(get_tenant_db_connection),
):
    """
    Rastrea en tiempo real y alta velocidad el último consecutivo existente de Manzana, Barrio y Comuna
    en la base de datos para sugerir el siguiente número correlativo sin dejar vacíos.
    """
    depto = "41"
    mpio = "001"
    sec = sector.strip().zfill(2)[:2]
    com = comuna.strip().zfill(2)[:2]
    bar = barrio.strip().zfill(4)[:4]
    
    prefijo_13 = f"{depto}{mpio}{sec}{com}{bar}"
    prefijo_9 = f"{depto}{mpio}{sec}{com}"
    prefijo_7 = f"{depto}{mpio}{sec}"
    schema_main = tenant.schemas.main or "a_base_principal"
    
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # 1. Manzanas en base principal
        cur.execute(f"""
            SELECT MAX(SUBSTRING(numero_predial, 14, 4)::int) AS max_manzana,
                   COUNT(DISTINCT SUBSTRING(numero_predial, 14, 4)) AS total_manzanas
            FROM {schema_main}.arb_predio
            WHERE numero_predial LIKE %s
              AND length(numero_predial) = 30
              AND SUBSTRING(numero_predial, 14, 4) ~ '^[0-9]+$';
        """, (f"{prefijo_13}%",))
        res_m1 = cur.fetchone() or {}
        max_m1 = res_m1.get("max_manzana") or 0
        total_m = res_m1.get("total_manzanas") or 0
        
        # Manzanas en homologados
        cur.execute("""
            SELECT MAX(SUBSTRING(numero_predial, 14, 4)::int) AS max_manzana
            FROM arbimaps_app.codigos_homologados
            WHERE numero_predial LIKE %s
              AND length(numero_predial) = 30
              AND SUBSTRING(numero_predial, 14, 4) ~ '^[0-9]+$';
        """, (f"{prefijo_13}%",))
        res_m2 = cur.fetchone() or {}
        max_m2 = res_m2.get("max_manzana") or 0
        
        max_m = max(max_m1, max_m2)
        sig_m = str(max_m + 1).zfill(4)
        
        # 2. Barrios/Veredas
        cur.execute(f"""
            SELECT MAX(SUBSTRING(numero_predial, 10, 4)::int) AS max_barrio
            FROM {schema_main}.arb_predio
            WHERE numero_predial LIKE %s
              AND length(numero_predial) = 30
              AND SUBSTRING(numero_predial, 10, 4) ~ '^[0-9]+$';
        """, (f"{prefijo_9}%",))
        res_b = cur.fetchone() or {}
        max_b = res_b.get("max_barrio") or 0
        sig_b = str(max_b + 1).zfill(4)

        # 3. Comunas
        cur.execute(f"""
            SELECT MAX(SUBSTRING(numero_predial, 8, 2)::int) AS max_comuna
            FROM {schema_main}.arb_predio
            WHERE numero_predial LIKE %s
              AND length(numero_predial) = 30
              AND SUBSTRING(numero_predial, 8, 2) ~ '^[0-9]+$';
        """, (f"{prefijo_7}%",))
        res_c = cur.fetchone() or {}
        max_c = res_c.get("max_comuna") or 0
        sig_c = str(max_c + 1).zfill(2)
        
        npn_base_sugerido = f"{prefijo_13}{sig_m}0000000000000"
        
        return {
            "success": True,
            "sector": sec,
            "comuna": com,
            "barrio": bar,
            "prefijo_13": prefijo_13,
            "max_manzana_existente": str(max_m).zfill(4),
            "siguiente_manzana_sugerida": sig_m,
            "total_manzanas_en_zona": total_m,
            "max_barrio_existente": str(max_b).zfill(4),
            "siguiente_barrio_sugerido": sig_b,
            "max_comuna_existente": str(max_c).zfill(2),
            "siguiente_comuna_sugerida": sig_c,
            "npn_base_sugerido": npn_base_sugerido,
        }


@router.get("/catalogo-territorial")
def obtener_catalogo_territorial(
    user: dict = Depends(_verificar_rol_autorizado),
    tenant: TenantContext = Depends(get_current_tenant),
    conn=Depends(get_tenant_db_connection),
):
    """
    Retorna el catálogo oficial de Sectores, Comunas urbanas, Corregimientos
    y las 80 Veredas oficiales de Neiva registradas en cartografía catastral.
    """
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Veredas oficiales
        veredas = []
        try:
            cur.execute("""
                SELECT codigo, nombre 
                FROM c_cartografia_catastral.cc_vereda 
                ORDER BY codigo ASC;
            """)
            for r in cur.fetchall():
                cod_str = str(r["codigo"] or "")
                # Extraer los 4 dígitos de la vereda (pos 14 a 17 del código largo o últimos 4)
                cod_4d = cod_str[-4:] if len(cod_str) >= 4 else cod_str.zfill(4)
                veredas.append({
                    "codigo_completo": cod_str,
                    "codigo_4d": cod_4d,
                    "nombre": r["nombre"]
                })
        except Exception as exc:
            logger.warning("Excepcion en predios_generador_api: %s", exc)

        # Si no hay en c_cartografia_catastral, consultar las veredas con predios existentes
        if not veredas:
            cur.execute("""
                SELECT DISTINCT SUBSTRING(numero_predial, 10, 4) AS cod_4d
                FROM a_base_principal.arb_predio
                WHERE length(numero_predial) = 30 AND SUBSTRING(numero_predial, 10, 4) <> '0000'
                ORDER BY cod_4d;
            """)
            for r in cur.fetchall():
                veredas.append({
                    "codigo_4d": r["cod_4d"],
                    "nombre": f"Vereda {r['cod_4d']}"
                })

        return {
            "success": True,
            "sectores": [
                {"codigo": "01", "nombre": "01 - Urbano (Comunas 01 a 10)"},
                {"codigo": "00", "nombre": "00 - Rural General"},
                {"codigo": "02", "nombre": "02 - Corregimiento Río Las Ceibas"},
                {"codigo": "03", "nombre": "03 - Corregimiento Vegalarga"},
                {"codigo": "04", "nombre": "04 - Corregimiento Fortalecillas"},
                {"codigo": "05", "nombre": "05 - Corregimiento El Caguán"},
                {"codigo": "06", "nombre": "06 - Corregimiento Guacirco"},
                {"codigo": "07", "nombre": "07 - Corregimiento San Antonio"},
                {"codigo": "08", "nombre": "08 - Corregimiento Chapinero / Aipecito"}
            ],
            "comunas_urbanas": [
                {"codigo": str(i).zfill(2), "nombre": f"Comuna {str(i).zfill(2)}"} for i in range(1, 11)
            ],
            "total_veredas": len(veredas),
            "veredas": veredas
        }


@router.post("/generar-npn-homologados", response_model=GenerarNpnResponse)
def generar_npn_y_reservar(
    payload: GenerarNpnRequest,
    user: dict = Depends(_verificar_rol_autorizado),
    tenant: TenantContext = Depends(get_current_tenant),
    conn=Depends(get_tenant_db_connection),
):
    """
    Genera N números prediales de 30 dígitos aplicando la norma catastral de Neiva:
    - Conserva el prefijo territorial (pos 1-13) y la manzana (pos 14-17).
    - Para NPH (0, 4, 3, 2): Consecutivo de Terreno (pos 18-21), Edificio=00, Piso=00, Unidad=0000.
    - Para PH/Condominio/Cementerio/Mejoras (9, 8, 7, 5): Fija Terreno (pos 18-21), Edificio (pos 23-24), Piso (pos 25-26) y Consecutivo de Unidad (pos 27-30).
    - Reserva de forma atómica N códigos homologados disponibles.
    """
    username = user.get("username") if isinstance(user, dict) else str(user)
    partes_base = _desglosar_npn(payload.predio_matriz)
    
    # 1. Base territorial de la manzana (17 dígitos: Pos 1-13 + Manzana 14-17)
    prefijo_manzana = f"{partes_base['prefijo_13']}{partes_base['manzana']}"
    
    # 2. Consultar el conjunto de predios existentes para garantizar NO REPETICIÓN cruzada
    schema_main = tenant.schemas.main or "a_base_principal"
    
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        query_existentes = f"""
            SELECT DISTINCT numero_predial
            FROM (
                SELECT numero_predial FROM {schema_main}.arb_predio 
                WHERE numero_predial LIKE %s AND length(numero_predial) = 30
                UNION
                SELECT numero_predial FROM f_r1_r2.r1_predio_propietario 
                WHERE numero_predial LIKE %s AND length(numero_predial) = 30
                UNION
                SELECT numero_predial FROM arbimaps_app.codigos_homologados 
                WHERE numero_predial LIKE %s AND length(numero_predial) = 30
            ) todos_npn
        """
        like_pattern = f"{prefijo_manzana}%"
        cur.execute(query_existentes, (like_pattern, like_pattern, like_pattern))
        npns_existentes = {r["numero_predial"] for r in cur.fetchall() if r.get("numero_predial")}
        
        # 3. Determinar condición (Posición 22: 1 dígito)
        # 0 = No propiedad horizontal (NPH)
        # 9 = Predios en Propiedad Horizontal (PH)
        # 5 = Mejoras por edificaciones en terreno ajeno de propiedad no reglamentaria en PH
        # 8 = Predio en condominio
        # 7 = Parque cementerios
        # 4 = Vías
        # 3 = Bienes de uso público diferentes a las vías
        # 2 = Informal
        cond_raw = str(payload.condicion_propiedad or "0").strip()
        primer_digito_cond = cond_raw[0] if cond_raw else "0"

        tipo_mut = (payload.tipo_mutacion or "DESENGLOBE").upper().strip()
        es_tramite_unidades = (primer_digito_cond in {"9", "8", "7", "5"}) or (tipo_mut in {"PH", "CONDOMINIO", "MEJORA_PH"})

        nuevos_npns: List[dict] = []
        
        if es_tramite_unidades:
            # EN PH / CONDOMINIO / CEMENTERIOS / MEJORAS (9, 8, 7, 5):
            # Pos 18-21: Terreno matriz fijo
            # Pos 22: Condición (9, 8, 7, 5)
            # Pos 23-24: Edificio (2 dígitos, ej. 00 o 01)
            # Pos 25-26: Piso (2 dígitos, ej. 00 o 01)
            # Pos 27-30: Unidad consecutiva (4 dígitos: 0001, 0002...)
            terreno_fijo = partes_base["terreno"]
            edificio_val = (payload.edificio if payload.edificio is not None else partes_base["edificio"]).zfill(2)[:2]
            piso_val = (payload.piso if payload.piso is not None else partes_base["piso"]).zfill(2)[:2]
            
            # Buscar unidades existentes con este prefijo (Manzana + Terreno + Condición + Edificio + Piso)
            prefijo_torre = f"{prefijo_manzana}{terreno_fijo}{primer_digito_cond}{edificio_val}{piso_val}"
            unidades_usadas = set()
            for npn in npns_existentes:
                if npn.startswith(prefijo_torre):
                    try:
                        unidades_usadas.add(int(npn[26:30]))
                    except ValueError:
                        pass
  
            
            max_unidad = max(unidades_usadas) if unidades_usadas else 0
            siguiente_unidad = max_unidad + 1 if max_unidad > 0 else 1
            
            while len(nuevos_npns) < payload.cantidad:
                if siguiente_unidad not in unidades_usadas:
                    p = dict(partes_base)
                    p["terreno"] = terreno_fijo
                    p["condicion"] = primer_digito_cond
                    p["edificio"] = edificio_val
                    p["piso"] = piso_val
                    p["unidad"] = str(siguiente_unidad).zfill(4) # Pos 27-30 (4 dígitos)
                    npn_candidato = _construir_npn(p)
                    if npn_candidato not in npns_existentes:
                        nuevos_npns.append(p)
                        npns_existentes.add(npn_candidato)
                siguiente_unidad += 1
        else:
            # EN NPH / DESENGLOBE / SUBDIVISIÓN / VÍAS / BIENES PÚBLICOS / INFORMAL (0, 4, 3, 2):
            # Pos 18-21: Consecutivo de Terreno
            # Pos 22: Condición (0, 4, 3, 2)
            # Pos 23-24: Edificio = '00'
            # Pos 25-26: Piso = '00'
            # Pos 27-30: Unidad = '0000'
            edificio_val = "00"
            piso_val = "00"
            unidad_val = "0000"
            
            terrenos_usados = set()
            for npn in npns_existentes:
                try:
                    terrenos_usados.add(int(npn[17:21]))
                except ValueError:
                    pass
            
            # Buscar el último terreno registrado en esta manzana
            max_terreno = max(terrenos_usados) if terrenos_usados else int(partes_base.get("terreno", "0000"))
            siguiente_terreno = max_terreno + 1 if max_terreno > 0 else 1
            
            while len(nuevos_npns) < payload.cantidad:
                if siguiente_terreno not in terrenos_usados:
                    p = dict(partes_base)
                    p["terreno"] = str(siguiente_terreno).zfill(4) # Pos 18-21 (4 dígitos)
                    p["condicion"] = primer_digito_cond             # Pos 22 (1 dígito)
                    p["edificio"] = edificio_val                    # Pos 23-24 ('00')
                    p["piso"] = piso_val                            # Pos 25-26 ('00')
                    p["unidad"] = unidad_val                        # Pos 27-30 ('0000')
                    npn_candidato = _construir_npn(p)
                    if npn_candidato not in npns_existentes:
                        nuevos_npns.append(p)
                        npns_existentes.add(npn_candidato)
                siguiente_terreno += 1

        # 4. Bloquear y reservar N códigos homologados disponibles (FOR UPDATE SKIP LOCKED)
        cur.execute("""
            SELECT id, codigo_homologado 
            FROM arbimaps_app.codigos_homologados
            WHERE estado = 'DISPONIBLE'
            ORDER BY id ASC
            LIMIT %s
            FOR UPDATE SKIP LOCKED;
        """, (payload.cantidad,))
        
        filas_homologados = cur.fetchall()
        if len(filas_homologados) < payload.cantidad:
            conn.rollback()
            raise HTTPException(
                status_code=400,
                detail=f"Inventario insuficiente: Se solicitaron {payload.cantidad} códigos pero solo hay {len(filas_homologados)} disponibles en la bolsa."
            )
        
        # 5. Actualizar los códigos a estado 'RESERVADO' vinculando el NPN y auditoría
        items_resultado: List[ItemPredioGenerado] = []
        fecha_reserva_str = datetime.now(timezone.utc).isoformat()
        
        for idx, h_row in enumerate(filas_homologados):
            h_id = h_row["id"]
            ch_codigo = h_row["codigo_homologado"]
            npn_obj = nuevos_npns[idx]
            npn_str = _construir_npn(npn_obj)
            
            obs_full = f"Reserva de trámite {payload.consecutivo_tramite or 'S/N'}. {payload.observaciones or ''}".strip()
            
            cur.execute("""
                UPDATE arbimaps_app.codigos_homologados
                SET estado = 'RESERVADO',
                    numero_predial = %s,
                    observaciones = %s,
                    usuario = %s,
                    fecha_asignacion = NOW()
                WHERE id = %s;
            """, (npn_str, obs_full, username, h_id))
            
            items_resultado.append(ItemPredioGenerado(
                id_inventario=h_id,
                codigo_homologado=ch_codigo,
                numero_predial=npn_str,
                departamento=npn_str[0:2],
                municipio=npn_str[2:5],
                sector=npn_str[5:7],
                comuna=npn_str[7:9],
                barrio=npn_str[9:13],
                manzana=npn_str[13:17],
                terreno=npn_str[17:21],
                condicion=npn_str[21:22],
                edificio=npn_str[22:24],
                piso=npn_str[24:26],
                unidad=npn_str[26:30],
                estado="RESERVADO",
                fecha_reserva=fecha_reserva_str,
            ))
            
        conn.commit()
        
        return GenerarNpnResponse(
            success=True,
            cantidad_generada=len(items_resultado),
            predio_matriz_base=payload.predio_matriz,
            consecutivo_tramite=payload.consecutivo_tramite,
            items=items_resultado,
        )


@router.get("/reservas-activas")
def listar_reservas_activas(
    user: dict = Depends(_verificar_rol_autorizado),
    tenant: TenantContext = Depends(get_current_tenant),
    conn=Depends(get_tenant_db_connection),
):
    """
    Retorna la lista de todas las reservas activas (estado 'RESERVADO')
    con su NPN propuesto, código homologado, usuario responsable y fecha.
    """
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT 
                id,
                codigo_homologado,
                numero_predial,
                observaciones,
                usuario,
                fecha_asignacion,
                estado
            FROM arbimaps_app.codigos_homologados
            WHERE estado = 'RESERVADO'
            ORDER BY fecha_asignacion DESC NULLS LAST, id DESC;
        """)
        filas = cur.fetchall()
        
        items = []
        for r in filas:
            items.append({
                "id": r["id"],
                "codigo_homologado": r["codigo_homologado"],
                "numero_predial": r["numero_predial"] or "",
                "observaciones": r["observaciones"] or "",
                "usuario": r["usuario"] or "Desconocido",
                "fecha_asignacion": r["fecha_asignacion"].isoformat() if r.get("fecha_asignacion") else "",
                "estado": r["estado"]
            })
            
        return {
            "success": True,
            "total_reservados": len(items),
            "items": items
        }


@router.post("/liberar-homologados")
def liberar_homologados(
    payload: LiberarHomologadosRequest,
    user: dict = Depends(_verificar_rol_autorizado),
    tenant: TenantContext = Depends(get_current_tenant),
    conn=Depends(get_tenant_db_connection),
):
    """
    Libera códigos que estaban en estado 'RESERVADO' devolviéndolos a 'DISPONIBLE'
    si el trámite no se consolidó en Alfa.
    """
    if not payload.codigos:
        raise HTTPException(status_code=400, detail="Debe enviar al menos un código a liberar.")
        
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE arbimaps_app.codigos_homologados
            SET estado = 'DISPONIBLE',
                numero_predial = NULL,
                observaciones = NULL,
                usuario = NULL,
                fecha_asignacion = NULL
            WHERE (codigo_homologado = ANY(%s) OR numero_predial = ANY(%s))
              AND estado = 'RESERVADO';
        """, (payload.codigos, payload.codigos))
        afectados = cur.rowcount
        conn.commit()
        
        return {
            "success": True,
            "codigos_liberados": afectados,
            "mensaje": f"Se liberaron exitosamente {afectados} códigos homologados hacia la bolsa disponible."
        }


@router.post("/consolidar-homologados")
def consolidar_homologados(
    payload: LiberarHomologadosRequest,
    user: dict = Depends(_verificar_rol_autorizado),
    tenant: TenantContext = Depends(get_current_tenant),
    conn=Depends(get_tenant_db_connection),
):
    """
    Consolida códigos que estaban en estado 'RESERVADO' cambiándolos a 'ASIGNADO'
    para dejarlos fijos de manera definitiva en la base de datos tras su creación en Alfa.
    """
    if not payload.codigos:
        raise HTTPException(status_code=400, detail="Debe enviar al menos un código a consolidar.")
        
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE arbimaps_app.codigos_homologados
            SET estado = 'ASIGNADO',
                fecha_asignacion = NOW()
            WHERE (codigo_homologado = ANY(%s) OR numero_predial = ANY(%s))
              AND estado = 'RESERVADO';
        """, (payload.codigos, payload.codigos))
        afectados = cur.rowcount
        conn.commit()
        
        return {
            "success": True,
            "codigos_consolidados": afectados,
            "mensaje": f"Se consolidaron exitosamente {afectados} códigos en estado definitivo (ASIGNADO)."
        }



def _obtener_homologados_existentes_multi_schema(cur, schema_main: str, npns: List[str]) -> dict:
    resultado = {}
    if not npns:
        return resultado

    # 1. Buscar en arbimaps_app.codigos_homologados
    cur.execute("""
        SELECT id, codigo_homologado, numero_predial, estado, fecha_asignacion, fecha_cargue
        FROM arbimaps_app.codigos_homologados
        WHERE numero_predial = ANY(%s)
          AND codigo_homologado IS NOT NULL 
          AND codigo_homologado != ''
    """, (npns,))
    for r in cur.fetchall():
        npn = r.get("numero_predial")
        if npn and r.get("codigo_homologado"):
            resultado[npn] = {
                "id": r.get("id"),
                "codigo_homologado": r.get("codigo_homologado"),
                "estado": r.get("estado") or "RESERVADO",
                "origen": "arbimaps_app.codigos_homologados",
                "fecha": str(r.get("fecha_asignacion") or r.get("fecha_cargue") or "")
            }

    # 2. Buscar en a_base_principal.arb_predio
    cur.execute(f"""
        SELECT numero_predial, codigo_homologado
        FROM {schema_main}.arb_predio
        WHERE numero_predial = ANY(%s)
          AND codigo_homologado IS NOT NULL 
          AND codigo_homologado != ''
    """, (npns,))
    for r in cur.fetchall():
        npn = r.get("numero_predial")
        ch = r.get("codigo_homologado")
        if npn and ch and npn not in resultado:
            resultado[npn] = {
                "id": None,
                "codigo_homologado": ch,
                "estado": "ASIGNADO",
                "origen": "a_base_principal.arb_predio",
                "fecha": ""
            }

    return resultado

@router.post("/liberar-reservas-inactivas")
def liberar_reservas_inactivas(
    payload: LiberarInactivasRequest,
    user: dict = Depends(_verificar_rol_autorizado),
    tenant: TenantContext = Depends(get_current_tenant),
    conn=Depends(get_tenant_db_connection),
):
    """
    Libera automáticamente todas las reservas en estado 'RESERVADO'
    que lleven inactivas más de N días (por defecto 30 días).
    """
    dias = max(1, payload.dias_antiguedad)
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE arbimaps_app.codigos_homologados
            SET estado = 'DISPONIBLE',
                numero_predial = NULL,
                observaciones = NULL,
                usuario = NULL,
                fecha_asignacion = NULL
            WHERE estado = 'RESERVADO'
              AND (fecha_asignacion < NOW() - (%s || ' days')::INTERVAL OR fecha_asignacion IS NULL);
        """, (dias,))
        afectados = cur.rowcount
        conn.commit()
        
        return {
            "success": True,
            "dias_antiguedad": dias,
            "codigos_liberados": afectados,
            "mensaje": f"Se liberaron exitosamente {afectados} reservas inactivas (> {dias} días) hacia la bolsa disponible."
        }


@router.post("/asignar-homologado-existentes", response_model=AsignarHomologadoExistenteResponse)
def asignar_homologado_a_predios_existentes(
    payload: AsignarHomologadoExistenteRequest,
    user: dict = Depends(_verificar_rol_autorizado),
    tenant: TenantContext = Depends(get_current_tenant),
    conn=Depends(get_tenant_db_connection),
):
    """
    Asigna o vincula un Código Homologado oficial disponible a NPNs existentes de 30 dígitos.
    PROTECCIÓN ESTRICTA: Si un NPN ya posee un código homologado previamente asignado o reservado
    (en arbimaps_app.codigos_homologados o a_base_principal.arb_predio), el sistema NO consumirá
    un nuevo código de la bolsa ni modificará el código existente.
    """
    username = user.get("username") if isinstance(user, dict) else str(user)
    
    npns_solicitados = []
    for raw_npn in payload.numeros_prediales:
        clean_npn = "".join(filter(str.isdigit, str(raw_npn or ""))).zfill(30)[:30]
        if len(clean_npn) == 30 and clean_npn not in npns_solicitados:
            npns_solicitados.append(clean_npn)

    if not npns_solicitados:
        raise HTTPException(
            status_code=400,
            detail="No se ingresaron números prediales válidos de 30 dígitos."
        )

    if len(npns_solicitados) > 100:
        raise HTTPException(
            status_code=400,
            detail="Solo se permite procesar hasta 100 NPNs por solicitud."
        )

    schema_main = tenant.schemas.main or "a_base_principal"
    
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # 1. Base principal y R1
        cur.execute(f"SELECT DISTINCT numero_predial FROM {schema_main}.arb_predio WHERE numero_predial = ANY(%s)", (npns_solicitados,))
        npns_en_base_principal = {r["numero_predial"] for r in cur.fetchall() if r.get("numero_predial")}

        cur.execute("SELECT DISTINCT numero_predial FROM f_r1_r2.r1_predio_propietario WHERE numero_predial = ANY(%s)", (npns_solicitados,))
        npns_en_r1 = {r["numero_predial"] for r in cur.fetchall() if r.get("numero_predial")}

        # 2. Homologados existentes en codigos_homologados y arb_predio
        homologados_previos_map = _obtener_homologados_existentes_multi_schema(cur, schema_main, npns_solicitados)

        # NPNs que efectivamente requieren un nuevo código de la bolsa disponible
        npns_sin_homologado = [npn for npn in npns_solicitados if npn not in homologados_previos_map]
        cantidad_necesaria = len(npns_sin_homologado)

        if cantidad_necesaria == 0:
            conn.rollback()
            raise HTTPException(
                status_code=400,
                detail=f"Acción no permitida: Todos los {len(npns_solicitados)} predios ingresados ya cuentan con un código homologado oficial asignado previamente en el sistema. No se permite realizar asignaciones sobre predios previamente homologados."
            )

        filas_homologados_nuevos = []
        if cantidad_necesaria > 0:
            cur.execute("""
                SELECT id, codigo_homologado
                FROM arbimaps_app.codigos_homologados
                WHERE estado = 'DISPONIBLE'
                ORDER BY id ASC
                LIMIT %s
                FOR UPDATE SKIP LOCKED;
            """, (cantidad_necesaria,))
            filas_homologados_nuevos = cur.fetchall() or []

            if len(filas_homologados_nuevos) < cantidad_necesaria:
                conn.rollback()
                raise HTTPException(
                    status_code=400,
                    detail=f"Inventario insuficiente en bolsa: Se requieren {cantidad_necesaria} códigos para los NPNs sin homologar pero solo hay {len(filas_homologados_nuevos)} disponibles."
                )

        items_resultado: List[ItemPredioExistenteAsignado] = []
        fecha_actual_str = datetime.now(timezone.utc).isoformat()
        idx_nuevo = 0

        for npn in npns_solicitados:
            if npn in npns_en_base_principal:
                origen = "Base Principal (arb_predio)"
            elif npn in npns_en_r1:
                origen = "Catastro R1/R2 (r1_predio_propietario)"
            else:
                origen = "NPN Ingresado (No en Base R1)"

            if npn in homologados_previos_map:
                # MANTENER CÓDIGO EXISTENTE - NO MODIFICAR NI CONSUMIR BOLSA
                h_previo = homologados_previos_map[npn]
                items_resultado.append(ItemPredioExistenteAsignado(
                    id_inventario=h_previo.get("id"),
                    codigo_homologado=h_previo.get("codigo_homologado", ""),
                    numero_predial=npn,
                    estado=h_previo.get("estado", "ASIGNADO"),
                    es_nueva_reserva=False,
                    origen_base=origen,
                    fecha_reserva=str(h_previo.get("fecha") or fecha_actual_str),
                ))
            else:
                # ASIGNAR NUEVO CÓDIGO DE LA BOLSA
                h_row = filas_homologados_nuevos[idx_nuevo]
                idx_nuevo += 1

                h_id = h_row["id"]
                ch_codigo = h_row["codigo_homologado"]
                obs_full = f"Asignación a NPN existente. Trámite {payload.consecutivo_tramite or 'S/N'}. {payload.observaciones or ''}".strip()

                cur.execute("""
                    UPDATE arbimaps_app.codigos_homologados
                    SET estado = 'RESERVADO',
                        numero_predial = %s,
                        observaciones = %s,
                        usuario = %s,
                        fecha_asignacion = NOW()
                    WHERE id = %s;
                """, (npn, obs_full, username, h_id))

                items_resultado.append(ItemPredioExistenteAsignado(
                    id_inventario=h_id,
                    codigo_homologado=ch_codigo,
                    numero_predial=npn,
                    estado="RESERVADO",
                    es_nueva_reserva=True,
                    origen_base=origen,
                    fecha_reserva=fecha_actual_str,
                ))

        conn.commit()

        return AsignarHomologadoExistenteResponse(
            success=True,
            total_solicitados=len(npns_solicitados),
            total_asignados=len(items_resultado),
            consecutivo_tramite=payload.consecutivo_tramite,
            items=items_resultado,
        )

@router.post("/consultar-npns-existentes", response_model=ConsultarNpnsExistentesResponse)
def consultar_npns_existentes_diagnostico(
    payload: ConsultarNpnsExistentesRequest,
    user: dict = Depends(_verificar_rol_autorizado),
    tenant: TenantContext = Depends(get_current_tenant),
    conn=Depends(get_tenant_db_connection),
):
    """
    Consulta diagnóstica (solo lectura) de presencia e historial de homologación para una lista de NPNs.
    - Verifica presencia en a_base_principal.arb_predio.
    - Verifica presencia en f_r1_r2.r1_predio_propietario.
    - Verifica si ya posee un código homologado en arbimaps_app.codigos_homologados.
    """
    npns_solicitados = []
    for raw_npn in payload.numeros_prediales:
        clean_npn = "".join(filter(str.isdigit, str(raw_npn or ""))).zfill(30)[:30]
        if len(clean_npn) == 30 and clean_npn not in npns_solicitados:
            npns_solicitados.append(clean_npn)

    if not npns_solicitados:
        raise HTTPException(
            status_code=400,
            detail="No se ingresaron números prediales válidos de 30 dígitos."
        )

    if len(npns_solicitados) > 100:
        raise HTTPException(
            status_code=400,
            detail="Solo se permite consultar hasta 100 NPNs por solicitud."
        )

    schema_main = tenant.schemas.main or "a_base_principal"
    
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # 1. Base principal
        cur.execute(f"SELECT DISTINCT numero_predial FROM {schema_main}.arb_predio WHERE numero_predial = ANY(%s)", (npns_solicitados,))
        npns_en_base_principal = {r["numero_predial"] for r in cur.fetchall() if r.get("numero_predial")}

        # 2. R1/R2
        cur.execute("SELECT DISTINCT numero_predial FROM f_r1_r2.r1_predio_propietario WHERE numero_predial = ANY(%s)", (npns_solicitados,))
        npns_en_r1 = {r["numero_predial"] for r in cur.fetchall() if r.get("numero_predial")}

        # 3. Homologados
        cur.execute("""
            SELECT id, codigo_homologado, numero_predial, estado, fecha_asignacion, fecha_cargue
            FROM arbimaps_app.codigos_homologados
            WHERE numero_predial = ANY(%s)
        """, (npns_solicitados,))
        homologados_existentes_rows = cur.fetchall() or []
        homologados_previos_map = _obtener_homologados_existentes_multi_schema(cur, schema_main, npns_solicitados)

    items: List[ItemDiagnosticoNpn] = []
    total_con_h = 0
    total_sin_h = 0

    for npn in npns_solicitados:
        en_base = npn in npns_en_base_principal
        en_r1 = npn in npns_en_r1

        if en_base:
            origen = "Base Principal (arb_predio)"
        elif en_r1:
            origen = "Catastro R1/R2 (r1_predio_propietario)"
        else:
            origen = "NPN Ingresado (No en Base R1)"

        if npn in homologados_previos_map:
            total_con_h += 1
            h_info = homologados_previos_map[npn]
            items.append(ItemDiagnosticoNpn(
                numero_predial=npn,
                existe_base_principal=en_base,
                existe_r1=en_r1,
                origen_base=origen,
                tiene_homologado=True,
                codigo_homologado_actual=h_info.get("codigo_homologado"),
                estado_homologado_actual=h_info.get("estado"),
                fecha_homologacion=str(h_info.get("fecha_asignacion") or h_info.get("fecha_cargue") or ""),
                requiere_nuevo_homologado=False,
            ))
        else:
            total_sin_h += 1
            items.append(ItemDiagnosticoNpn(
                numero_predial=npn,
                existe_base_principal=en_base,
                existe_r1=en_r1,
                origen_base=origen,
                tiene_homologado=False,
                codigo_homologado_actual=None,
                estado_homologado_actual=None,
                fecha_homologacion=None,
                requiere_nuevo_homologado=True,
            ))

    return ConsultarNpnsExistentesResponse(
        success=True,
        total_consultados=len(npns_solicitados),
        total_sin_homologado=total_sin_h,
        total_con_homologado=total_con_h,
        items=items,
    )
