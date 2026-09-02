"""Run one forward round through isolated three-model self-iterative closure."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from collections import deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Any, Iterable

import jsonschema
import yaml
from referencing import Registry, Resource


ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"
MODELS = ("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna")
MODEL_CODES = {"gpt-5.6-sol": "SOL", "gpt-5.6-terra": "TERRA", "gpt-5.6-luna": "LUNA"}
RUNTIME_ITEMS = ["SKILL.md", "constitution", "runtime", "contracts", "profiles", "registries", "validators", "patcher", "references"]
CLEAN_AGENT_DISABLED_FEATURES = (
    "apps", "plugins", "remote_plugin", "recommended_plugins",
    "skill_mcp_dependency_install", "tool_suggest", "browser_use",
    "computer_use", "image_generation", "in_app_browser",
)
CLEAN_SKILL_PATH_INSTRUCTION = (
    "Read installed Skill files only from the task-specific "
    "`AIALRA_EVAL_SKILL_ROOT` environment variable. In PowerShell, join relative paths "
    "to `$env:AIALRA_EVAL_SKILL_ROOT`; never type, infer, split, or reconstruct an absolute "
    "run-root path. Do not probe an alternative path if a read fails."
)
WRITE_LOCK = Lock()

sys.path.insert(0, str(ROOT))
from patcher.deterministic_committer import PatchError, apply_minimal_transaction, sha256_text  # noqa: E402
from runtime.self_iteration import deterministic_findings, line_nodes, merge_findings  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--round", type=int, required=True, dest="round_number")
    parser.add_argument("--auth", type=Path, required=True)
    parser.add_argument("--private-report", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--seed-drafts", type=Path)
    parser.add_argument("--feedback", type=Path)
    parser.add_argument("--model", action="append", choices=MODELS)
    parser.add_argument("--case-id", action="append", help="run only the named case for an isolated diagnostic")
    parser.add_argument("--reasoning-effort", default="medium")
    parser.add_argument("--codex", default="codex")
    parser.add_argument("--timeout-seconds", type=int, default=600)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--resume-incomplete", action="store_true")
    parser.add_argument("--qualification-id")
    parser.add_argument("--retry-run-errors", action="store_true")
    parser.add_argument("--fail-fast", action=argparse.BooleanOptionalAction, default=None)
    return parser.parse_args()


def configure_run(args: argparse.Namespace) -> argparse.Namespace:
    """Bind diagnostic or qualification semantics before any external call."""

    args.run_kind = "diagnostic" if getattr(args, "case_id", None) else "qualification"
    qualification_id = getattr(args, "qualification_id", None)
    if args.run_kind == "qualification" and not qualification_id:
        raise ValueError("formal closure runs require --qualification-id")
    if qualification_id and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{2,79}", qualification_id):
        raise ValueError("qualification id must use 3-80 letters, digits, dots, underscores, or hyphens")
    if getattr(args, "fail_fast", None) is None:
        args.fail_fast = args.run_kind == "qualification"
    return args


def can_retry_run_error(status: str, completed_attempts: int, enabled: bool) -> bool:
    """Permit one bounded host retry without resampling semantic failures."""

    return status == "RUN_ERROR" and enabled and completed_attempts < 2


def should_schedule_host_retry(
    status: str, completed_attempts: int, enabled: bool, stop_scheduling: bool,
) -> bool:
    """Never claim a retry after fail-fast has stopped new scheduling."""

    return not stop_scheduling and can_retry_run_error(status, completed_attempts, enabled)


def digest_json(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def runtime_tree_digest() -> str:
    """Bind evidence to the exact installable Skill tree used by every clean agent."""

    digest = hashlib.sha256()
    files: list[Path] = []
    for relative in RUNTIME_ITEMS:
        source = ROOT / relative
        files.extend([source] if source.is_file() else source.rglob("*"))
    for path in sorted(
        (item for item in files if item.is_file() and "__pycache__" not in item.parts and item.suffix != ".pyc"),
        key=lambda item: item.relative_to(ROOT).as_posix(),
    ):
        relative = path.relative_to(ROOT).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        content = path.read_bytes()
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def closure_runner_digest() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def normalized_review_feedback(item: Mapping[str, Any]) -> list[str]:
    """Keep user intent hard without turning regression examples into exact prose."""

    return [
        str(item["instruction"]),
        *(
            f"必须修复的性质（按语义验收，除非用户明确要求原样）：{value}"
            for value in item.get("regressions", [])
        ),
        *(f"必须保留的语义：{value}" for value in item.get("correct_parts", [])),
    ]


def registry() -> Registry:
    value = Registry()
    for path in CONTRACTS.glob("*.schema.json"):
        schema = json.loads(path.read_text(encoding="utf-8"))
        value = value.with_resource(schema["$id"], Resource.from_contents(schema))
    return value


def validate_schema(name: str, value: Any) -> None:
    schema = json.loads((CONTRACTS / name).read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema, registry=registry()).validate(value)


def install_candidate(codex_home: Path) -> None:
    destination = codex_home / "skills" / "human-readable-technical-writing"
    destination.mkdir(parents=True, exist_ok=True)
    for relative in RUNTIME_ITEMS:
        source = ROOT / relative
        target = destination / relative
        if source.is_dir():
            shutil.copytree(source, target)
        elif source.exists():
            shutil.copy2(source, target)


def event_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from event_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from event_strings(item)


def access_event_strings(item: dict[str, Any]) -> Iterable[str]:
    """Yield only executed access targets, never command output or model prose."""

    item_type = item.get("type")
    if item_type == "command_execution":
        for key in ("command", "path"):
            if isinstance(item.get(key), str):
                yield item[key]
    elif item_type == "file_read":
        for key in ("path", "uri"):
            if isinstance(item.get(key), str):
                yield item[key]
    elif item_type == "tool_call":
        for key in ("arguments", "input", "path", "uri", "command"):
            if key in item:
                yield from event_strings(item[key])


def normalize_windows_path(value: str) -> str:
    """Normalize JSON-escaped and mixed-separator Windows paths for boundary checks."""

    normalized = value.rstrip(" )],").replace("/", "\\")
    while "\\\\" in normalized:
        normalized = normalized.replace("\\\\", "\\")
    return normalized.lower()


def access_violations(events: list[dict[str, Any]], allowed_roots: list[Path]) -> list[str]:
    allowed = [normalize_windows_path(str(path.resolve())) for path in allowed_roots]
    violations: set[str] = set()
    for event in events:
        item = event.get("item") if isinstance(event, dict) else None
        if not isinstance(item, dict) or item.get("type") not in {"command_execution", "file_read", "tool_call"}:
            continue
        for text in access_event_strings(item):
            if item.get("type") == "command_execution" and re.search(
                r"(?i)(?:^|\s)(?:curl|wget|ssh|scp|sftp|Invoke-WebRequest|Invoke-RestMethod|iwr)(?:\s|$)", text,
            ):
                violations.add(f"prohibited network command: {text[:160]}")
            for match in re.findall(r"[A-Za-z]:\\[^\r\n\"']+", text):
                normalized = normalize_windows_path(match)
                infrastructure = (
                    "\\.cache\\codex-runtimes\\" in normalized
                    or "\\appdata\\local\\openai\\codex\\runtimes\\" in normalized
                )
                if not any(normalized.startswith(root) for root in allowed) and not infrastructure:
                    violations.add(match.rstrip(" )],"))
    return sorted(violations)


def preservation_snapshot(text: str) -> dict[str, Any]:
    """Freeze components and distinct numeric facts that a local repair must not disturb."""

    numeric_text = "\n".join(
        re.sub(r"^\s*(?:#{1,6}\s+)?\d+(?:\.\d+)*[.)]?\s+", "", line)
        for line in text.splitlines()
    )
    return {
        "numbers": sorted(set(re.findall(r"(?<![A-Za-z0-9])[-+]?\d+(?:[.:]\d+)*(?:%|°C|\s*(?:V|万|项|分钟|个月))?", numeric_text))),
        "fenced_blocks": re.findall(r"```[^\n]*\n.*?```", text, flags=re.DOTALL),
        "table_rows": [line for line in text.splitlines() if line.lstrip().startswith("|")],
        "image_links": re.findall(r"!\[[^\]]*\]\([^\n)]+\)", text),
    }


def parse_events(stdout: str) -> tuple[list[dict[str, Any]], str, str | None]:
    events: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    messages = [
        event["item"] for event in events
        if event.get("type") == "item.completed"
        and isinstance(event.get("item"), dict)
        and event["item"].get("type") == "agent_message"
    ]
    body = str(messages[-1].get("text", "")) if messages else ""
    thread_id = None
    for event in events:
        if event.get("type") in {"thread.started", "thread.created"}:
            thread_id = event.get("thread_id") or event.get("threadId")
        if thread_id:
            break
    return events, body, str(thread_id) if thread_id else None


def decode_process_output(value: bytes | str | None) -> str:
    """Decode Codex pipes without corrupting Chinese on Windows code-page output."""

    if value is None:
        return ""
    if isinstance(value, str):
        return value
    for encoding in ("utf-8", "gb18030"):
        try:
            return value.decode(encoding)
        except UnicodeDecodeError:
            continue
    return value.decode("utf-8", errors="replace")


def run_codex(command: list[str], environment: dict[str, str], timeout: int) -> dict[str, Any]:
    try:
        process = subprocess.run(
            command, text=False, capture_output=True,
            timeout=timeout, env=environment, check=False,
        )
        stdout = decode_process_output(process.stdout)
        stderr = decode_process_output(process.stderr)
        exit_code = process.returncode
    except subprocess.TimeoutExpired as error:
        stdout = decode_process_output(error.stdout)
        stderr = decode_process_output(error.stderr) + "\nTIMEOUT"
        exit_code = 124
    events, body, thread_id = parse_events(stdout)
    return {"exit_code": exit_code, "stdout": stdout, "stderr": stderr, "events": events, "body": body, "thread_id": thread_id}


def initial_prompt(request: dict[str, Any], seed: str | None, feedback: list[str]) -> str:
    seed_instruction = ""
    if seed is not None:
        seed_instruction = f"""
