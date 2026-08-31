"""Bind isolated round-one drafts to exact requests and immutable content digests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / "evals" / "forward" / "round-1"
REQUESTS = DIRECTORY / "requests.jsonl"
DRAFTS = DIRECTORY / "drafts.jsonl"
OUTPUT = DIRECTORY / "candidates.jsonl"


def canonical_digest(value: Any) -> str:
    """Hash one JSON value with stable UTF-8 encoding."""

    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def main() -> int:
    """Package drafts without altering any generated answer."""

    requests = [json.loads(line) for line in REQUESTS.read_text(encoding="utf-8").splitlines() if line.strip()]
    drafts = [json.loads(line) for line in DRAFTS.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(requests) != 20 or len(drafts) != 20:
        raise SystemExit(f"expected 20 requests and drafts, found {len(requests)} and {len(drafts)}")
    draft_by_id = {item["case_id"]: item for item in drafts}
    if len(draft_by_id) != 20:
        raise SystemExit("draft case identifiers are not unique")
    output = []
    for request in requests:
        case_id = request["case_id"]
        draft = draft_by_id.get(case_id)
        if draft is None:
            raise SystemExit(f"missing draft for {case_id}")
        if set(draft) != {"case_id", "answer", "source_units", "support_map", "background_claims"}:
            raise SystemExit(f"{case_id} draft fields differ from the isolated generator contract")
        answer = draft["answer"]
        output.append(
            {
                "case_id": case_id,
                "round": 1,
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
    OUTPUT.write_text("".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in output), encoding="utf-8", newline="\n")
    print(json.dumps({"status": "PASS", "candidates": len(output), "answers_rewritten": 0}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
