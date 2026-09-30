from __future__ import annotations

from ..base import RuleIssue
from .compat.administrativo import NumeroPredialHelper, _normalize_direccion_tipo
from .compat.juridico import JuridicoHelper, DOCUMENTO_IDENTIDAD_FIELDS, _nit_es_valido


def rule_1_40(dataset):
    helper = NumeroPredialHelper(dataset)
    issues: list[RuleIssue] = []
    required = {
        "clase_via_principal": ("clase_via_principal", "Clase_Via_Principal"),
        "valor_via_principal": ("valor_via_principal", "Valor_Via_Principal"),
        "valor_via_generadora": ("valor_via_generadora", "Valor_Via_Generadora"),
        "numero_predio": ("numero_predio", "Numero_Predio"),
    }
    for table_name, row in helper.iter_direcciones():
        tipo_match = helper._extract_field(row, ("tipo_direccion", "Tipo_Direccion"), require_value=False)
        tipo_raw = tipo_match[1] if tipo_match else None
        if _normalize_direccion_tipo(tipo_raw) != "ESTRUCTURADA":
            continue
        missing: list[str] = []
        for label, fields in required.items():
            match = helper._extract_field(row, fields, require_value=False)
            if not match or helper._is_empty(match[1]): missing.append(label)
        nombre_match = helper._extract_field(row, ("nombre_predio", "Nombre_Predio"), require_value=False)
        nombre_raw = nombre_match[1] if nombre_match else None
        if not missing and helper._is_empty(nombre_raw): continue
        ref = helper.get_relation_value(row, ("arb_predio_direccion", "arb_direccion_arb_predio_direccion_fkey", "predio", "arb_predio"))
        issues.append(RuleIssue(
            rule_id="1.40", object_ref=ref or helper.identify(row),
            message=("Si el tipo de dirección es Estructurada, clase_via_principal, valor_via_principal, "
                     "valor_via_generadora y numero_predio deben estar diligenciados y nombre_predio debe ser NULL."),
            details={"tabla": table_name, "class": table_name, "campo": tipo_match[0] if tipo_match else "tipo_direccion",
                     "tipo_direccion": tipo_raw, "faltantes": missing, "nombre_predio": nombre_raw,
                     "predio_ref": ref},
        ))
    return issues


def rule_2_16(dataset):
    helper = JuridicoHelper(dataset)
    issues: list[RuleIssue] = []
    for table_name, row in helper.iter_derecho_interesado_fuente():
        tipo_documento = helper.get_field_value(row, ("i_tipo_documento", "I_Tipo_Documento", "tipo_documento"))
        documento = helper.get_field_value(row, DOCUMENTO_IDENTIDAD_FIELDS)
        if str(tipo_documento or "").strip() == "NIT" and not _nit_es_valido(documento):
            issues.append(helper.make_issue(
                row, rule_id="2.16",
                message="El NIT debe cumplir la estructura de nueve dígitos, guion y un dígito de verificación; ser mayor a cero y no consecutivo.",
                details={"tabla": table_name, "tipo_documento": tipo_documento, "documento_identidad": documento},
            ))
    return issues


SOURCE_RULES = {"1.40": rule_1_40, "2.16": rule_2_16}
