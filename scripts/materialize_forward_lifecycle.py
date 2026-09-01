"""Create pending lifecycle records from one immutable first-attempt round."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--round", type=int, required=True, dest="round_number")
    return parser.parse_args()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> int:
    args = parse_args()
    if args.round_number < 2:
        raise SystemExit("pending first-attempt lifecycle materialization is only valid for round 2 or later")
    directory = ROOT / "evals" / "forward" / f"round-{args.round_number}"
    requests = {item["case_id"]: item for item in read_jsonl(directory / "requests.jsonl")}
    candidates = read_jsonl(directory / "candidates.jsonl")
    if len(requests) != 20 or len(candidates) != 20:
        raise SystemExit("expected exactly 20 immutable requests and candidates")
    lifecycle = directory / "lifecycle"
    target = lifecycle / "candidate"
    target.mkdir(parents=True, exist_ok=True)
    for name in ("gold", "rejected"):
        (lifecycle / name).mkdir(parents=True, exist_ok=True)
    expected_files: set[str] = set()
    for candidate in candidates:
        origin = candidate["case_id"]
        request = requests.get(origin)
        if request is None:
            raise SystemExit(f"missing request for {origin}")
        record_id = f"CANDIDATE-{origin}-R1"
        filename = record_id + ".json"
        expected_files.add(filename)
        record = {
            "identity": {
                "case_id": record_id,
                "origin_case_id": origin,
                "status": "candidate",
                "revision": 1,
                "approved_by_user": False,
                "reviewed_at": None,
                "profile_revision_at_review": None,
            },
            "task": request,
            "source": {
                "original_request_sha256": candidate["request_sha256"],
                "original_answer_sha256": candidate["answer_sha256"],
                "source_units": candidate["source_units"],
                "support_map": candidate["support_map"],
                "background_claims": candidate["background_claims"],
                "revision_references": [],
            },
            "artifact": {
                "answer": candidate["answer"],
                "answer_sha256": candidate["answer_sha256"],
                "approved_snapshot_sha256": None,
                "revision_of": None,
            },
            "review": {
                "decision_source": "pending_user_review",
                "decision": "pending",
                "reasons": [],
                "correct_parts": [],
                "regression_requirements": [],
                "non_blocking_preferences": [],
                "privacy": {
                    "status": "public_safe",
                    "basis": "全新合成评测主题，不含用户、服务器、私有项目或凭据数据",
                },
            },
        }
        (target / filename).write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    stale = [path for path in target.glob("*.json") if path.name not in expected_files]
    if stale:
        raise SystemExit("refusing to remove unexpected pending lifecycle files: " + ", ".join(path.name for path in stale))
    print(json.dumps({"status": "PASS", "round": args.round_number, "pending": len(expected_files)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
