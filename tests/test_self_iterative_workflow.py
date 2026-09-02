"""Executable checks for the isolated self-iterative forward workflow."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import run_iterative_forward_matrix as matrix  # noqa: E402


class IterativeForwardWorkflowTests(unittest.TestCase):
    """Prove session binding, minimal repair, final recheck, and public evidence."""

    def test_parse_events_returns_last_message_and_session(self) -> None:
        stdout = "\n".join([
            json.dumps({"type": "thread.started", "thread_id": "session-1"}),
            json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "first"}}),
            json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "last"}}),
        ])
        events, body, session = matrix.parse_events(stdout)
        self.assertEqual(len(events), 3)
        self.assertEqual(body, "last")
        self.assertEqual(session, "session-1")

    def test_unseeded_initial_prompt_is_nonempty(self) -> None:
        prompt = matrix.initial_prompt({"case_id": "FWD-R2-021"}, None, [])
        self.assertIsInstance(prompt, str)
        self.assertIn("FWD-R2-021", prompt)

    def test_semantic_prompt_requires_evidence_before_term_escalation(self) -> None:
        prompt = matrix.review_prompt({}, "税前差 3 元", {}, [])
        self.assertIn("strict professional-term threshold", prompt)
        self.assertIn("pre-tax", prompt)
        self.assertIn("Never invent a style rule", prompt)
        self.assertIn("ordered-list markers", prompt)

    def test_case_filter_is_exposed_for_isolated_diagnostics(self) -> None:
        source = (ROOT / "scripts" / "run_iterative_forward_matrix.py").read_text(encoding="utf-8")
        self.assertIn('parser.add_argument("--case-id", action="append"', source)

    def test_formal_run_requires_qualification_id_and_defaults_to_fail_fast(self) -> None:
        args = argparse.Namespace(case_id=None, qualification_id=None, fail_fast=None)
        with self.assertRaisesRegex(ValueError, "require --qualification-id"):
            matrix.configure_run(args)
        configured = matrix.configure_run(argparse.Namespace(
            case_id=None, qualification_id="round2-q20", fail_fast=None,
        ))
        self.assertEqual(configured.run_kind, "qualification")
        self.assertTrue(configured.fail_fast)

    def test_diagnostic_run_never_requires_qualification_id(self) -> None:
        configured = matrix.configure_run(argparse.Namespace(
            case_id=["FWD-R2-024"], qualification_id=None, fail_fast=None,
        ))
        self.assertEqual(configured.run_kind, "diagnostic")
        self.assertFalse(configured.fail_fast)

    def test_qualification_id_rejects_unsafe_characters(self) -> None:
        with self.assertRaisesRegex(ValueError, "letters, digits"):
            matrix.configure_run(argparse.Namespace(
                case_id=None, qualification_id="round 2/private", fail_fast=None,
            ))

    def test_only_one_host_retry_is_allowed_and_review_required_is_terminal(self) -> None:
        self.assertTrue(matrix.can_retry_run_error("RUN_ERROR", 1, True))
        self.assertFalse(matrix.can_retry_run_error("RUN_ERROR", 2, True))
        self.assertFalse(matrix.can_retry_run_error("RUN_ERROR", 1, False))
        self.assertFalse(matrix.can_retry_run_error("REVIEW_REQUIRED", 0, True))

    def test_runtime_tree_digest_is_stable_and_sha256_shaped(self) -> None:
        first = matrix.runtime_tree_digest()
        self.assertEqual(first, matrix.runtime_tree_digest())
        self.assertRegex(first, r"^[a-f0-9]{64}$")
        self.assertRegex(matrix.closure_runner_digest(), r"^[a-f0-9]{64}$")

    def test_windows_code_page_output_preserves_chinese(self) -> None:
        self.assertEqual(matrix.decode_process_output("中文输出".encode("gb18030")), "中文输出")

    def test_access_audit_rejects_paths_outside_clean_roots(self) -> None:
        events = [{
            "item": {"type": "file_read", "path": r"C:\private\memory.txt"},
        }]
        violations = matrix.access_violations(events, [Path(r"C:\isolated\home"), Path(r"C:\isolated\task")])
        self.assertEqual(violations, [r"C:\private\memory.txt"])

    def test_access_audit_allows_codex_shell_runtime_infrastructure(self) -> None:
        events = [{
            "item": {"type": "command_execution", "command": r"X:\runtime\.cache\codex-runtimes\runtime\pwsh.exe"},
        }]
        self.assertEqual(matrix.access_violations(events, [Path(r"F:\isolated\home")]), [])

    def test_access_audit_ignores_paths_mentioned_only_in_command_output(self) -> None:
        events = [{
            "item": {
                "type": "command_execution",
                "command": r"Get-Content F:\\isolated\\home\\skill.md",
                "aggregated_output": r"example C:\\private\\memory.txt",
            },
        }]
        self.assertEqual(matrix.access_violations(events, [Path(r"F:\isolated\home")]), [])

    def test_access_audit_normalizes_json_escaped_skill_path(self) -> None:
        events = [{
            "item": {"type": "file_read", "path": r"F:\\isolated\\home\\skills\\skill.md"},
        }]
        self.assertEqual(matrix.access_violations(events, [Path(r"F:\isolated\home")]), [])

    def test_access_audit_normalizes_json_escaped_command_path(self) -> None:
        events = [{
            "item": {
                "type": "command_execution",
                "command": r'''"X:\\runtime\\.cache\\codex-runtimes\\runtime\\pwsh.exe" -Command "Get-Content -Raw 'F:\\isolated\\home\\skills\\skill.md'"''',
            },
        }]
        self.assertEqual(matrix.access_violations(events, [Path(r"F:\isolated\home")]), [])

    def test_access_audit_allows_isolated_agent_container_but_rejects_sibling(self) -> None:
        events = [{
            "item": {"type": "command_execution", "command": r"rg --files F:\\isolated\\reviewer-1"},
        }]
        self.assertEqual(matrix.access_violations(events, [Path(r"F:\isolated\reviewer-1")]), [])
        self.assertEqual(
            matrix.access_violations(events, [Path(r"F:\isolated\reviewer-2")]),
            [r"F:\\isolated\\reviewer-1"],
        )

    def test_preservation_snapshot_covers_numbers_and_mixed_components(self) -> None:
        answer = """温度为 78°C

