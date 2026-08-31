"""Validate the round-four lifecycle, immutable first attempt, and 13 review candidates."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

import jsonschema
from referencing import Registry, Resource


ROOT = Path(__file__).resolve().parents[1]
FORWARD = ROOT / "evals" / "forward" / "round-1"
LIFECYCLE = FORWARD / "lifecycle"


class ValidationFailure(RuntimeError):
    """Represent one deterministic lifecycle, provenance, or snapshot failure."""


def require(condition: bool, message: str) -> None:
    """Stop at the first confirmed integrity defect."""

    if not condition:
        raise ValidationFailure(message)


def digest(text: str) -> str:
    """Return the exact UTF-8 digest used by review records."""

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def validator(schema_name: str, references: list[str]) -> jsonschema.Draft202012Validator:
    """Build one validator with its local schema references."""

    schema = json.loads((ROOT / "contracts" / schema_name).read_text(encoding="utf-8"))
    registry = Registry()
    for name in references:
        reference = json.loads((ROOT / "contracts" / name).read_text(encoding="utf-8"))
        registry = registry.with_resource(reference["$id"], Resource.from_contents(reference))
    return jsonschema.Draft202012Validator(schema, registry=registry, format_checker=jsonschema.FormatChecker())


def load_jsonl(path: Path) -> dict[str, dict[str, Any]]:
    """Load one identifier-indexed JSONL file."""

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return {row["case_id"]: row for row in rows}


def visible_generated_text(text: str) -> str:
    """Remove verbatim code and blockquote evidence before applying the Lucas punctuation profile."""

    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith(">"))


def validate_anchor_records(failures: list[str]) -> dict[str, int]:
    """Validate 25 anchor records and protect every accepted snapshot."""

    lifecycle_validator = validator("evaluation-case.schema.json", ["candidate-case.schema.json"])
    paths = (
        sorted((ROOT / "evals" / "gold").glob("GOLD-??.json"))
        + sorted((ROOT / "evals" / "rejected").glob("REJECTED-??*.json"))
        + sorted((ROOT / "evals" / "candidate").glob("CANDIDATE-??-R5.json"))
    )
    counts = {"gold": 0, "rejected": 0, "candidate": 0}
    for path in paths:
        case = json.loads(path.read_text(encoding="utf-8"))
        errors = list(lifecycle_validator.iter_errors(case))
        if errors:
            failures.append(f"{path.name}: {errors[0].message}")
            continue
        status = case["identity"]["status"]
        counts[status] += 1
        answer_hash = digest(case["artifact"]["answer"])
        if status == "gold" and answer_hash != case["artifact"]["approved_snapshot_sha256"]:
            failures.append(f"{path.name}: accepted answer differs from approved snapshot")
        if "。" in visible_generated_text(case["artifact"]["answer"]):
            failures.append(f"{path.name}: generated prose contains Chinese full stop")
    require(counts == {"gold": 11, "rejected": 13, "candidate": 1}, f"anchor lifecycle counts differ: {counts}")
    return counts


def validate_c03_r5(failures: list[str]) -> None:
    """Validate source coverage and registered npm constraints without matching one expected answer."""

    path = ROOT / "evals" / "candidate" / "CANDIDATE-03-R5.json"
    candidate = json.loads(path.read_text(encoding="utf-8"))
    answer = candidate["artifact"]["answer"]
    if not re.search(r"(?<![A-Za-z])npm(?![A-Za-z])", answer):
        failures.append("CANDIDATE-03-R5: official npm form is absent")
    if re.search(r"Node(?:\.js)? Package Manager|包管理器（Package Manager）", answer, re.IGNORECASE):
        failures.append("CANDIDATE-03-R5: npm is presented as an acronym expansion or misleading parenthetical category")
    if "npm" not in answer or "Node.js" not in answer or not all(item in answer for item in ("客户端", "软件包仓库")):
        failures.append("CANDIDATE-03-R5: npm definition does not cover the registered client and registry roles")
    source_ids = {atom["id"] for atom in candidate["semantics"]["source_atoms"]}
    background_ids = {atom["id"] for atom in candidate["semantics"]["background_atoms"]}
    support_ids = {item for mapping in candidate["artifact"]["support_map"] for item in mapping["supports"]}
    if not source_ids <= support_ids:
        failures.append("CANDIDATE-03-R5: source-atom coverage is incomplete")
    if not background_ids <= support_ids:
        failures.append("CANDIDATE-03-R5: background-atom coverage is incomplete")
    references = {item["id"] for item in candidate["source"]["references"]}
    if any(atom["source_reference"] not in references for atom in candidate["semantics"]["background_atoms"]):
        failures.append("CANDIDATE-03-R5: one background atom has no registered source")


def validate_forward_records(failures: list[str]) -> dict[str, int]:
    """Validate 32 forward lifecycle records and prove that first-attempt evidence never changed."""

    lifecycle_validator = validator("forward-lifecycle.schema.json", ["forward-request.schema.json"])
    originals = load_jsonl(FORWARD / "candidates.jsonl")
    requests = load_jsonl(FORWARD / "requests.jsonl")
    paths = sorted(LIFECYCLE.rglob("*.json"))
    counts = {"gold": 0, "rejected": 0, "candidate": 0}
    for path in paths:
        case = json.loads(path.read_text(encoding="utf-8"))
        errors = list(lifecycle_validator.iter_errors(case))
        if errors:
            failures.append(f"{path.name}: {errors[0].message}")
            continue
        origin = case["identity"]["origin_case_id"]
        original = originals[origin]
        status = case["identity"]["status"]
        counts[status] += 1
        if case["source"]["original_answer_sha256"] != original["answer_sha256"]:
            failures.append(f"{path.name}: original answer digest changed")
        if case["source"]["original_request_sha256"] != original["request_sha256"]:
            failures.append(f"{path.name}: original request digest changed")
        if case["task"] != requests[origin]:
            failures.append(f"{path.name}: task request differs from the immutable first-round request")
        if set(case["source"]["source_units"]) != set(case["source"]["support_map"]):
            failures.append(f"{path.name}: source-unit coverage is incomplete")
        reference_ids = {item["id"] for item in case["task"]["references"]} | {
            item["id"] for item in case["source"]["revision_references"]
        }
        unresolved = [
            item["source_reference"] for item in case["source"]["background_claims"]
            if item["source_reference"] not in reference_ids
        ]
        if unresolved:
            failures.append(f"{path.name}: unresolved background references {sorted(set(unresolved))}")
        answer = case["artifact"]["answer"]
        if digest(answer) != case["artifact"]["answer_sha256"]:
            failures.append(f"{path.name}: answer digest mismatch")
        if status in {"gold", "rejected"} and answer != original["answer"]:
            failures.append(f"{path.name}: reviewed first-attempt answer was rewritten")
        if status == "gold" and case["artifact"]["approved_snapshot_sha256"] != original["answer_sha256"]:
            failures.append(f"{path.name}: Gold snapshot does not bind the accepted first attempt")
        if status == "candidate" and "。" in visible_generated_text(answer):
            failures.append(f"{path.name}: revised generated prose contains Chinese full stop")
    require(counts == {"gold": 8, "rejected": 12, "candidate": 12}, f"forward lifecycle counts differ: {counts}")
    return counts


def build_report(failures: list[str], checked: int) -> dict[str, Any]:
    """Separate artifact integrity from human acceptance and next-round permission."""

    report = {
        "artifact_integrity": {"status": "PASS" if not failures else "FAIL", "checked": checked, "failures": failures},
        "human_acceptance": {"accepted": 8, "total": 20, "rate": 0.4, "threshold_met": False},
        "next_round_allowed": False,
        "reason": "57 个生命周期记录和原始前向证据保持一致，但第一轮只有 8/20 获得用户原样接受" if not failures else "生命周期、摘要、来源或修订候选存在确定性错误",
        "impact": "13 个修订候选可以进入人工审核，第二轮前向测试仍被阻止" if not failures else "当前候选包不能进入人工审核",
        "next": "审核 CANDIDATE-03-R5 和 12 个前向 R2 候选" if not failures else "修复失败记录并重新运行完整检查",
    }
    jsonschema.Draft202012Validator(
        json.loads((ROOT / "contracts" / "forward-round-report.schema.json").read_text(encoding="utf-8"))
    ).validate(report)
    return report


def main() -> int:
    """Run lifecycle, immutable-evidence, C03, and report-interface checks."""

    failures: list[str] = []
    try:
        anchor = validate_anchor_records(failures)
        validate_c03_r5(failures)
        forward = validate_forward_records(failures)
        require({key: anchor[key] + forward[key] for key in anchor} == {"gold": 19, "rejected": 25, "candidate": 13}, "combined lifecycle counts differ")
    except (ValidationFailure, json.JSONDecodeError, jsonschema.ValidationError) as error:
        failures.append(str(error))
    report = build_report(failures, 57)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["artifact_integrity"]["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
