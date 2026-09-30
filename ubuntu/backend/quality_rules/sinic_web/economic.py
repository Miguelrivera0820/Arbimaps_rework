# -*- coding: utf-8 -*-
"""Reglas SINIC - Componente Económico.

Implementación completa de las 15 reglas del componente económico del catálogo oficial SINIC:
- 47: Predios no PH con unidades de construcción deben tener valor comercial de construcción > 0.
- 48: Predios no PH con unidades de construcción deben tener avalúo catastral de construcción > 0.
- 49: Predios informales deben tener avalúo catastral de terreno igual a 0.
- 50: Predios informales deben tener valor comercial de terreno igual a 0.
- 51: Predios activos no PH ni informal deben tener valor comercial de terreno > 0.
- 52: Predios activos no PH ni informal deben tener avalúo catastral de terreno > 0.
- 53: Valor comercial total = valor comercial terreno + valor comercial construcciones (> 0).
- 54: Avalúo catastral total = avalúo catastral terreno + avalúo catastral construcciones (> 0, cerrado al mil).
- 55: Predios no informales de tipo Privado, Baldío, Fiscal, Uso Público o Presunto Baldío deben tener valor comercial > 0.
- 56: Predios no informales deben tener avalúo catastral > 0 (no vacío ni nulo).
- 101: Predio informal con construcciones exige avalúo catastral > 0.
- 102: Predio informal con construcciones exige valor comercial > 0.
- 103: Valor comercial en informal corresponde únicamente al valor comercial de construcciones.
- 104: Avalúo catastral en informal corresponde únicamente al avalúo catastral de construcciones.
- 105: Predio activo exige avalúo catastral vigente correspondiente al año en curso del reporte.
"""
from __future__ import annotations
import datetime
from decimal import Decimal, ROUND_HALF_UP
import re

WebProject = None
NULL = None

from .engine import metadata_regla
from . import model as arb_model
from .economic_helper import (
    EconomicoWebHelper,
    _is_empty,
    _is_not_empty,
    _to_float,
    _feature_identifier_aliases,
    _novedad_es_cancelacion,
    _normalized_domain_text,
)

COMPONENT_SLUG = 'economico'
LAYER_ALIASES = {}


def obtener_capas_relevantes():
    if WebProject is None:
        return {}
    capas = {}
    try:
        for layer in WebProject.instance().mapLayers().values():
            try:
                capas[layer.name()] = layer
            except Exception:
                pass
    except Exception:
        pass
    return capas


def _capas(layer_dict=None, layer_dic=None):
    return layer_dict if layer_dict is not None else (layer_dic if layer_dic is not None else obtener_capas_relevantes())


def _feature_uid(feature):
    if feature is None:
        return ""
    if isinstance(feature, dict):
        for k in ("t_ili_tid", "id_operacion", "t_id", "id", "identificador"):
            v = feature.get(k)
            if v is not None and str(v).strip():
                return str(v).strip()
        return str(id(feature))
    try:
        return str(feature.id())
    except Exception:
        return str(id(feature))


def _redondear_al_mil(valor):
    if valor is None:
        return None
    try:
        return float(Decimal(str(valor)).quantize(Decimal("1e3"), rounding=ROUND_HALF_UP))
    except Exception:
        return None


def _extraer_anio_vigencia(valor):
    if _is_empty(valor):
        return None
    text = str(valor).strip()
    match = re.search(r"\b(19\d\d|20\d\d)\b", text)
    if match:
        try:
            return int(match.group(1))
        except Exception:
            pass
    return None


def _obtener_anio_referencia_vigencia(ctx=None):
    """Vigencia objetivo sin depender del nombre ni contenido fijo de un XTF.

    Prioridad: vigencia máxima presente en ARB_AvaluoValor -> año calendario
    como último fallback cuando el archivo no contiene ninguna vigencia válida.
    El criterio es idéntico en web y plugin y no depende de configuración local.
    """
    years=[]
    if isinstance(ctx, dict):
        for item in ctx.get("avaluos_con_predio", []) or []:
            year=item.get("values",{}).get("vigencia")
            if isinstance(year,int):
                years.append(year)
    return max(years) if years else datetime.date.today().year


