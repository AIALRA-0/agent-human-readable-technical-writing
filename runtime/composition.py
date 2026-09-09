"""Render explicit writing structure without guessing or rewriting its meaning."""

from __future__ import annotations

import re
from typing import Any


# Generated scalar fields cannot smuggle a second Markdown block into one item.
BLOCK_PREFIX = re.compile(r"^(?:#{1,6}(?:\s|$)|[-+*]\s|\d+[.)]\s|>|`{3}|~{3}|\||\$\$|(?:[-*_]\s*){3,}$)")


def _object(value: Any, required: set[str], optional: set[str], location: str) -> dict:
    """Reject typos before rendering instead of silently dropping supplied data."""
    if not isinstance(value, dict):
        raise ValueError(f"{location}: expected an object")
    if required - value.keys() or value.keys() - required - optional:
        raise ValueError(f"{location}: missing or unknown fields")
    return value


def _text(value: Any, location: str, *, multiline: bool = False) -> str:
    """Normalize authored field boundaries only; literal source bypasses this."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{location}: expected nonempty text")
    if multiline:
        return value
    if any(char in value for char in "\n\r\v\f\x85\u2028\u2029"):
        raise ValueError(f"{location}: use separate items, not embedded line breaks")
    result = value.strip().rstrip("。；")
    if not result or BLOCK_PREFIX.match(result):
        raise ValueError(f"{location}: expected inline text, not a block marker")
    return result


def _boolean(value: Any, location: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{location}: expected a boolean")
    return value


def _array(value: Any, location: str) -> list:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{location}: expected a nonempty array")
    return value


def _join(parts: list[str]) -> str:
    """Separate blocks while retaining all existing source characters."""
    result = ""
    for part in parts:
        if result:
            result += "\n" * max(0, 2 - (len(result) - len(result.rstrip("\n"))))
        result += part
    return result


def _fence(body: str, language: Any) -> str:
    """Choose a fence longer than any source run; never execute the body."""
    if not isinstance(language, str) or not re.fullmatch(r"[A-Za-z0-9_+.#-]*", language):
        raise ValueError("code.language: invalid language label")
    longest = max((len(match.group()) for match in re.finditer(r"`+", body)), default=0)
    fence = "`" * max(3, longest + 1)
    ending = "" if body.endswith("\n") else "\n"
    return f"{fence}{language}\n{body}{ending}{fence}"


def render_document(document: Any, *, sources: dict[str, str] | None = None,
                    host_nested_blank: bool = False) -> str:
    """Compose one draft; structure validity is not factual or semantic approval."""
    doc = _object(document, {"blocks"}, {"title"}, "document")
    _boolean(host_nested_blank, "host_nested_blank")
    originals = {} if sources is None else sources
    if not isinstance(originals, dict) or any(
        not isinstance(key, str) or not key or not isinstance(value, str) or not value
        for key, value in originals.items()
    ):
        raise ValueError("sources: expected nonempty identifiers mapped to literal text")
    used: set[str] = set()

    def items(values: Any, ordered: bool, indentation: int = 0) -> str:
        """Render each explicit peer independently and preserve child ownership."""
        lines = []
        for number, value in enumerate(_array(values, "list.items"), 1):
            item = _object(value, {"text"}, {"children", "children_ordered"}, "list.item")
            marker = f"{number}." if ordered else "-"
            lines.append(" " * indentation + marker + " " + _text(item["text"], "item.text"))
            child_order = _boolean(item.get("children_ordered", False), "children_ordered")
            if "children" in item:
                if host_nested_blank:
                    lines.append("")
                child_indent = indentation + max(4, len(marker) + 1)
                lines.append(items(item["children"], child_order, child_indent))
            elif "children_ordered" in item:
                raise ValueError("children_ordered requires children")
        return "\n".join(lines)

    def blocks(values: Any, level: int = 2) -> str:
        """Assign heading depth and keep original objects adjacent to explanations."""
        rendered = []
        previous_kind = None
        for block in _array(values, "blocks"):
            if not isinstance(block, dict) or not isinstance(block.get("type"), str):
                raise ValueError("block: missing type")
            kind = block["type"]
            if kind == "section":
                _object(block, {"type", "heading", "blocks"}, set(), "section")
                if level > 6:
                    raise ValueError("section: Markdown headings cannot exceed six levels")
                heading = _text(block["heading"], "section.heading")
                rendered.append(_join(["#" * level + " " + heading, blocks(block["blocks"], level + 1)]))
            elif kind == "paragraph":
                _object(block, {"type", "text"}, set(), "paragraph")
                rendered.append(_text(block["text"], "paragraph.text"))
            elif kind == "list":
                _object(block, {"type", "items"}, {"ordered"}, "list")
                rendered.append(items(block["items"], _boolean(block.get("ordered", False), "ordered")))
            elif kind == "term":
                _object(block, {"type", "zh", "en", "definition"}, {"abbr"}, "term")
                parts = _array(block["definition"], "term.definition")
                if not 3 <= len(parts) <= 5:
                    raise ValueError("term.definition: supply three to five continuous clauses")
                zh = _text(block["zh"], "term.zh")
                en = _text(block["en"], "term.en")
                abbr = _text(block["abbr"], "term.abbr") + " " if "abbr" in block else ""
                definition = "；".join(_text(part, "term.definition") for part in parts)
                term = f"- {abbr}{zh}（{en}）：{definition}"
                if previous_kind == "term":
                    rendered[-1] += "\n" + term
                else:
                    rendered.append(term)
            elif kind == "source":
                _object(block, {"type", "id"}, {"presentation", "language"}, "source")
                identifier = block["id"]
                if not isinstance(identifier, str) or identifier not in originals:
                    raise ValueError("source: unknown identifier")
                body = originals[identifier]
                presentation = block.get("presentation", "raw")
                if presentation != "code" and "language" in block:
                    raise ValueError("source.language requires code presentation")
                if presentation == "raw":
                    rendered.append(body)
                elif presentation == "quote":
                    rendered.append("".join("> " + line for line in body.splitlines(keepends=True)))
                elif presentation == "code":
                    rendered.append(_fence(body, block.get("language", "")))
                else:
                    raise ValueError("source: unknown presentation")
                used.add(identifier)
            elif kind == "code":
                _object(block, {"type", "language", "text"}, set(), "code")
                rendered.append(_fence(_text(block["text"], "code.text", multiline=True), block["language"]))
            elif kind == "image":
                _object(block, {"type", "alt", "url"}, {"caption"}, "image")
                alt = _text(block["alt"], "image.alt")
                url = block["url"]
                if any(char in alt for char in "[]"):
                    raise ValueError("image.alt: square brackets require a literal source object")
                if not isinstance(url, str) or not url.strip() or any(char in url for char in "\r\n<>\x00"):
                    raise ValueError("image.url: invalid address")
                escaped_alt = alt.replace("\\", "\\\\")
                obj = f"![{escaped_alt}](<{url}>)"
                rendered.append(_join([obj, _text(block["caption"], "image.caption")]) if "caption" in block else obj)
            elif kind == "formula":
                _object(block, {"type", "text"}, set(), "formula")
                body = _text(block["text"], "formula.text", multiline=True)
                if "$$" in body:
                    raise ValueError("formula: supply the expression without outer delimiters")
                rendered.append("$$\n" + body + ("" if body.endswith("\n") else "\n") + "$$")
            else:
                raise ValueError("block: unknown type")
            previous_kind = kind
        return _join(rendered)

    parts = []
    if "title" in doc:
        parts.append("# " + _text(doc["title"], "title"))
    parts.append(blocks(doc["blocks"]))
    if used != set(originals):
        raise ValueError("sources: one or more supplied original objects were omitted")
    result = _join(parts)
    return result if result.endswith("\n") else result + "\n"