This is a legacy pre-closure draft. Preserve it exactly as the initial answer in this first response. Do not repair it yet. Read the current Skill and compile the required manifest around this exact answer so later closure turns can apply minimal patches.

LEGACY_DRAFT:
{seed}
"""
    return f"""Use the installed $human-readable-technical-writing Skill for one isolated Chinese writing case.

Read the complete Skill entrypoint and every file it requires for this request. You have no conversation history, expected answer, scoring rubric, or user configuration outside the installed Skill. Do not browse or inspect unrelated files.

Return only the JSON object required by the supplied output schema. The answer is an internal first draft, not a user-approved result. Treat every explicit prior constraint prefixed `必须保留的语义：` as a hard content requirement. Preserve its named fact, condition, range, number, mechanism, relationship, or source unit in substance; an associated location, symptom, or example is not a substitute for the named mechanism or relationship. Treat `必须修复的性质` entries as semantic acceptance properties, not byte-for-byte replacement strings, unless the user's instruction explicitly says 原样、逐字、固定为, or quotes exact required text. Equivalent verbs such as 使用、执行、进行, or 采用 must not fail when the required official term and meaning are preserved. Independently declare every professional term actually used in the answer, every semantic parallel group, section decision, and evidence-boundary visibility decision. For every parallel group, set `required_layout` to `compact_inline` only when the items are genuinely short, tightly related, and permitted to remain on one line under the semicolon rule; otherwise use `indented_list`. Every `item_texts` value must be one exact single-line substring in the answer and must never contain a newline. `rendered_as_indented_list` records the actual answer, not the desired repair. `core_terms` is topic-diversity metadata, not evidence that a phrase is professional. `term_uses` is not a request-term inventory: omit ordinary operational phrases and terms that do not occur in the answer. Do not invent parenthetical English for ordinary phrases. Every declared professional term must provide its verified official English and make `first_use_text` an exact substring containing that English. In a translation, put that complete professional first use at the source-equivalent semantic occurrence; a generic rendering followed by a later glossary entry is not sufficient. For EXPLAIN or TEACHING work, declare every background claim actually needed by the explanation with an explicit source reference or a clearly marked general-knowledge or inference basis; do not leave the required mechanism unsupported. When a material evidence gap needs a next check but no procedure source was supplied, state only a non-factual direction such as `需要进一步核对相关条件`; never invent a measurement, diagnostic step, threshold, or operating procedure. Do not omit a declaration merely because the answer forgot to follow the corresponding rule. Before returning the first draft, apply a component preflight: for IMAGE, state the overall subject and reading start, then cover each effective element's function and its relation to the whole result, not just its location; for TABLE, keep every source header, column, row, cell, order, and value, never add an explanation column or put explanations into data cells, and place decisions and limits outside the table; only claim GitHub centering when the task contract explicitly names the `github_markdown` renderer and supplies actual render evidence.

Explicit prior review constraints for this case:
{json.dumps(feedback, ensure_ascii=False)}

REQUEST_AND_MATERIAL:
{json.dumps(request, ensure_ascii=False, indent=2)}
{seed_instruction}
"""


def seed_manifest_prompt(request: dict[str, Any], seed: str, feedback: list[str]) -> str:
    """Compile evidence and layout declarations while the host owns the immutable draft."""

    return f"""Use the installed $human-readable-technical-writing Skill to compile the manifest for one immutable legacy draft

Read the complete Skill entrypoint and every file it requires for this request. Do not browse or inspect unrelated files
The host already owns and freezes the answer, so your output schema intentionally has no answer field
Return only the manifest JSON required by the supplied schema
Treat `core_terms` as topic-diversity metadata, not a professional-term declaration
Declare only professional terms actually used in the frozen answer; omit ordinary operational phrases
Every declared professional term must provide its verified official English, and `first_use_text` must be an exact answer substring containing that English
Declare every semantic parallel group even when the frozen answer renders it incorrectly
Set `required_layout` to `compact_inline` for genuinely short, tightly related items allowed on one line by the semicolon rule; otherwise use `indented_list`
`rendered_as_indented_list` records the frozen answer's actual layout

EXPLICIT_PRIOR_REVIEW_CONSTRAINTS:
{json.dumps(feedback, ensure_ascii=False)}

REQUEST_AND_MATERIAL:
{json.dumps(request, ensure_ascii=False, indent=2)}

HOST_FROZEN_LEGACY_DRAFT:
{seed}
"""


def required_reference_tokens(request: dict[str, Any]) -> list[str]:
    """Extract stable machine identifiers from user-supplied reference content."""

    tokens: set[str] = set()
    for reference in request.get("references", []):
        content = str(reference.get("content", ""))
        tokens.update(re.findall(
            r"(?<![A-Za-z0-9_])(?=[A-Z0-9_-]*\d)[A-Z][A-Z0-9_-]{1,79}(?![A-Za-z0-9_])",
            content,
        ))
    return sorted(tokens)


def source_and_background_evidence(
    initial: dict[str, Any], seed: str | None, request: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Keep a rejected seed's repair scope distinct from user acceptance."""

    evidence = {
        key: initial[key]
        for key in ("source_units", "support_map", "background_claims")
    }
    evidence["source_text_for_parenthetical_english"] = json.dumps(
        request or {}, ensure_ascii=False, sort_keys=True,
    ) + ("\n" + seed if seed is not None else "")
    evidence["required_reference_tokens"] = required_reference_tokens(request or {})
    if seed is not None:
        evidence["frozen_legacy_draft"] = seed
        evidence["legacy_seed_repair_contract"] = {
            "approval_status": "rejected_as_delivery_not_user_accepted",
            "policy": (
                "Preserve every semantic unit not explicitly identified as wrong in prior "
                "user feedback; repair the identified feedback defects and any directly applicable "
                "current hard-rule defect with the smallest grounded local change. A sourced local "
                "addition required by the current hard contract does not invalidate otherwise correct "
                "legacy content. This repair-scope evidence "
                "does not set approved_by_user and does not override a direct contradiction in "
                "the supplied source."
            ),
        }
    return evidence


