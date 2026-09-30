"""Public quality-rules API.

Only the SINIC engine is active in web validation. Historical/legacy rule modules are
kept on disk for reference, but are not imported or executed here.
"""
from .sinic_web.registry import RULE_FUNCTIONS, run_rules

__all__ = ["RULE_FUNCTIONS", "run_rules"]
