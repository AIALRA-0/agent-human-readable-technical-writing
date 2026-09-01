"""Validate broad-coverage forward rounds without scoring their answers."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
FORWARD = ROOT / "evals" / "forward"
RANGES = {"very_short": (1, 80), "short": (81, 250), "medium": (251, 700), "long": (701, 1500), "extended": (1501, 3000)}
SLOTS = [
    ("TRANSFORM", "NONE", ("TEXT",)), ("TRANSLATE", "GLOSS", ("TEXT",)),
    ("COMPRESS", "NONE", ("TEXT",)), ("EXPLAIN", "TEACHING", ("TEXT",)),
    ("GENERATE", "GLOSS", ("TEXT",)), ("FORMAT_ONLY", "NONE", ("TEXT",)),
    ("EXPLAIN", "EXPLANATORY", ("IMAGE", "TEXT")), ("EXPLAIN", "GLOSS", ("TABLE", "TEXT")),
    ("EXPLAIN", "TEACHING", ("CODE", "TEXT")), ("TRANSFORM", "GLOSS", ("TEXT",)),
    ("TRANSFORM", "EXPLANATORY", ("TEXT",)), ("TRANSLATE", "EXPLANATORY", ("TEXT",)),
    ("EXPLAIN", "TEACHING", ("TEXT",)), ("COMPRESS", "GLOSS", ("TEXT",)),
    ("GENERATE", "EXPLANATORY", ("TEXT",)), ("FORMAT_ONLY", "NONE", ("TEXT",)),
    ("EXPLAIN", "EXPLANATORY", ("IMAGE", "TEXT")), ("EXPLAIN", "GLOSS", ("TABLE", "TEXT")),
    ("EXPLAIN", "TEACHING", ("CODE", "TEXT")), ("TRANSFORM", "GLOSS", ("TEXT",)),
]
TASK_DISTRIBUTIONS = {
    2: Counter({"tutorial": 3, "operation": 3, "reference": 3, "explanation": 3, "decision": 3, "status": 2, "audit": 3}),
    3: Counter({"tutorial": 3, "operation": 3, "reference": 3, "explanation": 3, "decision": 2, "status": 3, "audit": 3}),
}
QUOTAS = {"distributed_condition": 4, "conflicting_sources": 2, "noisy_input": 3, "mixed_format": 4, "correction_turn": 2, "numeric_scope": 3, "negation_exception": 3, "urgency_or_emotion": 2}


def stable_digest(value: Any) -> str:
    serialized = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def material_text(source: dict[str, Any]) -> str:
    content = source["content"]
    if source["material_type"] == "image":
        return str(content["alt"])
    if isinstance(content, list):
        return "".join(str(item) for item in content)
    return str(content)


def input_chars(item: dict[str, Any]) -> int:
    return len(item["request"]) + len(material_text(item["source"])) + sum(len(reference["content"]) for reference in item["references"])


def round3_gate() -> bool:
    ledgers = []
    for path in (ROOT / "evals" / "reviews").glob("vnext-1.1-round-*.json"):
        record = json.loads(path.read_text(encoding="utf-8")).get("review_round", {})
        if record.get("forward_round") == 2:
            ledgers.append(record)
    return any(record.get("review_result", {}).get("accepted") == 20 and record.get("review_result", {}).get("rejected") == 0 for record in ledgers)


def main() -> int:
    schema = json.loads((ROOT / "contracts" / "forward-request.schema.json").read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    errors: list[str] = []
    topic_ids: set[str] = set()
    source_digests: set[str] = set()
    term_sets: set[tuple[str, ...]] = set()
    checked = 0
    rounds = []
    for directory in sorted(FORWARD.glob("round-*")):
        match = re.fullmatch(r"round-([2-9][0-9]*)", directory.name)
        if not match or not (directory / "requests.jsonl").exists():
            continue
        round_number = int(match.group(1))
        rounds.append(round_number)
        if round_number == 3 and not round3_gate():
            errors.append("round-3 exists before round-2 received explicit first-draft 20/20 acceptance")
        rows = [json.loads(line) for line in (directory / "requests.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        if len(rows) != 20:
            errors.append(f"round-{round_number}: expected 20 requests, found {len(rows)}")
            continue
        for index, item in enumerate(rows, start=1):
            checked += 1
            schema_errors = list(validator.iter_errors(item))
            if schema_errors:
                errors.append(f"{item.get('case_id', index)}: {schema_errors[0].message}")
            expected_slot = SLOTS[index - 1]
            actual_slot = (item["base_operation"], item["augmentation"], tuple(item["components"]))
            if actual_slot != expected_slot:
                errors.append(f"{item['case_id']}: operation/augmentation/component slot changed")
            actual_chars = input_chars(item)
            if item["input_char_count"] != actual_chars:
                errors.append(f"{item['case_id']}: input_char_count says {item['input_char_count']}, observed {actual_chars}")
            low, high = RANGES[item["length_class"]]
            if not low <= actual_chars <= high:
                errors.append(f"{item['case_id']}: {actual_chars} chars outside {item['length_class']} range")
            observed_digest = stable_digest(item["source"]["content"])
            if item["source"]["sha256"] != observed_digest:
                errors.append(f"{item['case_id']}: source digest mismatch")
            topic = item["topic_id"]
            if topic in topic_ids:
                errors.append(f"{item['case_id']}: duplicate topic_id {topic}")
            topic_ids.add(topic)
            summary_digest = stable_digest({
                "material": item["source"]["content"],
                "references": [reference["content"] for reference in item["references"]],
            })
            if summary_digest in source_digests:
                errors.append(f"{item['case_id']}: duplicate source-summary digest")
            source_digests.add(summary_digest)
            terms = tuple(sorted(term.casefold() for term in item["core_terms"]))
            if terms in term_sets:
                errors.append(f"{item['case_id']}: duplicate core-term set")
            term_sets.add(terms)
        if Counter(item["length_class"] for item in rows) != Counter({name: 4 for name in RANGES}):
            errors.append(f"round-{round_number}: length classes are not 4 each")
        if Counter(item["audience"] for item in rows) != Counter({name: 4 for name in ("zero_prior_knowledge", "operator", "technical_practitioner", "decision_maker", "auditor")}):
            errors.append(f"round-{round_number}: audiences are not 4 each")
        expected_tasks = TASK_DISTRIBUTIONS.get(round_number)
        if expected_tasks and Counter(item["content_task"] for item in rows) != expected_tasks:
            errors.append(f"round-{round_number}: content-task distribution differs")
        tags = Counter(tag for item in rows for tag in item["variation_tags"])
        for tag, minimum in QUOTAS.items():
            if tags[tag] < minimum:
                errors.append(f"round-{round_number}: {tag} appears {tags[tag]} times, expected at least {minimum}")
    result = {"status": "PASS" if not errors else "FAIL", "rounds": rounds, "checked": checked, "errors": errors}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
