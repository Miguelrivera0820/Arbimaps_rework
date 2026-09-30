from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .compat import administrativo as arb_admin
from .compat import juridico as arb_jur
from .compat import obligatorias as arb_obl
from .compat import economico as arb_eco
from .compat import fisico as arb_fis
from .support import dataset_from_layers, issues_to_result
from .legacy_sources import SOURCE_RULES

_META_CACHE: dict[str, dict[str, Any]] | None = None


def _catalog_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "resource" / "quality_rules"


def _load_meta(force: bool = False) -> dict[str, dict[str, Any]]:
    global _META_CACHE
    if _META_CACHE is not None and not force: return _META_CACHE
    meta: dict[str, dict[str, Any]] = {}
    for name in ("all_rules.json", "estructura.json", "general.json", "juridico.json", "economico.json", "fisico.json"):
        path = _catalog_dir() / name
        if not path.exists(): continue
        try: data = json.loads(path.read_text(encoding="utf-8"))
        except Exception: continue
        rules = data.get("rules", []) if isinstance(data, dict) else data if isinstance(data, list) else []
        for item in rules:
            if not isinstance(item, dict): continue
            rid = str(item.get("id") or "").strip()
            if rid: meta[rid] = item
    _META_CACHE = meta
    return meta


def metadata_regla(codigo: object) -> dict[str, Any]:
    rid = str(codigo).strip()
    meta = _load_meta().get(rid)
    if meta is None: meta = _load_meta(force=True).get(rid)
    return meta or {}


def limpiar_cache_metadata() -> None:
    global _META_CACHE
    _META_CACHE = None


def resultado_pendiente(codigo: object, motivo: str | None = None) -> dict[str, Any]:
    rid = str(codigo)
    meta = metadata_regla(rid)
    impl = meta.get("implementation", {}) if isinstance(meta, dict) else {}
    message = motivo or impl.get("pending_reason") or f"Regla SINIC {rid} preparada; lógica pendiente de implementación."
    return {"cumple": True, "omitida": True, "pendiente": True, "errores": [], "mensaje": message, "regla_sinic": meta}


def _texto(value: Any) -> str:
    if value is None: return ""
    text = str(value).strip()
    return "" if text.lower() in {"", "none", "null", "<null>", "nan"} else text


def _detalles(error: Any) -> dict[str, Any]:
    if not isinstance(error, dict): return {}
    details = error.get("detalles")
    if not isinstance(details, dict): details = error.get("details")
    return dict(details) if isinstance(details, dict) else {}


def _clave_error(error: dict[str, Any]) -> tuple[str, str, str, str]:
    layer = error.get("capa")
    try: layer_name = layer.name()
    except Exception: layer_name = _texto(layer)
    return (_texto(error.get("aid")), _texto(layer_name), _texto(error.get("descripcion")), repr(sorted((str(k), str(v)) for k, v in _detalles(error).items())))


def _source_callable(module_key: str, rule_id: str):
    module = {"administrativo": arb_admin, "juridico": arb_jur, "obligatorias": arb_obl, "economico": arb_eco, "fisico": arb_fis}.get(module_key)
    if module is None: return None
    functions = getattr(module, "RULE_FUNCTIONS", {})
    fn = functions.get(rule_id) if isinstance(functions, dict) else None
    if callable(fn): return fn
    private_name = ("rule_" if module_key == "obligatorias" else "_rule_") + rule_id.replace(".", "_")
    fn = getattr(module, private_name, None)
    if callable(fn): return fn
    return SOURCE_RULES.get(rule_id)


def _ejecutar_fuente(module_key: str, rule_id: str, layers: dict[str, Any] | None):
    if rule_id == "1.50": return None
    fn = _source_callable(module_key, rule_id)
    if not callable(fn): return None
    dataset = dataset_from_layers(layers)
    issues = fn(dataset)
    return issues_to_result(rule_id, issues, layers)