| 项目 | 数值 |
|---|---:|
| 阈值 | 40% |

![状态图](assets/status.svg)

```python
limit = 3
```"""
        snapshot = matrix.preservation_snapshot(answer)
        self.assertIn("78°C", snapshot["numbers"])
        self.assertIn("40%", snapshot["numbers"])
        self.assertEqual(len(snapshot["table_rows"]), 3)
        self.assertEqual(snapshot["image_links"], ["![状态图](assets/status.svg)"])
        self.assertEqual(len(snapshot["fenced_blocks"]), 1)

    def test_manifest_invariants_cover_schema_unsupported_sets(self) -> None:
        payload = {
            "source_units": ["SRCU-001", "SRCU-001"], "support_map": ["SRCU-002"],
            "parallel_groups": [{"group_id": "PGRP-001", "item_texts": ["甲", "甲"]}],
            "section_plan": {"heading_levels": [3, 3]},
            "answer": "正文", "term_uses": [],
        }
        findings = matrix.initial_contract_findings(payload)
        self.assertEqual(len(findings), 4)

    def test_manifest_rejects_null_english_professional_term_declarations(self) -> None:
        payload = {
            "source_units": ["SRCU-001"], "support_map": ["SRCU-001"],
            "parallel_groups": [], "section_plan": {"heading_levels": []},
            "answer": "当前为只读状态",
            "term_uses": [{"term": "只读状态", "official_english": None, "first_use_text": "只读状态"}],
        }
        findings = matrix.initial_contract_findings(payload)
        self.assertEqual(len(findings), 1)
        self.assertIn("requires verified official English", findings[0])

    def test_professional_term_list_label_is_not_a_colon_pseudo_heading(self) -> None:
        manifest = {
            "term_uses": [{
                "term": "残余压力", "official_english": "Residual Pressure",
                "first_use_text": "残余压力（Residual Pressure）",
            }],
            "parallel_groups": [],
            "section_plan": {"headings_required": False, "heading_levels": []},
        }
        findings = matrix.deterministic_findings(
            "- 残余压力（Residual Pressure）：主要能源隔离后仍残留的压力",
            manifest,
        )
        self.assertNotIn("COLON_PSEUDO_HEADING", {item["rule_id"] for item in findings})
        pseudo = matrix.deterministic_findings("操作：关闭阀门", manifest)
        self.assertIn("COLON_PSEUDO_HEADING", {item["rule_id"] for item in pseudo})

    def test_compact_inline_parallel_group_does_not_require_list_layout(self) -> None:
        manifest = {
            "term_uses": [],
            "parallel_groups": [{
                "group_id": "PGRP-001", "item_texts": ["17 笔一致", "1 笔税前差 3 元"],
                "required_layout": "compact_inline", "rendered_as_indented_list": False,
            }],
            "section_plan": {"headings_required": False, "heading_levels": []},
        }
        findings = matrix.deterministic_findings("17 笔一致；1 笔税前差 3 元", manifest)
        self.assertNotIn("PARALLEL_GROUP_LAYOUT", {item["rule_id"] for item in findings})

    def test_patch_ids_are_normalized_without_changing_patch_content(self) -> None:
        payload = {"patches": [{
            "identity": {"patch_id": "PATCH-999", "finding_id": "F-1", "operation": "replace_exact"},
            "replacement": {"old_text": "。", "new_text": "", "expected_occurrences": 1},
        }], "updated_manifest": {}}
        normalized, mappings = matrix.normalize_patch_ids(payload, 2)
        self.assertEqual(normalized["patches"][0]["identity"]["patch_id"], "PATCH-002")
        self.assertEqual(mappings, [{"submitted": "PATCH-999", "assigned": "PATCH-002"}])
        self.assertEqual(payload["patches"][0]["identity"]["patch_id"], "PATCH-999")

    def test_seed_manifest_schema_has_no_answer_field(self) -> None:
        schema = json.loads((ROOT / "contracts" / "forward-manifest-output.schema.json").read_text(encoding="utf-8"))
        self.assertNotIn("answer", schema["properties"])
        self.assertNotIn("answer", schema["required"])

    def test_rejected_patch_contract_retries_and_reaches_pass_after_recheck(self) -> None:
        initial_answer = "答案。"
        initial_hash = hashlib.sha256(initial_answer.encode("utf-8")).hexdigest()
        final_answer = "答案"
        final_hash = hashlib.sha256(final_answer.encode("utf-8")).hexdigest()
        manifest = {
            "term_uses": [], "parallel_groups": [],
            "section_plan": {
                "headings_required": False, "heading_levels": [],
                "basis": "单行短答无需标题", "colon_pseudo_headings_allowed": False,
            },
            "boundary_visibility": {"mode": "internal", "material_reason": None},
        }
        initial_payload = {
            "answer": initial_answer,
            "source_units": ["SRCU-001"], "support_map": ["SRCU-001"],
            "background_claims": [], **manifest,
        }
        patch_payload = {
            "patches": [{
                "identity": {"patch_id": "PATCH-001", "finding_id": "LUCAS_NO_CHINESE_FULL_STOP:LINE-0001", "operation": "replace_exact"},
                "target": {"document_sha256": initial_hash, "node_id": "LINE-0001"},
                "replacement": {"old_text": "。", "new_text": "", "expected_occurrences": 1},
                "authorization": {"reason": "只移除中文句号", "repair_scope": "token", "preserve": ["答案"]},
                "verification": {"rerun_validators": ["deterministic", "semantic"]},
            }],
            "updated_manifest": manifest,
        }
        initial_result = {
            "exit_code": 0, "stderr": "", "events": [],
            "body": json.dumps(initial_payload, ensure_ascii=False), "thread_id": "session-1",
        }
        patch_result = {
            "exit_code": 0, "stderr": "", "events": [],
            "body": json.dumps(patch_payload, ensure_ascii=False), "thread_id": "session-1",
        }
        rejected_patch_payload = json.loads(json.dumps(patch_payload))
        rejected_patch_payload["patches"][0]["target"]["document_sha256"] = "0" * 64
        rejected_patch_result = {
            "exit_code": 0, "stderr": "", "events": [],
            "body": json.dumps(rejected_patch_payload, ensure_ascii=False), "thread_id": "session-1",
        }
        reviewer_result = {"events": []}
        request = {
            "case_id": "FWD-R2-021", "request": "改写", "source": {"content": "答案"},
        }
        args = argparse.Namespace()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            auth = root / "auth.json"
            auth.write_text("{}", encoding="utf-8")
            with (
                patch.object(matrix, "start_agent", return_value=initial_result),
                patch.object(matrix, "resume_agent", side_effect=[rejected_patch_result, patch_result]),
                patch.object(matrix, "semantic_review", side_effect=[([], reviewer_result, []), ([], reviewer_result, []), ([], reviewer_result, [])]),
            ):
                public, private = matrix.run_case(
                    args, request, "gpt-5.6-sol", None, [], auth, root / "runs",
                )
        self.assertEqual(public["status"], "PASS")
        self.assertEqual(public["answer"], final_answer)
        self.assertEqual(public["final_sha256"], final_hash)
        self.assertEqual(public["first_attempt_hard_errors"], 1)
        self.assertEqual(public["repair_rounds"], 2)
        self.assertEqual(public["iterations"]["rounds"][0]["result_status"], "FAIL")
        self.assertEqual(public["iterations"]["rounds"][1]["result_status"], "PASS")
        self.assertEqual(public["iterations"]["rounds"][0]["finding_rule_ids"], ["LUCAS_NO_CHINESE_FULL_STOP"])
        self.assertEqual(public["iterations"]["rounds"][1]["patch_summaries"][0]["repair_scope"], "token")
        self.assertIn("document hash mismatch", private["iterations"][0]["patch_rejection"])
        self.assertEqual(private["iterations"][1]["before_answer"], initial_answer)


if __name__ == "__main__":
    unittest.main()
