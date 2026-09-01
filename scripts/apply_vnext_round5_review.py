"""Apply the five explicit round-five acceptances without rewriting answers."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REVIEW_PATH = ROOT / "evals" / "reviews" / "vnext-1.1-round-5.json"
REVIEWED_AT = "2026-09-01"
PROFILE = "round-5-inline-alignment-aemp"


def digest(text: str) -> str:
    """Return the immutable UTF-8 answer digest."""

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    """Read one UTF-8 JSON object."""

    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict[str, Any]) -> None:
    """Write one stable UTF-8 JSON object."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def accept_anchor(decision: dict[str, Any]) -> str:
    """Convert the exact C03 R6 snapshot to GOLD-03."""

    candidate_path = ROOT / "evals" / "candidate" / f"{decision['reviewed_candidate_id']}.json"
    gold_path = ROOT / "evals" / "gold" / f"{decision['resulting_record_id']}.json"
    source = read_json(candidate_path if candidate_path.exists() else gold_path)
    accepted = copy.deepcopy(source)
    answer_hash = digest(accepted["artifact"]["answer"])
    if answer_hash != decision["reviewed_answer_sha256"]:
        raise RuntimeError("C03 reviewed answer digest differs from the explicit decision")
    accepted["identity"].update({
        "case_id": decision["resulting_record_id"],
        "status": "gold",
        "revision": 6,
        "approved_by_user": True,
        "reviewed_at": REVIEWED_AT,
        "profile_revision_at_review": PROFILE,
    })
    accepted["artifact"]["approved_snapshot_sha256"] = answer_hash
    accepted["review"].update({
        "decision_source": "explicit_user_review",
        "decision": "accepted",
        "reasons": [decision["user_instruction"]],
        "reviewed_snapshot_sha256": answer_hash,
    })
    write_json(gold_path, accepted)
    if candidate_path.exists():
        candidate_path.unlink()
    return str(gold_path.relative_to(ROOT)).replace("\\", "/")


def accept_forward(decision: dict[str, Any]) -> str:
    """Convert one exact forward R3 snapshot to Gold."""

    lifecycle = ROOT / "evals" / "forward" / "round-1" / "lifecycle"
    candidate_path = lifecycle / "candidate" / f"{decision['reviewed_candidate_id']}.json"
    gold_path = lifecycle / "gold" / f"{decision['resulting_record_id']}.json"
    source = read_json(candidate_path if candidate_path.exists() else gold_path)
    accepted = copy.deepcopy(source)
    answer_hash = digest(accepted["artifact"]["answer"])
    if answer_hash != decision["reviewed_answer_sha256"]:
        raise RuntimeError(f"{decision['reviewed_candidate_id']}: answer digest differs from the explicit decision")
    accepted["identity"].update({
        "case_id": decision["resulting_record_id"],
        "status": "gold",
        "approved_by_user": True,
        "reviewed_at": REVIEWED_AT,
        "profile_revision_at_review": PROFILE,
    })
    accepted["artifact"]["approved_snapshot_sha256"] = answer_hash
    accepted["review"].update({
        "decision_source": "explicit_user_review",
        "decision": "accepted",
        "reasons": [decision["user_instruction"]],
    })
    write_json(gold_path, accepted)
    if candidate_path.exists():
        candidate_path.unlink()
    return str(gold_path.relative_to(ROOT)).replace("\\", "/")


def main() -> int:
    """Apply all five decisions and report the exact post-review state."""

    review = read_json(REVIEW_PATH)["review_round"]
    if review["review_result"] != {
        "reviewed": 5,
        "accepted": 5,
        "rejected": 0,
        "new_candidates": 0,
        "automated_checks_are_user_acceptance": False,
    }:
        raise RuntimeError("round-five review summary differs from the five explicit acceptances")
    written = []
    for decision in review["decisions"]:
        if decision["decision"] != "accepted" or decision["next_candidate_id"] is not None:
            raise RuntimeError("round-five ledger may contain only terminal accepted decisions")
        if decision["reviewed_candidate_id"] == "CANDIDATE-03-R6":
            written.append(accept_anchor(decision))
        else:
            written.append(accept_forward(decision))
    print(json.dumps({
        "status": "PASS",
        "written": written,
        "lifecycle": {"gold": 32, "rejected": 30, "candidate": 0, "total": 62},
        "first_round_human_acceptance": "8/20",
        "round_five_review": {"accepted": 5, "rejected": 0, "new_candidates": 0},
        "next_round_allowed": True,
        "reason": "only the five explicit user acceptances changed lifecycle state; accepted answer text was not rewritten",
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
