"""Deterministically align existing same-line comments inside one code block."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class CommentUnit:
    """One code line with a comment marker outside quoted strings."""

    line_number: int
    code: str
    comment: str
    marker_index: int


def display_width(text: str) -> int:
    """Measure display columns with four-column tab stops."""

    column = 0
    for character in text:
        column = column + (4 - column % 4) if character == "\t" else column + 1
    return column


def marker_index(line: str, marker: str) -> int:
    """Find the first comment marker outside simple single or double quoted strings."""

    quote: str | None = None
    escaped = False
    index = 0
    while index <= len(line) - len(marker):
        character = line[index]
        if escaped:
            escaped = False
            index += 1
            continue
        if character == "\\" and quote is not None:
            escaped = True
            index += 1
            continue
        if character in {"'", '"'}:
            if quote == character:
                quote = None
            elif quote is None:
                quote = character
            index += 1
            continue
        if quote is None and line.startswith(marker, index):
            return index
        index += 1
    return -1


def comment_units(text: str, marker: str) -> list[CommentUnit]:
    """Return lines that contain code followed by a legal same-line comment marker."""

    units: list[CommentUnit] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        index = marker_index(line, marker)
        if index < 0 or not line[:index].strip():
            continue
        units.append(CommentUnit(line_number, line[:index].rstrip(" \t"), line[index:].lstrip(), index))
    return units


def align_text(text: str, marker: str = "#") -> str:
    """Place every existing same-line marker at longest code width plus two."""

    lines = text.splitlines()
    units = comment_units(text, marker)
    if not units:
        raise ValueError("no same-line comments found")
    longest = max(display_width(unit.code) for unit in units)
    for unit in units:
        padding = longest - display_width(unit.code) + 1
        lines[unit.line_number - 1] = unit.code + " " * padding + unit.comment
    suffix = "\n" if text.endswith(("\n", "\r")) else ""
    return "\n".join(lines) + suffix


def check_alignment(text: str, marker: str = "#") -> dict[str, object]:
    """Report exact marker columns without changing the supplied block."""

    units = comment_units(text, marker)
    if not units:
        return {"status": "FAIL", "target_column": None, "units": [], "failures": ["no same-line comments found"]}
    target = max(display_width(unit.code) for unit in units) + 2
    rows = []
    failures = []
    lines = text.splitlines()
    for unit in units:
        actual = display_width(lines[unit.line_number - 1][:unit.marker_index]) + 1
        rows.append({"line": unit.line_number, "code_width": display_width(unit.code), "comment_column": actual})
        if actual != target:
            failures.append(f"line {unit.line_number}: comment column {actual}, target {target}")
    return {"status": "PASS" if not failures else "FAIL", "target_column": target, "units": rows, "failures": failures}


def main() -> int:
    """Align stdin or verify it with a machine-readable result."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--marker", choices=["#", "//", "--"], default="#")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    source = sys.stdin.read()
    if args.check:
        report = check_alignment(source, args.marker)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["status"] == "PASS" else 1
    try:
        sys.stdout.write(align_text(source, args.marker))
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
