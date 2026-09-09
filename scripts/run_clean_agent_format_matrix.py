"""Run randomized format-trigger and format-compliance checks with clean Agents.

Each case/model gets a new task directory and a new local Agent home.  The
writer sees only the installed Skill, the user request, and its source
materials.  The reviewer is a different clean Agent and receives no expected
answer or hidden case metadata.  Full events and answers stay in the private
run root; the report contains only redacted counts and hashes.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import shutil
import sys
from collections import deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path
from threading import Lock
from typing import Any

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from patcher.deterministic_committer import PatchError, apply_minimal_transaction, sha256_text  # noqa: E402
from runtime.format_validation import (  # noqa: E402
    deterministic_format_findings,
    deterministic_format_replacements,
)
from scripts.run_iterative_forward_matrix import (  # noqa: E402
    CLEAN_AGENT_DISABLED_FEATURES,
    MODELS,
    MODEL_CODES,
    RUNTIME_ITEMS,
    SUPPORTED_MODELS,
    access_violations,
    can_retry_run_error,
    line_nodes,
    parse_events,
    run_codex,
    should_schedule_host_retry,
    validate_schema,
)


WRITE_LOCK = Lock()
FORMAT_BUNDLE_BASE = (
    "references/format-rules.md",
    "references/explanation-framework.md",
)
TRIGGER_MEASUREMENT = "declared_activation_proxy"
REVIEW_SCOPE = ("format", "explanation")
SNAPSHOT_DIRECTORY = ".skill-snapshot"
REVIEW_RULE_PATTERN = r"^(?:FMT-[0-9]{3}|EXPL-(?:00[1-9]|01[0-4]))$"
PARALLEL_GUIDANCE = """Apply FMT-036 through FMT-043 together. Independent column definitions, row-mapping facts and comparison facts in authored table explanations must be separated at their semantic depth; preserving the original table does not exempt its authored explanation. Inspect newly inserted explanations as well as the initial text.

Under FMT-036 and FMT-054, one concept's continuous definition remains one block. A continuous cause-to-result explanation is not automatically a list merely because it contains multiple verbs. Apply FMT-056 and FMT-057 as currently written, without restoring the old mandatory history, etymology or taxonomy checklist.

Line breaks must preserve source ownership and shared conditions. Several lines may belong to one source through nesting, explicit attribution or an unambiguous enclosing block. FMT-043 does not impose one line per source. Report it only when the actual markers, indentation or order misrepresent that relationship, and explain which relationship is lost. When splitting an item, retain that relationship in the local replacement. Protected source objects and a single item's dependent explanation remain subject to the exceptions in the supplied rules; punctuation alone does not prove independent items."""


def review_output_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Extend only the existing review entry's rule namespace, not its structure."""

    value = copy.deepcopy(schema)
    value["properties"]["findings"]["items"]["properties"]["rule_id"]["pattern"] = REVIEW_RULE_PATTERN
    return value


def extend_review_schema(skill_root: Path) -> None:
    schema_path = skill_root / "contracts/format-review-output.schema.json"
    schema = review_output_schema(json.loads(schema_path.read_text(encoding="utf-8")))
    schema_path.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def copy_candidate_tree(source_root: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    for relative in RUNTIME_ITEMS:
        source = source_root / relative
        target = destination / relative
        if source.is_dir():
            shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        elif source.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)


def freeze_candidate_snapshot(run_root: Path, source_root: Path = ROOT) -> Path:
    """Copy and finalize the installable Skill exactly once for this run."""

    snapshot_root = run_root / SNAPSHOT_DIRECTORY
    copy_candidate_tree(source_root, snapshot_root)
    extend_review_schema(snapshot_root)
    return snapshot_root


