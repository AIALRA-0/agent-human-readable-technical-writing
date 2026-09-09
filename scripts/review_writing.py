"""Check local Markdown and deliver it even when format findings remain.

--patch accepts {"patches": [...]} using contracts/patch.schema.json. Targets are
one-based LINE-0001 nodes (including original line endings); document_sha256 is
the SHA-256 of the exact UTF-8 input. Repeat --patch for a second transaction,
bound to the first result. Supplied transactions and --fix-safe share two rounds.
Literal source prose must be marked as a quote or fenced block.
--fix-safe also deletes authored physical-line-final Chinese full stops and
semicolons, preserving trailing whitespace, other punctuation and source objects.
It never deletes punctuation between statements or inside closing quotes.
--edits accepts a compact, hash-bound transaction; the report supplies exact line
nodes. It is translated to the same committer, never to a whole-file rewrite.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from patcher.deterministic_committer import PatchError, apply_minimal_transaction, sha256_text
from runtime.format_validation import (
    code_preservation_roles,
    deterministic_format_findings,
    deterministic_format_replacements,
    protected_format_material,
    protected_inline_material,
    permitted_source_image_edit,
    source_image_findings,
)

MAX_REPAIR_ROUNDS = 2


def compact_transaction(text: str, payload: Any) -> list[dict[str, Any]]:
    """Expand explicit local edits without guessing old text, nodes, or hashes."""

    if not isinstance(payload, dict) or set(payload) != {"document_sha256", "edits"}:
        raise PatchError("--edits requires document_sha256 and edits")
    if payload["document_sha256"] != sha256_text(text):
        raise PatchError("edit document hash does not match the current text")
    if not isinstance(payload["edits"], list) or not payload["edits"]:
        raise PatchError("edits must be a non-empty list")
    patches = []
    nodes = line_nodes(text)
    for index, edit in enumerate(payload["edits"], 1):
        keys = {"node_id", "old_text", "new_text", "scope", "reason"}
        if not isinstance(edit, dict) or set(edit) != keys:
            raise PatchError("each edit requires node_id, old_text, new_text, scope and reason")
        if not all(isinstance(edit[key], str) for key in keys):
            raise PatchError("edit fields must be strings")
        if edit["scope"] not in {"token", "phrase", "sentence"} or not edit["reason"].strip():
            raise PatchError("edit requires a minimal scope and a non-empty reason")
        node = nodes.get(edit["node_id"])
        if node is None or not edit["old_text"] or text[node[0]:node[1]].count(edit["old_text"]) != 1:
            raise PatchError("old text must occur exactly once in the specified line node")
        patches.append({
            "identity": {"patch_id": f"PATCH-{index:03d}", "finding_id": f"local-{index}", "operation": "replace_exact"},
            "target": {"document_sha256": payload["document_sha256"], "node_id": edit["node_id"]},
            "replacement": {"old_text": edit["old_text"], "new_text": edit["new_text"], "expected_occurrences": 1},
            "authorization": {"reason": edit["reason"], "repair_scope": edit["scope"], "preserve": ["原始对象和未命中内容"]},
            "verification": {"rerun_validators": ["format", "protected_material"]},
        })
    return patches


def line_nodes(text: str) -> dict[str, tuple[int, int]]:
    nodes = {}
    cursor = 0
    for number, line in enumerate(text.splitlines(keepends=True), 1):
        nodes[f"LINE-{number:04d}"] = (cursor, cursor + len(line))
        cursor += len(line)
    return nodes


def _safe_patches(text: str, *, host_nested_blank: bool = False) -> list[dict[str, Any]]:
    patches = []
    for number, replacement in enumerate(deterministic_format_replacements(text, host_nested_blank=host_nested_blank), 1):
        patches.append({
            "identity": {"patch_id": f"PATCH-{number:03d}", "finding_id": replacement["rule_id"], "operation": "replace_exact"},
            "target": {"document_sha256": sha256_text(text), "node_id": replacement["node_id"]},
            "replacement": {"old_text": replacement["old_text"], "new_text": replacement["new_text"], "expected_occurrences": 1},
            "authorization": {"reason": "仅调整已确认的块间空白、同行注释空格或删除生成正文物理行末中文句号和分号", "repair_scope": "token", "preserve": ["实质文本、句中标点、其他末尾符号和原样材料"]},
            "verification": {"rerun_validators": ["format", "protected_material"]},
        })
    return patches


def _apply(text: str, patches: list[dict[str, Any]], *, source_images: list[str] | None = None) -> str:
    roles = code_preservation_roles(text)
    original_material = protected_format_material(text, code_roles=roles, include_inline=False)
    original_inline = Counter(protected_inline_material(text))
    for proposal in patches:
        replacement = proposal.get("replacement", {})
        old, new = replacement.get("old_text", ""), replacement.get("new_text", "")
        if original_inline[old] and permitted_source_image_edit(old, new, source_images or []):
            original_inline[old] -= 1
            original_inline[new] += 1  # The corrected object must actually survive.

    def preserve_material(result: str) -> list[str]:
        new_roles = code_preservation_roles(result)
        if len(new_roles) != len(roles) or any(
            (before == "literal" and after != "literal") or
            (before != "annotated" and after == "annotated")
            for before, after in zip(roles, new_roles)
        ):
            return ["patch cannot relabel original or unknown code to gain editing permission"]
        if protected_format_material(result, code_roles=roles, include_inline=False) != original_material:
            return ["patch changes protected material"]
        if original_inline - Counter(protected_inline_material(result)):
            return ["patch removes or changes an existing inline object"]
        return []

    return apply_minimal_transaction(text, patches, line_nodes(text), [preserve_material])


def review_text(
    text: str, *, transactions: list[list[dict[str, Any]]] | None = None, fix_safe: bool = False,
    edit_transactions: list[dict[str, Any]] | None = None,
    host_nested_blank: bool = False,
    source_images: list[str] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Apply bounded exact transactions in memory, then report two review parts."""

    transactions = transactions or []
    edit_transactions = edit_transactions or []
    if transactions and edit_transactions:
        raise PatchError("use either full patches or compact edits, not both")
    if len(transactions) + len(edit_transactions) > MAX_REPAIR_ROUNDS:
        raise PatchError("at most two patch transactions are allowed")
    original_hash = sha256_text(text)
    rounds = []
    for patches in transactions:
        before = sha256_text(text)
        text = _apply(text, patches, source_images=source_images)
        rounds.append({"kind": "supplied", "before_sha256": before, "after_sha256": sha256_text(text), "patches": patches})
    for edits in edit_transactions:
        patches = compact_transaction(text, edits)
        before = sha256_text(text)
        text = _apply(text, patches, source_images=source_images)
        rounds.append({"kind": "compact", "before_sha256": before, "after_sha256": sha256_text(text), "patches": patches})
    while fix_safe and len(rounds) < MAX_REPAIR_ROUNDS:
        patches = _safe_patches(text, host_nested_blank=host_nested_blank)
        if not patches:
            break
        before = sha256_text(text)
        text = _apply(text, patches, source_images=source_images)
        rounds.append({"kind": "safe", "before_sha256": before, "after_sha256": sha256_text(text), "patches": patches})
    findings = deterministic_format_findings(text, host_nested_blank=host_nested_blank)
    findings.extend(source_image_findings(text, source_images or []))
    defects = [item for item in findings if item["status"] == "FAIL"]
    candidates = [item for item in findings if item["status"] == "REVIEW_REQUIRED"]
    report = {
        "format": {
            "status": "ISSUES_REMAIN" if defects else "REVIEW_REQUIRED" if candidates else "PASS",
            "delivery_blocked": False,
            "nested_list_spacing": "host-required" if host_nested_blank else "compact",
            "source_images_checked": list(dict.fromkeys(source_images or [])),
            "findings": defects,
            "candidates": candidates,
            "repair_rounds": len(rounds),
            "max_repair_rounds": MAX_REPAIR_ROUNDS,
            "rounds": rounds,
            "input_sha256": original_hash,
            "document_sha256": sha256_text(text),
            "text": text,
            "line_nodes": [{"node_id": node, "text": text[start:end]} for node, (start, end) in line_nodes(text).items()],
        },
        "content": {
            "status": "SAME_AGENT_REVIEW_REQUIRED",
            "reference": "references/explanation-framework.md",
            "next_action": "由同一写作 Agent 按解释框架复读最终文本，核对零基础理解与原文信息保留",
            "beginner_understanding": "NOT_ASSESSED",
            "user_acceptance": "NOT_ASSESSED",
        },
    }
    return text, report


