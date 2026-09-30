from __future__ import annotations

import unicodedata
from pathlib import Path
from typing import Any

from .xtf_reader import parse_xtf_tables, TARGET_CLASSES
from .sinic_web_adapter import run_sinic_rules, _json_safe
from .npn_resolver import (
    annotate_ids_with_npns,
    build_npn_lookup,
    build_tid_lookup,
    resolve_display_tid,
    resolve_issue_npn,
)


def _debug_tables(tables: dict[str, list[dict[str, Any]]]) -> None:
    print("========== TABLAS DETECTADAS EN XTF ==========")
    if not tables:
        print("No se detectaron tablas.")
        print("=============================================")
        return

    for table_name, rows in sorted(tables.items()):
        print(f"TABLA: {table_name}")
        print(f"CANTIDAD: {len(rows)}")
        if rows:
            first_row = rows[0]
            print(f"CAMPOS: {list(first_row.keys())}")
            print(f"MUESTRA: {first_row}")
        print("---------------------------------------------")

    print("=============================================")


def _total_predios(tables: dict[str, list[dict[str, Any]]]) -> int:
    for table_name in ("ARB_Predio", "arb_predio", "ILC_Predio", "ilc_predio"):
        rows = tables.get(table_name)
        if rows:
            return len(rows)
    return 0


PREDIO_TABLES = ("ARB_Predio", "arb_predio", "ILC_Predio", "ilc_predio")
PREDIO_IDENTIFIER_FIELDS = (
    "t_ili_tid",
    "T_Ili_Tid",
    "T_ILI_TID",
    "id_operacion",
    "Id_Operacion",
    "ID_OPERACION",
    "id_predio",
    "ID_PREDIO",
    "predio_id",
    "Predio_ID",
    "t_id",
    "T_ID",
    "tid",
    "TID",
)