def review_prompt(
    request: dict[str, Any], answer: str, manifest: dict[str, Any], feedback: list[str],
    evidence: dict[str, Any] | None = None,
) -> str:
    return f"""Use the installed $human-readable-technical-writing Skill as an independent semantic verifier.

Re-read the Skill, active Lucas profile, term registry, structure rules, component rules, and verification rules. Inspect only this request, current answer, manifest, and SOURCE_AND_BACKGROUND_EVIDENCE supplied in this prompt. Do not inspect the case root, parent run root, sibling worker, sibling reviewer, prior attempt directory, or any file outside this reviewer's own task and installed Skill directories; all case evidence needed for review is already embedded below. Do not rewrite the answer. Return only findings required by the output schema.

Before checking structure or style, build a must-preserve checklist from every PRIOR_USER_FEEDBACK item prefixed `必须保留的语义：` and check each named fact, condition, range, number, mechanism, relationship, and source unit against CURRENT_ANSWER. An associated location, symptom, example, or conclusion is not a substitute for a named mechanism or relationship. Treat `必须修复的性质` entries as semantic acceptance properties, not byte-for-byte strings, unless the user's own instruction explicitly requires 原样、逐字、固定为, or quotes exact required text. Do not fail equivalent verbs such as 使用、执行、进行, or 采用 when the required official term and meaning are preserved. Report every currently discoverable blocking violation in this review; do not stage an already visible rule into a later round. Before returning, inspect the earliest answer occurrence of every `term_uses` entry and verify there—not in a later glossary or definition item—every registered required meaning. Every blocking finding must be grounded in an explicit installed Skill rule, registry entry, source-preservation rule, or prior user feedback. Never invent a style rule or turn an advisory preference into FAIL. Standard Markdown ordered-list markers such as `1.` and `2.` are valid for ordered steps, do not require wording such as “第一步”, and do not require blank lines between sibling items. Every declared `parallel_groups.item_texts` value must be one exact single-line answer substring; a multiline block is an invalid declaration and must be fixed in the same review. When a sentence explains all children in a nested list, verify that it belongs to the parent before the child list; a prose line after the last child at the child's indentation is an incorrect attachment and must be reported in the same review.

Discover undeclared professional terms and parallel groups independently. Apply a strict professional-term threshold: appearing in a technical, financial, operational, or other domain context is not enough. `core_terms`, topic keywords, a frozen legacy draft, a model-authored background claim whose source says no external source was provided, and a generic request to explain wording nearby never prove a stable professional identity or official English form. A phrase triggers the complete professional first-use contract only when the installed registry defines it, independently supplied source evidence gives it a stable formal identity, or the request explicitly identifies that exact phrase as a formal professional term. An installed registry entry's sourced definition and name rationale are valid background support even when CURRENT_MANIFEST omitted or malformed the matching background claim; report the stale manifest as locally fixable instead of calling the registered meaning unsupported. Ordinary modifiers, status labels, task-specific labels, numeric categories, and explanatory phrases remain common language; examples include sync window, pairing window, calibration offset, read-only check, current result, pending item, pre-tax, pressure energy, and pressure release. Explain an ordinary task-specific label naturally in Chinese and remove invented parenthetical English with a local FAIL repair; never return REVIEW_REQUIRED merely because that ordinary label lacks official English. Do not demand invented official English for common language or for words used only inside the explanation of an already declared term. A missing or stale manifest declaration is fixable when a safe token, phrase, sentence, or manifest-only repair can correct it: return FAIL rather than REVIEW_REQUIRED merely because the current manifest is incomplete. Do not split a registered term's established compound action or a joint condition into a nested list merely because Chinese uses `并`; phrases such as `隔离泵的能源并上锁` and `泵停止并完成上锁隔离后` may remain inline when their parts jointly define one method or state and are not independently ordered items.

Use SOURCE_AND_BACKGROUND_EVIDENCE when judging added explanation. A declared background claim with an explicit source reference or clearly marked general-knowledge nature is not an unsupported source claim merely because it is absent from CURRENT_MANIFEST. Do not require a blockquote for a user-supplied identifier or preservation token unless the answer is actually presenting it as quoted evidence. A human-facing audit or review number such as `B23` is not automatically a code identifier and does not require backticks. A same-line form such as `复核编号 B23：抽查 18 张` is compact audit metadata followed by its value, not a colon pseudo-heading. A natural complete sentence that introduces a following list, quotation, or example may end with a colon and is not a colon pseudo-heading. Very short, tightly related audit facts may remain on one line separated by semicolons when the manifest declares `compact_inline`; do not force them into a list merely because there are several facts. In a translation, when a source phrase maps to a declared professional term, require the complete professional first-use form at that source-equivalent semantic occurrence; a generic rendering followed by a later glossary definition does not satisfy source-term preservation. For `COMPRESS + NONE`, when the source itself already states an unchecked or unknown range, preserving that limitation is sufficient; do not invent an impact claim, recommendation, or next-check action that the source does not support. For IMAGE, inspect the overall subject, reading start, every effective element's function, the relationships between elements, the supported impact, and the limits; a location-only statement is incomplete when the profile requires a function. For TABLE, inspect the original header, columns, rows, cells, order, and values before judging explanation; an added decision or explanation column is not a harmless summary when it changes the source structure. Require GitHub render evidence only when the request or manifest explicitly selects the `github_markdown` renderer; otherwise do not invent a visual-evidence blocker. In this first review pass, explicitly inspect every parenthetical English phrase against `term_uses` and supplied evidence, then inspect every evidence-gap sentence for the limitation, its actual impact, and the next-check direction. If no procedure source was supplied, reject any newly invented measurement, diagnostic step, threshold, or operating procedure and require only a non-factual direction. Report those findings together with all other currently visible blockers. Check source completeness, facts, conditions, scope, numbers, exceptions, all parts of professional first use, title necessity and level, colon pseudo-headings, semicolon scope, internal evidence-label leakage, and whether each proposed repair can stay within one token, phrase, or sentence. Use REVIEW_REQUIRED only when no safe token, phrase, sentence, or manifest-only repair exists.

For a frozen legacy seed, SOURCE_AND_BACKGROUND_EVIDENCE includes `frozen_legacy_draft` and `legacy_seed_repair_contract`. Treat every semantic unit in that draft not explicitly identified as wrong by prior feedback as immutable user-supplied repair context. Do not remove or challenge such a unit merely because it lacks a new external source. “The content is correct” preserves those semantic units; it does not prohibit a sourced local addition required by a directly applicable current hard contract, such as completing professional first use. This scopes the minimum repair only: it does not make the answer user-accepted and does not override a direct contradiction in the supplied source. When prior feedback explicitly preserves a mechanism or explanation from a frozen legacy draft, treat that named content as user-supplied preservation evidence rather than demanding a new external source. If an important limitation needs a next check but no procedure source is supplied, use only a natural non-factual direction such as “需要进一步核对相关条件”; do not invent diagnostic measurements or procedures. When CURRENT_MANIFEST sets boundary visibility to `internal` and prior feedback requires the boundary to stay hidden, do not demand user-visible boundary prose merely because the internal source ledger has limited coverage; override `internal` only for a concrete conclusion, operation, or safety consequence supported by the request.

PRIOR_USER_FEEDBACK:
{json.dumps(feedback, ensure_ascii=False)}

REQUEST:
{json.dumps(request, ensure_ascii=False, indent=2)}

SOURCE_AND_BACKGROUND_EVIDENCE:
{json.dumps(evidence or {}, ensure_ascii=False, indent=2)}

CURRENT_MANIFEST:
{json.dumps(manifest, ensure_ascii=False, indent=2)}

CURRENT_ANSWER:
{answer}
"""


def review_completion_prompt(first_findings: list[dict[str, Any]]) -> str:
    """Force one same-session completeness pass before the first repair transaction."""

    return f"""The answer and manifest have not changed since your first semantic review

Perform one same-session completeness pass before the repair Agent sees any finding
Return the same review schema and include every still-valid first-pass finding plus every blocker you missed
Do not rewrite the answer and do not defer a visible problem to a later repair round

Check these dimensions independently and in this order:
1. source facts, conditions, scope, numbers, exceptions, and required identifiers
2. every professional term's grounded identity and complete first semantic occurrence
3. every parallel group, nested list, semicolon, and natural list introduction
4. section necessity, heading level, and colon pseudo-heading boundaries
5. image overview, reading start, per-element function, relationships, impact, table source structure, and applicable render evidence
6. evidence limitation, actual impact, next-check direction, and unsupported procedures
7. minimum patch scope and whether all current findings can be repaired together

FIRST_PASS_FINDINGS:
{json.dumps(first_findings, ensure_ascii=False, indent=2)}
"""


@lru_cache(maxsize=1)
def registered_official_english() -> frozenset[str]:
    """Return official English forms grounded by the installed term registry."""

    payload = yaml.safe_load((ROOT / "registries" / "terms.yaml").read_text(encoding="utf-8"))
    values: set[str] = set()
    for item in payload["registry"]["terms"].values():
        if item.get("official_english"):
            values.add(str(item["official_english"]))
        official_form = str(item.get("official_form", ""))
        values.update(re.findall(r"[（(]([A-Za-z][A-Za-z0-9'’+./ -]{1,100})[）)]", official_form))
    return frozenset(values)


