"""Motor activo de reglas SINIC para la validacion web."""
from .registry import RULE_FUNCTIONS, run_rules

__all__ = ["RULE_FUNCTIONS", "run_rules"]