def _normalizar_condicion_predio_economico(raw_value, npn=None):
    if _is_not_empty(raw_value):
        norm = _normalized_domain_text(raw_value)
        if "informal" in norm or str(raw_value).strip() in {"706", "1345"}:
            return "Informal"
        if "nph" in norm:
            return "NPH"
        if any(x in norm for x in ("propiedad_horizontal", "propiedadhorizontal", "condominio")) or norm.startswith("ph") or norm.endswith("ph") or "_ph" in norm or "ph_" in norm or norm == "ph":
            return "Propiedad_Horizontal"
        if any(x in norm for x in ("bien_uso_publico", "bienusopublico", "uso_publico")):
            return "Bien_Uso_Publico"
        if "via" in norm:
            return "Via"
        if "parque_cementerio" in norm or "parquecementerio" in norm:
            return "Parque_Cementerio"

    if npn:
        digits = "".join(ch for ch in str(npn) if ch.isalnum())
        if len(digits) >= 22:
            d22 = digits[21]
            if d22 == "2":
                return "Informal"
            elif d22 in ("8", "9"):
                return "Propiedad_Horizontal"
            elif d22 == "0":
                return "NPH"
            elif d22 == "3":
                return "Bien_Uso_Publico"
            elif d22 == "4":
                return "Via"
            elif d22 == "7":
                return "Parque_Cementerio"

    return "NPH"


def _normalizar_tipo_predio_economico(raw_value):
    if _is_empty(raw_value):
        return None
    norm = _normalized_domain_text(raw_value)
    if "privad" in norm:
        return "Privado"
    if "presuntobaldio" in norm or "presunto_baldio" in norm:
        return "Presunto_Baldio"
    if "baldio" in norm:
        return "Baldio"
    if "fiscal" in norm:
        return "Fiscal"
    if "usopublico" in norm or "uso_publico" in norm or "bien_uso_publico" in norm:
        return "Uso_Publico"
    return str(raw_value).strip()


def _avaluo_values_web(helper, feature):
    fields = {
        "valor_comercial": ("valor_comercial", "Valor_Comercial", "avaluo_comercial", "Avaluo_Comercial"),
        "valor_comercial_terreno": ("valor_comercial_terreno", "Valor_Comercial_Terreno", "avaluo_comercial_terreno", "Avaluo_Comercial_Terreno"),
        "valor_comercial_unidades": ("valor_comercial_total_unidadesconstruccion", "Valor_Comercial_Total_UnidadesConstruccion", "valor_comercial_total_unidades_construccion", "avaluo_comercial_total_unidades_construccion", "Avaluo_Comercial_Total_Unidades_Construccion"),
        "valor_catastral": ("valor_catastral", "Valor_Catastral", "avaluo_catastral", "Avaluo_Catastral"),
        "valor_catastral_terreno": ("valor_catastral_terreno", "Valor_Catastral_Terreno", "avaluo_catastral_terreno", "Avaluo_Catastral_Terreno"),
        "valor_catastral_unidades": ("valor_catastral_total_unidadesconstruccion", "Valor_Catastral_Total_UnidadesConstruccion", "valor_catastral_total_unidades_construccion", "avaluo_catastral_total_unidades_construccion", "Avaluo_Catastral_Total_Unidades_Construccion"),
    }
    vals = {key: _to_float(helper.get_field_value(feature, aliases)) for key, aliases in fields.items()}
    vigencia_raw = helper.get_field_value(
        feature,
        ("vigencia", "Vigencia", "anio_vigencia", "Anio_Vigencia", "fecha_avaluo_catastral", "Fecha_Avaluo_Catastral", "fecha_avaluo", "Fecha_Avaluo", "vigencia_avaluo", "anio", "ano_vigencia")
    )
    vals["vigencia"] = _extraer_anio_vigencia(vigencia_raw)
    vals["vigencia_raw"] = vigencia_raw
    return vals


