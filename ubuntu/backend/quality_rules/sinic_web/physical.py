# -*- coding: utf-8 -*-
"""Reglas SINIC - Componente Físico.

Implementación de las 12 reglas del componente físico del catálogo oficial SINIC:
- 21: Para todos los Terrenos, verificar que no existan polígonos de áreas mínimas (menos de 1 m2).
- 60: Predios PH UP o Condominio UP deben tener área privada construida > 0 en relación de Copropiedad.
- 80: Ubicación de la planta en Unidades de Construcción debe ser mayor a 0.
- 107: Predios PH Unidad Predial exigen al menos una unidad de construcción asociada.
- 124: Predio PH UP o Cementerio UP exige al menos una unidad de construcción asociada.
- 129: Unidad de Construcción tipo Anexo exige uso de construcción de Anexos.
- 130: Unidad de Construcción tipo Comercial exige uso comercial.
- 131: Unidad de Construcción tipo Industrial exige uso industrial.
- 132: Unidad de Construcción tipo Institucional exige uso institucional.
- 133: Unidad de Construcción tipo Residencial exige uso residencial.
- 135: Relación de superficie En Rasante exige ubicación de planta igual a 1.
- 136: Relación de superficie Sobre Rasante exige ubicación de planta mayor a 1.
"""
from __future__ import annotations
import re

WebProject = None
NULL = None

from .engine import metadata_regla
from .extensions import FISICO_FUNCTIONS
from . import model as arb_model
from .economic_helper import EconomicoWebHelper as _DomainHelper

COMPONENT_SLUG = "fisico"

LAYER_ALIASES = {
    "ARB_Terreno": (
        "ARB_Terreno", "arb_terreno", "LC_Terreno", "lc_terreno", "CR_Terreno", "cr_terreno",
        "E_Terreno", "e_terreno", "terreno", "Terreno", "(ARB) Terreno", "ARB Terreno"
    ),
    "ARB_Predio": (
        "ARB_Predio", "arb_predio", "LC_Predio", "lc_predio", "CR_Predio", "cr_predio",
        "A_Predio", "a_predio", "predio", "Predio"
    ),
    "ARB_UnidadConstruccion": (
        "ARB_UnidadConstruccion", "arb_unidadconstruccion", "LC_UnidadConstruccion", "lc_unidadconstruccion",
        "CR_UnidadConstruccion", "cr_unidadconstruccion", "D_Unidad_de_Construccion", "d_unidad_de_construccion",
        "ARB_Unidad_de_construcción", "ARB_Unidad_de_construccion", "unidadconstruccion", "UnidadConstruccion",
        "LC_Construccion_UnidadConstruccion", "(ARB) Unidad de construcción", "(ARB) Unidad de construccion"
    ),
    "ARB_CaracteristicasUnidadConstruccion": (
        "ARB_CaracteristicasUnidadConstruccion", "arb_caracteristicasunidadconstruccion",
        "LC_CaracteristicasUnidadConstruccion", "lc_caracteristicasunidadconstruccion",
        "CR_CaracteristicasUnidadConstruccion", "cr_caracteristicasunidadconstruccion",
        "caracteristicasunidadconstruccion", "caracteristicas_calificacion",
        "ARB Características de la unidad de construcción", "ARB Caracteristicas de la unidad de construccion",
        "(ARB) Características de la unidad de construcción", "(ARB) Caracteristicas de la unidad de construccion",
        "Características de la unidad de construcción", "Caracteristicas de la unidad de construccion"
    ),
    "ARB_Copropiedad": (
        "ARB_Copropiedad", "arb_copropiedad", "CR_Copropiedad", "cr_copropiedad",
        "ARB_PredioCopropiedad", "arb_prediocopropiedad", "copropiedad", "Copropiedad"
    ),
}


def _is_empty(v):
    if v is None:
        return True
    try:
        if NULL is not None and v == NULL:
            return True
        if hasattr(v, "isNull") and v.isNull():
            return True
    except Exception:
        pass
    s = str(v).strip().lower()
    return s in {"", "none", "null", "<null>", "nan"}


