"""Rebuild every materialized forward-round artifact without inventing decisions."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FORWARD = ROOT / "evals" / "forward"


def run(*arguments: str) -> None:
    """Run one repository generator and preserve its failure status."""

    subprocess.run([sys.executable, *arguments], cwd=ROOT, check=True)


def main() -> int:
    """Rebuild declared rounds and replay only committed explicit-review ledgers."""

    rounds: list[int] = []
    for directory in sorted(FORWARD.glob("round-*")):
        match = re.fullmatch(r"round-([2-9][0-9]*)", directory.name)
        if match and (directory / "requests.jsonl").exists():
            rounds.append(int(match.group(1)))
    for round_number in rounds:
        if round_number == 2:
            run("scripts/build_forward_round2_requests.py")
        else:
            run("scripts/build_forward_round_requests.py", "--round", str(round_number))
        run("scripts/materialize_forward_round1.py", "--round", str(round_number))
        run("scripts/check_forward_candidates.py", "--round", str(round_number))
        closure = FORWARD / f"round-{round_number}" / "closure-results.jsonl"
        if not closure.exists():
            run("scripts/build_forward_review_packet.py", "--round", str(round_number))
            continue
        if round_number == 2:
            run("scripts/migrate_round2_preclosure.py")
        run("scripts/materialize_forward_lifecycle.py", "--round", str(round_number))
        review_root = FORWARD / f"round-{round_number}" / "reviews"
        source_ledger = review_root / "review-1-source.json"
        if source_ledger.exists():
            run("scripts/finalize_round2_review_ledger.py")
        for ledger in sorted(review_root.glob("review-*.json")):
            if ledger.name == "review-1.json" and source_ledger.exists():
                continue
            run("scripts/apply_forward_review.py", "--ledger", str(ledger))
        run("scripts/build_forward_review_packet.py", "--round", str(round_number))
    print(json.dumps({"status": "PASS", "rounds": rounds}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
