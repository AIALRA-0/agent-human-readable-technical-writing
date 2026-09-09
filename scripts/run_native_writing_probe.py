"""Small native-skill probe. Run only after freezing the candidate.

No answer judging, prompt rule bundles, retries, publishing or user installation.
Raw CLI results remain outside the repository in run-root/private. The report is
an allowlisted summary of observed calls, not an assertion of writing compliance.
Unrecognised read syntax deliberately yields not_proven. No CLI runs on import.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import sys
from typing import Any
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.run_iterative_forward_matrix import (  # noqa: E402
    CLEAN_AGENT_DISABLED_FEATURES as FEATURES,
    MODELS,
    RUNTIME_ITEMS,
    run_codex,
    runtime_tree_digest,
)

SKILL = "human-readable-technical-writing"
FILES = ("SKILL.md", "references/format-rules.md", "references/explanation-framework.md")
CASES = (
    ("implicit_explanation", (
        "我完全没有编程基础，请用中文帮我理解这段说明，并走一遍具体例子："
        "消息队列（Message Queue）先保存待处理的消息，处理程序再逐条取出。"
        "本例每条消息是一张订单，每分钟新来3张，程序每分钟最多处理2张，"
        "开始时没有积压。两分钟后会怎样？",
    )),
    ("explicit_skill", (
        "请使用 $human-readable-technical-writing，用中文帮第一次接触这件事的人"
        "讲清楚下面的说明：温控器（Thermostat）根据温度控制加热器。"
        "这个示例低于18摄氏度就加热，达到20摄氏度就停止，中间保持原来的开关状态。"
        "请说明从17摄氏度升到21摄氏度、再降到19摄氏度的过程。",
    )),
    ("pure_json", (
        '只输出一个合法 JSON 对象，不要 Markdown 或解释。字段 count 的值为整数3，'
        '字段 enabled 的值为布尔值 true，不要其他字段。',
    )),
    ("multi_turn", (
        "我没有技术基础，请用中文解释这个存水例子：水箱开始是空的，每分钟进水3升，"
        "出水口每分钟最多排出2升，没有水就不排。请带我算完前两分钟。",
        "先换个话题。请把这份活动通知改成方便邻居阅读的中文："
        "周六上午九点在一楼大厅交换旧书，每人最多带五本，"
        "下雨仍在室内举行，不收费用，儿童需要家长陪同。",
        "回到刚才的水箱。现在进水改成每分钟1升，其他条件保持不变。"
        "从前两分钟结束时继续算接下来的两分钟，请解释水量为什么这样变化。",
    )),
)


def write_new(path: Path, value: Any) -> None:
    """Exclusive creation also protects private evidence from accidental reuse."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def prepare_root(run_root: Path, report: Path, auth: Path) -> Path:
    for path in (run_root, report):
        if path.is_relative_to(ROOT) or ROOT.is_relative_to(path):
            raise ValueError("run-root and report must be outside the repository")
    if report.is_relative_to(run_root) or run_root.is_relative_to(report):
        raise ValueError("report must be separate from the private run-root")
    if not auth.is_file() or auth.is_relative_to(run_root):
        raise ValueError("auth must be an existing file outside run-root")
    if report.exists() or report.is_symlink():
        raise ValueError("report already exists")
    if run_root.exists() and (not run_root.is_dir() or any(run_root.iterdir())):
        raise ValueError("run-root must be new or empty; old runs are never removed")
    for parent in (run_root, *run_root.parents):
        if any((parent / directory / "skills").exists() for directory in (".agents", ".codex")):
            raise ValueError("run-root ancestors must not supply additional skills")
    run_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    private = run_root / "private"
    private.mkdir(mode=0o700)  # Atomic claim; another runner cannot share this root.
    report.parent.mkdir(parents=True, exist_ok=True)
    return private


