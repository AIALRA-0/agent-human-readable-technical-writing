"""Validate the public 72-case trigger matrix without claiming execution."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "evals" / "trigger-matrix" / "vnext-1.1-72-cases.jsonl"


def main() -> int:
    """Check schema, identifiers, and the exact 3 x 4 x 6 design."""

    schema = json.loads((ROOT / "contracts" / "trigger-matrix-case.schema.json").read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    cases = [json.loads(line) for line in CASES.read_text(encoding="utf-8").splitlines() if line.strip()]
    errors: list[str] = []
    if len(cases) != 72:
        errors.append(f"expected 72 cases, found {len(cases)}")
    ids = [case.get("case_id") for case in cases]
    if len(set(ids)) != len(ids):
        errors.append("case identifiers are not unique")
    counts = Counter((case.get("family"), case.get("expectation")) for case in cases)
    families = {"code_explanation", "explanatory_translation", "status_audit"}
    expectations = {"explicit_trigger", "implicit_trigger", "negative_no_trigger", "rule_adherence"}
    for family in families:
        for expectation in expectations:
            if counts[(family, expectation)] != 6:
                errors.append(f"{family}/{expectation}: expected 6, found {counts[(family, expectation)]}")
    for case in cases:
        case_errors = list(validator.iter_errors(case))
        if case_errors:
            errors.append(f"{case.get('case_id', '<missing>')}: {case_errors[0].message}")
        expected_activation = case.get("expectation") != "negative_no_trigger"
        if case.get("expected_activation") is not expected_activation:
            errors.append(f"{case.get('case_id')}: activation expectation contradicts class")
    status = "PASS" if not errors else "FAIL"
    print(json.dumps({"status": status, "cases": len(cases), "groups": {f"{key[0]}/{key[1]}": value for key, value in sorted(counts.items())}, "failures": errors, "execution_status": "not_evidence; use run_vnext_trigger_matrix.py for real isolated tasks"}, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
