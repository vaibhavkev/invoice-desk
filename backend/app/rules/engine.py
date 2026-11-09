"""Rules engine: evaluate R1-R10 and collect failures and warnings (SPEC 4.6)."""
from __future__ import annotations

from typing import Any, Dict, List

from .rules import RULES, RuleContext


def evaluate(ctx: RuleContext) -> Dict[str, Any]:
    results: List[Dict[str, Any]] = []
    for rule in RULES:
        results.append(rule(ctx))
    failed_hold = [r["code"] for r in results if r["passed"] is False and r["severity"] == "HOLD"]
    failed_reject = [r["code"] for r in results if r["passed"] is False and r["severity"] == "REJECT"]
    warnings = [f"{r['code']}: {w}" for r in results for w in r.get("warnings") or []]
    return {"results": results, "failed_hold": failed_hold, "failed_reject": failed_reject, "warnings": warnings}


def aggregate(rules_output: Dict[str, Any]) -> str:
    """Any REJECT failure -> REJECT; else any HOLD failure -> HOLD; else APPROVE. Warnings never count."""
    if rules_output["failed_reject"]:
        return "REJECT"
    if rules_output["failed_hold"]:
        return "HOLD"
    return "APPROVE"
