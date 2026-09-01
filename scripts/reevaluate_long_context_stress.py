"""Re-evaluate frozen stress bodies after correcting deterministic regexes."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from run_vnext_trigger_matrix import digest, validate_inline_alignment


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--private-report", type=Path, required=True)
    args = parser.parse_args()
    private_path = args.private_report.resolve()
    try:
        private_path.relative_to(ROOT.resolve())
    except ValueError:
        pass
    else:
        raise SystemExit("private report must be outside the repository")
    cases = [json.loads(line) for line in (ROOT / "evals" / "long-context" / "vnext-1.1-8-cases.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    private = {item["case_id"]: item for item in json.loads(private_path.read_text(encoding="utf-8"))["cases"]}
    public_path = ROOT / "evals" / "long-context" / "vnext-1.1-public-results.json"
    prior = json.loads(public_path.read_text(encoding="utf-8"))
    prior_by_id = {item["case_id"]: item for item in prior["results"]}
    results = []
    for case in cases:
        saved = private[case["case_id"]]
        body = saved["body"]
        violations = [] if saved["exit_code"] == 0 else [f"Codex exit code {saved['exit_code']}"]
        violations.extend(f"required pattern missing: {pattern}" for pattern in case["required_patterns"] if re.search(pattern, body, re.IGNORECASE | re.MULTILINE) is None)
        violations.extend(f"forbidden pattern present: {pattern}" for pattern in case["forbidden_patterns"] if re.search(pattern, body, re.IGNORECASE | re.MULTILINE) is not None)
        prose = re.sub(r"```.*?```", "", body, flags=re.DOTALL)
        if "。" in prose:
            violations.append("Lucas profile violation: Chinese full stop in generated prose")
        events = []
        for line in saved["stdout"].splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                events.append(event)
        commands = "\n".join(str(event.get("item", {}).get("command", "")) for event in events if isinstance(event.get("item"), dict) and event["item"].get("type") == "command_execution")
        helper = "runtime/align_inline_comments.py" in commands.replace("\\\\", "/").replace("\\", "/").lower()
        if case["case_id"] == "LONG-007":
            violations.extend(validate_inline_alignment(body))
            if not helper:
                violations.append("deterministic alignment helper was not invoked")
        results.append({"case_id": case["case_id"], "dimension": case["dimension"], "input_char_count": case["input_char_count"], "model": prior["model"], "passed": not violations, "violations": violations, "body_sha256": digest(body), "event_sha256": prior_by_id[case["case_id"]]["event_sha256"], "alignment_helper_invoked": helper})
    history = list(prior.get("evaluation_history", [{"revision": 1, "passed": prior["passed"], "failed": prior["failed"], "status": "superseded_false_positive_regexes"}]))
    for item in history:
        if item["status"] == "current":
            item["status"] = "superseded_windows_path_normalization"
    current_passed = sum(item["passed"] for item in results)
    history.append({"revision": max(item["revision"] for item in history) + 1, "passed": current_passed, "failed": 8 - current_passed, "status": "current"})
    payload = {"matrix_version": prior["matrix_version"], "model": prior["model"], "raw_bodies_location": "local_private_report", "planned_total": 8, "total": 8, "passed": current_passed, "failed": 8 - current_passed, "automated_checks_are_user_acceptance": False, "evaluation_history": history, "results": results}
    public_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"status": "PASS" if payload["failed"] == 0 else "FAIL", "passed": payload["passed"], "failed": payload["failed"], "model_reruns": 0}, ensure_ascii=False))
    return 0 if payload["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
