"""Validate the round-three lifecycle state and the single C03-R4 anchor candidate."""

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


class ValidationFailure(RuntimeError):
    """Represent one deterministic lifecycle or anchor-candidate failure."""


def require(condition: bool, message: str) -> None:
    """Stop at the first deterministic defect with an auditable message."""

    if not condition:
        raise ValidationFailure(message)


def lifecycle_validator() -> jsonschema.Draft202012Validator:
    """Build the lifecycle validator with its local schema reference."""

    schema = json.loads((ROOT / "contracts" / "evaluation-case.schema.json").read_text(encoding="utf-8"))
    candidate_schema = json.loads((ROOT / "contracts" / "candidate-case.schema.json").read_text(encoding="utf-8"))
    registry = Registry().with_resource(candidate_schema["$id"], Resource.from_contents(candidate_schema))
    return jsonschema.Draft202012Validator(schema, registry=registry, format_checker=jsonschema.FormatChecker())


def load_records() -> list[tuple[Path, dict[str, Any]]]:
    """Load the exact 11 Gold, 12 Rejected, and one Candidate records."""

    paths = (
        sorted((ROOT / "evals" / "gold").glob("GOLD-??.json"))
        + sorted((ROOT / "evals" / "rejected").glob("REJECTED-??*.json"))
        + sorted((ROOT / "evals" / "candidate").glob("CANDIDATE-??-R4.json"))
    )
    require(len(paths) == 24, f"expected 24 lifecycle records, found {len(paths)}")
    return [(path, json.loads(path.read_text(encoding="utf-8"))) for path in paths]


def support_coverage(case: dict[str, Any]) -> tuple[int, int, int, int]:
    """Return covered and total source/background atom counts."""

    source_ids = {atom["id"] for atom in case["semantics"]["source_atoms"]}
    background_ids = {atom["id"] for atom in case["semantics"]["background_atoms"]}
    support_ids = {item for mapping in case["artifact"]["support_map"] for item in mapping.get("supports", [])}
    return len(source_ids & support_ids), len(source_ids), len(background_ids & support_ids), len(background_ids)


def validate_gold_snapshots(records: list[tuple[Path, dict[str, Any]]]) -> None:
    """Bind every accepted decision to the exact reviewed answer text."""

    review = json.loads((ROOT / "evals" / "reviews" / "vnext-1.1-round-2.json").read_text(encoding="utf-8"))
    reviewed_hashes = {
        item["origin_case_id"]: item["approved_snapshot_sha256"]
        for item in review["review_round"]["decisions"]
        if item["decision"] == "accepted"
    }
    for path, case in records:
        if case["identity"]["status"] != "gold":
            continue
        actual = hashlib.sha256(case["artifact"]["answer"].encode("utf-8")).hexdigest()
        require(actual == case["artifact"]["approved_snapshot_sha256"], f"{path.name}: approved snapshot digest mismatch")
        origin = case["identity"]["origin_case_id"]
        if origin in reviewed_hashes:
            require(actual == reviewed_hashes[origin], f"{path.name}: answer differs from round-two reviewed snapshot")


def validate_round_one_rejections() -> int:
    """Keep every first-round failure detectable by its case-specific lock."""

    expectations = json.loads(
        (ROOT / "evals" / "deterministic" / "round1-rejected-expectations.json").read_text(encoding="utf-8")
    )["cases"]
    detected = 0
    for number, expectation in sorted(expectations.items()):
        rejected = json.loads((ROOT / "evals" / "rejected" / f"REJECTED-{number}.json").read_text(encoding="utf-8"))
        answer = rejected["artifact"]["answer"]
        findings = [item for item in expectation["required_all"] if item not in answer]
        findings.extend(item for item in expectation["forbidden_all"] if item in answer)
        if findings:
            detected += 1
    require(detected == 10, f"round-one rejected regression detected {detected}/10")
    return detected


