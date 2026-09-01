"""Validate every vNext lifecycle record without assigning human acceptance."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import jsonschema
from referencing import Registry, Resource


ROOT = Path(__file__).resolve().parents[1]
FORWARD_ROOT = ROOT / "evals" / "forward"


class ValidationFailure(RuntimeError):
    """Represent one confirmed lifecycle or evidence defect."""


def require(condition: bool, message: str) -> None:
    """Raise one readable validation error."""

    if not condition:
        raise ValidationFailure(message)


def digest(text: str) -> str:
    """Return the repository UTF-8 digest."""

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def display_width(text: str) -> int:
    """Measure visible columns with four-column tab stops."""

    column = 0
    for character in text:
        column = column + (4 - column % 4) if character == "\t" else column + 1
    return column


def read_json(path: Path) -> dict[str, Any]:
    """Read one UTF-8 JSON object."""

    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> dict[str, dict[str, Any]]:
    """Load one case-id indexed JSONL file."""

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return {row["case_id"]: row for row in rows}


def validator(schema_name: str, references: list[str]) -> jsonschema.Draft202012Validator:
    """Build one local JSON Schema validator."""

    schema = read_json(ROOT / "contracts" / schema_name)
    registry = Registry()
    for name in references:
        reference = read_json(ROOT / "contracts" / name)
        registry = registry.with_resource(reference["$id"], Resource.from_contents(reference))
    return jsonschema.Draft202012Validator(schema, registry=registry, format_checker=jsonschema.FormatChecker())


def visible_generated_text(text: str) -> str:
    """Hide verbatim code and quotations before applying generated-prose punctuation rules."""

    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith(">"))


def validate_anchor_records(failures: list[str]) -> tuple[Counter[str], list[str], dict[str, dict[str, Any]]]:
    """Validate anchor snapshots, status paths, and current C03 constraints."""

    lifecycle_validator = validator("evaluation-case.schema.json", ["candidate-case.schema.json"])
    paths = sorted((ROOT / "evals" / "gold").glob("GOLD-??.json"))
    paths += sorted((ROOT / "evals" / "rejected").glob("REJECTED-??*.json"))
    paths += sorted((ROOT / "evals" / "candidate").glob("CANDIDATE-??-R*.json"))
    counts: Counter[str] = Counter()
    candidate_ids: list[str] = []
    seen: set[str] = set()
    records: dict[str, dict[str, Any]] = {}
    for path in paths:
        case = read_json(path)
        errors = list(lifecycle_validator.iter_errors(case))
        if errors:
            failures.append(f"{path.name}: {errors[0].message}")
            continue
        identity = case["identity"]
        case_id = identity["case_id"]
        if case_id in seen:
            failures.append(f"duplicate anchor case id: {case_id}")
        seen.add(case_id)
        records[case_id] = case
        status = identity["status"]
        counts[status] += 1
        if path.parent.name != status:
            failures.append(f"{path.name}: path status differs from identity status")
        answer = case["artifact"]["answer"]
        answer_hash = digest(answer)
        if status == "gold" and case["artifact"]["approved_snapshot_sha256"] != answer_hash:
            failures.append(f"{path.name}: Gold snapshot differs from accepted answer")
        if status == "candidate":
            candidate_ids.append(case_id)
        if "。" in visible_generated_text(answer):
            failures.append(f"{path.name}: generated prose contains Chinese full stop")

    c03_path = ROOT / "evals" / "gold" / "GOLD-03.json"
    require(c03_path.exists(), "accepted GOLD-03 snapshot is missing")
    c03 = read_json(c03_path)
    answer = c03["artifact"]["answer"]
    if "npm 是官方名称，不是 `Node Package Manager` 的首字母缩写" not in answer:
        failures.append("GOLD-03: official-name boundary is absent")
    if re.search(r"npm\s*(?:是|（|\()\s*Node(?:\.js)? Package Manager", answer, re.IGNORECASE):
        failures.append("GOLD-03: npm is presented as an acronym expansion")
    if not all(item in answer for item in ("客户端", "软件包仓库", "退出码", "CI")):
        failures.append("GOLD-03: one preserved npm or execution explanation is missing")
    source_ids = {atom["id"] for atom in c03["semantics"]["source_atoms"]}
    background_ids = {atom["id"] for atom in c03["semantics"]["background_atoms"]}
    support_ids = {item for mapping in c03["artifact"]["support_map"] for item in mapping["supports"]}
    if not source_ids | background_ids <= support_ids:
        failures.append("GOLD-03: source or background support coverage is incomplete")
    return counts, candidate_ids, records


def forward_paths() -> list[Path]:
    """Return lifecycle JSON files from every materialized forward round."""

    paths: list[Path] = []
    for lifecycle in sorted(FORWARD_ROOT.glob("round-*/lifecycle")):
        paths.extend(sorted(lifecycle.rglob("*.json")))
    return paths


def load_forward_evidence(failures: list[str]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Load immutable attempt-one requests and candidates from every forward round."""

    request_validator = validator("forward-request.schema.json", [])
    candidate_validator = validator("forward-candidate.schema.json", [])
    requests: dict[str, dict[str, Any]] = {}
    originals: dict[str, dict[str, Any]] = {}
    for directory in sorted(FORWARD_ROOT.glob("round-*")):
        if not directory.is_dir():
            continue
        match = re.fullmatch(r"round-([1-9][0-9]*)", directory.name)
        if match is None:
            failures.append(f"invalid forward round directory: {directory.name}")
            continue
        round_number = int(match.group(1))
        request_path = directory / "requests.jsonl"
        candidate_path = directory / "candidates.jsonl"
        if not request_path.exists() and not candidate_path.exists():
            continue
        if not request_path.exists() or not candidate_path.exists():
            failures.append(f"{directory.name}: requests and immutable candidates must both exist")
            continue
        round_requests = load_jsonl(request_path)
        round_candidates = load_jsonl(candidate_path)
        if len(round_requests) != 20 or len(round_candidates) != 20:
            failures.append(f"{directory.name}: expected 20 requests and candidates")
        if set(round_requests) != set(round_candidates):
            failures.append(f"{directory.name}: request and candidate identifiers differ")
        for case_id, request in round_requests.items():
            errors = list(request_validator.iter_errors(request))
            if errors:
                failures.append(f"{case_id}: request schema: {errors[0].message}")
            if request.get("round") != round_number or not case_id.startswith(f"FWD-R{round_number}-"):
                failures.append(f"{case_id}: request is stored in the wrong round")
            if case_id in requests:
                failures.append(f"duplicate immutable request: {case_id}")
            requests[case_id] = request
        for case_id, candidate in round_candidates.items():
            errors = list(candidate_validator.iter_errors(candidate))
            if errors:
                failures.append(f"{case_id}: candidate schema: {errors[0].message}")
            if candidate.get("round") != round_number or candidate.get("generation_attempt") != 1:
                failures.append(f"{case_id}: immutable attempt metadata differs")
            if candidate.get("request_sha256") != digest(json.dumps(round_requests.get(case_id), ensure_ascii=False, sort_keys=True, separators=(",", ":"))):
                failures.append(f"{case_id}: immutable request binding differs")
            if candidate.get("answer_sha256") != digest(candidate.get("answer", "")):
                failures.append(f"{case_id}: immutable answer digest differs")
            originals[case_id] = candidate
    return requests, originals


