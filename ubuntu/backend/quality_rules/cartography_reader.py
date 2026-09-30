from __future__ import annotations

import logging
import os
from typing import Any

from .sinic_web.support import WebLayer, safe_geometry
from .sinic_web.compat.topologico import _load_geometry

log = logging.getLogger(__name__)

# Capas equivalentes al paquete MODELO_CARTOGRAFIA usado por el plugin QGIS.
CARTOGRAPHY_TABLES = (
    # Nombres físicos reales en PostgreSQL y variantes históricas/GPKG.
    "cc_barrio",
    "cc_centro_poblado", "cc_centropoblado",
    "cc_corregimiento",
    "cc_lmite_municipio", "cc_limite_municipio", "cc_limitemunicipio",
    "cc_localidad_comuna", "cc_localidadcomuna",
    "cc_manzana",
    "cc_nomenclatura_vial", "cc_nomenclaturavial",
    "cc_permetro_urbano", "cc_perimetro_urbano", "cc_perimetrourbano",
    "cc_sector_rural", "cc_sectorrural",
    "cc_sector_urbano", "cc_sectorurbano",
    "cc_vereda",
)
# Capas de zonas homogéneas usadas por las reglas físicas/topológicas SINIC.
# En Neiva, las tablas vigentes están en h_submodelo_avaluo; gdb_neiva existe
# pero actualmente contiene estas cuatro tablas vacías, por lo que no se usa
# como fallback automático.
ZONE_TABLES = (
    "av_zonahomogeneafisicarural",
    "av_zonahomogeneafisicaurbana",
    "av_zonahomogeneageoeconomicarural",
    "av_zonahomogeneageoeconomicaurbana",
)



def _schema_name() -> str:
    return (os.getenv("SINIC_CARTOGRAPHY_SCHEMA", "c_cartografia_catastral").strip() or "c_cartografia_catastral")


def _zones_schema_name() -> str:
    return (os.getenv("SINIC_ZONES_SCHEMA", "h_submodelo_avaluo").strip() or "h_submodelo_avaluo")


def _resolve_tenant(municipality_code: str | None) -> Any | None:
    code = str(municipality_code or "").strip().lower()
    if not code:
        return None
    try:
        from tenants.registry import MunicipalityRegistry
        from tenants.context import TenantContext
        config = MunicipalityRegistry.from_sources().require_active(code)
        return TenantContext.from_config(config)
    except Exception as exc:
        log.warning("No fue posible resolver el tenant '%s' para cartografia SINIC: %s", code, exc)
        return None


def _available_tables(cursor, schema: str, allowed_tables=CARTOGRAPHY_TABLES) -> list[str]:
    """Descubre tablas, vistas, materializadas y foreign tables visibles al usuario.

    ``information_schema.tables`` no siempre expone materialized views ni todas
    las relaciones PostGIS accesibles al rol del contenedor. Eso hacía que la
    web cargara solo Barrio/Corregimiento/Manzana/Vereda mientras QGIS tenía el
    conjunto cartográfico completo.
    """
    cursor.execute(
        """
        SELECT c.relname AS table_name
        FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname=%s
          AND c.relkind IN ('r','p','v','m','f')
        ORDER BY c.relname
        """,
        (schema,),
    )
    allowed = {name.lower() for name in allowed_tables}
    found=[]
    for row in cursor.fetchall():
        name=str(row["table_name"])
        if name.lower() in allowed and name not in found:
            found.append(name)
    return found


def _columns(cursor, schema: str, table_name: str) -> list[tuple[str, str]]:
    """Obtiene columnas también para materialized views/foreign tables."""
    cursor.execute(
        """
        SELECT a.attname AS column_name, t.typname AS udt_name
        FROM pg_catalog.pg_attribute a
        JOIN pg_catalog.pg_class c ON c.oid=a.attrelid
        JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        JOIN pg_catalog.pg_type t ON t.oid=a.atttypid
        WHERE n.nspname=%s AND c.relname=%s
          AND a.attnum>0 AND NOT a.attisdropped
        ORDER BY a.attnum
        """,
        (schema, table_name),
    )
    return [(str(row["column_name"]), str(row["udt_name"] or "")) for row in cursor.fetchall()]


