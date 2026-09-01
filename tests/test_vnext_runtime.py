"""Smoke tests for the executable vNext compiler and structural verifier."""

from __future__ import annotations

import copy
import hashlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from runtime.align_inline_comments import align_text, check_alignment  # noqa: E402
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
            "long_context_coverage": {
                "input_char_count": 1, "length_class": "very_short", "section_count": 1,
                "full_document_check": False, "anchors": [], "term_scopes": [], "source_priorities": [],
            },
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
            "term_uses": [], "parallel_group_coverage": [], "component_coverage": [], "boundary_coverage": [],
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

    def test_compile_records_round_five_presentation(self) -> None:
        """The compiler requires verifiable GitHub object and caption alignment."""

        contract = compile_contract({
            "task_id": "TASK-TEST-003", "base_operation": "EXPLAIN", "augmentation": "GLOSS",
            "audience": "general_reader", "genre": "readme", "media": ["github_markdown"],
            "components": ["TEXT", "IMAGE"],
        })
        self.assertEqual("round-5-inline-alignment-aemp", contract["identity"]["profile_revision"])
        self.assertTrue(contract["presentation"]["renderer"]["exact_object_alignment"])
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
            "code": None,
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

    def add_term(self, bundle: dict, requirement: dict, use: dict, text: str) -> None:
        """Attach one term requirement and its rendered use to a valid bundle."""

        bundle["task_contract"]["terminology"]["term_requirements"] = [requirement]
        bundle["term_uses"] = [use]
        bundle["rendered_document"]["text"] = text
        bundle["rendered_document"]["sentences"][0]["text"] = text
        bundle["rendered_document"]["sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()

    def test_registered_parenthetical_title_case_passes(self) -> None:
        """Registered prose passes and literal machine or evidence contexts stay unchanged."""

        bundle = self.build_bundle()
        requirement = {
            "term_id": "CI", "official_form": "CI 持续集成（Continuous Integration）",
            "official_english": "Continuous Integration", "abbreviation": "CI", "registered": True,
            "official_case_verified": True, "parenthetical_english_case": "title_case",
            "parenthetical_form": "Continuous Integration", "official_case_precedence": True,
            "acronym_expansion_allowed": True, "name_rationale": "持续把改动合入共同代码并自动检查",
            "name_rationale_source": "registry:CI", "required_meanings": ["definition"],
        }
        use = {
            "term_id": "CI", "official_form": "CI 持续集成（Continuous Integration）", "parenthetical_form": "Continuous Integration",
            "claimed_expansion": None, "context": "authored_prose",
            "meanings_covered": ["definition"], "sentence_id": "SENT-001",
        }
        self.add_term(bundle, requirement, use, "CI 持续集成（Continuous Integration）会自动检查代码")
        self.assertEqual("PASS", verify_bundle(bundle)["status"])
        for context in ("code", "inline_code", "url", "path", "verbatim"):
            with self.subTest(context=context):
                literal_bundle = self.build_bundle()
                literal_use = dict(use)
                literal_use.update({"official_form": "ci", "parenthetical_form": None, "context": context})
                self.add_term(literal_bundle, requirement, literal_use, "ci")
                self.assertEqual("PASS", verify_bundle(literal_bundle)["status"])

    def test_registered_parenthetical_lowercase_fails(self) -> None:
        """A registered lowercase parenthetical category is a MACHINE_FINAL error."""

        bundle = self.build_bundle()
        requirement = {
            "term_id": "CI", "official_form": "CI 持续集成（Continuous Integration）",
            "official_english": "Continuous Integration", "abbreviation": "CI", "registered": True,
            "official_case_verified": True, "parenthetical_english_case": "title_case",
            "parenthetical_form": "Continuous Integration", "official_case_precedence": True,
            "acronym_expansion_allowed": True, "name_rationale": "持续把改动合入共同代码并自动检查",
            "name_rationale_source": "registry:CI", "required_meanings": ["definition"],
        }
        use = {
            "term_id": "CI", "official_form": "CI 持续集成（Continuous Integration）", "parenthetical_form": "continuous integration",
            "claimed_expansion": None, "context": "authored_prose",
            "meanings_covered": ["definition"], "sentence_id": "SENT-001",
        }
        self.add_term(bundle, requirement, use, "CI 持续集成（continuous integration）会自动检查代码")
        report = verify_bundle(bundle)
        self.assertEqual("FAIL", report["status"])
        self.assertIn("PARENTHETICAL_ENGLISH_CASE", {item["rule_id"] for item in report["findings"]})

    def test_prohibited_acronym_expansion_fails(self) -> None:
        """The runtime rejects an invented expansion for a registered non-acronym name."""

        bundle = self.build_bundle()
        requirement = {
            "term_id": "npm", "official_form": "npm", "official_english": None, "abbreviation": None,
            "registered": True, "official_case_verified": True, "parenthetical_english_case": "not_applicable",
            "parenthetical_form": None, "official_case_precedence": True,
            "acronym_expansion_allowed": False, "name_rationale": "npm 是官方名称，不按缩写展开",
            "name_rationale_source": "registry:npm", "required_meanings": ["definition", "name_origin"],
        }
        use = {
            "term_id": "npm", "official_form": "npm", "parenthetical_form": None,
            "claimed_expansion": "Node Package Manager", "context": "authored_prose",
            "meanings_covered": ["definition", "name_origin"], "sentence_id": "SENT-001",
        }
        self.add_term(bundle, requirement, use, "npm Node Package Manager 是包管理工具")
        report = verify_bundle(bundle)
        self.assertEqual("FAIL", report["status"])
        self.assertIn("ACRONYM_EXPANSION", {item["rule_id"] for item in report["findings"]})

    def test_unknown_official_case_requires_review(self) -> None:
        """An unregistered name stops for review instead of receiving guessed casing."""

        bundle = self.build_bundle()
        requirement = {
            "term_id": "UNKNOWN", "official_form": "Unknown Tool", "official_english": None, "abbreviation": None, "registered": False,
            "official_case_verified": False, "parenthetical_english_case": "title_case",
            "parenthetical_form": None, "official_case_precedence": True,
            "acronym_expansion_allowed": False, "name_rationale": "尚未确认",
            "name_rationale_source": "unverified:UNKNOWN", "required_meanings": ["definition"],
        }
        use = {
            "term_id": "UNKNOWN", "official_form": "Unknown Tool", "parenthetical_form": None,
            "claimed_expansion": None, "context": "authored_prose",
            "meanings_covered": ["definition"], "sentence_id": "SENT-001",
        }
        self.add_term(bundle, requirement, use, "Unknown Tool 用于编排数据")
        report = verify_bundle(bundle)
        self.assertEqual("REVIEW_REQUIRED", report["status"])
        self.assertIn("UNVERIFIED_OFFICIAL_CASE", {item["rule_id"] for item in report["findings"]})

    def test_parallel_group_requires_coverage_ledger(self) -> None:
        """A semantic parallel group cannot disappear into unstructured prose."""

        bundle = self.build_bundle()
        bundle["task_contract"]["structure"]["parallel_groups"] = [{
            "group_id": "PGRP-001", "kind": "facts", "item_ids": ["ITEM-A", "ITEM-B"],
            "required_layout": "indented_list", "minimum_depth": 1,
        }]
        report = verify_bundle(bundle)
        self.assertIn("PARALLEL_GROUP_LEDGER", {item["rule_id"] for item in report["findings"]})

    def test_parallel_group_requires_indented_list(self) -> None:
        """Registered parallel items must be rendered as a list at the declared depth."""

        bundle = self.build_bundle()
        bundle["task_contract"]["structure"]["parallel_groups"] = [{
            "group_id": "PGRP-001", "kind": "comparison", "item_ids": ["ITEM-A", "ITEM-B"],
            "required_layout": "indented_list", "minimum_depth": 1,
        }]
        bundle["parallel_group_coverage"] = [{
            "group_id": "PGRP-001", "item_ids": ["ITEM-A", "ITEM-B"],
            "covered_item_ids": ["ITEM-A", "ITEM-B"], "rendered_as_list": False, "nesting_depth": 0,
        }]
        report = verify_bundle(bundle)
        self.assertIn("PARALLEL_GROUP_LAYOUT", {item["rule_id"] for item in report["findings"]})

    def add_code_component(self, bundle: dict, uncovered: list[str]) -> None:
        """Attach one code component with explicit annotated-code mappings."""

        source = "```python\nvalue = 1  # 初始化数值\n```\n\n```python\nlong_name = 2  # 初始化较长名称\n```"
        mappings = [
            {"unit_id": "CODE-001", "source_locator": "代码块 1 第 1 行", "explanation_locator": "代码块 1 第 1 行注释"},
            {"unit_id": "CODE-002", "source_locator": "代码块 2 第 1 行", "explanation_locator": "代码块 2 第 1 行注释"},
        ]
        bundle["task_contract"]["context"]["components"].append("CODE")
        bundle["task_contract"]["components"]["component_order"].append({"component_id": "CODE-1", "source_before_explanation": True})
        bundle["task_contract"]["code"] = {
            "coverage_mode": "annotated_code", "unit_mappings": mappings,
            "comment_alignment": {"mode": "longest_commentable_line", "scope": "per_code_block", "overflow_policy": "allow"},
        }
        bundle["component_coverage"].append({
            "component_id": "CODE-1", "component_type": "CODE", "source_text": source,
            "source_position": 0, "explanation_position": len(source), "required_units": ["CODE-001", "CODE-002"],
            "covered_units": ["CODE-001", "CODE-002"],
            "presentation": {"source_format": "code_fence", "object_alignment": "not_applicable", "caption_alignment": "not_applicable", "renderer": "chat", "limitation": ""},
            "mermaid": None, "table_cells": {"all": [], "covered": []},
            "code": {
                "coverage_mode": "annotated_code", "unit_mappings": mappings, "uncovered_units": uncovered,
                "comment_alignment": {
                    "mode": "longest_commentable_line",
                    "blocks": [
                        {
                            "block_id": "CODE-BLOCK-001", "target_column": 11,
                            "units": [{"unit_id": "CODE-001", "commentable": True, "code_width": 9, "comment_column": 11, "same_line": True}],
                        },
                        {
                            "block_id": "CODE-BLOCK-002", "target_column": 15,
                            "units": [{"unit_id": "CODE-002", "commentable": True, "code_width": 13, "comment_column": 15, "same_line": True}],
                        },
                    ],
                },
            },
        })
        text = source + "\n\n" + bundle["rendered_document"]["text"]
        bundle["rendered_document"]["text"] = text
        bundle["rendered_document"]["sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()

    def test_annotated_code_mode_passes(self) -> None:
        """Legal code comments can satisfy per-unit coverage."""

        bundle = self.build_bundle()
        self.add_code_component(bundle, [])
        self.assertEqual("PASS", verify_bundle(bundle)["status"])

    def test_uncovered_code_unit_fails(self) -> None:
        """A dense summary cannot hide an uncovered effective statement."""

        bundle = self.build_bundle()
        self.add_code_component(bundle, ["CODE-001"])
        report = verify_bundle(bundle)
        self.assertIn("CODE_UNIT_COVERAGE", {item["rule_id"] for item in report["findings"]})

    def test_compile_annotated_code_requires_longest_line_alignment(self) -> None:
        """Annotated code receives the user-required per-block alignment contract."""

        contract = compile_contract({
            "task_id": "TASK-CODE-ALIGN", "base_operation": "EXPLAIN", "augmentation": "TEACHING",
            "audience": "beginner", "genre": "code_explanation", "media": ["chat"],
            "components": ["TEXT", "CODE"], "code_coverage_mode": "annotated_code",
        })
        self.assertEqual("longest_commentable_line", contract["code"]["comment_alignment"]["mode"])
        self.assertEqual("per_code_block", contract["code"]["comment_alignment"]["scope"])
        aligned = align_text("x = 1  # short\nlong_name = x + 2 # long\n")
        alignment = check_alignment(aligned)
        self.assertEqual("PASS", alignment["status"])
        self.assertEqual({19}, {unit["comment_column"] for unit in alignment["units"]})
        tabbed = align_text("\tx = 1 // short\nlong_name = 2 // long\n", marker="//")
        tabbed_alignment = check_alignment(tabbed, marker="//")
        self.assertEqual("PASS", tabbed_alignment["status"])
        self.assertEqual({15}, {unit["comment_column"] for unit in tabbed_alignment["units"]})

    def test_compile_line_by_line_marks_alignment_not_applicable(self) -> None:
        """Non-commentable formats do not fabricate inline-comment evidence."""

        contract = compile_contract({
            "task_id": "TASK-CODE-JSON", "base_operation": "EXPLAIN", "augmentation": "TEACHING",
            "audience": "beginner", "genre": "code_explanation", "media": ["chat"],
            "components": ["TEXT", "CODE"], "code_coverage_mode": "line_by_line_explanation",
        })
        self.assertEqual("not_applicable", contract["code"]["comment_alignment"]["mode"])

    def test_shifted_inline_comment_fails(self) -> None:
        """One comment shifted away from the shared column is rejected."""

        bundle = self.build_bundle()
        self.add_code_component(bundle, [])
        bundle["component_coverage"][-1]["code"]["comment_alignment"]["blocks"][0]["units"][0]["comment_column"] = 10
        report = verify_bundle(bundle)
        self.assertIn("CODE_COMMENT_ALIGNMENT_UNITS", {item["rule_id"] for item in report["findings"]})

    def test_wrong_alignment_target_fails(self) -> None:
        """The declared column must be longest code width plus two."""

        bundle = self.build_bundle()
        self.add_code_component(bundle, [])
        bundle["component_coverage"][-1]["code"]["comment_alignment"]["blocks"][1]["target_column"] = 16
        report = verify_bundle(bundle)
        self.assertIn("CODE_COMMENT_ALIGNMENT_TARGET", {item["rule_id"] for item in report["findings"]})

    def test_missing_commentable_unit_fails(self) -> None:
        """Alignment evidence must cover every task CODE mapping."""

        bundle = self.build_bundle()
        self.add_code_component(bundle, [])
        bundle["component_coverage"][-1]["code"]["comment_alignment"]["blocks"][0]["units"] = []
        report = verify_bundle(bundle)
        self.assertIn("CODE_COMMENT_ALIGNMENT_UNITS", {item["rule_id"] for item in report["findings"]})

    def test_line_by_line_alignment_evidence_passes(self) -> None:
        """Line-by-line explanation passes only with empty not-applicable alignment evidence."""

        bundle = self.build_bundle()
        self.add_code_component(bundle, [])
        bundle["task_contract"]["code"]["coverage_mode"] = "line_by_line_explanation"
        bundle["task_contract"]["code"]["comment_alignment"]["mode"] = "not_applicable"
        code = bundle["component_coverage"][-1]["code"]
        code["coverage_mode"] = "line_by_line_explanation"
        code["comment_alignment"] = {"mode": "not_applicable", "blocks": []}
        self.assertEqual("PASS", verify_bundle(bundle)["status"])

    def test_superseded_requirement_is_removed_by_default(self) -> None:
        """An overridden requirement cannot remain in the current answer by default."""

        bundle = self.build_bundle()
        bundle["task_contract"]["conversation"]["superseded_texts"] = ["静置 10 分钟"]
        text = "静置 10 分钟；任务已接收"
        bundle["rendered_document"]["text"] = text
        bundle["rendered_document"]["sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
        report = verify_bundle(bundle)
        self.assertIn("SUPERSEDED_REQUIREMENT_LEAK", {item["rule_id"] for item in report["findings"]})

    def test_requested_history_may_keep_superseded_requirement(self) -> None:
        """Audit and revocation tasks may retain the old requirement when explicitly requested."""

        bundle = self.build_bundle()
        bundle["task_contract"]["conversation"] = {
            "preserve_superseded_requirements": True, "superseded_texts": ["静置 10 分钟"],
            "reason": "用户要求说明已经撤销的旧安排",
        }
        text = "静置 10 分钟；任务已接收"
        bundle["rendered_document"]["text"] = text
        bundle["rendered_document"]["sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
        self.assertEqual("PASS", verify_bundle(bundle)["status"])

    def configure_long_context(self, bundle: dict) -> None:
        """Attach one fully covered six-section extended-input contract."""

        anchors = [
            {"anchor_id": "LC-A001", "kind": "CONDITION", "source_locator": "第 1 节", "expected_value": "仅在温度低于 5°C 时启动"},
            {"anchor_id": "LC-A002", "kind": "NUMBER", "source_locator": "第 6 节", "expected_value": "保留 30 天"},
        ]
        term_scopes = [
            {"term": "窗口", "scope_id": "LC-SCOPE-001", "expected_meaning": "数据采集时间范围"},
        ]
        source_priorities = [{
            "conflict_id": "LC-CONFLICT-001", "claim": "保存期限", "source_ids": ["POLICY-OLD", "POLICY-NEW"],
            "priority_source_id": "POLICY-NEW", "must_surface": True,
        }]
        bundle["task_contract"] = compile_contract({
            "task_id": "TASK-LONG-001", "base_operation": "EXPLAIN", "augmentation": "EXPLANATORY",
            "audience": "auditor", "genre": "audit", "media": ["chat"], "components": ["TEXT"],
            "content_task": "audit", "input_char_count": 1800, "length_class": "extended", "section_count": 6,
            "long_context_anchors": anchors, "term_scope_requirements": term_scopes,
            "source_priority_requirements": source_priorities,
        })
        bundle["long_context_coverage"] = {
            "input_char_count": 1800, "length_class": "extended", "section_count": 6,
            "full_document_check": True,
            "anchors": [
                {**item, "observed_value": item["expected_value"], "output_locator": f"输出-{item['anchor_id']}", "status": "preserved"}
                for item in anchors
            ],
            "term_scopes": [
                {**item, "observed_meaning": item["expected_meaning"], "output_locator": "输出-术语窗口"}
                for item in term_scopes
            ],
            "source_priorities": [{"conflict_id": "LC-CONFLICT-001", "selected_source_id": "POLICY-NEW", "surfaced": True}],
        }

    def test_compile_classifies_five_length_ranges(self) -> None:
        """The compiler binds the agreed low-token Unicode ranges exactly."""

        expected = {1: "very_short", 81: "short", 251: "medium", 701: "long", 1501: "extended"}
        for count, length_class in expected.items():
            contract = compile_contract({
                "task_id": f"TASK-LENGTH-{count}", "base_operation": "EXPLAIN", "augmentation": "NONE",
                "audience": "operator", "genre": "operation", "media": ["chat"], "components": ["TEXT"],
                "input_char_count": count,
                "long_context_anchors": [{"anchor_id": "LC-A001", "kind": "CLAIM", "source_locator": "输入", "expected_value": "保留事实"}]
                if count >= 701 else [],
            })
            self.assertEqual(length_class, contract["long_context"]["length_class"])

    def test_long_context_metadata_mismatch_fails(self) -> None:
        """Evidence for a different input size cannot certify the current task."""

        bundle = self.build_bundle()
        self.configure_long_context(bundle)
        bundle["long_context_coverage"]["input_char_count"] = 1799
        report = verify_bundle(bundle)
        self.assertIn("LONG_CONTEXT_METADATA", {item["rule_id"] for item in report["findings"]})

    def test_long_context_requires_full_document_recheck(self) -> None:
        """Passing individual sections cannot replace a final whole-document pass."""

        bundle = self.build_bundle()
        self.configure_long_context(bundle)
        bundle["long_context_coverage"]["full_document_check"] = False
        report = verify_bundle(bundle)
        self.assertIn("FULL_DOCUMENT_RECHECK", {item["rule_id"] for item in report["findings"]})

    def test_long_context_missing_anchor_fails(self) -> None:
        """A distant condition must remain represented in the output ledger."""

        bundle = self.build_bundle()
        self.configure_long_context(bundle)
        bundle["long_context_coverage"]["anchors"] = bundle["long_context_coverage"]["anchors"][1:]
        report = verify_bundle(bundle)
        self.assertIn("LONG_CONTEXT_ANCHOR_MISSING", {item["rule_id"] for item in report["findings"]})

    def test_long_context_changed_number_fails(self) -> None:
        """A cross-section number cannot silently change while remaining locatable."""

        bundle = self.build_bundle()
        self.configure_long_context(bundle)
        bundle["long_context_coverage"]["anchors"][1]["observed_value"] = "保留 7 天"
        bundle["long_context_coverage"]["anchors"][1]["status"] = "changed"
        report = verify_bundle(bundle)
        self.assertIn("LONG_CONTEXT_ANCHOR_VALUE", {item["rule_id"] for item in report["findings"]})

    def test_long_context_term_scope_drift_fails(self) -> None:
        """The same visible term keeps its registered meaning inside each scope."""

        bundle = self.build_bundle()
        self.configure_long_context(bundle)
        bundle["long_context_coverage"]["term_scopes"][0]["observed_meaning"] = "桌面窗口"
        report = verify_bundle(bundle)
        self.assertIn("LONG_CONTEXT_TERM_SCOPE", {item["rule_id"] for item in report["findings"]})

    def test_long_context_source_priority_fails(self) -> None:
        """A conflict cannot be hidden or resolved with the lower-priority source."""

        bundle = self.build_bundle()
        self.configure_long_context(bundle)
        bundle["long_context_coverage"]["source_priorities"][0].update({"selected_source_id": "POLICY-OLD", "surfaced": False})
        report = verify_bundle(bundle)
        self.assertIn("LONG_CONTEXT_SOURCE_PRIORITY", {item["rule_id"] for item in report["findings"]})

    def test_complete_long_context_evidence_passes(self) -> None:
        """Exact anchors, scoped terms, conflict handling, and full review can pass together."""

        bundle = self.build_bundle()
        self.configure_long_context(bundle)
        self.assertEqual("PASS", verify_bundle(bundle)["status"])

    def add_github_image(self, bundle: dict, evidence: list[dict]) -> None:
        """Attach one centered GitHub image and its renderer evidence."""

        source = '<div align="center"><img src="figure.svg" alt="示意图" /><p>图 1. 示意图</p></div>'
        bundle["task_contract"] = compile_contract({
            "task_id": "TASK-TEST-IMG", "base_operation": "EXPLAIN", "augmentation": "GLOSS",
            "audience": "general_reader", "genre": "readme", "media": ["github_markdown"],
            "components": ["TEXT", "IMAGE"], "render_evidence": evidence,
        })
        bundle["component_coverage"] = [{
            "component_id": "IMAGE", "component_type": "IMAGE", "source_text": source,
            "source_position": 0, "explanation_position": len(source), "required_units": ["image"], "covered_units": ["image"],
            "presentation": {"source_format": "image", "object_alignment": "center", "caption_alignment": "center", "renderer": "github_markdown", "limitation": ""},
            "mermaid": None, "table_cells": {"all": [], "covered": []}, "code": None,
        }]
        text = source + "\n\n" + bundle["rendered_document"]["text"]
        bundle["rendered_document"]["text"] = text
        bundle["rendered_document"]["sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()

    def test_github_visual_requires_four_render_results(self) -> None:
        """Source alignment markup alone cannot prove the rendered result."""

        bundle = self.build_bundle()
        self.add_github_image(bundle, [])
        report = verify_bundle(bundle)
        self.assertIn("GITHUB_RENDER_EVIDENCE", {item["rule_id"] for item in report["findings"]})

    def test_github_visual_passes_four_render_results(self) -> None:
        """Desktop and mobile light and dark render evidence satisfies the layout contract."""

        evidence = [
            {"component_id": "IMAGE", "renderer": "github_markdown", "viewport_width": width, "theme": theme,
             "object_centered": True, "caption_centered": True, "horizontal_overflow": False, "evidence_source": f"render-{width}-{theme}.png"}
            for width in (390, 1280) for theme in ("light", "dark")
        ]
        bundle = self.build_bundle()
        self.add_github_image(bundle, evidence)
        self.assertEqual("PASS", verify_bundle(bundle)["status"])

    def test_professional_term_requires_name_rationale(self) -> None:
        """A standalone professional term must explain why its registered name is used."""

        bundle = self.build_bundle()
        requirement = {
            "term_id": "TTL", "official_form": "TTL 生存时间（Time to Live）", "official_english": "Time to Live", "abbreviation": "TTL",
            "registered": True, "official_case_verified": True, "name_rationale": "表示记录能够继续使用的时间",
            "name_rationale_source": "registry:TTL", "parenthetical_english_case": "title_case", "parenthetical_form": "Time to Live",
            "official_case_precedence": True, "acronym_expansion_allowed": True, "required_meanings": ["definition", "name_origin"],
        }
        use = {
            "term_id": "TTL", "official_form": "TTL 生存时间（Time to Live）", "parenthetical_form": "Time to Live",
            "claimed_expansion": "Time to Live", "context": "authored_prose", "meanings_covered": ["definition"], "sentence_id": "SENT-001",
        }
        self.add_term(bundle, requirement, use, "TTL 生存时间（Time to Live）规定缓存时长")
        report = verify_bundle(bundle)
        self.assertIn("TERM_FIRST_USE_COVERAGE", {item["rule_id"] for item in report["findings"]})


if __name__ == "__main__":
    unittest.main()
