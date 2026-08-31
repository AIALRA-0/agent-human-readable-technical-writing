"""Validate 16 context fixtures while preserving the deterministic or semantic boundary."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "evals" / "contextual" / "round-2-context-cases.jsonl"
SCHEMA = ROOT / "contracts" / "context-case.schema.json"
EXPECTED = {"actor_clarity": 4, "punctuation_choice": 4, "local_consistency": 2, "paragraph_boundary": 2, "parenthetical_case": 4}


def main() -> int:
    """Check contract completeness, distribution, and the semantic-boundary declaration."""

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    cases = [json.loads(line) for line in CASES.read_text(encoding="utf-8").splitlines() if line.strip()]
    errors: list[str] = []
    identifiers = [case.get("case_id") for case in cases]
    if len(cases) != 16:
        errors.append(f"expected 16 cases, found {len(cases)}")
    if len(identifiers) != len(set(identifiers)):
        errors.append("context case identifiers are not unique")
    counts = Counter(case.get("dimension") for case in cases)
    if dict(counts) != EXPECTED:
        errors.append(f"dimension counts differ: {dict(counts)}")
    for case in cases:
        schema_errors = list(validator.iter_errors(case))
        if schema_errors:
            errors.append(f"{case.get('case_id')}: {schema_errors[0].message}")
        expected_automatic = case.get("case_id") in {"CTX-R2-013", "CTX-R2-014", "CTX-R2-015"}
        if case.get("automatic_decision") is not expected_automatic:
            errors.append(f"{case.get('case_id')}: automatic-decision boundary differs from the reviewed context")
        if case.get("case_id") == "CTX-R2-016" and case.get("expected_disposition") != "review_required":
            errors.append("CTX-R2-016: unknown official casing must require review")
    status = "PASS" if not errors else "FAIL"
    report = {
        "status": status,
        "results": {"cases": len(cases), "contract_valid": len(cases) - len(errors), "dimension_counts": dict(counts)},
        "reason": "16 个语境案例具有完整结构；三个已登记大小写场景允许确定性判断，其他语义问题继续保留给 Agent 或用户" if not errors else "语境案例的结构或职责边界存在错误",
        "impact": "检查器能够区分已登记大小写、原文豁免和未知官方写法，不会把未登记名称当成确定答案" if not errors else "当前语境集合不能用于回归校准",
        "next": "在真实生成中使用这些案例检查泛化表现" if not errors else "修复列出的结构错误后重试",
        "errors": errors,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
