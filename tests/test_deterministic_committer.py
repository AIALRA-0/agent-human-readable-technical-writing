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
    apply_minimal_transaction,
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

    def test_same_text_in_two_nodes_can_be_patched_in_only_one_node(self) -> None:
        text = "lockout\nlockout\n"
        nodes = {"LINE-0001": (0, 8), "LINE-0002": (8, len(text))}
        patch = make_patch(
            text,
            patch_id="PATCH-LOCAL",
            node_id="LINE-0001",
            old_text="lockout",
            new_text="Lockout",
        )
        self.assertEqual(apply_transaction(text, [patch], nodes), "Lockout\nlockout\n")

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

    def test_exact_deletion_is_allowed_inside_authorized_node(self) -> None:
        patch = make_patch(
            self.text,
            patch_id="PATCH-013",
            node_id="SEG-01",
            old_text="旧术语",
            new_text="",
        )
        result = apply_transaction(self.text, [patch], self.nodes)
        self.assertNotIn("旧术语", result)
        self.assertIn("第二段不应改变", result)

    def test_unknown_node_rejects_patch(self) -> None:
        patch = make_patch(
            self.text,
            patch_id="PATCH-014",
            node_id="SEG-99",
            old_text="旧术语",
            new_text="登记术语",
        )
        with self.assertRaisesRegex(PatchError, "unknown node_id"):
            apply_transaction(self.text, [patch], self.nodes)

    def test_invalid_node_range_rejects_patch(self) -> None:
        patch = make_patch(
            self.text,
            patch_id="PATCH-015",
            node_id="SEG-01",
            old_text="旧术语",
            new_text="登记术语",
        )
        invalid_nodes = dict(self.nodes)
        invalid_nodes["SEG-01"] = (-1, self.second_start)
        with self.assertRaisesRegex(PatchError, "invalid node range"):
            apply_transaction(self.text, [patch], invalid_nodes)

    def test_unsupported_operation_rejects_patch(self) -> None:
        patch = make_patch(
            self.text,
            patch_id="PATCH-016",
            node_id="SEG-01",
            old_text="旧术语",
            new_text="登记术语",
        )
        patch["identity"]["operation"] = "replace_regex"
        with self.assertRaisesRegex(PatchError, "unsupported operation"):
            apply_transaction(self.text, [patch], self.nodes)

    def test_empty_old_text_rejects_patch(self) -> None:
        patch = make_patch(
            self.text,
            patch_id="PATCH-017",
            node_id="SEG-01",
            old_text="旧术语",
            new_text="登记术语",
        )
        patch["replacement"]["old_text"] = ""
        with self.assertRaisesRegex(PatchError, "old_text must be non-empty"):
            apply_transaction(self.text, [patch], self.nodes)

    def test_non_text_new_value_rejects_patch(self) -> None:
        patch = make_patch(
            self.text,
            patch_id="PATCH-018",
            node_id="SEG-01",
            old_text="旧术语",
            new_text="登记术语",
        )
        patch["replacement"]["new_text"] = 42
        with self.assertRaisesRegex(PatchError, "new_text must be text"):
            apply_transaction(self.text, [patch], self.nodes)

    def test_boolean_occurrence_count_rejects_patch(self) -> None:
        patch = make_patch(
            self.text,
            patch_id="PATCH-019",
            node_id="SEG-01",
            old_text="旧术语",
            new_text="登记术语",
        )
        patch["replacement"]["expected_occurrences"] = True
        with self.assertRaisesRegex(PatchError, "positive integer"):
            apply_transaction(self.text, [patch], self.nodes)

    def test_empty_validator_list_rejects_patch(self) -> None:
        patch = make_patch(
            self.text,
            patch_id="PATCH-020",
            node_id="SEG-01",
            old_text="旧术语",
            new_text="登记术语",
        )
        patch["verification"]["rerun_validators"] = []
        with self.assertRaisesRegex(PatchError, "non-empty list"):
            apply_transaction(self.text, [patch], self.nodes)

    def test_self_iterative_repair_rejects_section_scope(self) -> None:
        """The closure path cannot replace a section to hide one local failure."""

        patch = make_patch(
            self.text, patch_id="PATCH-021", node_id="SEG-01",
            old_text="旧术语", new_text="登记术语",
        )
        patch["authorization"]["repair_scope"] = "section"
        with self.assertRaisesRegex(PatchError, "scope is too broad"):
            apply_minimal_transaction(self.text, [patch], self.nodes)

    def test_self_iterative_repair_rejects_noop(self) -> None:
        """A no-op cannot consume one of the three repair rounds."""

        patch = make_patch(
            self.text, patch_id="PATCH-022", node_id="SEG-01",
            old_text="旧术语", new_text="旧术语",
        )
        with self.assertRaisesRegex(PatchError, "no-op patch"):
            apply_minimal_transaction(self.text, [patch], self.nodes)

    def test_self_iterative_repair_rejects_empty_batch(self) -> None:
        """An empty patch round cannot be recorded as progress."""

        with self.assertRaisesRegex(PatchError, "at least one patch"):
            apply_minimal_transaction(self.text, [], self.nodes)


if __name__ == "__main__":
    unittest.main()