def install_case(case_root: Path, auth: Path) -> tuple[Path, Path]:
    case_root.mkdir(mode=0o700)
    home, task = case_root / "home", case_root / "task"
    home.mkdir(mode=0o700)
    task.mkdir(mode=0o700)
    # Copy bytes, not the user's config, agents, sessions or file permissions.
    fd = os.open(home / "auth.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(auth.read_bytes())
    destination = task / ".agents" / "skills" / SKILL
    destination.mkdir(parents=True)
    for relative in RUNTIME_ITEMS:
        source, target = ROOT / relative, destination / relative
        if source.is_dir():
            shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    return home, task


def environment_for(home: Path) -> dict[str, str]:
    # Do not inherit API credentials, app context, eval hints or config overrides.
    allowed = {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "SYSTEMDRIVE",
               "PROGRAMFILES", "PROGRAMFILES(X86)", "TEMP", "TMP", "LANG", "LC_ALL"}
    environment = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    environment.update({
        "CODEX_HOME": str(home), "HOME": str(home), "USERPROFILE": str(home),
        "APPDATA": str(home / "appdata"), "LOCALAPPDATA": str(home / "localappdata"),
    })
    return environment


def base_command(codex: str, task: Path) -> list[str]:
    # These are exec options. Keeping sandbox/cwd before resume also avoids
    # relying on the top-level interactive CLI forwarding them to exec.
    command = [codex, "exec", "--sandbox", "workspace-write",
               "-C", str(task), "-c", 'web_search="disabled"',
               "-c", "sandbox_workspace_write.network_access=false", "-c", 'approval_policy="never"']
    for feature in FEATURES:
        command.extend(("--disable", feature))
    return command


def writer_command(codex: str, task: Path, model: str, session: str | None) -> list[str]:
    command = base_command(codex, task)
    if session:
        command.append("resume")
    command.extend(("--ignore-user-config", "--ignore-rules", "--json", "--skip-git-repo-check", "--model", model))
    if session:
        command.append(session)
    command.append("-")  # All user material is sent through stdin, including resume.
    return command


def check_host_help(codex: str, home: Path, private: Path) -> None:
    """Only the eventual operator runs these bounded, model-free help calls."""
    task = home.parent / "task"
    # Exercise the actual argument positions with --help before any writer can
    # start, including the parent exec options on a resume invocation.
    checks = (
        ([codex, "--help"], ("--disable", "--config")),
        (writer_command(codex, task, MODELS[0], None)[:-1] + ["--help"],
         ("--ignore-user-config", "--ignore-rules", "--sandbox", "-C", "--json", "--skip-git-repo-check", "--model")),
        (writer_command(codex, task, MODELS[0], "00000000-0000-0000-0000-000000000000")[:-1] + ["--help"],
         ("--ignore-user-config", "--ignore-rules", "--json", "--skip-git-repo-check", "--model")),
    )
    for index, (command, flags) in enumerate(checks):
        result = run_codex(command, environment_for(home), 20)
        evidence_path = private / f"help-{index}.json"
        write_new(evidence_path, {"command": command, **result})
        help_text = result["stdout"]
        missing = [flag for flag in flags if not re.search(
            r"(?<![\w-])" + re.escape(flag) + r"(?![\w-])", help_text)]
        if result["exit_code"] != 0 or missing:
            raise ValueError(f"CLI help-{index} failed: exit_code={result['exit_code']}, "
                             f"missing options={missing}; no writer started. Local evidence: {evidence_path}")


def canonical_path(raw: str, task: Path) -> str | None:
    if raw.startswith("file://"):
        uri = urlsplit(raw)
        if uri.netloc not in ("", "localhost"):
            return None
        raw = unquote(uri.path)
        if re.match(r"^/[A-Za-z]:/", raw):
            raw = raw[1:]
    if not raw or any(char in raw for char in "$`*?\n\r"):
        return None
    if re.match(r"^[A-Za-z]:[\\/]", raw):
        if os.name != "nt":
            return str(PureWindowsPath(raw)).casefold()
    path = Path(raw.replace("\\", "/"))
    return os.path.normcase(str((path if path.is_absolute() else task / path).resolve()))


def command_reads(command: str) -> tuple[set[str], bool]:
    """Recognise simple full-file reads; never grep filenames out of arbitrary code.

    Pipelines, slices, variables, conditions and embedded programs are unresolved.
    Deduplication is per tool call: repeated operands do not prove a later reread.
    """
    tokens = re.findall(r'''"[^"\n]*"|'[^'\n]*'|[^\s;|&<>]+|[;|&<>]''', command)
    tokens = [token[1:-1] if token[:1] in ("'", '"') else token for token in tokens]
    if not tokens:
        return set(), True
    executable = tokens[0].replace("\\", "/").rsplit("/", 1)[-1].lower()
    if executable in {"pwsh", "pwsh.exe", "powershell", "powershell.exe", "bash", "sh"}:
        markers = [i for i, token in enumerate(tokens) if token.lower() in {"-command", "-c", "-lc"}]
        if len(markers) != 1 or markers[0] != len(tokens) - 2:
            return set(), True
        return command_reads(tokens[-1])
    if any(token in {"|", "&", "<", ">"} for token in tokens):
        return set(), True
    # Retain line boundaries so separate commands cannot become path operands.
    if "\n" in command or "\r" in command:
        return set(), True
    groups: list[list[str]] = [[]]
    for token in tokens:
        if token == ";":
            groups.append([])
        else:
            groups[-1].append(token)
    paths: set[str] = set()
    unresolved = False
    for group in groups:
        if not group:
            continue
        verb = group[0].lower()
        if verb in {"echo", "write-output", "write-host", "printf"}:
            # A quoted filename in output is not a file read. Substitution is unknown.
            unresolved |= any("$" in token or "`" in token for token in group[1:])
            continue
        if verb not in {"get-content", "cat", "type"}:
            unresolved = True
            continue
        operands: list[str] = []
        invalid = False
        i = 1
        while i < len(group):
            token = group[i]
            if token.lower() == "-encoding" and i + 1 < len(group):
                i += 2
                continue
            if token.lower() in {"-raw", "-path", "-literalpath", "--"}:
                i += 1
                continue
            if token.startswith("-") or any(char in token for char in "$`(){}*?,"):
                invalid = True
            operands.append(token)
            i += 1
        if invalid or not operands:
            unresolved = True
        else:
            paths.update(operands)
    return paths, unresolved


def read_evidence(events: list[dict[str, Any]], task: Path) -> dict[str, Any]:
    installed = task / ".agents" / "skills" / SKILL
    targets = {canonical_path(str(installed / relative), task): relative for relative in FILES}
    counts = {relative: 0 for relative in FILES}
    full_counts = {relative: 0 for relative in FILES}
    expected = {}
    for relative in FILES:
        try:
            expected[relative] = (installed / relative).read_text(encoding="utf-8").strip()
        except OSError:
            expected[relative] = ""
    calls = {"command_execution": 0, "mcp_tool_call": 0}
    unresolved = failed = 0
    seen: set[str] = set()
    for event in events:
        item = event.get("item")
        if event.get("type") != "item.completed" or not isinstance(item, dict):
            continue
        kind = item.get("type")
        if kind not in calls:
            if kind not in {"agent_message", "reasoning", "todo_list"}:
                unresolved += 1
            continue
        identity = str(item.get("id") or json.dumps(item, sort_keys=True))
        if identity in seen:
            continue
        seen.add(identity)
        calls[kind] += 1
        if item.get("status") != "completed":
            failed += 1
            continue
        if kind == "command_execution":
            output = item.get("aggregated_output")
            if item.get("exit_code") != 0:
                failed += 1
                continue
            paths, unknown = command_reads(str(item.get("command", "")))
            if paths and (not isinstance(output, str) or not output.strip() or re.search(
                r"(?i)cannot find path|no such file|permission denied|access.+denied|"
                r"Get-Content\s*:|ObjectNotFound", output
            )):
                unresolved += 1
                continue
        else:
            result = item.get("result")
            if item.get("error") or not isinstance(result, dict) or result.get("isError"):
                failed += 1
                continue
            arguments = item.get("arguments")
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except ValueError:
                    arguments = None
            if item.get("tool") not in {"read_file", "read_text_file", "read_multiple_files", "read_resource"} or not isinstance(arguments, dict):
                unresolved += 1
                continue
            if any(key in arguments for key in ("head", "tail", "offset", "limit", "start_line", "end_line")):
                unresolved += 1
                continue
            content = result.get("content")
            if not isinstance(content, list) or not any(
                isinstance(block, dict) and block.get("type") == "text" and block.get("text") for block in content
            ):
                unresolved += 1
                continue
            # Multi-file responses can contain per-file errors despite isError=false.
            if any(re.search(r"(?i)error|not found|denied", str(block.get("text", "")))
                   for block in content if isinstance(block, dict)):
                unresolved += 1
                continue
            raw_paths = arguments.get("paths", [arguments.get("path") or arguments.get("uri")])
            paths = set(raw_paths) if isinstance(raw_paths, list) and all(isinstance(p, str) for p in raw_paths) else set()
            unknown = not bool(paths)
            output = "\n".join(str(block.get("text", "")) for block in content if isinstance(block, dict))
        matched = {targets.get(canonical_path(path, task)) for path in paths}
        for relative in matched - {None}:
            counts[relative] += 1
            # A successful read invocation alone does not prove full content was
            # visible. Compare tool output only, never an agent message or answer.
            normalized_output = output.replace("\r\n", "\n") if isinstance(output, str) else ""
            if (expected[relative] and expected[relative] in normalized_output
                    and not re.search(r"(?i)truncated", normalized_output)):
                full_counts[relative] += 1
        unresolved += int(unknown or None in matched)
    return {
        "read_calls": counts, "full_read_calls": full_counts, "tool_calls": calls, "failed_calls": failed,
        "unresolved_calls": unresolved,
        "discovery": "proven" if all(full_counts.values()) else "not_proven",
        "reference_reread": "proven" if all(full_counts[name] >= 2 for name in FILES[1:]) else "not_proven",
    }


def summarize_turn(result: dict[str, Any], task: Path, index: int, negative: bool) -> dict[str, Any]:
    events = result["events"]
    evidence = read_evidence(events, task)
    complete = result["exit_code"] == 0 and any(event.get("type") == "turn.completed" for event in events)
    complete &= not any(event.get("type") in {"error", "turn.failed"} for event in events)
    started = {event["item"].get("id") for event in events
               if event.get("type") == "item.started" and isinstance(event.get("item"), dict)
               and event["item"].get("type") in {"command_execution", "mcp_tool_call"}}
    finished = {event["item"].get("id") for event in events
                if event.get("type") == "item.completed" and isinstance(event.get("item"), dict)}
    complete &= not bool(started - finished)
    summary = {"turn": index + 1, "phase": "initial" if index == 0 else "resume",
               "event_count": len(events), "completed": bool(complete), **evidence}
    # Some hosts omit rejected calls from JSON events but report the denial on
    # stderr. Preserve that separate observation without publishing raw paths.
    denied = bool(re.search(r"(?im)^.*(?:tools::router|exec_command failed).*rejected: blocked by policy", str(result.get("stderr", ""))))
    summary["host_policy_denial_observed"] = denied
    if negative:
        # Only this mechanical format check touches a body; no prose is judged.
        try:
            value = json.loads(result["body"])
            valid = (isinstance(value, dict) and set(value) == {"count", "enabled"}
                     and type(value["count"]) is int and value["count"] == 3 and value["enabled"] is True)
        except (TypeError, ValueError):
            valid = False
        summary["json_body_valid"] = valid
        observed = sum(evidence["read_calls"].values())
        if observed or (complete and not valid):
            summary["negative"] = "failed"
        elif complete and valid and not evidence["unresolved_calls"] and not evidence["failed_calls"] and not denied:
            summary["negative"] = "passed"
        else:
            summary["negative"] = "not_proven"
    return summary


def run_case(codex: str, model: str, case: tuple[str, tuple[str, ...]], case_root: Path,
             home: Path, task: Path, timeout: int) -> dict[str, Any]:
    case_id, prompts = case
    turns: list[dict[str, Any]] = []
    session = None
    same_session = True
    confirmed_session = True
    for index, prompt in enumerate(prompts):
        command = writer_command(codex, task, model, session)
        try:
            result = run_codex(command, environment_for(home), timeout, stdin_text=prompt)
        except Exception as error:
            write_new(case_root / f"turn-{index + 1}-error.json", {"error": repr(error)})
            break
        write_new(case_root / f"turn-{index + 1}.json", result)
        summary = summarize_turn(result, task, index, case_id == "pure_json")
        turns.append(summary)
        returned = result.get("thread_id")
        if index == 0:
            session = returned
        elif returned and returned != session:
            same_session = False
        if index and returned != session:
            confirmed_session = False
        if not summary["completed"] or not session or not same_session:
            break
    value = {"id": case_id, "model": model, "turn_count": len(turns),
             "expected_turn_count": len(prompts), "turns": turns}
    if len(prompts) > 1:
        value["same_session_resume"] = "proven" if same_session and confirmed_session and session and len(turns) == 3 else "not_proven"
        value["return_reference_reads"] = "proven" if (
            value["same_session_resume"] == "proven" and turns[-1]["completed"]
            and all(turns[0]["full_read_calls"][name] and turns[-1]["full_read_calls"][name] for name in FILES[1:])
        ) else "not_proven"
    return value


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--auth", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--model", action="append", help="repeat to select models; defaults to Sol, Terra, Luna")
    parser.add_argument("--case-id", choices=[case[0] for case in CASES],
                        help="run one existing case for a small host diagnostic")
    parser.add_argument("--codex", default="codex")
    parser.add_argument("--workers", type=int, choices=(1, 2, 3), default=3)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    args = parser.parse_args(argv)
    args.model = args.model or list(MODELS)
    if not 1 <= args.timeout_seconds <= 900:
        parser.error("timeout-seconds must be between 1 and 900")
    if any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", model) for model in args.model):
        parser.error("model must be a model identifier")
    args.model = list(dict.fromkeys(args.model))
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    private = prepare_root(args.run_root.resolve(), args.report.resolve(), args.auth.resolve())
    digest = runtime_tree_digest()
    jobs = []
    for model_index, model in enumerate(args.model):
        for case_index, case in enumerate(CASES):
            if args.case_id and case[0] != args.case_id:
                continue
            case_root = private / f"m{model_index + 1}-c{case_index + 1}"
            home, task = install_case(case_root, args.auth.resolve())
            jobs.append((args.codex, model, case, case_root, home, task, args.timeout_seconds))
    if runtime_tree_digest() != digest:
        raise ValueError("runtime changed while installing; no writer started")
    write_new(private / "runtime.json", {"runtime_tree_digest": digest})
    try:
        check_host_help(args.codex, jobs[0][4], private)
    except (OSError, ValueError) as error:
        diagnostic = private / "startup-error.json"
        write_new(diagnostic, {"error_type": type(error).__name__, "error": str(error)})
        raise ValueError(f"{error}; startup diagnostic: {diagnostic}") from error
    print(f"CLI help checks passed; starting {len(jobs)} cases with {args.workers} workers", flush=True)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(run_case, *job) for job in jobs]
        cases = [future.result() for future in futures]
    # Construct public data only from the fixed summary fields, never raw results.
    write_new(args.report.resolve(), {"case_count": len(cases), "model_count": len(args.model),
                                     "turn_count": sum(case["turn_count"] for case in cases), "cases": cases})
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as error:
        # Startup diagnostics identify the local evidence without printing raw
        # process output, credentials or model answers into the terminal.
        print(f"Probe stopped: {error}", file=sys.stderr)
        raise SystemExit(2)
