"""Checks for the recoverable round-two legacy-review finalizer."""

from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import finalize_round2_review_ledger as finalizer


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


class RoundTwoReviewFinalizerTests(unittest.TestCase):
    def source(self) -> dict[str, object]:
        return {
            "reviewed_at": "2026-09-01",
            "profile_revision_at_review": "round-6-self-iterative-cross-model",
            "decisions": [{
                "origin_case_id": "FWD-R2-021",
                "instruction": "修复标点",
                "reasons": ["标点错误"],
                "correct_parts": ["保留数字"],
                "regressions": ["只改标点"],
            }],
        }

    def test_missing_successor_returns_structured_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write(root / "reviews" / "review-1-source.json", self.source())
            with patch.object(finalizer, "ROUND", root):
                ledger, missing = finalizer.build_ledger()
            self.assertIsNone(ledger)
            self.assertEqual(len(missing), 2)

    def test_apply_writes_canonical_ledger_and_removes_temporary_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_path = root / "reviews" / "review-1-source.json"
            write(source_path, self.source())
            write(root / "lifecycle" / "rejected" / "REJECTED-FWD-R2-021-SOL.json", {
                "artifact": {"answer_sha256": "a" * 64},
            })
            write(root / "lifecycle" / "candidate" / "CANDIDATE-FWD-R2-021-SOL-R2.json", {
                "identity": {"case_id": "CANDIDATE-FWD-R2-021-SOL-R2"},
                "artifact": {"answer": "修复后答案", "answer_sha256": "b" * 64},
            })
            with (
                patch.object(finalizer, "ROUND", root),
                patch.object(finalizer, "parse_args", return_value=argparse.Namespace(check=False)),
            ):
                self.assertEqual(finalizer.main(), 0)
                self.assertEqual(finalizer.main(), 0)
            self.assertFalse(source_path.exists())
            ledger = json.loads((root / "reviews" / "review-1.json").read_text(encoding="utf-8"))
            self.assertEqual(ledger["decisions"][0]["decision"], "rejected")
            self.assertFalse(ledger.get("automated_checks_are_user_acceptance", False))


if __name__ == "__main__":
    unittest.main()
