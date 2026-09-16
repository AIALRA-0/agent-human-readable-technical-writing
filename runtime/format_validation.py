"""Observable format checks and explicitly marked context-dependent candidates.

The checker only reports observable character and block-structure defects.  It
does not decide open-ended style quality, factual correctness, or whether a
term is professional; those decisions remain with the writing Agent.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from typing import Any
from urllib.parse import unquote

from runtime.align_inline_comments import align_text, display_width, marker_index


def _finding(rule_id: str, location: str, old_text: str, reason: str, scope: str = "token", *, candidate: bool = False) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "status": "REVIEW_REQUIRED" if candidate else "FAIL",
        "severity": "MACHINE_CANDIDATE" if candidate else "MACHINE_FINAL",
        "location": location,
        "old_text": old_text,
        "reason": reason,
        "repair_scope": scope,
    }


def _authored_lines(text: str) -> list[tuple[int, str]]:
    protected = _protected_lines(text)
    return [(number, line) for number, line in enumerate(text.splitlines(), 1) if number not in protected]


def _without_inline_code(line: str) -> str:
    return _INLINE_MATERIAL.sub(lambda match: " " * len(match.group(0)), line)


def parenthetical_term_payload_issue(payload: str) -> str | None:
    """Return one observable impurity in a full-width English-name payload."""

    if re.search(r"[,，;；、]", payload):
        return "全角英文括号内混入逗号、分号或并列分隔符"
    if re.search(r"(?:也称|又称|简称|别名|亦称)|\b(?:also\s+known\s+as|a\.?k\.?a\.?|alias|short\s+for|meaning|means)\b", payload, re.IGNORECASE):
        return "全角英文括号内混入别名、简称或解释性表达"
    if re.search(r"[A-Za-z]", payload) and re.search(r"[\u3400-\u9fff]", payload):
        return "全角英文括号内混入中文别名或解释"
    return None


# Mask complete objects only: punctuation following a link or formula is prose.
_INLINE_MATERIAL = re.compile(
    r"(?<!`)(`+)(?!`).*?(?<!`)\1(?!`)"
    r"|!?\[[^\]\n]*\]\((?:[^()\n]|\([^()\n]*\))*\)"
    r"|!?\[[^\]\n]*\]\[[^\]\n]*\]"
    r"|<https?://[^>\n]+>"
    r"|(?<!\\)\$\$[^\n]*?(?<!\\)\$\$"
    r"|(?<![\\$])\$(?!\$)[^\n]*?(?<!\\)\$(?!\$)"
    r"|\\\([^\n]*?\\\)|\\\[[^\n]*?\\\]"
)


def _protected_lines(text: str) -> set[int]:
    """Locate source blocks, including fence delimiters, without rewriting them."""

    lines = text.splitlines()
    protected: set[int] = set()
    for start, _, body in _fenced_blocks(text):
        protected.update(range(start, min(len(lines), start + len(body) + 1) + 1))
    math_end: str | None = None
    table = False
    for number, line in enumerate(lines, 1):
        if number in protected:
            continue
        stripped = (line.removeprefix("\ufeff") if number == 1 else line).strip()
        if math_end:
            protected.add(number)
            if math_end in stripped:
                math_end = None
            continue
        for opening, closing in (("$$", "$$"), (r"\[", r"\]")):
            if stripped.startswith(opening):
                if closing not in stripped[len(opening):]:
                    protected.add(number)
                    math_end = closing
                elif stripped.endswith(closing):
                    protected.add(number)
                break
        if stripped.startswith(">") or re.match(r"^\s{0,3}\[[^\]]+\]:\s*\S", line):
            protected.add(number)
        # A delimiter row also identifies tables without outer pipes.
        if "|" in line and re.fullmatch(r"\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)+\|?\s*", line):
            protected.update((number - 1, number))
            table = True
        elif stripped.startswith("|") or (table and "|" in line and stripped):
            protected.add(number)
        else:
            table = False
    return protected


def _fenced_blocks(text: str) -> list[tuple[int, str, list[str]]]:
    blocks: list[tuple[int, str, list[str]]] = []
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        opening_line = lines[index].removeprefix("\ufeff") if index == 0 else lines[index]
        match = re.match(r"^\s*(`{3,}|~{3,})([^\n]*)$", opening_line)
        if not match:
            index += 1
            continue
        start = index + 1
        fence = match.group(1)
        language = match.group(2).strip().casefold()
        index += 1
        body: list[str] = []
        while index < len(lines) and not re.fullmatch(r"\s*" + re.escape(fence[0]) + "{" + str(len(fence)) + r",}\s*", lines[index]):
            body.append(lines[index])
            index += 1
        blocks.append((start, language, body))
        index += 1
    return blocks


def _is_structural_code_line(line: str) -> bool:
    stripped = line.strip()
    return not stripped or stripped in {"}", ")", "]", "};"} or re.fullmatch(r"[})\]]+[,;]?", stripped) is not None


def _comment_marker(language: str) -> str | None:
    if language in {"json", "jsonc", "text", "log", "console", "output"}:
        return None
    if language in {"python", "py", "shell", "bash", "sh", "yaml", "yml", "ruby", "perl"}:
        return "#"
    if language in {"sql", "postgresql", "mysql", "tsql"}:
        return "--"
    return "//"


def _is_legal_header_comment(line: str, marker: str) -> bool:
    stripped = line.strip()
    return stripped.startswith(marker) or (
        marker in {"--", "//"} and stripped.startswith("/*") and stripped.endswith("*/")
    )


def _label_is_negated(text: str, start: int) -> bool:
    return bool(re.search(r"(?:不是|并非|不属于|不作为|不能视为|不能当作|不要当作)[^，；：:。]*$", text[:start]))


def _code_context(lines: list[str], start: int) -> str:
    """Read a block's local role, not an incidental mention of original code."""

    context = lines[max(0, start - 5):start - 1]
    annotated = re.compile(
        r"(?:解释|注释|说明)副本|带(?:合法)?注释(?:的)?(?:版本|副本|代码|读法)|注释版"
        r"|(?:只|仅)(?:增加|添加|补充)(?:中文)?注释"
        r"|(?:另加|增加|加入|添加)(?:中文)?说明的副本"
    )
    original = re.compile(r"(?:原始|原件|逐字|原样)(?:代码|查询|脚本|配置|内容)?|原代码")
    for line in reversed(context):
        stripped = line.strip()
        if not stripped:
            continue
        # An explicitly named explanation copy remains authored even when the
        # same sentence says its executable statements match the original.
        if any(not _label_is_negated(stripped, match.start()) for match in annotated.finditer(stripped)):
            return "annotated"
        if any(not _label_is_negated(stripped, match.start()) for match in original.finditer(stripped)):
            return "literal"
        if stripped.startswith(("#", "```", "~~~")):
            break
    return "unknown"