@lru_cache(maxsize=1)
def registered_term_markers() -> frozenset[str]:
    """Return stable human-visible forms that identify a registered term."""

    payload = yaml.safe_load((ROOT / "registries" / "terms.yaml").read_text(encoding="utf-8"))
    values: set[str] = set(registered_official_english())
    for item in payload["registry"]["terms"].values():
        official_form = str(item.get("official_form", "")).strip()
        if official_form:
            values.add(official_form)
            chinese_form = re.split(r"[（(]", official_form, maxsplit=1)[0].strip()
            if len(chinese_form) >= 2:
                values.add(chinese_form)
    return frozenset(values)


def term_declaration_grounded(term: dict[str, Any], evidence: dict[str, Any]) -> bool:
    """Do not let a model-authored manifest certify its own official English."""

    english = term.get("official_english")
    if not english:
        return True
    value = str(english)
    return (
        value in registered_official_english()
        or value in str(evidence.get("source_text_for_parenthetical_english", ""))
    )


def unsupported_term_declaration_findings(
    answer: str, manifest: dict[str, Any], evidence: dict[str, Any],
) -> list[dict[str, Any]]:
    """Reject unsupported official-English claims even when the model declared them itself."""

    findings: list[dict[str, Any]] = []
    for index, term in enumerate(manifest.get("term_uses", []), start=1):
        if term_declaration_grounded(term, evidence):
            continue
        english = str(term.get("official_english", ""))
        parenthetical = next(
            (value for value in (f"（{english}）", f"({english})") if value in answer),
            english,
        )
        findings.append({
            "finding_id": f"UNVERIFIED_OFFICIAL_CASE:TERM-{index:03d}",
            "rule_id": "UNVERIFIED_OFFICIAL_CASE",
            "status": "FAIL",
            "location": f"CURRENT_MANIFEST.term_uses[{index - 1}]",
            "old_text": parenthetical,
            "reason": "模型自报的官方英文既不在术语表中，也不在用户请求或冻结种子中；删除新增括号英文和对应术语声明，不要仅调整大小写",
            "repair_scope": "phrase",
            "source": "deterministic",
        })
    return findings


