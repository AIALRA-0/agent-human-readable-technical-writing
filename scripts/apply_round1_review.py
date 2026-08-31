"""Convert the 12 reviewed candidate anchors into stable lifecycle records."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REVIEW_PATH = ROOT / "evals" / "reviews" / "vnext-1.1-round-1.json"


def canonical_sha256(data: object) -> str:
    """Return one stable digest so later revisions can prove their exact origin."""

    encoded = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_lifecycle_case(original: dict, decision: dict) -> dict:
    """Preserve the original source and answer while changing only lifecycle metadata."""

    number = original["identity"]["case_id"].split("-")[-1]
    accepted = decision["decision"] == "accepted"
    status = "gold" if accepted else "rejected"
    case_id = f"GOLD-{number}" if accepted else f"REJECTED-{number}"
    return {
        "identity": {
            "case_id": case_id,
            "origin_case_id": original["identity"]["case_id"],
            "status": status,
            "revision": 1,
            "approved_by_user": accepted,
            "category": original["identity"]["category"],
            "reviewed_at": "2026-08-30",
        },
        "task": original["task"],
        "source": original["source"],
        "semantics": original["semantics"],
        "artifact": {
            "answer": original["candidate"]["answer"],
            "support_map": original["candidate"]["support_map"],
            "self_claims": original["candidate"]["self_claims"],
            "original_case_sha256": canonical_sha256(original),
        },
        "review": {
            "decision_source": "explicit_user_review",
            "decision": decision["decision"],
            "reasons": decision["reasons"],
            "correct_parts": decision["correct_parts"],
            "regression_requirements": decision["regression_requirements"],
            "privacy": {
                "status": "public_safe",
                "basis": "只保存脱敏后的技术判断，不包含原始对话、账户信息或个人路径",
            },
        },
    }


def main() -> int:
    """Write deterministic lifecycle files and leave deletion of old names to version control."""

    review = json.loads(REVIEW_PATH.read_text(encoding="utf-8"))["review_round"]
    decisions = {item["origin_case_id"]: item for item in review["decisions"]}
    written = []
    for number in range(1, 13):
        origin_id = f"CANDIDATE-{number:02d}"
        source_path = ROOT / "evals" / "candidate" / f"{origin_id}.json"
        if not source_path.exists():
            destination = ROOT / "evals" / ("gold" if number <= 2 else "rejected") / (
                f"GOLD-{number:02d}.json" if number <= 2 else f"REJECTED-{number:02d}.json"
            )
            if destination.exists():
                written.append(str(destination.relative_to(ROOT)))
                continue
            raise FileNotFoundError(source_path)
        original = json.loads(source_path.read_text(encoding="utf-8"))
        lifecycle = build_lifecycle_case(original, decisions[origin_id])
        destination = ROOT / "evals" / lifecycle["identity"]["status"] / f'{lifecycle["identity"]["case_id"]}.json'
        destination.write_text(json.dumps(lifecycle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        written.append(str(destination.relative_to(ROOT)))

    print(json.dumps({"status": "PASS", "written": written, "reason": "12 explicit user decisions were converted without changing source material or reviewed answers"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