def validate_forward_records(failures: list[str]) -> tuple[Counter[str], list[str]]:
    """Validate generalized rounds, revisions, immutable attempts, and revision ancestry."""

    lifecycle_validator = validator("forward-lifecycle.schema.json", ["forward-request.schema.json"])
    requests, originals = load_forward_evidence(failures)
    records: dict[str, dict[str, Any]] = {}
    counts: Counter[str] = Counter()
    candidates: list[str] = []
    for path in forward_paths():
        case = read_json(path)
        errors = list(lifecycle_validator.iter_errors(case))
        if errors:
            failures.append(f"{path.name}: {errors[0].message}")
            continue
        identity = case["identity"]
        case_id = identity["case_id"]
        if case_id in records:
            failures.append(f"duplicate forward case id: {case_id}")
        records[case_id] = case
        status = identity["status"]
        counts[status] += 1
        if path.parent.name != status:
            failures.append(f"{path.name}: path status differs from identity status")
        if status == "candidate":
            candidates.append(case_id)

        origin = identity["origin_case_id"]
        original = originals.get(origin)
        request = requests.get(origin)
        if original is None or request is None:
            failures.append(f"{path.name}: immutable forward source is missing")
            continue
        if case["source"]["original_answer_sha256"] != original["answer_sha256"]:
            failures.append(f"{path.name}: original answer digest changed")
        if case["source"]["original_request_sha256"] != original["request_sha256"]:
            failures.append(f"{path.name}: original request digest changed")
        if case["task"] != request:
            failures.append(f"{path.name}: request differs from immutable forward request")
        if identity["revision"] == 1 and status in {"gold", "rejected"} and case["artifact"]["answer"] != original["answer"]:
            failures.append(f"{path.name}: reviewed first attempt was rewritten")

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
        answer_hash = digest(case["artifact"]["answer"])
        if answer_hash != case["artifact"]["answer_sha256"]:
            failures.append(f"{path.name}: answer digest mismatch")
        if status == "gold" and case["artifact"]["approved_snapshot_sha256"] != answer_hash:
            failures.append(f"{path.name}: Gold snapshot does not bind the reviewed answer")
        if status == "candidate" and identity["revision"] > 1 and "。" in visible_generated_text(case["artifact"]["answer"]):
            failures.append(f"{path.name}: revised generated prose contains Chinese full stop")

    for case_id, case in records.items():
        parent = case["artifact"]["revision_of"]
        if parent is not None and parent not in records:
            failures.append(f"{case_id}: revision parent does not exist: {parent}")

    fwd009 = records.get("GOLD-FWD-R1-009-R3")
    if fwd009:
        answer = fwd009["artifact"]["answer"]
        blocks = re.findall(r"```python\n(.*?)```", answer, re.DOTALL)
        annotated = next((block for block in blocks if "#" in block), "")
        units: list[tuple[int, int]] = []
        for line in annotated.splitlines():
            if not line.strip() or re.fullmatch(r"\s*[\]\[{}(),;]+\s*", line):
                continue
            marker = line.find("#")
            if marker < 0:
                failures.append("GOLD-FWD-R1-009-R3: one effective statement lacks a same-line comment")
                continue
            code = line[:marker].rstrip(" \t")
            units.append((display_width(code), display_width(line[:marker]) + 1))
        if not units:
            failures.append("GOLD-FWD-R1-009-R3: aligned annotated block is missing")
        else:
            target = max(width for width, _ in units) + 2
            if any(column != target for _, column in units):
                failures.append("GOLD-FWD-R1-009-R3: comments are not aligned at longest code width plus two")
        if "调用方提供可逐项读取" in answer:
            failures.append("GOLD-FWD-R1-009-R3: prose repeats content already carried by comments")
    fwd015 = records.get("GOLD-FWD-R1-015-R3")
    if fwd015 and "重新安装会删除尚未同步的本地标注" not in fwd015["artifact"]["answer"]:
        failures.append("GOLD-FWD-R1-015-R3: source certainty about local annotation deletion was weakened")
    return counts, candidates


