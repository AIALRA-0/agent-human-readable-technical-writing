"""Validate one redacted clean-Agent format qualification report."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


SHA256 = re.compile(r"[0-9a-f]{64}")
FORBIDDEN_PUBLIC_KEYS = {
    "answer", "first_answer", "final_findings", "final_rejected_review_findings",
    "events", "thread_id", "worker_session_id", "prompt", "response_body",
}


def _walk_keys(value: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            keys.add(str(key))
            keys.update(_walk_keys(item))
    elif isinstance(value, list):
        for item in value:
            keys.update(_walk_keys(item))
    return keys


def validate_report(payload: dict[str, Any], *, require_complete: bool = True) -> list[str]:
    errors: list[str] = []
    results = payload.get("results")
    models = payload.get("models")
    if not isinstance(results, list) or not isinstance(models, list) or not models:
        return ["report must contain non-empty results and models arrays"]
    if payload.get("automated_result_is_user_acceptance") is not False:
        errors.append("automated results must not be marked as user acceptance")
    if payload.get("raw_answers_in_report") is not False:
        errors.append("redacted report must declare that raw answers are absent")
    if payload.get("trigger_measurement") != "declared_activation_proxy":
        errors.append("trigger measurement must be labeled declared_activation_proxy")
    if payload.get("host_skill_routing_verified") is not False:
        errors.append("declared activation cannot certify real host Skill routing")
    if payload.get("review_scope") != ["format", "explanation"]:
        errors.append("review_scope must record both format and explanation")
    leaked = sorted(FORBIDDEN_PUBLIC_KEYS & _walk_keys(payload))
    if leaked:
        errors.append("redacted report contains private keys: " + ", ".join(leaked))
    if payload.get("run_kind") == "qualification" and not payload.get("qualification_id"):
        errors.append("formal qualification is missing qualification_id")
    keys = [(item.get("case_id"), item.get("model")) for item in results if isinstance(item, dict)]
    if len(keys) != len(set(keys)):
        errors.append("case/model result keys are not unique")
    if any(model not in models for _, model in keys):
        errors.append("one or more result models are outside the declared model set")
    if payload.get("completed") != len(results):
        errors.append("completed count does not match result records")
    expected_total = payload.get("case_count", 0) * len(models)
    if require_complete and len(results) != expected_total:
        errors.append(f"qualification is incomplete: {len(results)}/{expected_total}")
    maximum_repairs = payload.get("max_repair_rounds")
    if type(maximum_repairs) is not int or not 1 <= maximum_repairs <= 2:
        errors.append("max_repair_rounds must be 1 or 2")
        maximum_repairs = 2
    for item in results:
        if not isinstance(item, dict):
            errors.append("result record is not an object")
            continue
        label = f"{item.get('case_id')}/{item.get('model')}"
        if item.get("trigger_access_violation_count") != 0:
            errors.append(f"{label}: trigger accessed data outside its clean boundary")
        expected = item.get("expected_trigger")
        if item.get("trigger_pass") is not True:
            errors.append(f"{label}: trigger result does not match expectation")
        if expected is True:
            if item.get("trigger_activated") is not True:
                errors.append(f"{label}: positive request did not declare Skill activation")
            if item.get("writing_status") != "PASS" or item.get("status") != "PASS":
                errors.append(f"{label}: positive writing closure did not pass")
            if item.get("access_violation_count") != 0:
                errors.append(f"{label}: writing chain accessed data outside its clean boundary")
            if not SHA256.fullmatch(str(item.get("first_draft_sha256", ""))):
                errors.append(f"{label}: first-draft digest is missing or invalid")
            if not SHA256.fullmatch(str(item.get("final_sha256", ""))):
                errors.append(f"{label}: final digest is missing or invalid")
            repair_rounds = item.get("repair_rounds")
            if not isinstance(repair_rounds, int) or repair_rounds < 0 or repair_rounds > maximum_repairs:
                errors.append(f"{label}: repair-round count is outside the configured bound")
        elif expected is False:
            if item.get("trigger_activated") is not False:
                errors.append(f"{label}: non-triggering control declared Skill activation")
            if item.get("writing_status") != "NOT_APPLICABLE" or item.get("status") != "PASS":
                errors.append(f"{label}: non-triggering control has not passed its actual output check")
            if item.get("negative_output_status") != "PASS" or item.get("negative_output_exact") is not True:
                errors.append(f"{label}: classification alone does not prove exact negative output")
            if item.get("negative_output_access_violation_count") != 0:
                errors.append(f"{label}: negative output accessed data outside its clean boundary")
            if not SHA256.fullmatch(str(item.get("negative_output_sha256", ""))):
                errors.append(f"{label}: negative output digest is missing or invalid")
        else:
            errors.append(f"{label}: expected_trigger is not boolean")
        attempts = item.get("host_attempts")
        if not isinstance(attempts, list) or not 1 <= len(attempts) <= 2:
            errors.append(f"{label}: host attempts must contain one or two immutable summaries")
    if payload.get("passed") != sum(isinstance(item, dict) and item.get("status") == "PASS" for item in results):
        errors.append("passed count does not match result records")
    if payload.get("failed") != sum(not isinstance(item, dict) or item.get("status") != "PASS" for item in results):
        errors.append("failed count does not match result records")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("--allow-incomplete", action="store_true")
    args = parser.parse_args()
    payload = json.loads(args.report.read_text(encoding="utf-8"))
    errors = validate_report(payload, require_complete=not args.allow_incomplete)
    print(json.dumps({
        "status": "PASS" if not errors else "FAIL",
        "completed": payload.get("completed"),
        "errors": errors,
    }, ensure_ascii=False))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
