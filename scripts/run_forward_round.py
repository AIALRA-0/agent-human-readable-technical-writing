"""Generate one unseen forward round exactly once in isolated Codex tasks."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ITEMS = ["SKILL.md", "constitution", "runtime", "contracts", "profiles", "registries", "validators", "patcher", "references"]
WRITE_LOCK = Lock()


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--round", type=int, required=True, dest="round_number")
    parser.add_argument("--auth", type=Path, required=True)
    parser.add_argument("--private-report", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True, help="external durable run directory; must be outside the repository")
    parser.add_argument("--model", default="gpt-5.6-sol")
    parser.add_argument("--reasoning-effort", default="medium")
    parser.add_argument("--codex", default="codex")
    parser.add_argument("--timeout-seconds", type=int, default=420)
    parser.add_argument("--workers", type=int, default=4)
    return parser.parse_args()


def install_candidate(codex_home: Path) -> None:
    destination = codex_home / "skills" / "human-readable-technical-writing"
    destination.mkdir(parents=True)
    for relative in RUNTIME_ITEMS:
        source = ROOT / relative
        if not source.exists():
            continue
        target = destination / relative
        shutil.copytree(source, target) if source.is_dir() else shutil.copy2(source, target)


def prompt_for(request: dict[str, Any]) -> str:
    payload = json.dumps(request, ensure_ascii=False, indent=2)
    return f"""Use the installed $human-readable-technical-writing skill to answer this single Chinese writing request.

This is an isolated first-attempt evaluation. You may inspect only the installed skill and the request/material below. Do not browse, search, inspect unrelated files, infer an expected answer, or score yourself. Generate the answer once.

After applying the skill, return exactly one JSON object and no Markdown fence. The object must have exactly these fields:
- answer: the complete user-facing answer string
- source_units: an array of SRCU-001 style identifiers covering every supplied semantic unit
- support_map: the same unique identifiers that are actually represented in the answer
- background_claims: an array of objects with claim and source_reference; use only supplied reference IDs, or an empty array

The answer itself must preserve required source components. If the source is an image, use its relative path in Markdown. If it is code or a table, preserve it. Do not expose this JSON wrapper inside answer.

