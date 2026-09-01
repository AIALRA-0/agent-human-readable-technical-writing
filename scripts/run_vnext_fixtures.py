"""Execute and summarize the 236 deterministic vNext fixtures."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from validators.vnext_minimal import validate_fixture  # noqa: E402


DEFAULT_FIXTURES = [
    ROOT / "evals" / "deterministic" / "vnext-1.1-minimal-cases.jsonl",
    ROOT / "evals" / "deterministic" / "round-4-generalization-cases.jsonl",
    ROOT / "evals" / "deterministic" / "round-5-finalization-cases.jsonl",
]
EXPECTED_COUNTS = {
    "lifecycle_schema": 20,
    "terms_official_standalone": 40,
    "layout_lists_paragraphs": 20,
    "mermaid_caption_explanation": 16,
    "provenance_support_boundary": 20,
    "image_explanation": 16,
    "table_explanation": 16,
    "code_explanation": 16,
    "privacy_source_retention": 8,
    "presentation_spacing": 16,
    "term_meaning_contract": 8,
    "parallel_group_layout": 8,
    "github_render_evidence": 6,
    "code_coverage_mode": 6,
    "conversation_supersession": 4,
    "code_comment_alignment": 8,
    "content_sufficiency": 8,
}


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

    fixture_paths = [arguments.fixtures] if arguments.fixtures else DEFAULT_FIXTURES
    cases = [case for path in fixture_paths for case in load_cases(path)]
    case_ids = [case["case_id"] for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("fixture case identifiers must be unique across files")
    results, counts = run_cases(cases)
    mismatches = [result for result in results if not result["matched"]]
    count_errors = {
        category: {"expected": expected, "actual": counts.get(category, 0)}
        for category, expected in EXPECTED_COUNTS.items()
        if counts.get(category, 0) != expected
    }
    unexpected_categories = sorted(set(counts) - set(EXPECTED_COUNTS))
    passed = len(cases) == 236 and not mismatches and not count_errors and not unexpected_categories
    report = {
        "status": "PASS" if passed else "FAIL",
        "summary": {
            "total": len(cases),
            "matched": len(cases) - len(mismatches),
            "mismatched": len(mismatches),
            "category_counts": dict(sorted(counts.items())),
        },
        "reason": "every independently executed rule produced its reviewed pass or fail result" if passed else "one or more executable fixtures disagreed with the reviewed expectation or required count",
        "impact": "the vNext deterministic gate has executable positive and negative coverage for all seventeen active categories" if passed else "the deterministic gate cannot be used for candidate review until every mismatch is resolved",
        "next": "run lifecycle, contextual, and forward-candidate validation" if passed else "inspect the reported rule and repair only its validator or fixture",
        "count_errors": count_errors,
        "unexpected_categories": unexpected_categories,
        "mismatches": mismatches,
    }
    if arguments.report:
        arguments.report.parent.mkdir(parents=True, exist_ok=True)
        arguments.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