def _build_economic_predio_context(helper):
    predio_layers = tuple(dict.fromkeys(helper.ILC_PREDIO_LAYERS + helper.PREDIO_LAYERS))
    predios = list(helper.iter_layer_rows(predio_layers))

    avaluo_layers = tuple(dict.fromkeys(helper.ILC_ESTRUCTURA_AVALUO_LAYERS + helper.AVALUO_LAYERS))
    avaluos = list(helper.iter_layer_rows(avaluo_layers))

    # 1. Detección de predios cancelados
    cancelados_aliases = set()
    novedades_layers = tuple(dict.fromkeys(helper.ILC_DATOS_ADICIONALES_LAYERS + helper.NOVEDAD_NUMERO_PREDIAL_LAYERS))
    for _, _, nov_feat in helper.iter_layer_rows(novedades_layers):
        novedad = helper.get_field_value(
            nov_feat,
            ("novedad_numeros_prediales", "Novedad_Numeros_Prediales", "novedad_numero_predial", "novedad_numeros_prediales_tipo", "tipo_novedad")
        )
        if _novedad_es_cancelacion(novedad):
            ref = helper.get_field_value(
                nov_feat,
                ("arb_predio_novedad_numero_predial", "ARB_Predio_Novedad_Numero_Predial",
                 "predio", "ilc_predio", "predio_ref", "ilc_predio_datos_adicionales",
                 "predio_id", "numero_predial")
            )
            # Sin REF/FK estructural no se asigna la novedad por cantidad u orden.
            # Eso evita que un XTF de un solo predio produzca una asociación inventada.
            if _is_not_empty(ref):
                cancelados_aliases.add(str(ref).strip())

    # 2. Registrar predios
    predios_info = {}
    alias_to_predio_key = {}

    for table_name, capa, feat in predios:
        p_key = arb_model.canonical_key(feat)
        aliases = _feature_identifier_aliases(helper, feat)
        npn = helper.get_field_value(feat, ("numero_predial_nacional", "numero_predial", "Numero_Predial_Nacional", "Numero_Predial", "npn"))
        if _is_not_empty(npn):
            aliases.add(str(npn).strip())

        cond_raw = helper.get_field_value(feat, ("condicion_predio", "Condicion_Predio", "condicion", "Condicion"))
        condicion = _normalizar_condicion_predio_economico(cond_raw, npn)

        tipo_raw = helper.get_field_value(feat, ("tipo_predio", "Tipo_Predio", "tipo", "Tipo"))
        tipo = _normalizar_tipo_predio_economico(tipo_raw)

        novedad_directa = helper.get_field_value(feat, ("novedad_numeros_prediales", "Novedad_Numeros_Prediales"))
        es_cancelado = bool(aliases & cancelados_aliases) or _novedad_es_cancelacion(novedad_directa)

        info = {
            "key": p_key,
            "feature": feat,
            "capa": capa,
            "tabla": table_name,
            "aliases": aliases,
            "npn": npn,
            "condicion": condicion,
            "tipo": tipo,
            "cancelado": es_cancelado,
            "uc_count": 0,
            "avaluos": [],
        }
        predios_info[p_key] = info
        for alias in aliases:
            alias_to_predio_key[arb_model.ref(alias)] = p_key

        if _novedad_es_cancelacion(novedad_directa):
            cancelados_aliases.update(aliases)

    # 3. Conteo de Unidades de Construcción por relación estructural
    # ARB_UnidadConstruccion no referencia directamente al predio en esta estructura:
    # Unidad -> Construccion -> Predio. No se infiere por cantidad ni por orden.
    unit_aliases=(
        "ARB_UnidadConstruccion","arb_unidadconstruccion","ARB_Unidad_de_construccion",
        "(ARB) Unidad de construcción","(ARB) Unidad de construccion","Unidad de construcción",
    )
    construction_aliases=(
        "ARB_Construccion","arb_construccion","(ARB) Construccion","(ARB) Construcción","Construccion","Construcción",
    )
    _, units_by_predio, _ = arb_model.units_by_predio(
        helper.layer_dict, unit_aliases, construction_aliases,
        ("construccion","arb_construccion","id_construccion","construccion_id"),
        ("predio","arb_predio","ilc_predio","predio_id","id_predio")
    )
    for p_key, info in predios_info.items():
        info["uc_count"] = len(units_by_predio.get(p_key, []))

    # 4. Vincular Avalúos con Predios
    avaluos_con_predio = []
    avaluo_refs_encontrados = set()

    for av_table, av_capa, av_feat in avaluos:
        v = _avaluo_values_web(helper, av_feat)
        ref_fields=("arb_predio_avaluo", "ARB_Predio_Avaluo", "ilc_predio_avaluo", "predio", "predio_ref", "arb_predio", "ilc_predio", "predio_id", "numero_predial")
        matched_p_key=None
        ref=None
        for field in ref_fields:
            candidate=helper.get_field_value(av_feat,(field,))
            if _is_not_empty(candidate):
                ref=candidate
                matched_p_key=alias_to_predio_key.get(arb_model.ref(candidate))
                if matched_p_key:
                    break
        predio_item = predios_info.get(matched_p_key) if matched_p_key else None
        if predio_item:
            predio_item["avaluos"].append({
                "tabla": av_table,
                "capa": av_capa,
                "feature": av_feat,
                "values": v,
            })
            avaluo_refs_encontrados.update(predio_item["aliases"])
        elif _is_not_empty(ref):
            avaluo_refs_encontrados.add(str(ref).strip())

        avaluos_con_predio.append({
            "tabla": av_table,
            "capa": av_capa,
            "feature": av_feat,
            "values": v,
            "predio": predio_item,
        })

    return {
        "predios": predios,
        "predios_info": predios_info,
        "alias_to_predio_key": alias_to_predio_key,
        "avaluos_con_predio": avaluos_con_predio,
        "avaluo_refs_encontrados": avaluo_refs_encontrados,
        "cancelados_aliases": cancelados_aliases,
    }


