# -*- coding: utf-8 -*-
"""Reglas SINIC complementarias para General y Físico.

Este módulo completa las reglas que no estaban implementadas en el paquete SINIC
original. Está diseñado para trabajar con capas web y con estructuras equivalentes
provenientes de XTF/INTERLIS, usando aliases y relaciones REF sin depender del orden
de carga de las capas.
"""
from __future__ import annotations

import datetime as _dt
import math
import re
import unicodedata
from collections import Counter, defaultdict

WebProject = None
NULL = None
WebGeometry = None

from .engine import metadata_regla
from . import model as arb_model
from .compat import administrativo as arb_admin
from .support import dataset_from_layers, issues_to_result
from .compat import obligatorias as arb_obl
from .legacy_sources import SOURCE_RULES
try:
    from .economic_helper import EconomicoWebHelper as _DomainHelper
except Exception:
    _DomainHelper = None

EPS = 1e-7
# Tolerancia técnica para descartar micro-slivers producidos por redondeo/digitación.
# No cambia la regla de negocio; evita reportar áreas subcentimétricas como errores materiales.
TOPOLOGY_AREA_TOLERANCE = 0.05  # m²
_FEATURE_LAYER = {}
_GEOM_CACHE = {}
_DOMAIN_HELPER = _DomainHelper({}) if _DomainHelper is not None else None

# -----------------------------------------------------------------------------
# Utilidades comunes
# -----------------------------------------------------------------------------

def _norm(value):
    if value is None:
        return ""
    try:
        if NULL is not None and value == NULL:
            return ""
        if hasattr(value, "isNull") and value.isNull():
            return ""
    except Exception:
        pass
    text = str(value).strip()
    if text.lower() in {"", "none", "null", "<null>", "nan"}:
        return ""
    text = "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))
    return "".join(ch for ch in text.upper() if ch.isalnum())


def _text(value):
    if value is None:
        return ""
    try:
        if NULL is not None and value == NULL:
            return ""
        if hasattr(value, "isNull") and value.isNull():
            return ""
    except Exception:
        pass
    s = str(value).strip()
    return "" if s.lower() in {"", "none", "null", "<null>", "nan"} else s


def _float(value):
    s = _text(value)
    if not s:
        return None
    try:
        return float(s.replace(",", "."))
    except Exception:
        return None


def _int(value):
    v = _float(value)
    return int(v) if v is not None and float(v).is_integer() else None


def _layers(layer_dict=None):
    if layer_dict is not None:
        return layer_dict
    if WebProject is None:
        return {}
    try:
        return {lyr.name(): lyr for lyr in WebProject.instance().mapLayers().values()}
    except Exception:
        return {}


def _layer_name(layer):
    try:
        return layer.name()
    except Exception:
        return str(layer)


def _is_historical_layer(layer):
    """True para capas históricas que no deben mezclarse con la geometría vigente."""
    n = _norm(_layer_name(layer))
    return "HISTORICO" in n or "HISTORICA" in n or "HISTORICAL" in n


def _unique_layers(capas):
    seen = set()
    for _, layer in (capas or {}).items():
        key = id(layer)
        if key in seen:
            continue
        seen.add(key)
        yield layer


def _layer_match_tokens(layer):
    """Devuelve nombres normalizados de la capa y de su origen físico.

    Mantiene paridad con QGIS aunque el nombre visible o la fuente use variantes
    históricas como ``cc_lmite_municipio`` o ``cc_permetro_urbano``.
    """
    tokens=set()
    n=_norm(_layer_name(layer))
    if n:
        tokens.add(n)
    try:
        src=str(layer.source() or "")
    except Exception:
        src=""
    if src:
        m=re.search(r"(?:^|[|;])layername=([^|;]+)", src, re.I)
        if m:
            v=_norm(m.group(1).strip('\"\''))
            if v: tokens.add(v)
        m=re.search(r"\btable\s*=\s*(?:\"[^\"]+\"\.)?\"?([A-Za-z0-9_]+)\"?", src, re.I)
        if m:
            v=_norm(m.group(1))
            if v: tokens.add(v)
    return tokens


def _find_layers(capas, aliases):
    wanted={_norm(x) for x in aliases if _norm(x)}
    exact=[]; suffix=[]
    for layer in _unique_layers(capas):
        tokens=_layer_match_tokens(layer)
        if tokens & wanted:
            exact.append(layer); continue
        if any(any(t.endswith(a) for a in wanted if len(a)>=8 and a.startswith(("ARB","LC","CR","CC","ILC"))) for t in tokens):
            suffix.append(layer)
    return exact if exact else suffix

def _layer_matches_aliases(layer, aliases):
    if layer is None:
        return False
    target = _norm(_layer_name(layer))
    return target in {_norm(a) for a in aliases}


def _find_layer(capas, aliases):
    rows = _find_layers(capas, aliases)
    return rows[0] if rows else None


def _features(layer):
    if layer is None:
        return []
    if isinstance(layer, (list, tuple)):
        rows = list(layer)
    else:
        try:
            rows = list(layer.getFeatures())
        except Exception:
            return []
    # Conserva la capa de origen para resolver dominios RelationReference/ValueRelation
    # sin alterar las FK estructurales. El helper devuelve la FK cruda cuando la
    # capa referenciada no es un catálogo con iliCode/dispName.
    for feat in rows:
        _FEATURE_LAYER[id(feat)] = layer
    return rows


def _field_names(feature):
    if isinstance(feature, dict):
        return list(feature.keys())
    try:
        return [f.name() for f in feature.fields()]
    except Exception:
        return []


def _get(feature, aliases, default=None):
    if feature is None:
        return default
    if isinstance(aliases, str):
        aliases = (aliases,)
    names = _field_names(feature)
    norm_map = {_norm(n): n for n in names}
    for a in aliases:
        if isinstance(feature, dict) and a in feature:
            return feature.get(a)
        real = norm_map.get(_norm(a))
        if real is not None:
            try:
                raw = feature[real] if not isinstance(feature, dict) else feature.get(real)
            except Exception:
                try:
                    raw = feature.attribute(real)
                except Exception:
                    continue
            if not isinstance(feature, dict) and _DOMAIN_HELPER is not None:
                try:
                    layer = _FEATURE_LAYER.get(id(feature))
                    return _DOMAIN_HELPER._resolve_domain_value(layer, real, raw)
                except Exception:
                    pass
            return raw
    return default


def _get_raw(feature, aliases, default=None):
    """Obtiene el valor almacenado de una FK sin resolver dominios/etiquetas.

    Las relaciones estructurales deben compararse por UUID/t_id reales. Una
    etiqueta visible puede repetirse y no es una clave de relación segura.
    """
    if feature is None:
        return default
    if isinstance(aliases, str):
        aliases = (aliases,)
    names = _field_names(feature)
    norm_map = {_norm(n): n for n in names}
    for a in aliases:
        if isinstance(feature, dict) and a in feature:
            return feature.get(a)
        real = norm_map.get(_norm(a))
        if real is None:
            continue
        try:
            return feature[real] if not isinstance(feature, dict) else feature.get(real)
        except Exception:
            try:
                return feature.attribute(real)
            except Exception:
                continue
    return default


def _ref(value):
    """Normaliza claves de relación web/INTERLIS sin perder UUID ni t_id."""
    if value is None:
        return ""
    # QVariant/web puede entregar enteros como 123, 123.0 o texto.
    try:
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
    except Exception:
        pass
    s = _text(value).strip().strip("{}").strip()
    if re.fullmatch(r"[-+]?\d+\.0+", s):
        s = s.split(".", 1)[0]
    return s


def _entity_keys(feature):
    """Claves estructurales válidas para relaciones ARB/LADM.

    No incorpora ``identificador`` ni el FID interno de web: son valores de
    negocio/proveedor y no son destino de las FK del modelo ARB observado.
    """
    return arb_model.entity_keys(feature)


def _aid(feature):
    # Para mostrar AID se conserva la preferencia por el identificador INTERLIS.
    for a in ("t_ili_tid", "T_Ili_Tid", "T_ILI_TID", "TID", "tid", "id_operacion", "Id_Operacion", "identificador", "Identificador", "t_id", "id", "ID"):
        v = _get(feature, (a,))
        if _ref(v):
            return _ref(v)
    keys = _entity_keys(feature)
    return next(iter(keys), str(id(feature)))


def _repair_geometry(g):
    """Normaliza geometrías inválidas antes de operaciones topológicas.

    QGIS y la web usan GEOS, pero una geometría inválida puede producir resultados
    diferentes en unaryUnion/difference/intersection. Se aplica makeValid de forma
    equivalente en ambos motores para que el mismo dato tenga el mismo resultado.
    """
    if g is None:
        return None
    try:
        if hasattr(g, "isEmpty") and g.isEmpty():
            return g
    except Exception:
        pass
    try:
        if hasattr(g, "is_empty") and bool(g.is_empty):
            return g
    except Exception:
        pass
    try:
        if hasattr(g, "isGeosValid"):
            if g.isGeosValid():
                return g
            fixed = g.makeValid()
            if fixed is not None:
                return fixed
    except Exception:
        pass
    try:
        valid = getattr(g, "is_valid")
        valid = valid() if callable(valid) else bool(valid)
        if valid:
            return g
        from shapely import make_valid as _shp_make_valid
        return _shp_make_valid(g)
    except Exception:
        return g


def clear_geometry_cache():
    """Limpia el cache de geometrías normalizadas para una nueva validación."""
    _GEOM_CACHE.clear()


def _geometry_cache_key(feature):
    if feature is None or isinstance(feature, dict):
        return None
    layer = _FEATURE_LAYER.get(id(feature))
    try:
        fid = feature.id()
    except Exception:
        return None
    try:
        fid = int(fid)
    except Exception:
        fid = str(fid)
    return (id(layer) if layer is not None else 0, fid)


def _geom_raw(feature):
    """Devuelve la geometría original sin intentar repararla.

    Se usa en reglas que validan la validez del dato de entrada (p. ej. SINIC 24).
    Las reglas topológicas pueden seguir usando _geom(), que normaliza/repara para
    poder ejecutar operaciones GEOS sin convertir una geometría inválida en un
    falso cumplimiento de la regla de validez.
    """
    if feature is None:
        return None
    if isinstance(feature, dict):
        return feature.get("__geometry__") or feature.get("geometry")
    try:
        if hasattr(feature, "hasGeometry") and not feature.hasGeometry():
            return None
        return feature.geometry()
    except Exception:
        return None


def _geom(feature):
    if feature is None:
        return None
    if isinstance(feature, dict):
        return _repair_geometry(feature.get("__geometry__") or feature.get("geometry"))
    key = _geometry_cache_key(feature)
    if key is not None and key in _GEOM_CACHE:
        return _GEOM_CACHE[key]
    try:
        if hasattr(feature, "hasGeometry") and not feature.hasGeometry():
            return None
        g = _repair_geometry(feature.geometry())
        if key is not None:
            _GEOM_CACHE[key] = g
        return g
    except Exception:
        return None


def _g_empty(g):
    if g is None:
        return True
    for name in ("isEmpty", "is_empty"):
        try:
            attr = getattr(g, name)
            return bool(attr() if callable(attr) else attr)
        except Exception:
            pass
    return False


def _g_area(g):
    if _g_empty(g):
        return 0.0
    try:
        a = getattr(g, "area")
        return float(a() if callable(a) else a)
    except Exception:
        return 0.0


def _g_valid(g):
    if _g_empty(g):
        return False
    for name in ("isGeosValid", "is_valid"):
        try:
            attr = getattr(g, name)
            return bool(attr() if callable(attr) else attr)
        except Exception:
            pass
    return True


def _g_intersects(a, b):
    if _g_empty(a) or _g_empty(b):
        return False
    try:
        return bool(a.intersects(b))
    except Exception:
        return False


def _g_intersection(a, b):
    if not _g_intersects(a, b):
        return None
    try:
        return _repair_geometry(a.intersection(b))
    except Exception:
        return None


def _g_difference(a, b):
    if _g_empty(a):
        return None
    try:
        return _repair_geometry(a.difference(b))
    except Exception:
        return None


def _g_combine(a, b):
    if _g_empty(a):
        return _repair_geometry(b)
    if _g_empty(b):
        return _repair_geometry(a)
    for name in ("combine", "union"):
        try:
            return _repair_geometry(getattr(a, name)(b))
        except Exception:
            pass
    return None


def _union(geoms):
    vals = [g for g in geoms if not _g_empty(g)]
    if not vals:
        return None
    # web: unaryUnion es mucho más rápida y robusta para miles de polígonos.
    if WebGeometry is not None:
        try:
            if hasattr(vals[0], "asWkt"):
                return _repair_geometry(WebGeometry.unaryUnion(vals))
        except Exception:
            pass
    # Pruebas/headless: si Shapely está disponible se aprovecha su unary_union.
    try:
        from shapely.ops import unary_union as _shp_unary_union
        if hasattr(vals[0], "geom_type"):
            return _repair_geometry(_shp_unary_union(vals))
    except Exception:
        pass
    result = vals[0]
    for g in vals[1:]:
        combined = _g_combine(result, g)
        if not _g_empty(combined):
            result = combined
    return result


def _g_bounds(g):
    """Bounding box genérico para WebGeometry/Shapely."""
    if _g_empty(g):
        return None
    try:
        b = g.boundingBox()
        return (float(b.xMinimum()), float(b.yMinimum()), float(b.xMaximum()), float(b.yMaximum()))
    except Exception:
        pass
    try:
        b = tuple(float(x) for x in g.bounds)
        return b if len(b) == 4 else None
    except Exception:
        return None


def _bbox_intersects(a, b, tol=EPS):
    if a is None or b is None:
        return True
    return not (a[2] < b[0] - tol or b[2] < a[0] - tol or a[3] < b[1] - tol or b[3] < a[1] - tol)

def _g_within(a, b, tolerance=EPS):
    if _g_empty(a) or _g_empty(b):
        return False
    try:
        if bool(a.within(b)):
            return True
    except Exception:
        pass
    diff = _g_difference(a, b)
    return _g_area(diff) <= tolerance


def _geom_hole_count(g):
    if _g_empty(g):
        return 0
    # Shapely
    try:
        typ = getattr(g, "geom_type", "")
        if typ == "Polygon":
            return len(g.interiors)
        if typ == "MultiPolygon":
            return sum(len(x.interiors) for x in g.geoms)
    except Exception:
        pass
    # WebGeometry
    try:
        poly = g.asPolygon()
        if poly:
            return max(0, len(poly) - 1)
    except Exception:
        pass
    try:
        mpoly = g.asMultiPolygon()
        return sum(max(0, len(poly) - 1) for poly in mpoly or [])
    except Exception:
        return 0


