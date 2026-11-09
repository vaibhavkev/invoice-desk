"""Stage 6 - policy rules (SPEC 4.6)."""
from __future__ import annotations

from ...rules.engine import evaluate
from ...rules.rules import RuleContext
from ..types import StageResult


def run_rules(ctx: RuleContext) -> StageResult:
    out = evaluate(ctx)
    res = out["results"]
    passed = [r for r in res if r["passed"] is True]
    failed = [r for r in res if r["passed"] is False]
    skipped = [r for r in res if r["passed"] is None]
    warned = [r for r in passed if r["warnings"]]
    if not failed:
        summary = f"All {len(passed)} applicable rules passed"
        summary += f" ({len(warned)} with a warning)." if warned else "."
    else:
        parts = []
        if out["failed_reject"]:
            parts.append(f"{', '.join(out['failed_reject'])} failed with REJECT severity")
        if out["failed_hold"]:
            parts.append(f"{', '.join(out['failed_hold'])} failed with HOLD severity")
        summary = f"{len(passed)} of {len(res)} rules passed; " + " and ".join(parts) + "."
    if skipped:
        summary += f" {len(skipped)} not applicable ({', '.join(r['code'] for r in skipped)})."
    status = "warn" if failed or warned else "done"
    return StageResult(summary=summary, output=out, status=status, warnings=list(out["warnings"]))
