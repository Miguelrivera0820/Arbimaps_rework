from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .cartography_reader import CARTOGRAPHY_TABLES, ZONE_TABLES, load_cartography_from_database
from .sinic_web.registry import RULE_FUNCTIONS
from .sinic_web.config import (
    estado_regla,
    clasificacion_regla,
    clasificacion_efectiva,
)
from .sinic_web.support import WebLayer, json_safe, normalize_key
from .sinic_web.extensions import clear_geometry_cache


def build_layer_dict(
    tables: dict[str, list[dict[str, Any]]],
    *,
    municipality_code: str | None = None,
) -> tuple[dict[str, WebLayer], str]:
    """Une el XTF con la cartografía viva del esquema c_cartografia_catastral."""
    layers = {name: WebLayer(name, rows) for name, rows in tables.items()}
    cartography, cartography_source = load_cartography_from_database(municipality_code)
    layers.update(cartography)
    return layers, cartography_source


def load_catalog() -> dict[str, dict[str, Any]]:
    path = Path(__file__).resolve().parent.parent / "resource" / "quality_rules" / "all_rules.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    rules = data.get("rules", []) if isinstance(data, dict) else data
    catalog: dict[str, dict[str, Any]] = {}
    for item in rules:
        if not isinstance(item, dict): continue
        rule_id = str(item.get("id") or "").strip()
        if not rule_id: continue
        copied = dict(item)
        copied["estado"] = estado_regla(rule_id)
        copied["clasificacion"] = clasificacion_regla(rule_id)
        copied["component_slug"] = str(item.get("sheet_slug") or "").strip().lower()
        copied["component_label"] = str(item.get("component") or "").replace("Componente ", "").strip()
        catalog[rule_id] = copied
    return catalog


def run_sinic_rules(tables: dict[str, list[dict[str, Any]]], *, municipality_code: str | None = None) -> dict[str, Any]:
    clear_geometry_cache()
    layers, cartography_source = build_layer_dict(tables, municipality_code=municipality_code)
    catalog = load_catalog()
    results: dict[str, dict[str, Any]] = {}
    cartography_keys = {normalize_key(name) for name in (*CARTOGRAPHY_TABLES, *ZONE_TABLES)}
    base_layers = {name: layer for name, layer in layers.items() if normalize_key(name) not in cartography_keys}
    for rule_id in sorted(RULE_FUNCTIONS, key=int):
        function = RULE_FUNCTIONS[rule_id]
        component = str(catalog.get(str(rule_id), {}).get("component_slug") or "").lower()
        rule_layers = base_layers if component in {"juridico", "economico", "estructura"} else layers
        try:
            result = function(layer_dict=rule_layers)
            if not isinstance(result, dict): result = {"cumple": False, "errores": [], "error_ejecucion": f"La regla {rule_id} devolvió un resultado no válido."}
        except Exception as exc:
            result = {"cumple": False, "errores": [], "error_ejecucion": f"{type(exc).__name__}: {exc}", "mensaje": f"Error ejecutando la regla SINIC {rule_id}: {exc}"}
        # Guardar siempre el resultado de cada regla, también cuando falla.
        results[str(rule_id)] = result

        # Esta clasificación solo afecta a la validación actual: el catálogo
        # predeterminado de las reglas 86 y 87 permanece restrictivo.
        if str(rule_id) in {"86", "87"}:
            estado, clasificacion = clasificacion_efectiva(rule_id, result)
            catalog[str(rule_id)]["estado"] = estado
            catalog[str(rule_id)]["clasificacion"] = clasificacion
    return {"results": results, "catalog": catalog, "cartography_source": cartography_source, "loaded_layers": sorted(layers.keys())}

_json_safe = json_safe

__all__ = ["build_layer_dict", "json_safe", "_json_safe", "load_catalog", "run_sinic_rules"]