def _g_wkt(g):
    """Serializa geometría de diagnóstico sin guardar objetos WebGeometry en resultados."""
    if _g_empty(g):
        return ""
    try:
        return str(g.asWkt())
    except Exception:
        pass
    try:
        return str(g.wkt)
    except Exception:
        return ""


def _g_hole_geometries(g):
    """Devuelve cada hueco interior como geometría independiente.

    Se usa para que cada inconsistencia apunte al hueco exacto y no al polígono
    completo. No depende de IDs ni de un XTF concreto.
    """
    if _g_empty(g):
        return []
    geoms = []
    if WebGeometry is not None:
        try:
            poly = g.asPolygon()
            if poly:
                for ring in poly[1:]:
                    if ring:
                        hole = WebGeometry.fromPolygonXY([ring])
                        if not _g_empty(hole):
                            geoms.append(hole)
        except Exception:
            pass
        if not geoms:
            try:
                for poly in g.asMultiPolygon() or []:
                    for ring in poly[1:]:
                        if ring:
                            hole = WebGeometry.fromPolygonXY([ring])
                            if not _g_empty(hole):
                                geoms.append(hole)
            except Exception:
                pass
    # Compatibilidad con geometrías tipo Shapely usadas en pruebas auxiliares.
    if not geoms:
        try:
            from shapely.geometry import Polygon
            typ = getattr(g, "geom_type", "")
            polys = [g] if typ == "Polygon" else list(g.geoms) if typ == "MultiPolygon" else []
            for poly in polys:
                for ring in poly.interiors:
                    hole = Polygon(ring)
                    if not getattr(hole, "is_empty", True):
                        geoms.append(hole)
        except Exception:
            pass
    return geoms


def _g_holes_geometry(g):
    """Devuelve una geometría agregada con todos los huecos interiores."""
    return _union(_g_hole_geometries(g))


def _meta(code):
    return metadata_regla(str(code)) or {}


def _error(code, layer, feature, message, **details):
    d = dict(details)
    d.setdefault("tabla", _layer_name(layer) if layer is not None else "")
    d.setdefault("class", d.get("tabla", ""))
    d.setdefault("sinic_id", str(code))
    d.setdefault("sinic_abreviatura", _meta(code).get("abbreviation", ""))
    return {
        "aid": _aid(feature) if feature is not None else d.get("aid", "N/A"),
        "descripcion": message,
        "capa": layer,
        "regla": str(code),
        "detalles": d,
        "details": d,
    }


def _result(code, errors, message=None, **extra):
    out = {
        "cumple": len(errors) == 0,
        "errores": errors,
        "mensaje": message or (f"Se detectaron {len(errors)} incumplimientos en la regla SINIC {code}." if errors else f"No se detectaron errores en la regla SINIC {code}."),
        "regla_sinic": _meta(code),
    }
    out.update(extra)
    return out


def _not_verifiable(code, reason):
    return _result(code, [], f"Regla SINIC {code} no verificable con los datos actualmente cargados en web: {reason}", no_verificable=True, motivo_no_verificable=reason)


def _source_admin(code, source_id, capas):
    fn = getattr(arb_admin, "_rule_" + source_id.replace(".", "_"), None)
    if not callable(fn):
        fn = SOURCE_RULES.get(source_id)
    if not callable(fn):
        return _not_verifiable(code, f"la lógica fuente ARBIMAPS {source_id} no está disponible")
    dataset = dataset_from_layers(capas)
    try:
        issues = fn(dataset)
        base = issues_to_result(source_id, issues, capas)
    except Exception as exc:
        return _result(code, [], f"Error ejecutando lógica fuente {source_id}: {exc}", error_ejecucion=str(exc), cumple=False)
    errors = []
    for original in base.get("errores", []) or []:
        e = dict(original)
        d = dict(e.get("detalles") or e.get("details") or {})
        d.update({"sinic_id": str(code), "arbimaps_regla_origen": source_id, "implementacion": "MIGRADA_ARBIMAPS"})
        e["regla"] = str(code)
        e["detalles"] = d
        e["details"] = d
        errors.append(e)
    return _result(code, errors)


def _source_obl(code, source_id, capas):
    funcs = getattr(arb_obl, "RULE_FUNCTIONS", {})
    fn = funcs.get(source_id) if isinstance(funcs, dict) else None
    if not callable(fn):
        fn = getattr(arb_obl, "rule_" + source_id.replace(".", "_"), None)
    if not callable(fn):
        return _not_verifiable(code, f"la lógica fuente ARBIMAPS {source_id} no está disponible")
    try:
        dataset = dataset_from_layers(capas)
        base = issues_to_result(source_id, fn(dataset), capas)
    except Exception as exc:
        return _result(code, [], f"Error ejecutando lógica fuente {source_id}: {exc}", error_ejecucion=str(exc), cumple=False)
    errors = []
    for original in base.get("errores", []) or []:
        e = dict(original)
        d = dict(e.get("detalles") or e.get("details") or {})
        d.update({"sinic_id": str(code), "arbimaps_regla_origen": source_id, "implementacion": "MIGRADA_ARBIMAPS"})
        e["regla"] = str(code)
        e["detalles"] = d
        e["details"] = d
        errors.append(e)
    return _result(code, errors)


PREDIO_ALIASES = ("ARB_Predio", "(ARB) Predio", "ARB Predio", "LC_Predio", "CR_Predio", "Predio")
TERRENO_ALIASES = ("ARB_Terreno", "(ARB) Terreno", "ARB Terreno", "LC_Terreno", "CR_Terreno", "Terreno")
CONSTRUCCION_ALIASES = ("ARB_Construccion", "(ARB) Construccion", "(ARB) Construcción", "ARB Construccion", "LC_Construccion", "CR_Construccion", "Construccion")
UC_ALIASES = (
    "ARB_UnidadConstruccion", "ARB_Unidad_de_Construccion", "ARB Unidad de Construccion",
    "(ARB) Unidad de construcción", "(ARB) Unidad de construccion",
    "LC_UnidadConstruccion", "CR_UnidadConstruccion", "UnidadConstruccion",
    "Unidad de construcción", "Unidad de construccion",
)
CARAC_ALIASES = ("ARB_CaracteristicasUnidadConstruccion", "ARB Características de la unidad de construcción", "ARB Caracteristicas de la unidad de construccion", "(ARB) Características de la unidad de construcción", "(ARB) Caracteristicas de la unidad de construccion", "LC_CaracteristicasUnidadConstruccion", "CR_CaracteristicasUnidadConstruccion", "CaracteristicasUnidadConstruccion", "Características de la unidad de construcción", "Caracteristicas de la unidad de construccion")
DIRECCION_ALIASES = ("ARB_Direccion", "(ARB) Dirección", "(ARB) Direccion", "ARB Dirección", "LC_Direccion", "Direccion", "Dirección")
DERECHO_ALIASES = ("ARB_DerechoInteresadoFuente", "(ARB) Derecho Interesado Fuente", "ARB Derecho Interesado Fuente", "LC_Derecho", "DerechoInteresadoFuente")
COPROPIEDAD_ALIASES = ("ARB_Copropiedad", "ARB_PredioCopropiedad", "CR_Copropiedad", "PredioCopropiedad", "Copropiedad")
INFO_PH_ALIASES = ("ARB_InformacionPH", "(ARB) Información PH", "(ARB) Informacion PH", "ARB Información PH", "CR_InformacionPH", "InformacionPH", "Informacion_PH")
TRAMITE_ALIASES = ("ARB_Tramite", "(ARB) Tramite", "(ARB) Trámite", "ARB Tramite", "ILC_Tramite", "Tramite")
BARRIO_ALIASES = ("CC_Barrio", "(CC) Barrio", "Barrio")
LOCALIDAD_COMUNA_ALIASES = ("CC_LocalidadComuna", "(CC) Localidad Comuna", "LocalidadComuna", "Localidad Comuna")
VEREDA_ALIASES = ("CC_Vereda", "(CC) Vereda", "Vereda")
SECTOR_URBANO_ALIASES = ("CC_SectorUrbano", "CC_Sector_Urbano", "(CC) Sector Urbano", "SectorUrbano", "Sector Urbano")
SECTOR_RURAL_ALIASES = ("CC_SectorRural", "CC_Sector_Rural", "(CC) Sector rural", "SectorRural", "Sector rural")
PERIMETRO_URBANO_ALIASES = ("CC_PerimetroUrbano", "CC_Perimetro_Urbano", "cc_perimetro_urbano", "cc_perimetrourbano", "CC_PermetroUrbano", "CC_Permetro_Urbano", "cc_permetro_urbano", "cc_permetrourbano", "(CC) Perímetro Urbano", "PerimetroUrbano", "PermetroUrbano", "Perímetro Urbano")
MANZANA_ALIASES = ("CC_Manzana", "(CC) Manzana", "Manzana")
LIMITE_ALIASES = ("CC_LimiteMunicipio", "CC_Limite_Municipio", "cc_limite_municipio", "cc_limitemunicipio", "CC_LmiteMunicipio", "CC_Lmite_Municipio", "cc_lmite_municipio", "cc_lmitemunicipio", "(CC) Límite municipio", "LimiteMunicipio", "Limite_Municipio", "LmiteMunicipio", "Límite municipio")
CORREGIMIENTO_ALIASES = ("CC_Corregimiento", "(CC) Corregimiento", "Corregimiento")
CENTRO_POBLADO_ALIASES = ("CC_CentroPoblado", "CC_Centro_Poblado", "(CC) Centro poblado", "CentroPoblado", "Centro poblado")
EXT_DIRECCION_ALIASES = ("ExtDireccion", "Ext_Direccion", "EXT_Direccion", "(EXT) Dirección", "(EXT) Direccion")
ZHF_RURAL_ALIASES = ("VM_ZonaHomogeneaFisicaRural", "VM_Zona_Homogenea_Fisica_Rural", "(VM) Zona Homogénea Física Rural", "ZonaHomogeneaFisicaRural", "zonas_homogeneas_fisicas_rural", "zonas_fisicas_rural", "av_zonahomogeneafisicarural")
ZHG_RURAL_ALIASES = ("VM_ZonaHomogeneaGeoeconomicaRural", "VM_Zona_Homogenea_Geoeconomica_Rural", "(VM) Zona Homogénea Geoeconómica Rural", "ZonaHomogeneaGeoeconomicaRural", "41001_20260717__av_zonahomogeneageoeconomicarural", "zonas_geoeconomicas_rural", "av_zonahomogeneageoeconomicarural")
ZHF_URBANA_ALIASES = ("VM_ZonaHomogeneaFisicaUrbana", "VM_Zona_Homogenea_Fisica_Urbana", "(VM) Zona Homogénea Física Urbana", "ZonaHomogeneaFisicaUrbana", "zonas_homogeneas_fisicas_urbana", "zonas_fisicas_urbana", "av_zonahomogeneafisicaurbana")
ZHG_URBANA_ALIASES = ("VM_ZonaHomogeneaGeoeconomicaUrbana", "VM_Zona_Homogenea_Geoeconomica_Urbana", "(VM) Zona Homogénea Geoeconómica Urbana", "ZonaHomogeneaGeoeconomicaUrbana", "41001_20260717__av_zonahomogeneageoeconomicaurbana", "zonas_geoeconomicas_urbana", "av_zonahomogeneageoeconomicaurbana")

CARTOGRAFIA_ALIAS_GROUPS = (
    LIMITE_ALIASES, CORREGIMIENTO_ALIASES, CENTRO_POBLADO_ALIASES, PERIMETRO_URBANO_ALIASES,
    SECTOR_URBANO_ALIASES, SECTOR_RURAL_ALIASES, VEREDA_ALIASES, LOCALIDAD_COMUNA_ALIASES,
    BARRIO_ALIASES, MANZANA_ALIASES, ZHF_RURAL_ALIASES, ZHG_RURAL_ALIASES,
    ZHF_URBANA_ALIASES, ZHG_URBANA_ALIASES,
)

CAPAS_TOPOLOGICAS_145 = (
    TERRENO_ALIASES, MANZANA_ALIASES, VEREDA_ALIASES, SECTOR_RURAL_ALIASES, SECTOR_URBANO_ALIASES,
    BARRIO_ALIASES, LOCALIDAD_COMUNA_ALIASES, CORREGIMIENTO_ALIASES, CENTRO_POBLADO_ALIASES,
    PERIMETRO_URBANO_ALIASES, LIMITE_ALIASES, ZHF_RURAL_ALIASES, ZHG_RURAL_ALIASES,
    ZHF_URBANA_ALIASES, ZHG_URBANA_ALIASES,
)

CAPAS_TOPOLOGICAS_146 = CAPAS_TOPOLOGICAS_145 + (UC_ALIASES, EXT_DIRECCION_ALIASES,)


def _canonical_topology_name(layer):
    """Nombre estable de clase para reportes/AID, independiente del alias visible o fuente."""
    grupos = (
        (TERRENO_ALIASES, "ARB_Terreno"),
        (MANZANA_ALIASES, "cc_manzana"),
        (VEREDA_ALIASES, "cc_vereda"),
        (SECTOR_RURAL_ALIASES, "cc_sectorrural"),
        (SECTOR_URBANO_ALIASES, "cc_sectorurbano"),
        (BARRIO_ALIASES, "cc_barrio"),
        (LOCALIDAD_COMUNA_ALIASES, "cc_localidadcomuna"),
        (CORREGIMIENTO_ALIASES, "cc_corregimiento"),
        (CENTRO_POBLADO_ALIASES, "cc_centropoblado"),
        (PERIMETRO_URBANO_ALIASES, "cc_perimetrourbano"),
        (LIMITE_ALIASES, "cc_limitemunicipio"),
        (ZHF_RURAL_ALIASES, "av_zonahomogeneafisicarural"),
        (ZHG_RURAL_ALIASES, "av_zonahomogeneageoeconomicarural"),
        (ZHF_URBANA_ALIASES, "av_zonahomogeneafisicaurbana"),
        (ZHG_URBANA_ALIASES, "av_zonahomogeneageoeconomicaurbana"),
        (UC_ALIASES, "ARB_UnidadConstruccion"),
        (EXT_DIRECCION_ALIASES, "ExtDireccion"),
    )
    for aliases, nombre in grupos:
        if _layer_matches_aliases(layer, aliases):
            return nombre
    return _layer_name(layer)

