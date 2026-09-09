"""Validate the generated top-level format case inventory."""

from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RULES_PATH = ROOT / "references" / "format-rules.md"
CASES_PATH = ROOT / "evals" / "candidate" / "format-layer" / "format-cases.json"


def unprotected_text(text: str) -> str:
    """Remove code fences and quote lines before checking generated prose."""
    text = re.sub(r"```[\s\S]*?```", "", text)
    return "\n".join(line for line in text.splitlines() if not line.startswith(">"))


def main() -> None:
    rule_ids = re.findall(
        r"(?m)^- `(FMT-\d{3})` ", RULES_PATH.read_text(encoding="utf-8"),
    )
    rules = set(rule_ids)
    payload = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    items = payload.get("cases", [])
    ids = [item.get("id") for item in items]
    covered = {rule for item in items for rule in item.get("rules", [])}
    errors: list[str] = []
    if len(items) != 20:
        errors.append(f"expected 20 cases, got {len(items)}")
    if len(rule_ids) != len(rules):
        errors.append("format rule ids are not unique")
    if rules != {f"FMT-{number:03d}" for number in range(1, 111)}:
        errors.append("format rules must contain the continuous FMT-001 through FMT-110 range")
    if len(set(ids)) != len(ids):
        errors.append("case ids are not unique")
    if covered - rules:
        errors.append(f"unknown rules: {sorted(covered - rules)}")
    if rules - covered:
        errors.append(f"uncovered rules: {sorted(rules - covered)}")
    for item in items:
        for key in ("id", "title", "request", "input", "output", "rules"):
            if not item.get(key):
                errors.append(f"{item.get('id', '<unknown>')} missing {key}")
        output = str(item.get("output", ""))
        prose = unprotected_text(output)
        if "。" in prose:
            errors.append(f"{item.get('id', '<unknown>')} has an unprotected Chinese full stop")
        if any(line.rstrip().endswith(("。", "；")) for line in prose.splitlines()):
            errors.append(f"{item.get('id', '<unknown>')} has a forbidden terminal Chinese mark")
        if re.search(r"(?m)^\s*(操作|术语|证据边界)：", prose):
            errors.append(f"{item.get('id', '<unknown>')} has a colon pseudo-heading")
    if errors:
        raise SystemExit("\n".join(errors))
    print(f"format fragments structurally valid: {len(items)}; registered rules: {len(covered)}/{len(rules)}; behavioral compliance not evaluated")


if __name__ == "__main__":
    main()