def _is_not_empty(v):
    return not _is_empty(v)


def _to_float(v):
    if _is_empty(v):
        return None
    try:
        return float(str(v).replace(",", ".").strip())
    except Exception:
        return None


def _normalize_text(v):
    if _is_empty(v):
        return ""
    text = str(v).strip().lower()
    for o, r in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ñ", "n")):
        text = text.replace(o, r)
    text = re.sub(r"[_\s\-]+", "_", text)
    return text.strip("_")


def _feature_identify(feature):
    if feature is None:
        return "sin_aid"
    if isinstance(feature, dict):
        for k in ("t_ili_tid", "id_operacion", "t_id", "id", "identificador"):
            val = feature.get(k)
            if _is_not_empty(val):
                return str(val).strip()
        return str(id(feature))
    try:
        for k in ("t_ili_tid", "id_operacion", "t_id", "id", "identificador"):
            val = feature[k]
            if _is_not_empty(val):
                return str(val).strip()
    except Exception:
        pass
    try:
        return str(feature.id())
    except Exception:
        return str(id(feature))


class FisicoWebHelper:
    """Helper para inspección y extracción de capas en el componente físico."""

    TERRENO_NAMES = ("arb_terreno", "lc_terreno", "cr_terreno", "terreno")
    PREDIO_NAMES = ("arb_predio", "lc_predio", "cr_predio", "predio")
    UNIDAD_NAMES = (
        "arb_unidadconstruccion", "arb_unidad_de_construccion", "arb unidad de construccion",
        "(ARB) Unidad de construcción", "(ARB) Unidad de construccion",
        "lc_unidadconstruccion", "cr_unidadconstruccion", "unidadconstruccion",
        "unidad de construcción", "unidad de construccion",
    )
    CARACTERISTICAS_NAMES = (
        "arb_caracteristicasunidadconstruccion", "lc_caracteristicasunidadconstruccion",
        "cr_caracteristicasunidadconstruccion", "caracteristicasunidadconstruccion",
        "ARB Características de la unidad de construcción", "ARB Caracteristicas de la unidad de construccion",
        "(ARB) Características de la unidad de construcción", "(ARB) Caracteristicas de la unidad de construccion",
        "Características de la unidad de construcción", "Caracteristicas de la unidad de construccion",
    )
    COPROPIEDAD_NAMES = ("arb_copropiedad", "cr_copropiedad", "copropiedad", "arb_prediocopropiedad")

    def __init__(self, layers=None):
        self.layers = layers if layers is not None else obtener_capas_relevantes()
        self._feature_layers = {}
        self._domain_helper = _DomainHelper(self.layers)

    @staticmethod
    def normalize_key(name):
        # web usa nombres visibles como ``(ARB) Terreno``; se eliminan todos
        # los separadores/puntuación para equipararlos con ``ARB_Terreno``.
        return re.sub(r"[^a-z0-9]+", "", _normalize_text(name))

    def layer_name(self, layer):
        if layer is None:
            return ""
        try:
            return layer.name()
        except Exception:
            return str(layer)

    def find_layer(self, candidates):
        """Busca por nombre normalizado sin confundir capas auxiliares/históricas.

        La versión anterior aceptaba ``c in norm`` y podía hacer que ``Terreno``
        coincidiera con ``Terreno histórico`` o que ``Predio`` coincidiera con
        ``Alerta Predio``. En el proyecto ARBIMAPS real se prioriza igualdad exacta
        y solo se permite sufijo para nombres técnicos calificados por modelo/esquema.
        """
        if not self.layers:
            return None
        cands_norm = [self.normalize_key(c) for c in candidates if c]
        # 1. Igualdad exacta sobre nombre visible y clave del diccionario.
        for name, layer in self.layers.items():
            names = [name]
            try:
                names.append(layer.name())
            except Exception:
                pass
            norms = {self.normalize_key(n) for n in names}
            if any(c in norms for c in cands_norm):
                return layer
        # 2. Fallback controlado para nombres de modelo/esquema (sin substring genérico).
        technical = [c for c in cands_norm if c.startswith(("arb", "lc", "cr", "cca", "ilc")) and len(c) >= 8]
        for name, layer in self.layers.items():
            try:
                raw = layer.name()
            except Exception:
                raw = name
            norm = self.normalize_key(raw)
            if "historico" in norm or "historica" in norm:
                if not any("historico" in c or "historica" in c for c in cands_norm):
                    continue
            if any(norm.endswith(c) for c in technical):
                return layer
        return None

    def iter_layer_rows(self, candidates):
        layer = self.find_layer(candidates)
        if layer is None:
            return
        tname = self.layer_name(layer)
        try:
            for feat in layer.getFeatures():
                self._feature_layers[id(feat)] = layer
                yield tname, layer, feat
        except Exception:
            if isinstance(layer, (list, tuple)):
                for feat in layer:
                    yield tname, layer, feat

    def get_field_value(self, feature, field_aliases):
        if feature is None:
            return None
        if isinstance(feature, dict):
            for a in field_aliases:
                if a in feature:
                    return feature[a]
            norm_map = {self.normalize_key(k): v for k, v in feature.items()}
            for a in field_aliases:
                norm_a = self.normalize_key(a)
                if norm_a in norm_map:
                    return norm_map[norm_a]
            return None

        fields = feature.fields() if hasattr(feature, "fields") else None
        if fields:
            names = [f.name() for f in fields]
            norm_names = {self.normalize_key(n): n for n in names}
            for a in field_aliases:
                real = a if a in names else norm_names.get(self.normalize_key(a))
                if not real:
                    continue
                try:
                    raw = feature[real]
                except Exception:
                    try:
                        raw = feature.attribute(real)
                    except Exception:
                        continue
                layer = self._feature_layers.get(id(feature))
                if layer is not None:
                    try:
                        return self._domain_helper._resolve_domain_value(layer, real, raw)
                    except Exception:
                        pass
                return raw
        return None

    def make_error(self, layer, feature, rule_id, message, details=None):
        d = dict(details or {})
        tname = d.get("tabla") or self.layer_name(layer)
        d.setdefault("tabla", tname)
        d.setdefault("class", tname)
        meta = metadata_regla(rule_id)
        d.setdefault("sinic_id", rule_id)
        d.setdefault("sinic_abreviatura", meta.get("abbreviation", ""))
        return {
            "aid": _feature_identify(feature),
            "descripcion": message,
            "capa": layer,
            "regla": rule_id,
            "detalles": d,
            "details": d,
        }


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


