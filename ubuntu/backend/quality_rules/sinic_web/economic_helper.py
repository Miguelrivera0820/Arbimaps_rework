from __future__ import annotations

from typing import Any


def _is_empty(value: Any) -> bool:
    if value is None: return True
    try:
        if hasattr(value, "isNull") and value.isNull(): return True
    except Exception: pass
    text = str(value).strip()
    return text == "" or text.upper() in {"NULL", "<NULL>"} or text.lower() in {"none", "nan"}


class EconomicoWebHelper:
    IDENTIFIER_FIELDS = ("t_ili_tid", "T_Ili_Tid", "T_ILI_TID", "id_operacion", "identificacion", "t_id", "TID", "id", "identificador")
    CARACTERISTICAS_UC_LAYERS = (
        "ARB_CaracteristicasUnidadConstruccion", "arb_caracteristicasunidadconstruccion",
        "ARB_Características_de_la_unidad_de_construcción", "ARB_Caracteristicas_de_la_unidad_de_construccion",
        "ARB_Caracteristicas de la unidad de construccion", "ARB_Características de la unidad de construcción",
        "ARB_Caracteristicas_de_la_unidad_de_construcción", "ARB_Características_de_la_unidad_de_construccion",
        "CaracteristicasUnidadConstruccion", "Características Unidad Construcción", "Caracteristicas Unidad Construccion",
        "Características de la unidad de construcción", "Caracteristicas de la unidad de construccion",
        "Caracteristicas_Unidad_Construccion", "caracteristicas_unidad_construccion", "caracteristicas_calificacion",
        "Características Calificación", "Caracteristicas Calificacion",
    )
    PREDIO_LAYERS = ("ARB_Predio", "arb_predio", "A_Predio", "a_predio")
    NOVEDAD_NUMERO_PREDIAL_LAYERS = ("ARB_NovedadNumeroPredialValor", "arb_novedadnumeropredialvalor", "Novedad Numero Predial", "Novedad Número Predial")
    AVALUO_LAYERS = ("ARB_AvaluoValor", "arb_avaluovalor", "Avaluo Valor", "Avalúo Valor", "(ARB) Avaluo Valor", "(ARB) Avalúo Valor")
    ILC_PREDIO_LAYERS = ("ILC_Predio", "ilc_predio", "(ILC) Predio", "ILC Predio")
    ILC_ESTRUCTURA_AVALUO_LAYERS = ("ILC_EstructuraAvaluo", "ilc_estructuraavaluo", "ILC_Estructura_Avaluo", "(ILC) Estructura Avalúo", "(ILC) Estructura Avaluo", "ILC Estructura Avalúo")
    ILC_DATOS_ADICIONALES_LAYERS = ("ILC_DatosAdicionalesLevantamientoCatastral", "ilc_datosadicionaleslevantamientocatastral", "(ILC) Datos adicionales levantamiento catastral", "ILC Datos Adicionales Levantamiento Catastral")

    def __init__(self, layer_dict=None):
        self.layer_dict = layer_dict or {}
        self._feature_layers: dict[int, Any] = {}

    @staticmethod
    def normalize_key(name):
        text = str(name).strip().lower()
        for old, new in (("á","a"),("é","e"),("í","i"),("ó","o"),("ú","u"),("ñ","n")):
            text = text.replace(old, new)
        return "".join(ch for ch in text if ch.isalnum())

    @classmethod
    def normalize_domain_value(cls, field_name, value):
        if _is_empty(value): return None
        text = str(value).strip()
        norm = cls.normalize_key(text)
        field_norm = cls.normalize_key(field_name)
        generic = {
            "residencial":"Residencial", "comercial":"Comercial", "industrial":"Industrial", "institucional":"Institucional", "anexo":"Anexo",
            "conservacionproteccionambiental":"Conservacion_Proteccion_Ambiental", "sinbanio":"Sin_Banio", "sinbano":"Sin_Banio", "sincocina":"Sin_Cocina",
            "cancelacion":"Cancelacion", "cancelacionporenglobe":"Cancelacion_Por_Englobe", "cancelacionpordesenglobe":"Cancelacion_Por_Desenglobe",
        }
        if norm in generic: return generic[norm]
        if field_norm in {"tipounidadconstruccion", "cctipocalificar", "tipocalificar"}:
            return {"1352":"Residencial","290":"Residencial","0":"Residencial","1353":"Comercial","291":"Comercial","1":"Comercial","1349":"Industrial","287":"Industrial","3":"Industrial","1350":"Institucional","288":"Institucional","4":"Institucional","1351":"Anexo","289":"Anexo","5":"Anexo","1348":"Conservacion_Proteccion_Ambiental","2":"Conservacion_Proteccion_Ambiental"}.get(text, text)
        if field_norm == "tiponovedad":
            return {"1":"Cancelacion","2":"Cancelacion_Por_Englobe","3":"Cancelacion_Por_Desenglobe","611":"Cancelacion"}.get(text, text)
        return text

    @staticmethod
    def _layer_identity(layer):
        try: return layer.id()
        except Exception: return str(id(layer))

    def get_layers(self, aliases):
        alias_norm = {self.normalize_key(a) for a in aliases}
        layers, seen = [], set()
        for logical_name, layer in self.layer_dict.items() if isinstance(self.layer_dict, dict) else []:
            if layer is None: continue
            try: layer_name = layer.name()
            except Exception: layer_name = str(logical_name)
            logical_norm, layer_norm = self.normalize_key(logical_name), self.normalize_key(layer_name)
            is_characteristics = any("caracteristicas" in a and "unidad" in a and "construccion" in a for a in alias_norm)
            if logical_norm in alias_norm or layer_norm in alias_norm or (is_characteristics and "caracteristicas" in layer_norm and "unidad" in layer_norm and "construccion" in layer_norm):
                identity = self._layer_identity(layer)
                if identity not in seen: layers.append(layer); seen.add(identity)
        return layers

    def iter_layer_rows(self, aliases):
        for layer in self.get_layers(aliases):
            table_name = self.layer_name(layer)
            try: features = layer.getFeatures()
            except Exception: continue
            for feature in features:
                self._feature_layers[id(feature)] = layer
                yield table_name, layer, feature

    def iter_caracteristicas_unidad_construccion(self):
        yield from self.iter_layer_rows(self.CARACTERISTICAS_UC_LAYERS)

    @staticmethod
    def layer_name(layer):
        try: return layer.name()
        except Exception: return ""

    @staticmethod
    def field_names(feature_or_layer):
        try: return list(feature_or_layer.fields().names())
        except Exception:
            try: return [field.name() for field in feature_or_layer.fields()]
            except Exception: return []

    def has_any_field(self, layer, candidates):
        fields = {self.normalize_key(field) for field in self.field_names(layer)}
        return any(self.normalize_key(candidate) in fields for candidate in candidates)

    def get_field_value(self, feature, candidates):
        candidate_norm = {self.normalize_key(candidate) for candidate in candidates}
        if isinstance(feature, dict):
            for key, value in feature.items():
                if self.normalize_key(key) in candidate_norm: return self.normalize_domain_value(key, value)
            return None
        names = self.field_names(feature)
        for field_name in names:
            if self.normalize_key(field_name) not in candidate_norm: continue
            try: raw = feature[field_name]
            except Exception:
                try: raw = feature.attribute(field_name)
                except Exception: return None
            return self.normalize_domain_value(field_name, raw)
        return None

    def _resolve_domain_value(self, layer, field_name, raw_value):
        return self.normalize_domain_value(field_name, raw_value)

    def identify(self, feature):
        for field in self.IDENTIFIER_FIELDS:
            value = self.get_field_value(feature, (field,))
            if not _is_empty(value): return str(value).strip()
        return None

    def make_error(self, layer, feature, rule_id, message, details=None):
        fixed = dict(details or {})
        table_name = fixed.get("tabla") or self.layer_name(layer)
        fixed.setdefault("tabla", table_name); fixed.setdefault("class", table_name)
        return {"aid": self.identify(feature), "descripcion": message, "capa": layer, "regla": rule_id, "details": fixed, "detalles": fixed}


def _is_not_empty(value: Any) -> bool:
    return not _is_empty(value)


def _to_float(value: Any):
    if _is_empty(value): return None
    try: return float(str(value).strip().replace(",", "."))
    except Exception: return None


def _normalized_domain_text(value: Any) -> str:
    return EconomicoWebHelper.normalize_key("" if value is None else str(value).strip())


def _novedad_es_cancelacion(value: Any) -> bool:
    return False if _is_empty(value) else "cancelacion" in _normalized_domain_text(value)


def _feature_identifier_aliases(helper: EconomicoWebHelper, feature: Any) -> set[str]:
    aliases: set[str] = set()
    for field in helper.IDENTIFIER_FIELDS:
        value = helper.get_field_value(feature, (field,))
        if _is_not_empty(value): aliases.add(str(value).strip())
    return aliases
