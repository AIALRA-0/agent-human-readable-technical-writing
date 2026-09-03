"""Deterministic checks and exact-patch closure for self-iterative delivery."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Callable, Iterable, Mapping, Sequence

from patcher.deterministic_committer import apply_minimal_transaction, sha256_text


MAX_REPAIR_ROUNDS = 3
PASS = "PASS"
FAIL = "FAIL"
REVIEW_REQUIRED = "REVIEW_REQUIRED"


def _finding(
    rule_id: str,
    location: str,
    old_text: str,
    reason: str,
    repair_scope: str,
    *,
    status: str = FAIL,
    source: str = "deterministic",
) -> dict[str, str]:
    """Build one stable finding that can be handed to an exact-patch worker."""

    return {
        "finding_id": f"{rule_id}:{location}",
        "rule_id": rule_id,
        "status": status,
        "location": location,
        "old_text": old_text,
        "reason": reason,
        "repair_scope": repair_scope,
        "source": source,
    }


def line_nodes(text: str) -> dict[str, tuple[int, int]]:
    """Expose stable one-line nodes so closure patches cannot replace whole sections."""

    nodes: dict[str, tuple[int, int]] = {}
    cursor = 0
    for number, line in enumerate(text.splitlines(keepends=True), start=1):
        nodes[f"LINE-{number:04d}"] = (cursor, cursor + len(line))
        cursor += len(line)
    if not nodes:
        nodes["LINE-0001"] = (0, len(text))
    elif cursor < len(text):
        nodes[f"LINE-{len(nodes) + 1:04d}"] = (cursor, len(text))
    return nodes


def _authored_lines(text: str) -> list[tuple[int, str]]:
    """Return prose lines while excluding code fences, blockquotes, and image source lines."""

    result: list[tuple[int, str]] = []
    in_fence = False
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.lstrip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or stripped.startswith(">") or stripped.startswith("!["):
            continue
        result.append((number, line))
    return result


def deterministic_findings(
    answer: str,
    manifest: Mapping[str, Any] | None = None,
    supported_parenthetical_source: str | None = None,
) -> list[dict[str, str]]:
    """Find profile-required defects without deciding open-ended writing quality."""

    findings: list[dict[str, str]] = []
    authored = _authored_lines(answer)
    authored_numbers = {number for number, _ in authored}
    official_english = {
        str(item.get("official_english"))
        for item in (manifest or {}).get("term_uses", [])
        if item.get("official_english")
    }
    professional_labels = {
        str(value).strip()
        for item in (manifest or {}).get("term_uses", [])
        for value in (item.get("term"), item.get("first_use_text"))
        if value
    }
    for number, line in authored:
        location = f"LINE-{number:04d}"
        list_item = bool(re.match(r"^\s{0,3}(?:[-*+]\s+|\d+[.)]\s+)", line))
        prose = re.sub(r"^\s{0,3}(?:[-*+]\s+|\d+[.)]\s+)", "", line)
        if "。" in line:
            findings.append(_finding(
                "LUCAS_NO_CHINESE_FULL_STOP", location, line,
                "生成中文正文含中文句号", "token",
            ))
        if line.rstrip().endswith("；"):
            findings.append(_finding(
                "LUCAS_NO_TRAILING_SEMICOLON", location, line,
                "段落或列表项末尾保留了中文分号", "token",
            ))
        colon_match = re.match(r"^(?!https?://|[A-Za-z]:\\|#{1,6}\s|\|)([^：:\n]{1,40})(?<!\d)[：:](?!\d)\s*(?:\S.*)?$", prose)
        professional_term_definition = bool(
            colon_match and colon_match.group(1).strip() in professional_labels
        )
        inline_review_metadata = bool(
            colon_match
            and re.fullmatch(
                r"复核编号\s+`?[A-Z](?=[A-Z0-9_-]*\d)[A-Z0-9_-]{1,79}`?",
                colon_match.group(1).strip(),
            )
            and prose[colon_match.end(1) + 1:].strip()
        )
        natural_introduction = bool(
            colon_match
            and re.search(
                r"(?:如下|包括|分别为|分别说明|分为|需要核对|需要完成|可按|例如|即|原因是|测量条件不同|会发生以下变化|(?:请)?按以下(?:内容|项目|事项|步骤|顺序|对象|证据|变化)(?:进行|操作|处理|完成)?|以下(?:内容|项目|事项|步骤|对象|证据|变化)|(?:以下|下面).*(?:是|为).+)$",
                colon_match.group(1).strip(),
            )
        )
        label_like_prefix = bool(
            colon_match
            and len(colon_match.group(1).strip()) <= 12
            and not re.search(r"[，；。！？、‘’“”《》()（）]", colon_match.group(1))
        )
        if (
            colon_match
            and not list_item
            and label_like_prefix
            and not natural_introduction
            and not inline_review_metadata
            and not professional_term_definition
            and not re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", prose)
        ):
            findings.append(_finding(
                "COLON_PSEUDO_HEADING", location, line,
                "内容使用冒号伪标题，应该取消标题或使用适当 Markdown 标题", "sentence",
            ))
        if re.search(r"(?:证据边界|验证边界|内部边界)\s*[：:]", line):
            findings.append(_finding(
                "INTERNAL_BOUNDARY_LABEL", location, line,
                "内部证据字段泄漏到用户可见正文", "sentence",
            ))
        parenthetical_pattern = (
            r"[（(]([A-Za-z][A-Za-z0-9'’+./ -]{1,80})[）)]"
            if supported_parenthetical_source is not None
            else r"[（(]([a-z][A-Za-z0-9 -]{1,80})[）)]"
        )
        for match in re.finditer(parenthetical_pattern, line):
            if match.group(1) in official_english:
                continue
            if supported_parenthetical_source is not None and match.group(1) in supported_parenthetical_source:
                continue
            findings.append(_finding(
                "PARENTHETICAL_ENGLISH_CASE", location, match.group(0),
                "括号内普通英文没有使用标题式大小写，或者新增英文没有来源与术语登记支持", "token",
            ))
    lines = answer.splitlines()
    for index, line in enumerate(lines[1:], start=1):
        previous = lines[index - 1]
        if (
            line.strip()
            and re.match(r"^\s{0,3}(?:[-*+]\s+|\d+[.)]\s+)", line)
            and previous.strip()
            and not re.match(r"^\s{0,3}(?:[-*+]\s+|\d+[.)]\s+)", previous)
            and not previous.lstrip().startswith((">", "#"))
        ):
            findings.append(_finding(
                "MISSING_BLOCK_SEPARATOR", f"LINE-{index + 1:04d}", line,
                "普通正文与随后列表之间缺少空行", "token",
            ))
        previous_nested_item = re.match(r"^(\s+)(?:[-*+]\s+|\d+[.)]\s+)", previous)
        current_item = re.match(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)", line)
        current_indent = len(line) - len(line.lstrip(" \t"))
        if (
            previous_nested_item
            and line.strip()
            and not current_item
            and current_indent == len(previous_nested_item.group(1))
            and index in authored_numbers
            and index + 1 in authored_numbers
        ):
            findings.append(_finding(
                "NESTED_LIST_AMBIGUOUS_CONTINUATION", f"LINE-{index + 1:04d}", line,
                "共同说明与最后一个嵌套项目使用相同缩进，结构上会错误附着到该子项；应该把共同说明放到父项中，再列出子项", "sentence",
            ))
    for index, line in enumerate(lines[1:-1], start=1):
        if line.strip():
            continue
        previous = lines[index - 1]
        following = lines[index + 1]
        previous_item = re.match(r"^(\s*)([-*+]\s+|\d+[.)]\s+)", previous)
        following_item = re.match(r"^(\s*)([-*+]\s+|\d+[.)]\s+)", following)
        following_indent = len(following) - len(following.lstrip(" \t"))
        previous_indent = len(previous_item.group(1)) if previous_item else 0
        separate_list_blocks = bool(
            previous_item
            and following_item
            and previous_indent == len(following_item.group(1))
            and bool(re.match(r"\d", previous_item.group(2)))
            != bool(re.match(r"\d", following_item.group(2)))
        )
        if previous_item and (
            (following_item and not separate_list_blocks)
            or (
                following.strip()
                and previous_indent > 0
                and following_indent >= previous_indent
            )
        ):
            findings.append(_finding(
                "LIST_INTERNAL_BLANK_LINE", f"LINE-{index + 1:04d}", "\n",
                "同一列表或嵌套列表内部出现空行", "token",
            ))
    if re.search(r"\n[ \t]*\n[ \t]*\n", answer):
        findings.append(_finding(
            "EXCESSIVE_BLANK_LINES", "DOCUMENT", "\n\n\n",
            "正文出现连续两个以上空行", "token",
        ))

    if manifest is None:
        return merge_findings(findings)

    section_plan = manifest.get("section_plan", {})
    headings = [(number, line) for number, line in authored if re.match(r"^#{1,6}\s+\S", line)]
    if section_plan.get("headings_required") and not headings:
        findings.append(_finding(
            "SECTION_PLAN_MISSING", "DOCUMENT", answer[:200] or "<empty>",
            "章节计划要求分区，但正文没有 Markdown 标题", "sentence",
        ))
    if not section_plan.get("headings_required") and headings:
        findings.append(_finding(
            "SECTION_PLAN_UNNECESSARY", f"LINE-{headings[0][0]:04d}", headings[0][1],
            "章节计划认为短内容不需要标题，但正文仍增加了标题", "sentence",
        ))
    declared_levels = set(section_plan.get("heading_levels", []))
    actual_levels = {len(re.match(r"^(#+)", line).group(1)) for _, line in headings}
    if headings and actual_levels != declared_levels:
        findings.append(_finding(
            "SECTION_LEVEL_MISMATCH", "DOCUMENT", headings[0][1],
            "正文标题层级与章节计划不一致", "token",
        ))

    for group in manifest.get("parallel_groups", []):
        group_id = str(group.get("group_id", "PGRP-UNKNOWN"))
        required_layout = str(group.get("required_layout", "indented_list"))
        item_lines: list[int] = []
        rendered_lines: list[str] = []
        missing: list[str] = []
        for item in group.get("item_texts", []):
            matches = [(number, line) for number, line in authored if item in line]
            if not matches:
                missing.append(item)
            else:
                item_lines.append(matches[0][0])
                rendered_lines.append(matches[0][1])
        if missing:
            findings.append(_finding(
                "PARALLEL_GROUP_COVERAGE", group_id, missing[0],
                "排比组登记项目没有全部出现在正文", "sentence",
            ))
        elif required_layout == "indented_list" and (
            len(set(item_lines)) != len(item_lines)
            or not group.get("rendered_as_indented_list")
            or not all(re.match(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)", line) for line in rendered_lines)
        ):
            old = next((line for number, line in authored if number in item_lines), group_id)
            findings.append(_finding(
                "PARALLEL_GROUP_LAYOUT", group_id, old,
                "两个以上同类项目没有逐项换行并按层级缩进", "sentence",
            ))
        elif required_layout == "compact_inline" and (
            len(set(item_lines)) != 1 or group.get("rendered_as_indented_list")
        ):
            old = next((line for number, line in authored if number in item_lines), group_id)
            findings.append(_finding(
                "PARALLEL_GROUP_LAYOUT", group_id, old,
                "排比组声明为紧凑同排，但项目实际分布在多个行或列表层级中", "sentence",
            ))

    for term in manifest.get("term_uses", []):
        english = term.get("official_english")
        first_use = str(term.get("first_use_text", ""))
        if first_use not in answer:
            findings.append(_finding(
                "TERM_FIRST_USE_LOCATION", str(term.get("term", "term")), first_use or str(term.get("term", "")),
                "术语登记的首次出现文本无法在答案中定位", "phrase",
            ))
        if english and english not in first_use:
            findings.append(_finding(
                "TERM_FIRST_USE_ENGLISH", str(term.get("term", "term")), first_use or str(term.get("term", "")),
                "专业词首次出现没有保留登记的官方英文", "phrase",
            ))
        first_occurrence = next(
            ((number, line) for number, line in authored if first_use and first_use in line),
            None,
        )
        if first_occurrence:
            first_number, first_line = first_occurrence
            first_prose = re.sub(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)", "", first_line)
            first_defines_term = bool(re.search(
                rf"{re.escape(first_use)}\s*(?:[：:]|是|指(?:的是)?|表示|用于)", first_prose,
            ))
            deferred_definition = next((
                (number, line)
                for number, line in authored
                if number > first_number
                and re.sub(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)", "", line).startswith(
                    (f"{first_use}：", f"{first_use}:")
                )
            ), None)
            if deferred_definition and not first_defines_term:
                findings.append(_finding(
                    "TERM_FIRST_USE_DEFERRED", f"LINE-{first_number:04d}", first_line,
                    "专业词首次出现只保留名称，完整解释被推迟到后置定义；必须在首次语义位置完成解释", "sentence",
                ))

    boundary = manifest.get("boundary_visibility", {})
    if boundary.get("mode") == "internal" and re.search(r"证据边界|验证边界|内部边界", "\n".join(line for _, line in authored)):
        findings.append(_finding(
            "BOUNDARY_VISIBILITY", "DOCUMENT", "证据边界",
            "边界计划要求内部保存，但正文暴露了内部标签", "phrase",
        ))
    if boundary.get("mode") == "natural_when_material" and not boundary.get("material_reason"):
        findings.append(_finding(
            "BOUNDARY_MATERIAL_REASON", "MANIFEST", "natural_when_material",
            "正文显示重要限制，但没有登记为什么会影响结论、操作或安全", "phrase",
        ))
    return merge_findings(findings)


def merge_findings(*groups: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate checker and Agent findings without discarding their first evidence."""

    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for group in groups:
        for raw in group:
            finding = dict(raw)
            key = (str(finding.get("rule_id")), str(finding.get("location")), str(finding.get("old_text")))
            if key in seen:
                continue
            seen.add(key)
            merged.append(finding)
    return merged