def _capas(layer_dict, layer_dic):
    return layer_dict if layer_dict is not None else (layer_dic if layer_dic is not None else obtener_capas_relevantes())


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


def _resultado_no_verificable(codigo, motivo):
    return {
        "cumple": True, "no_verificable": True, "errores": [],
        "mensaje": f"Regla SINIC {codigo} no verificable: {motivo}",
        "motivo_no_verificable": motivo, "regla_sinic": metadata_regla(codigo),
    }


def _extraer_id_predio(helper, feat):
    return helper.get_field_value(
        feat,
        ("predio", "arb_predio", "id_predio", "Id_Predio", "predio_id", "Predio_ID", "lc_predio", "cr_predio", "t_id_predio")
    )


def _resolver_tipo_unidad_construccion(helper, feat, char_feat=None):
    raw=None
    for source in (feat,char_feat):
        if source is None:
            continue
        raw=helper.get_field_value(source,("tipo_unidad_construccion","Tipo_Unidad_Construccion","tipo_construccion","Tipo_Construccion","tipo","Tipo"))
        if _is_not_empty(raw):
            break
    norm=_normalize_text(raw)
    if "anexo" in norm or str(raw).strip() in {"1351","289","5"}: return "Anexo"
    if "comercial" in norm or str(raw).strip() in {"1353","291","1"}: return "Comercial"
    if "industrial" in norm or str(raw).strip() in {"1349","287","3"}: return "Industrial"
    if "institucional" in norm or str(raw).strip() in {"1350","288","4"}: return "Institucional"
    if "residencial" in norm or str(raw).strip() in {"1352","290","0"}: return "Residencial"
    return norm or "Desconocido"