def _avaluos_objetivo(ctx, anio_referencia=None):
    """Selecciona el avalúo de la vigencia objetivo y evita validar todo el histórico.

    ARB_AvaluoValor conserva múltiples vigencias por predio. Las reglas económicas
    de consistencia de la base vigente (47-56 y 101-104) deben operar sobre la
    vigencia catastral del proyecto/año en curso. La regla 105 se encarga de
    denunciar explícitamente cuando esa vigencia no existe.
    """
    anio_referencia = anio_referencia or _obtener_anio_referencia_vigencia(ctx)
    agrupados = {}
    sin_predio = []
    for item in ctx.get("avaluos_con_predio", []):
        predio = item.get("predio")
        if predio is None:
            sin_predio.append(item)
            continue
        agrupados.setdefault(predio.get("key"), []).append(item)

    seleccion = []
    for rows in agrupados.values():
        exactos = [x for x in rows if x.get("values", {}).get("vigencia") == anio_referencia]
        if exactos:
            seleccion.extend(exactos)
            continue
        # Si existen vigencias identificables pero ninguna es la objetivo, no se
        # usan registros históricos como sustituto; regla 105 informará la falta.
        if any(x.get("values", {}).get("vigencia") is not None for x in rows):
            continue
        # Compatibilidad con modelos que no exponen vigencia: conservar registros
        # para no desactivar silenciosamente las demás validaciones económicas.
        seleccion.extend(rows)

    if sin_predio:
        exactos = [x for x in sin_predio if x.get("values", {}).get("vigencia") == anio_referencia]
        if exactos:
            seleccion.extend(exactos)
        elif not any(x.get("values", {}).get("vigencia") is not None for x in sin_predio):
            seleccion.extend(sin_predio)
    return seleccion


def _extraer_detalles_base(item):
    predio = item.get("predio")
    v = item.get("values", {})
    detalles = {
        "tabla": item.get("tabla", ""),
        "valor_comercial": v.get("valor_comercial"),
        "valor_comercial_terreno": v.get("valor_comercial_terreno"),
        "valor_comercial_unidades": v.get("valor_comercial_unidades"),
        "valor_catastral": v.get("valor_catastral"),
        "valor_catastral_terreno": v.get("valor_catastral_terreno"),
        "valor_catastral_unidades": v.get("valor_catastral_unidades"),
    }
    if predio:
        detalles["numero_predial"] = predio.get("npn")
        # Mantener separado el identificador técnico del predio y su NPN.
        # Evita que la columna AID/ID del Excel web termine mostrando el NPN.
        detalles["predio_id"] = predio.get("key")
        detalles["condicion_predio"] = predio.get("condicion")
        detalles["tipo_predio"] = predio.get("tipo")
        detalles["unidades_construccion"] = predio.get("uc_count", 0)
    return detalles


def _crear_error_sinic(helper, codigo, capa, feat, mensaje, detalles=None):
    meta = metadata_regla(codigo)
    d = {
        "sinic_id": codigo,
        "sinic_abreviatura": meta.get("abbreviation", ""),
    }
    if detalles:
        d.update(detalles)
    err = helper.make_error(capa, feat, codigo, mensaje, d)
    # Las reglas económicas son de nivel predio. ARB_AvaluoValor puede no
    # traer TID en el XTF, así que el AID estable debe ser el del predio
    # relacionado, igual que en el plugin QGIS.
    predio_id = d.get("predio_id")
    if predio_id is not None and str(predio_id).strip():
        err["aid"] = str(predio_id).strip()
    err["detalles"] = d
    err["details"] = d
    err["regla"] = codigo
    return err


def _resultado_sinic(codigo, errores):
    meta = metadata_regla(codigo)
    return {
        "cumple": len(errores) == 0,
        "errores": errores,
        "mensaje": (
            f"Se detectaron {len(errores)} incumplimientos en la regla SINIC {codigo}."
            if errores
            else f"No se detectaron errores en la regla SINIC {codigo}."
        ),
        "regla_sinic": meta,
    }


# -----------------------------------------------------------------------------
# Funciones individuales de validación SINIC
# -----------------------------------------------------------------------------

