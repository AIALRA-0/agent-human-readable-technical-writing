"""Create pending lifecycle records from one immutable first-attempt round."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MODEL_CODES = {"gpt-5.6-sol": "SOL", "gpt-5.6-terra": "TERRA", "gpt-5.6-luna": "LUNA"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--round", type=int, required=True, dest="round_number")
    return parser.parse_args()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def digest_json(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def main() -> int:
    args = parse_args()
    if args.round_number < 2:
        raise SystemExit("pending first-attempt lifecycle materialization is only valid for round 2 or later")
    directory = ROOT / "evals" / "forward" / f"round-{args.round_number}"
    requests = {item["case_id"]: item for item in read_jsonl(directory / "requests.jsonl")}
    closure_path = directory / "closure-results.jsonl"
    if len(requests) != 20:
        raise SystemExit("expected exactly 20 immutable requests")
    if not closure_path.exists():
        raise SystemExit("self-iterative closure results are required before lifecycle materialization")
    candidates = read_jsonl(closure_path)
    if len(candidates) != 60:
        raise SystemExit("expected exactly 60 three-model closure results")
    if any(item.get("status") != "PASS" for item in candidates):
        raise SystemExit("only completed closure results can become review candidates")
    lifecycle = directory / "lifecycle"
    target = lifecycle / "candidate"
    target.mkdir(parents=True, exist_ok=True)
    for name in ("gold", "rejected"):
        (lifecycle / name).mkdir(parents=True, exist_ok=True)
    created = 0
    existing = 0
    for candidate in candidates:
        origin = candidate["case_id"]
        request = requests.get(origin)
        if request is None:
            raise SystemExit(f"missing request for {origin}")
        model = candidate["model"]
        model_code = MODEL_CODES.get(model)
        if model_code is None:
            raise SystemExit(f"unsupported closure model: {model}")
        model_records = []
        for path in lifecycle.rglob("*.json"):
            current = json.loads(path.read_text(encoding="utf-8"))
            if current["identity"]["origin_case_id"] == origin and current["identity"].get("model") == model:
                model_records.append(current)
        revision = max((item["identity"]["revision"] for item in model_records), default=0) + 1
        if model_records:
            latest = max(model_records, key=lambda item: item["identity"]["revision"])
            if latest["identity"]["status"] == "candidate":
                expected_id = f"CANDIDATE-{origin}-{model_code}-R{latest['identity']['revision']}"
                if latest["identity"]["case_id"] != expected_id or latest["artifact"]["answer_sha256"] != candidate["final_sha256"]:
                    raise SystemExit(f"{origin} {model_code}: existing candidate differs from closure result")
                existing += 1
                continue
            if latest["identity"]["status"] != "rejected":
                raise SystemExit(f"{origin} {model_code}: accepted chain cannot create another candidate")
        record_id = f"CANDIDATE-{origin}-{model_code}-R{revision}"
        filename = record_id + ".json"
        parent = max(model_records, key=lambda item: item["identity"]["revision"])["identity"]["case_id"] if model_records else None
        references = []
        if model_records:
            latest = max(model_records, key=lambda item: item["identity"]["revision"])
            references.append({
                "id": latest["identity"]["case_id"], "kind": "explicit_user_review",
                "content": "；".join(latest["review"]["reasons"]),
            })
        record = {
            "identity": {
                "case_id": record_id,
                "origin_case_id": origin,
                "model": model,
                "status": "candidate",
                "revision": revision,
                "approved_by_user": False,
                "reviewed_at": None,
                "profile_revision_at_review": None,
            },
            "task": request,
            "source": {
                "original_request_sha256": digest_json(request),
                "original_answer_sha256": candidate["first_draft_sha256"],
                "source_units": candidate["source_units"],
                "support_map": candidate["support_map"],
                "background_claims": candidate["background_claims"],
                "revision_references": references,
            },
            "artifact": {
                "answer": candidate["answer"],
                "answer_sha256": candidate["final_sha256"],
                "approved_snapshot_sha256": None,
                "revision_of": parent,
                "closure": candidate["iterations"],
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
        created += 1
    print(json.dumps({"status": "PASS", "round": args.round_number, "created": created, "existing_closed_candidates": existing}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