def _resolver_uso_construccion(helper, feat, char_feat=None):
    for f in (feat, char_feat):
        if f is None:
            continue
        raw = helper.get_field_value(
            f,
            ("uso", "Uso", "uso_ucons", "Uso_UCons", "uso_unidad_construccion", "destino_economico", "actividad_economica")
        )
        if _is_not_empty(raw):
            return _normalize_text(raw)
    return ""


# -----------------------------------------------------------------------------
# Funciones individuales de validación SINIC (Módulo FÍSICO)
# -----------------------------------------------------------------------------

def regla_21(layer_dict=None, layer_dic=None, **kwargs):
    """Para todos los Terrenos, verificar que no existan polígonos de áreas mínimas (menos de 1 m2)."""
    codigo = "21"
    helper = FisicoWebHelper(_capas(layer_dict, layer_dic))
    errores = []

    for tname, layer, feat in helper.iter_layer_rows(helper.TERRENO_NAMES):
        has_geom = False
        area = None
        if hasattr(feat, "hasGeometry") and feat.hasGeometry():
            geom = feat.geometry()
            if geom is not None:
                try:
                    is_empty = bool(geom.isEmpty()) if hasattr(geom, "isEmpty") else bool(getattr(geom, "is_empty", False))
                except Exception:
                    is_empty = False
                if not is_empty:
                    has_geom = True
                    try:
                        area_value = getattr(geom, "area", None)
                        area = abs(float(area_value() if callable(area_value) else area_value))
                    except Exception:
                        area = None
        elif isinstance(feat, dict) and "area" in feat:
            has_geom = True
            raw_area = _to_float(feat["area"])
            area = abs(raw_area) if raw_area is not None else None

        if has_geom and area is not None:
            if area < 1.0:
                errores.append(helper.make_error(
                    layer, feat, codigo,
                    f"El polígono de terreno tiene un área menor a 1 m² ({area:.4f} m²).",
                    {"tabla": tname, "area_m2": round(area, 4), "umbral_minimo": 1.0}
                ))

    return _resultado_sinic(codigo, errores)