def _canonical_topology_token(layer):
    return _norm(_canonical_topology_name(layer))

def _hole_sort_key(geom):
    b = _g_bounds(geom)
    if b is None:
        b = (0.0, 0.0, 0.0, 0.0)
    return tuple(round(float(v), 6) for v in b) + (round(float(_g_area(geom)), 6),)

def _capas_por_grupos(capas, grupos):
    """Resuelve solo las clases explícitamente aplicables y evita capas ajenas del proyecto."""
    out=[]; vistos=set()
    for aliases in grupos:
        for layer in _find_layers(capas, aliases):
            key=id(layer)
            if key in vistos:
                continue
            vistos.add(key); out.append(layer)
    return out

CARTOGRAFIA_REQUERIDA_TOPOLOGIA = (
    ("CC_LimiteMunicipio", LIMITE_ALIASES),
    ("CC_Corregimiento", CORREGIMIENTO_ALIASES),
    ("CC_CentroPoblado", CENTRO_POBLADO_ALIASES),
    ("CC_PerimetroUrbano", PERIMETRO_URBANO_ALIASES),
    ("CC_SectorUrbano", SECTOR_URBANO_ALIASES),
    ("CC_SectorRural", SECTOR_RURAL_ALIASES),
    ("CC_Vereda", VEREDA_ALIASES),
    ("CC_LocalidadComuna", LOCALIDAD_COMUNA_ALIASES),
    ("CC_Barrio", BARRIO_ALIASES),
    ("CC_Manzana", MANZANA_ALIASES),
    ("ZHF_Rural", ZHF_RURAL_ALIASES),
    ("ZHG_Rural", ZHG_RURAL_ALIASES),
    ("ZHF_Urbana", ZHF_URBANA_ALIASES),
    ("ZHG_Urbana", ZHG_URBANA_ALIASES),
)


def _cartografia_faltante(capas):
    faltantes=[]
    for label, aliases in CARTOGRAFIA_REQUERIDA_TOPOLOGIA:
        if not _find_layers(capas, aliases):
            faltantes.append(label)
    return faltantes


def _cartografia_cargada(capas):
    return not _cartografia_faltante(capas)


def _marcar_parcial_por_cartografia(resultado, capas, reglas_dependientes="145-148"):
    """Marca parcial cuando falta alguna capa cartográfica de referencia.

    Antes bastaba con que hubiera una sola capa CC/VM y la regla podía aparecer
    como completamente verificada. Para paridad Web/QGIS se exige presencia del
    mismo conjunto cartográfico; las tablas/capas pueden existir vacías.
    """
    faltantes=_cartografia_faltante(capas)
    if not faltantes:
        return resultado
    resultado=dict(resultado or {})
    resultado["no_verificable"]=True
    resultado["verificacion_parcial"]=True
    motivo=(
        "faltan capas cartográficas de referencia en web: " + ", ".join(faltantes) + "; "
        f"la parte cartográfica de las reglas {reglas_dependientes} queda parcial"
    )
    resultado["motivo_no_verificable"]=motivo
    msg=str(resultado.get("mensaje","") or "").strip()
    resultado["mensaje"]=(msg+" " if msg else "")+"Validación parcial: "+motivo+"."
    return resultado

def _marcar_parcial_por_deslinde_oficial(resultado, subregla):
    """No presenta como verificación total lo que exige contraste externo IGAC.

    Los GPKG suministrados incluyen CC_LimiteMunicipio, pero el catálogo 5.12/5.30
    exige además contrastar contra el deslinde oficial IGAC y municipios colindantes.
    Sin esas fuentes externas solo puede certificarse la topología interna de la capa.
    """
    resultado=dict(resultado or {})
    resultado["no_verificable"]=True
    resultado["verificacion_parcial"]=True
    motivo=(f"la subregla {subregla} exige contraste con el deslinde oficial municipal del IGAC "
            "y los límites catastrales de municipios colindantes; esas fuentes externas no fueron suministradas")
    previo=str(resultado.get("motivo_no_verificable","") or "").strip()
    resultado["motivo_no_verificable"]=(previo+"; " if previo else "")+motivo
    msg=str(resultado.get("mensaje","") or "").strip()
    if motivo not in msg:
        resultado["mensaje"]=(msg+" " if msg else "")+"Validación parcial: "+motivo+"."
    return resultado


NPN_FIELDS = ("Numero_Predial", "Numero_Predial_Nacional", "numero_predial", "npn", "NPN")
COND_FIELDS = ("Condicion_Predio", "condicion_predio", "condicion")
ESTADO_FIELDS = ("Estado", "estado_predio", "Estado_Predio", "estado")
TIPO_FIELDS = ("Tipo", "tipo_predio", "Tipo_Predio", "tipo")
DEST_FIELDS = ("Destinacion_Economica", "destinacion_economica", "destino_economico")
COD_HOM_FIELDS = ("codigo_homologado", "Codigo_Homologado", "codigoHomologado")
NUPRE_FIELDS = ("nupre", "NUPRE", "Nupre")
AREA_CAT_FIELDS = ("Area_Catastral_Terreno", "area_catastral_terreno", "area_terreno")
PREDIO_REF_FIELDS = ("predio", "Predio", "arb_predio", "arb_predio_avaluo", "ARB_Predio_Avaluo", "id_predio", "unidad_predial", "predio_asociado")
CONSTRUCCION_REF_FIELDS = ("construccion", "Construccion", "arb_construccion", "id_construccion")
CARAC_REF_FIELDS = ("caracteristicasunidadconstruccion", "CaracteristicasUnidadConstruccion", "caracteristicas", "id_caracteristicas")


def _predios(capas):
    layer = _find_layer(capas, PREDIO_ALIASES)
    return layer, _features(layer)


def _npn(feat):
    return _text(_get(feat, NPN_FIELDS))


def _active(feat):
    s = _norm(_get(feat, ESTADO_FIELDS))
    return not any(x in s for x in ("CANCELADO", "INACTIVO", "RETIRADO", "ELIMINADO"))


def _condition(feat):
    return _norm(_get(feat, COND_FIELDS))


def _ptype(feat):
    return _norm(_get(feat, TIPO_FIELDS))


def _dest(feat):
    return _norm(_get(feat, DEST_FIELDS))


def _predio_index(capas):
    layer, feats = _predios(capas)
    index = {}
    for f in feats:
        keys = set(_entity_keys(f))
        keys.update((_npn(f), _text(_get(f, COD_HOM_FIELDS)), _text(_get(f, NUPRE_FIELDS)), _text(_get(f, ("Id_Operacion", "id_operacion")))))
        for k in keys:
            k = _ref(k)
            if k:
                index[k] = f
    return layer, feats, index


def _linked_predio(feat, pred_idx):
    ref = _ref(_get_raw(feat, PREDIO_REF_FIELDS))
    return pred_idx.get(ref)


def _terrains_by_predio(capas, pred_idx=None):
    layer = _find_layer(capas, TERRENO_ALIASES)
    out = defaultdict(list)
    unlinked = []
    pred_idx = pred_idx or _predio_index(capas)[2]
    for f in _features(layer):
        p = _linked_predio(f, pred_idx)
        if p is None:
            unlinked.append(f)
        else:
            out[_aid(p)].append(f)
    return layer, out, unlinked


def _constructions_by_predio(capas, pred_idx=None):
    layer = _find_layer(capas, CONSTRUCCION_ALIASES)
    out = defaultdict(list)
    unlinked = []
    pred_idx = pred_idx or _predio_index(capas)[2]
    for f in _features(layer):
        p = _linked_predio(f, pred_idx)
        if p is None:
            unlinked.append(f)
        else:
            out[_aid(p)].append(f)
    return layer, out, unlinked


def _ucs_by_construction(capas):
    layer = _find_layer(capas, UC_ALIASES)
    out = defaultdict(list)
    for f in _features(layer):
        out[_ref(_get_raw(f, CONSTRUCCION_REF_FIELDS))].append(f)
    return layer, out


def _ucs_by_predio(capas, pred_idx=None):
    pred_layer, pred_feats, pred_idx = _predio_index(capas) if pred_idx is None else (None, [], pred_idx)
    cons_layer, cons_by_pred, _ = _constructions_by_predio(capas, pred_idx)
    uc_layer, uc_by_cons = _ucs_by_construction(capas)
    result = defaultdict(list)
    for pid, cons in cons_by_pred.items():
        for c in cons:
            vistos = set()
            for ckey in _entity_keys(c):
                for uc in uc_by_cons.get(ckey, []):
                    marker = _aid(uc)
                    if marker not in vistos:
                        result[pid].append(uc)
                        vistos.add(marker)
    return uc_layer, result


def _is_informal_height(feat):
    n = _npn(feat)
    return len(n) >= 30 and n[21] == "2" and n[22:30] != "00000000"


def _is_informal_land(feat):
    n = _npn(feat)
    return len(n) >= 30 and n[21] == "2" and n[22:30] == "00000000"


def _is_urban(feat):
    n = _npn(feat)
    return len(n) >= 7 and n[5:7] != "00"


def _is_rural(feat):
    n = _npn(feat)
    return len(n) >= 7 and n[5:7] == "00"


def _pair_overlap(code, layer, feats, group_key=None, min_area=TOPOLOGY_AREA_TOLERANCE):
    """Detecta superposiciones con poda por bounding box.

    La versión anterior comparaba todos contra todos. En capas como CC_Manzana
    (miles de objetos) eso era muy costoso y podía congelar web. El barrido por
    xmin conserva el resultado geométrico pero solo intersecta candidatos cercanos.
    """
    errors = []
    groups = defaultdict(list)
    if group_key is None:
        groups[None] = list(feats)
    else:
        for f in feats:
            groups[group_key(f)].append(f)
    for key, rows in groups.items():
        entries = []
        for f in rows:
            g = _geom(f)
            if _g_empty(g):
                continue
            b = _g_bounds(g)
            if b is None:
                continue
            entries.append((b[0], b[2], b[1], b[3], f, g, b))
        entries.sort(key=lambda x: x[0])
        active = []
        for entry in entries:
            xmin, xmax, ymin, ymax, feat, geom, bbox = entry
            active = [a for a in active if a[1] >= xmin - EPS]
            for other in active:
                if not _bbox_intersects(bbox, other[6]):
                    continue
                inter = _g_intersection(geom, other[5])
                area = _g_area(inter)
                if area > min_area:
                    feat_1, feat_2 = other[4], feat
                    aid_1, aid_2 = _aid(feat_1), _aid(feat_2)
                    # Orden canónico: el mismo par debe producir el mismo AID principal
                    # en Web y QGIS aunque el barrido espacial visite los objetos al revés.
                    if str(aid_2) < str(aid_1):
                        feat_1, feat_2 = feat_2, feat_1
                        aid_1, aid_2 = aid_2, aid_1
                    micro = area < 1.0
                    prefijo = "Microtraslape" if micro else "Superposición"
                    mensaje = f"{prefijo} geométrico no permitido entre AID {aid_1} y AID {aid_2}; área exacta: {area:.3f} m²."
                    errors.append(_error(
                        code, layer, feat_1, mensaje,
                        otro_aid=aid_2, area_superpuesta=area, grupo=key,
                        clasificacion_geometrica="microtraslape" if micro else "superposicion_material",
                        tolerancia_tecnica_m2=min_area,
                        tipo_geometria_error="superposicion",
                        geometria_error_wkt=_g_wkt(inter),
                    ))
            active.append(entry)
    return errors

def _municipality_code(capas):
    """Obtiene el DIVIPOLA desde una fuente externa al NPN que se valida.

    La prioridad es la capa oficial (CC) Limite municipio del proyecto web.
    No se infiere el codigo tomando el NPN predominante porque eso haria que
    un conjunto completo con el mismo prefijo erroneo se validara a si mismo.
    """
    limite = _find_layer(capas, LIMITE_ALIASES)
    for feat in _features(limite):
        dep = _text(_get(feat, (
            "codigo_departamento", "Codigo_Departamento", "cod_departamento",
            "departamento_codigo", "codigo_dpto", "cod_dpto",
        )))
        mun = _text(_get(feat, (
            "codigo_municipio", "Codigo_Municipio", "cod_municipio",
            "municipio_codigo", "codigo_mpio", "cod_mpio",
        )))
        dep_digits = "".join(ch for ch in dep if ch.isdigit())
        mun_digits = "".join(ch for ch in mun if ch.isdigit())
        if len(dep_digits) >= 2:
            dep_digits = dep_digits[:2]
        if len(mun_digits) >= 5 and dep_digits and mun_digits.startswith(dep_digits):
            mun_digits = mun_digits[-3:]
        elif len(mun_digits) >= 3:
            mun_digits = mun_digits[-3:]
        if len(dep_digits) == 2 and len(mun_digits) == 3:
            return dep_digits + mun_digits
    return ""


def _reference_year(capas):
    years = []
    layer = _find_layer(capas, ("ARB_AvaluoValor", "AvaluoValor", "Avaluo"))
    for f in _features(layer):
        raw = _text(_get(f, ("Fecha_Avaluo_Catastral", "fecha_avaluo_catastral", "vigencia", "Vigencia")))
        m = re.search(r"(?:19|20)\d{2}", raw)
        if m:
            years.append(int(m.group()))
    return max(years) if years else _dt.date.today().year


# -----------------------------------------------------------------------------
# GENERAL: 7, 8, 9, 19, 32, 33
# -----------------------------------------------------------------------------

def regla_7(layer_dict=None, **kwargs):
    capas = _layers(layer_dict)
    code = "7"
    layer, feats = _predios(capas)
    errors = []
    municipality = _municipality_code(capas)
    dep = municipality[:2] if municipality else ""
    if not dep:
        return _not_verifiable(code, "no se cargó una fuente DIVIPOLA cartográfica independiente del NPN (por ejemplo, CC_LimiteMunicipio)")
    for f in feats:
        n = _npn(f)
        if len(n) >= 2 and n[:2] != dep:
            errors.append(_error(code, layer, f, "Las posiciones 1-2 del NPN no corresponden al departamento DIVIPOLA del conjunto de datos.", numero_predial=n, esperado=dep, encontrado=n[:2]))
    return _result(code, errors)