def _corresponde(codigo_sinic: object, fuente: str, error: dict[str, Any]) -> bool:
    sid = str(codigo_sinic)
    desc = _texto(error.get("descripcion")).lower()
    details = _detalles(error)
    if fuente == "1.1" and sid in {"13", "14", "15"}:
        esperado = {"13": "000000000", "14": "300000000", "15": "400000000"}
        return _texto(details.get("valor_esperado_22_30")) == esperado[sid]
    if fuente == "2.2" and sid == "88": return "privado no informal" in desc and "dominio" in desc
    if fuente == "2.2" and sid == "94": return False
    if sid == "110" and fuente == "2.20":
        nombres = details.get("nombres")
        if isinstance(nombres, (list, tuple)): return any(bool(_texto(value)) for value in nombres)
        return "nombres" in desc or "apellidos" in desc
    return True


def ejecutar_regla_exacta(codigo_sinic: object, layer_dict: dict[str, Any] | None = None) -> dict[str, Any]:
    codigo = str(codigo_sinic)
    meta = metadata_regla(codigo)
    if not meta: raise KeyError(f"Regla SINIC no registrada: {codigo}")
    equivalence = meta.get("equivalence", {})
    implementation = meta.get("implementation", {})
    if str(equivalence.get("type", "")).lower() != "exacta": return resultado_pendiente(codigo)
    if not implementation.get("executable"): return resultado_pendiente(codigo)

    sources = list(implementation.get("source_rule_ids") or [])
    module_keys = list(implementation.get("source_module_keys") or [])
    errors: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    missing: list[str] = []
    source_messages: list[str] = []
    source_to_module = {
        "1.1":"administrativo", "1.5":"administrativo", "1.12":"administrativo", "1.50":"administrativo",
        "11.48":"obligatorias",
        "2.2":"juridico", "2.3":"juridico", "2.10":"juridico", "2.12":"juridico", "2.14":"juridico", "2.16":"juridico", "2.18":"juridico", "2.20":"juridico", "2.23":"juridico", "2.24":"juridico", "2.25":"juridico",
        "4.10":"economico", "4.11":"economico",
        "3.1":"fisico", "3.5":"fisico", "3.7":"fisico", "3.8":"fisico", "3.9":"fisico", "3.10":"fisico", "3.11":"fisico", "3.12":"fisico", "3.18":"fisico",
    }
    for source in sources:
        module_key = source_to_module.get(source) or (module_keys[0] if module_keys else "")
        result = _ejecutar_fuente(module_key, source, layer_dict)
        if result is None:
            missing.append(source); continue
        if isinstance(result, dict) and result.get("mensaje"): source_messages.append(f"{source}: {result['mensaje']}")
        for original in (result.get("errores", []) if isinstance(result, dict) else []) or []:
            if not isinstance(original, dict) or not _corresponde(codigo, source, original): continue
            error = dict(original)
            details = _detalles(error)
            details.update({"sinic_id": codigo, "sinic_abreviatura": meta.get("abbreviation", ""), "arbimaps_regla_origen": source, "tipo_equivalencia": "Exacta"})
            error["detalles"] = details; error["details"] = details; error["regla"] = codigo
            key = _clave_error(error)
            if key in seen: continue
            seen.add(key); errors.append(error)
    if missing:
        return {"cumple": True, "omitida": True, "pendiente": True, "errores": errors, "mensaje": f"Regla SINIC {codigo} definida como Exacta, pero falta lógica fuente: {', '.join(missing)}.", "fuentes_no_disponibles": missing, "regla_sinic": meta}
    return {"cumple": not errors, "errores": errors, "mensaje": f"Se detectaron {len(errors)} incumplimientos en la regla SINIC {codigo}." if errors else f"No se detectaron errores en la regla SINIC {codigo}.", "mensajes_fuente": source_messages, "regla_sinic": meta}
