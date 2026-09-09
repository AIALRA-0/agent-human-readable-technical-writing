"""Checks for randomized clean-Agent format qualification."""

from __future__ import annotations

import json
import copy
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from collections import Counter
from pathlib import Path
from unittest.mock import patch

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from runtime.align_inline_comments import align_text  # noqa: E402
from runtime.format_validation import deterministic_format_findings, deterministic_format_replacements  # noqa: E402
from scripts import generate_agent_variability_cases as generator  # noqa: E402
from scripts import run_clean_agent_format_matrix as matrix  # noqa: E402
from scripts import run_iterative_forward_matrix as forward_matrix  # noqa: E402
from scripts import validate_clean_agent_format_matrix as report_validator  # noqa: E402


def exact_test_patch(answer: str, old_text: str, new_text: str, node: str = "LINE-0001") -> dict:
    return {
        "identity": {"patch_id": "PATCH-001", "finding_id": "FINDING-001", "operation": "replace_exact"},
        "target": {"document_sha256": matrix.sha256_text(answer), "node_id": node},
        "replacement": {"old_text": old_text, "new_text": new_text, "expected_occurrences": 1},
        "authorization": {"reason": "只改命中标点", "repair_scope": "token", "preserve": ["其他字符"]},
        "verification": {"rerun_validators": ["FORMAT_NO_CHINESE_FULL_STOP"]},
    }


def write_snapshot_source(root: Path, marker: str) -> None:
    (root / "references").mkdir(parents=True)
    (root / "contracts").mkdir(parents=True)
    (root / "SKILL.md").write_text(
        f"---\nname: test\ndescription: snapshot test\n---\n{marker}\n",
        encoding="utf-8",
    )
    (root / "references/format-rules.md").write_text(f"FMT {marker}\n", encoding="utf-8")
    (root / "references/explanation-framework.md").write_text(
        f"EXPL {marker}\n", encoding="utf-8",
    )
    for schema_name in (
        "format-agent-output.schema.json", "format-review-output.schema.json",
    ):
        (root / "contracts" / schema_name).write_text(
            (ROOT / "contracts" / schema_name).read_text(encoding="utf-8"),
            encoding="utf-8",
        )


