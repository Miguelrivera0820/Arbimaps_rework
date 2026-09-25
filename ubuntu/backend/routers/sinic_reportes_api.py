import logging
import os
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from routers.auth import get_current_user, get_user_role, normalize_role
from tenants import get_tenant_db_connection
from services.sinic_export_service import SINICExportService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sinic", tags=["sinic-reportes"])
sinic_service = SINICExportService()


def _verificar_rol_admin_o_soporte(user: dict = Depends(get_current_user)):
    role = normalize_role(get_user_role(user))
    if role not in {"admin", "soporte"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso exclusivo para administradores y equipo de soporte."
        )
    return user


class GenerarEntregaPayload(BaseModel):
    tipo_entrega: str = Field("TOTAL", description="Tipo de entrega: TOTAL o DELTA")
    observaciones: Optional[str] = Field(None, description="Observaciones de la entrega")


@router.get("/versiones", response_model=List[Dict[str, Any]])
def listar_versiones_sinic(
    user: dict = Depends(_verificar_rol_admin_o_soporte),
    conn=Depends(get_tenant_db_connection)
):
    """
    Retorna el historial completo de entregas y versiones XTF generadas para SINIC.
    """
    try:
        versiones = sinic_service.obtener_historial_versiones(conn)
        return versiones
    except Exception as e:
        logger.error(f"Error al listar versiones SINIC: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error al obtener historial: {str(e)}")


@router.get("/resumen-diagnostico")
def obtener_resumen_diagnostico(
    user: dict = Depends(_verificar_rol_admin_o_soporte),
    conn=Depends(get_tenant_db_connection)
):
    """
    Retorna resumen general del estado de datos y diagnóstico pre-flight.
    """
    try:
        resumen = sinic_service.ejecutar_preflight_checks(conn)
        return resumen
    except Exception as e:
        logger.error(f"Error al obtener resumen diagnostico SINIC: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error al diagnosticar: {str(e)}")


@router.post("/preflight-checker")
def ejecutar_preflight_checker(
    user: dict = Depends(_verificar_rol_admin_o_soporte),
    conn=Depends(get_tenant_db_connection)
):
    """
    Ejecuta manualmente la batería de chequeos de calidad Pre-Flight.
    """
    try:
        resultado = sinic_service.ejecutar_preflight_checks(conn)
        return resultado
    except Exception as e:
        logger.error(f"Error ejecutando Pre-Flight Checker: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error en validación pre-flight: {str(e)}")


@router.post("/generar-entrega-xtf")
def generar_entrega_xtf(
    payload: GenerarEntregaPayload,
    user: dict = Depends(_verificar_rol_admin_o_soporte),
    conn=Depends(get_tenant_db_connection)
):
    """
    Ejecuta la ETL y empaquetado del archivo XTF oficial en D:\\20250711_CONSERVACION NEIVA\\20260915_MODULO TRANSFERENCIA SINIC.
    """
    username = user.get("username") or user.get("email") or "admin"
    try:
        resultado = sinic_service.generar_paquete_xtf_sinic(conn, payload.dict(), username)
        return resultado
    except Exception as e:
        logger.error(f"Error al generar entrega XTF SINIC: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error al generar XTF: {str(e)}")


@router.get("/descargar-paquete/{version_id}")
def descargar_paquete_zip(
    version_id: int,
    user: dict = Depends(_verificar_rol_admin_o_soporte),
    conn=Depends(get_tenant_db_connection)
):
    """
    Descarga directa del paquete .ZIP oficial de una versión generada.
    """
    try:
        versiones = sinic_service.obtener_historial_versiones(conn)
        target = next((v for v in versiones if v["id"] == version_id), None)
        if not target:
            raise HTTPException(status_code=404, detail="Versión no encontrada")

        filepath = target.get("ruta_relativa_storage")
        if not filepath or not os.path.exists(filepath):
            raise HTTPException(status_code=404, detail=f"Archivo físico no encontrado en el servidor: {filepath}")

        filename = target.get("nombre_archivo_xtf") or os.path.basename(filepath)
        return FileResponse(
            path=filepath,
            filename=filename,
            media_type="application/zip"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error al descargar paquete SINIC: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error de descarga: {str(e)}")


@router.get("/capas-geojson/terrenos")
def obtener_capas_geojson_terrenos(
    limit: Optional[int] = 5000,
    bbox: Optional[str] = None,
    user: dict = Depends(_verificar_rol_admin_o_soporte),
    conn=Depends(get_tenant_db_connection)
):
    """
    Capas GeoJSON de terrenos/predios optimizadas con simplificación espacial (0.5m) y bbox.
    """
    try:
        geojson = sinic_service.obtener_geojson_terrenos(conn, limit=limit, bbox=bbox)
        return geojson
    except Exception as e:
        logger.error(f"Error al obtener GeoJSON terrenos SINIC: {e}", exc_info=True)
        return {"type": "FeatureCollection", "features": []}


@router.get("/predio-detalle/{npn}")
def obtener_predio_detalle(
    npn: str,
    user: dict = Depends(_verificar_rol_admin_o_soporte),
    conn=Depends(get_tenant_db_connection)
):
    """
    Consulta el desglose completo LADM-COL de un predio según NPN de 30 dígitos.
    """
    try:
        predio = sinic_service.obtener_detalle_predio(conn, npn)
        if not predio:
            raise HTTPException(status_code=404, detail=f"Predio con NPN {npn} no fue encontrado.")
        return predio
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error al obtener detalle del predio SINIC {npn}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error al consultar predio: {str(e)}")


@router.post("/sincronizar-base-gsinic")
def sincronizar_base_gsinic(
    user: dict = Depends(_verificar_rol_admin_o_soporte),
    conn=Depends(get_tenant_db_connection)
):
    """
    Sincroniza en tiempo real las tablas del esquema g_sinic (terrenos, predios, unidades de construcción, baskets)
    a partir de a_base_principal y f_r1_r2.
    """
    try:
        res_sync = sinic_service.sincronizar_esquema_g_sinic(conn)
        res_enrich = sinic_enrich_service.ejecutar_enriquecimiento_completo()
        return {
            "success": True,
            "mensaje": "Sincronización y Enriquecimiento ETL SINIC v1.0 completado exitosamente.",
            "sync": res_sync,
            "enrichment": res_enrich
        }
    except Exception as e:
        logger.error(f"Error sincronizando base g_sinic: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error en sincronización g_sinic: {str(e)}")

from services.sinic_validation_service import SinicValidationService
from services.sinic_etl_enrichment_service import SinicEtlEnrichmentService
sinic_enrich_service = SinicEtlEnrichmentService()
sinic_val_service = SinicValidationService()

@router.get("/validar-consistencia")
def validar_consistencia_sinic(
    conn=Depends(get_tenant_db_connection)
):
    """
    Ejecuta el motor de validación oficial LADM_COL SINIC v1.0 (Reglas 1 a 5 de Nivel Básico).
    """
    try:
        reporte = sinic_val_service.ejecutar_validacion_completa()
        return reporte
    except Exception as e:
        logger.error(f"Error evaluando consistencia SINIC: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error en validación SINIC: {str(e)}")