def _literal_code_context(lines: list[str], start: int) -> bool:
    return _code_context(lines, start) == "literal"


def code_preservation_roles(text: str) -> list[str]:
    """Freeze source roles before a patch; changing a caption grants no rights."""

    lines = text.splitlines()
    return [_code_context(lines, start) for start, _, _ in _fenced_blocks(text)]


def _code_findings(text: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    text_lines = text.splitlines()
    for start, language, body in _fenced_blocks(text):
        if _literal_code_context(text_lines, start):
            continue
        # A displayed input/result is data even if its fence uses Python
        # highlighting. Require both a local data caption and a literal parse;
        # a caption cannot exempt assignments, calls, or other executable code.
        if _literal_data_body(body, language):
            context = text_lines[max(0, start - 5):start - 1]
            displayed_data = False
            for caption in reversed(context):
                if not caption.strip():
                    continue
                data_label = re.search(r"(?:示例|给定|原始|测试|本次|最终)?(?:的)?(?:输入|输出)(?:数据)?(?:是|如下|为|：|:)|(?:返回|交回|输出|得到).*(?:结果|列表)|(?:最终|返回)结果", caption)
                if data_label:
                    displayed_data = not _label_is_negated(caption, data_label.start())
                    break
                if caption.lstrip().startswith(("#", "```", "~~~")):
                    break
            if displayed_data:
                continue
        comment_marker = _comment_marker(language)
        if comment_marker is None:
            if language in {"json", "jsonc"} and any(
                marker_index(line, "//") >= 0 or marker_index(line, "#") >= 0 for line in body
            ):
                findings.append(_finding(
                    "FORMAT_JSON_COMMENT", f"LINE-{start:04d}", body[0] if body else "JSON",
                    "JSON 代码块使用了非法注释，应改为逐行解释", "sentence",
                ))
            continue
        inline: list[tuple[int, str, str]] = []
        for offset, line in enumerate(body):
            position = marker_index(line, comment_marker)
            if position >= 0 and line[:position].strip() and not line[:position].rstrip().endswith(comment_marker):
                inline.append((start + offset + 1, line[:position], line[position:]))
                if "、" in line[position + len(comment_marker):]:
                    findings.append(_finding(
                        "FORMAT_CODE_COMMENT_ENUMERATION", f"LINE-{start + offset + 1:04d}", line,
                        "注释含顿号，是否表达多个独立项目须结合语境复核", "phrase", candidate=True,
                    ))
        if not inline:
            if not any(line.lstrip().startswith(comment_marker) for line in body if line.strip()):
                findings.append(_finding(
                    "FORMAT_CODE_COMMENT_COVERAGE", f"LINE-{start:04d}", body[0] if body else "CODE",
                    "能合法添加注释的代码块既没有合法头行注释，也没有同行注释", "sentence",
                ))
            continue
        commentable = [
            (start + offset + 1, line)
            for offset, line in enumerate(body)
            if not _is_structural_code_line(line)
            and not _is_legal_header_comment(line, comment_marker)
        ]
        if len(inline) != len(commentable):
            findings.append(_finding(
                "FORMAT_CODE_COMMENT_COVERAGE", f"LINE-{start:04d}", body[0] if body else "```",
                "使用同行注释的代码块没有覆盖每个可注释有效语句", "sentence",
            ))
        widths = [display_width(code.rstrip(" \t")) for _, code, _ in inline]
        if widths:
            target = max(widths) + 2
            positions = [display_width(code) + 1 for _, code, _ in inline]
            if any(position != target for position in positions):
                findings.append(_finding(
                    "FORMAT_CODE_COMMENT_ALIGNMENT", f"LINE-{start:04d}", inline[0][2],
                    "同行注释没有在当前代码块内从最长可注释行宽后的统一目标列开始", "phrase",
                ))
        if language in {"json", "jsonc"} and any("//" in line or "#" in line for line in body):
            findings.append(_finding(
                "FORMAT_JSON_COMMENT", f"LINE-{start:04d}", body[0] if body else "```json",
                "JSON 代码块使用了非法注释，应改为逐行解释", "sentence",
            ))
    return findings


def _distinct_peer_lists(previous: str, following: str) -> bool:
    """Different list markers at the same indentation start separate blocks."""

    pattern = r"^([ \t]*)([-*+]|\d+([.)]))\s+"
    first = re.match(pattern, previous)
    second = re.match(pattern, following)
    if not first or not second:
        return False
    first_kind = first.group(3) or first.group(2)
    second_kind = second.group(3) or second.group(2)
    return (
        len(first.group(1).expandtabs(4)) == len(second.group(1).expandtabs(4))
        and first_kind != second_kind
    )


def _distinct_list_boundary(lines: list[str], following_index: int) -> bool:
    """Compare list peers, not a previous list's final nested child."""

    pattern = r"^([ \t]*)(?:[-*+]|\d+[.)])\s+"
    following = re.match(pattern, lines[following_index])
    if not following:
        return False
    indent = len(following.group(1).expandtabs(4))
    for previous in reversed(lines[:following_index]):
        if not previous.strip():
            continue
        peer = re.match(pattern, previous)
        if not peer:
            return False
        previous_indent = len(peer.group(1).expandtabs(4))
        if previous_indent > indent:
            continue
        if previous_indent < indent:
            return False
        return _distinct_peer_lists(previous, lines[following_index])
    return False


def _nested_list_start(previous: str, following: str) -> bool:
    pattern = r"^([ \t]*)(?:[-*+]|\d+[.)])\s+"
    parent, child = re.match(pattern, previous), re.match(pattern, following)
    return bool(parent and child and len(child[1].expandtabs(4)) > len(parent[1].expandtabs(4)))


def _list_continuation_parent(lines: list[str], index: int) -> str | None:
    """Recognize indented prose continuation without treating it as a new block."""

    current = lines[index]
    indent = len(current) - len(current.lstrip(" \t"))
    indent = len(current[:indent].expandtabs(4))
    if not indent:
        return None
    for previous in reversed(lines[:index]):
        if not previous.strip():
            continue
        marker = re.match(r"^([ \t]*(?:[-*+]|\d+[.)])\s+)", previous)
        if marker and indent >= len(marker[1].expandtabs(4)):
            return previous
        leading = previous[:len(previous) - len(previous.lstrip(" \t"))]
        if len(leading.expandtabs(4)) < indent or previous.lstrip().startswith(("#", "```", "~~~", ">", "|")):
            return None
    return None


def _list_spacing_findings(text: str, *, host_nested_blank: bool = False) -> list[dict[str, Any]]:
    """Find blank nodes placed directly between Markdown list items."""

    findings: list[dict[str, Any]] = []
    lines = text.splitlines(keepends=True)
    protected = _protected_lines(text)
    list_item = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)")
    for index, line in enumerate(lines):
        if any(number in protected for number in (index, index + 1, index + 2)) or line.strip() or index == 0 or index + 1 >= len(lines):
            continue
        previous = lines[index - 1].rstrip("\r\n")
        following = lines[index + 1].rstrip("\r\n")
        if host_nested_blank and _nested_list_start(previous, following):
            continue
        if list_item.match(previous) and list_item.match(following) and not _distinct_list_boundary(lines, index + 1):
            findings.append(_finding(
                "FORMAT_LIST_INTERNAL_BLANK", f"LINE-{index + 1:04d}", line,
                "同一 Markdown 列表的相邻项目之间存在空行", "token",
            ))
    return findings