def filter_ungrounded_professional_findings(
    findings: list[dict[str, Any]], manifest: dict[str, Any], evidence: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Ignore reviewer attempts to promote unsupported topic labels into professional terms."""

    grounded_terms = [
        item for item in manifest.get("term_uses", [])
        if term_declaration_grounded(item, evidence)
    ]
    source_text = str(evidence.get("source_text_for_parenthetical_english", ""))
    registry_markers = registered_term_markers()
    kept: list[dict[str, Any]] = []
    discarded: list[dict[str, Any]] = []
    for item in findings:
        rule_id = str(item.get("rule_id", "")).upper()
        if "PROFESSIONAL_FIRST_USE" not in rule_id and "TERM_FIRST_USE" not in rule_id:
            kept.append(item)
            continue
        target = f"{item.get('location', '')}\n{item.get('old_text', '')}"
        grounded = any(
            str(term.get("term", "")) in target
            or str(term.get("official_english", "")) in target
            for term in grounded_terms
            if term.get("term") or term.get("official_english")
        )
        grounded = grounded or any(marker in target for marker in registry_markers)
        target_english = re.findall(r"[A-Za-z][A-Za-z0-9'’+./ -]{1,100}", target)
        grounded = grounded or any(value.strip() in source_text for value in target_english)
        if grounded:
            kept.append(item)
        else:
            discarded.append(item)
    return kept, discarded


def patch_prompt(
    answer: str,
    manifest: dict[str, Any],
    findings: list[dict[str, Any]],
    previous_patch_rejection: str | None = None,
) -> str:
    nodes = [{"node_id": node, "text": answer[start:end]} for node, (start, end) in line_nodes(answer).items()]
    rejection = (
        "\nPREVIOUS_PATCH_REJECTION:\n"
        f"{previous_patch_rejection}\n"
        "Correct that contract error in this attempt.\n"
        if previous_patch_rejection else ""
    )
    return f"""Re-read the installed Skill rules named by these findings. Return only the exact patch object required by the output schema.

Patch only the smallest complete erroneous unit. Allowed repair_scope values are token, phrase, and sentence. Do not replace a paragraph, section, adjacent sections, blueprint, or whole answer. A repair for a must-preserve finding must restore the named fact, condition, range, number, mechanism, relationship, or source unit in substance; do not replace it with an associated location, symptom, example, or conclusion. Fix every supplied deterministic answer finding in this transaction; when answer findings and manifest findings coexist, submit the required answer patches and the corrected manifest together rather than returning a manifest-only change. One sentence patch may fix several supplied findings: join their exact finding IDs with `+` in `identity.finding_id`, and never add an unknown ID. When a colon pseudo-heading must become a Markdown heading, replace the complete line and put the marker before the title, for example `## 操作`; never append `##` after the title or replace only the colon. Put a professional term's official English and complete required explanation at that term's earliest semantic occurrence; never rely on a later glossary item to complete first use, and never attach the English to a nearby verb such as `注意`. When deleting one complete list item, bind `old_text` to the whole list line including its marker and terminating newline, then replace that line with an empty string; do not leave an empty list marker or an extra blank line for a later repair round. When converting ordinary prose into a new top-level block list, keep or add the colon on its complete introductory sentence and include exactly one required blank line around that top-level block in the same sentence patch. When adding a nested list inside an existing list item, keep the parent and child list contiguous with no blank line; an indented continuation belonging to that item also stays contiguous. If one sentence explains every child in a nested list, put that common explanation on the parent line before the children; never leave it after the last child at the child's indentation. Do not create a missing-colon, missing-block-separator, list-internal-blank, or ambiguous nested-continuation defect for a later round. When removing a Chinese full stop between adjacent sentences, preserve a valid separator and never concatenate the final word of one sentence with the subject of the next. Never use a Chinese semicolon as the last character of a paragraph or list item. Preserve non-exhaustive scope markers such as 等位置, 等情况, 其他, 不限于, or 不止 when rearranging content unless the finding explicitly authorizes changing that scope. Every `updated_manifest.parallel_groups.item_texts` value must be one exact single-line substring in the patched answer and must never contain a newline. These are sentence-scope patches, not paragraph rewrites. Every answer patch in this transaction must bind the same CURRENT_SHA256 shown below, one supplied line node, exact old text, exact occurrence count, preservation requirements, and validators. Count `expected_occurrences` for the literal `old_text` inside the selected line node, not across the whole answer, and verify that count immediately before submitting. Do not use a hash predicted from an earlier patch in the same batch. Before submitting, remove every patch whose `old_text` and `new_text` are identical; one no-op invalidates the whole transaction. Update the manifest to describe the patched answer without changing unrelated declarations. If every remaining defect is only a stale manifest declaration and the answer is already correct, return an empty `patches` array and change only `updated_manifest`; otherwise return at least one real answer patch.
{rejection}

CURRENT_SHA256:
{sha256_text(answer)}

LINE_NODES:
{json.dumps(nodes, ensure_ascii=False, indent=2)}

FINDINGS:
{json.dumps(findings, ensure_ascii=False, indent=2)}

CURRENT_MANIFEST:
{json.dumps(manifest, ensure_ascii=False, indent=2)}

CURRENT_ANSWER:
{answer}
"""


def initial_contract_findings(payload: dict[str, Any]) -> list[str]:
    """Check set and uniqueness invariants unsupported by strict model schemas."""

    findings: list[str] = []
    source_units = payload["source_units"]
    support_map = payload["support_map"]
    if len(source_units) != len(set(source_units)):
        findings.append("source_units contains duplicates")
    if len(support_map) != len(set(support_map)):
        findings.append("support_map contains duplicates")
    if set(source_units) != set(support_map):
        findings.append("support_map must exactly cover source_units")
    group_ids = [item["group_id"] for item in payload["parallel_groups"]]
    if len(group_ids) != len(set(group_ids)):
        findings.append("parallel group identifiers are not unique")
    if any(len(item["item_texts"]) != len(set(item["item_texts"])) for item in payload["parallel_groups"]):
        findings.append("one parallel group contains duplicate item text")
    levels = payload["section_plan"]["heading_levels"]
    if len(levels) != len(set(levels)):
        findings.append("heading levels contain duplicates")
    answer = payload["answer"]
    for item in payload["term_uses"]:
        first_use = item["first_use_text"]
        if not item.get("official_english"):
            findings.append(
                f"term {item['term']}: a professional term declaration requires verified official English; remove the entry if it is ordinary language"
            )
        if first_use not in answer:
            findings.append(f"term {item['term']}: first_use_text is not an exact answer substring; remove the entry if the term is absent")
        if item.get("official_english") and item["official_english"] not in first_use:
            findings.append(f"term {item['term']}: official_english is absent from first_use_text")
    return findings


def manifest_retry_prompt(payload: dict[str, Any], findings: list[str], *, manifest_only: bool = False) -> str:
    """Correct only unsupported schema invariants while freezing the answer text."""

    visible_payload = {key: value for key, value in payload.items() if key != "answer"} if manifest_only else payload
    answer_instruction = "The host owns the frozen answer and the output schema has no answer field" if manifest_only else "Preserve the answer string byte-for-byte"
    return f"""The initial JSON passed the model output schema but failed local manifest invariants

Return the same output schema again
{answer_instruction}
Correct only the declared arrays or manifest fields named by these findings
Do not repair or rewrite the answer in this turn

FINDINGS:
{json.dumps(findings, ensure_ascii=False, indent=2)}

CURRENT_OUTPUT:
{json.dumps(visible_payload, ensure_ascii=False, indent=2)}
"""


def normalize_patch_ids(payload: dict[str, Any], start: int) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Assign run-global evidence identifiers without changing patch semantics."""

    normalized = copy.deepcopy(payload)
    mappings: list[dict[str, str]] = []
    for offset, patch in enumerate(normalized["patches"]):
        original = patch["identity"]["patch_id"]
        assigned = f"PATCH-{start + offset:03d}"
        patch["identity"]["patch_id"] = assigned
        mappings.append({"submitted": original, "assigned": assigned})
    return normalized, mappings


def referenced_finding_ids(value: str) -> set[str]:
    """Expand a composite reference used when one sentence patch fixes several findings."""

    return {item for item in value.split("+") if item}


def validate_heading_patch_direction(
    answer: str, patches: list[dict[str, Any]], nodes: dict[str, tuple[int, int]],
) -> None:
    """Reject Markdown markers appended after a label instead of placed before it."""

    for patch in patches:
        finding_ids = referenced_finding_ids(str(patch["identity"]["finding_id"]))
        new_text = str(patch["replacement"]["new_text"])
        if not any(value.startswith("COLON_PSEUDO_HEADING:") for value in finding_ids):
            continue
        if "#" not in new_text:
            continue
        node_start, node_end = nodes[str(patch["target"]["node_id"])]
        node_text = answer[node_start:node_end]
        old_text = str(patch["replacement"]["old_text"])
        if old_text.rstrip("\r\n") != node_text.rstrip("\r\n") or not re.match(r"^#{1,6}\s+\S", new_text):
            raise PatchError(
                "Markdown heading repair must replace the complete line and place the marker before the title"
            )


def apply_closure_transaction(
    answer: str, manifest: dict[str, Any], patch_payload: dict[str, Any],
    evidence: dict[str, Any] | None = None,
    findings: list[dict[str, Any]] | None = None,
) -> str:
    """Apply answer patches or a non-worsening manifest-only semantic repair."""

    patches = patch_payload["patches"]
    if patches:
        nodes = line_nodes(answer)
        validate_heading_patch_direction(answer, patches, nodes)
        return apply_minimal_transaction(answer, patches, nodes)
    updated_manifest = patch_payload["updated_manifest"]
    if updated_manifest == manifest:
        raise PatchError("empty closure transaction did not change the manifest")
    before_findings = closure_deterministic_findings(answer, manifest, evidence or {})
    after_findings = closure_deterministic_findings(answer, updated_manifest, evidence or {})
    if len(after_findings) > len(before_findings):
        raise PatchError("manifest-only repair introduced deterministic findings")
    if len(after_findings) == len(before_findings):
        before_text = json.dumps(manifest, ensure_ascii=False, sort_keys=True)
        after_text = json.dumps(updated_manifest, ensure_ascii=False, sort_keys=True)
        manifest_findings = [
            item for item in (findings or [])
            if "MANIFEST" in str(item.get("location", "")).upper()
            and str(item.get("old_text", ""))
        ]
        if not any(
            before_text.count(str(item["old_text"])) > after_text.count(str(item["old_text"]))
            for item in manifest_findings
        ):
            raise PatchError("manifest-only repair was not bound to a supplied manifest finding")
    return answer


def evidence_scope_findings(answer: str, evidence: dict[str, Any]) -> list[dict[str, Any]]:
    """Protect explicit non-exhaustive scope in declared background claims."""

    findings: list[dict[str, Any]] = []
    marker = r"等(?:位置|情况|项目|内容|原因|因素|条件|范围|方式|处|方面|环节|部位|[，、和与]|$)"
    for index, item in enumerate(evidence.get("background_claims", []), start=1):
        claim = str(item.get("claim", ""))
        if re.search(marker, claim) and not re.search(rf"{marker}|其他|不限于|不止", answer):
            findings.append({
                "finding_id": f"EVIDENCE_SCOPE_MARKER:BG-{index:03d}:等",
                "rule_id": "EVIDENCE_SCOPE_MARKER",
                "status": "FAIL",
                "location": f"BACKGROUND-{index:03d}",
                "old_text": "等",
                "reason": "已登记背景主张的非穷尽范围没有保留在答案中",
                "repair_scope": "phrase",
                "source": "deterministic",
            })
    return merge_findings(findings)


def required_reference_findings(answer: str, evidence: dict[str, Any]) -> list[dict[str, Any]]:
    """Reject loss of stable identifiers supplied in request references."""

    return [
        {
            "finding_id": f"PROTECTED_TOKEN_PRESENCE:REFERENCE:{token}",
            "rule_id": "PROTECTED_TOKEN_PRESENCE",
            "status": "FAIL",
            "location": "DOCUMENT",
            "old_text": token,
            "reason": f"用户参考材料要求保留机器标识 {token}，当前答案缺失该标识",
            "repair_scope": "token",
            "source": "deterministic",
        }
        for token in evidence.get("required_reference_tokens", [])
        if token not in answer
    ]


def closure_deterministic_findings(
    answer: str, manifest: dict[str, Any], evidence: dict[str, Any],
) -> list[dict[str, Any]]:
    supported_source = evidence.get("source_text_for_parenthetical_english")
    return merge_findings(
        deterministic_findings(
            answer,
            manifest,
            str(supported_source) if supported_source is not None else None,
        ),
        evidence_scope_findings(answer, evidence),
        required_reference_findings(answer, evidence),
        unsupported_term_declaration_findings(answer, manifest, evidence),
    )


def parse_json_body(result: dict[str, Any], schema_name: str) -> dict[str, Any]:
    if result["exit_code"] != 0:
        raise RuntimeError(f"Codex exit code {result['exit_code']}: {result['stderr'][-500:]}")
    value = json.loads(result["body"].strip())
    validate_schema(schema_name, value)
    return value


def start_agent(
    args: argparse.Namespace, model: str, codex_home: Path, task_root: Path,
    prompt: str, schema_name: str,
) -> dict[str, Any]:
    environment = os.environ.copy()
    environment["CODEX_HOME"] = str(codex_home)
    environment["AIALRA_EVAL_SKILL_ROOT"] = str(
        codex_home / "skills" / "human-readable-technical-writing"
    )
    safe_prompt = f"{CLEAN_SKILL_PATH_INSTRUCTION}\n\n{prompt}"
    schema_path = codex_home / "skills" / "human-readable-technical-writing" / "contracts" / schema_name
    command = [
        args.codex, "exec", "--json", "--skip-git-repo-check", "--ignore-user-config",
        "--ignore-rules", "-c", 'web_search="disabled"', "--model", model,
        "-c", f'model_reasoning_effort="{args.reasoning_effort}"',
        "--approve-for-me", "--output-schema", str(schema_path),
        "-C", str(task_root), safe_prompt,
    ]
    for feature in CLEAN_AGENT_DISABLED_FEATURES:
        command[2:2] = ["--disable", feature]
    return run_codex(command, environment, args.timeout_seconds)


def resume_agent(
    args: argparse.Namespace, model: str, codex_home: Path, session_id: str,
    prompt: str, schema_name: str,
) -> dict[str, Any]:
    environment = os.environ.copy()
    environment["CODEX_HOME"] = str(codex_home)
    environment["AIALRA_EVAL_SKILL_ROOT"] = str(
        codex_home / "skills" / "human-readable-technical-writing"
    )
    safe_prompt = f"{CLEAN_SKILL_PATH_INSTRUCTION}\n\n{prompt}"
    schema_path = codex_home / "skills" / "human-readable-technical-writing" / "contracts" / schema_name
    command = [
        args.codex, "exec", "resume", "--json", "--ignore-user-config", "-c", 'web_search="disabled"',
        "--ignore-rules", "--skip-git-repo-check",
        "--model", model, "-c", f'model_reasoning_effort="{args.reasoning_effort}"',
        "--output-schema", str(schema_path), session_id, safe_prompt,
    ]
    for feature in CLEAN_AGENT_DISABLED_FEATURES:
        command[3:3] = ["--disable", feature]
    return run_codex(command, environment, args.timeout_seconds)


def semantic_review(
    args: argparse.Namespace, model: str, case_root: Path, round_number: int,
    request: dict[str, Any], answer: str, manifest: dict[str, Any], feedback: list[str], auth: Path,
    evidence: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    reviewer_root = case_root / f"reviewer-{round_number}"
    home = reviewer_root / "home"
    task = reviewer_root / "task"
    home.mkdir(parents=True)
    task.mkdir(parents=True)
    shutil.copy2(auth, home / "auth.json")
    install_candidate(home)
    result = start_agent(
        args, model, home, task,
        review_prompt(request, answer, manifest, feedback, evidence),
        "closure-review-output.schema.json",
    )
    payload = parse_json_body(result, "closure-review-output.schema.json")
    review_results = [result]
    raw_findings = list(payload["findings"])
    if round_number == 1:
        if not result.get("thread_id"):
            raise RuntimeError("reviewer session id is missing; completeness rescan is impossible")
        completion_result = resume_agent(
            args, model, home, result["thread_id"],
            review_completion_prompt(raw_findings), "closure-review-output.schema.json",
        )
        completion_payload = parse_json_body(completion_result, "closure-review-output.schema.json")
        review_results.append(completion_result)
        raw_findings = merge_findings(raw_findings, completion_payload["findings"])
    raw_findings, host_filtered = filter_ungrounded_professional_findings(
        raw_findings, manifest, evidence or {},
    )
    findings = []
    for index, raw in enumerate(raw_findings, start=1):
        item = dict(raw)
        item["finding_id"] = f"SEM-{round_number:02d}-{index:03d}"
        item["source"] = "semantic"
        findings.append(item)
    combined_result = dict(result)
    combined_result["events"] = [
        event for review_result in review_results for event in review_result["events"]
    ]
    combined_result["review_passes"] = len(review_results)
    combined_result["host_filtered_findings"] = host_filtered
    violations = access_violations(combined_result["events"], [reviewer_root])
    return findings, combined_result, violations


def run_case(
    args: argparse.Namespace, request: dict[str, Any], model: str, seed: str | None,
    feedback: list[str], auth: Path, run_root: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    case_id = request["case_id"]
    model_code = MODEL_CODES[model]
    case_root = run_root / f"{case_id}-{model_code}"
    if case_root.exists() and not (case_root / "result.json").exists():
        recovery = 1
        while (run_root / f"{case_id}-{model_code}.recovery-{recovery:02d}").exists():
            recovery += 1
        case_root = run_root / f"{case_id}-{model_code}.recovery-{recovery:02d}"
    worker_home = case_root / "worker" / "home"
    worker_task = case_root / "worker" / "task"
    worker_home.mkdir(parents=True)
    worker_task.mkdir(parents=True)
    shutil.copy2(auth, worker_home / "auth.json")
    install_candidate(worker_home)

    initial_schema = "forward-manifest-output.schema.json" if seed is not None else "forward-generation-output.schema.json"
    prompt = seed_manifest_prompt(request, seed, feedback) if seed is not None else initial_prompt(request, None, feedback)
    initial_result = start_agent(
        args, model, worker_home, worker_task,
        prompt, initial_schema,
    )
    initial_payload = parse_json_body(initial_result, initial_schema)
    initial = {"answer": seed, **initial_payload} if seed is not None else initial_payload
    session_id = initial_result["thread_id"]
    if not session_id:
        raise RuntimeError("worker session id is missing; exact resume is impossible")
    frozen_initial_answer = initial["answer"]
    contract_repairs: list[dict[str, Any]] = []
    violations = access_violations(initial_result["events"], [worker_home.parent])
    for contract_round in range(1, 3):
        contract_findings = initial_contract_findings(initial)
        if not contract_findings:
            break
        retry_schema = "forward-manifest-output.schema.json" if seed is not None else "forward-generation-output.schema.json"
        retry_result = resume_agent(
            args, model, worker_home, session_id,
            manifest_retry_prompt(initial, contract_findings, manifest_only=seed is not None), retry_schema,
        )
        corrected_payload = parse_json_body(retry_result, retry_schema)
        corrected = {"answer": seed, **corrected_payload} if seed is not None else corrected_payload
        if corrected["answer"] != frozen_initial_answer:
            raise ValueError("manifest-only retry changed the frozen initial answer")
        violations.extend(access_violations(retry_result["events"], [worker_home.parent]))
        contract_repairs.append({"round": contract_round, "findings": contract_findings, "events": retry_result["events"]})
        initial = corrected
    remaining_contract = initial_contract_findings(initial)
    if remaining_contract:
        raise ValueError("initial manifest remains invalid: " + " | ".join(remaining_contract))
    if seed is not None and initial["answer"] != seed:
        raise ValueError("legacy pre-closure draft changed before the repair loop")
    answer = initial["answer"]
    manifest = {key: initial[key] for key in ("term_uses", "parallel_groups", "section_plan", "boundary_visibility")}
    evidence = source_and_background_evidence(initial, seed, request)
    initial_manifest = json.loads(json.dumps(manifest, ensure_ascii=False))
    first_hash = sha256_text(answer)
    first_preservation = preservation_snapshot(answer)
    rounds: list[dict[str, Any]] = []
    private_iterations: list[dict[str, Any]] = []
    status = "FAIL"
    next_patch_number = 1
    previous_patch_rejection: str | None = None

    for repair_round in range(1, 4):
        before_answer = answer
        deterministic = closure_deterministic_findings(answer, manifest, evidence)
        semantic, review_result, review_violations = semantic_review(
            args, model, case_root, repair_round, request, answer, manifest, feedback, auth, evidence,
        )
        violations.extend(review_violations)
        combined = merge_findings(deterministic, semantic)
        if not combined:
            status = "PASS"
            if rounds:
                rounds[-1]["result_status"] = "PASS"
            private_iterations.append({
                "round": repair_round, "answer": answer, "deterministic": [], "semantic": [],
                "review_events": review_result["events"],
                "review_host_filters": review_result.get("host_filtered_findings", []),
            })
            break
        if any(item.get("status") == "REVIEW_REQUIRED" for item in combined):
            status = "REVIEW_REQUIRED"
            private_iterations.append({
                "round": repair_round, "answer": answer,
                "deterministic": deterministic, "semantic": semantic,
                "review_events": review_result["events"],
                "review_host_filters": review_result.get("host_filtered_findings", []),
            })
            break
        before = sha256_text(answer)
        patch_result = resume_agent(
            args, model, worker_home, session_id,
            patch_prompt(answer, manifest, combined, previous_patch_rejection), "closure-patch-output.schema.json",
        )
        submitted_patch_payload = parse_json_body(patch_result, "closure-patch-output.schema.json")
        allowed_finding_ids = {str(item["finding_id"]) for item in combined}
        submitted_finding_ids = {
            finding_id
            for item in submitted_patch_payload["patches"]
            for finding_id in referenced_finding_ids(str(item["identity"]["finding_id"]))
        }
        patch_payload, patch_id_mapping = normalize_patch_ids(submitted_patch_payload, next_patch_number)
        next_patch_number += len(patch_payload["patches"])
        violations.extend(access_violations(patch_result["events"], [worker_home.parent]))
        try:
            if not submitted_finding_ids <= allowed_finding_ids:
                raise PatchError("one patch references a finding outside the merged review set")
            patched_answer = apply_closure_transaction(answer, manifest, patch_payload, evidence, combined)
        except PatchError as error:
            previous_patch_rejection = str(error)
            rounds.append({
                "round": repair_round, "reread_rules": True,
                "deterministic_finding_ids": [str(item["finding_id"]) for item in deterministic],
                "semantic_finding_ids": [str(item["finding_id"]) for item in semantic],
                "finding_rule_ids": list(dict.fromkeys(str(item["rule_id"]) for item in combined)),
                "patch_ids": [str(item["identity"]["patch_id"]) for item in patch_payload["patches"]],
                "patch_summaries": [
                    {
                        "patch_id": str(item["identity"]["patch_id"]),
                        "finding_id": str(item["identity"]["finding_id"]),
                        "node_id": str(item["target"]["node_id"]),
                        "repair_scope": str(item["authorization"]["repair_scope"]),
                        "summary": str(item["authorization"]["reason"]),
                    }
                    for item in patch_payload["patches"]
                ],
                "before_sha256": before, "after_sha256": before,
                "result_status": "FAIL",
            })
            private_iterations.append({
                "round": repair_round, "answer": answer,
                "deterministic": deterministic, "semantic": semantic,
                "patches": patch_payload["patches"],
                "submitted_patches": submitted_patch_payload["patches"],
                "patch_id_mapping": patch_id_mapping,
                "patch_rejection": previous_patch_rejection,
                "review_events": review_result["events"], "patch_events": patch_result["events"],
                "review_host_filters": review_result.get("host_filtered_findings", []),
            })
            continue
        answer = patched_answer
        manifest = patch_payload["updated_manifest"]
        previous_patch_rejection = None
        remaining = closure_deterministic_findings(answer, manifest, evidence)
        after = sha256_text(answer)
        rounds.append({
            "round": repair_round, "reread_rules": True,
            "deterministic_finding_ids": [str(item["finding_id"]) for item in deterministic],
            "semantic_finding_ids": [str(item["finding_id"]) for item in semantic],
            "finding_rule_ids": list(dict.fromkeys(str(item["rule_id"]) for item in combined)),
            "patch_ids": [str(item["identity"]["patch_id"]) for item in patch_payload["patches"]],
            "patch_summaries": [
                {
                    "patch_id": str(item["identity"]["patch_id"]),
                    "finding_id": str(item["identity"]["finding_id"]),
                    "node_id": str(item["target"]["node_id"]),
                    "repair_scope": str(item["authorization"]["repair_scope"]),
                    "summary": str(item["authorization"]["reason"]),
                }
                for item in patch_payload["patches"]
            ],
            "before_sha256": before, "after_sha256": after,
            "result_status": "FAIL",
        })
        private_iterations.append({
            "round": repair_round, "before_answer": before_answer,
            "after_answer": answer, "deterministic": deterministic, "semantic": semantic,
            "patches": patch_payload["patches"], "submitted_patches": submitted_patch_payload["patches"],
            "patch_id_mapping": patch_id_mapping,
            "review_events": review_result["events"], "patch_events": patch_result["events"],
            "review_host_filters": review_result.get("host_filtered_findings", []),
        })

    if status == "FAIL":
        deterministic = closure_deterministic_findings(answer, manifest, evidence)
        semantic, review_result, review_violations = semantic_review(
            args, model, case_root, 4, request, answer, manifest, feedback, auth, evidence,
        )
        violations.extend(review_violations)
        status = "PASS" if not merge_findings(deterministic, semantic) else "REVIEW_REQUIRED"
        if status == "PASS" and rounds:
            rounds[-1]["result_status"] = "PASS"
        private_iterations.append({
            "round": "final-review", "answer": answer,
            "deterministic": deterministic, "semantic": semantic,
            "review_events": review_result["events"],
            "review_host_filters": review_result.get("host_filtered_findings", []),
        })

    if violations:
        status = "REVIEW_REQUIRED"
    final_preservation = preservation_snapshot(answer)
    preservation_status = "PASS" if first_preservation == final_preservation else "REVIEW_REQUIRED"
    if preservation_status != "PASS":
        status = "REVIEW_REQUIRED"
    closure = {
        "model": model, "worker_session_id": session_id,
        "qualification_id": getattr(args, "qualification_id", None),
        "run_kind": getattr(args, "run_kind", "runtime"),
        "first_draft_sha256": first_hash, "final_sha256": sha256_text(answer),
        "max_repair_rounds": 3, "rounds": rounds, "status": status,
    }
    validate_schema("closure-run.schema.json", closure)
    public = {
        "case_id": case_id, "model": model, "model_code": model_code,
        "qualification_id": getattr(args, "qualification_id", None),
        "run_kind": getattr(args, "run_kind", "runtime"),
        "skill_tree_sha256": getattr(args, "skill_tree_sha256", runtime_tree_digest()),
        "closure_runner_sha256": getattr(args, "closure_runner_sha256", closure_runner_digest()),
        "status": status, "first_draft_sha256": first_hash, "final_sha256": sha256_text(answer),
        "repair_rounds": len(rounds), "first_attempt_hard_errors": len(closure_deterministic_findings(initial["answer"], initial_manifest, evidence)),
        "access_violation_count": len(set(violations)), "preservation_status": preservation_status,
        "preservation_sha256": digest_json(final_preservation), "answer": answer,
        "source_units": initial["source_units"], "support_map": initial["support_map"],
        "background_claims": initial["background_claims"], **manifest, "iterations": closure,
    }
    private = {
        "case_id": case_id, "model": model, "request": request,
        "qualification_id": getattr(args, "qualification_id", None),
        "run_kind": getattr(args, "run_kind", "runtime"),
        "skill_tree_sha256": getattr(args, "skill_tree_sha256", runtime_tree_digest()),
        "closure_runner_sha256": getattr(args, "closure_runner_sha256", closure_runner_digest()),
        "initial": initial, "initial_events": initial_result["events"],
        "manifest_contract_repairs": contract_repairs,
        "iterations": private_iterations, "final_answer": answer,
        "initial_preservation": first_preservation, "final_preservation": final_preservation,
        "access_violations": sorted(set(violations)),
    }
    (case_root / "result.json").write_text(json.dumps({"public": public, "private": private}, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    return public, private


def persist(
    round_dir: Path, private_report: Path, requests: list[dict[str, Any]], models: list[str],
    public_by_key: dict[tuple[str, str], dict[str, Any]], private_by_key: dict[tuple[str, str], dict[str, Any]],
) -> None:
    with WRITE_LOCK:
        keys = [(request["case_id"], model) for request in requests for model in models]
        public = [public_by_key[key] for key in keys if key in public_by_key]
        private = [private_by_key[key] for key in keys if key in private_by_key]
        skill_digests = {item.get("skill_tree_sha256") for item in public}
        runner_digests = {item.get("closure_runner_sha256") for item in public}
        if len(skill_digests) > 1:
            raise ValueError("closure evidence mixes different Skill tree digests")
        if len(runner_digests) > 1:
            raise ValueError("closure evidence mixes different closure runner digests")
        round_dir.mkdir(parents=True, exist_ok=True)
        (round_dir / "closure-results.jsonl").write_text(
            "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in public),
            encoding="utf-8", newline="\n",
        )
        qualification_ids = {item.get("qualification_id") for item in public}
        run_kinds = {item.get("run_kind") for item in public}
        if len(qualification_ids) > 1 or len(run_kinds) > 1:
            raise ValueError("closure evidence mixes qualification identities or run kinds")
        summary = {
            "round": int(round_dir.name.split("-")[-1]), "models": models,
            "qualification_id": next(iter(qualification_ids), None),
            "run_kind": next(iter(run_kinds), None),
            "skill_tree_sha256": next(iter(skill_digests), None),
            "closure_runner_sha256": next(iter(runner_digests), None),
            "planned": len(keys), "completed": len(public),
            "passed": sum(item["status"] == "PASS" for item in public),
            "review_required": sum(item["status"] == "REVIEW_REQUIRED" for item in public),
            "run_errors": sum(item["status"] == "RUN_ERROR" for item in public),
            "first_attempt_with_hard_errors": sum(item["first_attempt_hard_errors"] > 0 for item in public),
            "automated_checks_are_user_acceptance": False,
            "results": [
                {
                    **{key: item.get(key) for key in ("case_id", "model", "status", "first_draft_sha256", "final_sha256", "repair_rounds", "first_attempt_hard_errors", "access_violation_count", "preservation_status", "preservation_sha256")},
                    "host_attempts": len(item.get("host_attempts", [])),
                }
                for item in public
            ],
        }
        (round_dir / "closure-public-report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        private_report.parent.mkdir(parents=True, exist_ok=True)
        private_report.write_text(json.dumps({
            "round": summary["round"], "models": models,
            "qualification_id": summary["qualification_id"], "run_kind": summary["run_kind"],
            "cases": private,
        }, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")


def main() -> int:
    try:
        args = configure_run(parse_args())
    except ValueError as error:
        raise SystemExit(str(error)) from error
    args.skill_tree_sha256 = runtime_tree_digest()
    args.closure_runner_sha256 = closure_runner_digest()
    if args.round_number < 2 or not 1 <= args.workers <= 8:
        raise SystemExit("round must be at least 2 and workers must be between 1 and 8")
    models = args.model or list(MODELS)
    if len(models) != len(set(models)):
        raise SystemExit("models must be unique")
    round_dir = ROOT / "evals" / "forward" / f"round-{args.round_number}"
    requests = read_jsonl(round_dir / "requests.jsonl")
    if len(requests) != 20:
        raise SystemExit("expected exactly 20 forward requests")
    if args.case_id:
        selected = set(args.case_id)
        known = {item["case_id"] for item in requests}
        if not selected <= known:
            raise SystemExit("one or more selected case identifiers do not exist in this round")
        requests = [item for item in requests if item["case_id"] in selected]
    auth = args.auth.resolve()
    private_report = args.private_report.resolve()
    run_root = args.run_root.resolve()
    for path, label in ((private_report, "private report"), (run_root, "run root")):
        try:
            path.relative_to(ROOT.resolve())
        except ValueError:
            pass
        else:
            raise SystemExit(f"{label} must stay outside the repository")
    if not auth.is_file():
        raise SystemExit("auth file is missing")
    closure_path = round_dir / "closure-results.jsonl"
    existing_public: list[dict[str, Any]] = []
    existing_private: list[dict[str, Any]] = []
    if private_report.exists() or closure_path.exists():
        if not args.resume_incomplete or not private_report.exists() or not closure_path.exists():
            raise SystemExit("closure evidence already exists; use --resume-incomplete only for a matching partial run")
        existing_public = read_jsonl(closure_path)
        if any(item.get("skill_tree_sha256") != args.skill_tree_sha256 for item in existing_public):
            raise SystemExit("partial run evidence belongs to a different Skill tree digest")
        if any(item.get("closure_runner_sha256") != args.closure_runner_sha256 for item in existing_public):
            raise SystemExit("partial run evidence belongs to a different closure runner digest")
        if any(item.get("qualification_id") != args.qualification_id for item in existing_public):
            raise SystemExit("partial run evidence belongs to a different qualification id")
        if any(item.get("run_kind") != args.run_kind for item in existing_public):
            raise SystemExit("partial run evidence belongs to a different run kind")
        private_payload = json.loads(private_report.read_text(encoding="utf-8"))
        if private_payload.get("qualification_id") != args.qualification_id or private_payload.get("run_kind") != args.run_kind:
            raise SystemExit("private partial evidence belongs to a different qualification run")
        existing_private = list(private_payload.get("cases", []))
    if run_root.exists() and any(run_root.iterdir()) and not args.resume_incomplete:
        raise SystemExit("run root must be new or empty")
    run_root.mkdir(parents=True, exist_ok=True)

    seeds: dict[tuple[str, str], str] = {}
    if args.seed_drafts:
        for item in read_jsonl(args.seed_drafts):
            seeds[(item["case_id"], item.get("model", "gpt-5.6-sol"))] = item["answer"]
    feedback: dict[str, list[str]] = {}
    if args.feedback:
        feedback_payload = json.loads(args.feedback.read_text(encoding="utf-8"))
        if isinstance(feedback_payload, dict) and isinstance(feedback_payload.get("decisions"), list):
            feedback = {
                item["origin_case_id"]: normalized_review_feedback(item)
                for item in feedback_payload["decisions"]
            }
        elif isinstance(feedback_payload, dict):
            feedback = feedback_payload
        else:
            raise SystemExit("feedback must be a case mapping or a migration review source")

    public_by_key: dict[tuple[str, str], dict[str, Any]] = {(item["case_id"], item["model"]): item for item in existing_public}
    private_by_key: dict[tuple[str, str], dict[str, Any]] = {(item["case_id"], item["model"]): item for item in existing_private}
    expected_keys = {(request["case_id"], model) for request in requests for model in models}
    if not set(public_by_key) <= expected_keys or set(private_by_key) != set(public_by_key):
        raise SystemExit("partial run evidence does not match the selected round and models")
    host_attempts: dict[tuple[str, str], list[dict[str, Any]]] = {
        key: list(item.get("host_attempts", []))
        for key, item in public_by_key.items()
    }
    private_host_attempts: dict[tuple[str, str], list[dict[str, Any]]] = {
        key: list(item.get("host_attempts", []))
        for key, item in private_by_key.items()
    }
    for key, item in list(public_by_key.items()):
        if can_retry_run_error(item["status"], len(host_attempts[key]), args.retry_run_errors):
            if not host_attempts[key]:
                host_attempts[key].append({"attempt": 1, "status": "RUN_ERROR", "error_type": item.get("error_type", "UnknownError")})
            if not private_host_attempts[key]:
                private_host_attempts[key].append({"attempt": 1, "status": "RUN_ERROR", "error": private_by_key[key].get("error", "unknown")})
            del public_by_key[key]
            del private_by_key[key]
    request_by_id = {request["case_id"]: request for request in requests}
    jobs = deque(
        (request, model)
        for request in requests for model in models
        if (request["case_id"], model) not in public_by_key
    )
    planned_total = len(expected_keys)
    if len(public_by_key) >= planned_total and not jobs:
        raise SystemExit("closure run is already complete and immutable")
    stop_scheduling = args.fail_fast and any(item["status"] != "PASS" for item in public_by_key.values())
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures: dict[Any, tuple[str, str]] = {}
        while jobs or futures:
            while jobs and len(futures) < args.workers and not stop_scheduling:
                request, model = jobs.popleft()
                key = (request["case_id"], model)
                future = executor.submit(
                    run_case, args, request, model, seeds.get(key),
                    feedback.get(request["case_id"], []), auth, run_root,
                )
                futures[future] = key
            if not futures:
                break
            completed, _ = wait(futures, return_when=FIRST_COMPLETED)
            outcomes: list[
                tuple[tuple[str, str], int, dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]
            ] = []
            for future in completed:
                key = futures.pop(future)
                attempt_number = len(host_attempts.get(key, [])) + 1
                try:
                    public, private = future.result()
                    public_attempt = {"attempt": attempt_number, "status": public["status"]}
                    private_attempt = {
                        "attempt": attempt_number, "status": public["status"],
                        "first_draft_sha256": public.get("first_draft_sha256"),
                        "final_sha256": public.get("final_sha256"),
                    }
                except Exception as error:
                    error_type = type(error).__name__
                    public = {
                        "case_id": key[0], "model": key[1], "model_code": MODEL_CODES[key[1]],
                        "qualification_id": args.qualification_id, "run_kind": args.run_kind,
                        "skill_tree_sha256": args.skill_tree_sha256,
                        "closure_runner_sha256": args.closure_runner_sha256,
                        "status": "RUN_ERROR", "error_type": error_type,
                        "first_draft_sha256": None, "final_sha256": None, "repair_rounds": 0,
                        "first_attempt_hard_errors": 0, "access_violation_count": 0,
                        "preservation_status": None, "preservation_sha256": None,
                    }
                    private = {
                        "case_id": key[0], "model": key[1],
                        "qualification_id": args.qualification_id, "run_kind": args.run_kind,
                        "error": repr(error),
                    }
                    public_attempt = {"attempt": attempt_number, "status": "RUN_ERROR", "error_type": error_type}
                    private_attempt = {"attempt": attempt_number, "status": "RUN_ERROR", "error": repr(error)}
                outcomes.append((key, attempt_number, public, private, public_attempt, private_attempt))
            if args.fail_fast and any(public["status"] == "REVIEW_REQUIRED" for _, _, public, _, _, _ in outcomes):
                stop_scheduling = True
            for key, attempt_number, public, private, public_attempt, private_attempt in outcomes:
                host_attempts.setdefault(key, []).append(public_attempt)
                private_host_attempts.setdefault(key, []).append(private_attempt)
                public["host_attempts"] = host_attempts[key]
                private["host_attempts"] = private_host_attempts[key]
                public_by_key[key] = public
                private_by_key[key] = private
                persist(round_dir, private_report, requests, models, public_by_key, private_by_key)
                retry = should_schedule_host_retry(
                    public["status"], attempt_number, args.retry_run_errors, stop_scheduling,
                )
                if retry:
                    del public_by_key[key]
                    del private_by_key[key]
                    jobs.appendleft((request_by_id[key[0]], key[1]))
                elif public["status"] != "PASS" and args.fail_fast:
                    stop_scheduling = True
                print(json.dumps({
                    "completed": len(public_by_key), "total": planned_total,
                    "case_id": key[0], "model": key[1], "status": public["status"],
                    "host_attempt": attempt_number, "retry_scheduled": retry,
                }, ensure_ascii=False), flush=True)
    failures = [item for item in public_by_key.values() if item["status"] != "PASS"]
    complete = len(public_by_key) == planned_total
    print(json.dumps({
        "status": "PASS" if complete and not failures else "FAIL",
        "qualification_id": args.qualification_id, "run_kind": args.run_kind,
        "completed": len(public_by_key), "planned": planned_total,
        "passed": len(public_by_key) - len(failures), "failed": len(failures),
        "stopped_early": not complete,
    }, ensure_ascii=False))
    return 0 if complete and not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