def skill_snapshot_digest(skill_root: Path) -> str:
    digest = hashlib.sha256()
    files = sorted(
        (
            path for path in skill_root.rglob("*")
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
        ),
        key=lambda path: path.relative_to(skill_root).as_posix(),
    )
    for path in files:
        relative = path.relative_to(skill_root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        content = path.read_bytes()
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def load_run_snapshot(run_root: Path, previous: dict[str, Any] | None) -> tuple[Path, str]:
    if previous is None:
        snapshot_root = freeze_candidate_snapshot(run_root)
    else:
        snapshot_root = run_root / SNAPSHOT_DIRECTORY
        if not snapshot_root.is_dir():
            raise SystemExit("resume requires the frozen Skill snapshot from the original run")
    snapshot_digest = skill_snapshot_digest(snapshot_root)
    if previous is not None and previous.get("skill_tree_sha256") != snapshot_digest:
        raise SystemExit("existing report does not match the frozen Skill snapshot")
    return snapshot_root, snapshot_digest


def install_candidate(home: Path, snapshot_root: Path | None = None) -> None:
    destination = home / "skills/human-readable-technical-writing"
    if snapshot_root is None:
        copy_candidate_tree(ROOT, destination)
        extend_review_schema(destination)
        return
    shutil.copytree(snapshot_root, destination)


def required_run_snapshot(args: argparse.Namespace) -> Path:
    snapshot_root = getattr(args, "skill_snapshot_root", None)
    if snapshot_root is None:
        raise RuntimeError("clean Agent run is not bound to a frozen Skill snapshot")
    return Path(snapshot_root)


def snapshot_metadata(skill_root: Path) -> str:
    skill_text = (skill_root / "SKILL.md").read_text(encoding="utf-8")
    frontmatter_end = skill_text.find("\n---", 4)
    return skill_text[: frontmatter_end + 4] if frontmatter_end >= 0 else skill_text


def install_negative_metadata(home: Path, snapshot_root: Path) -> None:
    destination = home / "skills/human-readable-technical-writing"
    (destination / "contracts").mkdir(parents=True)
    (destination / "SKILL.md").write_text(snapshot_metadata(snapshot_root), encoding="utf-8")
    shutil.copy2(
        snapshot_root / "contracts/format-agent-output.schema.json",
        destination / "contracts/format-agent-output.schema.json",
    )


def has_complete_output_evidence(item: dict[str, Any]) -> bool:
    if item.get("expected_trigger") is not False:
        return True
    return item.get("negative_output_status") in {"PASS", "REVIEW_REQUIRED", "RUN_ERROR"}


def digest_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--requests", type=Path, required=True)
    parser.add_argument("--auth", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--model", action="append", choices=SUPPORTED_MODELS)
    parser.add_argument("--codex", default="codex")
    parser.add_argument("--reasoning-effort", default="medium")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--max-repair-rounds", type=int, default=2)
    parser.add_argument("--qualification-id", help="required for a formal full-matrix qualification")
    parser.add_argument("--resume-incomplete", action="store_true")
    parser.add_argument("--retry-run-errors", action="store_true")
    parser.add_argument("--fail-fast", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--case-id", action="append", help="run only selected cases for a bounded diagnostic")
    return parser.parse_args()


def public_task(row: dict[str, Any]) -> dict[str, Any]:
    """Remove evaluator metadata before the request reaches any clean Agent."""

    source = copy.deepcopy(row["source"])
    source.pop("sha256", None)
    return {
        "request": row["request"],
        "source": source,
        "references": row.get("references", []),
    }


def agent_environment(home: Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment["CODEX_HOME"] = str(home)
    environment["AIALRA_EVAL_SKILL_ROOT"] = str(home / "skills" / "human-readable-technical-writing")
    return environment


def format_rule_bundle(home: Path, task_payload: dict[str, Any], phase: str) -> str:
    """Return an immutable, task-relevant Skill snapshot without Agent file access."""

    skill_root = home / "skills" / "human-readable-technical-writing"
    skill_text = (skill_root / "SKILL.md").read_text(encoding="utf-8")
    if phase == "trigger":
        frontmatter_end = skill_text.find("\n---", 4)
        return skill_text[: frontmatter_end + 4] if frontmatter_end >= 0 else skill_text
    sections = [f"===== SKILL.md =====\n{skill_text}"]
    for relative in FORMAT_BUNDLE_BASE:
        path = skill_root / relative
        if not path.is_file():
            raise RuntimeError(f"required format rule bundle file is missing: {relative}")
        sections.append(f"===== {relative} =====\n{path.read_text(encoding='utf-8')}")
    return "\n\n".join(sections)


def call_clean_agent(
    args: argparse.Namespace,
    model: str,
    home: Path,
    task: Path,
    prompt: str,
    schema_name: str,
    *,
    resume_session: str | None = None,
) -> dict[str, Any]:
    environment = agent_environment(home)
    skill_root = home / "skills" / "human-readable-technical-writing"
    schema_path = skill_root / "contracts" / schema_name
    if resume_session:
        command = [
            args.codex, "exec", "resume", "--json", "--ignore-user-config", "--ignore-rules",
            "-c", 'web_search="disabled"', "--skip-git-repo-check", "--model", model,
            "-c", f'model_reasoning_effort="{args.reasoning_effort}"', "--output-schema", str(schema_path),
            resume_session, "-",
        ]
        insertion = 3
    else:
        command = [
            args.codex, "exec", "--json", "--skip-git-repo-check", "--ignore-user-config",
            "--ignore-rules", "-c", 'web_search="disabled"', "--model", model,
            "-c", f'model_reasoning_effort="{args.reasoning_effort}"', "--sandbox", "read-only",
            "--output-schema", str(schema_path), "-C", str(task), "-",
        ]
        insertion = 2
    for feature in CLEAN_AGENT_DISABLED_FEATURES:
        command[insertion:insertion] = ["--disable", feature]
    return run_codex(command, environment, args.timeout_seconds, stdin_text=prompt)


def parse_payload(result: dict[str, Any], schema_name: str, *, patch_id_start: int | None = None) -> dict[str, Any]:
    try:
        payload = json.loads(result["body"].strip())
    except json.JSONDecodeError as error:
        if result["exit_code"] != 0:
            raise RuntimeError(f"Agent exit code {result['exit_code']}: {result['stderr'][-500:]}") from error
        raise RuntimeError(f"Agent did not return valid JSON: {error}") from error
    if schema_name == "format-patch-output.schema.json" and patch_id_start is not None:
        schema = json.loads((ROOT / "contracts" / schema_name).read_text(encoding="utf-8"))
        identity = schema["properties"]["patches"]["items"]["properties"]["identity"]["properties"]
        identity["patch_id"].pop("pattern")
        identity["patch_id"]["minLength"] = 1
        # Only the opaque bookkeeping label is normalized. All other submitted
        # structure/types are checked first; hashes, nodes and text stay exact.
        jsonschema.Draft202012Validator(schema).validate(payload)
        payload = normalize_patch_ids(payload, patch_id_start)
        validate_schema(schema_name, payload)
    elif schema_name == "format-review-output.schema.json":
        schema = json.loads((ROOT / "contracts" / schema_name).read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(review_output_schema(schema)).validate(payload)
    else:
        validate_schema(schema_name, payload)
    if result["exit_code"] != 0:
        recoverable = (
            result["exit_code"] == 1
            and "failed to flush rollout after emitting terminal turn event" in result["stderr"]
            and "not found" in result["stderr"]
        )
        if not recoverable:
            raise RuntimeError(f"Agent exit code {result['exit_code']}: {result['stderr'][-500:]}")
        result["recovered_terminal_flush_error"] = True
    return payload


def trigger_prompt(task_payload: dict[str, Any], rule_bundle: str) -> str:
    return f"""You are a clean routing Agent

Read the complete immutable Skill snapshot under `RULE_BUNDLE`, then decide whether it applies to the embedded underlying user request below

The instruction to return JSON is only the evaluation protocol and is not the underlying user request; do not classify this routing protocol as a pure JSON task. Classify only the content under `UNDERLYING_USER_REQUEST_AND_MATERIAL`

The bundle is complete for routing. Do not call tools or inspect files. Use only this bundle and the supplied request and materials; do not use prior conversation, evaluator metadata, expected answer or scoring rule

Return only the required JSON object with `activated` and a short reason

RULE_BUNDLE:
{rule_bundle}

UNDERLYING_USER_REQUEST_AND_MATERIAL:
{json.dumps(task_payload, ensure_ascii=False, indent=2)}
"""


def writer_prompt(task_payload: dict[str, Any], rule_bundle: str) -> str:
    return f"""You are a clean writing Agent with no conversation history

Read the complete immutable, task-relevant Skill snapshot under `RULE_BUNDLE`, then complete the user request

The bundle is complete for this format and explanation qualification. Do not call tools or inspect files. The Skill is the only writing guidance supplied for this task. Do not use prior conversation, evaluator metadata, expected answer or scoring rule. Return only the JSON object required by the output schema, with the complete final answer in `answer`

Before returning, perform the Skill's own format and task-applicable explanation self-review once across every applicable category in the supplied rule bundle and repair only the smallest complete units

The outer deterministic middleware runs the installed alignment checker after your response. In this isolated run, calculate required comment spacing from the supplied rules, do not call the checker yourself, and do not expose internal validation status or a claim that runtime evidence is missing in the user-facing answer

Apply the complete format rules and the explanation framework according to the underlying request. The framework does not authorize extra facts or teaching expansion when the user asks only for formatting or faithful rewriting

{PARALLEL_GUIDANCE}

Before using a range word such as `每条`, `全部`, `所有`, `均`, `始终` or `完全`, verify that every covered source item actually supports the statement. If any source line is truncated, unresolved or scoped more narrowly, keep the narrower explicit scope instead of generalizing

When source material contains commentable code, preserve the original source and provide its annotated copy as required by FMT-072. Choose block-header or aligned same-line comments according to the explanation unit in the supplied rule; do not demand both modes for every code block. Never insert a generated comment into the original block or label an annotated copy as original material

RULE_BUNDLE:
{rule_bundle}

USER_REQUEST_AND_MATERIAL:
{json.dumps(task_payload, ensure_ascii=False, indent=2)}
"""


def negative_output_prompt(task_payload: dict[str, Any], skill_metadata: str) -> str:
    return f"""You are a clean output Agent with no conversation history

The installed Skill metadata is supplied only so you can respect that this underlying request does not activate the Skill. Do not call tools, inspect files, or load further Skill instructions. Use only the metadata and underlying request below

Complete the underlying request exactly. Return only the JSON object required by the output schema, with the complete requested output in `answer`. Do not add an explanation, label, Markdown fence, quotation marks, or any other wrapper that the underlying request did not request

SKILL_METADATA:
{skill_metadata}

UNDERLYING_USER_REQUEST_AND_MATERIAL:
{json.dumps(task_payload, ensure_ascii=False, indent=2)}
"""


def review_prompt(task_payload: dict[str, Any], answer: str, rule_bundle: str, *, review_candidates: list[dict[str, Any]] | None = None) -> str:
    nodes = [
        {"node_id": node, "text": answer[start:end].rstrip("\r\n")}
        for node, (start, end) in line_nodes(answer).items()
    ]
    return f"""You are an independent clean review Agent with no conversation history

Read the complete immutable, task-relevant Skill snapshot under `RULE_BUNDLE`. Review CURRENT_ANSWER against the format rules and, where applicable to the underlying request, the explanation framework. Use EXPL-001 through EXPL-014 only when defined in that bundle. Assess source preservation and necessary understanding through the existing review categories; do not require expansion forbidden by the user or fixed terminology fields absent from the current rules

Do not call tools or inspect files. Do not rewrite the answer. Return only the required review JSON. Check every applicable format category, including punctuation, block structure, headings, parallel items, nesting, Chinese-English presentation, terminology, capitalization, formulas, code, images, tables, quotations and mixed media. Internally scan the complete answer twice before returning. Report every visible occurrence, not only one representative example. For the parallel-item rules, inspect every authored line that uses enumeration punctuation or a conjunction. Report an issue only when the named items are independent under the supplied rules. Use exact rule identifiers from the bundle. Do not postpone a visible issue to a later round, invent a violation from personal taste, or use evaluator metadata

Apply professional-term naming rules only to objectively established professional concepts. Require an official English form only when it is verified in the supplied source or rule bundle. Ordinary project labels, table headers, column names, field names, statuses and operational phrases are not professional terms by default. Never require an invented English name or an English-name placeholder; when official English is unavailable, keep natural Chinese under FMT-061 and still assess the applicable explanation requirements

Audit every authored scope word such as `每条`, `全部`, `所有`, `均`, `始终` and `完全` against the supplied source before returning. Report every unsupported expansion in the first review, especially when any source line is truncated, unresolved or narrower than the answer

Check complete source fidelity in the initial draft and after every repair. Use EXPL-012/013 and the rule bundle's source-preservation requirements for omitted source content, changed numbers or unsupported claims already present in the initial draft; a claim is not exempt because its text appeared in that draft. FMT-008 retains its specific meaning: a format repair must not change source facts or protected material. A verbatim quotation may be any exact contiguous excerpt from the source and does not need to include the entire source line unless the answer claims that it does

Treat an authored line as a forbidden colon pseudo-heading only when the label and colon stand alone as a section divider. A list item such as `- 单位：未提供`, a professional-term definition with content after the colon, and a code comment that continues with a complete explanation are not pseudo-headings

{PARALLEL_GUIDANCE}

Use an exact `FMT-NNN` or allowed `EXPL-NNN` identifier defined in the rule bundle. Every reason must connect that rule's requirement to the observed defect and the underlying request. A rule identifier alone is not a scoring justification. Every finding must identify exactly one supplied `LINE-NNNN` node and copy one non-empty, single-line `old_text` substring exactly from that node. For a missing explanation, bind to the existing line that requires it and identify the missing source relationship in the reason. When a block-level code comment is required by the chosen explanation unit and missing, target the first executable line so a legal header can be inserted immediately before it; do not also require a header for an already complete per-line explanation. Omit a finding when no exact current node proves it

Do not apply the ordinary parallel-item line-break rule by splitting one executable statement or its required same-line code comment. Judge comment content against the current FMT-072 explanation unit and source-preservation rules; do not impose an extra collective-name or out-of-block-list requirement

The outer deterministic middleware runs the installed code-alignment checker. Review the observable final code spacing and comment coverage, but do not require the answer itself to claim or display internal checker evidence; visible internal validation labels are themselves invalid user-facing content

RULE_BUNDLE:
{rule_bundle}

REQUEST_AND_MATERIAL:
{json.dumps(task_payload, ensure_ascii=False, indent=2)}

OPTIONAL_MACHINE_REVIEW_TARGETS:
{json.dumps(review_candidates or [], ensure_ascii=False, indent=2)}

These targets are questions, not proven violations. Resolve them from the supplied rules and current answer, along with the full-answer review. Do not copy a machine target identifier as a finding. Report only an actual defect bound to a defined FMT/EXPL rule and exact current evidence; a conjunction, lowercase product name, or repeated ordinary word alone does not prove one. An empty list does not certify that no semantic defects exist

CURRENT_ANSWER_LINE_NODES:
{json.dumps(nodes, ensure_ascii=False, indent=2)}
"""


def repair_prompt(
    answer: str, findings: list[dict[str, Any]], rule_bundle: str,
    *, previous_failure: dict[str, Any] | None = None,
) -> str:
    nodes = [{"node_id": node, "text": answer[start:end]} for node, (start, end) in line_nodes(answer).items()]
    failure_section = (
        "\nLAST_REJECTED_TRANSACTION:\n" + json.dumps(previous_failure, ensure_ascii=False, indent=2)
        if previous_failure is not None else ""
    )
    return f"""Re-read the immutable Skill snapshot under `RULE_BUNDLE` before making a local repair. Do not call tools or inspect files

Return only the exact patch object required by the output schema

RULE_BUNDLE:
{rule_bundle}

Repair only the supplied format or explanation findings with the smallest complete unit. Do not regenerate the paragraph, section or full answer. Preserve every fact, number, condition, exception, source object, code statement, table cell, image link, formula and quoted character not directly covered by a finding. A patch must use `replace_exact`, one supplied line node, the exact current document hash, an exact old text, a verified occurrence count, a minimal repair scope and at least one validator name. Return an empty patch list when no safe local repair is supported; unresolved findings remain recorded and the current answer is retained

{PARALLEL_GUIDANCE}

Copy old_text character-for-character from the supplied current node, including only punctuation and line endings actually present. Count expected_occurrences inside that node, not across the document. A token repair may use the complete exact line as unique matching context while changing only the offending characters in new_text. Matching context does not authorize rewriting that line or paragraph. When a token occurs more than once, use unique unchanged context to select the intended occurrence; do not guess a location, copy an absent final full stop, or silently change a submitted hash or old_text

If a finding concerns a Chinese full stop, change only the indicated authored punctuation or the smallest separator needed to keep the statements readable. Preserve punctuation inside protected material even when it appears in the matching context. A safe paragraph-final full stop can be deleted; a full stop between statements requires a semantic choice of semicolon or line break, never blind deletion or a fixed sentence-length heuristic. If a finding concerns a list, preserve the item text and change only the necessary block structure. If it concerns an inline code comment, preserve executable code and change only the comment spacing or text

For source-preservation or explanation findings, restore omitted source content or add the smallest necessary explanation supported by the supplied materials and current rules. Explain a term, mechanism or step locally when that support exists and the user's requested scope allows it. Do not invent facts, sources, rules or procedures, or present inference as a supplied fact. If the needed explanation cannot be supported, retain the unknown and return no unsafe patch

When LAST_REJECTED_TRANSACTION is present, the entire transaction was rejected and none of its edits were applied. Use its exact PatchError, failed patches and actual node texts to correct the proposal against CURRENT_SHA256 and LINE_NODES. Bind replacements to the current FINDINGS identifiers. This correction consumes the next round of the same two-round budget; it is not an extra retry loop

For additive findings, insert only the missing words and preserve the old sentence around the insertion. Do not alter a source claim while adding a unit, title, explanation or limitation. Do not expose source digests or internal validation metadata

When a replacement turns adjacent paragraphs into Markdown list items, inspect the neighboring line nodes. Remove blank lines that would remain between items by submitting separate exact patches in the same transaction, bound to the same finding. Do not create a list with blank lines between its items

CURRENT_SHA256:
{sha256_text(answer)}

LINE_NODES:
{json.dumps(nodes, ensure_ascii=False, indent=2)}

FINDINGS:
{json.dumps(findings, ensure_ascii=False, indent=2)}
{failure_section}

"""


def merge_findings(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    positions: dict[tuple[str, str], int] = {}
    for group in groups:
        for item in group:
            finding = dict(item)
            key = (str(finding.get("location")), str(finding.get("old_text")))
            if key not in positions:
                positions[key] = len(merged)
                merged.append(finding)
                continue
            existing = merged[positions[key]]
            rule_ids = [part for part in str(existing.get("rule_id", "")).split("+") if part]
            candidate = str(finding.get("rule_id", ""))
            if candidate and candidate not in rule_ids:
                rule_ids.append(candidate)
            existing["rule_id"] = "+".join(rule_ids)
            reason = str(finding.get("reason", ""))
            if reason and reason not in str(existing.get("reason", "")):
                existing["reason"] = str(existing.get("reason", "")) + " | " + reason
    return merged


def split_machine_findings(findings: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Machine candidates must reach review, never become mandatory repairs."""
    return ([item for item in findings if item.get("status") == "FAIL"],
            [item for item in findings if item.get("status") != "FAIL"])


def normalize_review_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Bind multi-line review evidence to one exact line-node repair target."""

    normalized: list[dict[str, Any]] = []
    for item in findings:
        finding = dict(item)
        old_text = str(finding.get("old_text", ""))
        if "\n" in old_text:
            lines = [line for line in old_text.splitlines() if line]
            if lines:
                finding["old_text"] = lines[-1]
                finding["reason"] = (
                    str(finding.get("reason", ""))
                    + "; multi-line evidence was bound to its final exact line for minimal patching"
                )
        normalized.append(finding)
    return normalized


def ground_review_findings(
    answer: str, findings: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Keep only review evidence that binds to an exact current line node."""

    nodes = line_nodes(answer)
    grounded: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for item in findings:
        finding = dict(item)
        old_text = str(finding.get("old_text", ""))
        candidates = [
            node_id for node_id, bounds in nodes.items()
            if old_text and old_text in answer[slice(*bounds)]
        ]
        declared = re.search(r"LINE-[0-9]{4}", str(finding.get("location", "")))
        declared_node = declared.group(0) if declared else None
        if declared_node in candidates:
            finding["location"] = declared_node
            grounded.append(finding)
        elif len(candidates) == 1:
            finding["location"] = candidates[0]
            grounded.append(finding)
        else:
            finding["rejection_reason"] = "review evidence is absent or ambiguous in the current answer"
            rejected.append(finding)
    return grounded, rejected


def filter_machine_decidable_findings(
    findings: list[dict[str, Any]], deterministic: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Let exact middleware results override contradictory semantic measurements."""

    required = {
        "FMT-025": "FORMAT_LIST_INTERNAL_BLANK",
        "FMT-073": "FORMAT_CODE_COMMENT_ALIGNMENT",
        "FMT-074": "FORMAT_CODE_COMMENT_ALIGNMENT",
        "FMT-075": "FORMAT_CODE_COMMENT_ALIGNMENT",
        "FMT-076": "FORMAT_CODE_COMMENT_ALIGNMENT",
    }
    observed = {str(item.get("rule_id")) for item in deterministic}
    kept: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for item in findings:
        machine_rule = required.get(str(item.get("rule_id")))
        if machine_rule and machine_rule not in observed:
            finding = dict(item)
            finding["rejection_reason"] = "machine-authoritative check found no matching defect"
            rejected.append(finding)
        else:
            kept.append(item)
    return kept, rejected


def filter_format_phase_findings(
    findings: list[dict[str, Any]], initial_answer: str, task_payload: dict[str, Any],
    *, review_scope: tuple[str, ...] = ("format",),
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Keep initial source findings in dual scope; retain the legacy format-only filter."""

    source_texts = [str(task_payload.get("source", {}).get("content", ""))]
    source_texts.extend(str(item.get("content", "")) for item in task_payload.get("references", []))
    kept: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for item in findings:
        rule_id = str(item.get("rule_id"))
        old_text = str(item.get("old_text", ""))
        out_of_scope = (
            review_scope == ("format",)
            and rule_id == "FMT-008" and old_text in initial_answer
        )
        quote = old_text.lstrip()
        exact_excerpt = (
            rule_id == "FMT-098"
            and quote.startswith(">")
            and any(quote[1:].strip() in source for source in source_texts)
        )
        if out_of_scope or exact_excerpt:
            finding = dict(item)
            finding["rejection_reason"] = (
                "initial-content claim is outside the legacy format-only repair invariant"
                if out_of_scope else "quoted text is an exact contiguous source excerpt"
            )
            rejected.append(finding)
        else:
            kept.append(item)
    return kept, rejected


def filter_undefined_rule_findings(
    findings: list[dict[str, Any]], rule_bundle: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Record unsupported scoring identifiers without inventing semantic exemptions."""

    defined = set(re.findall(r"(?m)^- `(FMT-\d{3}|EXPL-\d{3})`\s", rule_bundle))
    kept: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for item in findings:
        rule_id = str(item.get("rule_id", ""))
        if rule_id in defined and re.fullmatch(REVIEW_RULE_PATTERN, rule_id):
            kept.append(item)
        else:
            rejected.append(dict(item, rejection_reason="review rule is not defined in the supplied rule bundle"))
    return kept, rejected


def identify_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach stable current-round identifiers used by the exact patch middleware."""

    identified: list[dict[str, Any]] = []
    for index, item in enumerate(findings, start=1):
        finding = dict(item)
        finding["finding_id"] = f"FINDING-{index:03d}"
        identified.append(finding)
    return identified


def validate_patch_finding_bindings(
    payload: dict[str, Any], findings: list[dict[str, Any]],
) -> None:
    """Reject patches that are not bound to findings from the current review."""

    allowed = {str(item["finding_id"]) for item in findings}
    for patch in payload.get("patches", []):
        submitted = {
            value for value in str(patch["identity"]["finding_id"]).split("+") if value
        }
        if not submitted or not submitted <= allowed:
            raise PatchError("patch finding reference is outside the current merged review set")


def normalize_patch_ids(payload: dict[str, Any], run_number: int) -> dict[str, Any]:
    value = copy.deepcopy(payload)
    for index, patch in enumerate(value.get("patches", []), start=run_number):
        patch["identity"]["patch_id"] = f"PATCH-{index:03d}"
    return value


def remove_noop_patches(payload: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Discard only no-op proposals while preserving other transaction patches."""

    value = copy.deepcopy(payload)
    kept: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for patch in value.get("patches", []):
        replacement = patch.get("replacement", {})
        if replacement.get("old_text") == replacement.get("new_text"):
            rejected.append(patch)
        else:
            kept.append(patch)
    value["patches"] = kept
    return value, rejected


def patch_failure_feedback(
    answer: str, patches: list[dict[str, Any]], error: PatchError,
) -> dict[str, Any]:
    """Describe rejected proposals without correcting their targets or contents."""

    nodes = line_nodes(answer)
    actual_nodes: list[dict[str, Any]] = []
    for patch in patches:
        node_id = str(patch["target"]["node_id"])
        node_text = answer[slice(*nodes[node_id])] if node_id in nodes else None
        old_text = str(patch["replacement"]["old_text"])
        actual_nodes.append({
            "patch_id": patch["identity"]["patch_id"],
            "node_id": node_id,
            "text": node_text,
            "actual_occurrences": node_text.count(old_text) if node_text is not None and old_text else 0,
        })
    return {
        "patch_error": str(error),
        "document_sha256": sha256_text(answer),
        "failed_patches": copy.deepcopy(patches),
        "actual_nodes": actual_nodes,
    }


def compact_created_list_spacing(payload: dict[str, Any]) -> dict[str, Any]:
    """Remove blank lines only between list items created by one replacement."""

    value = copy.deepcopy(payload)
    list_item = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)")
    for patch in value.get("patches", []):
        text = str(patch["replacement"]["new_text"])
        lines = text.splitlines(keepends=True)
        compacted: list[str] = []
        for index, line in enumerate(lines):
            if (
                not line.strip()
                and compacted
                and index + 1 < len(lines)
                and list_item.match(compacted[-1].rstrip("\r\n"))
                and list_item.match(lines[index + 1].rstrip("\r\n"))
            ):
                continue
            compacted.append(line)
        patch["replacement"]["new_text"] = "".join(compacted)
    return value


def apply_safe_format_middleware(answer: str) -> tuple[str, list[dict[str, Any]]]:
    """Apply deterministic list-spacing and comment-alignment node patches."""

    proposals = deterministic_format_replacements(answer)
    if not proposals:
        return answer, []
    document_hash = sha256_text(answer)
    patches: list[dict[str, Any]] = []
    for index, proposal in enumerate(proposals, start=1):
        patches.append({
            "identity": {
                "patch_id": f"PATCH-MIDDLEWARE-{index:03d}",
                "finding_id": str(proposal["rule_id"]),
                "operation": "replace_exact",
            },
            "target": {
                "document_sha256": document_hash,
                "node_id": str(proposal["node_id"]),
            },
            "replacement": {
                "old_text": str(proposal["old_text"]),
                "new_text": str(proposal["new_text"]),
                "expected_occurrences": 1,
            },
            "authorization": {
                "reason": "apply an observable deterministic format correction",
                "repair_scope": "token" if not proposal["new_text"] else "phrase",
                "preserve": ["all non-format content"],
            },
            "verification": {"rerun_validators": [str(proposal["rule_id"])]},
        })
    return apply_minimal_transaction(answer, patches, line_nodes(answer)), patches


def add_list_spacing_patches(answer: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Remove only blank nodes between lines converted to list items together."""

    value = copy.deepcopy(payload)
    nodes = line_nodes(answer)
    converted: list[tuple[int, str, str]] = []
    for patch in value.get("patches", []):
        node_id = str(patch["target"]["node_id"])
        new_text = str(patch["replacement"]["new_text"])
        if re.match(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)", new_text):
            converted.append((int(node_id.rsplit("-", 1)[1]), node_id, str(patch["identity"]["finding_id"])))
    converted.sort()
    extras: list[dict[str, Any]] = []
    document_sha256 = sha256_text(answer)
    for left, right in zip(converted, converted[1:]):
        left_number, _, left_finding = left
        right_number, _, right_finding = right
        between = [f"LINE-{number:04d}" for number in range(left_number + 1, right_number)]
        if not between or any(answer[slice(*nodes[node])].strip() for node in between):
            continue
        for node_id in between:
            old_text = answer[slice(*nodes[node_id])]
            if not old_text:
                continue
            extras.append({
                "identity": {
                    "patch_id": "PATCH-AUTO",
                    "finding_id": f"{left_finding}+{right_finding}",
                    "operation": "replace_exact",
                },
                "target": {"document_sha256": document_sha256, "node_id": node_id},
                "replacement": {"old_text": old_text, "new_text": "", "expected_occurrences": 1},
                "authorization": {
                    "reason": "remove a blank line between list items created in the same transaction",
                    "repair_scope": "token",
                    "preserve": [],
                },
                "verification": {"rerun_validators": ["FMT-025"]},
            })
    value["patches"].extend(extras)
    return value


def run_trigger(
    args: argparse.Namespace, model: str, case_root: Path, task_payload: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    root = case_root / "trigger"
    home = root / "home"
    task = root / "task"
    home.mkdir(parents=True)
    task.mkdir(parents=True)
    shutil.copy2(args.auth.resolve(), home / "auth.json")
    install_candidate(home, required_run_snapshot(args))
    (task / "request.json").write_text(json.dumps(task_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    bundle = format_rule_bundle(home, task_payload, "trigger")
    result = call_clean_agent(
        args, model, home, task, trigger_prompt(task_payload, bundle), "format-trigger-output.schema.json",
    )
    payload = parse_payload(result, "format-trigger-output.schema.json")
    return payload, {
        "events": result["events"],
        "thread_id": result.get("thread_id"),
        "recovered_terminal_flush_error": bool(result.get("recovered_terminal_flush_error")),
        "access_violations": access_violations(result["events"], [root]),
    }


def run_negative_output(
    args: argparse.Namespace, model: str, case_root: Path, task_payload: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    root = case_root / "negative-output"
    home = root / "home"
    task = root / "task"
    home.mkdir(parents=True)
    task.mkdir(parents=True)
    shutil.copy2(args.auth.resolve(), home / "auth.json")
    snapshot_root = required_run_snapshot(args)
    install_negative_metadata(home, snapshot_root)
    (task / "request.json").write_text(
        json.dumps(task_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    result = call_clean_agent(
        args, model, home, task,
        negative_output_prompt(task_payload, snapshot_metadata(snapshot_root)),
        "format-agent-output.schema.json",
    )
    payload = parse_payload(result, "format-agent-output.schema.json")
    expected = task_payload.get("source", {}).get("content")
    if not isinstance(expected, str):
        raise RuntimeError("negative output comparison requires string source.content")
    violations = access_violations(result["events"], [root])
    exact = payload["answer"] == expected
    public = {
        "negative_output_status": "PASS" if exact and not violations else "REVIEW_REQUIRED",
        "negative_output_exact": exact,
        "negative_output_access_violation_count": len(set(violations)),
        "negative_output_sha256": sha256_text(payload["answer"]),
        "negative_output_terminal_flush_recovered": bool(
            result.get("recovered_terminal_flush_error")
        ),
    }
    private = {
        "payload": payload,
        "events": result["events"],
        "thread_id": result.get("thread_id"),
        "access_violations": sorted(set(violations)),
    }
    return public, private


def run_writer(
    args: argparse.Namespace, model: str, reviewer_model: str, case_root: Path,
    task_payload: dict[str, Any],
) -> dict[str, Any]:
    if not 1 <= args.max_repair_rounds <= 2:
        raise ValueError("repair rounds must be 1 or 2")
    writer_root = case_root / "writer"
    home = writer_root / "home"
    task = writer_root / "task"
    home.mkdir(parents=True)
    task.mkdir(parents=True)
    shutil.copy2(args.auth.resolve(), home / "auth.json")
    snapshot_root = required_run_snapshot(args)
    install_candidate(home, snapshot_root)
    (task / "request.json").write_text(json.dumps(task_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    bundle = format_rule_bundle(home, task_payload, "writer")
    initial_result = call_clean_agent(
        args, model, home, task, writer_prompt(task_payload, bundle), "format-agent-output.schema.json",
    )
    initial_payload = parse_payload(initial_result, "format-agent-output.schema.json")
    if not initial_result.get("thread_id"):
        raise RuntimeError("writer session id is missing; exact self-iteration is impossible")
    answer = initial_payload["answer"]
    first_hash = sha256_text(answer)
    events = list(initial_result["events"])
    recovered_flushes = int(bool(initial_result.get("recovered_terminal_flush_error")))
    violations = access_violations(initial_result["events"], [writer_root])
    rounds: list[dict[str, Any]] = []
    retry_feedback: dict[str, Any] | None = None
    retry_findings: list[dict[str, Any]] = []
    remaining: list[dict[str, Any]] = []
    status = "REVIEW_REQUIRED"
    for repair_round in range(1, args.max_repair_rounds + 1):
        round_input_sha256 = sha256_text(answer)
        answer, middleware_preflight = apply_safe_format_middleware(answer)
        deterministic = deterministic_format_findings(answer)
        machine_defects, machine_candidates = split_machine_findings(deterministic)
        reviewer_root = case_root / f"reviewer-{repair_round}"
        reviewer_home = reviewer_root / "home"
        reviewer_task = reviewer_root / "task"
        reviewer_home.mkdir(parents=True)
        reviewer_task.mkdir(parents=True)
        shutil.copy2(args.auth.resolve(), reviewer_home / "auth.json")
        install_candidate(reviewer_home, snapshot_root)
        (reviewer_task / "request.json").write_text(json.dumps(task_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        reviewer_result = call_clean_agent(
            args, reviewer_model, reviewer_home, reviewer_task,
            review_prompt(
                task_payload, answer, format_rule_bundle(reviewer_home, task_payload, "reviewer"),
                review_candidates=machine_candidates,
            ),
            "format-review-output.schema.json",
        )
        reviewer_payload = parse_payload(reviewer_result, "format-review-output.schema.json")
        semantic_raw = normalize_review_findings([
            dict(item, source="semantic") for item in reviewer_payload["findings"]
        ])
        semantic_raw, undefined_rules = filter_undefined_rule_findings(semantic_raw, bundle)
        semantic, rejected_review_findings = ground_review_findings(answer, semantic_raw)
        rejected_review_findings.extend(undefined_rules)
        semantic, machine_rejected = filter_machine_decidable_findings(semantic, deterministic)
        rejected_review_findings.extend(machine_rejected)
        semantic, phase_rejected = filter_format_phase_findings(
            semantic, initial_payload["answer"], task_payload,
            review_scope=REVIEW_SCOPE,
        )
        rejected_review_findings.extend(phase_rejected)
        events.extend(reviewer_result["events"])
        recovered_flushes += int(bool(reviewer_result.get("recovered_terminal_flush_error")))
        violations.extend(access_violations(reviewer_result["events"], [reviewer_root]))
        combined = identify_findings(merge_findings(machine_defects, semantic, retry_findings))
        record: dict[str, Any] = {
            "round": repair_round,
            "reread_rules": True,
            "round_input_sha256": round_input_sha256,
            "middleware_preflight_patches": middleware_preflight,
            "repair_attempted": bool(middleware_preflight),
            "repair_applied": bool(middleware_preflight),
            "deterministic_findings": machine_defects,
            "machine_review_candidates": machine_candidates,
            "semantic_findings": semantic,
            "rejected_review_findings": rejected_review_findings,
            "finding_rule_ids": list(dict.fromkeys(str(item.get("rule_id")) for item in combined)),
            "before_sha256": sha256_text(answer),
            "patches": [],
        }
        if not combined:
            record["result_status"] = "PASS"
            record["after_sha256"] = sha256_text(answer)
            rounds.append(record)
            status = "PASS"
            break
        record["repair_attempted"] = True
        if retry_feedback is not None:
            record["retry_feedback"] = retry_feedback
        patch_result = call_clean_agent(
            args, model, home, task,
            repair_prompt(answer, combined, bundle, previous_failure=retry_feedback),
            "format-patch-output.schema.json",
            resume_session=initial_result.get("thread_id"),
        )
        patch_payload = parse_payload(patch_result, "format-patch-output.schema.json", patch_id_start=repair_round * 100)
        record["submitted_patches"] = copy.deepcopy(json.loads(patch_result["body"])["patches"])
        patch_payload, rejected_noop_patches = remove_noop_patches(patch_payload)
        patch_payload = compact_created_list_spacing(patch_payload)
        patch_payload = add_list_spacing_patches(answer, patch_payload)
        patch_payload = normalize_patch_ids(patch_payload, repair_round * 100)
        validate_schema("format-patch-output.schema.json", patch_payload)
        events.extend(patch_result["events"])
        recovered_flushes += int(bool(patch_result.get("recovered_terminal_flush_error")))
        violations.extend(access_violations(patch_result["events"], [writer_root]))
        record["patches"] = patch_payload.get("patches", [])
        record["rejected_noop_patches"] = rejected_noop_patches
        try:
            validate_patch_finding_bindings(patch_payload, combined)
            if not patch_payload.get("patches"):
                raise PatchError("clean writer returned no patch for active format findings")
            candidate = apply_minimal_transaction(answer, patch_payload["patches"], line_nodes(answer))
            candidate, middleware_postflight = apply_safe_format_middleware(candidate)
            answer = candidate
            record["middleware_postflight_patches"] = middleware_postflight
            record["repair_applied"] = True
            retry_feedback = None
            retry_findings = []
            record["after_sha256"] = sha256_text(answer)
            record["result_status"] = "FAIL"
        except PatchError as error:
            record["patch_error"] = str(error)
            record["after_sha256"] = sha256_text(answer)
            record["result_status"] = "REVIEW_REQUIRED"
            retry_feedback = patch_failure_feedback(answer, record["patches"], error)
            record["patch_failure_feedback"] = retry_feedback
            retry_findings = combined
        rounds.append(record)
    if status != "PASS":
        final_local = deterministic_format_findings(answer)
        final_machine_defects, final_machine_candidates = split_machine_findings(final_local)
        final_reviewer_root = case_root / "reviewer-final"
        final_reviewer_home = final_reviewer_root / "home"
        final_reviewer_task = final_reviewer_root / "task"
        final_reviewer_home.mkdir(parents=True)
        final_reviewer_task.mkdir(parents=True)
        shutil.copy2(args.auth.resolve(), final_reviewer_home / "auth.json")
        install_candidate(final_reviewer_home, snapshot_root)
        (final_reviewer_task / "request.json").write_text(
            json.dumps(task_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
        final_review_result = call_clean_agent(
            args, reviewer_model, final_reviewer_home, final_reviewer_task,
            review_prompt(
                task_payload, answer, format_rule_bundle(final_reviewer_home, task_payload, "reviewer"),
                review_candidates=final_machine_candidates,
            ),
            "format-review-output.schema.json",
        )
        final_review_payload = parse_payload(final_review_result, "format-review-output.schema.json")
        final_semantic_raw = normalize_review_findings([
            dict(item, source="semantic") for item in final_review_payload["findings"]
        ])
        final_semantic_raw, undefined_rules = filter_undefined_rule_findings(final_semantic_raw, bundle)
        final_semantic, final_rejected_review_findings = ground_review_findings(
            answer, final_semantic_raw,
        )
        final_rejected_review_findings.extend(undefined_rules)
        final_semantic, machine_rejected = filter_machine_decidable_findings(
            final_semantic, final_local,
        )
        final_rejected_review_findings.extend(machine_rejected)
        final_semantic, phase_rejected = filter_format_phase_findings(
            final_semantic, initial_payload["answer"], task_payload,
            review_scope=REVIEW_SCOPE,
        )
        final_rejected_review_findings.extend(phase_rejected)
        events.extend(final_review_result["events"])
        recovered_flushes += int(bool(final_review_result.get("recovered_terminal_flush_error")))
        violations.extend(access_violations(final_review_result["events"], [final_reviewer_root]))
        remaining = merge_findings(final_machine_defects, final_semantic, retry_findings)
        status = "PASS" if not remaining else "REVIEW_REQUIRED"
    else:
        final_rejected_review_findings = []
    first_machine = split_machine_findings(deterministic_format_findings(initial_payload["answer"]))
    final_machine = split_machine_findings(deterministic_format_findings(answer))
    result = {
        "status": status,
        "model": model,
        "reviewer_model": reviewer_model,
        "worker_session_id": initial_result.get("thread_id"),
        "first_draft_sha256": first_hash,
        "final_sha256": sha256_text(answer),
        "attempt_rounds": sum(record["repair_attempted"] for record in rounds),
        "repair_rounds": sum(record["repair_applied"] for record in rounds),
        "first_deterministic_finding_count": len(first_machine[0]),
        "final_deterministic_finding_count": len(final_machine[0]),
        "first_machine_candidate_count": len(first_machine[1]),
        "final_machine_candidate_count": len(final_machine[1]),
        "final_finding_count": len(remaining),
        "final_finding_rule_ids": list(dict.fromkeys(str(item.get("rule_id")) for item in remaining)),
        "access_violation_count": len(set(violations)),
        "recovered_terminal_flush_count": recovered_flushes,
        "rejected_review_finding_count": sum(
            len(record.get("rejected_review_findings", [])) for record in rounds
        ) + len(final_rejected_review_findings),
        "answer": answer,
        "first_answer": initial_payload["answer"],
        "final_findings": remaining,
        "final_rejected_review_findings": final_rejected_review_findings,
        "rounds": rounds,
        "events": events,
        "access_violations": sorted(set(violations)),
    }
    return result


def run_case_model(
    args: argparse.Namespace,
    row: dict[str, Any],
    model: str,
    reviewer_model: str,
    run_root: Path,
    attempt_number: int,
) -> dict[str, Any]:
    case_root = (
        run_root / f"{row['case_id']}-{MODEL_CODES[model]}" /
        f"attempt-{attempt_number:02d}"
    )
    case_root.mkdir(parents=True)
    task_payload = public_task(row)
    trigger_payload, trigger_private = run_trigger(args, model, case_root, task_payload)
    expected = row.get("trigger_mode") != "non_triggering_control"
    trigger_pass = bool(trigger_payload["activated"]) == expected
    result: dict[str, Any] = {
        "case_id": row["case_id"],
        "model": model,
        "model_code": MODEL_CODES[model],
        "expected_trigger": expected,
        "trigger_activated": bool(trigger_payload["activated"]),
        "trigger_pass": trigger_pass,
        "trigger_measurement": TRIGGER_MEASUREMENT,
        "host_skill_routing_verified": False,
        "trigger_access_violation_count": len(trigger_private["access_violations"]),
        "trigger_terminal_flush_recovered": trigger_private["recovered_terminal_flush_error"],
        "status": "PASS" if trigger_pass and not expected else "REVIEW_REQUIRED",
        "writing_status": "NOT_RUN",
        "host_attempt": attempt_number,
    }
    private: dict[str, Any] = {"trigger": trigger_private, "trigger_payload": trigger_payload}
    if expected and trigger_pass:
        writer = run_writer(args, model, reviewer_model, case_root, task_payload)
        result.update({key: writer[key] for key in (
            "status", "first_draft_sha256", "final_sha256", "attempt_rounds", "repair_rounds",
            "first_deterministic_finding_count", "final_deterministic_finding_count", "access_violation_count",
            "recovered_terminal_flush_count", "rejected_review_finding_count",
            "final_finding_count", "final_finding_rule_ids",
        )})
        result["writing_status"] = writer["status"]
        result["status"] = writer["status"]
        private["writer"] = writer
        for key in ("first_machine_candidate_count", "final_machine_candidate_count"):
            if key in writer:
                result[key] = writer[key]
    elif expected:
        result["writing_status"] = "NOT_RUN_TRIGGER_MISS"
    else:
        negative_output, negative_private = run_negative_output(
            args, model, case_root, task_payload,
        )
        result.update(negative_output)
        result["writing_status"] = "NOT_APPLICABLE"
        result["status"] = (
            "PASS"
            if trigger_pass and negative_output["negative_output_status"] == "PASS"
            else "REVIEW_REQUIRED"
        )
        private["negative_output"] = negative_private
    (case_root / "result.json").write_text(json.dumps({"public": result, "private": private}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def write_report(report_path: Path, metadata: dict[str, Any], results: list[dict[str, Any]]) -> None:
    with WRITE_LOCK:
        payload = dict(metadata)
        payload.update({
            "completed": len(results),
            "trigger_passed": sum(bool(item.get("trigger_pass")) for item in results),
            "trigger_failed": sum(not bool(item.get("trigger_pass")) for item in results),
            "writing_planned": sum(item.get("expected_trigger") is True for item in results),
            "writing_passed": sum(item.get("writing_status") == "PASS" for item in results),
            "writing_review_required": sum(item.get("writing_status") == "REVIEW_REQUIRED" for item in results),
            "negative_output_planned": sum(item.get("expected_trigger") is False for item in results),
            "negative_output_passed": sum(item.get("negative_output_status") == "PASS" for item in results),
            "negative_output_review_required": sum(
                item.get("negative_output_status") == "REVIEW_REQUIRED" for item in results
            ),
            "negative_output_run_error": sum(
                item.get("negative_output_status") == "RUN_ERROR" for item in results
            ),
            "passed": sum(item.get("status") == "PASS" for item in results),
            "failed": sum(item.get("status") != "PASS" for item in results),
            "results": sorted(results, key=lambda item: (item["case_id"], item["model"])),
            "raw_answers_in_report": False,
            "automated_result_is_user_acceptance": False,
        })
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    if not 1 <= args.workers <= 8:
        raise SystemExit("workers must be between 1 and 8")
    if not 1 <= args.max_repair_rounds <= 2:
        raise SystemExit("format qualification repair rounds must be 1 or 2")
    requests_path = args.requests.resolve()
    auth_path = args.auth.resolve()
    run_root = args.run_root.resolve()
    report_path = args.report.resolve()
    if not requests_path.is_file() or not auth_path.is_file():
        raise SystemExit("requests or auth file is missing")
    if any(path == ROOT.resolve() or ROOT.resolve() in path.parents for path in (run_root, report_path)):
        raise SystemExit("run root and report must stay outside the repository")
    rows = read_jsonl(requests_path)
    if len(rows) != 20:
        raise SystemExit("clean format qualification requires exactly 20 requests")
    run_kind = "diagnostic" if args.case_id else "qualification"
    if run_kind == "qualification" and not args.qualification_id:
        raise SystemExit("--qualification-id is required for a formal full-matrix qualification")
    if run_kind == "diagnostic" and args.qualification_id:
        raise SystemExit("--qualification-id cannot be combined with --case-id diagnostics")
    if args.fail_fast is None:
        args.fail_fast = False
    if args.qualification_id and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{2,79}", args.qualification_id):
        raise SystemExit("qualification id must use 3-80 letters, digits, dots, underscores, or hyphens")
    if args.case_id:
        selected = set(args.case_id)
        known = {row["case_id"] for row in rows}
        if not selected <= known:
            raise SystemExit("one or more selected case identifiers do not exist")
        rows = [row for row in rows if row["case_id"] in selected]
    models = args.model or list(MODELS)
    request_digest = digest_file(requests_path)
    previous: dict[str, Any] | None = None
    if report_path.exists():
        if not args.resume_incomplete:
            raise SystemExit("report already exists; use --resume-incomplete only with the same run identity and digests")
        previous = json.loads(report_path.read_text(encoding="utf-8"))
    if run_root.exists() and any(run_root.iterdir()) and previous is None:
        raise SystemExit("run root must be new or empty")
    run_root.mkdir(parents=True, exist_ok=True)
    snapshot_root, skill_digest = load_run_snapshot(run_root, previous)
    args.skill_snapshot_root = snapshot_root
    runner_digest = digest_file(Path(__file__))
    run_metadata = {
        "qualification_id": args.qualification_id,
        "run_kind": run_kind,
        "seed_source_sha256": request_digest,
        "skill_tree_sha256": skill_digest,
        "runner_sha256": runner_digest,
        "models": models,
        "reasoning_effort": args.reasoning_effort,
        "worker_limit": args.workers,
        "max_repair_rounds": args.max_repair_rounds,
        "case_count": len(rows),
        "trigger_measurement": TRIGGER_MEASUREMENT,
        "host_skill_routing_verified": False,
        "review_scope": list(REVIEW_SCOPE),
    }
    existing: dict[tuple[str, str], dict[str, Any]] = {}
    attempts_by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
    if previous is not None:
        for key in (
            "qualification_id", "run_kind", "seed_source_sha256", "skill_tree_sha256",
            "runner_sha256", "models", "reasoning_effort",
            "max_repair_rounds", "case_count", "trigger_measurement", "review_scope",
        ):
            if previous.get(key) != run_metadata[key]:
                raise SystemExit("existing report does not match the current run identity, request, Skill tree, or models")
        for item in previous.get("results", []):
            key = (item["case_id"], item["model"])
            attempts_by_key[key] = list(item.get("host_attempts", []))
            if not has_complete_output_evidence(item):
                continue
            if can_retry_run_error(item.get("status", ""), len(attempts_by_key[key]), args.retry_run_errors):
                continue
            existing[key] = item
    jobs = deque(
        (row, model)
        for row in rows for model in models
        if (row["case_id"], model) not in existing
    )
    if not jobs:
        write_report(report_path, run_metadata, list(existing.values()))
        all_passed = all(item.get("status") == "PASS" for item in existing.values())
        print(json.dumps({
            "status": "PASS" if all_passed else "FAIL",
            "completed": len(existing), "planned": len(rows) * len(models),
        }, ensure_ascii=False))
        return 0 if all_passed else 1
    request_by_id = {row["case_id"]: row for row in rows}
    futures: dict[Any, tuple[str, str, int]] = {}
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        def submit_next() -> bool:
            if not jobs:
                return False
            row, model = jobs.popleft()
            key = (row["case_id"], model)
            attempt_number = len(attempts_by_key.get(key, [])) + 1
            future = executor.submit(
                run_case_model, args, row, model, model, run_root, attempt_number,
            )
            futures[future] = (row["case_id"], model, attempt_number)
            return True

        for _ in range(min(args.workers, len(jobs))):
            submit_next()
        stop_scheduling = args.fail_fast and any(item.get("status") != "PASS" for item in existing.values())
        while futures:
            completed, _ = wait(futures, return_when=FIRST_COMPLETED)
            for future in completed:
                case_id, model, attempt_number = futures.pop(future)
                key = (case_id, model)
                try:
                    item = future.result()
                except FileExistsError as error:
                    raise SystemExit("attempt path already exists; refusing to modify original attempt evidence") from error
                except Exception as error:
                    expected_trigger = (
                        request_by_id[key[0]].get("trigger_mode") != "non_triggering_control"
                    )
                    error_root = (
                        run_root / f"{key[0]}-{MODEL_CODES[key[1]]}" /
                        f"attempt-{attempt_number:02d}"
                    )
                    error_root.mkdir(parents=True, exist_ok=True)
                    (error_root / "host-error.json").write_text(
                        json.dumps({
                            "case_id": key[0], "model": key[1], "attempt": attempt_number,
                            "error_type": type(error).__name__, "error": repr(error),
                        }, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8",
                    )
                    item = {
                        "case_id": key[0], "model": key[1], "model_code": MODEL_CODES[key[1]],
                        "expected_trigger": expected_trigger,
                        "trigger_activated": None, "trigger_pass": False,
                        "trigger_reason": "RUN_ERROR", "trigger_access_violation_count": 0,
                        "status": "RUN_ERROR",
                        "writing_status": "RUN_ERROR" if expected_trigger else "NOT_APPLICABLE",
                        "host_attempt": attempt_number, "error_type": type(error).__name__,
                    }
                    if not expected_trigger:
                        item["negative_output_status"] = "RUN_ERROR"
                attempts_by_key.setdefault(key, []).append({
                    "attempt": attempt_number,
                    "status": item["status"],
                    **({"error_type": item.get("error_type")} if item["status"] == "RUN_ERROR" else {}),
                })
                item["host_attempts"] = attempts_by_key[key]
                existing[key] = item
                write_report(report_path, run_metadata, list(existing.values()))
                retry = should_schedule_host_retry(
                    item["status"], attempt_number, args.retry_run_errors, stop_scheduling,
                )
                if retry:
                    del existing[key]
                    jobs.appendleft((request_by_id[key[0]], key[1]))
                print(json.dumps({
                    "completed": len(existing), "planned": len(rows) * len(models),
                    "case_id": key[0], "model": key[1],
                    "trigger_pass": item.get("trigger_pass"), "writing_status": item.get("writing_status"),
                    "host_attempt": attempt_number, "retry_scheduled": retry,
                }, ensure_ascii=False), flush=True)
                if not retry and args.fail_fast and item["status"] != "PASS":
                    stop_scheduling = True
            while not stop_scheduling and len(futures) < args.workers and jobs:
                submit_next()
    failures = [
        item for item in existing.values()
        if item.get("status") != "PASS"
    ]
    complete = len(existing) == len(rows) * len(models)
    final = {
        "status": "PASS" if complete and not failures else "FAIL",
        "completed": len(existing), "planned": len(rows) * len(models),
        "failed": len(failures), "report": str(report_path),
    }
    print(json.dumps(final, ensure_ascii=False))
    return 0 if final["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