def regla_60(layer_dict=None, layer_dic=None, **kwargs):
    """Predios PH UP o Condominio UP deben tener área privada construida > 0 en relación de Copropiedad."""
    codigo = "60"
    helper = FisicoWebHelper(_capas(layer_dict, layer_dic))
    errores = []
    cop_layer = helper.find_layer(helper.COPROPIEDAD_NAMES)
    predios_aplicables = []
    for _, _, p in helper.iter_layer_rows(helper.PREDIO_NAMES):
        cond = _normalize_text(helper.get_field_value(p,("condicion_predio","Condicion_Predio","condicion","Condicion")))
        npn = helper.get_field_value(p,("numero_predial","Numero_Predial","numero_predial_nacional","Numero_Predial_Nacional"))
        is_up = "unidad_predial" in cond or (npn and len(str(npn))>=22 and str(npn)[21] in ("8","9"))
        if is_up:
            predios_aplicables.append(p)
    if predios_aplicables and cop_layer is None:
        return _resultado_no_verificable(codigo, "la estructura cargada no contiene una relación/capa de Copropiedad con área privada construida")

    # 1. Mapear áreas de copropiedad por id_predio
    copropiedad_por_predio = {}
    for tname, layer, cop_feat in helper.iter_layer_rows(helper.COPROPIEDAD_NAMES):
        predio_fk = helper.get_field_value(
            cop_feat,
            ("unidad_predial", "predio", "arb_predio", "id_predio", "Id_Predio", "t_id_predio")
        )
        if _is_empty(predio_fk):
            continue
        area_priv = _to_float(helper.get_field_value(
            cop_feat,
            ("area_privada_construida", "Area_Privada_Construida", "area_privada", "Area_Privada")
        ))
        area_const = _to_float(helper.get_field_value(
            cop_feat,
            ("area_construida", "Area_Construida", "area_comun_construida")
        ))
        copropiedad_por_predio.setdefault(str(predio_fk).strip(), []).append({
            "tabla": tname,
            "area_privada_construida": area_priv,
            "area_construida": area_const,
            "feat": cop_feat
        })

    # 2. Verificar cada predio PH UP / Condominio UP
    condiciones_up = {
        "ph_unidad_predial", "condominio_unidad_predial", "ph_up", "condominio_up",
        "phunidadpredial", "condominiounidadpredial"
    }

    for tname, layer, predio_feat in helper.iter_layer_rows(helper.PREDIO_NAMES):
        cond_raw = helper.get_field_value(
            predio_feat,
            ("condicion_predio", "Condicion_Predio", "condicion", "Condicion")
        )
        npn = helper.get_field_value(
            predio_feat,
            ("numero_predial", "Numero_Predial", "numero_predial_nacional", "Numero_Predial_Nacional")
        )
        cond_norm = _normalize_text(cond_raw)

        es_ph_cond_up = cond_norm in condiciones_up or "unidad_predial" in cond_norm
        if not es_ph_cond_up and npn:
            digits = "".join(ch for ch in str(npn) if ch.isalnum())
            if len(digits) >= 22 and digits[21] in ("8", "9"):
                es_ph_cond_up = True

        if not es_ph_cond_up:
            continue

        tid = _feature_identify(predio_feat)
        cop_list = copropiedad_por_predio.get(tid, [])
        if not cop_list:
            # También buscar por t_id numérico o id_operacion
            tid_alt = helper.get_field_value(predio_feat, ("t_id", "T_Id", "id_operacion", "id"))
            if tid_alt:
                cop_list = copropiedad_por_predio.get(str(tid_alt).strip(), [])

        # Si no hay copropiedad o ninguna tiene área privada construida > 0:
        area_priv_valida = any(
            (c.get("area_privada_construida") is not None and c["area_privada_construida"] > 0)
            for c in cop_list
        )

        if not area_priv_valida:
            areas_encontradas = [c.get("area_privada_construida") for c in cop_list] if cop_list else "Sin registro en Copropiedad"
            errores.append(helper.make_error(
                layer, predio_feat, codigo,
                f"El predio PH/Condominio UP no cuenta con área privada construida > 0 en la relación de Copropiedad.",
                {
                    "tabla": tname,
                    "numero_predial": npn,
                    "condicion_predio": cond_raw,
                    "area_privada_construida": str(areas_encontradas),
                    "registros_copropiedad": len(cop_list)
                }
            ))

    return _resultado_sinic(codigo, errores)


def regla_80(layer_dict=None, layer_dic=None, **kwargs):
    """Ubicación de la planta en Unidades de Construcción debe ser mayor a 0."""
    codigo = "80"
    helper = FisicoWebHelper(_capas(layer_dict, layer_dic))
    errores = []

    for tname, layer, feat in helper.iter_layer_rows(helper.UNIDAD_NAMES):
        planta_raw = helper.get_field_value(
            feat,
            ("planta_ubicacion", "Planta_Ubicacion", "planta", "Planta", "numero_planta", "piso")
        )
        planta = _to_float(planta_raw)

        if planta is None or planta <= 0:
            errores.append(helper.make_error(
                layer, feat, codigo,
                f"La ubicación de la planta de la unidad de construcción debe ser mayor a 0 (valor actual: {planta_raw}).",
                {"tabla": tname, "planta_ubicacion": planta_raw}
            ))

    return _resultado_sinic(codigo, errores)