def _block_spacing_findings(text: str, *, host_nested_blank: bool = False) -> list[dict[str, Any]]:
    """Find adjacent Markdown block types that require one separating blank line."""

    lines = text.splitlines(keepends=True)
    kinds: list[str] = []
    protected = _protected_lines(text)
    fences = {start for start, _, _ in _fenced_blocks(text)}
    fences.update(start + len(body) + 1 for start, _, body in _fenced_blocks(text))
    for number, line in enumerate(lines, 1):
        stripped = line.lstrip()
        if number in fences:
            kinds.append("fence")
        elif not line.strip():
            kinds.append("blank")
        elif re.match(r"^\s*#{1,6}\s+", line):
            kinds.append("heading")
        elif re.match(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)", line):
            kinds.append("list")
        elif stripped.startswith(">"):
            kinds.append("quote")
        elif stripped.startswith("|"):
            kinds.append("table")
        elif stripped.startswith("!["):
            kinds.append("image")
        elif number in protected:
            kinds.append("source")
        elif _list_continuation_parent(lines, number - 1) is not None:
            kinds.append("list_continuation")
        else:
            kinds.append("paragraph")
    structural = {"fence", "heading", "list", "quote", "table", "image"}
    findings: list[dict[str, Any]] = []
    for index in range(1, len(lines)):
        previous = kinds[index - 1]
        current = kinds[index]
        if "blank" in {previous, current} or (index in protected and index + 1 in protected):
            continue
        separate_lists = previous == current == "list" and _distinct_list_boundary(lines, index)
        if host_nested_blank and previous == current == "list" and _nested_list_start(lines[index - 1], lines[index]):
            separate_lists = True
        if current == "list_continuation" and previous in {"list", "list_continuation"}:
            continue
        if previous == "list_continuation" and current == "list":
            parent = _list_continuation_parent(lines, index - 1)
            separate_lists = bool(parent and (
                _distinct_peer_lists(parent, lines[index]) or
                (host_nested_blank and _nested_list_start(parent, lines[index]))
            ))
            if not separate_lists:
                continue
        if (previous == current and not separate_lists) or not ({previous, current} & structural):
            continue
        findings.append(_finding(
            "FORMAT_BLOCK_SPACING", f"LINE-{index + 1:04d}", lines[index],
            "不同 Markdown 块级结构之间缺少一个空行", "token",
        ))
    return findings


def _simple_sql_comment_positions(body: list[str], language: str) -> dict[int, int] | None:
    """Accept only the single-line SQL subset we can preserve byte-for-byte."""

    source = "\n".join(body)
    if any(token in source for token in ("/*", "*/", "$$", "\\", "`", "[", "]")) or re.search(r"\$\w+\$", source):
        return None
    positions = {}
    for number, line in enumerate(body, 1):
        position = marker_index(line, "--")
        if position >= 0:
            # MySQL treats --1 as subtraction, not as a comment. Do not normalize
            # this ambiguous subset: https://dev.mysql.com/doc/refman/8.4/en/ansi-diff-comments.html
            if language == "mysql" and position + 2 < len(line) and not line[position + 2].isspace():
                return None
            positions[number] = position
        code = line[:position] if position >= 0 else line
        if code.count("'") % 2 or code.count('"') % 2:
            return None
    return positions


def _safe_aligned_body(body: list[str], language: str, marker: str) -> list[str] | None:
    """Do not treat markers in multiline strings or unknown syntax as comments."""

    source = "\n".join(body)
    if language in {"python", "py"}:
        try:
            tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
        except (tokenize.TokenError, IndentationError, SyntaxError):
            return None
        comments = {(token.start[0], token.start[1]) for token in tokens if token.type == tokenize.COMMENT}
        for number, line in enumerate(body, 1):
            position = marker_index(line, marker)
            if position >= 0 and line[:position].strip() and (number, position) not in comments:
                return None
    elif language in {"sql", "postgresql", "mysql", "tsql"}:
        if _simple_sql_comment_positions(body, language) is None:
            return None
    else:
        return None
    try:
        return align_text(source, marker).splitlines()
    except ValueError:
        return None


def deterministic_format_replacements(text: str, *, host_nested_blank: bool = False) -> list[dict[str, str]]:
    """Fix spacing, comment alignment and authored physical-line-final 。 or ；.

    Full lines provide unique matching context; only the terminal character is
    deleted. Interior punctuation and protected inline objects stay untouched.
    """

    replacements: list[dict[str, str]] = []
    lines = text.splitlines(keepends=True)
    for finding in _list_spacing_findings(text, host_nested_blank=host_nested_blank):
        replacements.append({
            "rule_id": str(finding["rule_id"]),
            "node_id": str(finding["location"]),
            "old_text": str(finding["old_text"]),
            "new_text": "",
        })
    for finding in _block_spacing_findings(text, host_nested_blank=host_nested_blank):
        replacements.append({
            "rule_id": str(finding["rule_id"]),
            "node_id": str(finding["location"]),
            "old_text": str(finding["old_text"]),
            "new_text": ("\r\n" if "\r\n" in text else "\n") + str(finding["old_text"]),
        })
    plain_lines = text.splitlines()
    for start, language, body in _fenced_blocks(text):
        if _literal_code_context(plain_lines, start):
            continue
        marker = _comment_marker(language)
        if marker is None or not any(marker_index(line, marker) >= 0 for line in body):
            continue
        aligned = _safe_aligned_body(body, language, marker)
        if aligned is None:
            continue
        for offset, (old_line, new_line) in enumerate(zip(body, aligned)):
            if old_line == new_line:
                continue
            line_number = start + offset + 1
            old_node = lines[line_number - 1]
            ending = old_node[len(old_node.rstrip("\r\n")):]
            replacements.append({
                "rule_id": "FORMAT_CODE_COMMENT_ALIGNMENT",
                "node_id": f"LINE-{line_number:04d}",
                "old_text": old_node,
                "new_text": new_line + ending,
            })
    by_node = {replacement["node_id"]: replacement for replacement in replacements}
    for number, line in _authored_lines(text):
        end = len(line.rstrip(" \t"))
        if not end or line[end - 1] not in "。；":
            continue
        prose = _without_inline_code(line)
        if prose[end - 1] != line[end - 1]:
            continue
        # A bare URL has no closing delimiter proving that its last character
        # is prose punctuation; leave that ambiguous suffix alone.
        if re.search(r"(?:https?://|www\.)\S*$", prose[:end]):
            continue
        old_node = lines[number - 1]
        new_node = old_node[:end - 1] + old_node[end:]
        node_id = f"LINE-{number:04d}"
        rule_id = "FORMAT_NO_CHINESE_FULL_STOP" if line[end - 1] == "。" else "FORMAT_NO_TRAILING_SEMICOLON"
        if node_id in by_node:
            # Block spacing may already replace this entire line. Compose the
            # deletion into that proposal instead of submitting overlapping edits.
            previous = by_node[node_id]
            if previous["old_text"] != old_node or not previous["new_text"].endswith(old_node):
                raise ValueError(f"cannot compose terminal punctuation fix for {node_id}")
            previous["new_text"] = previous["new_text"][:-len(old_node)] + new_node
            previous["rule_id"] += "+" + rule_id
        else:
            replacements.append({
                "rule_id": rule_id,
                "node_id": node_id,
                "old_text": old_node,
                "new_text": new_node,
            })
    return replacements


