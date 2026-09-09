"""Collect one explicit session using the specified frozen skill, without running models.

No JS is evaluated. Only a small grammar of literal full-file reads and unchanged
exec_command result forwarding is accepted. Unknown code is not proof. Plain
r.output has no exit code: evidence is the app completion wrapper plus the entire
frozen file, not an invented process exit status. No reviewer fallback is allowed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import ntpath
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
FILES = ("SKILL.md", "references/format-rules.md", "references/explanation-framework.md")
REVIEWER = "scripts/review_writing.py"
CALL_TYPES = {"custom_tool_call", "function_call", "command_execution"}
OUTPUT_TYPES = {"custom_tool_call_output", "function_call_output"}
JS_STRING = r'''(?:"(?:[^"\\\r\n]|\\["'\\/bfnrt]|\\u[0-9a-fA-F]{4})*"|'(?:[^'\\\r\n]|\\["'\\/bfnrt]|\\u[0-9a-fA-F]{4})*')'''
JS_FORWARD = re.compile(
    r"\s*(?:// @exec:[^\n]*\n)?\s*(?:const|let)\s+(?P<var>[A-Za-z_]\w*)\s*=\s*await\s+"
    r"tools\.exec_command\s*\(\s*(?P<args>\{.*\})\s*\)\s*;\s*"
    r"text\s*\(\s*(?P=var)(?P<plain>\s*\.\s*output)?\s*\)\s*;?\s*", re.DOTALL,
)
JS_TEXT_AWAIT = re.compile(
    r"\s*(?:// @exec:[^\n]*\n)?\s*text\s*\(\s*await\s+tools\.exec_command\s*\(\s*"
    r"(?P<args>\{.*\})\s*\)\s*\)\s*;?\s*", re.DOTALL,
)
APP_HEADER = re.compile(r"Script completed\nWall time [\d.]+ seconds\nOutput:\n?")
TRUNCATION = re.compile(
    r"(?im)^Warning: truncated output\b|^.*(?:\.{3}|…)\s*\d+ (?:tokens|chars|characters) truncated\b|"
    r"^\[?output truncated\]?\s*$"
)
PEM_PRIVATE_KEY = re.compile(
    r"-----BEGIN [^-\r\n]*PRIVATE KEY-----.*?(?:-----END [^-\r\n]*PRIVATE KEY-----|\Z)", re.DOTALL,
)
INLINE_CREDENTIAL = re.compile(
    r'''(?i)\b(api[_ -]?key|private[_ -]?key|token|password|secret)\b(["']?\s*[:=]\s*)'''
    r'''(?:"[^"\r\n]*"|'[^'\r\n]*'|[^\s,;]+)'''
)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def normalized(text: str) -> str:
    # Only transport line endings may differ; do not strip file whitespace.
    return text.replace("\r\n", "\n")


def canonical_path(raw: str, base: str | None = None) -> str | None:
    if raw.startswith("file://"):
        uri = urlsplit(raw)
        if uri.netloc not in ("", "localhost"):
            return None
        raw = unquote(uri.path)
        if re.match(r"^/[A-Za-z]:/", raw):
            raw = raw[1:]
    if not raw or any(character in raw for character in "$*?\r\n" + chr(96)):
        return None
    if re.match(r"^[A-Za-z]:[\\/]", raw) and os.name != "nt":
        return ntpath.normpath(raw).casefold()
    path = Path(raw.replace("\\", "/"))
    if not path.is_absolute():
        if not base or not Path(base).is_absolute():
            return None
        path = Path(base) / path
    return os.path.normcase(str(path.resolve()))


def full_read_paths(command: str) -> set[str]:
    """Every statement must be a whole-file read; echoes/conditions reject the call."""
    if "\n" in command or "\r" in command:
        return set()
    pattern = re.compile(
        r'''\s*(?:'(?P<single>[^'\r\n]*)'|"(?P<double>[^"\r\n]*)"|'''
        r'''(?P<bare>[^\s,;'"|&<>]+)|(?P<statement>;)|(?P<comma>,))'''
    )
    tokens = []
    cursor = 0
    while cursor < len(command.rstrip()):
        match = pattern.match(command, cursor)
        if not match:
            return set()
        if match["statement"]:
            tokens.append((";", True, False, False))
        elif match["comma"]:
            tokens.append((",", False, True, False))
        else:
            value = match["single"] if match["single"] is not None else match["double"]
            tokens.append((value if value is not None else match["bare"], False, False, value is not None))
        cursor = match.end()
    if not tokens:
        return set()
    verb = tokens[0][0].lower()
    if verb in {"pwsh", "pwsh.exe", "powershell", "powershell.exe", "bash", "sh"}:
        if any(statement or comma for _, statement, comma, _ in tokens):
            return set()
        words = [word for word, _, _, _ in tokens]
        if (len(words) < 3 or words[-2].lower() not in {"-command", "-c", "-lc"}
                or any(word.lower() not in {"-noprofile", "-noninteractive"} for word in words[1:-2])):
            return set()
        return full_read_paths(words[-1])
    groups: list[list[tuple[str, bool, bool]]] = [[]]
    for word, statement, comma, quoted in tokens:
        if statement:
            groups.append([])
        else:
            groups[-1].append((word, comma, quoted))
    paths: set[str] = set()
    for group in groups:
        if not group or group[0][0].lower() not in {"get-content", "cat", "type"}:
            return set()
        operands = []
        literal_path = False
        expect_list_operand = False
        index = 1
        while index < len(group):
            token, comma, quoted = group[index]
            if comma:
                if not literal_path or not operands or expect_list_operand:
                    return set()
                expect_list_operand = True
                index += 1
                continue
            if expect_list_operand and (not quoted or token.startswith("-")):
                return set()
            if token.lower() == "-encoding":
                if (expect_list_operand or index + 1 == len(group) or group[index + 1][1]
                        or group[index + 1][0].lower() not in {"utf8", "utf-8", "utf8bom", "utf8nobom"}):
                    return set()
                index += 2
                continue
            if token.lower() == "-literalpath":
                literal_path = True
                index += 1
                continue
            if token.lower() in {"-raw", "-path", "--"}:
                index += 1
                continue
            if token.startswith("-") or any(char in token for char in "$(){}*?,#\r\n" + chr(96)):
                return set()
            operands.append(token)
            expect_list_operand = False
            index += 1
        if not operands or expect_list_operand:
            return set()
        paths.update(operands)
    return paths


def literal_object(source: str) -> dict[str, Any] | None:
    """Parse scalar JS object literals (quoted/unquoted keys) without executing code."""
    field = re.compile(
        rf"\s*(?P<key>{JS_STRING}|[A-Za-z_]\w*)\s*:\s*"
        rf"(?P<value>{JS_STRING}|true|false|null|\d+(?:\.\d+)?)\s*(?P<end>,|$)"
    )

    def scalar(raw: str) -> Any:
        if raw[0] in "\"'":
            parts = re.findall(r"\\u[0-9a-fA-F]{4}|\\.|[^\\]", raw[1:-1])
            escapes = {"b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}
            return "".join(chr(int(part[2:], 16)) if part.startswith("\\u") else
                           escapes.get(part[1], part[1]) if part.startswith("\\") else part for part in parts)
        return json.loads(raw)

    if not source.startswith("{") or not source.endswith("}"):
        return None
    body = source[1:-1].strip()
    result: dict[str, Any] = {}
    cursor = 0
    while cursor < len(body):
        match = field.match(body, cursor)
        if not match:
            return None
        key = scalar(match["key"]) if match["key"][0] in "\"'" else match["key"]
        if key in result:
            return None
        result[key] = scalar(match["value"])
        cursor = match.end()
    return result


def invocation(call: dict[str, Any]) -> tuple[set[str], str] | None:
    name = call.get("name")
    mode = "direct"
    if call.get("type") == "custom_tool_call" and name in {"exec", "functions.exec"}:
        code = call.get("input")
        match = JS_FORWARD.fullmatch(code) if isinstance(code, str) else None
        if match:
            args = literal_object(match["args"])
            mode = "plain" if match["plain"] else "json"
        else:
            match = JS_TEXT_AWAIT.fullmatch(code) if isinstance(code, str) else None
            if not match:
                return None
            args = literal_object(match["args"])
            # text() serializes the returned result object, so retain process exit evidence.
            mode = "json"
    elif call.get("type") == "command_execution":
        args = {"cmd": call.get("command"), "workdir": call.get("cwd")}
    elif name in {"exec_command", "functions.exec_command"}:
        args = call.get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                return None
    else:
        return None
    if not isinstance(args, dict) or not isinstance(args.get("cmd"), str):
        return None
    workdir = args.get("workdir")
    if workdir is not None and not isinstance(workdir, str):
        return None
    paths = {canonical_path(path, workdir) for path in full_read_paths(args["cmd"])}
    if not paths or None in paths:
        return None
    return paths, mode


def payload(event: dict[str, Any]) -> dict[str, Any]:
    candidate = event.get("payload", event.get("item", event))
    return candidate if isinstance(candidate, dict) else {}


def parse_events(data: bytes) -> list[dict[str, Any]]:
    """Project allowed records only; never retain user or reasoning payloads."""
    events = []
    for number, line in enumerate(data.decode("utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except ValueError:
            raise ValueError(f"invalid JSONL at line {number}") from None
        if not isinstance(event, dict):
            raise ValueError(f"non-object JSONL event at line {number}")
        item = payload(event)
        kind = item.get("type")
        if event.get("type") not in {"response_item", "item.completed"}:
            continue
        if kind in CALL_TYPES | OUTPUT_TYPES:
            keys = ("type", "id", "call_id", "name", "input", "arguments", "command", "cwd", "status",
                    "output", "aggregated_output", "exit_code", "session_id", "isError", "error", "truncated")
        elif (kind == "message" and item.get("role") == "assistant"
              and item.get("phase", item.get("channel")) in {"final_answer", "final"}):
            keys = ("type", "id", "role", "phase", "channel", "status", "content")
        else:
            continue
        events.append({"type": event["type"], "payload": {key: item[key] for key in keys if key in item}})
    return events


def load_events(session: Path) -> list[dict[str, Any]]:
    return parse_events(session.read_bytes())


def failed_status(item: dict[str, Any]) -> bool:
    return (item.get("status") not in (None, "completed", "success")
            or bool(item.get("isError") or item.get("error"))
            or ("exit_code" in item and type(item["exit_code"]) is int and item["exit_code"] != 0))


def execution_output(call: dict[str, Any], record: dict[str, Any], mode: str) -> tuple[str, str, str]:
    """Return stdout, success basis and rejection reason, never arbitrary error text."""
    if failed_status(call) or failed_status(record):
        return "", "", "failed"
    if call.get("truncated") or record.get("truncated"):
        return "", "", "truncated"
    raw = record.get("output", record)
    if mode != "direct":
        if not isinstance(raw, list) or not all(isinstance(block, dict) and
                block.get("type") in {"input_text", "text"} and isinstance(block.get("text"), str) for block in raw):
            return "", "", "unverified_output"
        blocks = [normalized(block["text"]) for block in raw]
        if not blocks or not APP_HEADER.fullmatch(blocks[0]):
            reason = "failed" if blocks and blocks[0].startswith(("Script failed", "Script error:")) else "unverified_output"
            return "", "", reason
        # The accepted JS grammar emits exactly one unchanged result.
        if len(blocks) != 2:
            return "", "", "unverified_output"
        if mode == "plain":
            return blocks[1], "script_completed_full_output_exit_unavailable", ""
        raw = blocks[1]
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return "", "", "unverified_output"
    if not isinstance(raw, dict):
        return "", "", "unverified_output"
    if failed_status(raw):
        return "", "", "failed"
    if raw.get("truncated") or raw.get("output_truncated"):
        return "", "", "truncated"
    if type(raw.get("exit_code")) is not int or raw["exit_code"] != 0 or raw.get("session_id") is not None:
        return "", "", "unverified_output"
    stdout = raw.get("output", raw.get("aggregated_output"))
    return (normalized(stdout), "process_exit_zero", "") if isinstance(stdout, str) else ("", "", "unverified_output")


def tool_evidence(events: list[dict[str, Any]], skill_root: Path,
                  frozen: dict[str, bytes] | None = None) -> dict[str, Any]:
    frozen = frozen if frozen is not None else {relative: (skill_root / relative).read_bytes() for relative in FILES}
    expected = {relative: normalized(data.decode("utf-8")) for relative, data in frozen.items()}
    targets = {canonical_path(str(skill_root / relative)): relative for relative in FILES}
    calls: dict[str, dict[str, Any]] = {}
    outputs: dict[str, dict[str, Any]] = {}
    conflicting: set[str] = set()
    for event in events:
        if event.get("type") not in {"response_item", "item.completed"}:
            continue
        item = payload(event)
        kind = item.get("type")
        identity = item.get("call_id", item.get("id"))
        if kind not in CALL_TYPES | OUTPUT_TYPES or not isinstance(identity, str):
            continue
        destination = calls if kind in CALL_TYPES else outputs
        # Mirrored transport record IDs can differ; compare their substantive fields.
        value = {key: value for key, value in item.items() if key != "id"}
        if identity in destination and value != destination[identity]:
            conflicting.add(identity)
        destination.setdefault(identity, value)
        if kind == "command_execution":
            outputs.setdefault(identity, value)
    counts = dict.fromkeys(FILES, 0)
    other_counts = dict.fromkeys(FILES, 0)
    rejected: dict[str, int] = {}
    accepted = []
    other_calls = []
    for identity, call in calls.items():
        parsed = invocation(call)
        reason = "conflicting_call_id" if identity in conflicting else "unsupported_call" if not parsed else ""
        if not reason:
            paths, mode = parsed
            stdout, basis, reason = execution_output(call, outputs.get(identity, {}), mode)
            # Rules may literally discuss failures and truncation. Only diagnostics
            # outside complete matched source texts can reject an otherwise full read.
            remainder = stdout
            for body in expected.values():
                remainder = remainder.replace(body, "")
            if not reason and TRUNCATION.search(remainder):
                reason = "truncated"
            if not reason and re.search(r"(?im)^(?:Get-Content\s*:|Get-Content:|cat: |type: |Script error:|Process exited with code [1-9])", remainder):
                reason = "failed"
            matched = {targets[path] for path in paths if path in targets}
            complete = sorted(relative for relative in matched if expected[relative] and expected[relative] in stdout)
            other = sorted(relative for relative in FILES if expected[relative] and expected[relative] in stdout and
                           any(path not in targets and path.replace("\\", "/").lower().endswith("/" + relative.lower()) for path in paths))
            if not reason and (complete or other):
                for files, tally, entries in ((complete, counts, accepted), (other, other_counts, other_calls)):
                    if files:
                        for relative in files:
                            tally[relative] += 1
                        entries.append({"call_id": identity, "files": files, "success_evidence": basis})
                continue
            reason = reason or "full_snapshot_content_not_proven"
        rejected[reason] = rejected.get(reason, 0) + 1
    return {"read_counts": counts, "accepted_calls": accepted, "rejected_calls": rejected,
            "other_root_same_content_read_counts": other_counts, "other_root_same_content_calls": other_calls,
            "complete_skill_and_two_references": all(counts[name] > 0 for name in FILES),
            "reference_reread_proven": all(counts[name] >= 2 for name in FILES[1:])}


def final_answers(events: list[dict[str, Any]]) -> list[str]:
    answers = []
    seen: set[str] = set()
    for event in events:
        if event.get("type") != "response_item":
            continue
        item = payload(event)
        if (item.get("type") != "message" or item.get("role") != "assistant"
                or item.get("phase", item.get("channel")) not in {"final_answer", "final"}
                or item.get("status") not in (None, "completed")):
            continue
        content = item.get("content")
        if not isinstance(content, list) or not content or not all(isinstance(block, dict) and
                block.get("type") == "output_text" and isinstance(block.get("text"), str) for block in content):
            continue
        text = "".join(block["text"] for block in content)
        identity = item.get("id")
        if text.strip() and (not identity or identity not in seen):
            answers.append(text)
            if identity:
                seen.add(identity)
    return answers


def redact_credentials(text: str) -> str:
    text = PEM_PRIVATE_KEY.sub("[REDACTED PRIVATE KEY]", text)
    return INLINE_CREDENTIAL.sub(r"\1\2[REDACTED]", text)


def ensure_new_private_output(output: Path) -> None:
    resolved = output.resolve()
    if resolved.is_relative_to(ROOT):
        raise ValueError("--output must be outside the repository")
    if output.exists() or output.is_symlink():
        raise FileExistsError("--output must be a new directory")
    output.mkdir(mode=0o700)  # Atomic claim; parent must already exist.


def write_json(path: Path, value: Any, *, created_by_reviewer: bool = False) -> None:
    with path.open("w" if created_by_reviewer else "x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def mechanical_review(skill_root: Path, output: Path, final_bytes: bytes | None,
                      nested_list_spacing: str = "compact") -> dict[str, Any]:
    if nested_list_spacing not in ("compact", "host-required"):
        raise ValueError("unknown nested-list spacing selection")
    script = skill_root / REVIEWER
    report_path = output / "writing-review.json"
    report: dict[str, Any] = {
        "mode": "checkonly", "mechanical_check_only": True,
        "beginner_understanding": "NOT_ASSESSED", "user_acceptance": "NOT_ASSESSED",
        "reviewer_source": "specified_skill_root",
        "nested_list_spacing": nested_list_spacing,
        "reviewer_sha256": sha256_bytes(script.read_bytes()) if script.is_file() else None,
    }
    if final_bytes is None:
        report["status"] = "NOT_RUN_NO_FINAL"
    elif not script.is_file():
        report["status"] = "NOT_RUN_FROZEN_REVIEWER_MISSING"
    else:
        command = [sys.executable, "-I", "-B", "-X", "utf8", str(script),
                   "--input", str(output / "final.md"), "--report", str(report_path)]
        if nested_list_spacing == "host-required":
            command.extend(["--nested-list-spacing", nested_list_spacing])
        try:
            result = subprocess.run(command, cwd=output, capture_output=True, timeout=60)
            report["exit_code"] = result.returncode
            if result.returncode != 0:
                report["status"] = "FROZEN_REVIEW_FAILED"
            else:
                raw = json.loads(report_path.read_bytes())
                form = raw["format"]
                final_hash = sha256_bytes(final_bytes)
                if (form["repair_rounds"] != 0 or form["input_sha256"] != final_hash
                        or form["document_sha256"] != final_hash or form["text"].encode("utf-8") != final_bytes
                        or (output / "final.md").read_bytes() != final_bytes):
                    report["status"] = "CHECKONLY_CONTRACT_VIOLATION"
                else:
                    report["status"] = "COMPLETED"
                    # Keep counts and hashes, not arbitrary report text or duplicate bodies.
                    report["format"] = {"status": form["status"], "repair_rounds": 0,
                                        "input_sha256": final_hash, "document_sha256": final_hash,
                                        "finding_count": len(form["findings"]), "candidate_count": len(form["candidates"])}
        except subprocess.TimeoutExpired:
            report["status"] = "FROZEN_REVIEW_TIMEOUT"
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            report["status"] = "FROZEN_REVIEW_FAILED"
    write_json(report_path, report, created_by_reviewer=report_path.exists())
    return report


def collect(session: Path, skill_root: Path, output: Path,
            nested_list_spacing: str = "compact") -> dict[str, Any]:
    if nested_list_spacing not in ("compact", "host-required"):
        raise ValueError("unknown nested-list spacing selection")
    session, skill_root = session.resolve(), skill_root.resolve()
    if not session.is_file() or not skill_root.is_dir():
        raise ValueError("--session must be a file and --skill-root must be a directory")
    if output.resolve().is_relative_to(skill_root):
        raise ValueError("--output must be outside the frozen skill directory")
    frozen = {}
    for relative in FILES:
        path = skill_root / relative
        if not path.is_file() or not path.resolve().is_relative_to(skill_root):
            raise ValueError(f"frozen skill is missing an internal file: {relative}")
        frozen[relative] = path.read_bytes()
    if (skill_root / REVIEWER).exists() and not (skill_root / REVIEWER).resolve().is_relative_to(skill_root):
        raise ValueError("frozen reviewer must be inside --skill-root")
    data = session.read_bytes()
    events = parse_events(data)
    answers = final_answers(events)
    evidence = tool_evidence(events, skill_root, frozen)
    original = answers[-1].encode("utf-8") if answers else None
    final_bytes = redact_credentials(answers[-1]).encode("utf-8") if answers else None
    evidence.update({"status": "FINAL_COLLECTED" if answers else "INCOMPLETE_NO_FINAL",
                     "nested_list_spacing": nested_list_spacing,
                     "skill_version": "current_repository" if skill_root == ROOT else "external_snapshot",
                     "skill_files": {name: sha256_bytes(value) for name, value in frozen.items()},
                     "session_sha256": sha256_bytes(data), "visible_final_turns": len(answers),
                     "original_final_sha256": sha256_bytes(original) if original is not None else None,
                     "redacted_final_sha256": sha256_bytes(final_bytes) if final_bytes is not None else None,
                     "redaction_applied": original != final_bytes})
    ensure_new_private_output(output)
    output = output.resolve()
    write_json(output / "read-evidence.json", evidence)
    if final_bytes is not None:
        with (output / "final.md").open("xb") as stream:
            stream.write(final_bytes)
    review = mechanical_review(skill_root, output, final_bytes, nested_list_spacing=nested_list_spacing)
    return {"completed": bool(answers), "review_status": review["status"], "output": str(output)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", type=Path, required=True)
    parser.add_argument("--skill-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--nested-list-spacing", choices=("compact", "host-required"), default="compact",
                        help="use host-required only when higher-priority host instructions require a blank "
                             "before each nested list; recorded in the reports")
    args = parser.parse_args(argv)
    try:
        result = collect(args.session, args.skill_root, args.output, nested_list_spacing=args.nested_list_spacing)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["review_status"] == "COMPLETED" else 2
    except Exception:
        # Do not echo arbitrary source JSON, subprocess diagnostics or credentials.
        print("ERROR: collection failed; check explicit inputs and the new external destination", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
