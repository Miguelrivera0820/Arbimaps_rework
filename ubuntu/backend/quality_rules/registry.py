"""Compatibility facade for the active SINIC registry."""
from .sinic_web.registry import RULE_FUNCTIONS, run_rules

__all__ = ["RULE_FUNCTIONS", "run_rules"]