def regla_8(layer_dict=None, **kwargs):
    capas = _layers(layer_dict)
    code = "8"
    layer, feats = _predios(capas)
    errors = []
    municipality = _municipality_code(capas)
    mun = municipality[2:5] if municipality else ""
    if not mun:
        return _not_verifiable(code, "no se cargó una fuente DIVIPOLA cartográfica independiente del NPN (por ejemplo, CC_LimiteMunicipio)")
    for f in feats:
        n = _npn(f)
        if len(n) >= 5 and n[2:5] != mun:
            errors.append(_error(code, layer, f, "Las posiciones 3-5 del NPN no corresponden al municipio DIVIPOLA del conjunto de datos.", numero_predial=n, esperado=mun, encontrado=n[2:5]))
    return _result(code, errors)


def regla_9(layer_dict=None, **kwargs):
    code = "9"
    capas = _layers(layer_dict)
    layer, feats = _predios(capas)
    errors = []
    aplicables = 0
    for f in feats:
        n = _npn(f)
        if len(n) >= 13 and n[5:7] == "00":
            aplicables += 1
            if n[9:13] != "0000":
                errors.append(_error(code, layer, f, "Cuando las posiciones 6-7 del NPN son '00', las posiciones 10-13 deben ser '0000'.", numero_predial=n, valor_6_7=n[5:7], valor_10_13=n[9:13]))
    if aplicables == 0:
        return _result(code, [], "Regla SINIC 9: no hay predios con posiciones 6-7 iguales a '00'.", no_aplica=True)
    return _result(code, errors)


def _coverage_rule(code, capas, child_aliases, parent_aliases, child_filter=None, tolerance_ratio=0.0):
    child_layer = _find_layer(capas, child_aliases)
    parent_layer = _find_layer(capas, parent_aliases)
    children = [f for f in _features(child_layer) if child_filter is None or child_filter(f)]
    parents = _features(parent_layer)
    if not children:
        return _result(code, [], f"Regla SINIC {code}: no hay elementos aplicables en el XTF.", no_aplica=True)
    if not parents:
        return _not_verifiable(code, f"no se encontró la capa de referencia ({', '.join(parent_aliases)})")
    child_union = _union([_geom(f) for f in children])
    parent_union = _union([_geom(f) for f in parents])
    if _g_empty(child_union) or _g_empty(parent_union):
        return _not_verifiable(code, "las geometrías requeridas están vacías")
    missing_parent = _g_difference(parent_union, child_union)
    outside_child = _g_difference(child_union, parent_union)
    mismatch = _g_area(missing_parent) + _g_area(outside_child)
    base = max(_g_area(parent_union), EPS)
    ratio = mismatch / base
    if ratio <= tolerance_ratio + EPS:
        return _result(code, [])
    err = _error(code, child_layer, children[0], "El cubrimiento geográfico no cumple la tolerancia exigida.", area_diferencia=mismatch, porcentaje_diferencia=ratio * 100.0, tolerancia_porcentaje=tolerance_ratio * 100.0, capa_referencia=_layer_name(parent_layer))
    return _result(code, [err])


def regla_19(layer_dict=None, **kwargs):
    """Cobertura frente al límite municipal sin falsos positivos en XTF parciales.

    Para un XTF de asignación parcial sí puede afirmarse si un terreno cae por fuera
    del límite; no puede afirmarse que falte el resto del municipio. La comparación
    total del 5% solo se aplica si el conjunto cubre al menos el 95% del límite o si
    el llamador declara ``dataset_completo=True``.
    """
    capas = _layers(layer_dict)
    terrain_layer = _find_layer(capas, TERRENO_ALIASES)
    terrain_feats = _features(terrain_layer)
    _, _, pred_idx = _predio_index(capas)
    active_terrains = []
    for t in terrain_feats:
        p = _linked_predio(t, pred_idx)
        if p is None or _active(p):
            active_terrains.append(t)
    if not active_terrains:
        return _result("19", [], "Regla SINIC 19: no hay terrenos activos aplicables.", no_aplica=True)
    boundary = _find_layer(capas, LIMITE_ALIASES)
    if boundary is None:
        return _not_verifiable("19", "no se cargó la cartografía externa CC_LimiteMunicipio para contrastar la cobertura")
    bu = _union([_geom(f) for f in _features(boundary)])
    tu = _union([_geom(f) for f in active_terrains])
    if _g_empty(bu) or _g_empty(tu):
        return _not_verifiable("19", "el límite municipal o los terrenos no contienen geometría")
    faltante = _g_difference(bu, tu)
    excedente = _g_difference(tu, bu)
    area_limite = max(_g_area(bu), EPS)
    area_faltante = _g_area(faltante)
    area_excedente = _g_area(excedente)
    cobertura = max(0.0, 1.0 - area_faltante / area_limite)
    dataset_completo = bool(kwargs.get("dataset_completo")) or cobertura >= 0.95 - EPS
    errors = []
    if area_excedente > TOPOLOGY_AREA_TOLERANCE:
        errors.append(_error(
            "19", terrain_layer, active_terrains[0],
            f"Se detectaron {area_excedente:.3f} m² de terreno activo por fuera del límite municipal.",
            area_fuera_limite=area_excedente, cobertura_limite_porcentaje=cobertura * 100.0,
            tipo_geometria_error="fuera_cobertura", geometria_error_wkt=_g_wkt(excedente),
            capa_referencia=_layer_name(boundary), tolerancia_tecnica_m2=TOPOLOGY_AREA_TOLERANCE,
        ))
    if dataset_completo:
        mismatch = area_faltante + area_excedente
        ratio = mismatch / area_limite
        if ratio > 0.05 + EPS:
            geom_diferencia = _g_combine(faltante, excedente)
            errors.append(_error(
                "19", terrain_layer, active_terrains[0],
                f"La cobertura total de terrenos activos difiere del límite municipal en {ratio * 100.0:.2f}% (máximo permitido: 5%).",
                porcentaje_diferencia=ratio * 100.0, tolerancia_porcentaje=5.0, area_diferencia=mismatch,
                tipo_geometria_error="diferencia_cobertura", geometria_error_wkt=_g_wkt(geom_diferencia),
                capa_referencia=_layer_name(boundary),
            ))
        return _result("19", errors)
    result = _result(
        "19", errors,
        f"Validación parcial: el XTF cubre aproximadamente {cobertura * 100.0:.2f}% del límite municipal. "
        "Se comprobó que los terrenos cargados no salgan del límite, pero no se interpreta como error la parte del municipio que no viene en este XTF.",
        no_verificable=True, verificacion_parcial=True,
        motivo_no_verificable="el XTF cargado representa una cobertura parcial del municipio",
    )
    return result


def _regla_cobertura_terreno_referencia(code, capas, terrenos, t_layer, ref_aliases, ref_label, dataset_completo=False):
    ref_layer = _find_layer(capas, ref_aliases)
    if ref_layer is None:
        return _not_verifiable(code, f"no se cargó la cartografía externa {ref_label}")
    ref_union = _union([_geom(f) for f in _features(ref_layer)])
    terrain_union = _union([_geom(f) for f in terrenos])
    if _g_empty(ref_union) or _g_empty(terrain_union):
        return _not_verifiable(code, "las geometrías requeridas están vacías")
    errors = []
    for t in terrenos:
        g = _geom(t)
        if _g_empty(g):
            continue
        fuera = _g_difference(g, ref_union)
        area_fuera = _g_area(fuera)
        if area_fuera > TOPOLOGY_AREA_TOLERANCE:
            errors.append(_error(
                code, t_layer, t,
                f"El terreno presenta {area_fuera:.3f} m² por fuera de la cobertura de {ref_label}.",
                area_fuera_referencia=area_fuera, capa_referencia=_layer_name(ref_layer),
                tolerancia_tecnica_m2=TOPOLOGY_AREA_TOLERANCE,
                tipo_geometria_error="fuera_cobertura", geometria_error_wkt=_g_wkt(fuera),
            ))
    if dataset_completo:
        faltante = _g_difference(ref_union, terrain_union)
        excedente = _g_difference(terrain_union, ref_union)
        mismatch = _g_area(faltante) + _g_area(excedente)
        if mismatch > TOPOLOGY_AREA_TOLERANCE:
            geom_diferencia = _g_combine(faltante, excedente)
            errors.append(_error(
                code, t_layer, terrenos[0],
                f"La cobertura mutua entre terrenos y {ref_label} presenta una diferencia de {mismatch:.3f} m².",
                area_diferencia=mismatch, capa_referencia=_layer_name(ref_layer),
                tipo_geometria_error="diferencia_cobertura", geometria_error_wkt=_g_wkt(geom_diferencia),
            ))
        return _result(code, errors)
    return _result(
        code, errors,
        f"Validación parcial: se comprobó la ubicación de cada terreno frente a {ref_label}. "
        "La cobertura mutua completa no se exige sobre un XTF de asignación parcial.",
        no_verificable=True, verificacion_parcial=True,
        motivo_no_verificable="la cobertura mutua completa requiere un conjunto municipal completo",
    )


def regla_32(layer_dict=None, **kwargs):
    capas = _layers(layer_dict)
    _, _, pred_idx = _predio_index(capas)
    t_layer = _find_layer(capas, TERRENO_ALIASES)
    urban = [t for t in _features(t_layer) if (lambda p: p is not None and _is_urban(p))(_linked_predio(t, pred_idx))]
    if not urban:
        return _result("32", [], "Regla SINIC 32: no hay terrenos urbanos aplicables.", no_aplica=True)
    return _regla_cobertura_terreno_referencia("32", capas, urban, t_layer, MANZANA_ALIASES, "CC_Manzana", bool(kwargs.get("dataset_completo")))


def regla_33(layer_dict=None, **kwargs):
    capas = _layers(layer_dict)
    _, _, pred_idx = _predio_index(capas)
    t_layer = _find_layer(capas, TERRENO_ALIASES)
    rural = [t for t in _features(t_layer) if (lambda p: p is not None and _is_rural(p))(_linked_predio(t, pred_idx))]
    if not rural:
        return _result("33", [], "Regla SINIC 33: no hay terrenos rurales aplicables.", no_aplica=True)
    return _regla_cobertura_terreno_referencia("33", capas, rural, t_layer, VEREDA_ALIASES, "CC_Vereda", bool(kwargs.get("dataset_completo")))


# -----------------------------------------------------------------------------
# FÍSICO: reglas faltantes
# -----------------------------------------------------------------------------

def regla_5(layer_dict=None, **kwargs):
    capas = _layers(layer_dict); layer = _find_layer(capas, UC_ALIASES); feats = _features(layer)
    # 5.31: la comparación solo aplica entre UC de la MISMA construcción,
    # planta y tipo de planta. Una FK ausente no autoriza a mezclar huérfanas.
    def key(f):
        cref = _ref(_get_raw(f, CONSTRUCCION_REF_FIELDS)) or f"__SIN_CONSTRUCCION__:{_aid(f)}"
        return (cref, _norm(_get(f, ("Tipo_Planta", "tipo_planta"))), _text(_get(f, ("Planta_Ubicacion", "planta_ubicacion"))))
    return _result("5", _pair_overlap("5", layer, feats, key))


def regla_20(layer_dict=None, **kwargs):
    capas = _layers(layer_dict); p_layer, p_feats, pidx = _predio_index(capas); t_layer = _find_layer(capas, TERRENO_ALIASES)
    applicable = []
    for t in _features(t_layer):
        p = _linked_predio(t, pidx)
        if p is None or not _is_informal_height(p) and not _is_informal_land(p):
            applicable.append(t)
    return _result("20", _pair_overlap("20", t_layer, applicable))


def regla_22(layer_dict=None, **kwargs):
    capas = _layers(layer_dict); layer = _find_layer(capas, UC_ALIASES); errors = []
    for f in _features(layer):
        g = _geom(f)
        if not _g_empty(g) and _g_area(g) < 0.5 - EPS:
            errors.append(_error("22", layer, f, "La Unidad de Construcción tiene un área geométrica menor a 0,5 m².", area_geometrica=_g_area(g), umbral=0.5))
    return _result("22", errors)


def regla_23(layer_dict=None, **kwargs):
    """Detecta vacíos *entre* Unidades de Construcción adyacentes.

    Un anillo interior de una sola Unidad no se considera por sí mismo un error de
    esta regla: puede representar un patio/vacío constructivo real. La regla SINIC
    23 habla de huecos entre polígonos adyacentes, por lo que se evalúan grupos de
    dos o más UC de la misma construcción y planta.
    """
    capas=_layers(layer_dict); layer=_find_layer(capas,UC_ALIASES); errors=[]
    feats=[f for f in _features(layer) if not _g_empty(_geom(f))]
    groups=defaultdict(list)
    for f in feats:
        cref=_ref(_get_raw(f,CONSTRUCCION_REF_FIELDS))
        # Si la relación con Construcción no está expuesta por el proveedor,
        # no se deben mezclar todas las UC sin referencia en un mismo grupo.
        # Se usa el AID como clave aislada para evitar huecos falsos.
        group_cref = cref or f"__SIN_CONSTRUCCION__:{_aid(f)}"
        tipo=_norm(_get(f,("Tipo_Planta","tipo_planta")))
        planta=_text(_get(f,("Planta_Ubicacion","planta_ubicacion")))
        groups[(group_cref,tipo,planta)].append(f)

    for (cref,tipo,planta),rows in groups.items():
        if len(rows)<2:
            continue
        union=_union([_geom(f) for f in rows])
        huecos=_g_hole_geometries(union)
        for indice,geom_hueco in enumerate(huecos,start=1):
            area_hueco=_g_area(geom_hueco)
            if area_hueco<=EPS:
                continue
            errors.append(_error(
                "23",layer,rows[0],
                f"Se detectó un vacío de {area_hueco:.3f} m² entre Unidades de Construcción adyacentes de la misma planta.",
                construccion_ref=cref,tipo_planta=tipo,planta_ubicacion=planta,
                cantidad_unidades=len(rows),indice_hueco=indice,area_vacio=area_hueco,
                tipo_geometria_error="hueco_entre_unidades",
                geometria_error_wkt=_g_wkt(geom_hueco),aids_grupo=[_aid(x) for x in rows],
            ))
    return _result("23",errors)


def regla_24(layer_dict=None, **kwargs):
    capas = _layers(layer_dict); layer = _find_layer(capas, UC_ALIASES); errors = []
    for f in _features(layer):
        # Esta regla debe inspeccionar la geometría ORIGINAL. Usar _geom() aquí
        # reparaba con makeValid() antes de validar y ocultaba geometrías inválidas.
        g = _geom_raw(f)
        if not _g_empty(g) and not _g_valid(g):
            errors.append(_error("24", layer, f, "La geometría de la Unidad de Construcción no es válida."))
    return _result("24", errors)