def _comment_free_body(body: list[str], language: str) -> list[str | None] | None:
    """For an explicit explanation copy, protect code but allow human comments."""

    source = "\n".join(body)
    multiline_string_lines: set[int] = set()
    if language in {"python", "py"}:
        try:
            ast.parse(source)
            tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
        except (tokenize.TokenError, IndentationError, SyntaxError, ValueError):
            return None
        positions = {token.start[0]: token.start[1] for token in tokens if token.type == tokenize.COMMENT}
        for token in tokens:
            if token.type == tokenize.STRING:
                multiline_string_lines.update(range(token.start[0], token.end[0]))
    elif language in {"sql", "postgresql", "mysql", "tsql"}:
        positions = _simple_sql_comment_positions(body, language)
        if positions is None:
            return None
    else:
        return None
    result: list[str | None] = []
    for number, line in enumerate(body, 1):
        if number not in positions:
            result.append(line if number in multiline_string_lines else line.rstrip(" \t"))
            continue
        prefix = line[:positions[number]].rstrip(" \t")
        result.append(prefix if prefix.strip() else None)
    return result


def _literal_data_body(body: list[str], language: str) -> bool:
    if language not in {"python", "py", "json", "text", "output"}:
        return False
    source = "\n".join(body)
    try:
        ast.literal_eval(source)
        return True
    except (SyntaxError, ValueError):
        try:
            import json
            json.loads(source)
            return True
        except (ValueError, TypeError):
            return False


def protected_inline_material(text: str) -> list[str]:
    """Authored explanation may repeat/reorder references, not change their bytes."""

    return [match.group(0) for _, line in _authored_lines(text) for match in _INLINE_MATERIAL.finditer(line)]


def protected_format_material(
    text: str, *, code_roles: list[str] | None = None, include_inline: bool = True,
) -> list[str]:
    """Snapshot literal objects and executable text of explicit explanation copies.

    This checks character preservation, not source meaning or completeness.
    Unmarked prose is authored text; literal prose must use a quote or fence.
    """

    lines = text.splitlines(keepends=True)
    blocks = _fenced_blocks(text)
    roles = code_preservation_roles(text) if code_roles is None else code_roles
    if len(roles) != len(blocks):
        return ["CODE_BLOCK_COUNT_CHANGED"]
    omitted: set[int] = set()
    for (start, language, body), role in zip(blocks, roles):
        if role == "literal":
            continue
        if _literal_data_body(body, language):
            # The authored fence label is presentation, not data. Body bytes stay
            # protected, so changing Python values into different JSON is rejected.
            ending = lines[start - 1][len(lines[start - 1].rstrip("\r\n")):]
            lines[start - 1] = "```LITERAL_DATA" + ending
            continue
        if role == "annotated":
            code_body = _comment_free_body(body, language)
            if code_body is not None:
                for offset, new_line in enumerate(code_body, start):
                    if new_line is None:
                        omitted.add(offset + 1)
                    else:
                        ending = lines[offset][len(lines[offset].rstrip("\r\n")):]
                        lines[offset] = new_line + ending
                continue
        marker = _comment_marker(language)
        aligned = _safe_aligned_body(body, language, marker) if marker else None
        if aligned is not None:
            for offset, new_line in enumerate(aligned, start):
                ending = lines[offset][len(lines[offset].rstrip("\r\n")):]
                lines[offset] = new_line + ending
    protected = _protected_lines(text)
    material: list[str] = []
    for number, line in enumerate(lines, 1):
        if number in omitted:
            continue
        if number in protected:
            material.append(line)
        elif include_inline:
            material.extend(match.group(0) for match in _INLINE_MATERIAL.finditer(line))
    return material


def _semantic_review_candidates(text: str) -> list[dict[str, Any]]:
    """Point to visible review targets, never infer a term or independent action."""

    authored = [(number, _without_inline_code(line)) for number, line in _authored_lines(text)]
    definition = re.compile(r"^\s*[-*+]\s+(?:[A-Za-z][A-Za-z0-9.-]*\s+)?(?P<zh>[\u3400-\u9fff][^（）：\n]*?)（(?P<en>[^（）\n]+)）：")
    terms: dict[str, tuple[int, str]] = {}
    definition_lines: dict[int, str] = {}
    for number, line in authored:
        match = definition.match(line)
        if match:
            name = match["zh"].strip()
            terms.setdefault(name, (number, match["en"]))
            definition_lines[number] = name
    originals = dict(_authored_lines(text))
    findings = []
    for number, prose in authored:
        location = f"LINE-{number:04d}"
        multiple_questions = len(re.findall(r"[？?]", prose)) > 1
        ordinary_prose = bool(prose.strip()) and not re.match(r"^\s*#{1,6}\s+", prose)
        if number not in definition_lines and ordinary_prose and (re.search(r"[、，；]|以及|并且|同时|或者", prose) or multiple_questions):
            findings.append(_finding(
                "FORMAT_PARALLEL_ITEMS_REVIEW", location, originals[number],
                "此段落或列表项含多个连接或分隔位置，请核对是否为可分别执行、核对或比较的项目；同一因果过程和同一动作的解释可保持连贯，标点本身不证明违规", "sentence", candidate=True,
            ))
        for name, (first_definition, english) in terms.items():
            if name not in prose:
                continue
            if number < first_definition and number not in definition_lines:
                findings.append(_finding(
                    "FORMAT_DEFINED_TERM_EARLY_USE_REVIEW", location, name,
                    "正文在后文正式定义前已出现同名词语，请核对此处是否实际使用该专业概念；普通同名词和原始对象不据此判错", "phrase", candidate=True,
                ))
            elif number in definition_lines and definition_lines[number] != name:
                paired = re.sub(re.escape(name) + r"\s*（" + re.escape(english) + r"）", "", prose)
                if name in paired:
                    findings.append(_finding(
                        "FORMAT_NESTED_DEFINED_TERM_REVIEW", location, name,
                        "此定义内部出现了本篇另一个已正式定义的名称，但未使用它在本篇声明的完整中英文配对；先确认是否同一专业概念，确认后只补短标签，不递归展开定义", "phrase", candidate=True,
                    ))
    return findings


