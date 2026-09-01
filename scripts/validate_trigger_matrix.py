"""Validate the 72-case design and optional redacted execution evidence."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "evals" / "trigger-matrix" / "vnext-1.1-72-cases.jsonl"
PUBLIC_RESULTS = ROOT / "evals" / "trigger-matrix" / "vnext-1.1-public-results.json"


def validate_public_results(cases: list[dict], errors: list[str]) -> dict[str, object] | None:
    """Require 72 redacted passing summaries without raw prompts or bodies."""

    if not PUBLIC_RESULTS.exists():
        return None
    report = json.loads(PUBLIC_RESULTS.read_text(encoding="utf-8"))
    expected_top = {"matrix_version", "model", "raw_bodies_location", "planned_total", "total", "passed", "failed", "results"}
    if set(report) != expected_top:
        errors.append("public result top-level fields differ from the redacted contract")
    if report.get("matrix_version") != "vnext-1.1-round-5" or report.get("model") != "gpt-5.6-sol":
        errors.append("matrix or fixed model version differs")
    if report.get("raw_bodies_location") != "local_private_report":
        errors.append("raw-body location boundary differs")
    results = report.get("results", [])
    if (report.get("planned_total"), report.get("total"), report.get("passed"), report.get("failed"), len(results)) != (72, 72, 72, 0, 72):
        errors.append("public result counts must be planned 72, total 72, passed 72, failed 0")
    case_by_id = {case["case_id"]: case for case in cases}
    result_ids = [result.get("case_id") for result in results]
    if len(set(result_ids)) != len(result_ids) or set(result_ids) != set(case_by_id):
        errors.append("public result identifiers differ from the 72-case manifest")
    expected_result_fields = {
        "case_id", "family", "expectation", "model", "activated", "expected_activation",
        "alignment_helper_invoked", "passed", "violations", "body_sha256", "event_sha256", "event_count",
    }
    for result in results:
        case = case_by_id.get(result.get("case_id"))
        if case is None:
            continue
        if set(result) != expected_result_fields:
            errors.append(f"{result.get('case_id')}: public summary fields differ")
        if result.get("family") != case["family"] or result.get("expectation") != case["expectation"]:
            errors.append(f"{case['case_id']}: public family or expectation differs")
        if result.get("model") != report.get("model"):
            errors.append(f"{case['case_id']}: per-case model differs")
        if result.get("activated") is not case["expected_activation"] or result.get("expected_activation") is not case["expected_activation"]:
            errors.append(f"{case['case_id']}: activation result differs from expectation")
        if result.get("passed") is not True or result.get("violations") != []:
            errors.append(f"{case['case_id']}: execution did not pass cleanly")
        if not re.fullmatch(r"[a-f0-9]{64}", str(result.get("body_sha256", ""))) or not re.fullmatch(r"[a-f0-9]{64}", str(result.get("event_sha256", ""))):
            errors.append(f"{case['case_id']}: body or event digest is invalid")
        if not isinstance(result.get("event_count"), int) or result["event_count"] < 1:
            errors.append(f"{case['case_id']}: event summary is empty")
        if case["evaluator"]["kind"] == "inline_alignment" and result.get("alignment_helper_invoked") is not True:
            errors.append(f"{case['case_id']}: deterministic alignment helper evidence is missing")
    serialized = json.dumps(report, ensure_ascii=False)
    if re.search(r'"(?:body|stdout|stderr|prompt)"\s*:', serialized):
        errors.append("public report contains a raw prompt, body, stdout, or stderr field")
    if re.search(r"[A-Za-z]:\\Users\\|\.codex[/\\]sessions", serialized, re.IGNORECASE):
        errors.append("public report contains a personal path or session location")
    return report


def main() -> int:
    """Check schema, identifiers, and the exact 3 x 4 x 6 design."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--require-results", action="store_true")
    args = parser.parse_args()
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
    public_report = validate_public_results(cases, errors)
    if args.require_results and public_report is None:
        errors.append("public execution result is required but missing")
    status = "PASS" if not errors else "FAIL"
    execution_status = "PASS 72/72" if public_report is not None and not errors else "not_evidence; use run_vnext_trigger_matrix.py for real isolated tasks"
    print(json.dumps({"status": status, "cases": len(cases), "groups": {f"{key[0]}/{key[1]}": value for key, value in sorted(counts.items())}, "failures": errors, "execution_status": execution_status}, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