def regla_25(layer_dict=None, **kwargs):
    capas = _layers(layer_dict); layer = _find_layer(capas, UC_ALIASES); errors = []
    for f in _features(layer):
        uso = _norm(_get(f, ("Uso", "uso", "uso_construccion")))
        etiqueta = _norm(_get(f, ("Etiqueta", "etiqueta", "Identificador")))
        uncovered = ("PARQUEADERO" in uso or "GARAJE" in uso or "PARQUEADERO" in etiqueta) and ("DESCUBIERTO" in uso or "DESCUBIERTO" in etiqueta)
        if not uncovered and _g_empty(_geom(f)):
            errors.append(_error("25", layer, f, "La Unidad de Construcción debe tener geometría asociada, excepto parqueaderos descubiertos."))
    return _result("25", errors)


def _remap_result_code(result, old_code, new_code):
    out=dict(result); remapped=[]
    for original in out.get("errores",[]) or []:
        e=dict(original); e["regla"]=str(new_code)
        d=dict(e.get("detalles") or e.get("details") or {}); d["sinic_id"]=str(new_code); d["sinic_abreviatura"]=_meta(new_code).get("abbreviation","")
        e["detalles"]=d; e["details"]=d; remapped.append(e)
    out["errores"]=remapped; out["regla_sinic"]=_meta(new_code)
    out["mensaje"]=_text(out.get("mensaje")).replace(f"SINIC {old_code}",f"SINIC {new_code}").replace(f"regla {old_code}",f"regla {new_code}")
    return out

def regla_26(layer_dict=None, **kwargs): return _remap_result_code(regla_32(layer_dict=layer_dict, **kwargs),"32","26")
def regla_27(layer_dict=None, **kwargs): return _remap_result_code(regla_33(layer_dict=layer_dict, **kwargs),"33","27")


def _rights_by_predio(capas):
    # Resuelve la FK contra todas las claves estables del predio (t_id, t_ili_tid, NPN, etc.).
    layer, out, _ = arb_model.rows_by_predio(capas, DERECHO_ALIASES, PREDIO_REF_FIELDS)
    return layer, out


def _rights_type(rows):
    vals = []
    for r in rows:
        vals.append(_norm(_get(r, ("D_Tipo", "d_tipo", "Tipo_Derecho", "tipo_derecho", "derecho_tipo"))))
    return vals


def _regla_superposicion_derecho(code, capas, derecho_objetivo, tipo_contraparte, dataset_completo=False):
    """Valida Posesión/Ocupación sin convertir un XTF parcial en falso positivo.

    Una ausencia de superposición solo es un incumplimiento demostrable cuando el
    conjunto está declarado completo. En un XTF de asignación puede no venir el
    terreno del predio informal o la contraparte catastral; en ese caso la regla
    queda como verificación parcial, no como error.
    """
    p_layer, preds, pidx = _predio_index(capas)
    t_layer, t_by_p, _ = _terrains_by_predio(capas, pidx)
    _, rights = _rights_by_predio(capas)
    errors=[]; unresolved=[]

    counterpart=[]
    for p in preds:
        # La contraparte espacial debe ser otro predio, no el propio informal.
        if tipo_contraparte in _ptype(p):
            for t in t_by_p.get(_aid(p), []):
                g=_geom(t)
                if not _g_empty(g): counterpart.append((_aid(p), t, g))

    for p in preds:
        if not _active(p):
            continue
        if not any(derecho_objetivo in x for x in _rights_type(rights.get(_aid(p), []))):
            continue
        terrenos=[t for t in t_by_p.get(_aid(p), []) if not _g_empty(_geom(t))]
        if not terrenos:
            unresolved.append(f"{_aid(p)}: el predio con {derecho_objetivo.title()} no trae terreno geométrico en este XTF")
            continue
        candidatos=[g for aid,_,g in counterpart if aid != _aid(p)]
        if not candidatos:
            unresolved.append(f"{_aid(p)}: no hay una contraparte {tipo_contraparte.title()} distinta y con geometría en este XTF")
            continue
        union=_union(candidatos)
        intersects=any(_g_intersects(_geom(t), union) for t in terrenos)
        if intersects:
            continue
        if not dataset_completo:
            unresolved.append(f"{_aid(p)}: no se encontró superposición dentro del XTF parcial; falta demostrar que esté incluida la contraparte espacial requerida")
            continue
        obj=terrenos[0]
        errors.append(_error(
            code, t_layer, obj,
            f"El predio activo con derecho de {derecho_objetivo.title()} no presenta la superposición total o parcial exigida con un predio de tipo {tipo_contraparte.title()}.",
            predio_aid=_aid(p), numero_predial=_npn(p), tipo_geometria_error="sin_superposicion",
            aids_grupo=[_aid(t) for t in terrenos],
        ))

    if unresolved:
        return _resultado_parcial(code, errors, "; ".join(unresolved))
    return _result(code, errors)


def regla_28(layer_dict=None, **kwargs):
    return _regla_superposicion_derecho("28", _layers(layer_dict), "POSESION", "PRIVADO", bool(kwargs.get("dataset_completo")))


def regla_29(layer_dict=None, **kwargs):
    return _regla_superposicion_derecho("29", _layers(layer_dict), "OCUPACION", "PUBLICO", bool(kwargs.get("dataset_completo")))


def regla_42(layer_dict=None, **kwargs):
    return _source_obl("42", "11.2", _layers(layer_dict))


def regla_43(layer_dict=None, **kwargs):
    capas = _layers(layer_dict); layer, feats = _predios(capas); seen = {}; errors=[]
    for f in feats:
        if not _active(f): continue
        value = _text(_get(f, COD_HOM_FIELDS))
        if not value:
            errors.append(_error("43", layer, f, "Todo predio activo debe tener Código Homologado diligenciado.")); continue
        key = value.upper()
        if key in seen:
            errors.append(_error("43", layer, f, "El Código Homologado debe ser único en la base catastral.", codigo_homologado=value, duplicado_con=_aid(seen[key])))
        else: seen[key]=f
    result = _result("43", errors)
    if not bool(kwargs.get("dataset_completo")):
        return _resultado_parcial("43", errors, "la unicidad en toda la base catastral no puede descartarse usando únicamente un XTF de asignación")
    return result


def regla_44(layer_dict=None, **kwargs):
    capas = _layers(layer_dict); layer, feats = _predios(capas); errors=[]
    for f in feats:
        if not _active(f): continue
        nupre, cod = _text(_get(f, NUPRE_FIELDS)), _text(_get(f, COD_HOM_FIELDS))
        if nupre and nupre != cod:
            errors.append(_error("44", layer, f, "El NUPRE del predio activo debe coincidir exactamente con su Código Homologado.", nupre=nupre, codigo_homologado=cod))
    return _result("44", errors)


def regla_57(layer_dict=None, **kwargs):
    capas = _layers(layer_dict); layer, feats = _predios(capas); errors=[]
    for f in feats:
        if "PUBLICO" in _ptype(f) and "USOPUBLICO" in _ptype(f):
            cond = _condition(f)
            if "BIENUSOPUBLICO" not in cond and "VIA" not in cond:
                errors.append(_error("57", layer, f, "Los predios de tipo Público Uso Público deben tener condición Bien_Uso_Publico o Vía.", condicion=_text(_get(f, COND_FIELDS))))
    return _result("57", errors)


def regla_58(layer_dict=None, **kwargs):
    capas = _layers(layer_dict); layer, feats = _predios(capas); errors=[]
    targets=("LOTEURBANIZADONOCONSTRUIDO","URBANIZABLENOURBANIZADO")
    for f in feats:
        if any(x in _dest(f) for x in targets) and not _is_urban(f):
            errors.append(_error("58", layer, f, "La destinación indicada exige ubicación en suelo urbano según el NPN.", numero_predial=_npn(f), destinacion=_text(_get(f, DEST_FIELDS))))
    return _result("58", errors)


def regla_59(layer_dict=None, **kwargs):
    capas = _layers(layer_dict); layer, feats = _predios(capas); errors=[]
    for f in feats:
        if "LOTERURAL" in _dest(f) and not _is_rural(f):
            errors.append(_error("59", layer, f, "Un predio con destinación Lote Rural no debe estar en suelo urbano según el NPN.", numero_predial=_npn(f)))
    return _result("59", errors)


def regla_61(layer_dict=None, **kwargs):
    capas = _layers(layer_dict); p_layer, preds, pidx = _predio_index(capas); _, t_by_p, _ = _terrains_by_predio(capas, pidx); errors=[]
    for p in preds:
        if _is_informal_height(p) and t_by_p.get(_aid(p)):
            errors.append(_error("61", p_layer, p, "El predio informal en construcción no debe tener terreno asociado.", terrenos_asociados=len(t_by_p[_aid(p)])))
    return _result("61", errors)


def regla_62(layer_dict=None, **kwargs):
    capas = _layers(layer_dict); p_layer, preds, pidx = _predio_index(capas); _, t_by_p, _ = _terrains_by_predio(capas, pidx); _, uc_by_p = _ucs_by_predio(capas, pidx); errors=[]
    for p in preds:
        informal = len(_npn(p))>=22 and _npn(p)[21]=='2'
        if informal and not t_by_p.get(_aid(p)):
            ucs=uc_by_p.get(_aid(p),[])
            if not any(not _g_empty(_geom(u)) for u in ucs):
                errors.append(_error("62", p_layer, p, "El predio informal sin terreno debe tener al menos una Unidad de Construcción con geometría."))
    return _result("62", errors)


def regla_63(layer_dict=None, **kwargs):
    capas = _layers(layer_dict); p_layer, preds, pidx = _predio_index(capas); _, t_by_p, _ = _terrains_by_predio(capas, pidx); errors=[]
    for p in preds:
        if _is_informal_land(p) and not t_by_p.get(_aid(p)):
            errors.append(_error("63", p_layer, p, "El predio informal sobre terreno debe tener terreno asociado."))
    return _result("63", errors)


def regla_64(layer_dict=None, **kwargs):
    capas = _layers(layer_dict); layer, preds = _predios(capas); groups=defaultdict(dict); errors=[]
    for p in preds:
        if not _is_informal_land(p): continue
        n=_npn(p)
        if len(n)<21: continue
        group=n[:13]; val=n[17:21]
        if val in groups[group]:
            errors.append(_error("64", layer, p, "Las posiciones 18-21 del NPN no deben repetirse para predios informales con terreno dentro de la misma manzana/vereda.", numero_predial=n, valor_18_21=val, duplicado_con=_aid(groups[group][val])))
        else: groups[group][val]=p
    result = _result("64", errors)
    if not bool(kwargs.get("dataset_completo")):
        return _resultado_parcial("64", errors, "la unicidad frente a predios informales fuera del XTF no puede descartarse sin la base catastral completa")
    return result


def regla_81(layer_dict=None, **kwargs):
    capas=_layers(layer_dict); layer=_find_layer(capas,UC_ALIASES); errors=[]
    for f in _features(layer):
        if not _g_empty(_geom(f)):
            h=_float(_get(f,("Altura","altura")))
            if h is None or h<=0: errors.append(_error("81",layer,f,"La Unidad de Construcción con geometría debe tener altura mayor a 0.",altura=h))
    return _result("81",errors)


def regla_82(layer_dict=None, **kwargs):
    capas=_layers(layer_dict); layer=_find_layer(capas,CARAC_ALIASES); errors=[]
    for f in _features(layer):
        a=_float(_get(f,("Area_Construida","area_construida","area")))
        if a is None or a<=0: errors.append(_error("82",layer,f,"Las Características de Unidad de Construcción exigen área construida mayor a 0.",area_construida=a))
    return _result("82",errors)


def regla_83(layer_dict=None, **kwargs):
    capas=_layers(layer_dict); layer=_find_layer(capas,CARAC_ALIASES); errors=[]
    fields=("Estado_Conservacion","estado_conservacion","CC_Conservacion_Estructura","CC_Conservacion_Acabados","CT_Conservacion_Tipologia","CNC_Conservacion_Anexo")
    bad={"NINGUNO","NOTIENE","NINGUNA","SINCONSERVACION"}
    for f in _features(layer):
        vals=[_get(f,(field,)) for field in fields]
        present=[v for v in vals if _text(v)]
        if not present or any(_norm(v) in bad for v in present):
            errors.append(_error("83",layer,f,"El estado de conservación debe estar definido y ser diferente de 'Ninguno'/'No tiene'.",valores=[_text(v) for v in present]))
    return _result("83",errors)


def regla_84(layer_dict=None, **kwargs):
    """Construcciones en vigencia >= 2026 deben tener avalúo de caracterización.

    En Captura_ArbiMaps la vigencia se obtiene del ARB_AvaluoValor más reciente del
    predio. El valor de caracterización se toma de
    Avaluo_Catastral_Total_Unidades_Construccion cuando el modelo no materializa un
    campo específico en ARB_Construccion.
    """
    capas=_layers(layer_dict); code="84"
    cons_layer=_find_layer(capas,CONSTRUCCION_ALIASES); av_layer=_find_layer(capas,("ARB_AvaluoValor","AvaluoValor","Avaluo"))
    _,_,pidx=_predio_index(capas); errors=[]
    av_by_pred=defaultdict(list)
    for a in _features(av_layer):
        pref=_ref(_get_raw(a,PREDIO_REF_FIELDS))
        date=_text(_get(a,("Fecha_Avaluo_Catastral","fecha_avaluo_catastral","Vigencia","vigencia")))
        m=re.search(r"(?:19|20)\d{2}",date); year=int(m.group()) if m else None
        if pref and year is not None: av_by_pred[pref].append((year,a))
    for c in _features(cons_layer):
        pref=_ref(_get_raw(c,PREDIO_REF_FIELDS)); p=pidx.get(pref)
        candidates=list(av_by_pred.get(pref,[]))
        if p is not None:
            candidates += av_by_pred.get(_aid(p),[]) + av_by_pred.get(_npn(p),[])
        if not candidates:
            # Si no hay histórico de avalúo no puede determinarse la vigencia aplicable.
            continue
        year,a=max(candidates,key=lambda x:x[0])
        if year<2026: continue
        direct=_float(_get(c,("Avaluo_Caracterizacion","avaluo_caracterizacion","Valor_Avaluo_Caracterizacion","avaluo_construccion")))
        linked=_float(_get(a,("Avaluo_Catastral_Total_Unidades_Construccion","avaluo_catastral_total_unidades_construccion")))
        value=direct if direct is not None else linked
        if value is None or value<=0:
            errors.append(_error(code,cons_layer,c,"La construcción en vigencia >= 2026 debe tener avalúo de caracterización.",vigencia=year,avaluo_caracterizacion=value,predio_ref=pref))
    if _features(cons_layer) and not _features(av_layer):
        return _not_verifiable(code,"no se encontró ARB_AvaluoValor para determinar vigencia y avalúo de caracterización")
    return _result(code,errors)