def regla_47(layer_dict=None, layer_dic=None, **kwargs):
    """Predios no PH con unidades de construcción deben tener valor comercial de construcción > 0."""
    codigo = "47"
    helper = EconomicoWebHelper(_capas(layer_dict, layer_dic))
    ctx = _build_economic_predio_context(helper)
    errores = []
    for item in _avaluos_objetivo(ctx):
        predio = item["predio"]
        if not predio or predio.get("cancelado"):
            continue
        if predio.get("condicion") != "Propiedad_Horizontal" and predio.get("uc_count", 0) > 0:
            unidades = item["values"]["valor_comercial_unidades"]
            if unidades is None or unidades <= 0:
                detalles = _extraer_detalles_base(item)
                errores.append(_crear_error_sinic(
                    helper, codigo, item["capa"], item["feature"],
                    f"Predios no PH con unidades de construcción asociadas ({predio.get('uc_count')}) deben tener valor comercial de construcción mayor a 0 (registrado: {unidades}).",
                    detalles
                ))
    return _resultado_sinic(codigo, errores)


def regla_48(layer_dict=None, layer_dic=None, **kwargs):
    """Predios no PH con unidades de construcción deben tener avalúo catastral de construcción > 0."""
    codigo = "48"
    helper = EconomicoWebHelper(_capas(layer_dict, layer_dic))
    ctx = _build_economic_predio_context(helper)
    errores = []
    for item in _avaluos_objetivo(ctx):
        predio = item["predio"]
        if not predio or predio.get("cancelado"):
            continue
        if predio.get("condicion") != "Propiedad_Horizontal" and predio.get("uc_count", 0) > 0:
            unidades = item["values"]["valor_catastral_unidades"]
            if unidades is None or unidades <= 0:
                detalles = _extraer_detalles_base(item)
                errores.append(_crear_error_sinic(
                    helper, codigo, item["capa"], item["feature"],
                    f"Predios no PH con unidades de construcción asociadas ({predio.get('uc_count')}) deben tener avalúo catastral de construcción mayor a 0 (registrado: {unidades}).",
                    detalles
                ))
    return _resultado_sinic(codigo, errores)


def regla_49(layer_dict=None, layer_dic=None, **kwargs):
    """Predios informales deben tener avalúo catastral de terreno igual a 0."""
    codigo = "49"
    helper = EconomicoWebHelper(_capas(layer_dict, layer_dic))
    ctx = _build_economic_predio_context(helper)
    errores = []
    for item in _avaluos_objetivo(ctx):
        predio = item["predio"]
        if not predio or predio.get("cancelado"):
            continue
        if predio.get("condicion") == "Informal":
            terreno = item["values"]["valor_catastral_terreno"]
            if terreno is None or abs(terreno) > 0.001:
                detalles = _extraer_detalles_base(item)
                errores.append(_crear_error_sinic(
                    helper, codigo, item["capa"], item["feature"],
                    f"Los predios informales deben tener avalúo catastral de terreno igual a 0 (registrado: {terreno}).",
                    detalles
                ))
    return _resultado_sinic(codigo, errores)


def regla_50(layer_dict=None, layer_dic=None, **kwargs):
    """Predios informales deben tener valor comercial de terreno igual a 0."""
    codigo = "50"
    helper = EconomicoWebHelper(_capas(layer_dict, layer_dic))
    ctx = _build_economic_predio_context(helper)
    errores = []
    for item in _avaluos_objetivo(ctx):
        predio = item["predio"]
        if not predio or predio.get("cancelado"):
            continue
        if predio.get("condicion") == "Informal":
            terreno = item["values"]["valor_comercial_terreno"]
            if terreno is None or abs(terreno) > 0.001:
                detalles = _extraer_detalles_base(item)
                errores.append(_crear_error_sinic(
                    helper, codigo, item["capa"], item["feature"],
                    f"Los predios informales deben tener valor comercial de terreno igual a 0 (registrado: {terreno}).",
                    detalles
                ))
    return _resultado_sinic(codigo, errores)


def regla_51(layer_dict=None, layer_dic=None, **kwargs):
    """Predios activos no PH ni informal deben tener valor comercial de terreno > 0."""
    codigo = "51"
    helper = EconomicoWebHelper(_capas(layer_dict, layer_dic))
    ctx = _build_economic_predio_context(helper)
    errores = []
    for item in _avaluos_objetivo(ctx):
        predio = item["predio"]
        if not predio or predio.get("cancelado"):
            continue
        if predio.get("condicion") not in ("Propiedad_Horizontal", "Informal"):
            terreno = item["values"]["valor_comercial_terreno"]
            if terreno is None or terreno <= 0:
                detalles = _extraer_detalles_base(item)
                errores.append(_crear_error_sinic(
                    helper, codigo, item["capa"], item["feature"],
                    f"Predios activos no PH ni informales deben tener valor comercial de terreno mayor a 0 (registrado: {terreno}).",
                    detalles
                ))
    return _resultado_sinic(codigo, errores)


