# -*- coding: utf-8 -*-
"""Reglas SINIC - Componente Jurídico.

Las equivalencias clasificadas como Exacta reutilizan sin modificar la lógica ARBIMAPS existente.
Las equivalencias Parciales, Relacionadas no equivalentes y Equivalentes por combinación
se implementan de forma específica según la descripción SINIC y la observación del cruce.
Las reglas sin correspondencia directa se implementan de forma nativa según la descripción SINIC.
Cuando una equivalencia Exacta apunta a una fuente ARBIMAPS que no está disponible o está vacía
en el paquete suministrado, se implementa la condición SINIC de forma explícita y se marca como
fallback nativo, sin modificar ni inventar la lógica ARBIMAPS fuente.
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict

from .compat import juridico as arb_jur
from .support import dataset_from_layers, issues_to_result
from .compat.juridico import _derecho_tipo_ilicode

WebProject = None
WebSpatialIndex = None

from .engine import ejecutar_regla_exacta, resultado_pendiente, metadata_regla

COMPONENT_SLUG = 'juridico'
LAYER_ALIASES = {}

def obtener_capas_relevantes():
    if WebProject is None:
        return {}
    capas = {}
    try:
        for layer in WebProject.instance().mapLayers().values():
            try: capas[layer.name()] = layer
            except Exception: pass
    except Exception:
        pass
    return capas

def _capas(layer_dict=None, layer_dic=None):
    return layer_dict if layer_dict is not None else (layer_dic if layer_dic is not None else obtener_capas_relevantes())


# -----------------------------------------------------------------------------
# SOPORTE PARA REGLAS SINIC PARCIALES / RELACIONADAS
# -----------------------------------------------------------------------------
# Las reglas clasificadas como Exacta NO pasan por estas funciones: continúan
# ejecutando la lógica ARBIMAPS original mediante ejecutar_regla_exacta().

OFICINA_FIELDS = (
    "fa_oficina", "FA_Oficina", "oficina", "Oficina", "oficina_registro",
    "Oficina_Registro", "oficina_fuente", "Oficina_Fuente",
    "oficina_origen", "Oficina_Origen",
)
CIUDAD_FIELDS = (
    "fa_ciudad", "FA_Ciudad", "ciudad", "Ciudad", "ciudad_fuente",
    "Ciudad_Fuente", "municipio_fuente", "Municipio_Fuente",
    "ciudad_origen", "Ciudad_Origen",
)
ESTADO_PREDIO_FIELDS = (
    "Estado", "estado", "estado_predio", "Estado_Predio", "estado_ladm", "Estado_Ladm",
)
AGRUPACION_RELATION_FIELDS = (
    "agrupacion", "Agrupacion", "agrupacion_interesados", "Agrupacion_Interesados",
    "grupo_interesados", "Grupo_Interesados", "col_agrupacioninteresados",
    "cr_agrupacioninteresados", "id_agrupacion", "agrupacion_id",
)
DERECHO_ID_FIELDS = (
    "d_tid", "D_TID", "d_t_ili_tid", "D_T_Ili_Tid", "id_derecho", "ID_DERECHO",
    "derecho_id", "Derecho_ID", "derecho", "Derecho",
)

LAYER_ALIASES.update({
    "ARB_Predio": ("ARB_Predio", "arb_predio", "A_Predio", "a_predio", "CCA_Predio", "cca_predio", "Predio"),
    "ARB_Terreno": ("ARB_Terreno", "arb_terreno", "ARB-Terreno", "Terreno", "terreno", "CCA_Terreno", "cca_terreno"),
    "ARB_Predio_Terreno": ("ARB_Predio_Terreno", "ARB_PredioTerreno", "arb_predio_terreno", "arb_predioterreno", "CCA_Predio_Terreno", "cca_predio_terreno"),
    "COL_AgrupacionInteresados": ("COL_AgrupacionInteresados", "col_agrupacioninteresados", "CR_AgrupacionInteresados", "cr_agrupacioninteresados", "AgrupacionInteresados", "Agrupacion Interesados"),
    "COL_Miembros": ("COL_Miembros", "col_miembros", "CR_Miembros", "cr_miembros", "Miembros"),
})


def _norm_token(value):
    if value is None:
        return ""
    text = str(value).strip().upper()
    text = "".join(
        ch for ch in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(ch)
    )
    return "".join(ch for ch in text if ch.isalnum())


def _raw_text(value):
    if value is None:
        return ""
    try:
        if hasattr(value, "isNull") and value.isNull():
            return ""
    except Exception:
        pass
    text = str(value).strip()
    if text.lower() in {"", "none", "null", "<null>", "nan"}:
        return ""
    return text


def _dataset_y_helper(layer_dict=None, layer_dic=None):
    capas = _capas(layer_dict, layer_dic)
    dataset = dataset_from_layers(capas)
    return capas, dataset, arb_jur.JuridicoHelper(dataset)


def _resultado_issues(codigo, issues, dataset, equivalencia, origen):
    resultado = issues_to_result(str(codigo), issues)
    meta = metadata_regla(str(codigo))
    for err in resultado.get("errores", []) or []:
        detalles = dict(err.get("detalles") or err.get("details") or {})
        detalles.update({
            "sinic_id": str(codigo),
            "tipo_equivalencia": equivalencia,
            "arbimaps_regla_origen": origen,
            "implementacion": "SINIC_AJUSTADA",
        })
        err["regla"] = str(codigo)
        err["detalles"] = detalles
        err["details"] = detalles
    resultado["regla_sinic"] = meta
    return resultado


def _resultado_errores(codigo, errores, equivalencia, origen):
    meta = metadata_regla(str(codigo))
    salida = []
    for original in errores:
        err = dict(original)
        detalles = dict(err.get("detalles") or err.get("details") or {})
        detalles.update({
            "sinic_id": str(codigo),
            "tipo_equivalencia": equivalencia,
            "arbimaps_regla_origen": origen,
            "implementacion": "SINIC_AJUSTADA",
        })
        err["regla"] = str(codigo)
        err["detalles"] = detalles
        err["details"] = detalles
        salida.append(err)
    return {
        "cumple": len(salida) == 0,
        "errores": salida,
        "mensaje": (
            f"Se detectaron {len(salida)} incumplimientos en la regla SINIC {codigo}."
            if salida else f"No se detectaron errores en la regla SINIC {codigo}."
        ),
        "regla_sinic": meta,
    }


def _resultado_omitido(codigo, mensaje):
    # Las reglas 1-4 son las únicas omitidas por decisión del proyecto. Para una
    # regla activa, la ausencia de una capa/relación necesaria significa que no
    # pudo verificarse; nunca debe presentarse como omitida ni como cumplimiento.
    mensaje = str(mensaje).replace(" omitida:", " no verificable:")
    return {
        "cumple": True,
        "no_verificable": True,
        "errores": [],
        "mensaje": mensaje,
        "motivo_no_verificable": mensaje,
        "regla_sinic": metadata_regla(str(codigo)),
    }


def _raw_row_value(helper, row, candidates):
    try:
        match = helper._extract_field(row, tuple(candidates), require_value=False)
    except Exception:
        match = None
    return match[1] if match else None


def _stable_ref(value):
    if value in (None, ""):
        return ""
    try:
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
    except Exception:
        pass
    text = str(value).strip().strip("{}")
    if re.fullmatch(r"[-+]?\d+\.0+", text):
        text = text.split(".", 1)[0]
    return text


def _predio_ids(helper, predio_row):
    ids = set()
    for field in arb_jur.PREDIO_IDENTIFIER_FIELDS + arb_jur.NUMERO_PREDIAL_FIELDS:
        value = helper.get_field_value(predio_row, (field,))
        key = _stable_ref(value)
        if key:
            ids.add(key)
    return ids


def _relaciones_por_predio(helper):
    """Indexa DerechoInteresadoFuente por claves estables del predio.

    No usa ``id(dict)``: DatasetReader puede materializar un nuevo diccionario en
    cada iteración y eso hacía que una relación válida apareciera inexistente.
    """
    predios_by_id = arb_jur._indexar_predios_por_identificador(helper)
    relaciones = defaultdict(list)
    for table_name, row in helper.iter_derecho_interesado_fuente():
        predio_ref, predio_row = arb_jur._buscar_predio_relacionado(helper, row, predios_by_id)
        keys = set()
        if predio_row is not None:
            keys.update(_predio_ids(helper, predio_row))
        ref = _stable_ref(predio_ref)
        if ref:
            keys.add(ref)
        for key in keys:
            relaciones[("ref", key)].append((table_name, row))
    return predios_by_id, relaciones


def _relaciones_de_predio(helper, predio_row, relaciones):
    rows = []
    vistos = set()
    for key in _predio_ids(helper, predio_row):
        for item in relaciones.get(("ref", key), []):
            marker = id(item[1])
            if marker not in vistos:
                rows.append(item)
                vistos.add(marker)
    return rows


def _tipo_predio(helper, predio_row):
    return str(helper.get_field_value(predio_row, ("tipo", "Tipo", "tipo_predio", "Tipo_Predio")) or "").strip()


def _condicion_predio(helper, predio_row):
    return str(helper.get_field_value(predio_row, ("Condicion_Predio", "condicion_predio", "condicion", "Condicion")) or "").strip()


def _predio_es_matriz(helper, predio_row):
    return "MATRIZ" in _norm_token(_condicion_predio(helper, predio_row))


def _predio_activo(helper, predio_row):
    """Considera activo salvo que exista un estado explícitamente inactivo/cancelado.

    Algunas materializaciones XTF/web no exponen Estado en ARB_Predio. En ese caso el
    registro pertenece al universo vigente cargado y no debe excluirse por ausencia del campo.
    """
    estado = helper.get_field_value(predio_row, ESTADO_PREDIO_FIELDS)
    if not estado:
        return True
    token = _norm_token(estado)
    if any(x in token for x in ("INACTIVO", "CANCELADO", "CANCELACION", "RETIRADO", "ELIMINADO")):
        return False
    return True


def _tipo_documento(helper, row):
    return str(helper.get_field_value(row, ("i_tipo_documento", "I_Tipo_Documento", "tipo_documento", "Tipo_Documento")) or "").strip()


def _firma_interesado(helper, row):
    tipo = arb_jur._tipo_interesado_ilicode(helper.get_field_value(row, arb_jur.TIPO_INTERESADO_FIELDS))
    documento = arb_jur._normalizar_documento_identidad(helper.get_field_value(row, arb_jur.DOCUMENTO_IDENTIDAD_FIELDS))
    razon = helper.get_field_value(row, arb_jur.RAZON_SOCIAL_FIELDS)
    nombre = arb_jur._nombre_completo_interesado(row, helper)
    if documento:
        return f"DOC:{documento}"
    if razon:
        return "J:" + arb_jur._normalize_text_for_compare(razon)
    if nombre:
        return "N:" + arb_jur._normalize_text_for_compare(nombre)
    if tipo:
        return f"TIPO:{tipo}"
    return ""


def _tiene_agrupacion(helper, row):
    value = _raw_row_value(helper, row, AGRUPACION_RELATION_FIELDS)
    return bool(_raw_text(value))


def _tiene_interesado_o_agrupacion(helper, row):
    return bool(_firma_interesado(helper, row) or _tiene_agrupacion(helper, row))


def _tipo_fuente(helper, row):
    value = helper.get_field_value(row, arb_jur.TIPO_FUENTE_FIELDS)
    return arb_jur._fuente_tipo_ilicode(value)


def _fuente_presente(helper, row):
    candidatos = (
        arb_jur.TIPO_FUENTE_FIELDS,
        arb_jur.ENTE_EMISOR_FIELDS,
        arb_jur.NUMERO_FUENTE_FIELDS,
        arb_jur.FECHA_FUENTE_FIELDS,
        OFICINA_FIELDS,
        CIUDAD_FIELDS,
    )
    return any(helper.get_field_value(row, fields) is not None for fields in candidatos)


def _sexo_sinic(helper, row):
    raw = _raw_row_value(helper, row, arb_jur.SEXO_FIELDS)

    # Si Sexo está vacío o es nulo, interpretar No_Aplica.
    if not _raw_text(raw):
        return "No_Aplica"

    token_raw = _norm_token(raw)
    if token_raw in {"NOAPLICA", "NOAPLICABLE"}:
        return "No_Aplica"
    if token_raw in {"NOBINARIO", "NOBINARIA"}:
        return "No_Binario"

    normalized = arb_jur._normalizar_valor_dominio("i_sexo", raw)
    token = _norm_token(normalized)

    if token == "MASCULINO":
        return "Masculino"
    if token == "FEMENINO":
        return "Femenino"
    if token == "SINDETERMINAR":
        return "Sin_Determinar"
    if token in {"NOBINARIO", "NOBINARIA"}:
        return "No_Binario"

    return _raw_text(raw)


def _derechos_tipos(helper, rows):
    return [
        arb_jur._derecho_tipo_ilicode(helper.get_field_value(row, arb_jur.TIPO_DERECHO_FIELDS))
        for _, row in rows
    ]


def _derecho_identity(helper, row):
    raw_id = _raw_row_value(helper, row, DERECHO_ID_FIELDS)
    if _raw_text(raw_id):
        return "ID:" + _raw_text(raw_id).strip("{}")
    tipo = arb_jur._derecho_tipo_ilicode(helper.get_field_value(row, arb_jur.TIPO_DERECHO_FIELDS))
    return "TIPO:" + tipo if tipo else ""


# ------------------------- utilidades web espaciales -------------------------

def _nombre_capa(layer):
    try:
        return layer.name()
    except Exception:
        return ""


def _find_layer(capas, aliases):
    aliases_norm = {_norm_token(alias) for alias in aliases}
    for key, layer in (capas or {}).items():
        if layer is None:
            continue
        if _norm_token(key) in aliases_norm or _norm_token(_nombre_capa(layer)) in aliases_norm:
            return layer
    if WebProject is not None:
        try:
            for layer in WebProject.instance().mapLayers().values():
                if _norm_token(_nombre_capa(layer)) in aliases_norm:
                    return layer
        except Exception:
            pass
    return None


def _field_map(layer):
    result = {}
    if layer is None:
        return result
    try:
        for field in layer.fields():
            result.setdefault(_norm_token(field.name()), field.name())
    except Exception:
        pass
    return result


def _feature_value(feature, layer, candidates):
    fmap = _field_map(layer)
    for candidate in candidates:
        field_name = fmap.get(_norm_token(candidate))
        if not field_name:
            continue
        try:
            value = feature[field_name]
        except Exception:
            try:
                value = feature.attribute(field_name)
            except Exception:
                value = None
        if _raw_text(value):
            return value
    return None


def _feature_values(feature, layer, candidates):
    values = set()
    fmap = _field_map(layer)
    for candidate in candidates:
        field_name = fmap.get(_norm_token(candidate))
        if not field_name:
            continue
        try:
            value = feature[field_name]
        except Exception:
            try:
                value = feature.attribute(field_name)
            except Exception:
                value = None
        text = _raw_text(value).strip("{}")
        if text:
            values.add(text)
    return values


def _features(layer):
    if layer is None:
        return []
    try:
        return list(layer.getFeatures())
    except Exception:
        return []


def _feature_id(feature):
    try:
        return str(feature.id())
    except Exception:
        return str(id(feature))


def _feature_geometry(feature):
    """Obtiene geometría tanto de QgsGeometry como de Shapely/WebFeature."""
    try:
        geom = feature.geometry()
    except Exception:
        geom = None
    if geom is None:
        return None
    try:
        if hasattr(geom, "isEmpty") and geom.isEmpty():
            return None
    except Exception:
        pass
    try:
        if hasattr(geom, "is_empty") and bool(geom.is_empty):
            return None
    except Exception:
        pass
    return geom


def _error_feature(codigo, layer, feature, descripcion, detalles=None):
    detalles = dict(detalles or {})
    npn = _raw_text(_feature_value(feature, layer, arb_jur.NUMERO_PREDIAL_FIELDS))
    aid = npn or _raw_text(_feature_value(feature, layer, arb_jur.PREDIO_IDENTIFIER_FIELDS)) or _feature_id(feature)
    return {
        "aid": aid,
        "descripcion": descripcion,
        "capa": layer,
        "regla": str(codigo),
        "detalles": detalles,
        "details": detalles,
    }


_PREDIO_KEYS_WEB = tuple(dict.fromkeys(arb_jur.PREDIO_IDENTIFIER_FIELDS + arb_jur.NUMERO_PREDIAL_FIELDS + (
    "codigo_homologado", "Codigo_Homologado", "nupre", "NUPRE",
)))
_TERRENO_KEYS_WEB = (
    "TID", "tid", "t_id", "T_Id", "T_ID", "id", "t_ili_tid", "T_Ili_Tid", "T_ILI_TID",
    "identificador", "Identificador",
)
_TERRENO_PREDIO_REFS = (
    "predio", "Predio", "arb_predio", "ARB_Predio", "id_predio", "Id_Predio",
    "predio_id", "Predio_ID", "id_operacion", "Id_Operacion", "numero_predial", "Numero_Predial",
)
_ASOC_PREDIO_REFS = _TERRENO_PREDIO_REFS
_ASOC_TERRENO_REFS = (
    "terreno", "Terreno", "arb_terreno", "ARB_Terreno", "id_terreno", "Id_Terreno", "terreno_id", "Terreno_ID",
)


def _predios_y_terrenos(capas):
    predio_layer = _find_layer(capas, LAYER_ALIASES["ARB_Predio"])
    terreno_layer = _find_layer(capas, LAYER_ALIASES["ARB_Terreno"])
    if predio_layer is None or terreno_layer is None:
        return predio_layer, terreno_layer, []

    predio_index = {}
    predios_info = []
    for feature in _features(predio_layer):
        keys = _feature_values(feature, predio_layer, _PREDIO_KEYS_WEB)
        npn = _raw_text(_feature_value(feature, predio_layer, arb_jur.NUMERO_PREDIAL_FIELDS))
        if npn:
            keys.add(npn)
        tipo_raw = _feature_value(feature, predio_layer, ("tipo", "Tipo", "tipo_predio", "Tipo_Predio"))
        cond_raw = _feature_value(feature, predio_layer, ("Condicion_Predio", "condicion_predio", "condicion", "Condicion"))
        tipo = arb_jur._normalizar_valor_dominio("tipo", tipo_raw)
        condicion = arb_jur._normalizar_valor_dominio("condicion_predio", cond_raw)
        info = {
            "feature": feature,
            "keys": keys,
            "npn": npn,
            "tipo": str(tipo or tipo_raw or "").strip(),
            "condicion": str(condicion or cond_raw or "").strip(),
        }
        predios_info.append(info)
        for key in keys:
            predio_index.setdefault(str(key).strip("{}"), info)

    association = defaultdict(set)
    asoc_layer = _find_layer(capas, LAYER_ALIASES["ARB_Predio_Terreno"])
    if asoc_layer is not None:
        for feature in _features(asoc_layer):
            predio_refs = _feature_values(feature, asoc_layer, _ASOC_PREDIO_REFS)
            terreno_refs = _feature_values(feature, asoc_layer, _ASOC_TERRENO_REFS)
            for terreno_ref in terreno_refs:
                association[terreno_ref].update(predio_refs)

    terrain_items = []
    for feature in _features(terreno_layer):
        geom = _feature_geometry(feature)
        if geom is None:
            continue
        predio_refs = _feature_values(feature, terreno_layer, _TERRENO_PREDIO_REFS)
        terreno_keys = _feature_values(feature, terreno_layer, _TERRENO_KEYS_WEB)
        for key in terreno_keys:
            predio_refs.update(association.get(key, set()))
        matched = []
        seen = set()
        for ref in predio_refs:
            info = predio_index.get(str(ref).strip("{}"))
            if info is not None and id(info) not in seen:
                seen.add(id(info))
                matched.append(info)
        for info in matched:
            terrain_items.append({
                "feature": feature,
                "geom": geom,
                "predio": info,
            })

    return predio_layer, terreno_layer, terrain_items


def _positive_area_overlap(g1, g2):
    try:
        if not g1.boundingBox().intersects(g2.boundingBox()):
            return False
    except Exception:
        pass
    try:
        if not g1.intersects(g2):
            return False
        intersection = g1.intersection(g2)
        if intersection is None or intersection.isEmpty():
            return False
        return float(intersection.area() or 0.0) > 1e-8
    except Exception:
        try:
            return bool(g1.overlaps(g2) or g1.contains(g2) or g2.contains(g1))
        except Exception:
            return False


def _superposiciones_informal(capas, tipos_objetivo):
    predio_layer, terreno_layer, items = _predios_y_terrenos(capas)
    if predio_layer is None or terreno_layer is None:
        return predio_layer, []

    informales = [item for item in items if _norm_token(item["predio"]["condicion"]) == "INFORMAL"]
    objetivos = [item for item in items if item["predio"]["tipo"] in tipos_objetivo]
    if not informales or not objetivos:
        return predio_layer, []

    target_by_fid = defaultdict(list)
    spatial_index = None
    if WebSpatialIndex is not None:
        try:
            spatial_index = WebSpatialIndex()
            added = set()
            for item in objetivos:
                fid = int(item["feature"].id())
                target_by_fid[fid].append(item)
                if fid not in added:
                    spatial_index.addFeature(item["feature"])
                    added.add(fid)
        except Exception:
            spatial_index = None
            target_by_fid.clear()

    pairs = []
    seen = set()
    for informal in informales:
        if spatial_index is not None:
            try:
                candidate_items = []
                for fid in spatial_index.intersects(informal["geom"].boundingBox()):
                    candidate_items.extend(target_by_fid.get(int(fid), []))
            except Exception:
                candidate_items = objetivos
        else:
            candidate_items = objetivos

        for objetivo in candidate_items:
            if informal["predio"] is objetivo["predio"]:
                continue
            if not _positive_area_overlap(informal["geom"], objetivo["geom"]):
                continue
            a = informal["predio"]
            b = objetivo["predio"]
            key = (
                a.get("npn") or next(iter(a.get("keys") or []), _feature_id(a["feature"])),
                b.get("npn") or next(iter(b.get("keys") or []), _feature_id(b["feature"])),
            )
            if key in seen:
                continue
            seen.add(key)
            pairs.append((a, b))
    return predio_layer, pairs


def _derechos_por_identificador(helper):
    predios_by_id = arb_jur._indexar_predios_por_identificador(helper)
    result = defaultdict(set)
    for _, row in helper.iter_derecho_interesado_fuente():
        predio_ref, predio_row = arb_jur._buscar_predio_relacionado(helper, row, predios_by_id)
        tipo = arb_jur._derecho_tipo_ilicode(helper.get_field_value(row, arb_jur.TIPO_DERECHO_FIELDS))
        if not tipo:
            continue
        if predio_row is not None:
            for key in _predio_ids(helper, predio_row):
                result[key].add(tipo)
        elif predio_ref:
            result[str(predio_ref).strip().strip("{}")].add(tipo)
    return result


def _derechos_de_info(info, derechos_index):
    tipos = set()
    for key in info.get("keys", set()):
        tipos.update(derechos_index.get(str(key).strip("{}"), set()))
    npn = info.get("npn")
    if npn:
        tipos.update(derechos_index.get(str(npn), set()))
    return tipos


def _find_group_layers(capas):
    grupos = _find_layer(capas, LAYER_ALIASES["COL_AgrupacionInteresados"])
    miembros = _find_layer(capas, LAYER_ALIASES["COL_Miembros"])
    return grupos, miembros


def _group_id_feature(feature, layer):
    value = _feature_value(feature, layer, (
        "T_Ili_Tid", "t_ili_tid", "TID", "tid", "T_Id", "t_id", "id", "identificador", "Identificador",
    ))
    return _raw_text(value).strip("{}") or _feature_id(feature)


def _to_float(value):
    text = _raw_text(value).replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except Exception:
        return None



# ----------------------- utilidades SINIC juridicas nativas -----------------------

AGRUPACION_TIPO_FIELDS = (
    "tipo", "Tipo", "tipo_agrupacion", "Tipo_Agrupacion",
    "tipo_agrupacion_interesados", "Tipo_Agrupacion_Interesados",
    "agrupacion_tipo", "Agrupacion_Tipo",
)

TRAMITE_REF_FIELDS = (
    "tramite", "Tramite", "trámite", "Trámite", "arb_tramite", "ARB_Tramite",
    "ilc_tramite", "ILC_Tramite", "tramite_id", "id_tramite", "Id_Tramite",
)

PREDIO_REF_WEB_FIELDS = tuple(dict.fromkeys(
    arb_jur.PREDIO_IDENTIFIER_FIELDS + arb_jur.NUMERO_PREDIAL_FIELDS + (
        "predio", "Predio", "arb_predio", "ARB_Predio", "ilc_predio", "ILC_Predio",
        "predio_id", "id_predio", "Id_Predio", "predio_asociado", "Predio_Asociado",
    )
))


def _layer_name(layer):
    try:
        return str(layer.name())
    except Exception:
        return ""


def _iter_unique_layers(capas):
    seen = set()
    for layer in (capas or {}).values():
        if layer is None or id(layer) in seen:
            continue
        seen.add(id(layer))
        yield layer
    if WebProject is not None:
        try:
            for layer in WebProject.instance().mapLayers().values():
                if layer is None or id(layer) in seen:
                    continue
                seen.add(id(layer))
                yield layer
        except Exception:
            pass


def _layers_matching(capas, predicate):
    result = []
    for layer in _iter_unique_layers(capas):
        try:
            if predicate(_norm_token(_layer_name(layer))):
                result.append(layer)
        except Exception:
            pass
    return result


def _feature_aliases_local(feature, layer, extra_fields=()):
    fields = tuple(dict.fromkeys(PREDIO_REF_WEB_FIELDS + tuple(extra_fields) + (
        "TID", "tid", "t_id", "T_Id", "T_ID", "t_ili_tid", "T_Ili_Tid", "T_ILI_TID",
        "id", "ID", "id_operacion", "Id_Operacion", "local_id", "Local_ID",
    )))
    values = _feature_values(feature, layer, fields)
    try:
        values.add(str(feature.id()))
    except Exception:
        pass
    return {str(v).strip().strip("{}") for v in values if _raw_text(v)}


def _feature_values_name_contains(feature, layer, token):
    token = _norm_token(token)
    fmap = _field_map(layer)
    values = set()
    for norm_name, real_name in fmap.items():
        if token not in norm_name:
            continue
        try:
            value = feature[real_name]
        except Exception:
            try:
                value = feature.attribute(real_name)
            except Exception:
                value = None
        text = _raw_text(value).strip("{}")
        if text:
            values.add(text)
    return values


def _predio_feature_index(capas):
    predio_layers = _layers_matching(
        capas,
        lambda n: n in {"ARBPREDIO", "ILCPREDIO", "APREDIO", "PREDIO"}
        or n.endswith("ARBPREDIO") or n.endswith("ILCPREDIO"),
    )
    infos = []
    alias_index = {}
    for layer in predio_layers:
        for feature in _features(layer):
            aliases = _feature_aliases_local(feature, layer)
            npn = _raw_text(_feature_value(feature, layer, arb_jur.NUMERO_PREDIAL_FIELDS))
            if npn:
                aliases.add(npn.strip("{}"))
            condicion_raw = _feature_value(feature, layer, ("Condicion_Predio", "condicion_predio", "condicion", "Condicion"))
            tipo_raw = _feature_value(feature, layer, ("tipo", "Tipo", "tipo_predio", "Tipo_Predio"))
            condicion = arb_jur._normalizar_valor_dominio("condicion_predio", condicion_raw)
            tipo = arb_jur._normalizar_valor_dominio("tipo", tipo_raw)
            info = {
                "layer": layer,
                "feature": feature,
                "aliases": aliases,
                "npn": npn,
                "condicion": str(condicion or condicion_raw or "").strip(),
                "tipo": str(tipo or tipo_raw or "").strip(),
            }
            infos.append(info)
            for alias in aliases:
                alias_index.setdefault(alias, info)
    return predio_layers, infos, alias_index


def _predios_con_tramite(capas):
    predio_layers, infos, alias_index = _predio_feature_index(capas)
    if not predio_layers:
        return set(), [], []

    asociados = set()
    relation_layers = _layers_matching(capas, lambda n: "TRAMITE" in n and "PREDIO" in n)
    tramite_layers = _layers_matching(
        capas,
        lambda n: "TRAMITE" in n and "PREDIO" not in n and "TIPO" not in n
        and "CATALOGO" not in n and "DOMINIO" not in n,
    )

    def mark(info):
        if info:
            asociados.update(info.get("aliases") or set())

    # Referencia directa en ARB_Predio.
    for info in infos:
        feature, layer = info["feature"], info["layer"]
        if _feature_values_name_contains(feature, layer, "tramite"):
            mark(info)

    # Tablas de relación Predio-Trámite.
    for layer in relation_layers:
        for feature in _features(layer):
            tramites = _feature_values_name_contains(feature, layer, "tramite")
            if not tramites:
                continue
            refs = _feature_values_name_contains(feature, layer, "predio")
            for ref in refs:
                mark(alias_index.get(str(ref).strip("{}")))

    # Trámite con FK directa al predio.
    for layer in tramite_layers:
        for feature in _features(layer):
            refs = _feature_values_name_contains(feature, layer, "predio")
            for ref in refs:
                mark(alias_index.get(str(ref).strip("{}")))

    return asociados, tramite_layers, relation_layers


def _informales_vinculados_a_formal(capas):
    predio_layers, infos, alias_index = _predio_feature_index(capas)
    if not predio_layers:
        return set(), []
    vinculados = set()
    relation_layers = _layers_matching(capas, lambda n: "INFORMALIDAD" in n and "PREDIO" in n)

    def is_informal(info):
        return _norm_token((info or {}).get("condicion")) == "INFORMAL"

    def mark(info):
        if info:
            vinculados.update(info.get("aliases") or set())

    # Algunas materializaciones guardan una referencia formal directamente en el predio informal.
    for info in infos:
        if not is_informal(info):
            continue
        feature, layer = info["feature"], info["layer"]
        formal_refs = _feature_values_name_contains(feature, layer, "formal")
        if any(alias_index.get(str(ref).strip("{}")) and not is_informal(alias_index.get(str(ref).strip("{}"))) for ref in formal_refs):
            mark(info)

    for layer in relation_layers:
        for feature in _features(layer):
            refs = set()
            refs.update(_feature_values_name_contains(feature, layer, "predio"))
            refs.update(_feature_values_name_contains(feature, layer, "formal"))
            refs.update(_feature_values_name_contains(feature, layer, "informal"))
            matched = []
            seen = set()
            for ref in refs:
                info = alias_index.get(str(ref).strip("{}"))
                if info is not None and id(info) not in seen:
                    seen.add(id(info)); matched.append(info)
            if len(matched) < 2:
                continue
            informales = [x for x in matched if is_informal(x)]
            formales = [x for x in matched if not is_informal(x)]
            if formales:
                for info in informales:
                    mark(info)
    return vinculados, relation_layers


def _normalizar_tipo_agrupacion(value):
    token = _norm_token(value)
    if token in {"GRUPOCIVIL", "CIVIL"}:
        return "Grupo_Civil"
    if token in {"GRUPOEMPRESARIAL", "EMPRESARIAL"}:
        return "Grupo_Empresarial"
    if token in {"GRUPOMIXTO", "MIXTO"}:
        return "Grupo_Mixto"
    return _raw_text(value)


def _group_type_alias_map(capas):
    grupos_layer = _find_layer(capas, LAYER_ALIASES["COL_AgrupacionInteresados"])
    result = {}
    if grupos_layer is None:
        return result
    for feature in _features(grupos_layer):
        tipo = _normalizar_tipo_agrupacion(_feature_value(feature, grupos_layer, AGRUPACION_TIPO_FIELDS))
        aliases = _feature_aliases_local(feature, grupos_layer)
        aliases.add(_group_id_feature(feature, grupos_layer))
        for alias in aliases:
            if alias:
                result[str(alias).strip("{}")] = tipo
    return result


def _agrupaciones_interesados(helper, capas):
    type_map = _group_type_alias_map(capas)
    groups = {}
    for table_name, row in helper.iter_derecho_interesado_fuente():
        raw_gid = _raw_row_value(helper, row, AGRUPACION_RELATION_FIELDS)
        gid = _raw_text(raw_gid).strip("{}")
        if not gid:
            continue
        item = groups.setdefault(gid, {"tipos": set(), "tipo_agrupacion": "", "row": row, "tabla": table_name})
        tipo_interesado = arb_jur._tipo_interesado_ilicode(helper.get_field_value(row, arb_jur.TIPO_INTERESADO_FIELDS))
        if tipo_interesado:
            item["tipos"].add(tipo_interesado)
        tipo_directo = _raw_row_value(helper, row, AGRUPACION_TIPO_FIELDS)
        tipo_grupo = _normalizar_tipo_agrupacion(tipo_directo) or type_map.get(gid, "")
        if tipo_grupo:
            item["tipo_agrupacion"] = tipo_grupo
    return groups, bool(type_map)

def regla_45(layer_dict=None, layer_dic=None, **kwargs):
    """Todo predio activo debe contar con una Matrícula Inmobiliaria no duplicada.

    La lógica fuente 1.12 no está ejecutable en el paquete actual; se valida de
    forma nativa para evitar que la regla quede silenciosamente pendiente.
    """
    _, dataset, helper = _dataset_y_helper(layer_dict, layer_dic)
    if not dataset.has_table("ARB_Predio"):
        return _resultado_omitido("45", "Regla SINIC 45 no verificable: no se encontró ARB_Predio.")
    by_fmi = defaultdict(list)
    for table_name, predio in helper.iter_predios():
        if not _predio_activo(helper, predio):
            continue
        fmi = _raw_text(helper.get_field_value(predio, arb_jur.MATRICULA_INMOBILIARIA_FIELDS))
        # La regla 45 es de unicidad. La obligatoriedad/no-cero se controla en
        # reglas jurídicas específicas; vacíos no deben convertirse en un falso
        # "duplicado" entre muchos predios.
        if not fmi or arb_jur._matricula_es_vacia_o_cero(fmi):
            continue
        by_fmi[fmi.upper()].append((table_name, predio, fmi))
    issues=[]
    for rows in by_fmi.values():
        if len(rows) < 2:
            continue
        aids=[]
        for _, p, _ in rows:
            ids=sorted(_predio_ids(helper,p)); aids.append(ids[0] if ids else "")
        for table_name, predio, fmi in rows:
            issues.append(helper.make_issue(
                predio, rule_id="45",
                message="La Matrícula Inmobiliaria de un predio activo no puede estar duplicada en otro predio activo.",
                details={"tabla":table_name,"matricula_inmobiliaria":fmi,"cantidad_predios":len(rows),"predios_relacionados":aids,"numero_predial":helper.get_field_value(predio,arb_jur.NUMERO_PREDIAL_FIELDS)},
            ))
    result=_resultado_issues("45",issues,dataset,"Exacta","1.12 (SINIC nativo: fuente no ejecutable)")
    if not bool(kwargs.get("dataset_completo")):
        result["no_verificable"]=True; result["verificacion_parcial"]=True
        result["motivo_no_verificable"]="La unicidad global de FMI requiere contrastar contra la base catastral completa, no solo el XTF de asignación."
        result["mensaje"] += " Validación parcial: la unicidad global requiere la base catastral completa."
    return result

def regla_46(layer_dict=None, layer_dic=None, **kwargs):
    """Predios en condición Informal deben estar vinculados al menos a un predio formal registrado."""
    # Equivalencia del cruce: Exacta | ARBIMAPS: 1.50
    # La fuente 1.50 no está disponible de forma ejecutable en el paquete suministrado.
    # Se implementa literalmente la condición SINIC sin alterar el módulo ARBIMAPS.
    capas, dataset, helper = _dataset_y_helper(layer_dict, layer_dic)
    vinculados, relation_layers = _informales_vinculados_a_formal(capas)
    if not dataset.has_table("ARB_Predio"):
        return _resultado_omitido("46", "Regla SINIC 46 omitida: no se encontró ARB_Predio.")
    if not relation_layers and not vinculados:
        return _resultado_omitido("46", "Regla SINIC 46 omitida: no se encontró la relación Predio-Informalidad necesaria para comprobar el vínculo con un predio formal.")
    issues = []
    for table_name, predio in helper.iter_predios():
        if _norm_token(_condicion_predio(helper, predio)) != "INFORMAL":
            continue
        ids = _predio_ids(helper, predio)
        if ids.intersection(vinculados):
            continue
        issues.append(helper.make_issue(
            predio, rule_id="46",
            message="Todo predio en condición Informal debe estar vinculado al menos a un predio formal registrado.",
            details={"tabla": table_name, "condicion_predio": _condicion_predio(helper, predio),
                     "numero_predial": helper.get_field_value(predio, arb_jur.NUMERO_PREDIAL_FIELDS),
                     "capas_informalidad_revisadas": [_layer_name(x) for x in relation_layers]},
        ))
    return _resultado_issues("46", issues, dataset, "Exacta", "1.50 (fallback SINIC nativo: fuente no disponible)")

def regla_66(layer_dict=None, layer_dic=None, **kwargs):
    """Derecho de tipo Dominio exige condición de predio formal (diferente a informal)."""
    # Equivalencia del cruce: Parcial | ARBIMAPS: 2.2
    # Ajuste SINIC: de 2.2 se conserva la relación Derecho-Predio, pero aquí se
    # valida directamente Dominio -> condición distinta de Informal, sin exigir FMI.
    _, dataset, helper = _dataset_y_helper(layer_dict, layer_dic)
    if not dataset.has_table("ARB_DerechoInteresadoFuente") or not dataset.has_table("ARB_Predio"):
        return _resultado_omitido("66", "Regla SINIC 66 omitida: faltan ARB_DerechoInteresadoFuente o ARB_Predio.")
    issues = []
    predios_by_id = arb_jur._indexar_predios_por_identificador(helper)
    for table_name, row in helper.iter_derecho_interesado_fuente():
        tipo_derecho = arb_jur._derecho_tipo_ilicode(helper.get_field_value(row, arb_jur.TIPO_DERECHO_FIELDS))
        if tipo_derecho != "Dominio":
            continue
        predio_ref, predio_row = arb_jur._buscar_predio_relacionado(helper, row, predios_by_id)
        if not predio_row:
            continue
        condicion = _condicion_predio(helper, predio_row)
        if _norm_token(condicion) == "INFORMAL":
            issues.append(helper.make_issue(
                row,
                rule_id="66",
                message="Un derecho de tipo Dominio debe estar asociado a un predio formal; la condición del predio no puede ser Informal.",
                details={"tabla": table_name, "tipo_derecho": tipo_derecho, "condicion_predio": condicion, "predio_ref": predio_ref},
            ))
    return _resultado_issues("66", issues, dataset, "Parcial", "2.2")

def regla_67(layer_dict=None, layer_dic=None, **kwargs):
    """Derecho de tipo Posesión exige tipo de predio Privado."""
    # Equivalencia Exacta con ARBIMAPS: 2.3
    return ejecutar_regla_exacta("67", _capas(layer_dict, layer_dic))

def regla_68(layer_dict=None, layer_dic=None, **kwargs):
    """Derecho de tipo Ocupación exige tipo de predio Público (Baldío, Fiscal, Uso Público, Presunto Baldío)."""
    # Equivalencia del cruce: Parcial | ARBIMAPS: 2.4; 2.5
    # Ajuste SINIC: 2.4 prohíbe Ocupación en privados y 2.5 prohíbe Posesión en
    # públicos; SINIC se expresa directamente como Ocupación -> predio Público.
    _, dataset, helper = _dataset_y_helper(layer_dict, layer_dic)
    if not dataset.has_table("ARB_DerechoInteresadoFuente") or not dataset.has_table("ARB_Predio"):
        return _resultado_omitido("68", "Regla SINIC 68 omitida: faltan ARB_DerechoInteresadoFuente o ARB_Predio.")
    publicos = {
        "Predio.Publico.Baldio.Baldio",
        "Predio.Publico.Baldio.Reserva_Indigena",
        "Predio.Publico.Fiscal_Patrimonial",
        "Predio.Publico.Uso_Publico",
        "Predio.Publico.Presunto_Baldio",
    }
    issues = []
    predios_by_id = arb_jur._indexar_predios_por_identificador(helper)
    for table_name, row in helper.iter_derecho_interesado_fuente():
        tipo_derecho = arb_jur._derecho_tipo_ilicode(helper.get_field_value(row, arb_jur.TIPO_DERECHO_FIELDS))
        if tipo_derecho != "Ocupacion":
            continue
        predio_ref, predio_row = arb_jur._buscar_predio_relacionado(helper, row, predios_by_id)
        if not predio_row:
            continue
        tipo_predio = _tipo_predio(helper, predio_row)
        if tipo_predio not in publicos:
            issues.append(helper.make_issue(
                row,
                rule_id="68",
                message="Un derecho de tipo Ocupacion debe estar asociado a un predio Público: Baldío, Fiscal Patrimonial, Uso Público o Presunto Baldío.",
                details={"tabla": table_name, "tipo_derecho": tipo_derecho, "tipo_predio": tipo_predio, "predio_ref": predio_ref},
            ))
    return _resultado_issues("68", issues, dataset, "Parcial", "2.4; 2.5")

def regla_69(layer_dict=None, layer_dic=None, **kwargs):
    """Derechos en predios (excepto Matrices) deben tener asociado al menos un interesado o agrupación."""
    # Equivalencia del cruce: Parcial | ARBIMAPS: 2.29
    # Ajuste SINIC: 2.29 valida el predio completo; aquí el control se hace sobre
    # cada registro de derecho y se exceptúan únicamente los predios Matriz.
    _, dataset, helper = _dataset_y_helper(layer_dict, layer_dic)
    if not dataset.has_table("ARB_DerechoInteresadoFuente") or not dataset.has_table("ARB_Predio"):
        return _resultado_omitido("69", "Regla SINIC 69 omitida: faltan ARB_DerechoInteresadoFuente o ARB_Predio.")
    issues = []
    predios_by_id = arb_jur._indexar_predios_por_identificador(helper)
    for table_name, row in helper.iter_derecho_interesado_fuente():
        tipo_derecho = arb_jur._derecho_tipo_ilicode(helper.get_field_value(row, arb_jur.TIPO_DERECHO_FIELDS))
        if not tipo_derecho:
            continue
        predio_ref, predio_row = arb_jur._buscar_predio_relacionado(helper, row, predios_by_id)
        if not predio_row or _predio_es_matriz(helper, predio_row):
            continue
        if not _tiene_interesado_o_agrupacion(helper, row):
            issues.append(helper.make_issue(
                row,
                rule_id="69",
                message="Todo derecho de un predio que no sea Matriz debe tener asociado al menos un interesado o una agrupación de interesados.",
                details={"tabla": table_name, "tipo_derecho": tipo_derecho, "predio_ref": predio_ref, "condicion_predio": _condicion_predio(helper, predio_row)},
            ))
    return _resultado_issues("69", issues, dataset, "Parcial", "2.29")

def regla_70(layer_dict=None, layer_dic=None, **kwargs):
    """Todo interesado debe tener un Tipo definido (no vacío ni nulo)."""
    # Equivalencia Exacta con ARBIMAPS: 11.48
    return ejecutar_regla_exacta("70", _capas(layer_dict, layer_dic))

def regla_71(layer_dict=None, layer_dic=None, **kwargs):
    """Interesados Persona Natural no deben tener Tipo de Documento NIT."""
    # Equivalencia Exacta con ARBIMAPS: 2.14
    return ejecutar_regla_exacta("71", _capas(layer_dict, layer_dic))

def regla_72(layer_dict=None, layer_dic=None, **kwargs):
    """Interesados Persona Jurídica deben tener Tipo de Documento NIT."""
    # Equivalencia del cruce: Parcial | ARBIMAPS: 2.13
    # Ajuste SINIC: a diferencia de 2.13, aquí NO se admite Secuencial.
    _, dataset, helper = _dataset_y_helper(layer_dict, layer_dic)
    if not dataset.has_table("ARB_DerechoInteresadoFuente"):
        return _resultado_omitido("72", "Regla SINIC 72 omitida: no se encontró ARB_DerechoInteresadoFuente.")
    issues = []
    for table_name, row in helper.iter_derecho_interesado_fuente():
        tipo = arb_jur._tipo_interesado_ilicode(helper.get_field_value(row, arb_jur.TIPO_INTERESADO_FIELDS))
        if tipo != "Persona_Juridica":
            continue
        tipo_documento = _tipo_documento(helper, row)
        if tipo_documento != "NIT":
            issues.append(helper.make_issue(
                row,
                rule_id="72",
                message="Un interesado Persona_Juridica debe tener Tipo de Documento NIT.",
                details={"tabla": table_name, "tipo_interesado": tipo, "tipo_documento": tipo_documento},
            ))
    return _resultado_issues("72", issues, dataset, "Parcial", "2.13")

def regla_73(layer_dict=None, layer_dic=None, **kwargs):
    """Persona Natural exige existencia de Primer Nombre y Primer Apellido."""
    # Equivalencia del cruce: Parcial | ARBIMAPS: 2.17
    # Ajuste SINIC: 2.17 valida uso y contenido alfabético; SINIC exige de forma
    # explícita que Primer Nombre y Primer Apellido existan.
    _, dataset, helper = _dataset_y_helper(layer_dict, layer_dic)
    if not dataset.has_table("ARB_DerechoInteresadoFuente"):
        return _resultado_omitido("73", "Regla SINIC 73 omitida: no se encontró ARB_DerechoInteresadoFuente.")
    issues = []
    for table_name, row in helper.iter_derecho_interesado_fuente():
        tipo = arb_jur._tipo_interesado_ilicode(helper.get_field_value(row, arb_jur.TIPO_INTERESADO_FIELDS))
        if tipo != "Persona_Natural":
            continue
        primer_nombre = helper.get_field_value(row, arb_jur.PRIMER_NOMBRE_FIELDS)
        primer_apellido = helper.get_field_value(row, arb_jur.PRIMER_APELLIDO_FIELDS)
        faltantes = []
        if not arb_jur._is_not_empty(primer_nombre):
            faltantes.append("Primer Nombre")
        if not arb_jur._is_not_empty(primer_apellido):
            faltantes.append("Primer Apellido")
        if faltantes:
            issues.append(helper.make_issue(
                row,
                rule_id="73",
                message="Persona_Natural exige " + " y ".join(faltantes) + ".",
                details={"tabla": table_name, "tipo_interesado": tipo, "primer_nombre": primer_nombre, "primer_apellido": primer_apellido, "faltantes": faltantes},
            ))
    return _resultado_issues("73", issues, dataset, "Parcial", "2.17")

def regla_74(layer_dict=None, layer_dic=None, **kwargs):
    """Persona Jurídica exige existencia de Razón Social."""
    # Equivalencia Exacta con ARBIMAPS: 2.20
    return ejecutar_regla_exacta("74", _capas(layer_dict, layer_dic))

def regla_75(layer_dict=None, layer_dic=None, **kwargs):
    """Persona Jurídica debe tener Sexo igual a 'No Aplica'."""
    # Equivalencia del cruce: Relacionada, no equivalente | ARBIMAPS: 2.21
    # Ajuste SINIC: 2.21 solo restringe el uso del campo Sexo a personas naturales;
    # SINIC exige expresamente el valor No Aplica para Persona Jurídica.
    _, dataset, helper = _dataset_y_helper(layer_dict, layer_dic)
    if not dataset.has_table("ARB_DerechoInteresadoFuente"):
        return _resultado_omitido("75", "Regla SINIC 75 omitida: no se encontró ARB_DerechoInteresadoFuente.")
    issues = []
    for table_name, row in helper.iter_derecho_interesado_fuente():
        tipo = arb_jur._tipo_interesado_ilicode(helper.get_field_value(row, arb_jur.TIPO_INTERESADO_FIELDS))
        if tipo != "Persona_Juridica":
            continue
        sexo = _sexo_sinic(helper, row)
        if sexo != "No_Aplica":
            issues.append(helper.make_issue(
                row,
                rule_id="75",
                message="Para Persona_Juridica, el atributo Sexo debe ser No Aplica.",
                details={"tabla": table_name, "tipo_interesado": tipo, "sexo": sexo},
            ))
    return _resultado_issues("75", issues, dataset, "Relacionada, no equivalente", "2.21")

def regla_76(layer_dict=None, layer_dic=None, **kwargs):
    """Persona Natural debe tener Sexo Masculino, Femenino, No Binario o Sin Determinar."""
    # Equivalencia del cruce: Relacionada, no equivalente | ARBIMAPS: 2.21
    # Ajuste SINIC: se valida explícitamente el catálogo permitido por SINIC.
    _, dataset, helper = _dataset_y_helper(layer_dict, layer_dic)
    if not dataset.has_table("ARB_DerechoInteresadoFuente"):
        return _resultado_omitido("76", "Regla SINIC 76 omitida: no se encontró ARB_DerechoInteresadoFuente.")
    validos = {"Masculino", "Femenino", "No_Binario", "Sin_Determinar"}
    issues = []
    for table_name, row in helper.iter_derecho_interesado_fuente():
        tipo = arb_jur._tipo_interesado_ilicode(helper.get_field_value(row, arb_jur.TIPO_INTERESADO_FIELDS))
        if tipo != "Persona_Natural":
            continue
        sexo = _sexo_sinic(helper, row)
        if sexo not in validos:
            issues.append(helper.make_issue(
                row,
                rule_id="76",
                message="Para Persona_Natural, Sexo debe ser Masculino, Femenino, No Binario o Sin Determinar.",
                details={"tabla": table_name, "tipo_interesado": tipo, "sexo": sexo, "valores_permitidos": sorted(validos)},
            ))
    return _resultado_issues("76", issues, dataset, "Relacionada, no equivalente", "2.21")

def regla_77(layer_dict=None, layer_dic=None, **kwargs):
    """Todo predio activo debe tener asociada al menos una fuente administrativa."""
    # Equivalencia del cruce: Parcial | ARBIMAPS: 2.12
    # Ajuste SINIC: 2.12 condiciona la fuente a la existencia de FMI; SINIC la
    # exige para TODO predio activo, incluso si no tiene matrícula.
    _, dataset, helper = _dataset_y_helper(layer_dict, layer_dic)
    if not dataset.has_table("ARB_Predio") or not dataset.has_table("ARB_DerechoInteresadoFuente"):
        return _resultado_omitido("77", "Regla SINIC 77 omitida: faltan ARB_Predio o ARB_DerechoInteresadoFuente.")
    _, relaciones = _relaciones_por_predio(helper)
    issues = []
    for table_name, predio in helper.iter_predios():
        if not _predio_activo(helper, predio):
            continue
        rows = _relaciones_de_predio(helper, predio, relaciones)
        if any(_fuente_presente(helper, row) for _, row in rows):
            continue
        issues.append(helper.make_issue(
            predio,
            rule_id="77",
            message="Todo predio activo debe tener asociada al menos una Fuente Administrativa.",
            details={"tabla": table_name, "estado_predio": helper.get_field_value(predio, ESTADO_PREDIO_FIELDS), "numero_predial": helper.get_field_value(predio, arb_jur.NUMERO_PREDIAL_FIELDS)},
        ))
    return _resultado_issues("77", issues, dataset, "Parcial", "2.12")

def regla_78(layer_dict=None, layer_dic=None, **kwargs):
    """Predios con trámite asociado deben tener fuente diferente a 'Sin Documento'."""
    # Sin correspondencia directa: implementación nativa SINIC.
    capas, dataset, helper = _dataset_y_helper(layer_dict, layer_dic)
    if not dataset.has_table("ARB_Predio") or not dataset.has_table("ARB_DerechoInteresadoFuente"):
        return _resultado_omitido("78", "Regla SINIC 78 omitida: faltan ARB_Predio o ARB_DerechoInteresadoFuente.")
    asociados, tramite_layers, relation_layers = _predios_con_tramite(capas)
    if not tramite_layers and not relation_layers and not asociados:
        return _resultado_omitido("78", "Regla SINIC 78 omitida: no se encontró información de Trámite asociable a predios.")
    _, relaciones = _relaciones_por_predio(helper)
    issues = []
    for table_name, predio in helper.iter_predios():
        if not _predio_ids(helper, predio).intersection(asociados):
            continue
        rows = _relaciones_de_predio(helper, predio, relaciones)
        fuentes = [_tipo_fuente(helper, row) for _, row in rows if _fuente_presente(helper, row)]
        fuentes = [x for x in fuentes if x]
        if any(x != "Sin_Documento" for x in fuentes):
            continue
        motivo = "Sin Documento" if "Sin_Documento" in fuentes else "sin fuente documental válida"
        issues.append(helper.make_issue(
            predio, rule_id="78",
            message="Todo predio con trámite asociado debe tener una Fuente Administrativa diferente a 'Sin Documento'.",
            details={"tabla": table_name, "numero_predial": helper.get_field_value(predio, arb_jur.NUMERO_PREDIAL_FIELDS),
                     "fuentes_encontradas": fuentes, "motivo": motivo,
                     "capas_tramite_revisadas": [_layer_name(x) for x in tramite_layers],
                     "capas_relacion_revisadas": [_layer_name(x) for x in relation_layers]},
        ))
    return _resultado_issues("78", issues, dataset, "Sin correspondencia directa", "—")

def regla_79(layer_dict=None, layer_dic=None, **kwargs):
    """Fuentes distintas a privado/sin documento deben diligenciar Ente Emisor, Oficina, Ciudad y Fecha."""
    # Equivalencia del cruce: Parcial | ARBIMAPS: 2.27; 2.28
    # Ajuste SINIC: se conserva la lectura del tipo de fuente, pero el criterio se
    # ajusta literalmente a los cuatro campos obligatorios definidos por SINIC.
    _, dataset, helper = _dataset_y_helper(layer_dict, layer_dic)
    if not dataset.has_table("ARB_DerechoInteresadoFuente"):
        return _resultado_omitido("79", "Regla SINIC 79 omitida: no se encontró ARB_DerechoInteresadoFuente.")
    issues = []
    excluidas = {"Sin_Documento", "Documento_Fuente.Documento_Privado"}
    for table_name, row in helper.iter_derecho_interesado_fuente():
        tipo_fuente = _tipo_fuente(helper, row)
        if not tipo_fuente or tipo_fuente in excluidas:
            continue
        ente = helper.get_field_value(row, arb_jur.ENTE_EMISOR_FIELDS)
        oficina = helper.get_field_value(row, OFICINA_FIELDS)
        ciudad = helper.get_field_value(row, CIUDAD_FIELDS)
        fecha = helper.get_field_value(row, arb_jur.FECHA_FUENTE_FIELDS)
        faltantes = []
        if not arb_jur._is_not_empty(ente): faltantes.append("Ente Emisor")
        if not arb_jur._is_not_empty(oficina): faltantes.append("Oficina")
        if not arb_jur._is_not_empty(ciudad): faltantes.append("Ciudad")
        if not arb_jur._is_not_empty(fecha): faltantes.append("Fecha")
        if faltantes:
            issues.append(helper.make_issue(
                row,
                rule_id="79",
                message="La Fuente Administrativa debe diligenciar " + ", ".join(faltantes) + ".",
                details={"tabla": table_name, "tipo_fuente": tipo_fuente, "ente_emisor": ente, "oficina": oficina, "ciudad": ciudad, "fecha": fecha, "faltantes": faltantes},
            ))
    return _resultado_issues("79", issues, dataset, "Parcial", "2.27; 2.28")

def regla_88(layer_dict=None, layer_dic=None, **kwargs):
    """Predio Privado con derecho Dominio exige Matrícula Inmobiliaria mayor a 0."""
    # Equivalencia Exacta con ARBIMAPS: 2.2
    return ejecutar_regla_exacta("88", _capas(layer_dict, layer_dic))

def regla_89(layer_dict=None, layer_dic=None, **kwargs):
    """Predio Baldío con derecho Dominio exige estar ubicado en zona rural."""
    # Sin correspondencia directa: implementación nativa SINIC.
    _, dataset, helper = _dataset_y_helper(layer_dict, layer_dic)
    if not dataset.has_table("ARB_Predio") or not dataset.has_table("ARB_DerechoInteresadoFuente"):
        return _resultado_omitido("89", "Regla SINIC 89 omitida: faltan ARB_Predio o ARB_DerechoInteresadoFuente.")
    tipos_baldio = {"Predio.Publico.Baldio.Baldio", "Predio.Publico.Baldio.Reserva_Indigena"}
    _, relaciones = _relaciones_por_predio(helper)
    issues = []
    for table_name, predio in helper.iter_predios():
        if _tipo_predio(helper, predio) not in tipos_baldio:
            continue
        derechos = set(_derechos_tipos(helper, _relaciones_de_predio(helper, predio, relaciones)))
        if "Dominio" not in derechos:
            continue
        npn = str(helper.get_field_value(predio, arb_jur.NUMERO_PREDIAL_FIELDS) or "").strip()
        if arb_jur._numero_predial_es_rural(npn):
            continue
        issues.append(helper.make_issue(
            predio, rule_id="89",
            message="Un predio Baldío con derecho Dominio debe estar ubicado en zona rural.",
            details={"tabla": table_name, "tipo_predio": _tipo_predio(helper, predio), "derechos": sorted(derechos),
                     "numero_predial": npn, "posiciones_6_7": npn[5:7] if len(npn) >= 7 else "", "valor_rural_esperado": "00"},
        ))
    return _resultado_issues("89", issues, dataset, "Sin correspondencia directa", "—")

def regla_90(layer_dict=None, layer_dic=None, **kwargs):
    """Predio Baldío con derecho Dominio exige Matrícula Inmobiliaria mayor a 0."""
    # Sin correspondencia directa: implementación nativa SINIC.
    _, dataset, helper = _dataset_y_helper(layer_dict, layer_dic)
    if not dataset.has_table("ARB_Predio") or not dataset.has_table("ARB_DerechoInteresadoFuente"):
        return _resultado_omitido("90", "Regla SINIC 90 omitida: faltan ARB_Predio o ARB_DerechoInteresadoFuente.")
    tipos_baldio = {"Predio.Publico.Baldio.Baldio", "Predio.Publico.Baldio.Reserva_Indigena"}
    _, relaciones = _relaciones_por_predio(helper)
    issues = []
    for table_name, predio in helper.iter_predios():
        if _tipo_predio(helper, predio) not in tipos_baldio:
            continue
        derechos = set(_derechos_tipos(helper, _relaciones_de_predio(helper, predio, relaciones)))
        if "Dominio" not in derechos:
            continue
        matricula = helper.get_field_value(predio, arb_jur.MATRICULA_INMOBILIARIA_FIELDS)
        if not arb_jur._matricula_es_vacia_o_cero(matricula):
            continue
        issues.append(helper.make_issue(
            predio, rule_id="90",
            message="Un predio Baldío con derecho Dominio debe tener Matrícula Inmobiliaria mayor a 0.",
            details={"tabla": table_name, "tipo_predio": _tipo_predio(helper, predio), "derechos": sorted(derechos),
                     "matricula_inmobiliaria": matricula, "numero_predial": helper.get_field_value(predio, arb_jur.NUMERO_PREDIAL_FIELDS)},
        ))
    return _resultado_issues("90", issues, dataset, "Sin correspondencia directa", "—")

def regla_91(layer_dict=None, layer_dic=None, **kwargs):
    """Predio Baldío con derecho Dominio exige tener un único interesado relacionado."""
    # Equivalencia del cruce: Parcial | ARBIMAPS: 2.6
    # Ajuste SINIC: 2.6 controla quién puede ser el interesado en Baldío+Dominio;
    # SINIC controla la cardinalidad: debe existir exactamente un interesado único.
    _, dataset, helper = _dataset_y_helper(layer_dict, layer_dic)
    if not dataset.has_table("ARB_Predio") or not dataset.has_table("ARB_DerechoInteresadoFuente"):
        return _resultado_omitido("91", "Regla SINIC 91 omitida: faltan ARB_Predio o ARB_DerechoInteresadoFuente.")
    tipos_baldio = {"Predio.Publico.Baldio.Baldio", "Predio.Publico.Baldio.Reserva_Indigena", "Predio.Publico.Presunto_Baldio"}
    _, relaciones = _relaciones_por_predio(helper)
    issues = []
    for table_name, predio in helper.iter_predios():
        if _tipo_predio(helper, predio) not in tipos_baldio:
            continue
        rows = [row for _, row in _relaciones_de_predio(helper, predio, relaciones)
                if arb_jur._derecho_tipo_ilicode(helper.get_field_value(row, arb_jur.TIPO_DERECHO_FIELDS)) == "Dominio"]
        if not rows:
            continue
        interesados = {firma for row in rows if (firma := _firma_interesado(helper, row))}
        if len(interesados) != 1:
            issues.append(helper.make_issue(
                predio,
                rule_id="91",
                message="Un predio Baldío con derecho Dominio debe tener un único interesado relacionado.",
                details={"tabla": table_name, "tipo_predio": _tipo_predio(helper, predio), "cantidad_interesados": len(interesados), "interesados": sorted(interesados), "numero_predial": helper.get_field_value(predio, arb_jur.NUMERO_PREDIAL_FIELDS)},
            ))
    return _resultado_issues("91", issues, dataset, "Parcial", "2.6")

def regla_92(layer_dict=None, layer_dic=None, **kwargs):
    """Predio informal superpuesto con Baldío exige derecho de Ocupación."""
    # Equivalencia del cruce: Relacionada, no equivalente | ARBIMAPS: 5.20
    # Ajuste SINIC: se evalúa directamente la superposición de los terrenos y,
    # cuando el predio informal se cruza con un Baldío, se exige Ocupación.
    capas, dataset, helper = _dataset_y_helper(layer_dict, layer_dic)
    tipos_baldio = {"Predio.Publico.Baldio.Baldio", "Predio.Publico.Baldio.Reserva_Indigena", "Predio.Publico.Presunto_Baldio"}
    predio_layer, pairs = _superposiciones_informal(capas, tipos_baldio)
    if predio_layer is None:
        return _resultado_omitido("92", "Regla SINIC 92 omitida: no se encontraron ARB_Predio y ARB_Terreno para evaluar superposición.")
    derechos_index = _derechos_por_identificador(helper)
    errores = []
    for informal, baldio in pairs:
        if "Ocupacion" in _derechos_de_info(informal, derechos_index):
            continue
        errores.append(_error_feature(
            "92", predio_layer, informal["feature"],
            "Un predio Informal superpuesto con un predio Baldío debe tener derecho de Ocupacion.",
            {"numero_predial_informal": informal.get("npn"), "numero_predial_baldio": baldio.get("npn"), "tipo_predio_baldio": baldio.get("tipo")},
        ))
    return _resultado_errores("92", errores, "Relacionada, no equivalente", "5.20")

def regla_93(layer_dict=None, layer_dic=None, **kwargs):
    """Predio informal con Ocupación superpuesto con Baldío exige estar en zona rural."""
    # Sin correspondencia directa: implementación nativa SINIC.
    capas, dataset, helper = _dataset_y_helper(layer_dict, layer_dic)
    tipos_baldio = {"Predio.Publico.Baldio.Baldio", "Predio.Publico.Baldio.Reserva_Indigena", "Predio.Publico.Presunto_Baldio"}
    predio_layer, pairs = _superposiciones_informal(capas, tipos_baldio)
    if predio_layer is None:
        return _resultado_omitido("93", "Regla SINIC 93 omitida: no se encontraron ARB_Predio y ARB_Terreno para evaluar superposición.")
    derechos_index = _derechos_por_identificador(helper)
    errores = []
    for informal, baldio in pairs:
        if "Ocupacion" not in _derechos_de_info(informal, derechos_index):
            continue
        npn = str(informal.get("npn") or "").strip()
        if arb_jur._numero_predial_es_rural(npn):
            continue
        errores.append(_error_feature(
            "93", predio_layer, informal["feature"],
            "Un predio Informal con derecho de Ocupación superpuesto con un Baldío debe estar ubicado en zona rural.",
            {"numero_predial_informal": npn, "numero_predial_baldio": baldio.get("npn"),
             "posiciones_6_7": npn[5:7] if len(npn) >= 7 else "", "valor_rural_esperado": "00"},
        ))
    return _resultado_errores("93", errores, "Sin correspondencia directa", "—")

def regla_94(layer_dict=None, layer_dic=None, **kwargs):
    """Predio informal con Ocupación superpuesto con Baldío exige no tener FMI."""
    # Se implementa espacialmente. Reutilizar 2.2 por texto producía falsos
    # positivos porque "Privado no informal" contiene la subcadena "informal"
    # y, además, 2.2 por sí sola no demuestra la superposición con Baldío.
    capas, dataset, helper = _dataset_y_helper(layer_dict, layer_dic)
    tipos_baldio={"Predio.Publico.Baldio.Baldio","Predio.Publico.Baldio.Reserva_Indigena","Predio.Publico.Presunto_Baldio"}
    predio_layer,pairs=_superposiciones_informal(capas,tipos_baldio)
    if predio_layer is None:
        return _resultado_omitido("94","Regla SINIC 94 no verificable: no se encontraron ARB_Predio y ARB_Terreno para evaluar superposición.")
    derechos_index=_derechos_por_identificador(helper); errores=[]
    for informal,baldio in pairs:
        if "Ocupacion" not in _derechos_de_info(informal,derechos_index):
            continue
        fmi=_feature_value(informal["feature"],predio_layer,arb_jur.MATRICULA_INMOBILIARIA_FIELDS)
        if arb_jur._matricula_es_vacia_o_cero(fmi):
            continue
        errores.append(_error_feature(
            "94",predio_layer,informal["feature"],
            "Un predio Informal con derecho de Ocupación superpuesto con un Baldío no debe tener Matrícula Inmobiliaria.",
            {"numero_predial_informal":informal.get("npn"),"numero_predial_baldio":baldio.get("npn"),"matricula_inmobiliaria":fmi,"tipo_predio_baldio":baldio.get("tipo")},
        ))
    return _resultado_errores("94",errores,"Exacta ajustada a condición SINIC","2.2 + superposición espacial")

def regla_95(layer_dict=None, layer_dic=None, **kwargs):
    """Predio Fiscal Patrimonial no informal exige derecho de Dominio."""
    # Equivalencia del cruce: Relacionada, no equivalente | ARBIMAPS: 2.5
    # Ajuste SINIC: 2.5 solo impide Posesión en públicos; aquí se exige de forma
    # positiva el derecho Dominio cuando Fiscal Patrimonial NO es Informal.
    _, dataset, helper = _dataset_y_helper(layer_dict, layer_dic)
    if not dataset.has_table("ARB_Predio") or not dataset.has_table("ARB_DerechoInteresadoFuente"):
        return _resultado_omitido("95", "Regla SINIC 95 omitida: faltan ARB_Predio o ARB_DerechoInteresadoFuente.")
    _, relaciones = _relaciones_por_predio(helper)
    issues = []
    for table_name, predio in helper.iter_predios():
        if _tipo_predio(helper, predio) != "Predio.Publico.Fiscal_Patrimonial":
            continue
        if _norm_token(_condicion_predio(helper, predio)) == "INFORMAL":
            continue
        tipos = set(_derechos_tipos(helper, _relaciones_de_predio(helper, predio, relaciones)))
        if "Dominio" not in tipos:
            issues.append(helper.make_issue(
                predio,
                rule_id="95",
                message="Un predio Fiscal Patrimonial no informal debe tener derecho de Dominio.",
                details={"tabla": table_name, "tipo_predio": _tipo_predio(helper, predio), "condicion_predio": _condicion_predio(helper, predio), "derechos": sorted(tipos), "numero_predial": helper.get_field_value(predio, arb_jur.NUMERO_PREDIAL_FIELDS)},
            ))
    return _resultado_issues("95", issues, dataset, "Relacionada, no equivalente", "2.5")

def regla_96(layer_dict=None, layer_dic=None, **kwargs):
    """Predio Fiscal Patrimonial con Dominio exige Matrícula Inmobiliaria mayor a 0."""
    # Sin correspondencia directa: implementación nativa SINIC.
    _, dataset, helper = _dataset_y_helper(layer_dict, layer_dic)
    if not dataset.has_table("ARB_Predio") or not dataset.has_table("ARB_DerechoInteresadoFuente"):
        return _resultado_omitido("96", "Regla SINIC 96 omitida: faltan ARB_Predio o ARB_DerechoInteresadoFuente.")
    _, relaciones = _relaciones_por_predio(helper)
    issues = []
    for table_name, predio in helper.iter_predios():
        if _tipo_predio(helper, predio) != "Predio.Publico.Fiscal_Patrimonial":
            continue
        derechos = set(_derechos_tipos(helper, _relaciones_de_predio(helper, predio, relaciones)))
        if "Dominio" not in derechos:
            continue
        matricula = helper.get_field_value(predio, arb_jur.MATRICULA_INMOBILIARIA_FIELDS)
        if not arb_jur._matricula_es_vacia_o_cero(matricula):
            continue
        issues.append(helper.make_issue(
            predio, rule_id="96",
            message="Un predio Fiscal Patrimonial con derecho Dominio debe tener Matrícula Inmobiliaria mayor a 0.",
            details={"tabla": table_name, "tipo_predio": _tipo_predio(helper, predio), "derechos": sorted(derechos),
                     "matricula_inmobiliaria": matricula, "numero_predial": helper.get_field_value(predio, arb_jur.NUMERO_PREDIAL_FIELDS)},
        ))
    return _resultado_issues("96", issues, dataset, "Sin correspondencia directa", "—")

def regla_97(layer_dict=None, layer_dic=None, **kwargs):
    """Predio informal superpuesto con Fiscal Patrimonial exige derecho de Ocupación."""
    # Equivalencia del cruce: Relacionada, no equivalente | ARBIMAPS: 5.20
    # Ajuste SINIC: se evalúa la superposición espacial y se exige Ocupación al
    # predio informal cuando se cruza con un Fiscal Patrimonial.
    capas, dataset, helper = _dataset_y_helper(layer_dict, layer_dic)
    predio_layer, pairs = _superposiciones_informal(capas, {"Predio.Publico.Fiscal_Patrimonial"})
    if predio_layer is None:
        return _resultado_omitido("97", "Regla SINIC 97 omitida: no se encontraron ARB_Predio y ARB_Terreno para evaluar superposición.")
    derechos_index = _derechos_por_identificador(helper)
    errores = []
    for informal, fiscal in pairs:
        if "Ocupacion" in _derechos_de_info(informal, derechos_index):
            continue
        errores.append(_error_feature(
            "97", predio_layer, informal["feature"],
            "Un predio Informal superpuesto con un predio Fiscal Patrimonial debe tener derecho de Ocupacion.",
            {"numero_predial_informal": informal.get("npn"), "numero_predial_fiscal": fiscal.get("npn"), "tipo_predio_fiscal": fiscal.get("tipo")},
        ))
    return _resultado_errores("97", errores, "Relacionada, no equivalente", "5.20")

def regla_98(layer_dict=None, layer_dic=None, **kwargs):
    """Predio Uso Público no informal exige derecho de Dominio."""
    # Equivalencia Exacta con ARBIMAPS: 2.10
    return ejecutar_regla_exacta("98", _capas(layer_dict, layer_dic))

def regla_99(layer_dict=None, layer_dic=None, **kwargs):
    """Predio con NPN pos 22='3' u '4' exige tipo Uso Público y derecho Dominio."""
    # Equivalencia del cruce: Equivalente por combinación | ARBIMAPS: 1.1; 2.10
    # Ajuste SINIC: se combinan ambas condiciones en una sola validación.
    _, dataset, helper = _dataset_y_helper(layer_dict, layer_dic)
    if not dataset.has_table("ARB_Predio") or not dataset.has_table("ARB_DerechoInteresadoFuente"):
        return _resultado_omitido("99", "Regla SINIC 99 omitida: faltan ARB_Predio o ARB_DerechoInteresadoFuente.")
    _, relaciones = _relaciones_por_predio(helper)
    issues = []
    for table_name, predio in helper.iter_predios():
        npn = str(helper.get_field_value(predio, arb_jur.NUMERO_PREDIAL_FIELDS) or "").strip()
        if len(npn) < 22 or npn[21] not in {"3", "4"}:
            continue
        tipo_predio = _tipo_predio(helper, predio)
        tipos_derecho = set(_derechos_tipos(helper, _relaciones_de_predio(helper, predio, relaciones)))
        faltantes = []
        if tipo_predio != "Predio.Publico.Uso_Publico":
            faltantes.append("Tipo de predio Uso Público")
        if "Dominio" not in tipos_derecho:
            faltantes.append("derecho Dominio")
        if faltantes:
            issues.append(helper.make_issue(
                predio,
                rule_id="99",
                message="Los predios cuyo NPN tiene 3 o 4 en la posición 22 deben ser de tipo Uso Público y tener derecho Dominio.",
                details={"tabla": table_name, "numero_predial": npn, "posicion_22": npn[21], "tipo_predio": tipo_predio, "derechos": sorted(tipos_derecho), "faltantes": faltantes},
            ))
    return _resultado_issues("99", issues, dataset, "Equivalente por combinación", "1.1; 2.10")

def regla_100(layer_dict=None, layer_dic=None, **kwargs):
    """Predio informal de Uso Público exige derecho de Ocupación."""
    # Equivalencia del cruce: Parcial | ARBIMAPS: 2.5
    # Ajuste SINIC: 2.5 impide Posesión en públicos; SINIC exige expresamente
    # Ocupación cuando el Uso Público tiene condición Informal.
    _, dataset, helper = _dataset_y_helper(layer_dict, layer_dic)
    if not dataset.has_table("ARB_Predio") or not dataset.has_table("ARB_DerechoInteresadoFuente"):
        return _resultado_omitido("100", "Regla SINIC 100 omitida: faltan ARB_Predio o ARB_DerechoInteresadoFuente.")
    _, relaciones = _relaciones_por_predio(helper)
    issues = []
    for table_name, predio in helper.iter_predios():
        if _tipo_predio(helper, predio) != "Predio.Publico.Uso_Publico":
            continue
        if _norm_token(_condicion_predio(helper, predio)) != "INFORMAL":
            continue
        tipos = set(_derechos_tipos(helper, _relaciones_de_predio(helper, predio, relaciones)))
        if "Ocupacion" not in tipos:
            issues.append(helper.make_issue(
                predio,
                rule_id="100",
                message="Un predio Informal de tipo Uso Público debe tener derecho de Ocupacion.",
                details={"tabla": table_name, "tipo_predio": _tipo_predio(helper, predio), "condicion_predio": _condicion_predio(helper, predio), "derechos": sorted(tipos), "numero_predial": helper.get_field_value(predio, arb_jur.NUMERO_PREDIAL_FIELDS)},
            ))
    return _resultado_issues("100", issues, dataset, "Parcial", "2.5")

def regla_109(layer_dict=None, layer_dic=None, **kwargs):
    """Interesados con NIT exigen documento de identidad diligenciado sin espacios ni caracteres especiales."""
    # Equivalencia Exacta con ARBIMAPS: 2.16
    return ejecutar_regla_exacta("109", _capas(layer_dict, layer_dic))

def regla_110(layer_dict=None, layer_dic=None, **kwargs):
    """Interesados Persona Jurídica no deben tener diligenciados nombres ni apellidos."""
    # Equivalencia Exacta con ARBIMAPS: 2.18; 2.20
    return ejecutar_regla_exacta("110", _capas(layer_dict, layer_dic))

def regla_111(layer_dict=None, layer_dic=None, **kwargs):
    """Documentos de identidad (CC, CE, NIT, Pasaporte, RC, TI) exigen > 5 dígitos sin espacios/caracteres especiales."""
    # Equivalencia del cruce: Parcial | ARBIMAPS: 2.15; 2.16
    # Ajuste SINIC: se aplica un único criterio a los seis tipos indicados por
    # SINIC: únicamente dígitos y longitud mayor a cinco.
    _, dataset, helper = _dataset_y_helper(layer_dict, layer_dic)
    if not dataset.has_table("ARB_DerechoInteresadoFuente"):
        return _resultado_omitido("111", "Regla SINIC 111 omitida: no se encontró ARB_DerechoInteresadoFuente.")
    tipos_objetivo = {"Cedula_Ciudadania", "Cedula_Extranjeria", "NIT", "Pasaporte", "Registro_Civil", "Tarjeta_Identidad"}
    issues = []
    for table_name, row in helper.iter_derecho_interesado_fuente():
        tipo_documento = _tipo_documento(helper, row)
        if tipo_documento not in tipos_objetivo:
            continue
        raw_documento = _raw_row_value(helper, row, arb_jur.DOCUMENTO_IDENTIDAD_FIELDS)
        documento = _raw_text(raw_documento)
        valido = bool(re.fullmatch(r"[0-9]{6,}", documento))
        if not valido:
            issues.append(helper.make_issue(
                row,
                rule_id="111",
                message="Para CC, CE, NIT, Pasaporte, RC o TI, el documento de identidad debe contener más de 5 dígitos y no puede tener espacios ni caracteres especiales.",
                details={"tabla": table_name, "tipo_documento": tipo_documento, "documento_identidad": documento},
            ))
    return _resultado_issues("111", issues, dataset, "Parcial", "2.15; 2.16")

def regla_113(layer_dict=None, layer_dic=None, **kwargs):
    """Predios no informales exigen un único derecho de tipo Dominio."""
    # Equivalencia del cruce: Relacionada, no equivalente | ARBIMAPS: 2.2; 2.10
    # Ajuste SINIC: se generaliza el criterio a TODO predio no Informal y se exige
    # que sus derechos correspondan únicamente a un derecho Dominio.
    _, dataset, helper = _dataset_y_helper(layer_dict, layer_dic)
    if not dataset.has_table("ARB_Predio") or not dataset.has_table("ARB_DerechoInteresadoFuente"):
        return _resultado_omitido("113", "Regla SINIC 113 omitida: faltan ARB_Predio o ARB_DerechoInteresadoFuente.")
    _, relaciones = _relaciones_por_predio(helper)
    issues = []
    for table_name, predio in helper.iter_predios():
        if _norm_token(_condicion_predio(helper, predio)) == "INFORMAL":
            continue
        rows = _relaciones_de_predio(helper, predio, relaciones)
        tipos = [arb_jur._derecho_tipo_ilicode(helper.get_field_value(row, arb_jur.TIPO_DERECHO_FIELDS)) for _, row in rows]
        tipos = [tipo for tipo in tipos if tipo]
        dominios = []
        otros = []
        for _, row in rows:
            tipo = arb_jur._derecho_tipo_ilicode(helper.get_field_value(row, arb_jur.TIPO_DERECHO_FIELDS))
            if not tipo:
                continue
            identidad = _derecho_identity(helper, row)
            if tipo == "Dominio":
                dominios.append(identidad or "TIPO:Dominio")
            else:
                otros.append(tipo)
        # Si el modelo expone un id propio del derecho, se respeta para la cardinalidad.
        # En estructuras aplanadas sin id de derecho, varias filas Dominio se consideran
        # el mismo derecho lógico y la validación se concentra en el tipo.
        domain_ids = {d for d in dominios if d}
        tiene_ids_reales = any(d.startswith("ID:") for d in domain_ids)
        cantidad_dominios = len(domain_ids) if tiene_ids_reales else (1 if domain_ids else 0)
        if cantidad_dominios != 1 or otros:
            issues.append(helper.make_issue(
                predio,
                rule_id="113",
                message="Todo predio no Informal debe tener un único derecho de tipo Dominio.",
                details={"tabla": table_name, "condicion_predio": _condicion_predio(helper, predio), "cantidad_derechos_dominio": cantidad_dominios, "otros_derechos": sorted(set(otros)), "numero_predial": helper.get_field_value(predio, arb_jur.NUMERO_PREDIAL_FIELDS)},
            ))
    return _resultado_issues("113", issues, dataset, "Relacionada, no equivalente", "2.2; 2.10")

def regla_117(layer_dict=None, layer_dic=None, **kwargs):
    """Agrupación de interesados Grupo Civil exige que todos los interesados sean Persona Natural."""
    # Equivalencia Exacta con ARBIMAPS 2.24, pero la función fuente suministrada es no-op.
    # Se implementa literalmente SINIC reutilizando la lógica base ARBIMAPS.
    capas, dataset, helper = _dataset_y_helper(layer_dict, layer_dic)
    grupos, tiene_catalogo = _agrupaciones_interesados(helper, capas)
    if not grupos:
        return _resultado_omitido("117", "Regla SINIC 117 omitida: no se encontraron agrupaciones relacionables con interesados.")
    issues = []
    for gid, info in grupos.items():
        if info.get("tipo_agrupacion") != "Grupo_Civil":
            continue
        tipos = set(info.get("tipos") or set())
        if tipos and tipos <= {"Persona_Natural"}:
            continue
        issues.append(helper.make_issue(
            info["row"], rule_id="117",
            message="Una agrupación Grupo_Civil debe estar conformada únicamente por interesados Persona Natural.",
            details={"tabla": info["tabla"], "agrupacion_id": gid, "tipo_agrupacion": info.get("tipo_agrupacion"),
                     "tipos_interesado_encontrados": sorted(tipos)},
        ))
    return _resultado_issues("117", issues, dataset, "Exacta", "2.24 (fallback SINIC nativo: fuente vacía)")

def regla_118(layer_dict=None, layer_dic=None, **kwargs):
    """Agrupación de interesados Grupo Empresarial exige que todos los interesados sean Persona Jurídica."""
    # Equivalencia Exacta con ARBIMAPS 2.25, pero la función fuente suministrada es no-op.
    capas, dataset, helper = _dataset_y_helper(layer_dict, layer_dic)
    grupos, tiene_catalogo = _agrupaciones_interesados(helper, capas)
    if not grupos:
        return _resultado_omitido("118", "Regla SINIC 118 omitida: no se encontraron agrupaciones relacionables con interesados.")
    issues = []
    for gid, info in grupos.items():
        if info.get("tipo_agrupacion") != "Grupo_Empresarial":
            continue
        tipos = set(info.get("tipos") or set())
        if tipos and tipos <= {"Persona_Juridica"}:
            continue
        issues.append(helper.make_issue(
            info["row"], rule_id="118",
            message="Una agrupación Grupo_Empresarial debe estar conformada únicamente por interesados Persona Jurídica.",
            details={"tabla": info["tabla"], "agrupacion_id": gid, "tipo_agrupacion": info.get("tipo_agrupacion"),
                     "tipos_interesado_encontrados": sorted(tipos)},
        ))
    return _resultado_issues("118", issues, dataset, "Exacta", "2.25 (fallback SINIC nativo: fuente vacía)")

def regla_119(layer_dict=None, layer_dic=None, **kwargs):
    """Agrupación con Personas Naturales y Jurídicas simultáneamente exige tipo Grupo_Mixto."""
    # Equivalencia Exacta con ARBIMAPS 2.23, pero la función fuente suministrada es no-op.
    capas, dataset, helper = _dataset_y_helper(layer_dict, layer_dic)
    grupos, tiene_catalogo = _agrupaciones_interesados(helper, capas)
    if not grupos:
        return _resultado_omitido("119", "Regla SINIC 119 omitida: no se encontraron agrupaciones relacionables con interesados.")
    issues = []
    for gid, info in grupos.items():
        tipos = set(info.get("tipos") or set())
        if not {"Persona_Natural", "Persona_Juridica"}.issubset(tipos):
            continue
        if info.get("tipo_agrupacion") == "Grupo_Mixto":
            continue
        issues.append(helper.make_issue(
            info["row"], rule_id="119",
            message="Una agrupación que contiene simultáneamente Personas Naturales y Jurídicas debe ser de tipo Grupo_Mixto.",
            details={"tabla": info["tabla"], "agrupacion_id": gid, "tipo_agrupacion": info.get("tipo_agrupacion"),
                     "tipos_interesado_encontrados": sorted(tipos)},
        ))
    return _resultado_issues("119", issues, dataset, "Exacta", "2.23 (fallback SINIC nativo: fuente vacía)")

def regla_120(layer_dict=None, layer_dic=None, **kwargs):
    """Matrícula > 0 exige Fuente Administrativa asociada con fecha, tipo y ente emisor."""
    # Equivalencia Exacta con ARBIMAPS: 2.12
    return ejecutar_regla_exacta("120", _capas(layer_dict, layer_dic))

def regla_121(layer_dict=None, layer_dic=None, **kwargs):
    """Predio Matriz con un único interesado exige que sea Persona Jurídica."""
    # Sin correspondencia directa: implementación nativa SINIC.
    _, dataset, helper = _dataset_y_helper(layer_dict, layer_dic)
    if not dataset.has_table("ARB_Predio") or not dataset.has_table("ARB_DerechoInteresadoFuente"):
        return _resultado_omitido("121", "Regla SINIC 121 omitida: faltan ARB_Predio o ARB_DerechoInteresadoFuente.")
    _, relaciones = _relaciones_por_predio(helper)
    issues = []
    for table_name, predio in helper.iter_predios():
        if not _predio_es_matriz(helper, predio):
            continue
        rows = _relaciones_de_predio(helper, predio, relaciones)
        interesados = {}
        for _, row in rows:
            firma = _firma_interesado(helper, row)
            if not firma:
                continue
            tipo = arb_jur._tipo_interesado_ilicode(helper.get_field_value(row, arb_jur.TIPO_INTERESADO_FIELDS))
            interesados.setdefault(firma, set())
            if tipo:
                interesados[firma].add(tipo)
        if len(interesados) != 1:
            continue
        firma, tipos = next(iter(interesados.items()))
        if tipos == {"Persona_Juridica"}:
            continue
        issues.append(helper.make_issue(
            predio, rule_id="121",
            message="Cuando un predio Matriz tiene un único interesado, este debe ser Persona Jurídica.",
            details={"tabla": table_name, "condicion_predio": _condicion_predio(helper, predio), "interesado": firma,
                     "tipos_interesado": sorted(tipos), "numero_predial": helper.get_field_value(predio, arb_jur.NUMERO_PREDIAL_FIELDS)},
        ))
    return _resultado_issues("121", issues, dataset, "Sin correspondencia directa", "—")

def regla_122(layer_dict=None, layer_dic=None, **kwargs):
    """Fuente Documento_Publico exige Ente Emisor, Oficina, Ciudad y Fecha diligenciados."""
    # Equivalencia del cruce: Parcial | ARBIMAPS: 2.27; 2.28
    # Ajuste SINIC: para Documento_Publico se exigen explícitamente los cuatro
    # campos definidos por SINIC, sin sustituirlos por el catálogo de 2.27/2.28.
    _, dataset, helper = _dataset_y_helper(layer_dict, layer_dic)
    if not dataset.has_table("ARB_DerechoInteresadoFuente"):
        return _resultado_omitido("122", "Regla SINIC 122 omitida: no se encontró ARB_DerechoInteresadoFuente.")
    issues = []
    for table_name, row in helper.iter_derecho_interesado_fuente():
        raw_tipo = _raw_row_value(helper, row, arb_jur.TIPO_FUENTE_FIELDS)
        if _norm_token(raw_tipo) not in {"DOCUMENTOPUBLICO", "FUENTEDOCUMENTOPUBLICO"}:
            continue
        ente = helper.get_field_value(row, arb_jur.ENTE_EMISOR_FIELDS)
        oficina = helper.get_field_value(row, OFICINA_FIELDS)
        ciudad = helper.get_field_value(row, CIUDAD_FIELDS)
        fecha = helper.get_field_value(row, arb_jur.FECHA_FUENTE_FIELDS)
        faltantes = []
        if not arb_jur._is_not_empty(ente): faltantes.append("Ente Emisor")
        if not arb_jur._is_not_empty(oficina): faltantes.append("Oficina")
        if not arb_jur._is_not_empty(ciudad): faltantes.append("Ciudad")
        if not arb_jur._is_not_empty(fecha): faltantes.append("Fecha")
        if faltantes:
            issues.append(helper.make_issue(
                row,
                rule_id="122",
                message="Una Fuente Documento_Publico debe diligenciar Ente Emisor, Oficina, Ciudad y Fecha.",
                details={"tabla": table_name, "tipo_fuente": raw_tipo, "ente_emisor": ente, "oficina": oficina, "ciudad": ciudad, "fecha": fecha, "faltantes": faltantes},
            ))
    return _resultado_issues("122", issues, dataset, "Parcial", "2.27; 2.28")

def regla_123(layer_dict=None, layer_dic=None, **kwargs):
    """Fuente Sin Documento exige Ente Emisor, Oficina, Ciudad y Fecha NO diligenciados."""
    # Sin correspondencia directa: implementación nativa SINIC.
    _, dataset, helper = _dataset_y_helper(layer_dict, layer_dic)
    if not dataset.has_table("ARB_DerechoInteresadoFuente"):
        return _resultado_omitido("123", "Regla SINIC 123 omitida: no se encontró ARB_DerechoInteresadoFuente.")
    issues = []
    for table_name, row in helper.iter_derecho_interesado_fuente():
        tipo_fuente = _tipo_fuente(helper, row)
        if tipo_fuente != "Sin_Documento":
            continue
        ente = helper.get_field_value(row, arb_jur.ENTE_EMISOR_FIELDS)
        oficina = helper.get_field_value(row, OFICINA_FIELDS)
        ciudad = helper.get_field_value(row, CIUDAD_FIELDS)
        fecha = helper.get_field_value(row, arb_jur.FECHA_FUENTE_FIELDS)
        diligenciados = []
        if arb_jur._is_not_empty(ente): diligenciados.append("Ente Emisor")
        if arb_jur._is_not_empty(oficina): diligenciados.append("Oficina")
        if arb_jur._is_not_empty(ciudad): diligenciados.append("Ciudad")
        if arb_jur._is_not_empty(fecha): diligenciados.append("Fecha")
        if not diligenciados:
            continue
        issues.append(helper.make_issue(
            row, rule_id="123",
            message="Cuando la Fuente Administrativa es 'Sin Documento', Ente Emisor, Oficina, Ciudad y Fecha no deben estar diligenciados.",
            details={"tabla": table_name, "tipo_fuente": tipo_fuente, "ente_emisor": ente, "oficina": oficina,
                     "ciudad": ciudad, "fecha": fecha, "campos_diligenciados": diligenciados},
        ))
    return _resultado_issues("123", issues, dataset, "Sin correspondencia directa", "—")

def regla_128(layer_dict=None, layer_dic=None, **kwargs):
    """Todas las Fuentes Administrativas deben estar asociadas a un predio activo."""
    # Sin correspondencia directa: implementación nativa SINIC.
    _, dataset, helper = _dataset_y_helper(layer_dict, layer_dic)
    if not dataset.has_table("ARB_DerechoInteresadoFuente") or not dataset.has_table("ARB_Predio"):
        return _resultado_omitido("128", "Regla SINIC 128 omitida: faltan ARB_DerechoInteresadoFuente o ARB_Predio.")
    predios_by_id = arb_jur._indexar_predios_por_identificador(helper)
    issues = []
    for table_name, row in helper.iter_derecho_interesado_fuente():
        if not _fuente_presente(helper, row):
            continue
        predio_ref, predio_row = arb_jur._buscar_predio_relacionado(helper, row, predios_by_id)
        if predio_row is not None and _predio_activo(helper, predio_row):
            continue
        estado = helper.get_field_value(predio_row or {}, ESTADO_PREDIO_FIELDS) if predio_row is not None else None
        issues.append(helper.make_issue(
            row, rule_id="128",
            message="Toda Fuente Administrativa debe estar asociada a un predio activo.",
            details={"tabla": table_name, "predio_ref": predio_ref, "predio_encontrado": predio_row is not None,
                     "estado_predio": estado, "tipo_fuente": _tipo_fuente(helper, row)},
        ))
    return _resultado_issues("128", issues, dataset, "Sin correspondencia directa", "—")

def regla_144(layer_dict=None, layer_dic=None, **kwargs):
    """Agrupación de Interesados exige suma de participaciones igual a 1 (100%)."""
    # Equivalencia del cruce: Parcial | ARBIMAPS: 2.26
    # Ajuste SINIC: 2.26 permite cero/null en algunos casos; SINIC exige que toda
    # agrupación materializada sume exactamente 1 (100%).
    capas = _capas(layer_dict, layer_dic)
    grupos_layer, miembros_layer = _find_group_layers(capas)
    if miembros_layer is None:
        return _resultado_omitido("144", "Regla SINIC 144 omitida: no se encontró COL_Miembros/CR_Miembros para sumar participaciones por agrupación.")

    group_features = {}
    if grupos_layer is not None:
        for feature in _features(grupos_layer):
            group_features[_group_id_feature(feature, grupos_layer)] = feature

    valores_por_grupo = defaultdict(list)
    feature_por_grupo = {}
    for feature in _features(miembros_layer):
        gid_raw = _feature_value(feature, miembros_layer, (
            "agrupacion", "Agrupacion", "agrupacion_id", "id_agrupacion",
            "interesado_cr_agrupacioninteresados", "cr_agrupacioninteresados",
            "col_agrupacioninteresados",
        ))
        gid = _raw_text(gid_raw).strip("{}")
        if not gid:
            continue
        participacion_raw = _feature_value(feature, miembros_layer, (
            "participacion", "Participacion", "participación", "porcentaje_participacion",
            "Porcentaje_Participacion", "cuota_participacion", "Cuota_Participacion",
        ))
        valores_por_grupo[gid].append(_to_float(participacion_raw))
        feature_por_grupo.setdefault(gid, feature)

    errores = []
    for gid, valores in valores_por_grupo.items():
        if not valores or any(v is None for v in valores):
            valido = False
            total_normalizado = None
        else:
            total = sum(valores)
            # Algunos modelos almacenan 100 en vez de 1; se normaliza a fracción.
            total_normalizado = total / 100.0 if any(abs(v) > 1.0 for v in valores) else total
            valido = abs(total_normalizado - 1.0) <= 1e-6
        if valido:
            continue
        layer = grupos_layer if grupos_layer is not None and gid in group_features else miembros_layer
        feature = group_features.get(gid) if grupos_layer is not None else None
        if feature is None:
            feature = feature_por_grupo.get(gid)
        errores.append(_error_feature(
            "144", layer, feature,
            "La suma de participaciones de una Agrupación de Interesados debe ser igual a 1 (100%).",
            {"agrupacion_id": gid, "participaciones": valores, "suma_normalizada": total_normalizado},
        ))
    return _resultado_errores("144", errores, "Parcial", "2.26")

codigos_funciones = {
    "45": regla_45,
    "46": regla_46,
    "66": regla_66,
    "67": regla_67,
    "68": regla_68,
    "69": regla_69,
    "70": regla_70,
    "71": regla_71,
    "72": regla_72,
    "73": regla_73,
    "74": regla_74,
    "75": regla_75,
    "76": regla_76,
    "77": regla_77,
    "78": regla_78,
    "79": regla_79,
    "88": regla_88,
    "89": regla_89,
    "90": regla_90,
    "91": regla_91,
    "92": regla_92,
    "93": regla_93,
    "94": regla_94,
    "95": regla_95,
    "96": regla_96,
    "97": regla_97,
    "98": regla_98,
    "99": regla_99,
    "100": regla_100,
    "109": regla_109,
    "110": regla_110,
    "111": regla_111,
    "113": regla_113,
    "117": regla_117,
    "118": regla_118,
    "119": regla_119,
    "120": regla_120,
    "121": regla_121,
    "122": regla_122,
    "123": regla_123,
    "128": regla_128,
    "144": regla_144,
}

reglas_implementadas = dict(codigos_funciones)

reglas_exactas_pendientes_fuente = []
reglas_pendientes_logica = []
todas_las_reglas = ['46', '66', '67', '68', '69', '70', '71', '72', '73', '74', '75', '76', '77', '78', '79', '88', '89', '90', '91', '92', '93', '94', '95', '96', '97', '98', '99', '100', '110', '113', '117', '118', '119', '120', '121', '122', '123', '128', '144']

clases_con_reglas = {'Juridico': list(codigos_funciones.keys())}
RULE_FUNCTIONS = codigos_funciones

def aplicar_reglas(capas=None, codigos=None, incluir_pendientes=True):
    capas = capas if capas is not None else obtener_capas_relevantes()
    seleccion = list(codigos) if codigos is not None else (list(codigos_funciones.keys()) if incluir_pendientes else list(reglas_implementadas.keys()))
    return {codigo: codigos_funciones[codigo](layer_dict=capas) for codigo in seleccion if codigo in codigos_funciones}