def regla_107(layer_dict=None, layer_dic=None, **kwargs):
    """Predios PH Unidad Predial exigen al menos una unidad de construcción asociada."""
    codigo="107"
    capas=_capas(layer_dict,layer_dic)
    helper=FisicoWebHelper(capas)
    errores=[]
    unit_aliases=LAYER_ALIASES["ARB_UnidadConstruccion"]
    cons_aliases=("ARB_Construccion","arb_construccion","(ARB) Construccion","(ARB) Construcción","Construccion","Construcción")
    _,uc_by_predio,_=arb_model.units_by_predio(capas,unit_aliases,cons_aliases,("construccion","arb_construccion","id_construccion"),("predio","arb_predio","id_predio"))
    for tname,layer,predio_feat in helper.iter_layer_rows(helper.PREDIO_NAMES):
        cond_raw=helper.get_field_value(predio_feat,("condicion_predio","Condicion_Predio","condicion","Condicion"))
        cond_norm=_normalize_text(cond_raw)
        npn=helper.get_field_value(predio_feat,("numero_predial","Numero_Predial","numero_predial_nacional","Numero_Predial_Nacional"))
        es_ph_up=("ph" in cond_norm and "unidad_predial" in cond_norm)
        if not es_ph_up and npn:
            digits="".join(ch for ch in str(npn) if ch.isalnum())
            es_ph_up=len(digits)>=22 and digits[21]=="9" and digits[22:30]!="00000000"
        if not es_ph_up:
            continue
        pkey=arb_model.canonical_key(predio_feat)
        if not uc_by_predio.get(pkey):
            errores.append(helper.make_error(layer,predio_feat,codigo,"El predio con condición PH Unidad Predial no tiene asociada ninguna unidad de construcción.",{"tabla":tname,"numero_predial":npn,"condicion_predio":cond_raw}))
    return _resultado_sinic(codigo,errores)


def regla_124(layer_dict=None, layer_dic=None, **kwargs):
    """Predio PH UP o Cementerio UP exige al menos una unidad de construcción asociada."""
    codigo="124"
    capas=_capas(layer_dict,layer_dic)
    helper=FisicoWebHelper(capas)
    errores=[]
    unit_aliases=LAYER_ALIASES["ARB_UnidadConstruccion"]
    cons_aliases=("ARB_Construccion","arb_construccion","(ARB) Construccion","(ARB) Construcción","Construccion","Construcción")
    _,uc_by_predio,_=arb_model.units_by_predio(capas,unit_aliases,cons_aliases,("construccion","arb_construccion","id_construccion"),("predio","arb_predio","id_predio"))
    for tname,layer,predio_feat in helper.iter_layer_rows(helper.PREDIO_NAMES):
        cond_raw=helper.get_field_value(predio_feat,("condicion_predio","Condicion_Predio","condicion","Condicion"))
        cond_norm=_normalize_text(cond_raw)
        npn=helper.get_field_value(predio_feat,("numero_predial","Numero_Predial","numero_predial_nacional","Numero_Predial_Nacional"))
        es_ph=("ph" in cond_norm and "unidad_predial" in cond_norm)
        es_cem=("cementerio" in cond_norm and ("unidad_predial" in cond_norm or "up" in cond_norm))
        if not (es_ph or es_cem) and npn:
            digits="".join(ch for ch in str(npn) if ch.isalnum())
            if len(digits)>=30 and digits[22:30]!="00000000":
                es_ph=digits[21]=="9"
                es_cem=digits[21]=="7"
        if not (es_ph or es_cem):
            continue
        pkey=arb_model.canonical_key(predio_feat)
        if not uc_by_predio.get(pkey):
            errores.append(helper.make_error(layer,predio_feat,codigo,"El predio PH UP o Cementerio UP debe tener al menos una unidad de construcción asociada.",{"tabla":tname,"numero_predial":npn,"condicion_predio":cond_raw}))
    return _resultado_sinic(codigo,errores)


