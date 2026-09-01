"""Apply explicit forward-review decisions without treating automation as acceptance."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "contracts" / "forward-review-ledger.schema.json"


class ReviewApplicationError(RuntimeError):
    """Represent a ledger, digest, transition, or idempotency defect."""


@dataclass(frozen=True)
class WriteOperation:
    """Describe one validated lifecycle write."""

    path: Path
    value: dict[str, Any]


def digest(text: str) -> str:
    """Return the repository UTF-8 digest."""

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    """Read one UTF-8 JSON object."""

    return json.loads(path.read_text(encoding="utf-8"))


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    """Replace one JSON file atomically within its destination directory."""

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    handle, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as temporary:
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def record_id(origin: str, revision: int, status: str) -> str:
    """Derive the only legal terminal identifier for one reviewed revision."""

    prefix = "GOLD" if status == "accepted" else "REJECTED"
    suffix = "" if revision == 1 else f"-R{revision}"
    return f"{prefix}-{origin}{suffix}"


def validate_ledger(ledger: dict[str, Any]) -> None:
    """Validate schema and cross-field uniqueness before touching lifecycle files."""

    schema = read_json(SCHEMA)
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(ledger)
    expected_review_id = f"forward-round-{ledger['forward_round']}-review-{ledger['review_iteration']}"
    if ledger["review_id"] != expected_review_id:
        raise ReviewApplicationError("review_id differs from round and iteration")
    candidate_ids = [item["reviewed_candidate_id"] for item in ledger["decisions"]]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ReviewApplicationError("one ledger cannot decide the same candidate twice")
    marker = f"CANDIDATE-FWD-R{ledger['forward_round']}-"
    if any(not candidate_id.startswith(marker) for candidate_id in candidate_ids):
        raise ReviewApplicationError("one decision belongs to a different forward round")


def terminal_record(source: dict[str, Any], decision: dict[str, Any], ledger: dict[str, Any]) -> dict[str, Any]:
    """Create the exact Gold or Rejected record for a reviewed answer."""

    result = copy.deepcopy(source)
    status = "gold" if decision["decision"] == "accepted" else "rejected"
    result["identity"].update(
        {
            "case_id": decision["resulting_record_id"],
            "status": status,
            "approved_by_user": status == "gold",
            "reviewed_at": ledger["reviewed_at"],
            "profile_revision_at_review": ledger["profile_revision_at_review"],
        }
    )
    answer_hash = digest(result["artifact"]["answer"])
    result["artifact"]["answer_sha256"] = answer_hash
    result["artifact"]["approved_snapshot_sha256"] = answer_hash if status == "gold" else None
    result["review"].update(
        {
            "decision_source": "explicit_user_review",
            "decision": decision["decision"],
            "reasons": decision["reasons"] or [decision["user_instruction"]],
            "correct_parts": decision["correct_parts"],
            "regression_requirements": decision["regression_requirements"],
            "non_blocking_preferences": decision["non_blocking_preferences"],
        }
    )
    return result


def revised_candidate(source: dict[str, Any], decision: dict[str, Any], ledger: dict[str, Any]) -> dict[str, Any]:
    """Create one pending revision that cites the explicit rejection."""

    revision = source["identity"]["revision"] + 1
    specification = decision["next_candidate"]
    if specification is None:
        raise ReviewApplicationError("rejected decision has no next candidate")
    result = copy.deepcopy(source)
    result["identity"].update(
        {
            "case_id": specification["candidate_id"],
            "status": "candidate",
            "revision": revision,
            "approved_by_user": False,
            "reviewed_at": None,
            "profile_revision_at_review": None,
        }
    )
    result["source"]["revision_references"].append(
        {
            "id": ledger["review_id"],
            "kind": "explicit_user_review",
            "content": decision["user_instruction"],
        }
    )
    result["artifact"].update(
        {
            "answer": specification["answer"],
            "answer_sha256": specification["answer_sha256"],
            "approved_snapshot_sha256": None,
            "revision_of": decision["resulting_record_id"],
        }
    )
    result["review"].update(
        {
            "decision_source": "pending_user_review",
            "decision": "pending",
            "reasons": [],
            "correct_parts": [],
            "regression_requirements": [],
            "non_blocking_preferences": [],
        }
    )
    return result


def plan_operations(ledger: dict[str, Any], root: Path = ROOT) -> tuple[list[WriteOperation], list[Path], list[str]]:
    """Validate every decision and return all writes before performing any of them."""

    validate_ledger(ledger)
    round_number = ledger["forward_round"]
    lifecycle = root / "evals" / "forward" / f"round-{round_number}" / "lifecycle"
    operations: list[WriteOperation] = []
    removals: list[Path] = []
    already_applied: list[str] = []
    target_paths: set[Path] = set()
    for decision in ledger["decisions"]:
        candidate_path = lifecycle / "candidate" / f"{decision['reviewed_candidate_id']}.json"
        match = decision["reviewed_candidate_id"].rsplit("-R", 1)
        if len(match) != 2:
            raise ReviewApplicationError(f"invalid candidate revision: {decision['reviewed_candidate_id']}")
        revision = int(match[1])
        origin = decision["reviewed_candidate_id"][len("CANDIDATE-") :].rsplit("-R", 1)[0]
        expected_result = record_id(origin, revision, decision["decision"])
        if decision["resulting_record_id"] != expected_result:
            raise ReviewApplicationError(f"{decision['reviewed_candidate_id']}: resulting record id differs from decision")
        result_status = "gold" if decision["decision"] == "accepted" else "rejected"
        result_path = lifecycle / result_status / f"{expected_result}.json"

        if not candidate_path.exists():
            if not result_path.exists():
                raise ReviewApplicationError(f"missing reviewed candidate: {candidate_path.name}")
            existing = read_json(result_path)
            if existing["artifact"]["answer_sha256"] != decision["reviewed_answer_sha256"]:
                raise ReviewApplicationError(f"{expected_result}: existing result digest differs")
            if decision["decision"] == "rejected":
                specification = decision["next_candidate"]
                next_path = lifecycle / "candidate" / f"{specification['candidate_id']}.json"
                if not next_path.exists() or read_json(next_path)["artifact"]["answer_sha256"] != specification["answer_sha256"]:
                    raise ReviewApplicationError(f"{expected_result}: partially applied rejection")
            already_applied.append(decision["reviewed_candidate_id"])
            continue

        source = read_json(candidate_path)
        if source["identity"]["status"] != "candidate" or source["review"]["decision"] != "pending":
            raise ReviewApplicationError(f"{candidate_path.name}: source is not pending user review")
        answer_hash = digest(source["artifact"]["answer"])
        if answer_hash != source["artifact"]["answer_sha256"] or answer_hash != decision["reviewed_answer_sha256"]:
            raise ReviewApplicationError(f"{candidate_path.name}: reviewed answer digest differs")
        if result_path.exists():
            raise ReviewApplicationError(f"refusing to overwrite existing result: {result_path.name}")

        terminal = terminal_record(source, decision, ledger)
        operations.append(WriteOperation(result_path, terminal))
        target_paths.add(result_path)
        if decision["decision"] == "rejected":
            specification = decision["next_candidate"]
            if digest(specification["answer"]) != specification["answer_sha256"]:
                raise ReviewApplicationError(f"{candidate_path.name}: next candidate digest differs")
            expected_next = f"CANDIDATE-{origin}-R{revision + 1}"
            if specification["candidate_id"] != expected_next:
                raise ReviewApplicationError(f"{candidate_path.name}: next candidate revision is not sequential")
            next_path = lifecycle / "candidate" / f"{expected_next}.json"
            if next_path.exists() or next_path in target_paths:
                raise ReviewApplicationError(f"refusing to overwrite next candidate: {next_path.name}")
            operations.append(WriteOperation(next_path, revised_candidate(source, decision, ledger)))
            target_paths.add(next_path)
        removals.append(candidate_path)
    return operations, removals, already_applied


def parse_args() -> argparse.Namespace:
    """Read one committed ledger and optionally perform a no-write preflight."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    """Apply a validated ledger after all decisions pass preflight."""

    args = parse_args()
    ledger = read_json(args.ledger)
    operations, removals, already_applied = plan_operations(ledger)
    if not args.dry_run:
        for operation in operations:
            atomic_write_json(operation.path, operation.value)
        for path in removals:
            path.unlink()
    print(
        json.dumps(
            {
                "status": "PASS",
                "mode": "dry_run" if args.dry_run else "applied",
                "review_id": ledger["review_id"],
                "writes": [str(item.path.relative_to(ROOT)).replace("\\", "/") for item in operations],
                "removals": [str(path.relative_to(ROOT)).replace("\\", "/") for path in removals],
                "already_applied": already_applied,
                "automated_checks_are_user_acceptance": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