def _load_patches(path: Path) -> list[dict[str, Any]]:
    # jsonschema is an existing repository dependency, needed only for --patch.
    import jsonschema

    payload = json.loads(path.read_bytes().decode("utf-8-sig"))
    if not isinstance(payload, dict) or set(payload) != {"patches"} or not isinstance(payload["patches"], list):
        raise PatchError('--patch must contain {"patches": [...]}')
    schema = json.loads((ROOT / "contracts/patch.schema.json").read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    for patch in payload["patches"]:
        error = next(validator.iter_errors(patch), None)
        if error:
            raise PatchError(f"invalid patch: {error.message}")
    return payload["patches"]


def _same_file(first: Path, second: Path) -> bool:
    return first.resolve() == second.resolve() or (first.exists() and second.exists() and first.samefile(second))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, required=True, help="UTF-8 Markdown input, never overwritten")
    parser.add_argument("--report", type=Path, required=True, help="JSON format/content report, including final text")
    parser.add_argument("--output", type=Path, help="explicit Markdown destination, required for repairs")
    parser.add_argument("--patch", type=Path, action="append", default=[], help="existing minimal exact-patch transaction JSON; at most twice")
    parser.add_argument("--edits", type=Path, action="append", default=[], help="compact hash-bound edits JSON; at most twice; cannot combine with --patch")
    parser.add_argument("--fix-safe", action="store_true", help="safe whitespace/comment alignment and authored physical-line-final Chinese full stop/semicolon deletion; at most two rounds total")
    parser.add_argument("--nested-list-spacing", choices=("compact", "host-required"), default="compact", help="use host-required only when higher-priority host instructions require a blank before each nested list; recorded in the report")
    parser.add_argument("--source-image", action="append", default=[], help="actual supplied image path or URL; repeat for multiple images; verifies retained object/alt text without fetching the image")
    args = parser.parse_args(argv)
    if (args.patch or args.edits or args.fix_safe) and args.output is None:
        parser.error("repairs require an explicit --output")
    try:
        destinations = [args.report] + ([args.output] if args.output else [])
        for index, destination in enumerate(destinations):
            if any(_same_file(destination, source) for source in [args.input, *args.patch, *args.edits, *destinations[:index]]):
                raise PatchError("input, patch files, report and output must use distinct paths")
        # Decode bytes directly so CRLF, final newline and a UTF-8 BOM survive.
        text = args.input.read_bytes().decode("utf-8")
        transactions = [_load_patches(path) for path in args.patch]
        edits = [json.loads(path.read_bytes().decode("utf-8-sig")) for path in args.edits]
        text, report = review_text(text, transactions=transactions, edit_transactions=edits, fix_safe=args.fix_safe,
                                  host_nested_blank=args.nested_list_spacing == "host-required", source_images=args.source_image)
        report["format"]["output"] = str(args.output.resolve()) if args.output else None
        # All transactions and preservation checks finish before any write.
        if args.output:
            args.output.write_bytes(text.encode("utf-8"))
        args.report.write_bytes((json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        print(json.dumps({"format": report["format"]["status"], "content": report["content"]["status"], "report": str(args.report)}, ensure_ascii=False))
        return 0
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
