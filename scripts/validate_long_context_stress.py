"""Validate public long-context evidence without reading private model bodies."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    cases = [json.loads(line) for line in (ROOT / "evals" / "long-context" / "vnext-1.1-8-cases.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    report = json.loads((ROOT / "evals" / "long-context" / "vnext-1.1-public-results.json").read_text(encoding="utf-8"))
    errors: list[str] = []
    if len(cases) != 8 or len({case["case_id"] for case in cases}) != 8:
        errors.append("stress declaration must contain eight unique cases")
    if any(not 1200 <= case["input_char_count"] <= 3000 for case in cases):
        errors.append("one stress input is outside 1200-3000 characters")
    results = report.get("results", [])
    if {case["case_id"] for case in cases} != {result.get("case_id") for result in results}:
        errors.append("stress declarations and public results differ")
    if report.get("total") != 8 or report.get("passed") != 8 or report.get("failed") != 0:
        errors.append("current stress evidence is not 8/8")
    if report.get("automated_checks_are_user_acceptance") is not False:
        errors.append("stress evidence must explicitly deny user-acceptance authority")
    if any(result.get("violations") or not result.get("passed") for result in results):
        errors.append("one current stress result still has violations")
    if any(len(result.get("body_sha256", "")) != 64 or len(result.get("event_sha256", "")) != 64 for result in results):
        errors.append("one public result lacks frozen body or event digest")
    if any(key in report for key in ("body", "stdout", "stderr", "prompt")):
        errors.append("public report contains a raw private field")
    history = report.get("evaluation_history", [])
    if not history or history[-1] != {"revision": 3, "passed": 8, "failed": 0, "status": "current"}:
        errors.append("evaluator correction history is incomplete")
    output = {"status": "PASS" if not errors else "FAIL", "cases": len(cases), "passed": report.get("passed"), "errors": errors, "scope": "release_evidence_not_user_acceptance"}
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
