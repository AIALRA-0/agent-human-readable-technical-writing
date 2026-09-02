"""Execute every inventoried deterministic vNext fixture."""

from __future__ import annotations

import argparse
import json
import hashlib
import sys
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from validators.vnext_minimal import validate_fixture  # noqa: E402


INVENTORY = ROOT / "evals" / "deterministic" / "inventory.json"


def load_cases(path: Path) -> list[dict[str, Any]]:
    """Load non-empty JSONL lines and reject duplicate case identifiers."""

    cases = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    case_ids = [case.get("case_id") for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("fixture case identifiers must be unique")
    return cases


def run_cases(cases: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], Counter[str]]:
    """Run every fixture and compare actual status with its reviewed expectation."""

    results: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for case in cases:
        category = case["category"]
        findings = validate_fixture(category, case["rule_id"], case["payload"])
        actual = "PASS" if not findings else "FAIL"
        matched = actual == case["expected"]
        counts[category] += 1
        results.append(
            {
                "case_id": case["case_id"],
                "category": category,
                "rule_id": case["rule_id"],
                "expected": case["expected"],
                "actual": actual,
                "matched": matched,
                "findings": findings,
            }
        )
    return results, counts


def main() -> int:
    """Execute fixtures and emit a machine-readable result with causal fields."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--fixtures", type=Path)
    parser.add_argument("--report", type=Path)
    arguments = parser.parse_args()

    inventory_errors: list[str] = []
    inventory: dict[str, Any] | None = None
    if arguments.fixtures:
        fixture_paths = [arguments.fixtures]
    else:
        inventory = json.loads(INVENTORY.read_text(encoding="utf-8"))
        fixture_paths = [INVENTORY.parent / item["path"] for item in inventory["files"]]
        actual_files = {path.name for path in INVENTORY.parent.glob("*.jsonl")}
        declared_files = {path.name for path in fixture_paths}
        if actual_files != declared_files:
            inventory_errors.append(f"fixture file set differs: declared={sorted(declared_files)} actual={sorted(actual_files)}")
        for item, path in zip(inventory["files"], fixture_paths):
            actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual_hash != item["sha256"]:
                inventory_errors.append(f"{path.name}: SHA-256 differs from inventory")
    cases = [case for path in fixture_paths for case in load_cases(path)]
    case_ids = [case["case_id"] for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("fixture case identifiers must be unique across files")
    results, counts = run_cases(cases)
    mismatches = [result for result in results if not result["matched"]]
    count_errors: dict[str, Any] = {}
    if inventory is not None:
        if len(cases) != inventory["total_rows"]:
            count_errors["total_rows"] = {"expected": inventory["total_rows"], "actual": len(cases)}
        if dict(sorted(counts.items())) != inventory["distribution"]:
            count_errors["distribution"] = {"expected": inventory["distribution"], "actual": dict(sorted(counts.items()))}
    passed = not mismatches and not count_errors and not inventory_errors
    report = {
        "status": "PASS" if passed else "FAIL",
        "summary": {
            "total": len(cases),
            "matched": len(cases) - len(mismatches),
            "mismatched": len(mismatches),
            "category_counts": dict(sorted(counts.items())),
        },
        "reason": "every inventoried rule produced its reviewed pass or fail result" if passed else "one or more executable fixtures disagreed with its expectation or committed inventory",
        "impact": f"the deterministic gate has executable coverage for {len(counts)} active categories" if passed else "the deterministic gate cannot be used for candidate review until every mismatch is resolved",
        "next": "run lifecycle, contextual, and forward-candidate validation" if passed else "inspect the reported rule and repair only its validator or fixture",
        "count_errors": count_errors,
        "inventory_errors": inventory_errors,
        "mismatches": mismatches,
    }
    if arguments.report:
        arguments.report.parent.mkdir(parents=True, exist_ok=True)
        arguments.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
