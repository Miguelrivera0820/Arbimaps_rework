from __future__ import annotations

from .general import codigos_funciones as general_rules
from .physical import codigos_funciones as physical_rules
from .legal import codigos_funciones as legal_rules
from .economic import codigos_funciones as economic_rules

RULE_FUNCTIONS: dict[str, object] = {}
for block in (general_rules, physical_rules, legal_rules, economic_rules):
    RULE_FUNCTIONS.update(block)


def run_rules(layers, rule_ids=None):
    selection = list(rule_ids) if rule_ids is not None else list(RULE_FUNCTIONS)
    results = {}
    for rule_id in selection:
        fn = RULE_FUNCTIONS.get(str(rule_id))
        if not callable(fn): continue
        try: results[str(rule_id)] = fn(layer_dict=layers)
        except Exception as exc:
            results[str(rule_id)] = {"cumple": False, "errores": [], "mensaje": f"Error ejecutando {rule_id}: {exc}", "error_ejecucion": str(exc)}
    return results
