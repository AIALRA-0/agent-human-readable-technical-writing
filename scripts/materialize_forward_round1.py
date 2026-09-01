"""Bind one round of isolated drafts to exact requests and immutable digests."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIRECTORY = ROOT / "evals" / "forward" / "round-1"


def canonical_digest(value: Any) -> str:
    """Hash one JSON value with stable UTF-8 encoding."""

    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def parse_args() -> argparse.Namespace:
    """Accept a future round while preserving the round-one command."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--round", type=int, default=1, dest="round_number")
    parser.add_argument("--directory", type=Path)
    return parser.parse_args()


def main() -> int:
    """Package exactly 20 attempt-one drafts without altering any answer."""

    args = parse_args()
    if args.round_number < 1:
        raise SystemExit("round must be a positive integer")
    directory = args.directory or ROOT / "evals" / "forward" / f"round-{args.round_number}"
    requests_path = directory / "requests.jsonl"
    drafts_path = directory / "drafts.jsonl"
    output_path = directory / "candidates.jsonl"

    requests = [json.loads(line) for line in requests_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    drafts = [json.loads(line) for line in drafts_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(requests) != 20 or len(drafts) != 20:
        raise SystemExit(f"expected 20 requests and drafts, found {len(requests)} and {len(drafts)}")
    draft_by_id = {item["case_id"]: item for item in drafts}
    if len(draft_by_id) != 20:
        raise SystemExit("draft case identifiers are not unique")
    output = []
    for request in requests:
        case_id = request["case_id"]
        if request.get("round") != args.round_number or not case_id.startswith(f"FWD-R{args.round_number}-"):
            raise SystemExit(f"{case_id} does not belong to round {args.round_number}")
        draft = draft_by_id.get(case_id)
        if draft is None:
            raise SystemExit(f"missing draft for {case_id}")
        if set(draft) != {"case_id", "answer", "source_units", "support_map", "background_claims"}:
            raise SystemExit(f"{case_id} draft fields differ from the isolated generator contract")
        answer = draft["answer"]
        output.append(
            {
                "case_id": case_id,
                "round": args.round_number,
                "generation_attempt": 1,
                "status": "pending_user_review",
                "request_sha256": canonical_digest(request),
                "answer": answer,
                "answer_sha256": hashlib.sha256(answer.encode("utf-8")).hexdigest(),
                "source_units": draft["source_units"],
                "support_map": draft["support_map"],
                "background_claims": draft["background_claims"],
                "review": {"decision": "pending", "reasons": []},
            }
        )
    output_path.write_text("".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in output), encoding="utf-8", newline="\n")
    print(json.dumps({"status": "PASS", "round": args.round_number, "candidates": len(output), "answers_rewritten": 0}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