def regla_52(layer_dict=None, layer_dic=None, **kwargs):
    """Predios activos no PH ni informal deben tener avalúo catastral de terreno > 0."""
    codigo = "52"
    helper = EconomicoWebHelper(_capas(layer_dict, layer_dic))
    ctx = _build_economic_predio_context(helper)
    errores = []
    for item in _avaluos_objetivo(ctx):
        predio = item["predio"]
        if not predio or predio.get("cancelado"):
            continue
        if predio.get("condicion") not in ("Propiedad_Horizontal", "Informal"):
            terreno = item["values"]["valor_catastral_terreno"]
            if terreno is None or terreno <= 0:
                detalles = _extraer_detalles_base(item)
                errores.append(_crear_error_sinic(
                    helper, codigo, item["capa"], item["feature"],
                    f"Predios activos no PH ni informales deben tener avalúo catastral de terreno mayor a 0 (registrado: {terreno}).",
                    detalles
                ))
    return _resultado_sinic(codigo, errores)


def regla_53(layer_dict=None, layer_dic=None, **kwargs):
    """Valor comercial total = valor comercial terreno + valor comercial construcciones."""
    codigo = "53"
    helper = EconomicoWebHelper(_capas(layer_dict, layer_dic))
    ctx = _build_economic_predio_context(helper)
    errores = []
    for item in _avaluos_objetivo(ctx):
        v = item["values"]
        total = v["valor_comercial"]
        terreno = v["valor_comercial_terreno"]
        unidades = v["valor_comercial_unidades"]
        if total is None or terreno is None or unidades is None or total <= 0 or abs(total - (terreno + unidades)) > 0.01:
            detalles = _extraer_detalles_base(item)
            errores.append(_crear_error_sinic(
                helper, codigo, item["capa"], item["feature"],
                f"El valor comercial total debe ser mayor a 0 y corresponder a la sumatoria de terreno más construcciones (Total={total}, Terreno={terreno}, Construcciones={unidades}).",
                detalles
            ))
    return _resultado_sinic(codigo, errores)


def regla_54(layer_dict=None, layer_dic=None, **kwargs):
    """Avalúo catastral total = avalúo catastral terreno + avalúo catastral construcciones."""
    codigo = "54"
    helper = EconomicoWebHelper(_capas(layer_dict, layer_dic))
    ctx = _build_economic_predio_context(helper)
    errores = []
    for item in _avaluos_objetivo(ctx):
        v = item["values"]
        total = v["valor_catastral"]
        terreno = v["valor_catastral_terreno"]
        unidades = v["valor_catastral_unidades"]
        if total is None or terreno is None or unidades is None or total <= 0:
            detalles = _extraer_detalles_base(item)
            errores.append(_crear_error_sinic(
                helper, codigo, item["capa"], item["feature"],
                "El avalúo catastral debe ser mayor que cero y estar diligenciado junto con terreno y unidades de construcción.",
                detalles
            ))
            continue
        esperado = _redondear_al_mil(Decimal(str(terreno)) + Decimal(str(unidades)))
        total_entero = round(total)
        es_entero = abs(total - total_entero) <= 0.001
        es_cerrado_al_mil = es_entero and int(total_entero) % 1000 == 0
        coincide = esperado is not None and abs(total - esperado) <= 0.01
        if not (es_cerrado_al_mil and coincide):
            detalles = _extraer_detalles_base(item)
            detalles["esperado_al_mil"] = esperado
            errores.append(_crear_error_sinic(
                helper, codigo, item["capa"], item["feature"],
                f"El avalúo catastral debe ser mayor que cero, cerrado al mil sin decimales, y corresponder a la suma de terreno + unidades redondeada al mil (Total={total}, Esperado={esperado}).",
                detalles
            ))
    return _resultado_sinic(codigo, errores)


def regla_55(layer_dict=None, layer_dic=None, **kwargs):
    """Predios no informales de tipo Privado, Baldío, Fiscal, Uso Público o Presunto Baldío deben tener valor comercial > 0."""
    codigo = "55"
    helper = EconomicoWebHelper(_capas(layer_dict, layer_dic))
    ctx = _build_economic_predio_context(helper)
    errores = []
    tipos_objetivo = {"Privado", "Baldio", "Fiscal", "Uso_Publico", "Presunto_Baldio"}
    for item in _avaluos_objetivo(ctx):
        predio = item["predio"]
        if not predio or predio.get("cancelado"):
            continue
        if predio.get("condicion") != "Informal":
            tipo = predio.get("tipo")
            if tipo is None or tipo in tipos_objetivo:
                total = item["values"]["valor_comercial"]
                if total is None or total <= 0:
                    detalles = _extraer_detalles_base(item)
                    errores.append(_crear_error_sinic(
                        helper, codigo, item["capa"], item["feature"],
                        f"Los predios no informales de tipo Privado, Baldío, Fiscal, Uso Público o Presunto Baldío deben tener valor comercial mayor a 0 (registrado: {total}).",
                        detalles
                    ))
    return _resultado_sinic(codigo, errores)


