"""Preserve legacy round-two drafts and record the five explicit Sol rejections."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ROUND = ROOT / "evals" / "forward" / "round-2"
PROFILE = "round-6-self-iterative-cross-model"
REVIEWED_AT = "2026-09-01"

FEEDBACK: dict[str, dict[str, Any]] = {
    "FWD-R2-021": {
        "instruction": "021：中文句号，失败，内容排版不够清晰",
        "reasons": ["生成正文含中文句号", "完成项、待处理项和只读状态挤在同一行，排版不够清晰"],
        "correct_parts": ["保留复核编号 B21、12 项已完成、2 项待权限恢复和未进行复制"],
        "regressions": ["删除生成中文句号", "把多个状态事实换行并保持原数字与范围"],
    },
    "FWD-R2-022": {
        "instruction": "022：括号内英文没首字母大写，残余压力作为专业词汇没有英文，内容没问题",
        "reasons": ["括号内 lockout 没有使用标题式大小写", "残余压力首次出现缺少英文 Residual Pressure"],
        "correct_parts": ["操作顺序和中文解释内容保持不变"],
        "regressions": ["使用上锁隔离（Lockout）", "首次使用残余压力（Residual Pressure）并保留正确含义"],
    },
    "FWD-R2-023": {
        "instruction": "023：含中文句号，内容没啥问题",
        "reasons": ["生成正文含中文句号"],
        "correct_parts": ["抽样数量、差异数量、差额和未检查范围全部保持不变"],
        "regressions": ["只做必要标点修复，不改写正确内容"],
    },
    "FWD-R2-024": {
        "instruction": "024：分号后面没有换行缩进，出现中文句号",
        "reasons": ["多个解释项目被分号压在同一行", "生成正文含中文句号"],
        "correct_parts": ["保留两种电压读数、0.7 V 差值和压降机制"],
        "regressions": ["多个解释项目换行并按层级缩进", "删除生成中文句号"],
    },
    "FWD-R2-025": {
        "instruction": "025：证据边界：这种玩意不应该出现，不需要：来结构化分段，结构化分段应该用###，分号只用于排比和专业词汇",
        "reasons": ["内部证据边界标签泄漏到正文", "使用冒号伪结构", "分号承担了应该换行的多项结构"],
        "correct_parts": ["保留首次配对步骤、圆键时长和复核编号 B25"],
        "regressions": ["默认隐藏证据边界标签", "按需使用 Markdown 标题或直接成文", "分号只用于紧凑并列或专业词说明"],
    },
}


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def main() -> int:
    candidate_dir = ROUND / "lifecycle" / "candidate"
    rejected_dir = ROUND / "lifecycle" / "rejected"
    files = sorted(candidate_dir.glob("CANDIDATE-FWD-R2-*-R1.json"))
    if not files:
        existing = sorted(rejected_dir.glob("REJECTED-FWD-R2-*-SOL.json"))
        if len(existing) == 5 and (ROUND / "legacy-preclosure-attempts.jsonl").exists() and (ROUND / "closure-seeds.jsonl").exists():
            print(json.dumps({"status": "PASS", "mode": "already_applied", "rejected": 5, "legacy_preclosure": 15}, ensure_ascii=False))
            return 0
        raise SystemExit("round-two legacy candidates are missing")
    if len(files) != 20:
        raise SystemExit(f"expected 20 legacy candidates, found {len(files)}")

    legacy: list[dict[str, Any]] = []
    seeds: list[dict[str, Any]] = []
    rejected = 0
    for path in files:
        record = read(path)
        origin = record["identity"]["origin_case_id"]
        if digest(record["artifact"]["answer"]) != record["artifact"]["answer_sha256"]:
            raise SystemExit(f"{path.name}: answer digest mismatch")
        feedback = FEEDBACK.get(origin)
        if feedback is None:
            legacy.append({
                "legacy_status": "legacy_preclosure_attempt",
                "reason": "该单次输出尚无人工决定，保留为运行证据并等待完整闭环替代",
                "record": record,
            })
        else:
            seeds.append({"case_id": origin, "model": "gpt-5.6-sol", "answer": record["artifact"]["answer"]})
            terminal = copy.deepcopy(record)
            terminal["identity"].update({
                "case_id": f"REJECTED-{origin}-SOL",
                "model": "gpt-5.6-sol",
                "status": "rejected",
                "approved_by_user": False,
                "reviewed_at": REVIEWED_AT,
                "profile_revision_at_review": PROFILE,
            })
            terminal["artifact"].update({"approved_snapshot_sha256": None, "revision_of": None})
            terminal["review"].update({
                "decision_source": "explicit_user_review", "decision": "rejected",
                "reasons": feedback["reasons"], "correct_parts": feedback["correct_parts"],
                "regression_requirements": feedback["regressions"], "non_blocking_preferences": [],
            })
            write(rejected_dir / f"REJECTED-{origin}-SOL.json", terminal)
            rejected += 1
        path.unlink()

    (ROUND / "legacy-preclosure-attempts.jsonl").write_text(
        "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in legacy),
        encoding="utf-8", newline="\n",
    )
    (ROUND / "closure-seeds.jsonl").write_text(
        "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in seeds),
        encoding="utf-8", newline="\n",
    )
    write(ROUND / "reviews" / "review-1-source.json", {
        "status": "awaiting_closed_successors",
        "reviewed_at": REVIEWED_AT,
        "profile_revision_at_review": PROFILE,
        "decision_source": "explicit_user_review",
        "decisions": [{"origin_case_id": origin, **feedback} for origin, feedback in FEEDBACK.items()],
        "automated_checks_are_user_acceptance": False,
    })
    print(json.dumps({"status": "PASS", "mode": "applied", "rejected": rejected, "legacy_preclosure": len(legacy)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
