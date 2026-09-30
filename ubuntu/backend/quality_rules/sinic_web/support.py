from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable

from ..base import RuleIssue
from ..dataset import InMemoryDataset
from .compat.topologico import _load_geometry

_GEOMETRY_KEYS = {"geometria", "geometry", "geom", "localizacion", "thegeom", "shape"}


def normalize_key(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").strip().lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return "".join(ch for ch in text if ch.isalnum())


class WebField:
    __slots__ = ("_name",)
    def __init__(self, name: str): self._name = str(name)
    def name(self) -> str: return self._name


class WebFields:
    __slots__ = ("_names",)
    def __init__(self, names: Iterable[str]): self._names = list(dict.fromkeys(str(n) for n in names))
    def __iter__(self): return iter(WebField(name) for name in self._names)
    def names(self) -> list[str]: return list(self._names)
    def indexOf(self, name: str) -> int:
        try: return self._names.index(name)
        except ValueError: return -1
    def indexFromName(self, name: str) -> int: return self.indexOf(name)


class WebWidgetSetup:
    __slots__ = ()
    def type(self) -> str: return ""
    def config(self) -> dict[str, Any]: return {}


class WebFeature:
    __slots__ = ("_row", "_fid", "_fields", "_geometry")
    def __init__(self, row: dict[str, Any], fid: int, fields: WebFields, geometry: Any = None):
        self._row = row
        self._fid = fid
        self._fields = fields
        self._geometry = geometry
    def __getitem__(self, key: str) -> Any: return self._row.get(key)
    def get(self, key: str, default: Any = None) -> Any: return self._row.get(key, default)
    def items(self): return self._row.items()
    def keys(self): return self._row.keys()
    def attribute(self, key: str) -> Any: return self._row.get(key)
    def id(self) -> int: return self._fid
    def fields(self) -> WebFields: return self._fields
    def geometry(self): return self._geometry
    def hasGeometry(self) -> bool:
        if self._geometry is None: return False
        try: return not bool(self._geometry.is_empty)
        except Exception: return True


class WebLayer:
    __slots__ = ("_name", "_fields", "_features", "_id")
    def __init__(self, name: str, rows: Iterable[dict[str, Any]]):
        self._name = str(name)
        source_rows = [dict(row) for row in rows if isinstance(row, dict)]
        field_names: list[str] = []
        seen: set[str] = set()
        for row in source_rows:
            for key in row.keys():
                if str(key).startswith("__"): continue
                if key not in seen:
                    seen.add(key); field_names.append(str(key))
        self._fields = WebFields(field_names)
        self._features: list[WebFeature] = []
        for fid, source in enumerate(source_rows):
            row = dict(source)
            geometry = row.pop("__geometry__", None)
            if geometry is None:
                for key, value in row.items():
                    if normalize_key(key) in _GEOMETRY_KEYS:
                        geometry = _load_geometry(value)
                        if geometry is not None: break
            self._features.append(WebFeature(row, fid, self._fields, geometry))
        self._id = f"web:{self._name}:{id(self)}"
    def name(self) -> str: return self._name
    def id(self) -> str: return self._id
    def source(self) -> str: return self._name
    def fields(self) -> WebFields: return self._fields
    def getFeatures(self): return iter(self._features)
    def featureCount(self) -> int: return len(self._features)
    def isModified(self) -> bool: return False
    def attributeAlias(self, index: int) -> str:
        names = self._fields.names()
        return names[index] if 0 <= index < len(names) else ""
    def editorWidgetSetup(self, index: int) -> WebWidgetSetup: return WebWidgetSetup()


def _row_from_feature(feature: Any) -> dict[str, Any]:
    if isinstance(feature, dict): return dict(feature)
    row = getattr(feature, "_row", None)
    if isinstance(row, dict): return dict(row)
    try: return dict(feature.items())
    except Exception: pass
    out: dict[str, Any] = {}
    try:
        names = feature.fields().names()
    except Exception:
        names = []
    for name in names:
        try: out[str(name)] = feature[name]
        except Exception:
            try: out[str(name)] = feature.attribute(name)
            except Exception: pass
    return out


def dataset_from_layers(layers: dict[str, Any] | None) -> InMemoryDataset:
    tables: dict[str, list[dict[str, Any]]] = {}
    for logical_name, layer in (layers or {}).items():
        if layer is None: continue
        try: table_name = str(layer.name())
        except Exception: table_name = str(logical_name)
        try: rows = [_row_from_feature(feature) for feature in layer.getFeatures()]
        except Exception:
            if isinstance(layer, (list, tuple)): rows = [_row_from_feature(feature) for feature in layer]
            else: rows = []
        tables[table_name] = rows
        if table_name != str(logical_name): tables[str(logical_name)] = rows
    return InMemoryDataset(tables)


def layer_for_table(layers: dict[str, Any] | None, table_name: object) -> Any:
    target = normalize_key(table_name)
    if not target: return None
    for logical_name, layer in (layers or {}).items():
        names = [logical_name]
        try: names.append(layer.name())
        except Exception: pass
        if any(normalize_key(name) == target for name in names): return layer
    return None


def issues_to_result(rule_id: str, issues: Iterable[RuleIssue], layers: dict[str, Any] | None = None) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for issue in issues:
        details = dict(issue.details or {})
        detail_key = repr(sorted((str(k), str(v)) for k, v in details.items() if not str(k).startswith("__")))
        key = (str(issue.rule_id), str(issue.object_ref), str(issue.message), detail_key)
        if key in seen: continue
        seen.add(key)
        table_name = details.get("tabla") or details.get("class") or details.get("tabla_error") or ""
        layer = layer_for_table(layers, table_name)
        errors.append({
            "aid": issue.object_ref,
            "descripcion": issue.message,
            "capa": layer if layer is not None else table_name,
            "regla": str(rule_id),
            "detalles": details,
            "details": details,
        })
    return {
        "cumple": not errors,
        "errores": errors,
        "mensaje": f"Se detectaron {len(errors)} incumplimientos en la regla {rule_id}." if errors else f"No se detectaron errores en la regla {rule_id}.",
    }


def safe_geometry(geometry: Any) -> Any:
    if geometry is None: return None
    try:
        if getattr(geometry, "is_valid", True): return geometry
        from shapely import make_valid
        return make_valid(geometry)
    except Exception:
        return geometry


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)): return value
    if isinstance(value, dict): return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)): return [json_safe(v) for v in value]
    if isinstance(value, WebLayer): return value.name()
    if isinstance(value, WebFeature): return str(value.id())
    try:
        if hasattr(value, "wkt"): return str(value.wkt)
    except Exception: pass
    try:
        name = value.name()
        if name: return str(name)
    except Exception: pass
    return str(value)