def regla_56(layer_dict=None, layer_dic=None, **kwargs):
    """Predios no informales deben tener avalúo catastral > 0 (no vacío ni nulo)."""
    codigo = "56"
    helper = EconomicoWebHelper(_capas(layer_dict, layer_dic))
    ctx = _build_economic_predio_context(helper)
    errores = []
    for item in _avaluos_objetivo(ctx):
        predio = item["predio"]
        if not predio or predio.get("cancelado"):
            continue
        if predio.get("condicion") != "Informal":
            total = item["values"]["valor_catastral"]
            if total is None or total <= 0:
                detalles = _extraer_detalles_base(item)
                errores.append(_crear_error_sinic(
                    helper, codigo, item["capa"], item["feature"],
                    f"Los predios no informales deben tener avalúo catastral mayor a 0, no vacío ni nulo (registrado: {total}).",
                    detalles
                ))
    return _resultado_sinic(codigo, errores)


def regla_101(layer_dict=None, layer_dic=None, **kwargs):
    """Predio informal con construcciones exige avalúo catastral > 0."""
    codigo = "101"
    helper = EconomicoWebHelper(_capas(layer_dict, layer_dic))
    ctx = _build_economic_predio_context(helper)
    errores = []
    for item in _avaluos_objetivo(ctx):
        predio = item["predio"]
        if not predio or predio.get("cancelado"):
            continue
        if predio.get("condicion") == "Informal" and predio.get("uc_count", 0) > 0:
            total = item["values"]["valor_catastral"]
            if total is None or total <= 0:
                detalles = _extraer_detalles_base(item)
                errores.append(_crear_error_sinic(
                    helper, codigo, item["capa"], item["feature"],
                    f"Predios informales con unidades de construcción asociadas ({predio.get('uc_count')}) deben tener avalúo catastral mayor a 0 (registrado: {total}).",
                    detalles
                ))
    return _resultado_sinic(codigo, errores)


def regla_102(layer_dict=None, layer_dic=None, **kwargs):
    """Predio informal con construcciones exige valor comercial > 0."""
    codigo = "102"
    helper = EconomicoWebHelper(_capas(layer_dict, layer_dic))
    ctx = _build_economic_predio_context(helper)
    errores = []
    for item in _avaluos_objetivo(ctx):
        predio = item["predio"]
        if not predio or predio.get("cancelado"):
            continue
        if predio.get("condicion") == "Informal" and predio.get("uc_count", 0) > 0:
            total = item["values"]["valor_comercial"]
            if total is None or total <= 0:
                detalles = _extraer_detalles_base(item)
                errores.append(_crear_error_sinic(
                    helper, codigo, item["capa"], item["feature"],
                    f"Predios informales con unidades de construcción asociadas ({predio.get('uc_count')}) deben tener valor comercial mayor a 0 (registrado: {total}).",
                    detalles
                ))
    return _resultado_sinic(codigo, errores)


def regla_103(layer_dict=None, layer_dic=None, **kwargs):
    """Valor comercial en informal corresponde únicamente al valor comercial de construcciones."""
    codigo = "103"
    helper = EconomicoWebHelper(_capas(layer_dict, layer_dic))
    ctx = _build_economic_predio_context(helper)
    errores = []
    for item in _avaluos_objetivo(ctx):
        predio = item["predio"]
        if not predio or predio.get("cancelado"):
            continue
        if predio.get("condicion") == "Informal":
            total = item["values"]["valor_comercial"]
            terreno = item["values"]["valor_comercial_terreno"]
            unidades = item["values"]["valor_comercial_unidades"]
            descuadre_total = total is None or unidades is None or abs(total - unidades) > 0.01
            terreno_no_cero = terreno is not None and abs(terreno) > 0.001
            if descuadre_total or terreno_no_cero:
                detalles = _extraer_detalles_base(item)
                errores.append(_crear_error_sinic(
                    helper, codigo, item["capa"], item["feature"],
                    f"En predios informales el valor comercial total debe corresponder únicamente al valor comercial de construcciones (Total={total}, Terreno={terreno}, Construcciones={unidades}).",
                    detalles
                ))
    return _resultado_sinic(codigo, errores)


