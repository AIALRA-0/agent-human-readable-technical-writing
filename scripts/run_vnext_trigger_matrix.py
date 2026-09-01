"""Run 72 isolated Codex tasks and separate private bodies from public evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = ROOT / "evals" / "trigger-matrix" / "vnext-1.1-72-cases.jsonl"
DEFAULT_PUBLIC_REPORT = ROOT / "evals" / "trigger-matrix" / "vnext-1.1-public-results.json"
RUNTIME_ITEMS = ["SKILL.md", "constitution", "runtime", "contracts", "profiles", "registries", "validators", "patcher", "references"]


def digest(text: str) -> str:
    """Return a lowercase SHA-256 digest for one text value."""

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_args() -> argparse.Namespace:
    """Read explicit paths so raw outputs cannot silently enter the repository."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--skill-root", type=Path, default=ROOT)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--auth", type=Path, required=True)
    parser.add_argument("--private-report", type=Path, required=True)
    parser.add_argument("--public-report", type=Path, default=DEFAULT_PUBLIC_REPORT)
    parser.add_argument("--model", default="gpt-5.6-sol")
    parser.add_argument("--reasoning-effort", default="medium")
    parser.add_argument("--codex", default="codex")
    parser.add_argument("--timeout-seconds", type=int, default=240)
    return parser.parse_args()


def display_width(text: str) -> int:
    """Measure columns with four-column tab stops."""

    column = 0
    for character in text:
        column = column + (4 - column % 4) if character == "\t" else column + 1
    return column


def pattern_findings(body: str, required: list[str], forbidden: list[str]) -> list[str]:
    """Apply declared case-insensitive public regex checks."""

    findings = [f"required pattern missing: {pattern}" for pattern in required if re.search(pattern, body, re.IGNORECASE | re.MULTILINE) is None]
    findings.extend(f"forbidden pattern present: {pattern}" for pattern in forbidden if re.search(pattern, body, re.IGNORECASE | re.MULTILINE) is not None)
    return findings


def fenced_blocks(body: str) -> list[tuple[str, str]]:
    """Return language and content from Markdown fences."""

    return [(match.group(1).lower(), match.group(2).rstrip("\n")) for match in re.finditer(r"```([^\n]*)\n(.*?)```", body, re.DOTALL)]


def validate_inline_alignment(body: str) -> list[str]:
    """Check same-line Python comments at longest code width plus two."""

    blocks = [content for language, content in fenced_blocks(body) if language not in {"json", "javascript", "js"} and "#" in content]
    if not blocks:
        return ["annotated code block missing"]
    findings: list[str] = []
    for block_index, block in enumerate(blocks, start=1):
        units: list[tuple[int, int]] = []
        for line_number, line in enumerate(block.splitlines(), start=1):
            if not line.strip() or re.fullmatch(r"\s*[\]\[{}(),;]+\s*", line):
                continue
            marker = line.find("#")
            if marker < 0:
                findings.append(f"block {block_index} line {line_number}: same-line comment missing")
                continue
            code = line[:marker].rstrip(" \t")
            units.append((display_width(code), display_width(line[:marker]) + 1))
            if line.rstrip(" \t") != line:
                findings.append(f"block {block_index} line {line_number}: trailing whitespace")
        if units:
            target = max(code_width for code_width, _ in units) + 2
            for unit_index, (_, actual) in enumerate(units, start=1):
                if actual != target:
                    findings.append(f"block {block_index} unit {unit_index}: comment column {actual}, target {target}")
    return findings


def validate_json_fallback(body: str) -> list[str]:
    """Require valid unchanged-style JSON and prose outside the non-commentable block."""

    blocks = [content for language, content in fenced_blocks(body) if language == "json"]
    if not blocks:
        return ["JSON code block missing"]
    findings: list[str] = []
    for block in blocks:
        try:
            json.loads(block)
        except json.JSONDecodeError:
            findings.append("JSON block is not valid JSON")
        if re.search(r"(?m)^\s*(//|#)|//\s*\w", block):
            findings.append("JSON block contains an illegal comment")
    prose = re.sub(r"```.*?```", "", body, flags=re.DOTALL)
    if not re.search(r"enabled", prose, re.IGNORECASE) or not re.search(r"limit", prose, re.IGNORECASE):
        findings.append("line-by-line explanation does not cover enabled and limit")
    return findings


def evaluate_body(body: str, declaration: dict[str, Any]) -> list[str]:
    """Apply only deterministic checks declared by the public case."""

    findings = pattern_findings(body, declaration["required_patterns"], declaration["forbidden_patterns"])
    kind = declaration["kind"]
    if kind == "inline_alignment":
        findings.extend(validate_inline_alignment(body))
    elif kind == "json_fallback":
        findings.extend(validate_json_fallback(body))
    return findings