class CleanAgentFormatMatrixTests(unittest.TestCase):
    def test_frozen_snapshot_is_unchanged_when_source_repo_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            run_root = root / "run"
            run_root.mkdir()
            write_snapshot_source(source, "VERSION_ONE")
            snapshot = matrix.freeze_candidate_snapshot(run_root, source)
            original_digest = matrix.skill_snapshot_digest(snapshot)

            (source / "SKILL.md").write_text(
                "---\nname: test\ndescription: snapshot test\n---\nVERSION_TWO\n",
                encoding="utf-8",
            )

            self.assertIn("VERSION_ONE", (snapshot / "SKILL.md").read_text(encoding="utf-8"))
            self.assertNotIn("VERSION_TWO", (snapshot / "SKILL.md").read_text(encoding="utf-8"))
            self.assertEqual(matrix.skill_snapshot_digest(snapshot), original_digest)

    def test_all_installs_in_one_run_read_the_same_frozen_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            run_root = root / "run"
            run_root.mkdir()
            write_snapshot_source(source, "RUN_VERSION")
            snapshot = matrix.freeze_candidate_snapshot(run_root, source)

            first_home = root / "first-home"
            second_home = root / "second-home"
            matrix.install_candidate(first_home, snapshot)
            (source / "references/format-rules.md").write_text("CHANGED_REPO\n", encoding="utf-8")
            matrix.install_candidate(second_home, snapshot)

            first = matrix.format_rule_bundle(first_home, {}, "writer")
            second = matrix.format_rule_bundle(second_home, {}, "reviewer")
            self.assertEqual(first, second)
            self.assertIn("RUN_VERSION", first)
            self.assertNotIn("CHANGED_REPO", second)

    def test_resume_rejects_report_summary_that_does_not_match_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            run_root = root / "run"
            run_root.mkdir()
            write_snapshot_source(source, "BOUND_VERSION")
            snapshot = matrix.freeze_candidate_snapshot(run_root, source)
            actual = matrix.skill_snapshot_digest(snapshot)

            with self.assertRaisesRegex(SystemExit, "frozen Skill snapshot"):
                matrix.load_run_snapshot(run_root, {"skill_tree_sha256": "0" * 64})
            loaded, loaded_digest = matrix.load_run_snapshot(
                run_root, {"skill_tree_sha256": actual},
            )
            self.assertEqual(loaded, snapshot)
            self.assertEqual(loaded_digest, actual)

    def test_negative_output_calls_clean_agent_with_metadata_only_and_exact_answer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            run_root = root / "run"
            run_root.mkdir()
            write_snapshot_source(source, "HIDDEN_RULE_BODY")
            snapshot = matrix.freeze_candidate_snapshot(run_root, source)
            auth = root / "auth.json"
            auth.write_text("{}", encoding="utf-8")
            task = {
                "request": "仅复制这个整数，不加单位或解释。",
                "source": {"content": "27", "material_type": "text"},
                "references": [],
            }
            response = {
                "body": json.dumps({"answer": "27"}), "exit_code": 0, "stderr": "",
                "events": [], "thread_id": "negative-session",
            }
            args = Namespace(auth=auth, skill_snapshot_root=snapshot)
            with patch.object(matrix, "call_clean_agent", return_value=response) as called:
                public, private = matrix.run_negative_output(
                    args, "gpt-5.6-sol", root / "case", task,
                )

            prompt_text = called.call_args.args[4]
            self.assertEqual(called.call_args.args[5], "format-agent-output.schema.json")
            self.assertIn("description: snapshot test", prompt_text)
            self.assertNotIn("HIDDEN_RULE_BODY", prompt_text)
            self.assertEqual(public["negative_output_status"], "PASS")
            self.assertTrue(public["negative_output_exact"])
            self.assertEqual(private["payload"], {"answer": "27"})
            installed = root / "case/negative-output/home/skills/human-readable-technical-writing"
            files = {
                path.relative_to(installed).as_posix() for path in installed.rglob("*") if path.is_file()
            }
            self.assertEqual(files, {"SKILL.md", "contracts/format-agent-output.schema.json"})

    def test_negative_output_rejects_wrappers_invalid_json_and_file_access(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            run_root = root / "run"
            run_root.mkdir()
            write_snapshot_source(source, "RULE_BODY")
            snapshot = matrix.freeze_candidate_snapshot(run_root, source)
            auth = root / "auth.json"
            auth.write_text("{}", encoding="utf-8")
            args = Namespace(auth=auth, skill_snapshot_root=snapshot)
            task = {
                "request": "只原样返回纯 Python 代码，不加说明或围栏。",
                "source": {"content": "print(1)\n", "material_type": "code"},
                "references": [],
            }
            for number, answer in enumerate(("```python\nprint(1)\n```", "print(1)\n说明"), 1):
                response = {
                    "body": json.dumps({"answer": answer}), "exit_code": 0, "stderr": "",
                    "events": [], "thread_id": "negative-session",
                }
                with self.subTest(answer=answer), patch.object(
                    matrix, "call_clean_agent", return_value=response,
                ):
                    public, _ = matrix.run_negative_output(
                        args, "gpt-5.6-sol", root / f"wrong-{number}", task,
                    )
                self.assertEqual(public["negative_output_status"], "REVIEW_REQUIRED")
                self.assertFalse(public["negative_output_exact"])

            invalid = {
                "body": "not-json", "exit_code": 0, "stderr": "", "events": [],
                "thread_id": "negative-session",
            }
            with patch.object(matrix, "call_clean_agent", return_value=invalid), self.assertRaisesRegex(
                RuntimeError, "valid JSON",
            ):
                matrix.run_negative_output(args, "gpt-5.6-sol", root / "invalid", task)

            outside = r"F:\outside\secret.txt"
            accessed = {
                "body": json.dumps({"answer": "print(1)\n"}), "exit_code": 0, "stderr": "",
                "events": [{"item": {"type": "file_read", "path": outside}}],
                "thread_id": "negative-session",
            }
            with patch.object(matrix, "call_clean_agent", return_value=accessed):
                public, private = matrix.run_negative_output(
                    args, "gpt-5.6-sol", root / "accessed", task,
                )
            self.assertTrue(public["negative_output_exact"])
            self.assertEqual(public["negative_output_status"], "REVIEW_REQUIRED")
            self.assertEqual(public["negative_output_access_violation_count"], 1)
            self.assertEqual(private["access_violations"], [outside])

    def test_negative_case_cannot_pass_from_trigger_classification_alone(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            row = {
                "case_id": "NEG", "request": "仅复制整数。",
                "source": {"content": "27"}, "references": [],
                "trigger_mode": "non_triggering_control",
            }
            trigger_private = {"access_violations": [], "recovered_terminal_flush_error": False}
            negative_public = {
                "negative_output_status": "REVIEW_REQUIRED", "negative_output_exact": False,
                "negative_output_access_violation_count": 0,
            }
            with patch.object(
                matrix, "run_trigger", return_value=({"activated": False}, trigger_private),
            ), patch.object(
                matrix, "run_negative_output", return_value=(negative_public, {}),
            ) as negative:
                result = matrix.run_case_model(
                    Namespace(), row, "gpt-5.6-sol", "gpt-5.6-sol", root, 1,
                )
            negative.assert_called_once()
            self.assertTrue(result["trigger_pass"])
            self.assertEqual(result["writing_status"], "NOT_APPLICABLE")
            self.assertEqual(result["status"], "REVIEW_REQUIRED")
            self.assertFalse(matrix.has_complete_output_evidence({"expected_trigger": False}))
            self.assertTrue(matrix.has_complete_output_evidence({
                "expected_trigger": False, "negative_output_status": "PASS",
            }))

    def test_resume_identity_includes_actual_reasoning_effort_and_rejects_missing_value(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            run_root = root / "run"
            run_root.mkdir()
            write_snapshot_source(source, "BOUND_VERSION")
            snapshot = matrix.freeze_candidate_snapshot(run_root, source)
            requests = root / "requests.jsonl"
            requests.write_text(
                "\n".join(
                    json.dumps({"case_id": f"CASE-{number:02d}"}) for number in range(20)
                ) + "\n",
                encoding="utf-8",
            )
            auth = root / "auth.json"
            auth.write_text("{}", encoding="utf-8")
            report = root / "report.json"
            previous = {
                "qualification_id": "Q-1", "run_kind": "qualification",
                "seed_source_sha256": matrix.digest_file(requests),
                "skill_tree_sha256": matrix.skill_snapshot_digest(snapshot),
                "runner_sha256": matrix.digest_file(Path(matrix.__file__)),
                "models": ["gpt-5.6-sol"], "reasoning_effort": "high",
                "max_repair_rounds": 2, "case_count": 20,
                "trigger_measurement": matrix.TRIGGER_MEASUREMENT,
                "review_scope": list(matrix.REVIEW_SCOPE), "results": [],
            }
            args = Namespace(
                requests=requests, auth=auth, run_root=run_root, report=report,
                model=["gpt-5.6-sol"], codex="codex", reasoning_effort="medium",
                workers=1, timeout_seconds=1, max_repair_rounds=2,
                qualification_id="Q-1", resume_incomplete=True,
                retry_run_errors=False, fail_fast=False, case_id=None,
            )
            for saved_effort in ("high", None):
                if saved_effort is None:
                    previous.pop("reasoning_effort", None)
                else:
                    previous["reasoning_effort"] = saved_effort
                report.write_text(json.dumps(previous), encoding="utf-8")
                with self.subTest(saved_effort=saved_effort), patch.object(
                    matrix, "parse_args", return_value=args,
                ), self.assertRaisesRegex(SystemExit, "existing report does not match"):
                    matrix.main()

    def test_generator_is_deterministic_balanced_and_has_no_answer_hints(self) -> None:
        first = generator.build_cases(20260907, 20, 8)
        self.assertEqual(first, generator.build_cases(20260907, 20, 8))
        generator.validate_rows(first)
        self.assertEqual(set(Counter(row["length_class"] for row in first).values()), {4})
        self.assertEqual(set(Counter(row["audience"] for row in first).values()), {4})
        self.assertEqual(sum(row["trigger_mode"] == "non_triggering_control" for row in first), 4)
        serialized = json.dumps(first, ensure_ascii=False).casefold()
        for forbidden in ("expected_answer", "gold", "score", "reviewer_hint"):
            self.assertNotIn(forbidden, serialized)

    def test_public_task_removes_hidden_evaluator_metadata(self) -> None:
        row = generator.build_cases(20260907, 20, 8)[0]
        visible = matrix.public_task(row)
        self.assertEqual(set(visible), {"request", "source", "references"})
        self.assertNotIn("sha256", visible["source"])
        serialized = json.dumps(visible, ensure_ascii=False)
        for hidden in ("trigger_mode", "length_class", "topic_id", "variation_tags"):
            self.assertNotIn(hidden, serialized)

    def test_rule_bundle_reads_full_two_parts_without_legacy_components(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            skill = home / "skills/human-readable-technical-writing"
            (skill / "references").mkdir(parents=True)
            (skill / "SKILL.md").write_text(
                "---\nname: test\ndescription: Chinese writing\n---\n## 1. 启动\nentry\n## 2. 正文\nFULL_ENTRY_END",
                encoding="utf-8",
            )
            for name, content in (
                ("format-rules.md", "- `FMT-001` full format rules\nFORMAT_END"),
                ("explanation-framework.md", "- `EXPL-001` explanation\nEXPLANATION_END"),
            ):
                (skill / "references" / name).write_text(content, encoding="utf-8")
            trigger = matrix.format_rule_bundle(home, {}, "trigger")
            self.assertIn("description:", trigger)
            self.assertNotIn("## 1. 启动", trigger)
            code = matrix.format_rule_bundle(
                home, {"source": {"material_type": "code"}, "components": ["CODE"]}, "writer",
            )
            self.assertIn("FMT-001", code)
            for marker in ("FULL_ENTRY_END", "FORMAT_END", "EXPLANATION_END", "EXPL-001"):
                self.assertIn(marker, code)
            self.assertNotIn("profiles/components", code)
            self.assertNotIn("EXPL-001", trigger)
            self.assertEqual(code, matrix.format_rule_bundle(home, {}, "reviewer"))
            (skill / "references/explanation-framework.md").unlink()
            with self.assertRaisesRegex(RuntimeError, "explanation-framework"):
                matrix.format_rule_bundle(home, {}, "writer")

    def test_existing_review_schema_extension_has_exact_explanation_range(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            matrix.install_candidate(home)
            schema_name = "format-review-output.schema.json"
            original = json.loads((ROOT / "contracts" / schema_name).read_text(encoding="utf-8"))
            installed = json.loads(
                (home / "skills/human-readable-technical-writing/contracts" / schema_name).read_text(encoding="utf-8")
            )
            self.assertEqual(installed, matrix.review_output_schema(original))
            rule_schema = installed["properties"]["findings"]["items"]["properties"]["rule_id"]
            for rule in ("FMT-036", "FMT-043", *(f"EXPL-{number:03d}" for number in range(1, 15))):
                jsonschema.validate(rule, rule_schema)
            for rule in ("EXPL-000", "EXPL-015", "EXPL-999", "OTHER-001"):
                with self.assertRaises(jsonschema.ValidationError):
                    jsonschema.validate(rule, rule_schema)
            restored = matrix.review_output_schema(original)
            restored["properties"]["findings"]["items"]["properties"]["rule_id"] = original["properties"]["findings"]["items"]["properties"]["rule_id"]
            self.assertEqual(restored, original)

    def test_installed_bundle_matches_the_entire_current_entry_and_two_rule_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            matrix.install_candidate(home)
            bundle = matrix.format_rule_bundle(home, {"source": {"material_type": "code"}}, "writer")
            paths = ("SKILL.md", "references/format-rules.md", "references/explanation-framework.md")
            expected = "\n\n".join(
                f"===== {relative} =====\n{(ROOT / relative).read_text(encoding='utf-8')}"
                for relative in paths
            )
            self.assertEqual(bundle, expected)
            findings = [{"rule_id": f"EXPL-{number:03d}"} for number in range(1, 15)]
            kept, rejected = matrix.filter_undefined_rule_findings(findings, bundle)
            self.assertEqual(kept, findings)
            self.assertEqual(rejected, [])

    def test_scoring_requires_defined_rules_without_dropping_valid_parallel_findings(self) -> None:
        findings = [{"rule_id": rule, "old_text": "证据"} for rule in (
            "FMT-036", "FMT-043", "EXPL-001", "EXPL-014", "EXPL-015", "FMT-999",
        )]
        bundle = "\n".join(f"- `{rule}` 当前规则" for rule in (
            "FMT-036", "FMT-043", "EXPL-001", "EXPL-014", "EXPL-015",
        ))
        kept, rejected = matrix.filter_undefined_rule_findings(findings, bundle)
        self.assertEqual([item["rule_id"] for item in kept], ["FMT-036", "FMT-043", "EXPL-001", "EXPL-014"])
        self.assertEqual(len(rejected), 2)
        kept, rejected = matrix.filter_format_phase_findings(kept, "证据", {})
        self.assertEqual(len(kept), 4)
        self.assertEqual(rejected, [])

    def test_prompts_share_parallel_rules_and_preserve_source_ownership(self) -> None:
        for prompt_text in (
            matrix.writer_prompt({}, "RULES"),
            matrix.review_prompt({}, "正文", "RULES"),
            matrix.repair_prompt("正文", [], "RULES"),
        ):
            self.assertIn(matrix.PARALLEL_GUIDANCE, prompt_text)
            self.assertIn("FMT-043 does not impose one line per source", prompt_text)
            self.assertIn("Independent column definitions, row-mapping facts", prompt_text)
            self.assertIn("continuous definition remains one block", prompt_text)
            self.assertIn("cause-to-result explanation is not automatically a list", prompt_text)

    def test_writer_prompt_contains_no_hidden_scoring_contract(self) -> None:
        task = {"request": "整理正文", "source": {"material_type": "text", "content": "正文"}, "references": []}
        prompt_text = matrix.writer_prompt(task, "RULES")
        self.assertIn("RULE_BUNDLE", prompt_text)
        self.assertIn("Do not call tools", prompt_text)
        self.assertIn("outer deterministic middleware", prompt_text)
        for forbidden in ("expected_answer", "trigger_mode", "topic_id", "variation_tags", "Gold"):
            self.assertNotIn(forbidden, prompt_text)

    def test_format_schemas_are_valid(self) -> None:
        names = (
            "format-agent-output.schema.json", "format-trigger-output.schema.json",
            "format-patch-output.schema.json", "format-review-output.schema.json",
        )
        for name in names:
            schema = json.loads((ROOT / "contracts" / name).read_text(encoding="utf-8"))
            jsonschema.Draft202012Validator.check_schema(schema)

    def test_review_checklist_constants_declare_boolean_type(self) -> None:
        schema = json.loads(
            (ROOT / "contracts" / "format-review-output.schema.json").read_text(encoding="utf-8")
        )
        categories = schema["properties"]["reviewed_categories"]["properties"]
        self.assertTrue(categories)
        for category in categories.values():
            self.assertEqual(category.get("type"), "boolean")
            self.assertIs(category.get("const"), True)

    def test_terminal_flush_error_is_recovered_only_with_valid_schema_output(self) -> None:
        result = {
            "exit_code": 1,
            "body": '{"activated":true,"reason":"matches"}',
            "stderr": "failed to flush rollout after emitting terminal turn event: thread x not found",
        }
        payload = matrix.parse_payload(result, "format-trigger-output.schema.json")
        self.assertTrue(payload["activated"])
        self.assertTrue(result["recovered_terminal_flush_error"])

    def test_patch_bookkeeping_id_normalization_does_not_change_evidence(self) -> None:
        proposal = exact_test_patch("正文。", "。", "")
        proposal["identity"]["patch_id"] = "PATCH-AUTO"
        original = copy.deepcopy(proposal)
        raw = {"body": json.dumps({"patches": [proposal]}), "exit_code": 0, "stderr": ""}
        with self.assertRaises(jsonschema.ValidationError):
            matrix.parse_payload(raw, "format-patch-output.schema.json")
        value = matrix.parse_payload(raw, "format-patch-output.schema.json", patch_id_start=100)
        self.assertEqual(value["patches"][0]["identity"]["patch_id"], "PATCH-100")
        value["patches"][0]["identity"]["patch_id"] = "PATCH-AUTO"
        self.assertEqual(value["patches"][0], original)
        self.assertEqual(json.loads(raw["body"])["patches"][0], original)
        for bad_id in (None, 12, "", {}):
            invalid = copy.deepcopy(original)
            invalid["identity"]["patch_id"] = bad_id
            with self.assertRaises(jsonschema.ValidationError):
                matrix.parse_payload(dict(raw, body=json.dumps({"patches": [invalid]})), "format-patch-output.schema.json", patch_id_start=100)
        invalid = copy.deepcopy(original)
        invalid["target"]["document_sha256"] = "not-a-hash"
        with self.assertRaises(jsonschema.ValidationError):
            matrix.parse_payload(dict(raw, body=json.dumps({"patches": [invalid]})), "format-patch-output.schema.json", patch_id_start=100)

    def test_machine_hints_are_not_deterministic_defects(self) -> None:
        observed = deterministic_format_findings("- 盒盖关紧，水汽较难进入。")
        defects, candidates = matrix.split_machine_findings(observed)
        self.assertTrue(defects)
        self.assertTrue(candidates)
        self.assertTrue(all(item["status"] == "FAIL" for item in defects))
        self.assertTrue(all(item["status"] == "REVIEW_REQUIRED" for item in candidates))

    def test_machine_candidates_need_semantic_confirmation_before_repair(self) -> None:
        schema = json.loads((ROOT / "contracts/format-review-output.schema.json").read_text(encoding="utf-8"))
        categories = {key: True for key in schema["properties"]["reviewed_categories"]["properties"]}
        for confirmed in (False, True):
            initial = "- 打开盒子，取出卡片" if confirmed else "- 盒盖关紧，水汽较难进入"
            repaired = "- 打开盒子\n- 取出卡片"
            reviews, repairs = [], []

            def fake_agent(args, model, home, task, prompt_text, schema_name, *, resume_session=None):
                if schema_name == "format-agent-output.schema.json":
                    payload = {"answer": initial}
                elif schema_name == "format-review-output.schema.json":
                    reviews.append(prompt_text)
                    findings = [{"rule_id": "FMT-036", "status": "FAIL", "location": "LINE-0001", "old_text": initial,
                                 "reason": "两个可分别执行的动作仍挤在同行", "repair_scope": "sentence"}] if confirmed and not repairs else []
                    payload = {"reviewed_categories": categories, "findings": findings}
                else:
                    repairs.append(prompt_text)
                    self.assertTrue(confirmed)
                    proposal = exact_test_patch(initial, initial, repaired)
                    proposal["identity"]["patch_id"] = "PATCH-AUTO"
                    proposal["authorization"]["repair_scope"] = "sentence"
                    payload = {"patches": [proposal]}
                return {"body": json.dumps(payload, ensure_ascii=False), "exit_code": 0, "stderr": "", "events": [], "thread_id": "writer-session"}

            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                auth = root / "auth.json"
                auth.write_text("{}", encoding="utf-8")
                args = Namespace(auth=auth, max_repair_rounds=2, skill_snapshot_root=root / "snapshot")
                with patch.object(matrix, "call_clean_agent", side_effect=fake_agent), patch.object(matrix, "install_candidate"), patch.object(
                    matrix, "format_rule_bundle", return_value="- `FMT-036` 独立动作分行"
                ):
                    result = matrix.run_writer(args, "model", "model", root / "case", {})
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["answer"], repaired if confirmed else initial)
            self.assertEqual(result["first_deterministic_finding_count"], 0)
            self.assertEqual(result["first_machine_candidate_count"], 1)
            self.assertEqual(result["attempt_rounds"], int(confirmed))
            self.assertIn("FORMAT_PARALLEL_ITEMS_REVIEW", reviews[0])
            self.assertTrue(result["rounds"][0]["machine_review_candidates"])
            if confirmed:
                self.assertEqual(result["rounds"][0]["submitted_patches"][0]["identity"]["patch_id"], "PATCH-AUTO")
                self.assertEqual(result["rounds"][0]["patches"][0]["identity"]["patch_id"], "PATCH-100")

    def test_deterministic_checker_handles_protected_regions(self) -> None:
        text = "正文。\n\n`原样。`\n\n> 引文。\n"
        findings = deterministic_format_findings(text)
        count = [item["rule_id"] for item in findings].count("FORMAT_NO_CHINESE_FULL_STOP")
        self.assertEqual(count, 1)

    def test_deterministic_checker_detects_parenthetical_lowercase(self) -> None:
        findings = deterministic_format_findings("审核人员（auditor）")
        self.assertIn("FORMAT_PARENTHETICAL_ENGLISH_CASE", {item["rule_id"] for item in findings})

    def test_blank_line_inside_unheaded_list_is_hard_rejected(self) -> None:
        text = "- 可以确认甲\n- 可以确认乙\n\n- 不能确认丙\n- 不能确认丁"
        rules = {item["rule_id"] for item in deterministic_format_findings(text)}
        self.assertIn("FORMAT_LIST_INTERNAL_BLANK", rules)

    def test_safe_middleware_compacts_lists_and_aligns_comments(self) -> None:
        answer = "- 甲\n\n- 乙\n\n```python\n# 功能块说明\nx = 1 # 短\nlong_name = 2 # 长\n```"
        fixed, patches = matrix.apply_safe_format_middleware(answer)
        self.assertIn("- 甲\n- 乙", fixed)
        code_lines = [line for line in fixed.splitlines() if line.startswith(("x =", "long_name"))]
        self.assertEqual(code_lines[0].index("#"), code_lines[1].index("#"))
        self.assertGreaterEqual(len(patches), 2)

    def test_safe_middleware_separates_different_block_types(self) -> None:
        answer = "- 列表项\n> 引用内容\n## 标题\n正文"
        fixed, patches = matrix.apply_safe_format_middleware(answer)
        self.assertEqual(fixed, "- 列表项\n\n> 引用内容\n\n## 标题\n\n正文")
        self.assertEqual(len(patches), 3)

    def test_complete_per_line_code_does_not_also_require_block_header(self) -> None:
        answer = "```sql\nSELECT id -- 选择字段\nFROM t    -- 读取表\n```"
        rules = {item["rule_id"] for item in deterministic_format_findings(answer)}
        self.assertNotIn("FORMAT_CODE_BLOCK_HEADER", rules)
        self.assertNotIn("FORMAT_CODE_COMMENT_COVERAGE", rules)

    def test_inline_code_comment_enumeration_is_rejected(self) -> None:
        body = align_text(
            "-- 功能块块说明\nSELECT a, b -- 返回 a、b 两个字段\nFROM t -- 读取记录", marker="--",
        )
        rules = {
            item["rule_id"] for item in deterministic_format_findings(f"```sql\n{body}\n```")
        }
        self.assertIn("FORMAT_CODE_COMMENT_ENUMERATION", rules)

    def test_sql_block_comment_is_a_legal_header(self) -> None:
        body = align_text(
            "/* 功能块说明 */\nSELECT id -- 选择字段\nFROM t -- 读取表", marker="--",
        )
        rules = {
            item["rule_id"] for item in deterministic_format_findings(f"```sql\n{body}\n```")
        }
        self.assertNotIn("FORMAT_CODE_BLOCK_HEADER", rules)
        self.assertNotIn("FORMAT_CODE_COMMENT_COVERAGE", rules)

    def test_internal_boundary_label_is_rejected_in_markdown_heading(self) -> None:
        findings = deterministic_format_findings("## 记录身份与证据边界")
        self.assertIn("FORMAT_INTERNAL_BOUNDARY_LABEL", {item["rule_id"] for item in findings})

    def test_original_code_block_is_exempt_when_labeled(self) -> None:
        text = "## 原始查询\n\n```sql\nSELECT area\nFROM records;\n```"
        rules = {item["rule_id"] for item in deterministic_format_findings(text)}
        self.assertNotIn("FORMAT_CODE_COMMENT_COVERAGE", rules)
        text = "## 查询原件\n\n```sql\nSELECT area\nFROM records;\n```"
        rules = {item["rule_id"] for item in deterministic_format_findings(text)}
        self.assertNotIn("FORMAT_CODE_COMMENT_COVERAGE", rules)

    def test_commentable_code_requires_in_block_comment(self) -> None:
        plain = "```sql\nSELECT area\nFROM records;\n```"
        rules = {item["rule_id"] for item in deterministic_format_findings(plain)}
        self.assertIn("FORMAT_CODE_COMMENT_COVERAGE", rules)
        annotated = "```sql\n-- 查询记录\nSELECT area\nFROM records;\n```"
        rules = {item["rule_id"] for item in deterministic_format_findings(annotated)}
        self.assertNotIn("FORMAT_CODE_COMMENT_COVERAGE", rules)

    def test_json_comments_are_rejected(self) -> None:
        text = "```json\n{\"ok\": true} // 说明\n```"
        rules = {item["rule_id"] for item in deterministic_format_findings(text)}
        self.assertIn("FORMAT_JSON_COMMENT", rules)

    def test_inline_comment_alignment_is_measured_by_display_column(self) -> None:
        body = align_text("x = 1 # 短\nlong_name = 2 # 长\n", "#")
        text = "```python\n" + body + "```"
        rules = {item["rule_id"] for item in deterministic_format_findings(text)}
        self.assertNotIn("FORMAT_CODE_COMMENT_ALIGNMENT", rules)
        bad = text.replace("long_name = 2 #", "long_name = 2  #")
        rules = {item["rule_id"] for item in deterministic_format_findings(bad)}
        self.assertIn("FORMAT_CODE_COMMENT_ALIGNMENT", rules)

    def test_patch_binding_rejects_unknown_finding(self) -> None:
        payload = {"patches": [{"identity": {"finding_id": "FINDING-999"}}]}
        with self.assertRaisesRegex(Exception, "outside the current merged review set"):
            matrix.validate_patch_finding_bindings(payload, [{"finding_id": "FINDING-001"}])

    def test_findings_for_the_same_text_are_coalesced_before_patch(self) -> None:
        first = {"rule_id": "FMT-036", "location": "LINE-0010", "old_text": "甲；乙", "reason": "并列"}
        second = {"rule_id": "FMT-042", "location": "LINE-0010", "old_text": "甲；乙", "reason": "分号"}
        merged = matrix.merge_findings([first], [second])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["rule_id"], "FMT-036+FMT-042")

    def test_multiline_review_evidence_uses_one_line_patch_target(self) -> None:
        normalized = matrix.normalize_review_findings([{
            "rule_id": "FMT-093", "location": "table explanation",
            "old_text": "first line\nsecond line", "reason": "comparison is missing",
        }])
        self.assertEqual(normalized[0]["old_text"], "second line")

    def test_review_evidence_must_bind_to_the_current_answer(self) -> None:
        answer = "- 已经分行的动作一\n- 已经分行的动作二\n"
        findings = [{
            "rule_id": "FMT-036",
            "status": "FAIL",
            "location": "LINE-0001",
            "old_text": "- 已经分行的动作一和动作二",
            "reason": "stale evidence",
            "repair_scope": "sentence",
        }]
        grounded, rejected = matrix.ground_review_findings(answer, findings)
        self.assertEqual(grounded, [])
        self.assertEqual(len(rejected), 1)

    def test_noop_patch_does_not_discard_other_patch_proposals(self) -> None:
        payload = {
            "patches": [
                {"replacement": {"old_text": "旧", "new_text": "新"}},
                {"replacement": {"old_text": "不变", "new_text": "不变"}},
            ]
        }
        filtered, rejected = matrix.remove_noop_patches(payload)
        self.assertEqual(len(filtered["patches"]), 1)
        self.assertEqual(len(rejected), 1)

    def test_rejected_patch_feedback_never_fabricates_missing_line_endings(self) -> None:
        answer = "only line"
        proposal = exact_test_patch(answer, "only line\n", "new line\n")
        original = copy.deepcopy(proposal)
        with self.assertRaisesRegex(matrix.PatchError, "found 0") as caught:
            matrix.apply_minimal_transaction(answer, [proposal], matrix.line_nodes(answer))
        feedback = matrix.patch_failure_feedback(answer, [proposal], caught.exception)
        self.assertEqual(feedback["failed_patches"], [original])
        self.assertEqual(feedback["actual_nodes"][0]["text"], answer)
        self.assertEqual(feedback["actual_nodes"][0]["actual_occurrences"], 0)
        self.assertEqual(feedback["patch_error"], str(caught.exception))
        self.assertEqual(proposal, original)

    def test_repeated_full_stops_have_unique_line_context_and_protected_offsets(self) -> None:
        line = "保留 `值。`，条件甲。条件乙。条件丙"
        answer = line + "\r\n" + line
        findings = [item for item in deterministic_format_findings(answer) if item["rule_id"] == "FORMAT_NO_CHINESE_FULL_STOP"]
        self.assertEqual(len(findings), 2)
        finding = findings[0]
        self.assertEqual(finding["old_text"], line)
        self.assertEqual(finding["location"], "LINE-0001")
        self.assertEqual(finding["expected_occurrences"], 1)
        self.assertEqual(finding["matched_occurrences"], 2)
        columns = [index + 1 for index, char in enumerate(line) if char == "。"]
        self.assertEqual(finding["matched_columns_1based"], columns[1:])
        replacement = "".join("；" if index + 1 in columns[1:] else char for index, char in enumerate(line))
        proposal = exact_test_patch(answer, finding["old_text"], replacement)
        repaired = matrix.apply_minimal_transaction(answer, [proposal], matrix.line_nodes(answer))
        self.assertEqual(repaired, replacement + "\r\n" + line)
        self.assertIn("`值。`", repaired)
        self.assertEqual(deterministic_format_replacements(answer), [])

    def run_rejected_patch_scenario(self, defect: str, *, fail_again: bool = False) -> tuple[dict, list[dict]]:
        line = "条件甲。条件乙。条件丙"
        initial = line + "\n保留事实"
        corrected = line.replace("。", "；")
        schema = json.loads((ROOT / "contracts/format-review-output.schema.json").read_text(encoding="utf-8"))
        categories = {key: True for key in schema["properties"]["reviewed_categories"]["properties"]}
        repair_calls: list[dict] = []

        def fake_agent(args, model, home, task, prompt_text, schema_name, *, resume_session=None):
            if schema_name == "format-agent-output.schema.json":
                payload = {"answer": initial}
            elif schema_name == "format-review-output.schema.json":
                payload = {"reviewed_categories": categories, "findings": []}
            else:
                proposal = exact_test_patch(initial, line, corrected)
                if not repair_calls or fail_again:
                    if defect == "repeated_token":
                        proposal["replacement"].update(old_text="。", new_text="；")
                    elif defect == "invented_full_stop":
                        proposal["replacement"]["old_text"] = line + "。"
                    elif defect == "wrong_hash":
                        proposal["target"]["document_sha256"] = "0" * 64
                    elif defect == "invented_newline":
                        proposal = exact_test_patch(initial, "保留事实\n", "保留事实", "LINE-0002")
                    else:
                        raise AssertionError(defect)
                repair_calls.append({"prompt": prompt_text, "resume": resume_session, "proposal": copy.deepcopy(proposal)})
                payload = {"patches": [proposal]}
            return {"body": json.dumps(payload, ensure_ascii=False), "exit_code": 0, "stderr": "", "events": [], "thread_id": "writer-session"}

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            auth = root / "auth.json"
            auth.write_text("{}", encoding="utf-8")
            args = Namespace(auth=auth, max_repair_rounds=2, skill_snapshot_root=root / "snapshot")
            with patch.object(matrix, "call_clean_agent", side_effect=fake_agent), patch.object(
                matrix, "install_candidate"
            ), patch.object(matrix, "format_rule_bundle", return_value="RULES"):
                result = matrix.run_writer(args, "model", "model", root / "case", {})

        self.assertEqual(len(repair_calls), 2)
        self.assertEqual([call["resume"] for call in repair_calls], ["writer-session", "writer-session"])
        self.assertEqual(result["attempt_rounds"], 2)
        self.assertEqual(result["first_answer"], initial)
        self.assertEqual(result["first_draft_sha256"], matrix.sha256_text(initial))
        first, second = result["rounds"]
        self.assertEqual(first["submitted_patches"], [repair_calls[0]["proposal"]])
        self.assertEqual(first["before_sha256"], first["after_sha256"])
        self.assertEqual(second["round_input_sha256"], matrix.sha256_text(initial))
        self.assertFalse(first["repair_applied"])
        feedback = json.loads(repair_calls[1]["prompt"].split("LAST_REJECTED_TRANSACTION:\n", 1)[1].strip())
        self.assertEqual(feedback, first["patch_failure_feedback"])
        self.assertEqual(feedback["patch_error"], first["patch_error"])
        self.assertEqual(feedback["failed_patches"], first["patches"])
        self.assertEqual(feedback["document_sha256"], matrix.sha256_text(initial))
        return result, repair_calls

    def test_invalid_old_text_is_rejected_then_corrected_in_second_round(self) -> None:
        for defect, error, occurrences in (
            ("repeated_token", "found 2", 2),
            ("invented_full_stop", "found 0", 0),
            ("wrong_hash", "document hash mismatch", 1),
            ("invented_newline", "found 0", 0),
        ):
            with self.subTest(defect=defect):
                result, _ = self.run_rejected_patch_scenario(defect)
                self.assertEqual(result["status"], "PASS")
                self.assertEqual(result["repair_rounds"], 1)
                self.assertEqual(result["answer"], "条件甲；条件乙；条件丙\n保留事实")
                self.assertEqual(result["final_finding_count"], 0)
                self.assertIn(error, result["rounds"][0]["patch_error"])
                node = result["rounds"][0]["patch_failure_feedback"]["actual_nodes"][0]
                self.assertEqual(node["actual_occurrences"], occurrences)
                self.assertEqual(node["text"], "保留事实" if defect == "invented_newline" else "条件甲。条件乙。条件丙\n")

    def test_second_invalid_patch_terminates_with_original_answer_and_failed_attempts(self) -> None:
        result, _ = self.run_rejected_patch_scenario("invented_full_stop", fail_again=True)
        self.assertEqual(result["status"], "REVIEW_REQUIRED")
        self.assertEqual(result["repair_rounds"], 0)
        self.assertEqual(result["answer"], result["first_answer"])
        self.assertEqual(result["final_sha256"], result["first_draft_sha256"])
        self.assertGreater(result["final_finding_count"], 0)
        self.assertTrue(all(record["repair_attempted"] and not record["repair_applied"] for record in result["rounds"]))
        self.assertTrue(all("found 0" in record["patch_error"] for record in result["rounds"]))

    def test_machine_alignment_result_overrides_semantic_mismeasurement(self) -> None:
        findings = [{"rule_id": "FMT-075", "old_text": "aligned", "location": "LINE-0001"}]
        kept, rejected = matrix.filter_machine_decidable_findings(findings, [])
        self.assertEqual(kept, [])
        self.assertEqual(len(rejected), 1)

    def test_legacy_format_only_phase_excludes_initial_claim_and_exact_excerpt(self) -> None:
        findings = [
            {"rule_id": "FMT-008", "old_text": "初稿范围词"},
            {"rule_id": "FMT-098", "old_text": "> 连续原文片段"},
        ]
        task = {"source": {"content": "前缀 连续原文片段 后缀"}, "references": []}
        kept, rejected = matrix.filter_format_phase_findings(findings, "初稿范围词", task)
        self.assertEqual(kept, [])
        self.assertEqual(len(rejected), 2)

    def test_dual_scope_does_not_drop_initial_source_findings_by_rule_number(self) -> None:
        initial = "保存副本"
        task = {"source": {"content": "保存副本，编号 42 的原始录音不可改写"}, "references": []}
        for rule in ("FMT-008", "EXPL-012", "EXPL-013"):
            with self.subTest(rule=rule):
                finding = {"rule_id": rule, "location": "LINE-0001", "old_text": initial,
                           "reason": "初稿遗漏编号和原始录音不可改写的要求", "status": "REVIEW_REQUIRED"}
                grounded, _ = matrix.ground_review_findings(initial, [finding])
                kept, rejected = matrix.filter_format_phase_findings(
                    grounded, initial, task, review_scope=matrix.REVIEW_SCOPE,
                )
                self.assertEqual(kept, [finding])
                self.assertEqual(rejected, [])

    def test_prompts_review_initial_fidelity_and_allow_supported_local_explanation(self) -> None:
        reviewer = matrix.review_prompt({}, "正文", "RULES")
        self.assertIn("Use EXPL-012/013", reviewer)
        self.assertIn("FMT-008 retains its specific meaning", reviewer)
        self.assertIn("Check complete source fidelity in the initial draft", reviewer)
        self.assertNotIn("not a general factuality score for the initial draft", reviewer)
        repair = matrix.repair_prompt("正文", [], "RULES")
        self.assertIn("restore omitted source content", repair)
        self.assertIn("supported by the supplied materials and current rules", repair)
        self.assertIn("Do not invent facts, sources, rules or procedures", repair)
        self.assertIn("Do not regenerate the paragraph, section or full answer", repair)
        self.assertNotIn("Do not add a new rule, term, fact, source or procedure", repair)

    def test_initial_source_omission_reaches_repair_and_final_review_in_dual_scope(self) -> None:
        initial = "保存副本\n保留编号 42"
        source = "保存副本，原始录音不可改写；保留编号 42"
        task_payload = {"request": "保留完整信息并解释", "source": {"content": source}, "references": []}
        schema = json.loads((ROOT / "contracts/format-review-output.schema.json").read_text(encoding="utf-8"))
        categories = {key: True for key in schema["properties"]["reviewed_categories"]["properties"]}
        for rule in ("FMT-008", "EXPL-012", "EXPL-013"):
            for repairable in (True, False):
                with self.subTest(rule=rule, repairable=repairable), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    auth = root / "auth.json"
                    auth.write_text("{}", encoding="utf-8")
                    repairs = []

                    def fake_agent(args, model, home, task, prompt_text, schema_name, *, resume_session=None):
                        if schema_name == "format-agent-output.schema.json":
                            self.assertIn(source, prompt_text)
                            payload = {"answer": initial}
                        elif schema_name == "format-review-output.schema.json":
                            nodes = json.loads(prompt_text.split("CURRENT_ANSWER_LINE_NODES:\n", 1)[1])
                            missing = "原始录音不可改写" not in nodes[0]["text"]
                            payload = {"reviewed_categories": categories, "findings": [{
                                "rule_id": rule, "status": "REVIEW_REQUIRED", "location": "LINE-0001",
                                "old_text": "保存副本", "reason": "初稿遗漏原始录音不可改写的要求", "repair_scope": "phrase",
                            }] if missing else []}
                        else:
                            repairs.append(resume_session)
                            proposal = exact_test_patch(initial, "保存副本", "保存副本，原始录音不可改写")
                            proposal["authorization"].update(reason="恢复源材料明确要求", repair_scope="phrase")
                            proposal["verification"]["rerun_validators"] = ["EXPL-012", "EXPL-013"]
                            payload = {"patches": [proposal] if repairable else []}
                        return {"body": json.dumps(payload, ensure_ascii=False), "exit_code": 0,
                                "stderr": "", "events": [], "thread_id": "writer-session"}

                    with patch.object(matrix, "call_clean_agent", side_effect=fake_agent), patch.object(
                        matrix, "install_candidate"
                    ), patch.object(matrix, "format_rule_bundle", return_value=f"- `{rule}` 来源保真"):
                        result = matrix.run_writer(
                            Namespace(
                                auth=auth, max_repair_rounds=2,
                                skill_snapshot_root=root / "snapshot",
                            ),
                            "model", "model", root / "case", task_payload,
                        )
                    self.assertEqual(result["first_answer"], initial)
                    self.assertEqual(repairs, ["writer-session"] * (1 if repairable else 2))
                    self.assertEqual(result["repair_rounds"], 1 if repairable else 0)
                    if repairable:
                        self.assertEqual(result["status"], "PASS")
                        self.assertEqual(result["answer"], "保存副本，原始录音不可改写\n保留编号 42")
                    else:
                        self.assertEqual(result["status"], "REVIEW_REQUIRED")
                        self.assertEqual(result["answer"], initial)
                        self.assertIn(rule, result["final_finding_rule_ids"])
                        self.assertTrue(result["final_findings"])

    def test_list_items_created_by_one_patch_are_compacted(self) -> None:
        payload = {"patches": [{"replacement": {"new_text": "- 甲\n\n- 乙\n"}}]}
        compacted = matrix.compact_created_list_spacing(payload)
        self.assertEqual(compacted["patches"][0]["replacement"]["new_text"], "- 甲\n- 乙\n")

    def test_list_spacing_patch_only_joins_items_converted_together(self) -> None:
        answer = "first\n\nsecond\n\n- existing group\n\n- separate group"
        document_hash = forward_matrix.sha256_text(answer)
        payload = {"patches": []}
        for number, old_text, new_text, finding_id in (
            (1, "first\n", "- first\n", "FINDING-001"),
            (3, "second\n", "- second\n", "FINDING-002"),
        ):
            payload["patches"].append({
                "identity": {"patch_id": "P", "finding_id": finding_id, "operation": "replace_exact"},
                "target": {"document_sha256": document_hash, "node_id": f"LINE-{number:04d}"},
                "replacement": {"old_text": old_text, "new_text": new_text, "expected_occurrences": 1},
                "authorization": {"reason": "test", "repair_scope": "sentence", "preserve": []},
                "verification": {"rerun_validators": ["FMT-025"]},
            })
        expanded = matrix.add_list_spacing_patches(answer, payload)
        blank_targets = [patch["target"]["node_id"] for patch in expanded["patches"] if patch["replacement"]["new_text"] == ""]
        self.assertEqual(blank_targets, ["LINE-0002"])

    def test_run_codex_supplies_large_prompt_through_stdin(self) -> None:
        completed = subprocess.CompletedProcess(["codex"], 0, stdout=b"", stderr=b"")
        with patch.object(forward_matrix.subprocess, "run", return_value=completed) as mocked:
            forward_matrix.run_codex(["codex", "exec", "-"], {}, 5, stdin_text="规则包")
        kwargs = mocked.call_args.kwargs
        self.assertEqual(kwargs["input"], "规则包".encode("utf-8"))
        self.assertIsNone(kwargs["stdin"])

    def test_report_validator_accepts_redacted_complete_result(self) -> None:
        digest = "a" * 64
        payload = {
            "run_kind": "qualification", "qualification_id": "FORMAT-Q1",
            "models": ["gpt-5.6-sol"], "case_count": 1, "completed": 1,
            "max_repair_rounds": 2, "passed": 1, "failed": 0,
            "raw_answers_in_report": False, "automated_result_is_user_acceptance": False,
            "trigger_measurement": "declared_activation_proxy", "host_skill_routing_verified": False,
            "review_scope": ["format", "explanation"],
            "results": [{
                "case_id": "FWD-R8-001", "model": "gpt-5.6-sol",
                "expected_trigger": True, "trigger_activated": True, "trigger_pass": True,
                "trigger_access_violation_count": 0, "writing_status": "PASS", "status": "PASS",
                "access_violation_count": 0, "first_draft_sha256": digest,
                "final_sha256": digest, "repair_rounds": 1,
                "host_attempts": [{"attempt": 1, "status": "PASS"}],
            }],
        }
        self.assertEqual(report_validator.validate_report(payload), [])
        payload["review_scope"] = ["format"]
        self.assertTrue(any("review_scope" in error for error in report_validator.validate_report(payload)))
        payload["review_scope"] = ["format", "explanation"]
        payload["host_skill_routing_verified"] = True
        self.assertTrue(any("host Skill routing" in error for error in report_validator.validate_report(payload)))
        payload["host_skill_routing_verified"] = False
        for maximum in (None, 3, True):
            payload["max_repair_rounds"] = maximum
            self.assertTrue(any("max_repair_rounds" in error for error in report_validator.validate_report(payload)))

    def test_two_repairs_retain_failed_answer_and_use_independent_review_homes(self) -> None:
        initial = "甲和乙\n保留事实"
        current = initial
        calls = []
        patch_count = 0
        schema = json.loads((ROOT / "contracts/format-review-output.schema.json").read_text(encoding="utf-8"))
        categories = {key: True for key in schema["properties"]["reviewed_categories"]["properties"]}

        def fake_agent(args, model, home, task, prompt_text, schema_name, *, resume_session=None):
            nonlocal current, patch_count
            calls.append((schema_name, home, resume_session))
            if schema_name == "format-agent-output.schema.json":
                payload = {"answer": initial}
            elif schema_name == "format-review-output.schema.json":
                payload = {"reviewed_categories": categories, "findings": [{
                    "rule_id": "EXPL-001", "status": "REVIEW_REQUIRED", "location": "LINE-0001",
                    "old_text": current.splitlines()[0], "reason": "需要局部解释", "repair_scope": "phrase",
                }]}
            else:
                patch_count += 1
                old_text = current.splitlines()[0]
                new_text = ("甲、乙", "甲与乙")[patch_count - 1]
                payload = {"patches": [{
                    "identity": {"patch_id": "PATCH-001", "finding_id": "FINDING-001", "operation": "replace_exact"},
                    "target": {"node_id": "LINE-0001", "document_sha256": matrix.sha256_text(current)},
                    "replacement": {"old_text": old_text, "new_text": new_text, "expected_occurrences": 1},
                    "authorization": {"reason": "局部修复", "repair_scope": "phrase", "preserve": ["保留事实"]},
                    "verification": {"rerun_validators": ["EXPL-001"]},
                }]}
                current = current.replace(old_text, new_text, 1)
            return {"body": json.dumps(payload, ensure_ascii=False), "exit_code": 0, "stderr": "", "events": [], "thread_id": "writer-session"}

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            auth = root / "auth.json"
            auth.write_text("{}", encoding="utf-8")
            args = Namespace(auth=auth, max_repair_rounds=2, skill_snapshot_root=root / "snapshot")
            with patch.object(matrix, "call_clean_agent", side_effect=fake_agent), patch.object(
                matrix, "install_candidate"
            ), patch.object(matrix, "format_rule_bundle", return_value="- `EXPL-001` 当前解释规则"):
                result = matrix.run_writer(args, "model", "model", root / "case", {})
            self.assertEqual(result["status"], "REVIEW_REQUIRED")
            self.assertEqual(result["repair_rounds"], 2)
            self.assertEqual(result["attempt_rounds"], 2)
            self.assertEqual(result["first_answer"], initial)
            self.assertEqual(result["first_draft_sha256"], matrix.sha256_text(initial))
            self.assertEqual(result["answer"], "甲与乙\n保留事实")
            self.assertEqual(result["final_finding_count"], 1)
            self.assertEqual(result["final_findings"][0]["rule_id"], "EXPL-001")
            review_homes = [home for name, home, _ in calls if name == "format-review-output.schema.json"]
            self.assertEqual(len(set(review_homes)), 3)
            self.assertTrue(all(home != calls[0][1] for home in review_homes))
            repairs = [resume for name, _, resume in calls if name == "format-patch-output.schema.json"]
            self.assertEqual(repairs, ["writer-session", "writer-session"])

    def test_existing_attempt_is_never_reused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            attempt = root / "CASE-SOL/attempt-01"
            attempt.mkdir(parents=True)
            original = attempt / "result.json"
            original.write_text("original evidence", encoding="utf-8")
            with patch.object(matrix, "run_trigger") as trigger:
                with self.assertRaises(FileExistsError):
                    matrix.run_case_model(Namespace(), {"case_id": "CASE"}, "gpt-5.6-sol", "gpt-5.6-sol", root, 1)
            trigger.assert_not_called()
            self.assertEqual(original.read_text(encoding="utf-8"), "original evidence")

    def test_trigger_is_reported_as_proxy_and_miss_is_not_forced_to_activate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            row = {
                "case_id": "CASE", "request": "整理正文", "source": {"content": "原文"},
                "trigger_mode": "implicit", "expected_answer": "HIDDEN_ANSWER",
            }
            private = {"access_violations": [], "recovered_terminal_flush_error": False}
            with patch.object(matrix, "run_trigger", return_value=({"activated": False}, private)) as trigger, patch.object(
                matrix, "run_writer"
            ) as writer:
                result = matrix.run_case_model(Namespace(), row, "gpt-5.6-sol", "gpt-5.6-sol", root, 1)
            writer.assert_not_called()
            visible = trigger.call_args.args[-1]
            self.assertNotIn("expected_answer", visible)
            self.assertNotIn("trigger_mode", visible)
            self.assertEqual(result["trigger_measurement"], "declared_activation_proxy")
            self.assertIs(result["host_skill_routing_verified"], False)
            self.assertEqual(result["writing_status"], "NOT_RUN_TRIGGER_MISS")
            self.assertEqual(result["status"], "REVIEW_REQUIRED")

    def test_report_validator_rejects_private_answer_and_false_acceptance(self) -> None:
        payload = {
            "models": ["gpt-5.6-sol"], "case_count": 0, "completed": 0,
            "max_repair_rounds": 2, "passed": 0, "failed": 0,
            "raw_answers_in_report": False, "automated_result_is_user_acceptance": True,
            "results": [], "answer": "不应公开",
        }
        errors = report_validator.validate_report(payload)
        self.assertTrue(any("user acceptance" in error for error in errors))
        self.assertTrue(any("private keys" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