REQUEST_AND_MATERIAL:
{payload}
"""


def parse_payload(body: str) -> dict[str, Any]:
    text = body.strip()
    match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    if match:
        text = match.group(1)
    value = json.loads(text)
    expected = {"answer", "source_units", "support_map", "background_claims"}
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError("final JSON fields differ from the isolated generator contract")
    if not isinstance(value["answer"], str) or not value["answer"].strip():
        raise ValueError("answer is empty")
    source_units = value["source_units"]
    support_map = value["support_map"]
    if not isinstance(source_units, list) or not source_units or not all(re.fullmatch(r"SRCU-[0-9]{3}", item or "") for item in source_units):
        raise ValueError("source_units are invalid")
    if len(source_units) != len(set(source_units)) or set(source_units) != set(support_map):
        raise ValueError("support_map must exactly cover unique source_units")
    if not isinstance(value["background_claims"], list):
        raise ValueError("background_claims is not an array")
    return value


def run_one(request: dict[str, Any], args: argparse.Namespace, run_root: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None]:
    case_id = request["case_id"]
    case_root = run_root / case_id
    codex_home = case_root / "home"
    task_root = case_root / "task"
    codex_home.mkdir(parents=True)
    task_root.mkdir(parents=True)
    shutil.copy2(args.auth, codex_home / "auth.json")
    install_candidate(codex_home)
    prompt = prompt_for(request)
    command = [args.codex, "-a", "never", "exec", "--ephemeral", "--json", "--skip-git-repo-check", "--model", args.model, "-c", f'model_reasoning_effort="{args.reasoning_effort}"', "-s", "danger-full-access", "-C", str(task_root), prompt]
    environment = os.environ.copy()
    environment["CODEX_HOME"] = str(codex_home)
    try:
        process = subprocess.run(command, text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=args.timeout_seconds, env=environment, check=False)
        stdout, stderr, exit_code = process.stdout, process.stderr, process.returncode
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout or ""
        stderr = (error.stderr or "") + "\nTIMEOUT"
        exit_code = 124
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
    error = None
    draft = None
    if exit_code != 0:
        error = f"Codex exit code {exit_code}"
    else:
        try:
            payload = parse_payload(body)
            draft = {"case_id": case_id, **payload}
        except (json.JSONDecodeError, ValueError, TypeError) as parse_error:
            error = str(parse_error)
    public = {
        "case_id": case_id, "model": args.model, "reasoning_effort": args.reasoning_effort,
        "generation_attempt": 1, "status": "frozen" if draft else "frozen_generation_failure",
        "answer_sha256": digest(draft["answer"]) if draft else None,
        "event_sha256": digest("\n".join(json.dumps(event, ensure_ascii=False, sort_keys=True) for event in events)),
        "error": error,
    }
    private = {"case_id": case_id, "exit_code": exit_code, "body": body, "stdout": stdout, "stderr": stderr, "error": error}
    result_root = run_root / "results"
    result_root.mkdir(parents=True, exist_ok=True)
    (result_root / f"{case_id}.json").write_text(
        json.dumps({"public": public, "private": private, "draft": draft}, ensure_ascii=False, indent=2),
        encoding="utf-8", newline="\n",
    )
    resolved_case = case_root.resolve()
    resolved_run = run_root.resolve()
    if resolved_run not in resolved_case.parents:
        raise RuntimeError("refusing to clean a task directory outside the external run root")
    shutil.rmtree(resolved_case)
    return public, private, draft


def persist(args: argparse.Namespace, directory: Path, requests: list[dict[str, Any]], public_by_id: dict[str, dict[str, Any]], private_by_id: dict[str, dict[str, Any]], drafts_by_id: dict[str, dict[str, Any]]) -> None:
    with WRITE_LOCK:
        ordered_ids = [item["case_id"] for item in requests]
        public = [public_by_id[case_id] for case_id in ordered_ids if case_id in public_by_id]
        private = [private_by_id[case_id] for case_id in ordered_ids if case_id in private_by_id]
        drafts = [drafts_by_id[case_id] for case_id in ordered_ids if case_id in drafts_by_id]
        args.private_report.parent.mkdir(parents=True, exist_ok=True)
        args.private_report.write_text(json.dumps({"round": args.round_number, "model": args.model, "cases": private}, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
        (directory / "generation-evidence.json").write_text(json.dumps({"round": args.round_number, "model": args.model, "reasoning_effort": args.reasoning_effort, "planned": len(requests), "completed": len(public), "successful": len(drafts), "results": public}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        (directory / "drafts.jsonl").write_text("".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in drafts), encoding="utf-8", newline="\n")


def main() -> int:
    raise SystemExit(
        "one-shot forward generation is disabled for vNext 1.1; use scripts/run_iterative_forward_matrix.py so every result completes isolated three-model closure"
    )
    args = parse_args()
    if args.round_number < 2 or args.workers < 1 or args.workers > 8:
        raise SystemExit("round must be >=2 and workers must be between 1 and 8")
    directory = ROOT / "evals" / "forward" / f"round-{args.round_number}"
    requests = [json.loads(line) for line in (directory / "requests.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(requests) != 20:
        raise SystemExit("expected exactly 20 requests")
    args.auth = args.auth.resolve()
    args.private_report = args.private_report.resolve()
    args.run_root = args.run_root.resolve()
    try:
        args.private_report.relative_to(ROOT.resolve())
    except ValueError:
        pass
    else:
        raise SystemExit("private report must be outside the repository")
    try:
        args.run_root.relative_to(ROOT.resolve())
    except ValueError:
        pass
    else:
        raise SystemExit("run root must be outside the repository")
    if not args.auth.is_file():
        raise SystemExit("auth file is missing")
    generated_paths = [directory / "drafts.jsonl", directory / "generation-evidence.json"]
    if any(path.exists() for path in generated_paths) or args.private_report.exists():
        raise SystemExit("round already has generation evidence; first attempts cannot be regenerated")
    if args.run_root.exists() and any(args.run_root.iterdir()):
        raise SystemExit("external run root must be new or empty")
    args.run_root.mkdir(parents=True, exist_ok=True)
    public_by_id: dict[str, dict[str, Any]] = {}
    private_by_id: dict[str, dict[str, Any]] = {}
    drafts_by_id: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(run_one, request, args, args.run_root): request["case_id"] for request in requests}
        for future in as_completed(futures):
            case_id = futures[future]
            public, private, draft = future.result()
            public_by_id[case_id] = public
            private_by_id[case_id] = private
            if draft:
                drafts_by_id[case_id] = draft
            persist(args, directory, requests, public_by_id, private_by_id, drafts_by_id)
            print(json.dumps({"completed": len(public_by_id), "total": 20, "case_id": case_id, "status": public["status"]}, ensure_ascii=False), flush=True)
    failed = [record for record in public_by_id.values() if record["status"] != "frozen"]
    print(json.dumps({"status": "PASS" if not failed else "FAIL", "round": args.round_number, "frozen": len(drafts_by_id), "generation_failures": len(failed)}, ensure_ascii=False))
    return 0 if not failed and len(drafts_by_id) == 20 else 1


if __name__ == "__main__":
    sys.exit(main())
