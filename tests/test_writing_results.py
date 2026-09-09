"""Check actual negative outputs, never promote routing-only records to passes."""

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts.render_writing_results import render
from scripts.validate_clean_agent_format_matrix import validate_report


class WritingResultTests(unittest.TestCase):
    def report(self, answer="27"):
        return {
            "run_kind": "qualification", "qualification_id": "TEST-Q1", "models": ["model"],
            "case_count": 1, "completed": 1, "passed": 1, "failed": 0, "max_repair_rounds": 2,
            "automated_result_is_user_acceptance": False, "raw_answers_in_report": False,
            "trigger_measurement": "declared_activation_proxy", "host_skill_routing_verified": False,
            "review_scope": ["format", "explanation"], "results": [{
                "case_id": "CASE", "model": "model", "model_code": "MODEL", "expected_trigger": False,
                "trigger_activated": False, "trigger_pass": True, "trigger_access_violation_count": 0,
                "writing_status": "NOT_APPLICABLE", "status": "PASS", "negative_output_status": "PASS",
                "negative_output_exact": True, "negative_output_access_violation_count": 0,
                "negative_output_sha256": hashlib.sha256(answer.encode()).hexdigest(),
                "host_attempts": [{"attempt": 1, "status": "PASS"}],
            }],
        }

    def test_negative_requires_observed_output_not_only_classification(self):
        report = self.report()
        self.assertEqual(validate_report(report), [])
        for field, value in (("writing_status", "NOT_RUN"), ("negative_output_status", None),
                             ("negative_output_exact", False), ("negative_output_access_violation_count", 1),
                             ("negative_output_sha256", None)):
            changed = copy.deepcopy(report)
            changed["results"][0][field] = value
            with self.subTest(field=field):
                self.assertTrue(validate_report(changed))

    def test_render_keeps_actual_negative_body_and_rejects_false_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report_path, request_path = root / "report.json", root / "requests.jsonl"
            private = root / "run/CASE-MODEL/attempt-01"
            private.mkdir(parents=True)
            request_path.write_text(json.dumps({"case_id": "CASE", "request": "仅复制", "source": {"content": "27"}}) + "\n", encoding="utf-8")
            report_path.write_text(json.dumps(self.report()), encoding="utf-8")
            (private / "result.json").write_text(json.dumps({"private": {"negative_output": {"payload": {"answer": "27"}}}}), encoding="utf-8")
            render(report_path, root / "run", request_path, root / "view")
            self.assertEqual((root / "view/CASE-MODEL-answer.md").read_bytes(), b"27")
            wrong = self.report("28")
            report_path.write_text(json.dumps(wrong), encoding="utf-8")
            (private / "result.json").write_text(json.dumps({"private": {"negative_output": {"payload": {"answer": "28"}}}}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "differs from source"):
                render(report_path, root / "run", request_path, root / "bad-view")
            wrong["results"][0].update(status="REVIEW_REQUIRED", negative_output_status="REVIEW_REQUIRED")
            report_path.write_text(json.dumps(wrong), encoding="utf-8")
            render(report_path, root / "run", request_path, root / "failed-view")
            self.assertEqual((root / "failed-view/CASE-MODEL-answer.md").read_bytes(), b"28")


if __name__ == "__main__":
    unittest.main()