def _heading_structure_findings(text: str) -> list[dict[str, Any]]:
    """Check observable heading shape without guessing semantic section boundaries."""

    lines = text.splitlines()
    protected = _protected_lines(text)
    headings: list[tuple[int, int, str]] = []
    for number, line in enumerate(lines, 1):
        if number in protected:
            continue
        match = re.match(r"^\s{0,3}(#{1,6})\s+(.+?)\s*$", line)
        if match:
            headings.append((number, len(match.group(1)), match.group(2)))
    findings: list[dict[str, Any]] = []
    for number, _, title in headings:
        prefix = re.match(r"^(\d+(?:\.\d+)*)([.、]?)(\s*)(?=[^\d\s])", title)
        if prefix and (prefix[2] != "." or not prefix[3]):
            findings.append(_finding(
                "FORMAT_HEADING_NUMBER_SUFFIX_REVIEW", f"LINE-{number:04d}", lines[number - 1],
                "若此数字是当前采用的阿拉伯数字层级编号，完整编号后应有点号和空格；先区分年份、数量、原文语义编号和原样保留内容，不自动修改", "phrase", candidate=True,
            ))
    for previous, current in zip(headings, headings[1:]):
        if current[1] > previous[1] + 1:
            findings.append(_finding(
                "FORMAT_HEADING_LEVEL_SKIP", f"LINE-{current[0]:04d}", lines[current[0] - 1],
                "标题从上一个标题跳过了必要层级，不能只为视觉大小跨级", "sentence",
            ))
    by_level: dict[int, list[tuple[int, str]]] = {}
    for number, level, title in headings:
        by_level.setdefault(level, []).append((number, title))
    number_prefix = re.compile(r"^\d+(?:\.\d+)*(?:[.、]?\s+)")
    for level, peers in by_level.items():
        if len(peers) < 2:
            continue
        numbered = [bool(number_prefix.match(title)) for _, title in peers]
        if any(numbered) and not all(numbered):
            number, title = peers[numbered.index(False)]
            findings.append(_finding(
                "FORMAT_HEADING_NUMBERING_REVIEW", f"LINE-{number:04d}", lines[number - 1],
                f"同一层级的标题混用编号与无编号形式，需核对当前文档的统一标题体系，标题层级为 {level}",
                "sentence", candidate=True,
            ))
    if headings:
        first_heading = headings[0][0]
        intro = [
            (number, line) for number, line in enumerate(lines[:first_heading - 1], 1)
            if number not in protected and line.strip() and not re.match(r"^\s*</?(?:div|p|h1)\b", line, re.IGNORECASE)
        ]
        paragraph_groups = 0
        previous_number: int | None = None
        for number, _ in intro:
            if previous_number is None or number > previous_number + 1:
                paragraph_groups += 1
            previous_number = number
        if paragraph_groups > 1 or any(re.match(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)", line) for _, line in intro):
            number, line = intro[0]
            findings.append(_finding(
                "FORMAT_HEADING_INTRO_SCOPE_REVIEW", f"LINE-{number:04d}", line,
                "第一处标题前存在多个正文块或列表，需核对它们是否已经承载独立内容；标题前导语只能概括全文目标",
                "sentence", candidate=True,
            ))
    return findings


def _display_math_blocks(text: str) -> list[tuple[int, int, str]]:
    """Return displayed math outside fenced code, quotes, and tables."""

    lines = text.splitlines()
    fenced_lines: set[int] = set()
    for start, _, body in _fenced_blocks(text):
        fenced_lines.update(range(start, min(len(lines), start + len(body) + 1) + 1))
    blocks: list[tuple[int, int, str]] = []
    index = 0
    while index < len(lines):
        number = index + 1
        stripped = lines[index].strip()
        if number in fenced_lines or lines[index].lstrip().startswith(">"):
            index += 1
            continue
        opening = next((item for item in (("$$", "$$"), (r"\[", r"\]")) if stripped.startswith(item[0])), None)
        if opening is None:
            index += 1
            continue
        start = number
        body = stripped[len(opening[0]):]
        if opening[1] in body:
            expression = body.split(opening[1], 1)[0]
            blocks.append((start, start, expression))
            index += 1
            continue
        collected: list[str] = []
        if body:
            collected.append(body)
        index += 1
        while index < len(lines):
            current = lines[index]
            if opening[1] in current:
                collected.append(current.split(opening[1], 1)[0])
                break
            collected.append(current)
            index += 1
        end = min(index + 1, len(lines))
        blocks.append((start, end, "\n".join(collected)))
        index += 1
    return blocks


def _formula_symbols(expression: str) -> list[str]:
    """Extract conservative single-letter free-symbol candidates from common TeX."""

    greek_names = (
        "alpha", "beta", "gamma", "delta", "epsilon", "varepsilon", "zeta", "eta", "theta", "vartheta",
        "iota", "kappa", "lambda", "mu", "nu", "xi", "omicron", "pi", "varpi", "rho", "varrho",
        "sigma", "varsigma", "tau", "upsilon", "phi", "varphi", "chi", "psi", "omega",
        "Gamma", "Delta", "Theta", "Lambda", "Xi", "Pi", "Sigma", "Upsilon", "Phi", "Psi", "Omega",
    )
    greek_pattern = r"\\(?:" + "|".join(greek_names) + r")(?![A-Za-z])"
    symbols = set(re.findall(greek_pattern, expression))
    cleaned = re.sub(r"\\(?:text|mathrm|operatorname)\s*\{[^{}]*\}", " ", expression)
    cleaned = re.sub(r"\\[A-Za-z]+", " ", cleaned)
    symbols.update(re.findall(r"(?<![A-Za-z])[A-Za-z](?![A-Za-z])", cleaned))
    return sorted(symbols)


def _formula_review_candidates(text: str) -> list[dict[str, Any]]:
    """Point to observable formula-explanation gaps without certifying meaning."""

    lines = text.splitlines()
    findings: list[dict[str, Any]] = []
    heading_pattern = re.compile(r"^\s{0,3}#{1,6}\s+")
    seen_symbols: set[str] = set()
    for start, end, expression in _display_math_blocks(text):
        before = lines[max(0, start - 13):start - 1]
        after = lines[end:min(len(lines), end + 32)]
        context = "\n".join([*before, *after])
        if not any(heading_pattern.match(line) for line in lines[:start - 1]):
            findings.append(_finding(
                "FORMAT_FORMULA_HEADING_REVIEW", f"LINE-{start:04d}", lines[start - 1],
                "独立公式附近没有可观察到的所属标题，需核对它是附带公式还是应当使用说明用途的相对大标题",
                "sentence", candidate=True,
            ))
        symbols = _formula_symbols(expression)
        new_symbols = [symbol for symbol in symbols if symbol not in seen_symbols]
        missing = []
        for symbol in new_symbols:
            listed = re.search(
                r"(?m)^\s*[-*+]\s+[^\n]*\$[^$\n]*" + re.escape(symbol) + r"[^$\n]*\$[^\n]+",
                context,
            )
            if listed is None:
                missing.append(symbol)
        if missing:
            findings.append(_finding(
                "FORMAT_FORMULA_SYMBOL_REVIEW", f"LINE-{start:04d}", lines[start - 1],
                "独立公式中的符号没有全部出现在附近的连续列表项说明中，需核对：" + "、".join(missing),
                "sentence", candidate=True,
            ))
        complex_formula = bool(
            re.search(r"\\(?:frac|sum|prod|int|nabla|partial)|[_^]|\([^)]*[+\-*/][^)]*\)", expression)
        )
        component_line = False
        for line in after:
            if not re.match(r"^\s*[-*+]\s+", line):
                continue
            inline_formulas = re.findall(r"\$([^$\n]+)\$", line)
            joined = " ".join(inline_formulas)
            if len(_formula_symbols(joined)) >= 2 or any(
                re.search(r"\\(?:frac|sum|prod|int|nabla|partial)|[+\-*/]", formula)
                for formula in inline_formulas
            ):
                component_line = True
                break
        if complex_formula and new_symbols and not component_line:
            findings.append(_finding(
                "FORMAT_FORMULA_COMPONENT_REVIEW", f"LINE-{start:04d}", lines[start - 1],
                "公式含有组合结构，但附近没有可观察到的多符号组分列表项，需核对关键分子、分母、差值、加权项或矩阵乘积是否已经解释",
                "sentence", candidate=True,
            ))
        seen_symbols.update(symbols)
    return findings


def _image_address(address: str, *, markdown: bool = False) -> str:
    address = address.strip().removeprefix("<").removesuffix(">")
    if markdown and not re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", address):
        address = unquote(address)
    if re.match(r"^[A-Za-z]:[\\/]", address):
        return address.replace("\\", "/").casefold()
    return address


def _inline_image_parts(raw: str) -> tuple[str, str, str] | None:
    if not _INLINE_MATERIAL.fullmatch(raw) or not raw.startswith("![") or "](" not in raw:
        return None
    alt, address = raw[2:-1].split("](", 1)
    title = re.search(r'''\s+["'][^"']*["']$''', address)
    return alt, address[:title.start()] if title else address, title[0] if title else ""


def permitted_source_image_edit(old: str, new: str, expected_images: list[str]) -> bool:
    """Allow a whole image's local correction, not replacement of known sources."""

    before, after = _inline_image_parts(old), _inline_image_parts(new)
    if not before or not after or before[2] != after[2] or not after[0].strip():
        return False
    expected = {_image_address(item) for item in expected_images}
    old_address, new_address = _image_address(before[1], markdown=True), _image_address(after[1], markdown=True)
    if new_address not in expected:
        return False
    if old_address in expected and old_address != new_address:
        return False  # One supplied image may never be swapped for another.
    # Existing accurate-address objects retain their authored alt unless it was
    # empty. Correcting a wrong address must not rewrite the existing caption.
    return before[0] == after[0] or (old_address == new_address and not before[0].strip())


def source_image_findings(text: str, expected_images: list[str]) -> list[dict[str, Any]]:
    """Check supplied image addresses only, without fetching or judging content."""
    objects: list[tuple[str, str, int, str]] = []
    code_lines = {number for start, _, body in _fenced_blocks(text) for number in range(start, start + len(body) + 2)}
    references: dict[str, str] = {}
    for number, line in enumerate(text.splitlines(), 1):
        if number not in code_lines:
            definition = re.match(r"^\s{0,3}\[([^\]]+)\]:\s*(<[^>]+>|\S+)", line)
            if definition:
                references.setdefault(" ".join(definition[1].split()).casefold(), definition[2])
    for number, line in enumerate(text.splitlines(), 1):
        if number in code_lines:
            continue
        for match in _INLINE_MATERIAL.finditer(line):
            raw = match.group(0)
            parts = _inline_image_parts(raw)
            if parts is None:
                reference = re.fullmatch(r"!\[([^\]]*)\]\[([^\]]*)\]", raw)
                if reference:
                    label = " ".join((reference[2] or reference[1]).split()).casefold()
                    if label in references:
                        objects.append((_image_address(references[label], markdown=True), reference[1], number, raw))
                continue
            alt, address, _ = parts
            objects.append((_image_address(address, markdown=True), alt, number, raw))
    first_line = next(iter(text.splitlines()), "")
    findings = []
    for source in dict.fromkeys(expected_images):
        matches = [item for item in objects if item[0] == _image_address(source)]
        if not matches:
            findings.append(_finding(
                "FORMAT_SOURCE_IMAGE_MISSING", "LINE-0001" if first_line else "DOCUMENT", first_line,
                "本次明确提供的图片地址未作为图片对象保留在正文中：" + source, "sentence",
            ))
        elif not any(alt.strip() for _, alt, _, _ in matches):
            _, _, number, raw = matches[0]
            findings.append(_finding(
                "FORMAT_SOURCE_IMAGE_ALT_MISSING", f"LINE-{number:04d}", raw,
                "已保留本次图片，但替代文本为空；描述必须据可见内容填写，程序不代写", "phrase",
            ))
    return findings


def _html_layout_lines(text: str) -> tuple[set[int], set[int], dict[int, set[int]]]:
    """Inspect inline container hints, not computed CSS or rendered geometry."""

    centered: set[int] = set()
    scrolling: set[int] = set()
    scopes: dict[int, set[int]] = {}
    stack: list[tuple[str, set[int], bool]] = []
    tag_pattern = re.compile(r"</?(div|details|section|figure|p)\b[^>]*>", re.IGNORECASE)
    protected = {
        number for start, _, body in _fenced_blocks(text)
        for number in range(start, start + len(body) + 2)
    }
    next_scope = 0
    for number, line in enumerate(text.splitlines(), 1):
        if number in protected or line.lstrip().startswith(">"):
            continue
        content_scopes: list[set[int]] = []
        content_scroll: list[bool] = []
        cursor = 0
        for match in tag_pattern.finditer(line):
            if line[cursor:match.start()].strip():
                content_scopes.append(set(stack[-1][1]) if stack else set())
                content_scroll.append(stack[-1][2] if stack else False)
            cursor = match.end()
            tag = match.group(0)
            name = match.group(1).casefold()
            if tag.startswith("</"):
                if stack and stack[-1][0] == name:
                    stack.pop()
                continue
            lower = tag.casefold()
            inherited = set(stack[-1][1]) if stack else set()
            # An inner explicit alignment overrides inheritance; CSS beats align.
            css = re.findall(r"text-align\s*:\s*(center|left|right|start|end|justify)\b", lower)
            attribute = re.search(r"\balign\s*=\s*['\"]?(center|left|right|justify)\b", lower)
            alignment = css[-1] if css else attribute[1] if attribute else None
            if alignment == "center":
                next_scope += 1
                inherited.add(next_scope)
            elif alignment is not None:
                inherited.clear()
            own_scroll = bool(
                re.search(r"overflow-x\s*:\s*auto\b", lower)
                and re.search(r"max-width\s*:\s*100%\b", lower)
            )
            stack.append((name, inherited, own_scroll or (stack[-1][2] if stack else False)))
        if line[cursor:].strip():
            content_scopes.append(set(stack[-1][1]) if stack else set())
            content_scroll.append(stack[-1][2] if stack else False)
        common = set.intersection(*content_scopes) if content_scopes else set()
        scopes[number] = common
        if common:
            centered.add(number)
        if content_scroll and all(content_scroll):
            scrolling.add(number)
    return centered, scrolling, scopes


def _markdown_tables(text: str, code_lines: set[int]) -> list[tuple[int, int, list[str]]]:
    """Locate simple Markdown tables by their delimiter row."""

    lines = text.splitlines()
    results: list[tuple[int, int, list[str]]] = []
    seen: set[tuple[int, int]] = set()
    delimiter = re.compile(r"\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)*\|?\s*")
    for index, line in enumerate(lines):
        number = index + 1
        if number in code_lines or index == 0 or "|" not in line or not delimiter.fullmatch(line):
            continue
        start = index - 1
        end = index + 1
        while end < len(lines) and end + 1 not in code_lines and lines[end].strip() and "|" in lines[end] and not lines[end].lstrip().startswith("<"):
            end += 1
        key = (start + 1, end)
        if key not in seen:
            seen.add(key)
            results.append((start + 1, end, lines[start:end]))
    return results


def _html_tables(text: str, code_lines: set[int]) -> list[tuple[int, int, str]]:
    """Locate HTML table ranges without treating fenced examples as output."""

    lines = text.splitlines()
    results: list[tuple[int, int, str]] = []
    index = 0
    while index < len(lines):
        number = index + 1
        if number in code_lines or not re.search(r"<table\b", lines[index], re.IGNORECASE):
            index += 1
            continue
        end = index
        while end < len(lines) and not re.search(r"</table\s*>", lines[end], re.IGNORECASE):
            end += 1
        if end >= len(lines):
            end = index
        results.append((number, end + 1, "\n".join(lines[index:end + 1])))
        index = end + 1
    return results


def _next_caption_line(lines: list[str], start: int, label: str) -> int | None:
    """Find an immediately associated Chinese image or table caption."""

    for index in range(start, min(len(lines), start + 6)):
        stripped = lines[index].strip()
        if not stripped or re.fullmatch(r"</?(?:div|details|section|figure)\b[^>]*>", stripped, re.IGNORECASE):
            continue
        plain = re.sub(r"^<p>|</p>$", "", stripped, flags=re.IGNORECASE).strip()
        plain = plain.strip("*_ ")
        return index + 1 if re.match(label + r"(?:\s|\d|[一二三四五六七八九十])", plain) else None
    return None


def visual_layout_findings(text: str) -> list[dict[str, Any]]:
    """Check observable visual containment without claiming rendered pixels."""

    lines = text.splitlines()
    code_lines = {
        number
        for start, _, body in _fenced_blocks(text)
        for number in range(start, start + len(body) + 2)
    }
    centered, scrolling, scopes = _html_layout_lines(text)
    findings: list[dict[str, Any]] = []

    for number, line in enumerate(lines, 1):
        if number in code_lines or line.lstrip().startswith(">"):
            continue
        if re.search(r"!\[[^\]\n]*\]\((?:[^()\n]|\([^()\n]*\))*\)|!\[[^\]\n]*\]\[[^\]\n]*\]|<img\b", line, re.IGNORECASE):
            if number not in centered:
                findings.append(_finding(
                    "FORMAT_IMAGE_NOT_CENTERED", f"LINE-{number:04d}", line,
                    "图片没有位于居中容器中", "sentence",
                ))
            caption_line = _next_caption_line(lines, number, "图")
            if caption_line is not None and not (scopes.get(number, set()) & scopes.get(caption_line, set())):
                findings.append(_finding(
                    "FORMAT_IMAGE_CAPTION_NOT_CENTERED", f"LINE-{caption_line:04d}", lines[caption_line - 1],
                    "图片题注没有与对应图片位于同一个居中容器中", "sentence",
                ))

    for start, end, table_lines in _markdown_tables(text, code_lines):
        if start not in centered or end not in centered:
            findings.append(_finding(
                "FORMAT_TABLE_NOT_CENTERED", f"LINE-{start:04d}", table_lines[0],
                "表格没有位于页面居中容器中", "sentence",
            ))
        caption_line = _next_caption_line(lines, end, "表")
        if caption_line is not None and not (scopes.get(start, set()) & scopes.get(caption_line, set())):
            findings.append(_finding(
                "FORMAT_TABLE_CAPTION_NOT_CENTERED", f"LINE-{caption_line:04d}", lines[caption_line - 1],
                "表题没有与对应表格位于同一个居中容器中", "sentence",
            ))
        delimiter_cells = [cell.strip() for cell in table_lines[1].strip().strip("|").split("|")]
        for row_offset, row in enumerate(table_lines[2:], 2):
            cells = row.strip().strip("|").split("|")
            for column, cell in enumerate(cells):
                if "![" in cell and column < len(delimiter_cells) and not re.fullmatch(r":-{3,}:", delimiter_cells[column]):
                    findings.append(_finding(
                        "FORMAT_TABLE_IMAGE_CELL_NOT_CENTERED", f"LINE-{start + row_offset:04d}", cell.strip(),
                        "多图表格中的图片单元格没有使用居中列对齐", "token",
                    ))
        if any(len(line) > 120 for line in table_lines) and not all(number in scrolling for number in range(start, end + 1)):
            findings.append(_finding(
                "FORMAT_WIDE_TABLE_OVERFLOW_REVIEW", f"LINE-{start:04d}", table_lines[0],
                "表格行较宽且没有可观察到的内部横向滚动容器，需核对目标媒介是否会造成页面整体溢出", "sentence", candidate=True,
            ))

    for start, end, table in _html_tables(text, code_lines):
        if start not in centered or end not in centered:
            findings.append(_finding(
                "FORMAT_TABLE_NOT_CENTERED", f"LINE-{start:04d}", lines[start - 1],
                "HTML 表格没有位于页面居中容器中", "sentence",
            ))
        caption_line = _next_caption_line(lines, end, "表")
        if caption_line is not None and not (scopes.get(start, set()) & scopes.get(caption_line, set())):
            findings.append(_finding(
                "FORMAT_TABLE_CAPTION_NOT_CENTERED", f"LINE-{caption_line:04d}", lines[caption_line - 1],
                "HTML 表题没有与对应表格位于同一个居中容器中", "sentence",
            ))
        for match in re.finditer(r"<t[dh]\b([^>]*)>(.*?)</t[dh]\s*>", table, re.IGNORECASE | re.DOTALL):
            attributes, cell_body = match.groups()
            if not re.search(r"<img\b", cell_body, re.IGNORECASE):
                continue
            cell_centered = bool(
                re.search(r"\balign\s*=\s*['\"]?center\b", attributes, re.IGNORECASE)
                or re.search(r"text-align\s*:\s*center\b", attributes, re.IGNORECASE)
                or re.search(
                    r"<(?:div|p)\b[^>]*(?:\balign\s*=\s*['\"]?center\b|text-align\s*:\s*center\b)",
                    cell_body, re.IGNORECASE,
                )
            )
            if not cell_centered:
                cell_line = start + table[:match.start()].count("\n")
                findings.append(_finding(
                    "FORMAT_TABLE_IMAGE_CELL_NOT_CENTERED", f"LINE-{cell_line:04d}", lines[cell_line - 1],
                    "HTML 多图表格中的图片单元格没有单独居中", "sentence",
                ))
        if any(len(line) > 120 for line in table.splitlines()) and not all(number in scrolling for number in range(start, end + 1)):
            findings.append(_finding(
                "FORMAT_WIDE_TABLE_OVERFLOW_REVIEW", f"LINE-{start:04d}", lines[start - 1],
                "HTML 表格可能过宽且没有可观察到的内部横向滚动容器", "sentence", candidate=True,
            ))

    return findings


def deterministic_format_findings(text: str, *, host_nested_blank: bool = False) -> list[dict[str, Any]]:
    """Return format defects and REVIEW_REQUIRED candidates, never semantic proof."""

    findings: list[dict[str, Any]] = []
    authored = _authored_lines(text)
    for number, line in authored:
        location = f"LINE-{number:04d}"
        prose = _without_inline_code(line)
        if "。" in prose:
            columns = [index + 1 for index, char in enumerate(prose) if char == "。"]
            finding = _finding(
                "FORMAT_NO_CHINESE_FULL_STOP", location, line,
                "普通生成内容含中文句号；整行仅用于唯一定位，只修改命中位置的标点，句中分隔须按原语义判断",
            )
            finding.update({
                "expected_occurrences": 1,
                "matched_columns_1based": columns,
                "matched_occurrences": len(columns),
            })
            findings.append(finding)
        if line.rstrip().endswith("；") and prose.rstrip().endswith("；"):
            findings.append(_finding("FORMAT_NO_TRAILING_SEMICOLON", location, line, "生成内容以中文分号结尾"))
        if re.fullmatch(r"\s*(操作|术语|证据边界|验证边界|内部边界)\s*[：:]\s*", line):
            findings.append(_finding("FORMAT_COLON_PSEUDO_HEADING", location, line, "独立标签可能承担分区作用，需结合后文确认", "sentence", candidate=True))
        if re.search(r"(?:证据边界|验证边界|内部边界)\s*[：:]", prose):
            findings.append(_finding("FORMAT_INTERNAL_BOUNDARY_LABEL", location, line, "内部边界字段泄漏到用户正文", "phrase"))
        if re.match(r"^\s{0,3}#{1,6}\s+", prose) and re.search(r"证据边界|验证边界|内部边界", prose):
            findings.append(_finding(
                "FORMAT_INTERNAL_BOUNDARY_LABEL", location, line,
                "Markdown 标题直接暴露了内部边界字段", "phrase",
            ))
        for match in re.finditer(r"(?<=[\u3400-\u9fff])（([^（）\n]{1,160})）", prose):
            issue = parenthetical_term_payload_issue(match.group(1))
            if issue:
                findings.append(_finding(
                    "FORMAT_PARENTHETICAL_TERM_CONTENT", location, match.group(0),
                    f"{issue}；中文术语后的全角括号只能保留经适用来源核实的英文名称本体，名称真实性仍需语义核查",
                    "phrase",
                ))
        for match in re.finditer(r"（([a-z][A-Za-z0-9 -]*)）", prose):
            findings.append(_finding(
                "FORMAT_PARENTHETICAL_ENGLISH_CASE", location, match.group(1),
                "括号英文以小写开头，须先核对官方名称或可靠学术来源中的名称本体，再判断适用的大小写，不能据大小写推断名称真实性", candidate=True,
            ))
    blank_numbers = {number for number, line in authored if not line.strip()}
    if any(number - 1 in blank_numbers for number in blank_numbers):
        findings.append(_finding("FORMAT_EXCESSIVE_BLANK_LINES", "DOCUMENT", "\n\n\n", "正文出现连续两个以上空行"))
    findings.extend(_list_spacing_findings(text, host_nested_blank=host_nested_blank))
    findings.extend(_block_spacing_findings(text, host_nested_blank=host_nested_blank))
    findings.extend(_code_findings(text))
    findings.extend(visual_layout_findings(text))
    findings.extend(_heading_structure_findings(text))
    findings.extend(_formula_review_candidates(text))
    findings.extend(_semantic_review_candidates(text))
    unique: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for finding in findings:
        key = (str(finding["rule_id"]), str(finding["location"]), str(finding["old_text"]))
        if key not in seen:
            seen.add(key)
            unique.append(finding)
    return unique
