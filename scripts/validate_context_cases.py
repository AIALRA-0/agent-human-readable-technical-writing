"""Validate every inventoried context fixture while preserving the semantic boundary."""

from __future__ import annotations

import json
import hashlib
import sys
from collections import Counter
from pathlib import Path

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
CASE_ROOT = ROOT / "evals" / "contextual"
INVENTORY = CASE_ROOT / "inventory.json"
SCHEMA = ROOT / "contracts" / "context-case.schema.json"


def main() -> int:
    """Check contract completeness, distribution, and the semantic-boundary declaration."""

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    inventory = json.loads(INVENTORY.read_text(encoding="utf-8"))
    paths = [CASE_ROOT / item["path"] for item in inventory["files"]]
    cases = [json.loads(line) for path in paths for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    errors: list[str] = []
    actual_files = {path.name for path in CASE_ROOT.glob("*.jsonl")}
    declared_files = {path.name for path in paths}
    if actual_files != declared_files:
        errors.append(f"context file set differs: declared={sorted(declared_files)} actual={sorted(actual_files)}")
    for item, path in zip(inventory["files"], paths):
        if hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
            errors.append(f"{path.name}: SHA-256 differs from inventory")
    identifiers = [case.get("case_id") for case in cases]
    if len(cases) != inventory["total_rows"]:
        errors.append(f"expected {inventory['total_rows']} inventoried cases, found {len(cases)}")
    if len(identifiers) != len(set(identifiers)):
        errors.append("context case identifiers are not unique")
    counts = Counter(case.get("dimension") for case in cases)
    if dict(sorted(counts.items())) != inventory["distribution"]:
        errors.append(f"dimension counts differ: {dict(sorted(counts.items()))}")
    for case in cases:
        schema_errors = list(validator.iter_errors(case))
        if schema_errors:
            errors.append(f"{case.get('case_id')}: {schema_errors[0].message}")
        expected_automatic = case.get("case_id") in {"CTX-R2-013", "CTX-R2-014", "CTX-R2-015"}
        if case.get("automatic_decision") is not expected_automatic:
            errors.append(f"{case.get('case_id')}: automatic-decision boundary differs from the reviewed context")
        if case.get("case_id") == "CTX-R2-016" and case.get("expected_disposition") != "review_required":
            errors.append("CTX-R2-016: unknown official casing must require review")
        if case.get("case_id") == "CTX-R4-004" and case.get("expected_disposition") != "review_required":
            errors.append("CTX-R4-004: unknown professional-term form must require review")
    status = "PASS" if not errors else "FAIL"
    report = {
        "status": status,
        "results": {"cases": len(cases), "contract_valid": len(cases) - len(errors), "dimension_counts": dict(counts)},
        "reason": f"{len(cases)} 个语境案例具有完整结构，机器形式与语义复核边界已分别登记" if not errors else "语境案例的结构或职责边界存在错误",
        "impact": "检查器能够区分已登记大小写、原文豁免和未知官方写法，不会把未登记名称当成确定答案" if not errors else "当前语境集合不能用于回归校准",
        "next": "在真实生成中使用这些案例检查泛化表现" if not errors else "修复列出的结构错误后重试",
        "errors": errors,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
