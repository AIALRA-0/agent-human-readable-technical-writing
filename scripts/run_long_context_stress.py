"""Run eight isolated long-context stress cases with private raw bodies."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from run_vnext_trigger_matrix import digest, install_candidate, validate_inline_alignment


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = ROOT / "evals" / "long-context" / "vnext-1.1-8-cases.jsonl"
DEFAULT_PUBLIC = ROOT / "evals" / "long-context" / "vnext-1.1-public-results.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--auth", type=Path, required=True)
    parser.add_argument("--private-report", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--public-report", type=Path, default=DEFAULT_PUBLIC)
    parser.add_argument("--model", default="gpt-5.6-sol")
    parser.add_argument("--reasoning-effort", default="medium")
    parser.add_argument("--codex", default="codex")
    parser.add_argument("--timeout-seconds", type=int, default=600)
    parser.add_argument("--workers", type=int, default=2)
    return parser.parse_args()


def run_case(case: dict[str, Any], args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    case_root = args.run_root / case["case_id"]
    codex_home = case_root / "home"
    task_root = case_root / "task"
    codex_home.mkdir(parents=True)
    task_root.mkdir(parents=True)
    shutil.copy2(args.auth, codex_home / "auth.json")
    install_candidate(ROOT, codex_home)
    command = [args.codex, "-a", "never", "exec", "--ephemeral", "--json", "--skip-git-repo-check", "--model", args.model, "-c", f'model_reasoning_effort="{args.reasoning_effort}"', "-s", "danger-full-access", "-C", str(task_root), case["prompt"]]
    environment = os.environ.copy()
    environment["CODEX_HOME"] = str(codex_home)
    try:
        process = subprocess.run(command, text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=args.timeout_seconds, env=environment, check=False)
        stdout, stderr, exit_code = process.stdout, process.stderr, process.returncode
    except subprocess.TimeoutExpired as error:
        stdout, stderr, exit_code = error.stdout or "", (error.stderr or "") + "\nTIMEOUT", 124
    events = []
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    messages = [event for event in events if event.get("type") == "item.completed" and isinstance(event.get("item"), dict) and event["item"].get("type") == "agent_message"]
    body = str(messages[-1]["item"].get("text", "")) if messages else ""
    violations = [] if exit_code == 0 else [f"Codex exit code {exit_code}"]
    for pattern in case["required_patterns"]:
        if re.search(pattern, body, re.IGNORECASE | re.MULTILINE) is None:
            violations.append(f"required pattern missing: {pattern}")
    for pattern in case["forbidden_patterns"]:
        if re.search(pattern, body, re.IGNORECASE | re.MULTILINE) is not None:
            violations.append(f"forbidden pattern present: {pattern}")
    prose = re.sub(r"```.*?```", "", body, flags=re.DOTALL)
    if "。" in prose:
        violations.append("Lucas profile violation: Chinese full stop in generated prose")
    commands = "\n".join(str(event.get("item", {}).get("command", "")) for event in events if isinstance(event.get("item"), dict) and event["item"].get("type") == "command_execution")
    helper = "runtime/align_inline_comments.py" in commands.replace("\\\\", "/").replace("\\", "/").lower()
    if case["case_id"] == "LONG-007":
        violations.extend(validate_inline_alignment(body))
        if not helper:
            violations.append("deterministic alignment helper was not invoked")
    public = {"case_id": case["case_id"], "dimension": case["dimension"], "input_char_count": case["input_char_count"], "model": args.model, "passed": not violations, "violations": violations, "body_sha256": digest(body), "event_sha256": digest("\n".join(json.dumps(event, ensure_ascii=False, sort_keys=True) for event in events)), "alignment_helper_invoked": helper}
    private = {"case_id": case["case_id"], "exit_code": exit_code, "body": body, "stdout": stdout, "stderr": stderr}
    result_root = args.run_root / "results"
    result_root.mkdir(parents=True, exist_ok=True)
    (result_root / f"{case['case_id']}.json").write_text(json.dumps({"public": public, "private": private}, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    resolved_case, resolved_run = case_root.resolve(), args.run_root.resolve()
    if resolved_run not in resolved_case.parents:
        raise RuntimeError("refusing to clean outside external run root")
    shutil.rmtree(resolved_case)
    return public, private


def persist(args: argparse.Namespace, cases: list[dict[str, Any]], public_by_id: dict[str, dict[str, Any]], private_by_id: dict[str, dict[str, Any]]) -> None:
    order = [case["case_id"] for case in cases]
    public = [public_by_id[item] for item in order if item in public_by_id]
    private = [private_by_id[item] for item in order if item in private_by_id]
    args.private_report.parent.mkdir(parents=True, exist_ok=True)
    args.public_report.parent.mkdir(parents=True, exist_ok=True)
    args.private_report.write_text(json.dumps({"model": args.model, "cases": private}, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    payload = {"matrix_version": "vnext-1.1-long-context-8", "model": args.model, "raw_bodies_location": "local_private_report", "planned_total": 8, "total": len(public), "passed": sum(item["passed"] for item in public), "failed": sum(not item["passed"] for item in public), "automated_checks_are_user_acceptance": False, "results": public}
    args.public_report.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def main() -> int:
    args = parse_args()
    for name in ("auth", "private_report", "run_root", "cases", "public_report"):
        setattr(args, name, getattr(args, name).resolve())
    for path, label in ((args.private_report, "private report"), (args.run_root, "run root")):
        try:
            path.relative_to(ROOT.resolve())
        except ValueError:
            pass
        else:
            raise SystemExit(f"{label} must be outside the repository")
    if args.private_report.exists() or args.public_report.exists() or (args.run_root.exists() and any(args.run_root.iterdir())):
        raise SystemExit("stress evidence already exists; cases cannot be regenerated")
    args.run_root.mkdir(parents=True, exist_ok=True)
    cases = [json.loads(line) for line in args.cases.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(cases) != 8 or any(not 1200 <= case["input_char_count"] <= 3000 for case in cases):
        raise SystemExit("expected eight 1200-3000 character cases")
    public_by_id: dict[str, dict[str, Any]] = {}
    private_by_id: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(run_case, case, args): case["case_id"] for case in cases}
        for future in as_completed(futures):
            case_id = futures[future]
            public, private = future.result()
            public_by_id[case_id], private_by_id[case_id] = public, private
            persist(args, cases, public_by_id, private_by_id)
            print(json.dumps({"completed": len(public_by_id), "total": 8, "case_id": case_id, "passed": public["passed"]}, ensure_ascii=False), flush=True)
    failed = sum(not item["passed"] for item in public_by_id.values())
    print(json.dumps({"status": "PASS" if failed == 0 else "FAIL", "total": 8, "passed": 8 - failed, "failed": failed}, ensure_ascii=False))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