def _validar_tipo_y_uso_uc(helper, codigo, tipo_esperado, palabras_clave_uso, mensaje_inconsistencia):
    errores=[]
    char_layer=helper.find_layer(helper.CARACTERISTICAS_NAMES)
    char_index=arb_model.index_features(char_layer)
    for tname,layer,feat in helper.iter_layer_rows(helper.UNIDAD_NAMES):
        cref=helper.get_field_value(feat,("caracteristicasunidadconstruccion","CaracteristicasUnidadConstruccion","caracteristicas","id_caracteristicas"))
        char_feat=char_index.get(arb_model.ref(cref)) if _is_not_empty(cref) else None
        tipo=_resolver_tipo_unidad_construccion(helper,feat,char_feat)
        if tipo!=tipo_esperado:
            continue
        uso=_resolver_uso_construccion(helper,feat,char_feat)
        if not uso:
            errores.append(helper.make_error(layer,feat,codigo,f"La unidad de construcción es de tipo '{tipo_esperado}', pero no tiene definido su uso de construcción.",{"tabla":tname,"tipo":tipo,"uso":"Vacio"}))
            continue
        if not any(palabra in uso for palabra in palabras_clave_uso):
            errores.append(helper.make_error(layer,feat,codigo,f"{mensaje_inconsistencia} (Uso actual: '{uso}').",{"tabla":tname,"tipo":tipo,"uso":uso,"dominio_esperado":tipo_esperado}))
    return _resultado_sinic(codigo,errores)


def regla_129(layer_dict=None, layer_dic=None, **kwargs):
    """Unidad de Construcción tipo Anexo exige uso de construcción de Anexos."""
    palabras = (
        "anexo", "cobertizo", "enramada", "garaje", "galpon", "piscina", "kiosko",
        "quiosco", "establo", "porqueriza", "caney", "marquesina", "beneficiadero",
        "corral", "tanque", "pesebre", "bodega_anexo", "secadero"
    )
    return _validar_tipo_y_uso_uc(
        FisicoWebHelper(_capas(layer_dict, layer_dic)),
        "129", "Anexo", palabras,
        "La unidad de construcción de tipo Anexo solo debe asociar usos del dominio de Anexos"
    )


def regla_130(layer_dict=None, layer_dic=None, **kwargs):
    """Unidad de Construcción tipo Comercial exige uso comercial."""
    palabras = (
        "comercial", "comercio", "local", "oficina", "hotel", "restaurante", "banco",
        "almacen", "centro_comercial", "parqueadero_comercial", "estacion_servicio",
        "clinica_veterinaria", "cine", "teatro_comercial"
    )
    return _validar_tipo_y_uso_uc(
        FisicoWebHelper(_capas(layer_dict, layer_dic)),
        "130", "Comercial", palabras,
        "La unidad de construcción de tipo Comercial solo debe asociar usos comerciales"
    )


def regla_131(layer_dict=None, layer_dic=None, **kwargs):
    """Unidad de Construcción tipo Industrial exige uso industrial."""
    palabras = (
        "industrial", "industria", "bodega", "fabrica", "taller", "planta", "silo",
        "laboratorio_industrial", "ingenio", "matadero", "almacenamiento_industrial"
    )
    return _validar_tipo_y_uso_uc(
        FisicoWebHelper(_capas(layer_dict, layer_dic)),
        "131", "Industrial", palabras,
        "La unidad de construcción de tipo Industrial solo debe asociar usos industriales"
    )


def regla_132(layer_dict=None, layer_dic=None, **kwargs):
    """Unidad de Construcción tipo Institucional exige uso institucional."""
    palabras = (
        "institucional", "educacion", "colegio", "escuela", "universidad", "salud",
        "hospital", "clinica", "puesto_salud", "culto", "iglesia", "templo", "seguridad",
        "policia", "bomberos", "carcel", "administracion_publica", "alcaldia", "cultural",
        "biblioteca", "museo", "recreacion_deporte", "asilo", "orfanato"
    )
    return _validar_tipo_y_uso_uc(
        FisicoWebHelper(_capas(layer_dict, layer_dic)),
        "132", "Institucional", palabras,
        "La unidad de construcción de tipo Institucional solo debe asociar usos institucionales"
    )


