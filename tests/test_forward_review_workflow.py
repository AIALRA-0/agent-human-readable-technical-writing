"""Tests for complete, human-only forward review packets."""

from __future__ import annotations

import json
import hashlib
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import build_forward_review_packet as review_packet  # noqa: E402
from scripts import apply_forward_review  # noqa: E402
from scripts import build_forward_round_requests  # noqa: E402
from scripts import validate_vnext_lifecycle  # noqa: E402


class ForwardReviewPacketTests(unittest.TestCase):
    """Keep all findings and make review pages stable for Git and people."""

    def test_group_findings_keeps_multiple_rules_for_one_case(self) -> None:
        grouped = review_packet.group_findings(
            [
                {"case_id": "FWD-R2-001", "rule_id": "RULE-A"},
                {"case_id": "FWD-R2-001", "rule_id": "RULE-B"},
            ]
        )
        self.assertEqual([item["rule_id"] for item in grouped["FWD-R2-001"]], ["RULE-A", "RULE-B"])

    def test_review_view_removes_only_invisible_terminal_whitespace(self) -> None:
        self.assertEqual(review_packet.review_safe_markdown("甲  \n乙\t\n"), "甲\n乙\n")

    def test_main_builds_complete_packet_and_four_five_case_batches(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            requests = []
            candidates = []
            for number in range(1, 21):
                case_id = f"FWD-R2-{number:03d}"
                requests.append(
                    {
                        "case_id": case_id,
                        "base_operation": "explain",
                        "augmentation": "clarify",
                        "components": ["TEXT"],
                        "request": f"解释案例 {number}",
                        "source": {"material_type": "text", "content": f"材料 {number}  "},
                    }
                )
                candidates.append(
                    {
                        "case_id": case_id,
                        "answer": f"答案 {number}  ",
                        "answer_sha256": f"{number:064x}",
                    }
                )
            findings = {
                "findings": [
                    {"case_id": "FWD-R2-001", "rule_id": "RULE-A", "evidence": "发现 A"},
                    {"case_id": "FWD-R2-001", "rule_id": "RULE-B", "evidence": "发现 B"},
                ]
            }
            (directory / "requests.jsonl").write_text(
                "\n".join(json.dumps(item, ensure_ascii=False) for item in requests) + "\n", encoding="utf-8"
            )
            (directory / "candidates.jsonl").write_text(
                "\n".join(json.dumps(item, ensure_ascii=False) for item in candidates) + "\n", encoding="utf-8"
            )
            (directory / "deterministic-findings.json").write_text(
                json.dumps(findings, ensure_ascii=False), encoding="utf-8"
            )

            with patch.object(sys, "argv", ["build_forward_review_packet.py", "--round", "2", "--directory", str(directory)]):
                self.assertEqual(review_packet.main(), 0)

            complete = (directory / "REVIEW-PACKET.md").read_text(encoding="utf-8")
            self.assertIn("失败 `RULE-A`：发现 A", complete)
            self.assertIn("失败 `RULE-B`：发现 B", complete)
            self.assertEqual(complete.count("## "), 20)
            self.assertFalse(any(line.endswith((" ", "\t")) for line in complete.splitlines()))
            batches = sorted((directory / "review-batches").glob("BATCH-*.md"))
            self.assertEqual(len(batches), 4)
            self.assertTrue(all(path.read_text(encoding="utf-8").count("## ") == 5 for path in batches))
            self.assertTrue((directory / "review-batches" / "INDEX.md").exists())


class ForwardReviewApplicationTests(unittest.TestCase):
    """Require explicit, digest-bound decisions and sequential revisions."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.lifecycle = self.root / "evals" / "forward" / "round-2" / "lifecycle"
        for status in ("candidate", "gold", "rejected"):
            (self.lifecycle / status).mkdir(parents=True)
        source_path = ROOT / "evals" / "forward" / "round-2" / "lifecycle" / "candidate" / "CANDIDATE-FWD-R2-021-R1.json"
        self.source = json.loads(source_path.read_text(encoding="utf-8"))
        self.candidate_path = self.lifecycle / "candidate" / source_path.name
        self.candidate_path.write_text(json.dumps(self.source, ensure_ascii=False), encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def ledger(self, decision: str, *, answer: str | None = None) -> dict[str, object]:
        answer_hash = self.source["artifact"]["answer_sha256"]
        rejected = decision == "rejected"
        next_answer = answer or self.source["artifact"]["answer"].replace("。", "")
        return {
            "review_id": "forward-round-2-review-1",
            "forward_round": 2,
            "review_iteration": 1,
            "reviewed_at": "2026-09-01",
            "decision_source": "explicit_user_review",
            "profile_revision_at_review": "round-5-inline-alignment-aemp",
            "privacy": {"status": "public_safe", "basis": "合成评测反馈"},
            "decisions": [
                {
                    "reviewed_candidate_id": "CANDIDATE-FWD-R2-021-R1",
                    "reviewed_answer_sha256": answer_hash,
                    "decision": decision,
                    "user_instruction": "接受" if not rejected else "拒绝中文句号，其他内容保留",
                    "reasons": [] if not rejected else ["生成正文含中文句号"],
                    "correct_parts": [] if not rejected else ["事实和数字保持不变"],
                    "regression_requirements": [] if not rejected else ["只移除中文句号"],
                    "non_blocking_preferences": [],
                    "resulting_record_id": "GOLD-FWD-R2-021" if not rejected else "REJECTED-FWD-R2-021",
                    "next_candidate": None
                    if not rejected
                    else {
                        "candidate_id": "CANDIDATE-FWD-R2-021-R2",
                        "answer": next_answer,
                        "answer_sha256": hashlib.sha256(next_answer.encode("utf-8")).hexdigest(),
                    },
                }
            ],
        }

    def apply_planned(self, ledger: dict[str, object]) -> None:
        operations, removals, already = apply_forward_review.plan_operations(ledger, self.root)
        self.assertEqual(already, [])
        for operation in operations:
            apply_forward_review.atomic_write_json(operation.path, operation.value)
        for path in removals:
            path.unlink()

    def test_acceptance_preserves_exact_answer_and_becomes_idempotent(self) -> None:
        ledger = self.ledger("accepted")
        self.apply_planned(ledger)
        gold_path = self.lifecycle / "gold" / "GOLD-FWD-R2-021.json"
        gold = json.loads(gold_path.read_text(encoding="utf-8"))
        self.assertEqual(gold["artifact"]["answer"], self.source["artifact"]["answer"])
        self.assertEqual(gold["review"]["decision_source"], "explicit_user_review")
        operations, removals, already = apply_forward_review.plan_operations(ledger, self.root)
        self.assertEqual((operations, removals), ([], []))
        self.assertEqual(already, ["CANDIDATE-FWD-R2-021-R1"])

    def test_rejection_creates_rejected_snapshot_and_pending_next_revision(self) -> None:
        ledger = self.ledger("rejected")
        self.apply_planned(ledger)
        rejected = json.loads((self.lifecycle / "rejected" / "REJECTED-FWD-R2-021.json").read_text(encoding="utf-8"))
        revised = json.loads((self.lifecycle / "candidate" / "CANDIDATE-FWD-R2-021-R2.json").read_text(encoding="utf-8"))
        self.assertEqual(rejected["artifact"]["answer"], self.source["artifact"]["answer"])
        self.assertEqual(revised["artifact"]["revision_of"], "REJECTED-FWD-R2-021")
        self.assertEqual(revised["review"]["decision"], "pending")
        self.assertEqual(revised["source"]["revision_references"][-1]["kind"], "explicit_user_review")

    def test_digest_mismatch_fails_before_any_write(self) -> None:
        ledger = self.ledger("accepted")
        ledger["decisions"][0]["reviewed_answer_sha256"] = "0" * 64
        with self.assertRaisesRegex(apply_forward_review.ReviewApplicationError, "digest differs"):
            apply_forward_review.plan_operations(ledger, self.root)
        self.assertTrue(self.candidate_path.exists())
        self.assertEqual(list((self.lifecycle / "gold").glob("*.json")), [])


class ForwardRoundRequestTests(unittest.TestCase):
    """Keep every later round broad, unique, and closed behind human review."""

    def test_round_three_and_four_are_unique_and_cover_required_distributions(self) -> None:
        rows = build_forward_round_requests.build_rows(3) + build_forward_round_requests.build_rows(4)
        self.assertEqual(len(rows), 40)
        self.assertEqual(len({item["topic_id"] for item in rows}), 40)
        self.assertEqual(len({tuple(sorted(item["core_terms"])) for item in rows}), 40)
        self.assertEqual(len({build_forward_round_requests.digest({"source": item["source"]["content"], "references": item["references"]}) for item in rows}), 40)
        for round_number in (3, 4):
            selected = [item for item in rows if item["round"] == round_number]
            self.assertEqual({name: sum(item["length_class"] == name for item in selected) for name in build_forward_round_requests.RANGES}, {name: 4 for name in build_forward_round_requests.RANGES})
            self.assertEqual(max(item["input_char_count"] for item in selected) >= 2800, True)

    def test_round_three_gate_is_closed_while_round_two_has_candidates(self) -> None:
        with self.assertRaisesRegex(SystemExit, "gated until every round 2 revision"):
            build_forward_round_requests.check_gate(3, False)

    def test_dynamic_streak_requires_two_later_perfect_rounds_after_a_failed_round(self) -> None:
        records: dict[str, dict[str, object]] = {}

        def add(round_number: int, number: int, revision: int, status: str) -> None:
            origin = f"FWD-R{round_number}-{(round_number - 1) * 20 + number:03d}"
            prefix = {"gold": "GOLD", "rejected": "REJECTED", "candidate": "CANDIDATE"}[status]
            suffix = "" if revision == 1 and status != "candidate" else f"-R{revision}"
            case_id = f"{prefix}-{origin}{suffix}"
            records[case_id] = {"identity": {"case_id": case_id, "origin_case_id": origin, "revision": revision, "status": status}}

        for number in range(1, 21):
            if number == 1:
                add(2, number, 1, "rejected")
                add(2, number, 2, "gold")
            else:
                add(2, number, 1, "gold")
        for round_number in (3, 4):
            for number in range(1, 21):
                add(round_number, number, 1, "gold")

        failures: list[str] = []
        state = validate_vnext_lifecycle.validate_revision_chains(records, failures)
        self.assertEqual(failures, [])
        report = validate_vnext_lifecycle.build_report(
            [], Counter({"gold": 91, "rejected": 31}), [], Counter({"accepted": 60, "rejected": 1}), state
        )
        self.assertEqual(state[2]["r1_accepted"], 19)
        self.assertEqual(report["perfect_round_streak"], {"current": 2, "required": 2, "release_gate_met": True})
        self.assertFalse(report["next_round_allowed"])


if __name__ == "__main__":
    unittest.main()