def regla_85(layer_dict=None, **kwargs):
    capas=_layers(layer_dict); layer=_find_layer(capas,CARAC_ALIASES); year=_reference_year(capas); errors=[]
    for f in _features(layer):
        y=_int(_get(f,("Anio_Construccion","anio_construccion","Ano_Construccion","ano_construccion")))
        if y is None or y>year:
            errors.append(_error("85",layer,f,"El año de construcción debe estar definido y ser menor o igual al año del reporte.",anio_construccion=y,anio_reporte=year))
    return _result("85",errors)


def regla_86(layer_dict=None, **kwargs):
    """2_CLC_CF_86: terreno obligatorio para predios activos no exceptuados."""
    capas = _layers(layer_dict)
    p_layer, preds, pidx = _predio_index(capas)
    _, terrenos_por_predio, _ = _terrains_by_predio(capas, pidx)
    errors = []

    excepciones = (
        "PHUNIDADPREDIAL",
        "PARQUECEMENTERIOUNIDADPREDIAL",
        "CEMENTERIOUNIDADPREDIAL",
        "INFORMALENALTURA",
    )

    for p in preds:
        estado = _norm(_get(p, ESTADO_FIELDS))
        if estado not in ("ACTIVO", "105"):
            continue
        npn = _npn(p)
        condicion = _condition(p)
        exento_npn = len(npn) < 22 or npn[21] != "5"
        exento_condicion = condicion in ("62", "67") or any(
            nombre in condicion for nombre in excepciones
        )
        exento_altura = _is_informal_height(p)
        if exento_npn or exento_condicion or exento_altura:
            continue
        if not terrenos_por_predio.get(_aid(p)):
            errors.append(
                _error(
                    "86",
                    p_layer,
                    p,
                    "Predio activo sin terreno asociado; "
                    "no aplica ninguna excepcion de la regla 86."
                )
            )
    return _result("86", errors)


def regla_87(layer_dict=None, **kwargs):
    """2_CLC_CF_87: area catastral positiva en predios activos no exentos."""
    capas = _layers(layer_dict)
    layer, preds = _predios(capas)
    errors = []
    excepciones = (
        "PHUNIDADPREDIAL",
        "PARQUECEMENTERIOUNIDADPREDIAL",
        "CEMENTERIOUNIDADPREDIAL",
        "INFORMALENALTURA",
    )
    for p in preds:
        estado = _norm(_get(p, ESTADO_FIELDS))
        if estado not in ("ACTIVO", "105"):
            continue
        npn = _npn(p)
        condicion = _condition(p)
        exento_npn = len(npn) < 22 or npn[21] != "5"
        exento_condicion = condicion in ("62", "67") or any(
            nombre in condicion for nombre in excepciones
        )
        exento_altura = _is_informal_height(p)
        if exento_npn or exento_condicion or exento_altura:
            continue
        area = _float(_get(p, AREA_CAT_FIELDS))
        if area is None or area <= 0:
            errors.append(
                _error(
                    "87",
                    layer,
                    p,
                    "Predio activo con area catastral de terreno "
                    "nula o menor o igual a cero; "
                    "no aplica ninguna excepcion de la regla 87.",
                    area_catastral_terreno=area,
                )
            )
    return _result("87", errors)


def regla_106(layer_dict=None, **kwargs):
    capas=_layers(layer_dict); p_layer,preds,pidx=_predio_index(capas); _,t_by_p,_=_terrains_by_predio(capas,pidx); errors=[]
    targets=("PHMATRIZ","CONDOMINIOMATRIZ","CEMENTERIOMATRIZ")
    for p in preds:
        if any(x in _condition(p) for x in targets) and not t_by_p.get(_aid(p)):
            errors.append(_error("106",p_layer,p,"Los predios PH Matriz, Condominio Matriz o Cementerio Matriz deben tener terreno asociado."))
    return _result("106",errors)


def regla_108(layer_dict=None, **kwargs):
    capas=_layers(layer_dict); p_layer,preds,pidx=_predio_index(capas); t_layer,t_by_p,_=_terrains_by_predio(capas,pidx); errors=[]
    for p in preds:
        cat=_float(_get(p,AREA_CAT_FIELDS)); terrains=t_by_p.get(_aid(p),[])
        if cat is None or cat<=0 or not terrains: continue
        geo=sum(_g_area(_geom(t)) for t in terrains)
        diff=abs(geo-cat)/cat if cat else math.inf
        if diff>0.10+EPS: errors.append(_error("108",p_layer,p,"La diferencia entre el área geométrica y el área catastral del terreno supera el 10%.",area_geometrica=geo,area_catastral=cat,diferencia_porcentaje=diff*100.0))
    return _result("108",errors)


def regla_112(layer_dict=None, **kwargs): return _source_admin("112","1.40",_layers(layer_dict))

def regla_114(layer_dict=None, **kwargs):
    capas=_layers(layer_dict); p_layer,preds,pidx=_predio_index(capas); info_layer=_find_layer(capas,INFO_PH_ALIASES); byp=defaultdict(list); errors=[]
    for info in _features(info_layer):
        byp[_ref(_get_raw(info,PREDIO_REF_FIELDS + ("arb_predio","cca_predio")))].append(info)
    for p in preds:
        cond=_condition(p); is_matrix=("PHMATRIZ" in cond or "CONDOMINIOMATRIZ" in cond or (_npn(p)[21:30] in {"800000000","900000000"} if len(_npn(p))>=30 else False))
        if not is_matrix: continue
        infos=byp.get(_aid(p),[])+byp.get(_npn(p),[])
        if not infos:
            errors.append(_error("114",p_layer,p,"Los predios PH Matriz o Condominio Matriz deben tener datos especiales de matriz (Información PH) diligenciados."))
            continue
        info=infos[0]
        required=("Area_Total_Terreno","Area_Total_Construida","Numero_Torres","Total_Unidades_Privadas")
        missing=[x for x in required if not _text(_get(info,(x,x.lower())))]
        if missing: errors.append(_error("114",info_layer,info,"Los datos especiales de la matriz están incompletos.",campos_faltantes=missing,predio_matriz=_aid(p)))
    return _result("114",errors)


def regla_115(layer_dict=None, **kwargs):
    capas=_layers(layer_dict); p_layer,preds,pidx=_predio_index(capas); cop_layer=_find_layer(capas,COPROPIEDAD_ALIASES); byp=defaultdict(list)
    for c in _features(cop_layer): byp[_ref(_get_raw(c,PREDIO_REF_FIELDS))].append(c)
    errors=[]; targets=("PHUNIDADPREDIAL","CONDOMINIOUNIDADPREDIAL","CEMENTERIOUNIDADPREDIAL")
    for p in preds:
        if any(x in _condition(p) for x in targets):
            candidates=byp.get(_aid(p),[])+byp.get(_npn(p),[])
            if not candidates: errors.append(_error("115",p_layer,p,"El predio UP debe tener datos de Predio Copropiedad diligenciados."))
    return _result("115",errors)


def regla_116(layer_dict=None, **kwargs):
    capas=_layers(layer_dict); layer,preds=_predios(capas); municipality=_municipality_code(capas); errors=[]
    # Prefijos confirmados/soportados por la configuración local. Para municipios no
    # incluidos se infiere el prefijo dominante del mismo XTF y se valida consistencia.
    official={"41001":"BFP"}
    expected=official.get(municipality,"")
    if not expected:
        pref=[_text(_get(p,COD_HOM_FIELDS))[:3].upper() for p in preds if len(_text(_get(p,COD_HOM_FIELDS)))>=3]
        expected=Counter(pref).most_common(1)[0][0] if pref else ""
    if not expected: return _not_verifiable("116","no fue posible determinar el prefijo esperado del Código Homologado")
    for p in preds:
        cod=_text(_get(p,COD_HOM_FIELDS))
        if cod and cod[:3].upper()!=expected:
            errors.append(_error("116",layer,p,"El prefijo del Código Homologado no corresponde al municipio.",codigo_homologado=cod,prefijo_esperado=expected,municipio_divipola=municipality))
    return _result("116",errors)


def regla_125(layer_dict=None, **kwargs):
    capas=_layers(layer_dict); p_layer,preds,pidx=_predio_index(capas); _,t_by_p,_=_terrains_by_predio(capas,pidx); errors=[]
    for p in preds:
        cond=_condition(p)
        if ("NPH" in cond or "CONDOMINIOUNIDADPREDIAL" in cond) and not t_by_p.get(_aid(p)):
            errors.append(_error("125",p_layer,p,"El predio NPH o Condominio UP debe tener terreno asociado."))
    return _result("125",errors)


def regla_126(layer_dict=None, **kwargs):
    capas=_layers(layer_dict); p_layer,preds,pidx=_predio_index(capas); t_layer=_find_layer(capas,TERRENO_ALIASES); errors=[]
    for t in _features(t_layer):
        p=_linked_predio(t,pidx)
        if p is None or not _active(p): errors.append(_error("126",t_layer,t,"Todo terreno debe estar asociado al menos a un predio activo.",predio_ref=_ref(_get_raw(t,PREDIO_REF_FIELDS))))
    return _result("126",errors)


def regla_127(layer_dict=None, **kwargs):
    capas=_layers(layer_dict); layer=_find_layer(capas,COPROPIEDAD_ALIASES); errors=[]
    for f in _features(layer):
        c=_float(_get(f,("coeficiente","Coeficiente","coeficiente_copropiedad","Coeficiente_Copropiedad")))
        if c is None or c<=0: errors.append(_error("127",layer,f,"En Predio Copropiedad, el coeficiente debe ser mayor a 0.",coeficiente=c))
    return _result("127",errors)


def regla_134(layer_dict=None, **kwargs):
    capas=_layers(layer_dict); _,_,pidx=_predio_index(capas); errors=[]
    for aliases in (TERRENO_ALIASES,CONSTRUCCION_ALIASES):
        layer=_find_layer(capas,aliases)
        for f in _features(layer):
            p=_linked_predio(f,pidx)
            if p is None or not _active(p): errors.append(_error("134",layer,f,"Toda unidad espacial debe estar asociada a un predio activo.",predio_ref=_ref(_get_raw(f,PREDIO_REF_FIELDS))))
    return _result("134",errors)


def _matrix_special_data(p):
    return {
        "total_torres": _get(p,("Total_Torres","total_torres","Numero_Torres","numero_torres")),
        "area_total_construida": _get(p,("Area_Total_Construida","area_total_construida")),
        "area_privada_construida": _get(p,("Area_Privada_Construida","area_privada_construida")),
        "area_construida_comun": _get(p,("Area_Construida_Comun","area_construida_comun","Area_Comun_Construida")),
        "total_unidades_privadas": _get(p,("Total_Unidades_Privadas","total_unidades_privadas")),
        "area_total_terreno": _get(p,("Area_Total_Terreno","area_total_terreno")),
        "area_privada_terreno": _get(p,("Area_Privada_Terreno","area_privada_terreno")),
        "area_terreno_comun": _get(p,("Area_Terreno_Comun","area_terreno_comun","Area_Comun_Terreno")),
    }


def regla_137(layer_dict=None, **kwargs):
    capas=_layers(layer_dict); layer,preds=_predios(capas); errors=[]
    matrices=[p for p in preds if "PHMATRIZ" in _condition(p)]
    ups=[p for p in preds if "PHUNIDADPREDIAL" in _condition(p)]
    for m in matrices:
        base=_npn(m)[:21]; associated=[p for p in ups if _npn(p)[:21]==base and len(_npn(p))>=24]
        vals=[int(_npn(p)[22:24]) for p in associated if _npn(p)[22:24].isdigit()]
        expected=max(vals) if vals else 0; actual=_int(_matrix_special_data(m)["total_torres"])
        if actual is None or actual!=expected: errors.append(_error("137",layer,m,"PH Matriz exige número de torres igual al máximo de posiciones 23-24 de sus UP asociadas.",torres_registradas=actual,torres_esperadas=expected))
    return _result("137",errors)


def regla_138(layer_dict=None, **kwargs):
    capas=_layers(layer_dict); layer,preds=_predios(capas); errors=[]
    for p in preds:
        if "PHMATRIZ" not in _condition(p): continue
        d=_matrix_special_data(p); total=_float(d["area_total_construida"]); priv=_float(d["area_privada_construida"]); common=_float(d["area_construida_comun"])
        if None in (total,priv,common) or abs(total-(priv+common))>0.01: errors.append(_error("138",layer,p,"PH Matriz exige área total construida = área privada construida + área construida común.",area_total=total,area_privada=priv,area_comun=common))
    return _result("138",errors)


def _info_ph_by_predio(capas):
    layer, out, _ = arb_model.rows_by_predio(
        capas, INFO_PH_ALIASES, PREDIO_REF_FIELDS + ("arb_predio", "cca_predio")
    )
    return layer, out

def _matrix_units(matrix,preds,kind="PH"):
    base=_npn(matrix)[:21]
    token="PHUNIDADPREDIAL" if kind=="PH" else "CONDOMINIOUNIDADPREDIAL"
    return [p for p in preds if token in _condition(p) and _npn(p)[:21]==base and _active(p)]

def regla_139(layer_dict=None, **kwargs):
    capas=_layers(layer_dict); p_layer,preds,pidx=_predio_index(capas); _,infos=_info_ph_by_predio(capas); _,c_by_p,_=_constructions_by_predio(capas,pidx); errors=[]
    for m in preds:
        if "PHMATRIZ" not in _condition(m): continue
        entries=infos.get(_aid(m),[])+infos.get(_npn(m),[]); registered=None
        if entries: registered=_float(_get(entries[0],("Area_Total_Construida_Comun","area_total_construida_comun","Area_Construida_Comun")))
        if registered is None: registered=_float(_matrix_special_data(m)["area_construida_comun"])
        common=sum((_g_area(_geom(c)) if not _g_empty(_geom(c)) else (_float(_get(c,("Area_Total_Construccion","area_total_construccion","Area_Construida"))) or 0.0)) for c in c_by_p.get(_aid(m),[]))
        if registered is None or abs(registered-common)>0.01: errors.append(_error("139",p_layer,m,"PH Matriz exige área construida común igual a la sumatoria de construcciones comunes.",valor_registrado=registered,valor_calculado=common))
    return _result("139",errors)