def _read_table(cursor, schema: str, table_name: str) -> list[dict[str, Any]]:
    from psycopg2 import sql
    columns = _columns(cursor, schema, table_name)
    geometry_columns = [name for name, udt_name in columns if udt_name.lower() in {"geometry", "geography"}]
    geometry_column = geometry_columns[0] if geometry_columns else None
    attribute_columns = [name for name, _ in columns if name not in geometry_columns]

    select_items = [sql.Identifier(name) for name in attribute_columns]
    if geometry_column:
        select_items.append(
            sql.SQL("ST_AsBinary({geom}) AS __geometry_wkb__").format(
                geom=sql.Identifier(geometry_column)
            )
        )

    if not select_items:
        return []

    query = sql.SQL("SELECT {fields} FROM {schema}.{table}").format(
        fields=sql.SQL(", ").join(select_items),
        schema=sql.Identifier(schema),
        table=sql.Identifier(table_name),
    )
    cursor.execute(query)

    rows: list[dict[str, Any]] = []
    for db_row in cursor.fetchall():
        row = dict(db_row)
        raw_geometry = row.pop("__geometry_wkb__", None)
        if raw_geometry is not None:
            geometry = safe_geometry(_load_geometry(raw_geometry))
            if geometry is not None:
                row["__geometry__"] = geometry
        rows.append(row)
    return rows


def load_cartography_from_database(
    municipality_code: str | None,
    *,
    schema: str | None = None,
) -> tuple[dict[str, WebLayer], str]:
    """Carga automáticamente la cartografía SINIC desde PostgreSQL.

    Usa la misma conexión configurada para el municipio y lee el esquema
    ``c_cartografia_catastral``. No requiere cargar ZIP/GPKG en la pantalla web.
    La conexión es exclusivamente de lectura y se cierra al terminar la carga.
    """
    tenant = _resolve_tenant(municipality_code)
    if tenant is None:
        return {}, ""

    target_schema = str(schema or _schema_name()).strip()
    zones_schema = _zones_schema_name()
    connection = None
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor

        connection = psycopg2.connect(**tenant.db_params)
        connection.set_session(readonly=True)
        layers: dict[str, WebLayer] = {}
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            # Cartografía catastral base: exclusivamente desde c_cartografia_catastral.
            for table_name in _available_tables(cursor, target_schema, CARTOGRAPHY_TABLES):
                rows = _read_table(cursor, target_schema, table_name)
                layers[table_name] = WebLayer(table_name, rows)
                log.info("SINIC cartografia: %s.%s -> %s elementos", target_schema, table_name, len(rows))

            # Zonas homogéneas: fuente oficial para Neiva = h_submodelo_avaluo.
            # Se cargan como capas independientes y nunca se buscan dentro del XTF.
            for table_name in _available_tables(cursor, zones_schema, ZONE_TABLES):
                rows = _read_table(cursor, zones_schema, table_name)
                layers[table_name] = WebLayer(table_name, rows)
                log.info("SINIC zonas: %s.%s -> %s elementos", zones_schema, table_name, len(rows))

        if not layers:
            log.warning(
                "No se encontraron capas SINIC en %s.%s para el municipio %s.",
                tenant.db.db_name,
                target_schema,
                tenant.municipality_code,
            )
            return {}, ""

        source = (
            f"PostgreSQL:{tenant.municipality_code}:{tenant.db.db_name}"
            f"[{target_schema},{zones_schema}]"
        )
        return layers, source
    except Exception as exc:
        log.warning(
            "No fue posible leer cartografia SINIC desde PostgreSQL para %s: %s",
            tenant.municipality_code,
            exc,
        )
        return {}, ""
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass


__all__ = ["CARTOGRAPHY_TABLES", "ZONE_TABLES", "load_cartography_from_database"]