def regla_133(layer_dict=None, layer_dic=None, **kwargs):
    """Unidad de Construcción tipo Residencial exige uso residencial."""
    palabras = (
        "residencial", "habitacional", "vivienda", "casa", "apartamento", "habitacion",
        "choza", "cabana", "bohio", "casa_campestre", "apartamento_multifamiliar"
    )
    return _validar_tipo_y_uso_uc(
        FisicoWebHelper(_capas(layer_dict, layer_dic)),
        "133", "Residencial", palabras,
        "La unidad de construcción de tipo Residencial solo debe asociar usos residenciales"
    )


def regla_135(layer_dict=None, layer_dic=None, **kwargs):
    """Relación de superficie En Rasante exige ubicación de planta igual a 1."""
    codigo = "135"
    helper = FisicoWebHelper(_capas(layer_dict, layer_dic))
    errores = []

    for tname, layer, feat in helper.iter_layer_rows(helper.UNIDAD_NAMES):
        rel_raw = helper.get_field_value(
            feat,
            ("relacion_superficie", "Relacion_Superficie", "relacion_superficie_tipo")
        )
        rel_norm = _normalize_text(rel_raw)

        if "en_rasante" not in rel_norm and rel_norm != "rasante":
            continue

        planta_raw = helper.get_field_value(
            feat,
            ("planta_ubicacion", "Planta_Ubicacion", "planta", "Planta", "numero_planta", "piso")
        )
        planta = _to_float(planta_raw)

        if planta != 1.0:
            errores.append(helper.make_error(
                layer, feat, codigo,
                f"La relación de superficie 'En Rasante' exige ubicación de planta igual a 1 (planta registrada: {planta_raw}).",
                {"tabla": tname, "relacion_superficie": rel_raw, "planta_ubicacion": planta_raw}
            ))

    return _resultado_sinic(codigo, errores)


def regla_136(layer_dict=None, layer_dic=None, **kwargs):
    """Relación de superficie Sobre Rasante exige ubicación de planta mayor a 1."""
    codigo = "136"
    helper = FisicoWebHelper(_capas(layer_dict, layer_dic))
    errores = []

    for tname, layer, feat in helper.iter_layer_rows(helper.UNIDAD_NAMES):
        rel_raw = helper.get_field_value(
            feat,
            ("relacion_superficie", "Relacion_Superficie", "relacion_superficie_tipo")
        )
        rel_norm = _normalize_text(rel_raw)

        if "sobre_rasante" not in rel_norm:
            continue

        planta_raw = helper.get_field_value(
            feat,
            ("planta_ubicacion", "Planta_Ubicacion", "planta", "Planta", "numero_planta", "piso")
        )
        planta = _to_float(planta_raw)

        if planta is None or planta <= 1.0:
            errores.append(helper.make_error(
                layer, feat, codigo,
                f"La relación de superficie 'Sobre Rasante' exige ubicación de planta mayor a 1 (planta registrada: {planta_raw}).",
                {"tabla": tname, "relacion_superficie": rel_raw, "planta_ubicacion": planta_raw}
            ))

    return _resultado_sinic(codigo, errores)


codigos_funciones = {
    "21": regla_21,
    "60": regla_60,
    "80": regla_80,
    "107": regla_107,
    "124": regla_124,
    "129": regla_129,
    "130": regla_130,
    "131": regla_131,
    "132": regla_132,
    "133": regla_133,
    "135": regla_135,
    "136": regla_136,
}
codigos_funciones.update(FISICO_FUNCTIONS)

reglas_implementadas = dict(codigos_funciones)
reglas_exactas_pendientes_fuente = []
reglas_pendientes_logica = []
todas_las_reglas = list(codigos_funciones.keys())

clases_con_reglas = {"Fisico": list(codigos_funciones.keys())}
RULE_FUNCTIONS = codigos_funciones


def aplicar_reglas(capas=None, codigos=None, incluir_pendientes=True):
    capas = capas if capas is not None else obtener_capas_relevantes()
    seleccion = list(codigos) if codigos is not None else (list(codigos_funciones.keys()) if incluir_pendientes else list(reglas_implementadas.keys()))
    return {codigo: codigos_funciones[codigo](layer_dict=capas) for codigo in seleccion if codigo in codigos_funciones}