def close_answer(
    initial_answer: str,
    model: str,
    worker_session_id: str,
    manifest: Mapping[str, Any],
    repair_rounds: Sequence[Mapping[str, Any]],
    validators: Iterable[Callable[[str], Sequence[str] | None]] = (),
) -> tuple[str, dict[str, Any]]:
    """Apply at most three supplied exact-patch rounds and return a closure ledger."""

    if len(repair_rounds) > MAX_REPAIR_ROUNDS:
        raise ValueError("self-iterative closure cannot exceed three repair rounds")
    answer = initial_answer
    first_hash = sha256_text(answer)
    records: list[dict[str, Any]] = []
    status = FAIL
    for index, repair in enumerate(repair_rounds, start=1):
        deterministic = deterministic_findings(answer, manifest)
        semantic = list(repair.get("semantic_findings", []))
        combined = merge_findings(deterministic, semantic)
        if not combined:
            status = PASS
            break
        if any(item.get("status") == REVIEW_REQUIRED for item in combined):
            status = REVIEW_REQUIRED
            break
        before = sha256_text(answer)
        answer = apply_minimal_transaction(answer, repair.get("patches", []), line_nodes(answer), validators)
        after = sha256_text(answer)
        remaining = merge_findings(
            deterministic_findings(answer, manifest),
            repair.get("post_semantic_findings", []),
        )
        round_status = PASS if not remaining else FAIL
        records.append({
            "round": index,
            "reread_rules": True,
            "deterministic_finding_ids": [str(item["finding_id"]) for item in deterministic],
            "semantic_finding_ids": [str(item.get("finding_id", item.get("rule_id", "semantic"))) for item in semantic],
            "finding_rule_ids": list(dict.fromkeys(str(item["rule_id"]) for item in combined)),
            "patch_ids": [str(item["identity"]["patch_id"]) for item in repair.get("patches", [])],
            "patch_summaries": [
                {
                    "patch_id": str(item["identity"]["patch_id"]),
                    "finding_id": str(item["identity"]["finding_id"]),
                    "node_id": str(item["target"]["node_id"]),
                    "repair_scope": str(item["authorization"]["repair_scope"]),
                    "summary": str(item["authorization"]["reason"]),
                }
                for item in repair.get("patches", [])
            ],
            "before_sha256": before,
            "after_sha256": after,
            "result_status": round_status,
        })
        if any(item.get("status") == REVIEW_REQUIRED for item in remaining):
            status = REVIEW_REQUIRED
            break
        if round_status == PASS:
            status = PASS
            break
    else:
        if not deterministic_findings(answer, manifest):
            status = PASS
    if status != PASS:
        status = REVIEW_REQUIRED
    ledger = {
        "model": model,
        "worker_session_id": worker_session_id,
        "first_draft_sha256": first_hash,
        "final_sha256": sha256_text(answer),
        "max_repair_rounds": MAX_REPAIR_ROUNDS,
        "rounds": records,
        "status": status,
    }
    return answer, ledger