def regla_140(layer_dict=None, **kwargs):
    capas=_layers(layer_dict); p_layer,preds=_predios(capas); _,infos=_info_ph_by_predio(capas); errors=[]
    for m in preds:
        if "PHMATRIZ" not in _condition(m): continue
        units=_matrix_units(m,preds,"PH"); entries=infos.get(_aid(m),[])+infos.get(_npn(m),[]); registered=None
        if entries: registered=_int(_get(entries[0],("Total_Unidades_Privadas","total_unidades_privadas")))
        if registered is None: registered=_int(_matrix_special_data(m)["total_unidades_privadas"])
        if registered is None or registered!=len(units): errors.append(_error("140",p_layer,m,"PH Matriz exige total unidades privadas igual al conteo de predios PH UP activos asociados.",valor_registrado=registered,conteo_unidades=len(units)))
    return _result("140",errors)


def regla_141(layer_dict=None, **kwargs):
    capas=_layers(layer_dict); layer,preds=_predios(capas); errors=[]
    for p in preds:
        if "CONDOMINIOMATRIZ" not in _condition(p): continue
        d=_matrix_special_data(p); total=_float(d["area_total_terreno"]); priv=_float(d["area_privada_terreno"]); common=_float(d["area_terreno_comun"])
        if None in (total,priv,common) or abs(total-(priv+common))>0.01: errors.append(_error("141",layer,p,"Condominio Matriz exige área total terreno = área privada terreno + área terreno común.",area_total=total,area_privada=priv,area_comun=common))
    return _result("141",errors)


def regla_142(layer_dict=None, **kwargs):
    capas=_layers(layer_dict); p_layer,preds,pidx=_predio_index(capas); _,t_by_p,_=_terrains_by_predio(capas,pidx); _,infos=_info_ph_by_predio(capas); errors=[]
    for m in preds:
        if "CONDOMINIOMATRIZ" not in _condition(m): continue
        units=_matrix_units(m,preds,"CONDO"); calculated=sum(sum(_g_area(_geom(t)) for t in t_by_p.get(_aid(u),[])) for u in units)
        entries=infos.get(_aid(m),[])+infos.get(_npn(m),[]); registered=None
        if entries: registered=_float(_get(entries[0],("Area_Total_Terreno_Privada","area_total_terreno_privada","Area_Privada_Terreno")))
        if registered is None: registered=_float(_matrix_special_data(m)["area_privada_terreno"])
        if registered is None or abs(registered-calculated)>max(0.01,abs(registered)*0.10): errors.append(_error("142",p_layer,m,"Condominio Matriz exige área privada de terreno igual a la sumatoria de áreas geométricas de terrenos de sus UP.",valor_registrado=registered,valor_calculado=calculated))
    return _result("142",errors)


def regla_143(layer_dict=None, **kwargs):
    capas=_layers(layer_dict)
    t_layer=_find_layer(capas,TRAMITE_ALIASES)
    p_layer,preds,pidx=_predio_index(capas)
    errors=[]

    # Estructura oficial: asociación N:M por arb_predio_tramite. Se usa como fuente
    # principal y se conservan los campos del trámite como compatibilidad secundaria.
    rel_aliases=("arb_predio_tramite","ARB_PredioTramite","ARB_Predio_Tramite","Predio Tramite","Predio Trámite")
    rel_layer,pairs=arb_model.relation_pairs(
        capas,rel_aliases,("predio","arb_predio","id_predio"),("tramite","arb_tramite","id_tramite")
    )
    tramite_index=arb_model.index_features(t_layer)
    rel_by_tramite=defaultdict(set)
    for pref,tref,_ in pairs:
        if pref and tref:
            rel_by_tramite[tref].add(pref)

    for t in _features(t_layer):
        token=_norm(_get(t,("tipo_tramite","tipo_mutacion","clasificacion_mutacion","Tipo_Tramite","Tipo_Mutacion")))
        if "CANCEL" not in token:
            continue
        refs=set()
        for tkey in _entity_keys(t):
            refs.update(rel_by_tramite.get(tkey,set()))
        # Compatibilidad con XTF que serializa referencias en atributos del trámite.
        for field in ("predios_resultantes","codigo_inicial","predio","predios"):
            raw=_text(_get(t,(field,)))
            if raw:
                refs.update(x.strip() for x in re.split(r"[,;\s]+",raw) if x.strip())
        if not refs and rel_layer is None:
            # Sin relación ni referencia no se puede inferir un incumplimiento.
            continue
        for pref in refs:
            p=pidx.get(_ref(pref))
            if p is not None and "CANCELADO" not in _norm(_get(p,ESTADO_FIELDS)):
                errors.append(_error("143",p_layer,p,"Los trámites de cancelación exigen que los predios asociados estén en estado Cancelado.",tramite_id=_aid(t),estado_predio=_text(_get(p,ESTADO_FIELDS))))
    return _result("143",errors)


def _resultado_parcial(code, errors, reason, message_prefix=None):
    msg = message_prefix or (f"Se detectaron {len(errors)} incumplimientos en la regla SINIC {code}." if errors else f"No se detectaron errores verificables en la regla SINIC {code}.")
    return _result(code, errors, msg + " Validación parcial: " + reason + ".", no_verificable=True, verificacion_parcial=True, motivo_no_verificable=reason)


def _hole_is_exception(hole, exception_union):
    if _g_empty(hole) or _g_empty(exception_union):
        return False
    remainder = _g_difference(hole, exception_union)
    return _g_area(remainder) <= TOPOLOGY_AREA_TOLERANCE


def regla_145(layer_dict=None, **kwargs):
    """Vacíos reales de cobertura, no simples anillos que otra entidad ya rellena."""
    capas = _layers(layer_dict); errors = []
    capas_aplicables = _capas_por_grupos(capas, CAPAS_TOPOLOGICAS_145)
    if not capas_aplicables:
        return _not_verifiable("145", "no se encontraron clases geométricas aplicables; las capas CC/VM son cartografía externa y deben cargarse en el proyecto web")
    _, _, pidx = _predio_index(capas)
    centro_layer = _find_layer(capas, CENTRO_POBLADO_ALIASES)
    perim_layer = _find_layer(capas, PERIMETRO_URBANO_ALIASES)
    centro_union = _union([_geom(f) for f in _features(centro_layer)])
    perim_union = _union([_geom(f) for f in _features(perim_layer)])
    for layer in capas_aplicables:
        if _is_historical_layer(layer):
            continue
        feats = [f for f in _features(layer) if not _g_empty(_geom(f))]
        if not feats:
            continue
        groups = [("CAPA", feats)]
        if _layer_matches_aliases(layer, TERRENO_ALIASES):
            formal, informal = [], []
            for f in feats:
                p = _linked_predio(f, pidx)
                (informal if p is not None and (_is_informal_height(p) or _is_informal_land(p)) else formal).append(f)
            groups = []
            if formal: groups.append(("TERRENO_FORMAL", formal))
            if informal: groups.append(("TERRENO_INFORMAL", informal))
        for group_name, rows in groups:
            coverage = _union([_geom(f) for f in rows])
            huecos = [h for h in _g_hole_geometries(coverage) if _g_area(h) > TOPOLOGY_AREA_TOLERANCE]
            valid_holes = []
            for hole in huecos:
                # 5.5: huecos de Sector Rural correspondientes a Centro Poblado son excepción.
                if _layer_matches_aliases(layer, SECTOR_RURAL_ALIASES) and _hole_is_exception(hole, centro_union):
                    continue
                # 5.13: ZHF rural admite centros poblados y perímetro urbano.
                if _layer_matches_aliases(layer, ZHF_RURAL_ALIASES):
                    exceptions = _g_combine(centro_union, perim_union)
                    if _hole_is_exception(hole, exceptions):
                        continue
                valid_holes.append(hole)
            # Orden estable por geometría: evita que GEOS/QGIS asignen índices distintos
            # a los mismos huecos por diferencias en el orden interno de los anillos.
            valid_holes.sort(key=_hole_sort_key)
            layer_name_canon = _canonical_topology_name(layer)
            layer_token_canon = _canonical_topology_token(layer)
            for indice, geom_hueco in enumerate(valid_holes, start=1):
                area_hueco = _g_area(geom_hueco)
                terrain_exception = _layer_matches_aliases(layer, TERRENO_ALIASES) and group_name == "TERRENO_FORMAL"
                extra = " Verifique si corresponde a la excepción permitida de vía o drenaje." if terrain_exception else ""
                errors.append(_error(
                    "145", layer, None,
                    f"Vacío real de cobertura de {area_hueco:.3f} m² en {layer_name_canon} ({group_name}); no está rellenado por otro polígono de la misma cobertura.{extra}",
                    aid=f"VACIO_{layer_token_canon}_{group_name}_{indice}",
                    grupo_topologico=group_name, cantidad_huecos=len(valid_holes), indice_hueco=indice,
                    area_hueco=area_hueco, tolerancia_tecnica_m2=TOPOLOGY_AREA_TOLERANCE,
                    requiere_revision_excepcion=terrain_exception,
                    tipo_geometria_error="hueco_cobertura", geometria_error_wkt=_g_wkt(geom_hueco),
                ))
    result=_marcar_parcial_por_cartografia(_result("145", errors), capas, "145")
    return _marcar_parcial_por_deslinde_oficial(result, "5.12")


def regla_146(layer_dict=None, **kwargs):
    capas = _layers(layer_dict); errors = []
    capas_aplicables = _capas_por_grupos(capas, CAPAS_TOPOLOGICAS_146)
    if not capas_aplicables:
        return _not_verifiable("146", "no se encontraron clases geométricas aplicables; las capas CC/VM son cartografía externa y deben cargarse en el proyecto web")
    for layer in capas_aplicables:
        if _is_historical_layer(layer):
            continue
        feats = [f for f in _features(layer) if not _g_empty(_geom(f))]
        if len(feats) < 2:
            continue
        if _layer_matches_aliases(layer, UC_ALIASES):
            # 5.31: solo se comparan UC de la MISMA construcción, planta y tipo de planta.
            def key(f):
                cref = _ref(_get_raw(f, CONSTRUCCION_REF_FIELDS))
                # Una UC sin referencia de construcción no se compara contra
                # otras UC también huérfanas: no hay evidencia de que pertenezcan
                # al mismo grupo lógico.
                cref = cref or f"__SIN_CONSTRUCCION__:{_aid(f)}"
                return (
                    cref,
                    _norm(_get(f, ("Tipo_Planta", "tipo_planta"))),
                    _text(_get(f, ("Planta_Ubicacion", "planta_ubicacion"))),
                )
            errors.extend(_pair_overlap("146", layer, feats, key))
        elif _layer_matches_aliases(layer, TERRENO_ALIASES):
            _, _, pidx = _predio_index(capas)
            _, rights = _rights_by_predio(capas)
            def tkey(f):
                p = _linked_predio(f, pidx)
                if p is None: return f"SIN_ASOCIACION:{_aid(f)}"
                if _is_informal_height(p) or _is_informal_land(p): return "INFORMAL"
                return "FORMAL"
            # 5.17 / 5.18: no superponer terrenos entre sí dentro del mismo universo
            # (formales con formales, informales con informales).
            errors.extend(_pair_overlap("146", layer, feats, tkey))

            # 5.19 / 5.20 son cruces ENTRE universos y por eso no quedan cubiertos
            # por el agrupamiento anterior. Se evalúan explícitamente.
            informal_pos=[]; informal_occ=[]; formal_public=[]; formal_private=[]
            for t in feats:
                p=_linked_predio(t,pidx)
                if p is None:
                    continue
                informal=_is_informal_height(p) or _is_informal_land(p)
                ptype=_ptype(p)
                p_rights=set(_rights_type(rights.get(_aid(p), [])))
                if informal:
                    if any("POSESION" in x for x in p_rights): informal_pos.append((t,p))
                    if any("OCUPACION" in x for x in p_rights): informal_occ.append((t,p))
                else:
                    if ("PUBLICOBALDIOBALDIO" in ptype or "PUBLICOFISCALPATRIMONIAL" in ptype or
                        "PUBLICOUSOPUBLICO" in ptype or "BIENUSOPUBLICO" in ptype):
                        formal_public.append((t,p))
                    if "PRIVADO" in ptype:
                        formal_private.append((t,p))

            def cross(rows_a, rows_b, subregla, descripcion):
                seen_cross=set()
                for ta,pa in rows_a:
                    ga=_geom(ta)
                    if _g_empty(ga): continue
                    for tb,pb in rows_b:
                        if _aid(pa)==_aid(pb): continue
                        gb=_geom(tb)
                        if _g_empty(gb) or not _g_intersects(ga,gb): continue
                        inter=_g_intersection(ga,gb)
                        area=_g_area(inter)
                        if area <= TOPOLOGY_AREA_TOLERANCE: continue
                        key=tuple(sorted((_aid(ta),_aid(tb))))+(subregla,)
                        if key in seen_cross: continue
                        seen_cross.add(key)
                        errors.append(_error(
                            "146",layer,ta,descripcion,subregla=subregla,
                            predio_aid=_aid(pa),predio_contraparte_aid=_aid(pb),
                            terreno_contraparte_aid=_aid(tb),area_superposicion=area,
                            tipo_geometria_error="superposicion",geometria_error_wkt=_g_wkt(inter),
                            aids_grupo=[_aid(ta),_aid(tb)],
                        ))
            cross(informal_pos,formal_public,"5.19","Un terreno informal con derecho de Posesión no debe superponerse con terreno formal Público Baldío, Fiscal Patrimonial o de Uso Público.")
            cross(informal_occ,formal_private,"5.20","Un terreno informal con derecho de Ocupación no debe superponerse con terreno formal de tipo Privado.")
        else:
            errors.extend(_pair_overlap("146", layer, feats))
    result=_marcar_parcial_por_cartografia(_result("146", errors), capas, "146")
    return _marcar_parcial_por_deslinde_oficial(result, "5.30")


