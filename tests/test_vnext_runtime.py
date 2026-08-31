"""Smoke tests for the executable vNext compiler and structural verifier."""

from __future__ import annotations

import copy
import hashlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from runtime.engine import compile_contract, verify_bundle  # noqa: E402


class VNextRuntimeTests(unittest.TestCase):
    """Prove the runtime enforces deterministic contracts without semantic guessing."""

    def build_bundle(self) -> dict:
        """Create one minimal fully traceable transform bundle."""

        text = "任务已接收"
        contract = compile_contract({
            "task_id": "TASK-TEST-001", "base_operation": "TRANSFORM", "augmentation": "NONE",
            "audience": "general_reader", "genre": "status", "media": ["chat"], "components": ["TEXT"],
        })
        return {
            "task_contract": contract,
            "source_spans": [{
                "identity": {"source_span_id": "SRC-001", "source_id": "SOURCE-1"},
                "location": {"locator": "第 1 句"},
                "content": {"text": text, "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()},
                "protection": {"protected_tokens": []},
            }],
            "source_presentations": [],
            "source_atoms": [{
                "identity": {"atom_id": "ATOM-001"}, "provenance": {"provenance_type": "SOURCE"},
                "meaning": {"claim": "任务已经接收", "subject": "任务", "predicate": "接收", "modality": "ASSERTED"},
                "source_linkage": {"source_span_id": "SRC-001"},
                "preservation": {"required": True, "protected_relations": ["SUBJECT", "MODALITY"]},
            }],
            "background_atoms": [], "inference_atoms": [],
            "segment_contracts": [{
                "identity": {"segment_id": "SEG-01"}, "purpose": {"reader_task": "确认任务状态"},
                "coverage": {"source_atoms": ["ATOM-001"], "background_atoms": [], "inference_atoms": []},
                "claims": {"must_claim": ["任务已经接收"], "must_not_claim": ["任务已经完成"]},
                "ordering": {"preferred_order": ["说明任务已经接收"]},
            }],
            "support_maps": [{
                "identity": {"mapping_id": "MAP-001"},
                "target": {"sentence_id": "SENT-001", "segment_id": "SEG-01"},
                "support": {"atom_ids": ["ATOM-001"]},
                "roles": {"values": ["source_restatement"]},
            }],
            "term_uses": [], "component_coverage": [], "boundary_coverage": [],
            "rendered_document": {
                "text": text, "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "sentences": [{
                    "sentence_id": "SENT-001", "text": text, "verbatim": False,
                    "actor_clarity": {"status": "explicit", "actor": "任务", "basis": "句子直接说明任务状态"},
                }],
            },
        }

    def test_compile_resets_standalone_terms(self) -> None:
        """Independent tasks cannot borrow terminology from another test."""

        contract = compile_contract({
            "task_id": "TASK-TEST-002", "base_operation": "TRANSFORM", "augmentation": "NONE",
            "audience": "general_reader", "genre": "status", "media": ["chat"], "components": ["TEXT"],
            "known_terms": ["HTTP"],
        })
        self.assertEqual([], contract["terminology"]["known_terms"])

    def test_valid_bundle_passes(self) -> None:
        """A complete source-to-sentence mapping reaches human review."""

        self.assertEqual("PASS", verify_bundle(self.build_bundle())["status"])

    def test_compile_records_round_two_presentation(self) -> None:
        """The compiler exposes renderer limits instead of claiming universal centering."""

        contract = compile_contract({
            "task_id": "TASK-TEST-003", "base_operation": "EXPLAIN", "augmentation": "GLOSS",
            "audience": "general_reader", "genre": "readme", "media": ["github_markdown"],
            "components": ["TEXT", "IMAGE"],
        })
        self.assertEqual("round-2-feedback", contract["identity"]["profile_revision"])
        self.assertFalse(contract["presentation"]["renderer"]["exact_object_alignment"])
        self.assertEqual("center", contract["presentation"]["component_alignment"]["caption"])

    def test_missing_source_allocation_fails(self) -> None:
        """A required source atom cannot disappear between understanding and rendering."""

        bundle = self.build_bundle()
        bundle["segment_contracts"][0]["coverage"]["source_atoms"] = []
        report = verify_bundle(bundle)
        self.assertEqual("FAIL", report["status"])
        self.assertIn("SOURCE_ATOM_ALLOCATION", {item["rule_id"] for item in report["findings"]})

    def test_blocking_clarification_requires_review(self) -> None:
        """The program stops when the Agent declares result-changing ambiguity."""

        bundle = self.build_bundle()
        bundle["task_contract"]["clarification"] = {"status": "BLOCKED", "blocking_questions": ["需要确认适用范围"]}
        self.assertEqual("REVIEW_REQUIRED", verify_bundle(bundle)["status"])

    def test_unregistered_horizontal_mermaid_fails(self) -> None:
        """Horizontal layout is rejected until the task contract records a real exception."""

        bundle = self.build_bundle()
        source = "```mermaid\nflowchart LR\nA --> B\n```"
        bundle["task_contract"]["context"]["components"].append("FLOWCHART")
        bundle["task_contract"]["components"]["component_order"].append({"component_id": "FLOW-1", "source_before_explanation": True})
        bundle["component_coverage"].append({
            "component_id": "FLOW-1", "component_type": "FLOWCHART", "source_text": source,
            "source_position": 0, "explanation_position": len(source) + 1,
            "required_units": ["A", "B"], "covered_units": ["A", "B"],
            "presentation": {
                "source_format": "mermaid", "object_alignment": "renderer_default",
                "caption_alignment": "not_applicable", "renderer": "chat",
                "limitation": "聊天渲染器不保证 Mermaid 对象精确居中",
            },
            "mermaid": {"direction": "LR", "post_explanation": {"node_relationships": "A 进入 B", "process_result": "流程到达 B", "evidence_boundary": "图中没有运行证据"}},
            "table_cells": {"all": [], "covered": []},
        })
        bundle["rendered_document"]["text"] = source + "\n" + bundle["rendered_document"]["text"]
        bundle["rendered_document"]["sha256"] = hashlib.sha256(bundle["rendered_document"]["text"].encode("utf-8")).hexdigest()
        report = verify_bundle(bundle)
        self.assertEqual("FAIL", report["status"])
        self.assertIn("MERMAID_VERTICAL_DEFAULT", {item["rule_id"] for item in report["findings"]})

    def test_carried_actor_requires_matching_previous_actor(self) -> None:
        """Natural subject omission is valid only when the prior actor is unchanged."""

        bundle = self.build_bundle()
        bundle["rendered_document"]["sentences"][0]["actor_clarity"] = {
            "status": "carried", "actor": "系统", "basis": "声称承接前文",
        }
        report = verify_bundle(bundle)
        self.assertIn("ACTOR_CLARITY", {item["rule_id"] for item in report["findings"]})

    def test_excessive_blank_lines_fail(self) -> None:
        """Two consecutive blank lines are a deterministic layout error."""

        bundle = self.build_bundle()
        text = "任务已接收\n\n\n"
        bundle["rendered_document"]["text"] = text
        bundle["rendered_document"]["sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
        report = verify_bundle(bundle)
        self.assertIn("EXCESSIVE_BLANK_LINES", {item["rule_id"] for item in report["findings"]})

    def test_required_source_uses_registered_blockquote(self) -> None:
        """A short verbatim status excerpt is kept in a blockquote before explanation."""

        bundle = self.build_bundle()
        excerpt = "> 任务已接收"
        bundle["task_contract"]["presentation"]["source_material"] = {
            "required": True, "format": "blockquote", "reason": "需要核对原始状态材料",
        }
        bundle["source_presentations"] = [{
            "source_span_id": "SRC-001", "format": "blockquote", "verbatim": True,
            "rendered_excerpt": excerpt, "reason": "短篇逐字状态材料",
        }]
        text = excerpt + "\n\n任务已接收"
        bundle["rendered_document"]["text"] = text
        bundle["rendered_document"]["sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
        self.assertEqual("PASS", verify_bundle(bundle)["status"])

    def test_inline_code_token_requires_backticks(self) -> None:
        """Registered command and field tokens stay visually distinct from prose."""

        bundle = self.build_bundle()
        bundle["task_contract"]["quality"]["inline_code_tokens"] = ["task_id"]
        report = verify_bundle(bundle)
        self.assertIn("INLINE_CODE_MARKUP", {item["rule_id"] for item in report["findings"]})

    def test_chinese_full_stop_fails_lucas_profile(self) -> None:
        """Generated Chinese punctuation remains a profile-required deterministic rule."""

        bundle = copy.deepcopy(self.build_bundle())
        bundle["rendered_document"]["text"] = "任务已接收。"
        bundle["rendered_document"]["sentences"][0]["text"] = "任务已接收。"
        bundle["rendered_document"]["sha256"] = hashlib.sha256("任务已接收。".encode("utf-8")).hexdigest()
        self.assertEqual("FAIL", verify_bundle(bundle)["status"])


if __name__ == "__main__":
    unittest.main()