def _normalize_key(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").strip().lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return "".join(ch for ch in text if ch.isalnum())


def _clean_identifier(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return text if text and text.lower() not in {"null", "none", "nan", "n/a", "na"} else ""


def _predio_identifier_lookup(tables: dict[str, list[dict[str, Any]]]) -> dict[str, str]:
    field_targets = {_normalize_key(field) for field in PREDIO_IDENTIFIER_FIELDS}
    lookup: dict[str, str] = {}

    for table_name in PREDIO_TABLES:
        for row in tables.get(table_name, []):
            identifiers: list[str] = []

            for key, value in row.items():
                if _normalize_key(key) not in field_targets:
                    continue
                identifier = _clean_identifier(value)
                if identifier and identifier not in identifiers:
                    identifiers.append(identifier)

            if not identifiers:
                continue

            display_id = identifiers[0]
            for identifier in identifiers:
                lookup[identifier] = display_id

    return lookup


def _issue_predio_id(issue: dict[str, Any], predio_lookup: dict[str, str]) -> str | None:
    details = issue.get("details")
    if not isinstance(details, dict):
        details = {}

    candidates: list[object] = []
    candidate_fields = (
        "t_ili_tid",
        "T_Ili_Tid",
        "T_ILI_TID",
        "predio_id",
        "id_predio",
        "id_operacion",
        "Id_Operacion",
        "ID_OPERACION",
        "arb_predio",
        "ilc_predio",
        "predio",
        "display_id",
        "object_id",
        "tid",
        "t_id",
        "T_ID",
    )

    for field in candidate_fields:
        candidates.append(details.get(field))
        candidates.append(issue.get(field))

    for source in (details, issue):
        for key, value in source.items():
            normalized_key = _normalize_key(key)
            if "predio" in normalized_key or normalized_key in {"tid", "idoperacion"}:
                candidates.append(value)

    object_class = _normalize_key(issue.get("object_class") or details.get("class") or details.get("tabla"))
    is_predio_object = object_class in {"arbpredio", "ilcpredio"}

    for candidate in candidates:
        identifier = _clean_identifier(candidate)
        if not identifier:
            continue
        if identifier in predio_lookup:
            return predio_lookup[identifier]
        if is_predio_object:
            return identifier

    return None


def _build_predio_summary(
    issues: list[dict[str, Any]],
    tables: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    predio_lookup = _predio_identifier_lookup(tables)
    predio_display_ids = set(predio_lookup.values())
    single_predio_id = next(iter(predio_display_ids)) if len(predio_display_ids) == 1 else None
    issue_counts_by_predio: dict[str, int] = {}

    for issue in issues:
        predio_id = _issue_predio_id(issue, predio_lookup)
        if not predio_id:
            predio_id = single_predio_id or "Sin identificar"
        issue_counts_by_predio[predio_id] = issue_counts_by_predio.get(predio_id, 0) + 1

    return [
        {"object_id": object_id, "issue_count": count}
        for object_id, count in sorted(
            issue_counts_by_predio.items(),
            key=lambda item: (-item[1], item[0]),
        )
    ]


def run_quality_checks(
    xtf_path: Path,
    *,
    municipality_code: str | None = None,
    department_code: str | None = None,
    dane_municipality_code: str | None = None,
    orip_code: str | None = None,
    department_name: str | None = None,
    municipality_name: str | None = None,
) -> dict[str, Any]:
    """Ejecuta en web el catálogo y la lógica SINIC unificada."""
    try:
        tables = parse_xtf_tables(xtf_path, TARGET_CLASSES)
        npn_lookup = build_npn_lookup(tables)
        tid_lookup = build_tid_lookup(tables)
    except Exception as exc:
        return {
            "status": "error",
            "issues": [],
            "message": f"No se pudieron leer las tablas del XTF: {exc}",
            "quality": {
                "summary": {
                    "total_rules": 0, "available_rules": 0, "implemented_rules": 0,
                    "unimplemented_rules": 0, "passed_rules": 0, "failed_rules": 0,
                    "total_issues": 0, "total_predios": 0, "predios_con_errores": 0,
                    "predios_sin_errores": 0,
                },
                "rules": [], "rule_catalog": {}, "predio_summary": [],
                "unimplemented_rule_ids": [], "issues": [],
            },
        }

    execution = run_sinic_rules(tables, municipality_code=municipality_code)
    raw_results = execution.get("results") or {}
    rule_catalog = execution.get("catalog") or {}
    executable_ids = sorted(raw_results.keys(), key=lambda value: int(value))
    omitted_ids = sorted(
        [rule_id for rule_id in rule_catalog if rule_id not in raw_results],
        key=lambda value: int(value),
    )

    issues: list[dict[str, Any]] = []
    rule_status: list[dict[str, Any]] = []

    for rule_id in executable_ids:
        result = raw_results.get(rule_id) or {}
        catalog_item = rule_catalog.get(rule_id) or {}
        component_slug = str(catalog_item.get("component_slug") or catalog_item.get("sheet_slug") or "").strip().lower()
        component_label = str(catalog_item.get("component_label") or catalog_item.get("component") or component_slug.title()).strip()
        errors = result.get("errores") if isinstance(result.get("errores"), list) else []
        execution_error = str(result.get("error_ejecucion") or "").strip()

        for error in errors:
            if not isinstance(error, dict):
                continue
            details = error.get("detalles") if isinstance(error.get("detalles"), dict) else error.get("details")
            details = _json_safe(dict(details)) if isinstance(details, dict) else {}
            raw_aid = (
                error.get("aid") or details.get("aid") or details.get("t_ili_tid")
                or details.get("T_Ili_Tid") or details.get("T_ILI_TID")
                or details.get("id_operacion") or details.get("id_predio")
            )
            # El AID y el NPN son conceptos distintos. Algunos objetos anidados
            # (especialmente ARB_AvaluoValor) no traen TID propio y el helper
            # puede devolver el NPN como aid. En ese caso se muestra el UUID/TID
            # del predio relacionado y el NPN permanece exclusivamente en NPN.
            predio_id_hint = str(details.get("predio_id") or details.get("predio_ref") or "").strip()
            raw_aid_text = str(raw_aid or "").strip()
            raw_aid_is_npn = raw_aid_text.isdigit() and len(raw_aid_text) == 30
            display_source = predio_id_hint if (raw_aid_is_npn and predio_id_hint) else raw_aid
            display_id = resolve_display_tid(display_source, tid_lookup) if display_source else None
            if not display_id:
                display_id = str(display_source or "Sin identificar")
            object_class = str(
                details.get("class") or details.get("tabla") or error.get("capa") or ""
            ).strip()
            npn = str(details.get("numero_predial") or details.get("npn") or "").strip()
            if not npn:
                for candidate in (
                    raw_aid, details.get("predio"), details.get("predio_ref"),
                    details.get("predio_id"), details.get("arb_predio"),
                    details.get("ilc_predio"), details.get("id_terreno"),
                    details.get("id_construccion"), details.get("id_uconstruccion"),
                ):
                    key = str(candidate or "").strip()
                    if key and key in npn_lookup:
                        npn = npn_lookup[key]
                        break
            message = str(error.get("descripcion") or error.get("message") or "Incumplimiento de la regla.")
            message = annotate_ids_with_npns(message, npn_lookup)
            issues.append({
                "rule": rule_id,
                "display_id": display_id,
                "object_id": display_id,
                "tid": raw_aid,
                "object_class": object_class,
                "npn": npn,
                "message": message,
                "details": details,
                "component": component_slug,
                "component_label": component_label,
                "estado": catalog_item.get("estado"),
                "clasificacion": catalog_item.get("clasificacion"),
            })

        if execution_error:
            issues.append({
                "rule": rule_id,
                "display_id": "Validador interno",
                "object_id": None,
                "tid": None,
                "object_class": "",
                "npn": "",
                "message": f"No se pudo ejecutar la regla SINIC {rule_id}: {execution_error}",
                "details": {"error_ejecucion": execution_error},
                "component": component_slug,
                "component_label": component_label,
                "estado": catalog_item.get("estado"),
                "clasificacion": catalog_item.get("clasificacion"),
            })

        issue_count = len(errors) + (1 if execution_error else 0)
        if execution_error:
            verification_status = "error_ejecucion"
        elif result.get("no_verificable"):
            verification_status = "parcial" if result.get("verificacion_parcial") else "no_verificable"
        elif result.get("no_aplica"):
            verification_status = "no_aplica"
        else:
            verification_status = "verificada"
        rule_status.append({
            "rule": rule_id,
            "component": component_slug,
            "component_label": component_label,
            "description": str(catalog_item.get("description") or ""),
            "passed": issue_count == 0,
            "issue_count": issue_count,
            "estado": catalog_item.get("estado"),
            "clasificacion": catalog_item.get("clasificacion"),
            "verification_status": verification_status,
            "no_verificable": bool(result.get("no_verificable")),
            "verificacion_parcial": bool(result.get("verificacion_parcial")),
            "mensaje": result.get("mensaje"),
        })

    total_predios = _total_predios(tables)
    predio_summary = _build_predio_summary(issues, tables)
    identified_predios = [item for item in predio_summary if item.get("object_id") != "Sin identificar"]
    predios_con_errores = min(len(identified_predios), total_predios) if total_predios else len(identified_predios)
    predios_sin_errores = max(total_predios - predios_con_errores, 0)
    passed_rules = sum(1 for item in rule_status if item["passed"])
    failed_rules = len(rule_status) - passed_rules

    quality = {
        "npn_by_object_id": npn_lookup,
        "issues": issues,
        "summary": {
            "total_rules": len(rule_status),
            "available_rules": len(rule_catalog),
            "implemented_rules": len(rule_status),
            "unimplemented_rules": len(omitted_ids),
            "passed_rules": passed_rules,
            "failed_rules": failed_rules,
            "total_issues": len(issues),
            "total_predios": total_predios,
            "predios_con_errores": predios_con_errores,
            "predios_sin_errores": predios_sin_errores,
        },
        "rules": rule_status,
        "rule_catalog": rule_catalog,
        "predio_summary": predio_summary,
        "unimplemented_rule_ids": omitted_ids,
        "omitted_rule_ids": omitted_ids,
        "cartography_source": execution.get("cartography_source") or "",
        "loaded_layers": execution.get("loaded_layers") or [],
    }
    return {
        "status": "passed" if not issues else "failed",
        "issues": issues,
        "message": None,
        "quality": quality,
    }