def install_candidate(skill_root: Path, codex_home: Path) -> None:
    """Copy only runtime-relevant candidate files into an isolated Codex home."""

    destination = codex_home / "skills" / "human-readable-technical-writing"
    destination.mkdir(parents=True)
    for relative in RUNTIME_ITEMS:
        source = skill_root / relative
        if not source.exists():
            continue
        target = destination / relative
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)


def run_case(case: dict[str, Any], args: argparse.Namespace, run_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Execute one ephemeral task and return public and private records."""

    case_root = run_root / case["case_id"]
    codex_home = case_root / "home"
    task_root = case_root / "task"
    codex_home.mkdir(parents=True)
    task_root.mkdir(parents=True)
    shutil.copy2(args.auth, codex_home / "auth.json")
    install_candidate(args.skill_root, codex_home)
    command = [
        args.codex,
        "-a", "never",
        "exec",
        "--ephemeral",
        "--json",
        "--skip-git-repo-check",
        "--model", args.model,
        "-c", f'model_reasoning_effort="{args.reasoning_effort}"',
        "-s", "danger-full-access",
        "-C", str(task_root),
        case["prompt"],
    ]
    environment = os.environ.copy()
    environment["CODEX_HOME"] = str(codex_home)
    try:
        process = subprocess.run(command, text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=args.timeout_seconds, env=environment, check=False)
        stdout, stderr, exit_code = process.stdout, process.stderr, process.returncode
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout or ""
        stderr = (error.stderr or "") + "\nTIMEOUT"
        exit_code = 124
    events: list[dict[str, Any]] = []
    event_lines: list[str] = []
    for line in (stdout + "\n" + stderr).splitlines():
        if not line.lstrip().startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
            event_lines.append(line)
    messages = [event for event in events if event.get("type") == "item.completed" and isinstance(event.get("item"), dict) and event["item"].get("type") == "agent_message"]
    body = str(messages[-1]["item"].get("text", "")) if messages else ""
    serialized = json.dumps(events, ensure_ascii=False)
    skill_read = bool(re.search(r"human-readable-technical-writing.*SKILL\.md|SKILL\.md.*human-readable-technical-writing", serialized, re.IGNORECASE))
    activation_matches = skill_read == case["expected_activation"]
    findings = [] if exit_code == 0 else [f"Codex exit code {exit_code}"]
    if not activation_matches:
        findings.append(f"activation was {skill_read}, expected {case['expected_activation']}")
    findings.extend(evaluate_body(body, case["evaluator"]))
    public = {
        "case_id": case["case_id"],
        "family": case["family"],
        "expectation": case["expectation"],
        "model": args.model,
        "activated": skill_read,
        "expected_activation": case["expected_activation"],
        "passed": not findings,
        "violations": findings,
        "body_sha256": digest(body),
        "event_sha256": digest("\n".join(event_lines)),
        "event_count": len(events),
    }
    private = {"case": case, "command": command[:-1] + ["<prompt-in-case>"], "exit_code": exit_code, "body": body, "stdout": stdout, "stderr": stderr}
    return public, private


def main() -> int:
    """Execute all cases; write raw bodies privately and only hashes publicly."""

    args = parse_args()
    args.skill_root = args.skill_root.resolve()
    args.cases = args.cases.resolve()
    args.auth = args.auth.resolve()
    args.private_report = args.private_report.resolve()
    args.public_report = args.public_report.resolve()
    try:
        args.private_report.relative_to(ROOT.resolve())
    except ValueError:
        pass
    else:
        raise SystemExit("private report must be outside the repository")
    if not (args.skill_root / "SKILL.md").is_file() or not args.auth.is_file():
        raise SystemExit("skill root or auth file is missing")
    cases = [json.loads(line) for line in args.cases.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(cases) != 72:
        raise SystemExit(f"expected 72 cases, found {len(cases)}")
    public_records: list[dict[str, Any]] = []
    private_records: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="vnext-trigger-matrix-") as temporary:
        run_root = Path(temporary)
        for index, case in enumerate(cases, start=1):
            public, private = run_case(case, args, run_root)
            public_records.append(public)
            private_records.append(private)
            print(json.dumps({"progress": f"{index}/72", "case_id": case["case_id"], "passed": public["passed"]}, ensure_ascii=False), flush=True)
    args.private_report.parent.mkdir(parents=True, exist_ok=True)
    args.public_report.parent.mkdir(parents=True, exist_ok=True)
    private_payload = {"model": args.model, "cases": private_records}
    public_payload = {
        "matrix_version": "vnext-1.1-round-5",
        "model": args.model,
        "raw_bodies_location": "local_private_report",
        "total": len(public_records),
        "passed": sum(record["passed"] for record in public_records),
        "failed": sum(not record["passed"] for record in public_records),
        "results": public_records,
    }
    args.private_report.write_text(json.dumps(private_payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    args.public_report.write_text(json.dumps(public_payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    print(json.dumps({key: public_payload[key] for key in ("matrix_version", "model", "total", "passed", "failed")}, ensure_ascii=False, indent=2))
    return 0 if public_payload["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