def latest_review() -> dict[str, Any]:
    """Return the latest review ledger that declares post-review counts."""

    ledgers: list[tuple[int, dict[str, Any]]] = []
    for path in (ROOT / "evals" / "reviews").glob("vnext-1.1-round-*.json"):
        match = re.fullmatch(r"vnext-1\.1-round-([1-9][0-9]*)\.json", path.name)
        if match is None:
            continue
        review = read_json(path).get("review_round", {})
        if "post_review_counts" in review:
            ledgers.append((int(match.group(1)), review))
    require(bool(ledgers), "no review ledger declares current lifecycle counts")
    return max(ledgers, key=lambda item: item[0])[1]


def validate_review_bindings(review: dict[str, Any], anchor_records: dict[str, dict[str, Any]], forward_records: dict[str, dict[str, Any]], failures: list[str]) -> list[str]:
    """Bind every explicit decision to the reviewed digest and resulting record."""

    decisions = review["decisions"]
    expected_result = review["review_result"]
    if len(decisions) != expected_result["reviewed"]:
        failures.append("review ledger decision count differs from review_result")
    decision_counts = Counter(item["decision"] for item in decisions)
    if decision_counts != Counter({"accepted": expected_result["accepted"], "rejected": expected_result["rejected"]}):
        failures.append("review ledger accepted or rejected count differs from review_result")
    all_records = anchor_records | forward_records
    expected_candidates: list[str] = []
    for decision in decisions:
        result_id = decision["resulting_record_id"]
        result = all_records.get(result_id)
        if result is None:
            failures.append(f"review result record is missing: {result_id}")
            continue
        if digest(result["artifact"]["answer"]) != decision["reviewed_answer_sha256"]:
            failures.append(f"{result_id}: reviewed answer digest does not match the ledger")
        expected_status = "gold" if decision["decision"] == "accepted" else "rejected"
        if result["identity"]["status"] != expected_status:
            failures.append(f"{result_id}: status contradicts explicit review decision")
        next_candidate = decision["next_candidate_id"]
        if decision["decision"] == "accepted" and next_candidate is not None:
            failures.append(f"{result_id}: accepted decision cannot create a candidate")
        if decision["decision"] == "rejected":
            if not next_candidate or next_candidate not in all_records:
                failures.append(f"{result_id}: rejected decision lacks its next candidate")
            else:
                expected_candidates.append(next_candidate)
    return expected_candidates


