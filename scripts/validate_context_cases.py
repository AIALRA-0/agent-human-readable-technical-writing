"""Validate the 12 context fixtures without pretending to automate semantic judgment."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "evals" / "contextual" / "round-2-context-cases.jsonl"
SCHEMA = ROOT / "contracts" / "context-case.schema.json"
EXPECTED = {"actor_clarity": 4, "punctuation_choice": 4, "local_consistency": 2, "paragraph_boundary": 2}


def main() -> int:
    """Check contract completeness, distribution, and the semantic-boundary declaration."""

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    cases = [json.loads(line) for line in CASES.read_text(encoding="utf-8").splitlines() if line.strip()]
    errors: list[str] = []
    identifiers = [case.get("case_id") for case in cases]
    if len(cases) != 12:
        errors.append(f"expected 12 cases, found {len(cases)}")
    if len(identifiers) != len(set(identifiers)):
        errors.append("context case identifiers are not unique")
    counts = Counter(case.get("dimension") for case in cases)
    if dict(counts) != EXPECTED:
        errors.append(f"dimension counts differ: {dict(counts)}")
    for case in cases:
        schema_errors = list(validator.iter_errors(case))
        if schema_errors:
            errors.append(f"{case.get('case_id')}: {schema_errors[0].message}")
        if case.get("automatic_decision") is not False:
            errors.append(f"{case.get('case_id')}: semantic disposition must not be automatic")
    status = "PASS" if not errors else "FAIL"
    report = {
        "status": status,
        "results": {"cases": len(cases), "contract_valid": len(cases) - len(errors), "dimension_counts": dict(counts)},
        "reason": "12 个语境案例具有完整结构，并明确禁止自动决定语义结果" if not errors else "语境案例的结构或职责边界存在错误",
        "impact": "这些案例可以校准 Agent 判断，但不能冒充确定性硬门" if not errors else "当前语境集合不能用于回归校准",
        "next": "在真实生成中使用这些案例检查泛化表现" if not errors else "修复列出的结构错误后重试",
        "errors": errors,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
