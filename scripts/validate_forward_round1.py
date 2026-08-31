"""Validate round-one forward artifacts without assigning a human style verdict."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / "evals" / "forward" / "round-1"
BANNED_ANCHOR_TERMS = ["npm", "CI", "FPGA", "幂等", "PowerShell", "SHA-256", "订单", "发票", "队列"]


def canonical_digest(value: Any) -> str:
    """Hash one JSON value with stable encoding."""

    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def source_digest(content: Any) -> str:
    """Hash request source content with the request-builder convention."""

    serialized = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def visible_generated_text(answer: str) -> str:
    """Remove verbatim code, blockquotes, tables, and image references from profile punctuation checks."""

    text = re.sub(r"```.*?```", "", answer, flags=re.DOTALL)
    lines = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith(">") or stripped.startswith("![") or stripped.startswith("|"):
            continue
        lines.append(line)
    return "\n".join(lines)


def main() -> int:
    """Check schemas, digests, source mappings, declared provenance, privacy, and component retention."""

    request_schema = json.loads((ROOT / "contracts" / "forward-request.schema.json").read_text(encoding="utf-8"))
    candidate_schema = json.loads((ROOT / "contracts" / "forward-candidate.schema.json").read_text(encoding="utf-8"))
    requests = [json.loads(line) for line in (DIRECTORY / "requests.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    candidates = [json.loads(line) for line in (DIRECTORY / "candidates.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    errors: list[str] = []
    request_validator = jsonschema.Draft202012Validator(request_schema)
    candidate_validator = jsonschema.Draft202012Validator(candidate_schema)
    if len(requests) != 20 or len(candidates) != 20:
        errors.append(f"expected 20 requests and candidates, found {len(requests)} and {len(candidates)}")
    request_by_id = {item.get("case_id"): item for item in requests}
    candidate_by_id = {item.get("case_id"): item for item in candidates}
    if len(request_by_id) != len(requests) or len(candidate_by_id) != len(candidates):
        errors.append("forward case identifiers are not unique")
    if set(request_by_id) != set(candidate_by_id):
        errors.append("request and candidate identifiers differ")
    source_coverage = 0
    background_coverage = 0
    for case_id in sorted(set(request_by_id) & set(candidate_by_id)):
        request = request_by_id[case_id]
        candidate = candidate_by_id[case_id]
        request_errors = list(request_validator.iter_errors(request))
        candidate_errors = list(candidate_validator.iter_errors(candidate))
        if request_errors:
            errors.append(f"{case_id} request schema: {request_errors[0].message}")
        if candidate_errors:
            errors.append(f"{case_id} candidate schema: {candidate_errors[0].message}")
        if source_digest(request["source"]["content"]) != request["source"]["sha256"]:
            errors.append(f"{case_id} source digest changed")
        if canonical_digest(request) != candidate["request_sha256"]:
            errors.append(f"{case_id} request binding changed")
        if hashlib.sha256(candidate["answer"].encode("utf-8")).hexdigest() != candidate["answer_sha256"]:
            errors.append(f"{case_id} answer digest changed")
        source_units = set(candidate["source_units"])
        if source_units != set(candidate["support_map"]):
            errors.append(f"{case_id} declared source-unit coverage is incomplete")
        else:
            source_coverage += 1
        reference_ids = {item["id"] for item in request["references"]}
        if any(item["source_reference"] not in reference_ids for item in candidate["background_claims"]):
            errors.append(f"{case_id} contains an unresolved background reference")
        else:
            background_coverage += 1
        combined_request = json.dumps(request, ensure_ascii=False)
        if any(re.search(rf"(?<![A-Za-z]){re.escape(term)}(?![A-Za-z])", combined_request, re.IGNORECASE) for term in BANNED_ANCHOR_TERMS):
            errors.append(f"{case_id} reuses a prohibited anchor term or material")
        visible = visible_generated_text(candidate["answer"])
        if "。" in visible:
            errors.append(f"{case_id} generated prose contains a Chinese full stop")
        if re.search(r"(?:ghp_|github_pat_|AKIA)[A-Za-z0-9_]+|[A-Za-z]:\\Users\\[^\\]+", candidate["answer"]):
            errors.append(f"{case_id} contains a secret pattern or personal absolute path")
        content = request["source"]["content"]
        material = request["source"]["material_type"]
        answer = candidate["answer"]
        if material in {"table", "code"} and isinstance(content, str) and content not in answer:
            errors.append(f"{case_id} does not preserve the original {material}")
        if material == "image" and isinstance(content, dict):
            path = content["path"]
            if path not in answer:
                errors.append(f"{case_id} does not preserve the original image")
    registered = json.loads((DIRECTORY / "deterministic-findings.json").read_text(encoding="utf-8"))
    registered_messages = [item["message"] for item in registered["findings"]]
    unexpected_errors = [item for item in errors if item not in registered_messages]
    missing_registered = [item for item in registered_messages if item not in errors]
    evidence_errors = []
    if registered.get("hard_error_count") != len(registered_messages):
        evidence_errors.append("registered hard-error count differs from its finding list")
    if registered.get("second_round_allowed") is not False:
        evidence_errors.append("second round must remain blocked while hard errors exist")
    evidence_errors.extend(f"unregistered error: {item}" for item in unexpected_errors)
    evidence_errors.extend(f"registered error no longer reproduced: {item}" for item in missing_registered)
    report = {
        "artifact_integrity": {
            "status": "PASS" if not evidence_errors else "FAIL",
            "checked": len(candidates),
            "failures": evidence_errors,
        },
        "human_acceptance": {"accepted": 8, "total": 20, "rate": 0.4, "threshold_met": False},
        "next_round_allowed": False,
        "reason": "首次答案、请求摘要和已登记机械错误保持一致，但用户只原样接受 8/20" if not evidence_errors else "前向证据与实际检查结果不一致",
        "impact": "第一轮成绩固定为 40%，修订版不能替换该成绩，第二轮继续停止" if not evidence_errors else "当前记录不能证明第一轮的真实结果",
        "next": "审核 12 个前向 R2 修订候选；全部接受后再生成第二轮" if not evidence_errors else "修复证据记录或生成物不一致问题",
    }
    report_schema = json.loads((ROOT / "contracts" / "forward-round-report.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(report_schema).validate(report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not evidence_errors else 1


if __name__ == "__main__":
    sys.exit(main())