def validate_c03_r4() -> dict[str, int]:
    """Check only facts and structures that can be determined without style guessing."""

    candidate = json.loads((ROOT / "evals" / "candidate" / "CANDIDATE-03-R4.json").read_text(encoding="utf-8"))
    rejected_r2 = json.loads((ROOT / "evals" / "rejected" / "REJECTED-03-R2.json").read_text(encoding="utf-8"))
    rejected_r3 = json.loads((ROOT / "evals" / "rejected" / "REJECTED-03-R3.json").read_text(encoding="utf-8"))
    review = json.loads((ROOT / "evals" / "reviews" / "vnext-1.1-c03-r3.json").read_text(encoding="utf-8"))
    answer = candidate["artifact"]["answer"]
    required = [
        "npm run check # npm 调用项目已登记的 check 脚本；系统在命令结束后显示检查结果",
        "npm 是 Node.js 生态使用的包管理器（Package Manager）、命令行工具和软件包仓库",
        "CI 持续集成（Continuous Integration）",
        "退出码 `2`",
        "没有证明当前项目已经启用 CI",
    ]
    forbidden = ["（package manager）", "（PACKAGE MANAGER）", "NPM（Node Package Manager）", "npm（Node Package Manager）", "Node Package Manager，npm"]
    require(all(item in answer for item in required), "C03-R4 is missing a reviewed subject, npm, CI, or boundary requirement")
    require(not any(item in answer for item in forbidden), "C03-R4 contains a casing defect or invented npm acronym expansion")
    visible = re.sub(r"```.*?```", "", answer, flags=re.DOTALL)
    require("。" not in visible, "C03-R4 generated prose contains a Chinese full stop")
    require(re.search(r"\n[ \t]*\n[ \t]*\n", answer) is None, "C03-R4 contains two consecutive blank lines")
    require(candidate["artifact"]["self_claims"] == [], "C03-R4 contains an ungrounded self claim")
    require(candidate["artifact"]["original_case_sha256"] == rejected_r2["artifact"]["original_case_sha256"], "C03-R4 no longer points to the reviewed original candidate")
    require(candidate["artifact"]["original_case_sha256"] == rejected_r3["artifact"]["original_case_sha256"], "C03-R4 and rejected R3 no longer share the original anchor")
    reviewed_r3 = review["review_round"]["decisions"][0]
    actual_r3_hash = hashlib.sha256(rejected_r3["artifact"]["answer"].encode("utf-8")).hexdigest()
    require(actual_r3_hash == reviewed_r3["reviewed_snapshot_sha256"], "REJECTED-03-R3 differs from the explicit user-review snapshot")
    references = {item["id"] for item in candidate["source"]["references"]}
    require({"REF-NPM-OFFICIAL", "REF-ROUND-3-CASE"} <= references, "C03-R4 lacks the official npm or explicit casing reference")
    require(all(atom["source_reference"] in references for atom in candidate["semantics"]["background_atoms"]), "C03-R4 contains an unresolved background reference")
    source_covered, source_total, background_covered, background_total = support_coverage(candidate)
    require(source_covered == source_total, f"C03-R4 source coverage {source_covered}/{source_total}")
    require(background_covered == background_total, f"C03-R4 background coverage {background_covered}/{background_total}")
    return {"source_covered": source_covered, "source_total": source_total, "background_covered": background_covered, "background_total": background_total}


def validate_all() -> dict[str, Any]:
    """Run schema, snapshot, rejection, provenance, and C03-R4 checks."""

    records = load_records()
    validator = lifecycle_validator()
    counts = {"gold": 0, "rejected": 0, "candidate": 0}
    for path, case in records:
        errors = sorted(validator.iter_errors(case), key=lambda error: list(error.path))
        require(not errors, f"{path.name}: {errors[0].message if errors else ''}")
        counts[case["identity"]["status"]] += 1
    require(counts == {"gold": 11, "rejected": 12, "candidate": 1}, f"lifecycle counts mismatch: {counts}")
    validate_gold_snapshots(records)
    rejected_detected = validate_round_one_rejections()
    c03 = validate_c03_r4()
    return {
        "lifecycle": counts,
        "lifecycle_total": len(records),
        "approved_snapshot_mismatches": 0,
        "round_one_rejected_regression": f"{rejected_detected}/10",
        "c03_r4_hard_rule_pass": "1/1",
        "c03_r4_source_coverage": f"{c03['source_covered']}/{c03['source_total']}",
        "c03_r4_background_coverage": f"{c03['background_covered']}/{c03['background_total']}",
        "hard_errors": 0,
        "ungrounded_additions": 0,
    }


def main() -> int:
    """Print a causal validation report and return a process status."""

    try:
        results = validate_all()
    except (ValidationFailure, jsonschema.ValidationError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "FAIL", "reason": str(error), "impact": "第三轮状态或 C03-R4 不能进入人工审核", "next": "修复指定记录后重新验证"}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({"status": "PASS", "results": results, "reason": "24 个生命周期记录有效，Gold 快照未变化，C03-R4 的确定性要求和来源覆盖完整", "impact": "C03-R4 可以进入人工审核，但仍不是 Gold", "next": "等待用户对 C03-R4 作出明确决定"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
