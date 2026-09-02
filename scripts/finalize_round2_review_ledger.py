"""Bind five explicit legacy Sol rejections to their closed R2 successors."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ROUND = ROOT / "evals" / "forward" / "round-2"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check", action="store_true",
        help="report readiness without writing the canonical review ledger",
    )
    return parser.parse_args()


def read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_ledger() -> tuple[dict[str, Any] | None, list[str]]:
    source_path = ROUND / "reviews" / "review-1-source.json"
    target = ROUND / "reviews" / "review-1.json"
    if not source_path.exists():
        if target.exists():
            return read(target), []
        return None, [source_path.as_posix()]
    source = read(source_path)
    decisions = []
    missing: list[str] = []
    for item in source["decisions"]:
        origin = item["origin_case_id"]
        rejected_path = ROUND / "lifecycle" / "rejected" / f"REJECTED-{origin}-SOL.json"
        candidate_path = ROUND / "lifecycle" / "candidate" / f"CANDIDATE-{origin}-SOL-R2.json"
        absent = [path for path in (rejected_path, candidate_path) if not path.exists()]
        if absent:
            missing.extend(path.as_posix() for path in absent)
            continue
        rejected = read(rejected_path)
        candidate = read(candidate_path)
        decisions.append({
            "reviewed_candidate_id": f"CANDIDATE-{origin}-SOL-R1",
            "reviewed_answer_sha256": rejected["artifact"]["answer_sha256"],
            "decision": "rejected",
            "user_instruction": item["instruction"],
            "reasons": item["reasons"],
            "correct_parts": item["correct_parts"],
            "regression_requirements": item["regressions"],
            "non_blocking_preferences": [],
            "resulting_record_id": f"REJECTED-{origin}-SOL",
            "next_candidate": {
                "candidate_id": candidate["identity"]["case_id"],
                "answer": candidate["artifact"]["answer"],
                "answer_sha256": candidate["artifact"]["answer_sha256"],
            },
        })
    if missing:
        return None, sorted(set(missing))
    return {
        "review_id": "forward-round-2-review-1",
        "forward_round": 2,
        "review_iteration": 1,
        "reviewed_at": source["reviewed_at"],
        "decision_source": "explicit_user_review",
        "profile_revision_at_review": source["profile_revision_at_review"],
        "privacy": {
            "status": "public_safe",
            "basis": "只记录用户对合成评测答案的技术反馈，不包含私有运行信息",
        },
        "decisions": decisions,
    }, []


def main() -> int:
    args = parse_args()
    target = ROUND / "reviews" / "review-1.json"
    source_path = ROUND / "reviews" / "review-1-source.json"
    if target.exists() and not source_path.exists():
        ledger = read(target)
        print(json.dumps({
            "status": "PASS", "mode": "already_applied",
            "review_id": ledger["review_id"], "decisions": len(ledger["decisions"]),
            "source_removed": False, "automated_checks_are_user_acceptance": False,
        }, ensure_ascii=False))
        return 0
    ledger, missing = build_ledger()
    if missing:
        print(json.dumps({
            "status": "BLOCKED",
            "reason": "closed Sol successors are not ready",
            "missing": missing,
            "automated_checks_are_user_acceptance": False,
        }, ensure_ascii=False))
        return 2
    assert ledger is not None
    if args.check:
        print(json.dumps({
            "status": "READY", "review_id": ledger["review_id"],
            "decisions": len(ledger["decisions"]),
            "automated_checks_are_user_acceptance": False,
        }, ensure_ascii=False))
        return 0
    target.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    if source_path.exists():
        source_path.unlink()
    print(json.dumps({
        "status": "PASS", "review_id": ledger["review_id"],
        "decisions": len(ledger["decisions"]), "source_removed": True,
        "automated_checks_are_user_acceptance": False,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
