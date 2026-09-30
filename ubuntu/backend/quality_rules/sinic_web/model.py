# -*- coding: utf-8 -*-
"""Resolución estructural ARB/LADM compartida por los validadores SINIC.

El objetivo es que las reglas dependan de la estructura del modelo (capas, campos y
relaciones) y nunca de IDs, cantidades de objetos, radicados o nombres de archivos XTF.
Funciona con las capas y entidades ligeras preparadas por el backend web.
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict

WebProject = None


def norm(value):
    if value is None:
        return ""
    text = str(value).strip().upper()
    text = "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))
    return "".join(ch for ch in text if ch.isalnum())


def text(value):
    if value is None:
        return ""
    try:
        if hasattr(value, "isNull") and value.isNull():
            return ""
    except Exception:
        pass
    s = str(value).strip()
    return "" if s.lower() in {"", "none", "null", "<null>", "nan"} else s


def ref(value):
    s = text(value).strip().strip("{}").strip()
    if re.fullmatch(r"[-+]?\d+\.0+", s):
        s = s.split(".", 1)[0]
    return s


def layer_name(layer):
    if layer is None:
        return ""
    try:
        return text(layer.name())
    except Exception:
        return text(layer)


def unique_layers(capas):
    seen = set()
    for layer in (capas or {}).values():
        if layer is None:
            continue
        marker = id(layer)
        if marker in seen:
            continue
        seen.add(marker)
        yield layer


def project_layers(capas=None):
    result = dict(capas or {})
    if WebProject is not None:
        try:
            for layer in WebProject.instance().mapLayers().values():
                result.setdefault(layer_name(layer), layer)
        except Exception:
            pass
    return result


def find_layer(capas, aliases, allow_historical=False):
    aliases = tuple(aliases or ())
    wanted = {norm(a) for a in aliases if norm(a)}
    if not wanted:
        return None
    layers = project_layers(capas)
    # Exacto primero.
    for key, layer in layers.items():
        names = {norm(key), norm(layer_name(layer))}
        if not allow_historical and any("HISTOR" in n for n in names):
            if not any("HISTOR" in w for w in wanted):
                continue
        if names & wanted:
            return layer
    # Fallback solo para nombres técnicos calificados; nunca substring genérico.
    technical = {w for w in wanted if len(w) >= 8 and w.startswith(("ARB", "ILC", "LC", "CR", "CCA", "CC"))}
    for key, layer in layers.items():
        names = {norm(key), norm(layer_name(layer))}
        if not allow_historical and any("HISTOR" in n for n in names) and not any("HISTOR" in w for w in wanted):
            continue
        if any(any(n.endswith(w) for w in technical) for n in names):
            return layer
    return None


def features(layer):
    if layer is None:
        return []
    if isinstance(layer, (list, tuple)):
        return list(layer)
    try:
        return list(layer.getFeatures())
    except Exception:
        return []


def field_names(feature):
    if isinstance(feature, dict):
        return list(feature.keys())
    try:
        return [f.name() for f in feature.fields()]
    except Exception:
        return []


def get(feature, aliases, default=None):
    if feature is None:
        return default
    if isinstance(aliases, str):
        aliases = (aliases,)
    names = field_names(feature)
    nmap = {norm(n): n for n in names}
    for alias in aliases:
        if isinstance(feature, dict) and alias in feature:
            return feature.get(alias)
        real = nmap.get(norm(alias))
        if real is None:
            continue
        try:
            return feature[real] if not isinstance(feature, dict) else feature.get(real)
        except Exception:
            try:
                return feature.attribute(real)
            except Exception:
                pass
    return default


# Identificadores estructurales que pueden ser destino de una REF/FK.
# No se usan identificadores de negocio (p.ej. ``identificador``) ni el FID
# interno de web: podrían coincidir accidentalmente con una FK de otra tabla.
STABLE_ID_FIELDS = (
    "t_id", "T_Id", "T_ID",
    "t_ili_tid", "T_Ili_Tid", "T_ILI_TID", "TID", "tid",
    "id_operacion", "Id_Operacion", "ID_OPERACION",
)
PREDIO_ALT_FIELDS = (
    "numero_predial", "Numero_Predial", "numero_predial_nacional", "Numero_Predial_Nacional", "npn", "NPN",
    "codigo_homologado", "Codigo_Homologado", "nupre", "NUPRE",
)


def entity_keys(feature, extra_fields=(), include_fid=False):
    keys = set()
    for field in tuple(STABLE_ID_FIELDS) + tuple(extra_fields):
        k = ref(get(feature, (field,)))
        if k:
            keys.add(k)
    if include_fid and not isinstance(feature, dict):
        try:
            k = ref(feature.id())
            if k:
                keys.add(k)
        except Exception:
            pass
    return keys


def predio_index(capas, aliases=("ARB_Predio", "(ARB) Predio", "Predio")):
    layer = find_layer(capas, aliases)
    rows = features(layer)
    index = {}
    for feat in rows:
        for key in entity_keys(feat, PREDIO_ALT_FIELDS):
            index.setdefault(key, feat)
    return layer, rows, index


def resolve_by_ref(feature, reference_fields, index):
    for field in reference_fields:
        k = ref(get(feature, (field,)))
        if k and k in index:
            return index[k], k
    return None, ""


def canonical_key(feature):
    # Prioridad a t_ili_tid para mostrar; las relaciones internas usan únicamente
    # llaves estructurales, nunca identificadores de negocio ni el FID de web.
    for field in ("t_ili_tid", "T_Ili_Tid", "T_ILI_TID", "TID", "tid", "t_id", "T_Id", "T_ID", "id_operacion"):
        k = ref(get(feature, (field,)))
        if k:
            return k
    keys = entity_keys(feature)
    return next(iter(keys), str(id(feature)))


def index_features(layer, extra_fields=()):
    idx = {}
    for feat in features(layer):
        for key in entity_keys(feat, extra_fields):
            idx.setdefault(key, feat)
    return idx


def construction_predio_map(capas, construction_aliases, predio_ref_fields):
    _, _, pidx = predio_index(capas)
    layer = find_layer(capas, construction_aliases)
    by_construction_key = {}
    by_predio_key = defaultdict(list)
    unlinked = []
    for cons in features(layer):
        predio, _ = resolve_by_ref(cons, predio_ref_fields, pidx)
        if predio is None:
            unlinked.append(cons)
            continue
        pkey = canonical_key(predio)
        by_predio_key[pkey].append(cons)
        for ckey in entity_keys(cons):
            by_construction_key[ckey] = predio
    return layer, by_predio_key, by_construction_key, unlinked


def units_by_predio(capas, unit_aliases, construction_aliases, unit_construction_fields, predio_ref_fields):
    cons_layer, cons_by_predio, cons_to_predio, _ = construction_predio_map(capas, construction_aliases, predio_ref_fields)
    unit_layer = find_layer(capas, unit_aliases)
    by_predio = defaultdict(list)
    unlinked = []
    seen = set()
    _, _, pidx = predio_index(capas)
    for unit in features(unit_layer):
        predio = None
        # Algunas variantes materializan predio directo en la unidad.
        predio, _ = resolve_by_ref(unit, predio_ref_fields, pidx)
        if predio is None:
            for field in unit_construction_fields:
                ckey = ref(get(unit, (field,)))
                if ckey and ckey in cons_to_predio:
                    predio = cons_to_predio[ckey]
                    break
        if predio is None:
            unlinked.append(unit)
            continue
        pkey = canonical_key(predio)
        marker = canonical_key(unit)
        if (pkey, marker) not in seen:
            seen.add((pkey, marker))
            by_predio[pkey].append(unit)
    return unit_layer, by_predio, unlinked


def rows_by_predio(capas, layer_aliases, predio_ref_fields):
    _, _, pidx = predio_index(capas)
    layer = find_layer(capas, layer_aliases)
    out = defaultdict(list)
    unlinked = []
    for feat in features(layer):
        predio, _ = resolve_by_ref(feat, predio_ref_fields, pidx)
        if predio is None:
            unlinked.append(feat)
        else:
            out[canonical_key(predio)].append(feat)
    return layer, out, unlinked


def relation_pairs(capas, relation_aliases, left_fields, right_fields):
    layer = find_layer(capas, relation_aliases)
    pairs = []
    for feat in features(layer):
        left = ""
        right = ""
        for f in left_fields:
            left = ref(get(feat, (f,)))
            if left:
                break
        for f in right_fields:
            right = ref(get(feat, (f,)))
            if right:
                break
        if left or right:
            pairs.append((left, right, feat))
    return layer, pairs