def regla_147(layer_dict=None, **kwargs):
    capas = _layers(layer_dict); errors = []; checked = 0; missing = []

    def layer_rows(aliases):
        layer = _find_layer(capas, aliases)
        return layer, _features(layer)

    def parent_union(groups):
        layers = []
        for aliases in groups:
            for layer in _find_layers(capas, aliases):
                if _features(layer):
                    layers.append(layer)
        geoms = [_geom(f) for layer in layers for f in _features(layer)]
        return layers, _union(geoms)

    def check(child_aliases, parent_groups, label, optional_child=True):
        nonlocal checked
        cl, children = layer_rows(child_aliases)
        if not children:
            return
        pls, pu = parent_union(parent_groups)
        if not pls or _g_empty(pu):
            missing.append(label)
            return
        checked += 1
        parent_names = ", ".join(_layer_name(x) for x in pls)
        for c in children:
            g = _geom(c)
            if _g_empty(g):
                continue
            fuera = _g_difference(g, pu)
            area = _g_area(fuera)
            if area > TOPOLOGY_AREA_TOLERANCE:
                errors.append(_error(
                    "147", cl, c,
                    f"El elemento presenta {area:.3f} m² por fuera de la cobertura jerárquica permitida ({parent_names}).",
                    capa_superior=parent_names, subregla=label, area_diferencia=area,
                    tolerancia_tecnica_m2=TOPOLOGY_AREA_TOLERANCE,
                    tipo_geometria_error="fuera_cobertura", geometria_error_wkt=_g_wkt(fuera),
                ))

    # 5.37-5.44 con relaciones OR/fallback fieles al catálogo.
    check(CENTRO_POBLADO_ALIASES, [LIMITE_ALIASES, CORREGIMIENTO_ALIASES], "5.37 CentroPoblado -> Limite/Corregimiento")
    check(PERIMETRO_URBANO_ALIASES, [LIMITE_ALIASES, CORREGIMIENTO_ALIASES], "5.38 PerimetroUrbano -> Limite/Corregimiento")
    check(SECTOR_URBANO_ALIASES, [CENTRO_POBLADO_ALIASES, PERIMETRO_URBANO_ALIASES], "5.39 SectorUrbano -> CentroPoblado/PerimetroUrbano")
    check(SECTOR_RURAL_ALIASES, [LIMITE_ALIASES, CORREGIMIENTO_ALIASES], "5.40 SectorRural -> Limite/Corregimiento")
    check(VEREDA_ALIASES, [SECTOR_RURAL_ALIASES], "5.41 Vereda -> SectorRural")
    check(LOCALIDAD_COMUNA_ALIASES, [SECTOR_URBANO_ALIASES], "5.42 LocalidadComuna -> SectorUrbano")
    # 5.43 no autoriza reemplazar LocalidadComuna por SectorUrbano.
    check(BARRIO_ALIASES, [LOCALIDAD_COMUNA_ALIASES], "5.43 Barrio -> LocalidadComuna")

    # 5.44 (catálogo oficial): usar Barrio si la clase existe. SOLO cuando
    # CC_Barrio no existe se permite LocalidadComuna y, si esta tampoco existe,
    # SectorUrbano. Unir simultáneamente las tres coberturas oculta errores reales
    # (una manzana fuera de Barrio podía pasar por estar dentro de SectorUrbano).
    man_layer, man_rows = layer_rows(MANZANA_ALIASES)
    if man_rows:
        _b_layer, _b_rows = layer_rows(BARRIO_ALIASES)
        _l_layer, _l_rows = layer_rows(LOCALIDAD_COMUNA_ALIASES)
        _s_layer, _s_rows = layer_rows(SECTOR_URBANO_ALIASES)
        if _b_rows:
            check(MANZANA_ALIASES, [BARRIO_ALIASES], "5.44 Manzana -> Barrio")
        elif _l_rows:
            check(MANZANA_ALIASES, [LOCALIDAD_COMUNA_ALIASES], "5.44 Manzana -> LocalidadComuna (fallback sin Barrio)")
        elif _s_rows:
            check(MANZANA_ALIASES, [SECTOR_URBANO_ALIASES], "5.44 Manzana -> SectorUrbano (fallback sin Barrio/LocalidadComuna)")
        else:
            missing.append("5.44 Manzana -> Barrio/LocalidadComuna/SectorUrbano")

    # 5.45: ExtDireccion -> Terreno, si existe ExtDireccion.
    check(EXT_DIRECCION_ALIASES, [TERRENO_ALIASES], "5.45 ExtDireccion -> Terreno")

    # 5.46-5.49: Terrenos frente a zonas homogéneas. Solo se intenta si hay terrenos aplicables.
    t_layer, terrains = layer_rows(TERRENO_ALIASES)
    _, _, pidx = _predio_index(capas)
    urban = [t for t in terrains if (lambda p: p is not None and _is_urban(p))(_linked_predio(t, pidx))]
    rural = [t for t in terrains if (lambda p: p is not None and _is_rural(p))(_linked_predio(t, pidx))]

    def check_terrain_subset(rows, parent_aliases, label):
        nonlocal checked
        if not rows:
            return
        pls, pu = parent_union([parent_aliases])
        if not pls or _g_empty(pu):
            missing.append(label)
            return
        checked += 1
        parent_names = ", ".join(_layer_name(x) for x in pls)
        for t in rows:
            g = _geom(t); fuera = _g_difference(g, pu); area = _g_area(fuera)
            if area > TOPOLOGY_AREA_TOLERANCE:
                errors.append(_error(
                    "147", t_layer, t,
                    f"El terreno presenta {area:.3f} m² por fuera de {parent_names}.",
                    capa_superior=parent_names, subregla=label, area_diferencia=area,
                    tolerancia_tecnica_m2=TOPOLOGY_AREA_TOLERANCE,
                    tipo_geometria_error="fuera_cobertura", geometria_error_wkt=_g_wkt(fuera),
                ))

    check_terrain_subset(urban, ZHG_URBANA_ALIASES, "5.46 Terreno urbano -> ZHG urbana")
    check_terrain_subset(urban, ZHF_URBANA_ALIASES, "5.47 Terreno urbano -> ZHF urbana")
    check_terrain_subset(rural, ZHG_RURAL_ALIASES, "5.48 Terreno rural -> ZHG rural")
    check_terrain_subset(rural, ZHF_RURAL_ALIASES, "5.49 Terreno rural -> ZHF rural")

    # 5.50: Terreno informal cubierto por terreno formal.
    informal = []; formal = []
    for t in terrains:
        p = _linked_predio(t, pidx)
        if p is not None and (_is_informal_height(p) or _is_informal_land(p)): informal.append(t)
        else: formal.append(t)
    if informal:
        fu = _union([_geom(t) for t in formal])
        if _g_empty(fu):
            missing.append("5.50 Terreno informal -> Terreno formal")
        else:
            checked += 1
            for t in informal:
                fuera = _g_difference(_geom(t), fu); area = _g_area(fuera)
                if area > TOPOLOGY_AREA_TOLERANCE:
                    errors.append(_error(
                        "147", t_layer, t,
                        f"El terreno informal presenta {area:.3f} m² que no están cubiertos por terreno formal.",
                        subregla="5.50 Terreno informal -> Terreno formal", area_diferencia=area,
                        tolerancia_tecnica_m2=TOPOLOGY_AREA_TOLERANCE,
                        tipo_geometria_error="fuera_cobertura", geometria_error_wkt=_g_wkt(fuera),
                    ))

    if checked == 0:
        return _not_verifiable("147", "no hay pares jerárquicos verificables con las capas cargadas")
    if missing:
        return _resultado_parcial("147", errors, "faltan capas para: " + "; ".join(sorted(set(missing))))
    return _result("147", errors)


def _feature_divipola(feature):
    ident = _text(_get(feature, ("Identificador", "identificador", "Codigo", "codigo", "Etiqueta", "etiqueta", "id_cartografico", "Identificador_Cartografico")))
    if len(ident) >= 5 and ident[:5].isdigit():
        return ident[:5], ident
    dep = "".join(ch for ch in _text(_get(feature, ("codigo_departamento", "Codigo_Departamento", "cod_departamento"))) if ch.isdigit())
    mun = "".join(ch for ch in _text(_get(feature, ("codigo_municipio", "Codigo_Municipio", "cod_municipio"))) if ch.isdigit())
    if len(dep) >= 2:
        dep = dep[:2]
    if len(mun) >= 5 and dep and mun.startswith(dep):
        mun = mun[-3:]
    elif len(mun) >= 3:
        mun = mun[-3:]
    if len(dep) == 2 and len(mun) == 3:
        return dep + mun, dep + mun
    return "", ident


def regla_148(layer_dict=None, **kwargs):
    capas = _layers(layer_dict); municipality = _municipality_code(capas); errors = []
    cart_layers = _capas_por_grupos(capas, CARTOGRAFIA_ALIAS_GROUPS)
    if not cart_layers:
        return _not_verifiable("148", "no hay capas cartográficas externas CC/VM cargadas en el proyecto web")
    if not municipality:
        return _not_verifiable("148", "no fue posible inferir el DIVIPOLA municipal desde la cartografía cargada (preferiblemente CC_LimiteMunicipio)")
    checked = 0
    for layer in cart_layers:
        for f in _features(layer):
            prefix, ident = _feature_divipola(f)
            if not prefix:
                continue
            checked += 1
            if prefix != municipality:
                errors.append(_error(
                    "148", layer, f,
                    f"El identificador cartográfico inicia en {prefix} y debe iniciar en {municipality} (DIVIPOLA municipal).",
                    identificador=ident, encontrado=prefix, esperado=municipality,
                ))
    if checked == 0:
        return _not_verifiable("148", "las capas cartográficas cargadas no contienen identificadores ni códigos departamental/municipal verificables")
    return _result("148", errors, f"Regla SINIC 148: se verificaron {checked} elementos cartográficos contra DIVIPOLA {municipality}." if not errors else None)

def regla_149(layer_dict=None, **kwargs):
    """Suma de coeficientes de UP evitando falsos positivos en XTF parciales."""
    capas = _layers(layer_dict)
    p_layer, preds, pidx = _predio_index(capas)
    cop_layer = _find_layer(capas, COPROPIEDAD_ALIASES)
    errors = []; unresolved = []
    matrices = [p for p in preds if any(x in _condition(p) for x in ("PHMATRIZ", "CONDOMINIOMATRIZ", "CEMENTERIOMATRIZ"))]
    if not matrices:
        return _result("149", [], "Regla SINIC 149: no hay matrices aplicables.", no_aplica=True)

    cop_rows = _features(cop_layer)
    for matrix in matrices:
        matrix_keys = {_ref(_aid(matrix)), _ref(_npn(matrix))}
        matrix_keys.update(_entity_keys(matrix))
        matrix_keys = {x for x in matrix_keys if x}
        vals = []
        associated = []

        # Preferencia 1: relación/capa Copropiedad explícita.
        for c in cop_rows:
            matrix_ref = _ref(_get_raw(c, ("matriz", "predio_matriz", "id_matriz", "Matriz", "unidad_predial_matriz")))
            if matrix_ref and matrix_ref not in matrix_keys:
                continue
            coeff = _float(_get(c, ("coeficiente", "Coeficiente", "coeficiente_copropiedad", "Coeficiente_Copropiedad")))
            if matrix_ref in matrix_keys:
                associated.append(c)
                if coeff is not None:
                    vals.append(coeff)

        # Preferencia 2: UP con Predio_Matriz explícito o, como compatibilidad, raíz NPN.
        if not associated:
            kind_tokens = []
            cond_m = _condition(matrix)
            if "PHMATRIZ" in cond_m: kind_tokens.append("PHUNIDADPREDIAL")
            if "CONDOMINIOMATRIZ" in cond_m: kind_tokens.append("CONDOMINIOUNIDADPREDIAL")
            if "CEMENTERIOMATRIZ" in cond_m: kind_tokens.append("CEMENTERIOUNIDADPREDIAL")
            base = _npn(matrix)[:21]
            for child in preds:
                if child is matrix or not _active(child) or not any(tok in _condition(child) for tok in kind_tokens):
                    continue
                explicit = _ref(_get_raw(child, ("Predio_Matriz", "predio_matriz", "Matriz", "matriz", "id_matriz")))
                matches = explicit in matrix_keys if explicit else bool(base and _npn(child)[:21] == base)
                if not matches:
                    continue
                associated.append(child)
                coeff = _float(_get(child, ("coeficiente_copropiedad", "Coeficiente_Copropiedad", "coeficiente", "Coeficiente")))
                if coeff is not None:
                    vals.append(coeff)

        registered_total = _int(_matrix_special_data(matrix).get("total_unidades_privadas"))
        complete_known = registered_total is not None and len(associated) >= registered_total
        if not associated:
            unresolved.append(f"{_aid(matrix)}: no vienen UP asociadas en el XTF")
            continue
        if len(vals) != len(associated):
            unresolved.append(f"{_aid(matrix)}: faltan coeficientes en {len(associated)-len(vals)} UP")
            continue
        total = sum(vals)
        # Si no conocemos cuántas UP conforman la matriz, una suma distinta de 1 puede
        # deberse simplemente a que el XTF es parcial; no se reporta como error falso.
        if not complete_known and abs(total - 1.0) > 0.0001:
            unresolved.append(f"{_aid(matrix)}: suma parcial {total:.10f} sin total de UP verificable")
            continue
        if abs(total - 1.0) > 0.0001:
            errors.append(_error(
                "149", p_layer, matrix,
                f"La suma de coeficientes de las {len(vals)} UP asociadas es {total:.10f} y debe ser 1.0000000000 (100%).",
                suma_coeficientes=total, cantidad_up=len(vals), total_unidades_registradas=registered_total,
            ))

    if unresolved:
        return _resultado_parcial("149", errors, "no se pudo demostrar que el XTF contenga todas las UP de cada matriz: " + "; ".join(unresolved))
    return _result("149", errors)


GENERAL_FUNCTIONS={
    "7":regla_7,"8":regla_8,"9":regla_9,"19":regla_19,"32":regla_32,"33":regla_33,
}
FISICO_FUNCTIONS={
    "5":regla_5,"20":regla_20,"22":regla_22,"23":regla_23,"24":regla_24,"25":regla_25,"26":regla_26,"27":regla_27,
    "28":regla_28,"29":regla_29,"42":regla_42,"43":regla_43,"44":regla_44,"57":regla_57,"58":regla_58,"59":regla_59,
    "61":regla_61,"62":regla_62,"63":regla_63,"64":regla_64,"82":regla_82,"84":regla_84,
    "85":regla_85,"86":regla_86,"87":regla_87,"106":regla_106,"108":regla_108,"114":regla_114,
    "115":regla_115,"116":regla_116,"125":regla_125,"126":regla_126,"127":regla_127,"134":regla_134,"137":regla_137,
    "138":regla_138,"139":regla_139,"140":regla_140,"141":regla_141,"142":regla_142,"143":regla_143,
    "81":regla_81,"83":regla_83,"112":regla_112,
    "145":regla_145,"146":regla_146,"147":regla_147,"148":regla_148,"149":regla_149,
}