def regla_104(layer_dict=None, layer_dic=None, **kwargs):
    """Avalúo catastral en informal corresponde únicamente al avalúo catastral de construcciones."""
    codigo = "104"
    helper = EconomicoWebHelper(_capas(layer_dict, layer_dic))
    ctx = _build_economic_predio_context(helper)
    errores = []
    for item in _avaluos_objetivo(ctx):
        predio = item["predio"]
        if not predio or predio.get("cancelado"):
            continue
        if predio.get("condicion") == "Informal":
            total = item["values"]["valor_catastral"]
            terreno = item["values"]["valor_catastral_terreno"]
            unidades = item["values"]["valor_catastral_unidades"]
            esperado = _redondear_al_mil(unidades) if unidades is not None else None
            descuadre_total = total is None or esperado is None or abs(total - esperado) > 0.01
            terreno_no_cero = terreno is not None and abs(terreno) > 0.001
            if descuadre_total or terreno_no_cero:
                detalles = _extraer_detalles_base(item)
                detalles["esperado_al_mil"] = esperado
                errores.append(_crear_error_sinic(
                    helper, codigo, item["capa"], item["feature"],
                    f"En predios informales el avalúo catastral total debe corresponder únicamente al avalúo catastral de construcciones redondeado al mil (Total={total}, Terreno={terreno}, Esperado={esperado}).",
                    detalles
                ))
    return _resultado_sinic(codigo, errores)


def regla_105(layer_dict=None, layer_dic=None, **kwargs):
    """Predio activo exige avalúo catastral vigente correspondiente al año en curso del reporte."""
    codigo = "105"
    helper = EconomicoWebHelper(_capas(layer_dict, layer_dic))
    ctx = _build_economic_predio_context(helper)
    errores = []
    anio_referencia = _obtener_anio_referencia_vigencia(ctx)

    for p_key, p_info in ctx["predios_info"].items():
        if p_info["cancelado"]:
            continue
        aliases = p_info["aliases"]
        capa = p_info["capa"]
        feat = p_info["feature"]
        avs = p_info["avaluos"]
        vigentes = [a for a in avs if a.get("values", {}).get("vigencia") == anio_referencia]

        if not vigentes:
            vigencias = sorted({a.get("values", {}).get("vigencia") for a in avs if a.get("values", {}).get("vigencia") is not None})
            errores.append(_crear_error_sinic(
                helper, codigo, capa, feat,
                f"El predio activo no cancelado exige avalúo catastral vigente correspondiente al año {anio_referencia}, pero no registra esa vigencia.",
                {"tabla": p_info["tabla"], "identificadores_predio": sorted(aliases), "vigencia_esperada": anio_referencia, "vigencias_encontradas": vigencias}
            ))
            continue

        if not any((a.get("values", {}).get("valor_catastral") or 0) > 0 for a in vigentes):
            errores.append(_crear_error_sinic(
                helper, codigo, capa, feat,
                f"El predio activo tiene registro de avalúo para {anio_referencia}, pero el avalúo catastral no es mayor que cero.",
                {"tabla": p_info["tabla"], "identificadores_predio": sorted(aliases), "vigencia_esperada": anio_referencia}
            ))
    return _resultado_sinic(codigo, errores)


codigos_funciones = {
    "47": regla_47,
    "48": regla_48,
    "49": regla_49,
    "50": regla_50,
    "51": regla_51,
    "52": regla_52,
    "53": regla_53,
    "54": regla_54,
    "55": regla_55,
    "56": regla_56,
    "101": regla_101,
    "102": regla_102,
    "103": regla_103,
    "104": regla_104,
    "105": regla_105,
}

reglas_implementadas = {
    "47": regla_47,
    "48": regla_48,
    "49": regla_49,
    "50": regla_50,
    "51": regla_51,
    "52": regla_52,
    "53": regla_53,
    "54": regla_54,
    "55": regla_55,
    "56": regla_56,
    "101": regla_101,
    "102": regla_102,
    "103": regla_103,
    "104": regla_104,
    "105": regla_105,
}

reglas_exactas_pendientes_fuente = []
reglas_pendientes_logica = []
todas_las_reglas = list(codigos_funciones.keys())

clases_con_reglas = {'Economico': list(codigos_funciones.keys())}
RULE_FUNCTIONS = codigos_funciones


def aplicar_reglas(capas=None, codigos=None, incluir_pendientes=True):
    capas = capas if capas is not None else obtener_capas_relevantes()
    seleccion = list(codigos) if codigos is not None else (list(codigos_funciones.keys()) if incluir_pendientes else list(reglas_implementadas.keys()))
    return {codigo: codigos_funciones[codigo](layer_dict=capas) for codigo in seleccion if codigo in codigos_funciones}
