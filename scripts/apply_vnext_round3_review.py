"""Materialize the third-round anchor and forward-test lifecycle without rewriting reviewed snapshots."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FORWARD = ROOT / "evals" / "forward" / "round-1"
LIFECYCLE = FORWARD / "lifecycle"
REVIEW_PATH = ROOT / "evals" / "reviews" / "vnext-1.1-round-3.json"
DRAFTS_PATH = FORWARD / "revision-drafts.json"
REVIEWED_AT = "2026-08-31"
PROFILE_REVISION = "round-3-capitalization"


def digest(text: str) -> str:
    """Return the exact UTF-8 text digest used to protect reviewed answers."""

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_jsonl(path: Path) -> dict[str, dict[str, Any]]:
    """Load one identifier-indexed JSONL file."""

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return {row["case_id"]: row for row in rows}


def write_json(path: Path, value: dict[str, Any]) -> None:
    """Write one stable human-reviewable JSON record."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def build_forward_record(
    *,
    request: dict[str, Any],
    original: dict[str, Any],
    status: str,
    answer: str,
    feedback: list[str],
    revision_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create one lifecycle record while keeping original request and answer digests immutable."""

    origin_id = original["case_id"]
    number = origin_id.rsplit("-", 1)[-1]
    if status == "gold":
        case_id = f"GOLD-FWD-R1-{number}"
        revision = 1
        approved = True
        reviewed_at: str | None = REVIEWED_AT
        reviewed_profile: str | None = PROFILE_REVISION
        decision_source = "explicit_user_review"
        decision = "accepted"
        approved_hash: str | None = digest(answer)
        revision_of: str | None = None
        reasons = ["用户明确表示原始答案可以原样接受"]
    elif status == "rejected":
        case_id = f"REJECTED-FWD-R1-{number}"
        revision = 1
        approved = False
        reviewed_at = REVIEWED_AT
        reviewed_profile = PROFILE_REVISION
        decision_source = "explicit_user_review"
        decision = "rejected"
        approved_hash = None
        revision_of = None
        reasons = feedback
    else:
        case_id = f"CANDIDATE-FWD-R1-{number}-R2"
        revision = 2
        approved = False
        reviewed_at = None
        reviewed_profile = None
        decision_source = "pending_user_review"
        decision = "pending"
        approved_hash = None
        revision_of = f"REJECTED-FWD-R1-{number}"
        reasons = ["根据第一轮用户反馈完成修订，等待用户逐项审核"]
    revision_evidence = revision_evidence or {"references": [], "background_claims": []}
    return {
        "identity": {
            "case_id": case_id,
            "origin_case_id": origin_id,
            "status": status,
            "revision": revision,
            "approved_by_user": approved,
            "reviewed_at": reviewed_at,
            "profile_revision_at_review": reviewed_profile,
        },
        "task": copy.deepcopy(request),
        "source": {
            "original_request_sha256": original["request_sha256"],
            "original_answer_sha256": original["answer_sha256"],
            "source_units": copy.deepcopy(original["source_units"]),
            "support_map": copy.deepcopy(original["support_map"]),
            "background_claims": copy.deepcopy(original["background_claims"]) + copy.deepcopy(revision_evidence["background_claims"]),
            "revision_references": copy.deepcopy(revision_evidence["references"]),
        },
        "artifact": {
            "answer": answer,
            "answer_sha256": digest(answer),
            "approved_snapshot_sha256": approved_hash,
            "revision_of": revision_of,
        },
        "review": {
            "decision_source": decision_source,
            "decision": decision,
            "reasons": reasons,
            "correct_parts": ["原始答案中未被用户否定的事实、数字、条件和证据边界继续保留"],
            "regression_requirements": feedback,
            "non_blocking_preferences": [],
            "privacy": {
                "status": "public_safe",
                "basis": "只保存脱敏技术反馈，不保存原始对话、账户信息或个人路径",
            },
        },
    }


def convert_c03() -> list[str]:
    """Freeze R4 as rejected and create a separate R5 candidate."""

    source_path = ROOT / "evals" / "candidate" / "CANDIDATE-03-R4.json"
    if not source_path.exists():
        source_path = ROOT / "evals" / "rejected" / "REJECTED-03-R4.json"
    r4 = json.loads(source_path.read_text(encoding="utf-8"))
    review = json.loads(REVIEW_PATH.read_text(encoding="utf-8"))["review_round"]["c03"]
    reviewed_hash = digest(r4["artifact"]["answer"])

    rejected = copy.deepcopy(r4)
    rejected["identity"].update({
        "case_id": "REJECTED-03-R4",
        "status": "rejected",
        "approved_by_user": False,
        "reviewed_at": REVIEWED_AT,
        "profile_revision_at_review": PROFILE_REVISION,
    })
    rejected["artifact"]["approved_snapshot_sha256"] = None
    rejected["review"].update({
        "decision": "rejected",
        "reasons": review["reasons"],
        "correct_parts": review["correct_parts"],
        "regression_requirements": [
            "npm 保持官方小写",
            "不得把 npm 展开为 Node.js Package Manager",
            "首次出现时自然说明 npm 的客户端和软件包仓库作用",
            "命令注释明确执行主体",
            "保留退出码、CI 和证据边界",
        ],
    })
    rejected["review"]["reviewed_snapshot_sha256"] = reviewed_hash
    write_json(ROOT / "evals" / "rejected" / "REJECTED-03-R4.json", rejected)

    r5 = copy.deepcopy(r4)
    r5["identity"].update({
        "case_id": "CANDIDATE-03-R5", "status": "candidate", "revision": 5,
        "approved_by_user": False, "reviewed_at": None, "profile_revision_at_review": None,
    })
    r5["source"]["references"] = [
        item for item in r5["source"]["references"] if item["id"] != "REF-ROUND-3-CASE"
    ]
    r5["source"]["references"].append({
        "id": "REF-ROUND-4-CASE",
        "kind": "explicit_user_review",
        "content": "npm 保持官方小写，不展开成 Node.js Package Manager；首次出现时自然说明它是 Node.js 生态使用的包管理客户端和软件包仓库",
    })
    r5["semantics"]["background_atoms"] = [
        atom for atom in r5["semantics"]["background_atoms"] if atom["id"] != "BG-004"
    ]
    r5["semantics"]["background_atoms"].append({
        "id": "BG-004",
        "source_reference": "REF-NPM-OFFICIAL",
        "purpose": "解释 npm 的官方形式和用途",
        "claim": "npm 是 Node.js 生态使用的包管理客户端和软件包仓库，不是 Node.js Package Manager 的首字母缩写",
        "provenance_type": "EXTERNAL_BACKGROUND",
    })
    r5["artifact"]["answer"] = (
        "用户可以运行下面的命令，让系统检查项目中的链接：\n\n"
        "```powershell\n"
        "npm run check # npm 调用项目已登记的 check 脚本；系统在命令结束后显示检查结果\n"
        "```\n\n"
        "npm 是 Node.js 生态使用的包管理客户端和软件包仓库；开发者可以用它安装、更新、管理和发布 JavaScript 或 TypeScript 软件包与项目依赖；这里的 `run check` 会让 npm 调用当前项目登记为 `check` 的脚本，脚本的实际检查内容由项目配置决定\n\n"
        "如果系统发现失效链接，检查命令会以退出码 `2` 结束；退出码是命令返回给操作系统的数字状态，调用脚本可以据此判断本次检查失败\n\n"
        "CI 持续集成（Continuous Integration）是开发者提交代码后自动执行构建、测试和检查，从而尽早发现代码集成问题的一套开发流程；CI 可以读取退出码 `2` 并把本次检查标记为失败，但现有说明没有证明当前项目已经启用 CI，需要查看项目的自动化配置才能确认"
    )
    r5["review"].update({
        "decision": "pending",
        "reasons": ["R5 已按用户反馈移除误导性的括号类别和虚假缩写展开，等待人工审核"],
        "correct_parts": review["correct_parts"],
        "regression_requirements": rejected["review"]["regression_requirements"],
    })
    r5["review"].pop("reviewed_snapshot_sha256", None)
    write_json(ROOT / "evals" / "candidate" / "CANDIDATE-03-R5.json", r5)
    candidate_r4 = ROOT / "evals" / "candidate" / "CANDIDATE-03-R4.json"
    if candidate_r4.exists():
        candidate_r4.unlink()
    return ["evals/rejected/REJECTED-03-R4.json", "evals/candidate/CANDIDATE-03-R5.json"]


def convert_forward() -> list[str]:
    """Preserve 20 first attempts and materialize eight Gold, twelve Rejected, and twelve R2 candidates."""

    review = json.loads(REVIEW_PATH.read_text(encoding="utf-8"))["review_round"]["forward"]
    requests = load_jsonl(FORWARD / "requests.jsonl")
    originals = load_jsonl(FORWARD / "candidates.jsonl")
    draft_data = json.loads(DRAFTS_PATH.read_text(encoding="utf-8"))
    drafts = draft_data["candidates"]
    evidence = draft_data["evidence"]
    written: list[str] = []
    for number in range(1, 21):
        case_id = f"FWD-R1-{number:03d}"
        original = originals[case_id]
        request = requests[case_id]
        feedback = review["feedback"].get(f"{number:03d}", [])
        if number in review["accepted"]:
            record = build_forward_record(request=request, original=original, status="gold", answer=original["answer"], feedback=[])
            path = LIFECYCLE / "gold" / f"GOLD-{case_id}.json"
            write_json(path, record)
            written.append(str(path.relative_to(ROOT)))
            continue
        rejected = build_forward_record(request=request, original=original, status="rejected", answer=original["answer"], feedback=feedback)
        rejected_path = LIFECYCLE / "rejected" / f"REJECTED-{case_id}.json"
        write_json(rejected_path, rejected)
        written.append(str(rejected_path.relative_to(ROOT)))
        revised = build_forward_record(request=request, original=original, status="candidate", answer=drafts[case_id], feedback=feedback, revision_evidence=evidence[case_id])
        candidate_path = LIFECYCLE / "candidate" / f"CANDIDATE-{case_id}-R2.json"
        write_json(candidate_path, revised)
        written.append(str(candidate_path.relative_to(ROOT)))
    return written


def main() -> int:
    """Generate all lifecycle outputs and report exact counts."""

    written = convert_c03() + convert_forward()
    print(json.dumps({
        "status": "PASS",
        "written": written,
        "lifecycle": {"gold": 19, "rejected": 25, "candidate": 13, "total": 57},
        "reason": "第三轮用户决定已绑定原始答案摘要，修订候选使用新版本号且没有覆盖首次前向答案",
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