def build_report(review: dict[str, Any], failures: list[str], counts: Counter[str], candidate_ids: list[str]) -> dict[str, Any]:
    """Keep machine integrity, explicit review, and release streak separate."""

    result = review["review_result"]
    accepted, total = (int(value) for value in review["first_round_result"]["human_acceptance"].split("/"))
    streak = review["perfect_round_streak"]
    report = {
        "artifact_integrity": {
            "status": "PASS" if not failures else "FAIL",
            "checked": sum(counts.values()),
            "failures": failures,
        },
        "human_acceptance": {"accepted": accepted, "total": total, "rate": accepted / total, "threshold_met": accepted == total},
        "revision_review": {
            "decision_source": "explicit_user_review",
            "reviewed": result["reviewed"],
            "accepted": result["accepted"],
            "rejected": result["rejected"],
        },
        "current_candidates": {
            "pending": len(candidate_ids),
            "case_ids": sorted(candidate_ids),
            "all_explicitly_accepted": not candidate_ids,
        },
        "perfect_round_streak": streak,
        "next_round_allowed": review["first_round_result"]["next_round_allowed"] and not candidate_ids,
        "reason": (
            f"生命周期和摘要一致，但 {len(candidate_ids)} 个新候选尚未获得用户接受"
            if candidate_ids and not failures
            else "生命周期、摘要和人工决定绑定一致；当前没有待审候选"
            if not failures
            else "生命周期、摘要、来源或人工决定绑定存在错误"
        ),
        "impact": (
            "当前审核包可以提交用户审核；自动通过不会改变人工状态"
            if candidate_ids and not failures
            else "可以按人工门槛生成下一轮未见案例；自动通过不会改变人工状态"
            if not failures
            else "当前候选包不能进入人工审核"
        ),
        "next": (
            "审核 " + "、".join(sorted(candidate_ids))
            if candidate_ids and not failures
            else "生成下一轮全新未见案例"
            if not failures
            else "修复列出的确定性错误后重新验证"
        ),
    }
    jsonschema.Draft202012Validator(read_json(ROOT / "contracts" / "forward-round-report.schema.json")).validate(report)
    return report


def main() -> int:
    """Validate all records and print dynamically derived counts."""

    failures: list[str] = []
    try:
        review = latest_review()
        anchor_counts, anchor_candidates, anchor_records = validate_anchor_records(failures)
        forward_counts, forward_candidates = validate_forward_records(failures)
        forward_records = {read_json(path)["identity"]["case_id"]: read_json(path) for path in forward_paths()}
        expected_candidates = validate_review_bindings(review, anchor_records, forward_records, failures)
        pending_first_attempts = [
            case_id for case_id, case in forward_records.items()
            if case["identity"]["status"] == "candidate"
            and case["identity"]["revision"] == 1
            and case["review"]["decision_source"] == "pending_user_review"
        ]
        expected_candidates.extend(pending_first_attempts)
        counts = anchor_counts + forward_counts
        expected = review["post_review_counts"]
        require(anchor_counts == Counter({key: value for key, value in expected["anchor"].items() if key != "total"}), f"anchor post-review counts differ: {dict(anchor_counts)}")
        expected_forward = Counter({key: value for key, value in expected["forward"].items() if key != "total"})
        expected_forward["candidate"] += len(pending_first_attempts)
        expected_combined = Counter({key: value for key, value in expected["combined"].items() if key != "total"})
        expected_combined["candidate"] += len(pending_first_attempts)
        require(forward_counts == expected_forward, f"forward post-review plus pending counts differ: {dict(forward_counts)}")
        require(counts == expected_combined, f"combined post-review plus pending counts differ: {dict(counts)}")
        require(sum(counts.values()) == expected["combined"]["total"] + len(pending_first_attempts), "combined lifecycle total differs from review ledger plus pending attempts")
        candidates = anchor_candidates + forward_candidates
        require(sorted(candidates) == sorted(expected_candidates), "current candidates differ from explicit rejected-decision transitions")
    except (ValidationFailure, json.JSONDecodeError, jsonschema.ValidationError) as error:
        failures.append(str(error))
        review = {"review_result": {"reviewed": 0, "accepted": 0, "rejected": 0}, "first_round_result": {"human_acceptance": "0/1", "next_round_allowed": False}, "perfect_round_streak": {"current": 0, "required": 2, "release_gate_met": False}}
        counts = Counter()
        candidates = []
    report = build_report(review, failures, counts, candidates)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["artifact_integrity"]["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
