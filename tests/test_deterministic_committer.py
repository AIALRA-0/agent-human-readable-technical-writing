"""Tests for exact replacement, conflict rejection, and transactional safety."""

from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from patcher.deterministic_committer import (  # noqa: E402
    PatchError,
    apply_transaction,
    commit_document,
    sha256_text,
)


def make_patch(
    text: str,
    *,
    patch_id: str,
    node_id: str,
    old_text: str,
    new_text: str,
    expected_occurrences: int = 1,
) -> dict[str, object]:
    """Build one complete grouped patch contract for a test document."""

    return {
        "identity": {
            "patch_id": patch_id,
            "finding_id": f"TEST-{patch_id}",
            "operation": "replace_exact",
        },
        "target": {"document_sha256": sha256_text(text), "node_id": node_id},
        "replacement": {
            "old_text": old_text,
            "new_text": new_text,
            "expected_occurrences": expected_occurrences,
        },
        "authorization": {
            "reason": "测试精确替换",
            "repair_scope": "phrase",
            "preserve": ["非目标文本保持不变"],
        },
        "verification": {"rerun_validators": ["test_validator"]},
    }


class DeterministicCommitterTests(unittest.TestCase):
    """Prove that accepted edits are exact and rejected batches do not write."""

    def setUp(self) -> None:
        self.text = "SEG-01\n旧术语保持含义\nSEG-02\n第二段不应改变\n"
        self.first_start = self.text.index("旧术语")
        self.second_start = self.text.index("第二段")
        self.nodes = {
            "SEG-01": (0, self.second_start),
            "SEG-02": (self.second_start, len(self.text)),
        }

    def test_exact_patch_changes_only_authorized_text(self) -> None:
        patch = make_patch(
            self.text,
            patch_id="PATCH-001",
            node_id="SEG-01",
            old_text="旧术语",
            new_text="登记术语",
        )
        result = apply_transaction(self.text, [patch], self.nodes)
        self.assertEqual(result, self.text.replace("旧术语", "登记术语"))
        self.assertIn("第二段不应改变", result)

    def test_hash_mismatch_rejects_patch(self) -> None:
        patch = make_patch(
            self.text,
            patch_id="PATCH-002",
            node_id="SEG-01",
            old_text="旧术语",
            new_text="登记术语",
        )
        patch["target"]["document_sha256"] = "0" * 64
        with self.assertRaisesRegex(PatchError, "hash mismatch"):
            apply_transaction(self.text, [patch], self.nodes)

    def test_missing_authorization_rejects_patch(self) -> None:
        patch = make_patch(
            self.text,
            patch_id="PATCH-012",
            node_id="SEG-01",
            old_text="旧术语",
            new_text="登记术语",
        )
        del patch["authorization"]
        with self.assertRaisesRegex(PatchError, "authorization must be an object"):
            apply_transaction(self.text, [patch], self.nodes)

    def test_occurrence_count_mismatch_rejects_patch(self) -> None:
        patch = make_patch(
            self.text,
            patch_id="PATCH-003",
            node_id="SEG-01",
            old_text="旧术语",
            new_text="登记术语",
            expected_occurrences=2,
        )
        with self.assertRaisesRegex(PatchError, "expected 2 occurrence"):
            apply_transaction(self.text, [patch], self.nodes)

    def test_text_outside_node_rejects_patch(self) -> None:
        patch = make_patch(
            self.text,
            patch_id="PATCH-004",
            node_id="SEG-01",
            old_text="第二段",
            new_text="其他段",
        )
        with self.assertRaisesRegex(PatchError, "outside the authorized node"):
            apply_transaction(self.text, [patch], self.nodes)

    def test_overlapping_patches_reject_entire_batch(self) -> None:
        patch_a = make_patch(
            self.text,
            patch_id="PATCH-005",
            node_id="SEG-01",
            old_text="旧术语保持",
            new_text="登记术语保留",
        )
        patch_b = make_patch(
            self.text,
            patch_id="PATCH-006",
            node_id="SEG-01",
            old_text="术语保持含义",
            new_text="术语保留含义",
        )
        with self.assertRaisesRegex(PatchError, "overlapping patches"):
            apply_transaction(self.text, [patch_a, patch_b], self.nodes)

    def test_non_overlapping_patches_commit_together(self) -> None:
        patch_a = make_patch(
            self.text,
            patch_id="PATCH-007",
            node_id="SEG-01",
            old_text="旧术语",
            new_text="登记术语",
        )
        patch_b = make_patch(
            self.text,
            patch_id="PATCH-008",
            node_id="SEG-02",
            old_text="第二段",
            new_text="后续段",
        )
        result = apply_transaction(self.text, [patch_a, patch_b], self.nodes)
        self.assertIn("登记术语保持含义", result)
        self.assertIn("后续段不应改变", result)

    def test_validator_failure_keeps_file_unchanged(self) -> None:
        patch = make_patch(
            self.text,
            patch_id="PATCH-009",
            node_id="SEG-01",
            old_text="旧术语",
            new_text="登记术语",
        )

        def failing_validator(_: str) -> list[str]:
            return ["模拟全文检查失败"]

        with tempfile.TemporaryDirectory() as directory:
            document = Path(directory) / "document.md"
            document.write_text(self.text, encoding="utf-8")
            before = document.read_bytes()
            with self.assertRaisesRegex(PatchError, "validator failure"):
                commit_document(document, [patch], self.nodes, [failing_validator])
            self.assertEqual(document.read_bytes(), before)

    def test_successful_file_commit_returns_new_hash(self) -> None:
        patch = make_patch(
            self.text,
            patch_id="PATCH-010",
            node_id="SEG-01",
            old_text="旧术语",
            new_text="登记术语",
        )
        with tempfile.TemporaryDirectory() as directory:
            document = Path(directory) / "document.md"
            document.write_text(self.text, encoding="utf-8")
            new_hash = commit_document(document, [patch], self.nodes)
            result = document.read_text(encoding="utf-8")
            self.assertEqual(new_hash, sha256_text(result))
            self.assertIn("登记术语保持含义", result)

    def test_input_patch_is_not_mutated(self) -> None:
        patch = make_patch(
            self.text,
            patch_id="PATCH-011",
            node_id="SEG-01",
            old_text="旧术语",
            new_text="登记术语",
        )
        original_patch = copy.deepcopy(patch)
        apply_transaction(self.text, [patch], self.nodes)
        self.assertEqual(patch, original_patch)


if __name__ == "__main__":
    unittest.main()
