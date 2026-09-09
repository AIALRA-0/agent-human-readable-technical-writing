"""Synthetic app wrappers; real D4 data is only used via explicit opt-in paths.

No private session text is a checked-in fixture and no test starts a model.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import collect_native_writing_evidence as collector


def event(item: dict) -> dict:
    return {"type": "response_item", "payload": item}


def final(text: str, identifier: str = "answer", **extra) -> dict:
    return event({"type": "message", "id": identifier, "role": "assistant", "phase": "final_answer",
                  "content": [{"type": "output_text", "text": text}], **extra})


def js_call(identifier: str, command: str, *, plain: bool = True, **args) -> dict:
    arguments = json.dumps({"cmd": command, **args}, ensure_ascii=False)
    code = f"const r = await tools.exec_command({arguments});\ntext(r.output);\n" if plain else (
        f"const r = await tools.exec_command({arguments});\ntext(r);\n")
    return event({"type": "custom_tool_call", "call_id": identifier, "name": "exec",
                  "status": "completed", "input": code})


def text_await_call(identifier: str, command: str, **args) -> dict:
    arguments = json.dumps({"cmd": command, **args}, ensure_ascii=False)
    return event({"type": "custom_tool_call", "call_id": identifier, "name": "exec",
                  "status": "completed", "input": f"text(await tools.exec_command({arguments}));"})


def app_output(identifier: str, body: str, *, plain: bool = True, code=0, success=True, **extra) -> dict:
    result = body if plain else json.dumps({"exit_code": code, "wall_time_seconds": 0.3,
                                            "output": body, **extra}, ensure_ascii=False)
    return event({"type": "custom_tool_call_output", "call_id": identifier, "output": [
        {"type": "input_text", "text": f"Script {'completed' if success else 'failed'}\nWall time 0.3 seconds\nOutput:\n"},
        {"type": "input_text", "text": result},
    ]})


# A real subprocess uses a deliberately distinct frozen reviewer. It rejects repair
# flags and verifies isolation; this catches accidental fallback to the repository.
FROZEN_REVIEWER = '''
import argparse, hashlib, json, pathlib, sys
p = argparse.ArgumentParser()
p.add_argument("--input", type=pathlib.Path, required=True)
p.add_argument("--report", type=pathlib.Path, required=True)
args = p.parse_args()
assert sys.dont_write_bytecode and sys.flags.isolated
assert pathlib.Path.cwd() == args.input.parent
body = args.input.read_bytes()
digest = hashlib.sha256(body).hexdigest()
report = {"format": {"status": "PASS", "repair_rounds": 0,
    "input_sha256": digest, "document_sha256": digest, "text": body.decode("utf-8"),
    "findings": [{"private_text": "DO_NOT_COPY_REVIEWER_TEXT"}], "candidates": []},
    "extra_private_text": "DO_NOT_COPY_REVIEWER_TEXT"}
args.report.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
'''

# Keep the legacy reviewer above option-unaware to test frozen-version compatibility.
SPACING_REVIEWER = FROZEN_REVIEWER.replace(
    'args = p.parse_args()',
    'p.add_argument("--nested-list-spacing", choices=("compact", "host-required"), default="compact")\n'
    'args = p.parse_args()',
).replace(
    'args.report.write_text',
    'report["format"]["findings"] = ([{"rule": "nested-blank"}] * '
    'body.count(b"\\n\\n  -") if args.nested_list_spacing == "compact" else [])\n'
    'args.report.write_text',
)


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.skill = self.root / "frozen" / "human-readable-technical-writing"
        for relative in collector.FILES:
            target = self.skill / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            # These words are valid rule text, not tool diagnostics.
            target.write_bytes(f"# Complete {relative}\nRules mention error, failed, permission, omitted and truncated\n".encode())
        reviewer = self.skill / collector.REVIEWER
        reviewer.parent.mkdir(parents=True)
        reviewer.write_bytes(FROZEN_REVIEWER.encode("utf-8"))
        self.session = self.root / "one.jsonl"

    def write_session(self, events):
        self.session.write_bytes("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in events).encode("utf-8"))

    def reads(self, names=collector.FILES, *, identifier="read", plain=True, **output_args):
        command = "; ".join(f"Get-Content -Raw '{self.skill / name}'" for name in names)
        body = "\r\n".join((self.skill / name).read_bytes().decode("utf-8") for name in names)
        return [js_call(identifier, command, plain=plain), app_output(identifier, body, plain=plain, **output_args)]

    def literal_path_list_command(self, names):
        return "Get-Content -LiteralPath " + ",".join(f"'{self.skill / name}'" for name in names) + " -Raw"

    def evidence(self, events):
        with patch.object(collector.subprocess, "run", side_effect=AssertionError("no commands from sessions may execute")):
            return collector.tool_evidence(events, self.skill)

    def assert_no_reads(self, events):
        evidence = self.evidence(events)
        self.assertEqual(sum(evidence["read_counts"].values()), 0)
        self.assertFalse(evidence["reference_reread_proven"])
        return evidence

    def collect(self, events, name="private-new", **options):
        self.write_session(events)
        original = self.session.read_bytes()
        output = self.root / name
        result = collector.collect(self.session, self.skill, output, **options)
        self.assertEqual(self.session.read_bytes(), original)
        read = json.loads((output / "read-evidence.json").read_bytes())
        review = json.loads((output / "writing-review.json").read_bytes())
        return output, result, read, review

    def test_d4_plain_wrapper_failed_attempt_then_one_skill_and_two_refs(self):
        failed_read = self.reads(("SKILL.md",), identifier="failed", success=False)
        # The D4 outer call itself was completed, while its output says Script failed.
        failed_read[1]["payload"]["output"][1]["text"] = "Script error:\nexec_command failed: CreateProcess"
        events = failed_read + self.reads(("SKILL.md",), identifier="skill") + self.reads(collector.FILES[1:], identifier="refs")
        evidence = self.evidence(events)
        self.assertEqual(evidence["read_counts"], dict.fromkeys(collector.FILES, 1))
        self.assertTrue(evidence["complete_skill_and_two_references"])
        self.assertFalse(evidence["reference_reread_proven"])
        self.assertEqual(evidence["rejected_calls"], {"failed": 1})
        self.assertEqual(len(evidence["accepted_calls"]), 2)
        self.assertTrue(all(row["success_evidence"] == "script_completed_full_output_exit_unavailable"
                            for row in evidence["accepted_calls"]))

    def test_text_result_json_wrapper_proves_exit_zero(self):
        evidence = self.evidence(self.reads(plain=False))
        self.assertEqual(evidence["read_counts"], dict.fromkeys(collector.FILES, 1))
        self.assertEqual(evidence["accepted_calls"][0]["success_evidence"], "process_exit_zero")

    def test_unquoted_js_keys_and_single_quoted_literals(self):
        events = self.reads(("SKILL.md",))
        command = f'Get-Content -LiteralPath "{(self.skill / "SKILL.md").as_posix()}" -Raw'
        events[0]["payload"]["input"] = f"let result = await tools.exec_command({{cmd: '{command}', max_output_tokens: 20000, login: false}}); text(result.output);"
        self.assertEqual(self.evidence(events)["read_counts"]["SKILL.md"], 1)

    def test_text_await_exec_command_literal_wrapper_requires_verified_complete_output(self):
        command = f"Get-Content -Raw '{self.skill / 'SKILL.md'}'"
        body = (self.skill / "SKILL.md").read_text()
        valid = [text_await_call("awaited", command), app_output("awaited", body, plain=False)]
        evidence = self.evidence(valid)
        self.assertEqual(evidence["read_counts"]["SKILL.md"], 1)
        self.assertEqual(evidence["accepted_calls"][0]["success_evidence"], "process_exit_zero")

        self.assert_no_reads([text_await_call("failed", command), app_output("failed", body, plain=False, code=1)])
        self.assert_no_reads([text_await_call("missing", command)])
        self.assert_no_reads([text_await_call("truncated", command), app_output(
            "truncated", body + "\nWarning: truncated output (original token count: 10000)", plain=False)])
        self.assert_no_reads([event({"type": "custom_tool_call", "call_id": "pseudo", "name": "exec",
                                     "status": "completed", "input": f"text({json.dumps(valid[0]['payload']['input'])});"}),
                              app_output("pseudo", body, plain=False)])
        wrong = self.root / "wrong-root" / "SKILL.md"
        mismatch = [text_await_call("mismatch", f"Get-Content -Raw '{wrong}'"),
                    app_output("mismatch", body, plain=False)]
        evidence = self.assert_no_reads(mismatch)
        self.assertEqual(evidence["other_root_same_content_read_counts"]["SKILL.md"], 1)

    def test_literalpath_comma_list_requires_verified_complete_output(self):
        names = collector.FILES[1:]
        command = self.literal_path_list_command(names)
        body = "\r\n".join((self.skill / name).read_text() for name in names)
        valid = [js_call("literal-list", command, plain=False), app_output("literal-list", body, plain=False)]
        evidence = self.evidence(valid)
        self.assertEqual(evidence["read_counts"], {"SKILL.md": 0, names[0]: 1, names[1]: 1})

        self.assert_no_reads([js_call("failed", command, plain=False), app_output("failed", body, plain=False, code=1)])
        self.assert_no_reads([js_call("missing", command, plain=False)])
        self.assert_no_reads([js_call("truncated", command, plain=False), app_output(
            "truncated", body + "\n[output truncated]", plain=False)])
        self.assert_no_reads([event({"type": "custom_tool_call", "call_id": "pseudo", "name": "exec",
                                     "status": "completed", "input": f"text({json.dumps(valid[0]['payload']['input'])});"}),
                              app_output("pseudo", body, plain=False)])
        wrong_names = tuple(self.root / "wrong-root" / name for name in names)
        wrong_command = "Get-Content -LiteralPath " + ",".join(f"'{path}'" for path in wrong_names) + " -Raw"
        evidence = self.assert_no_reads([js_call("mismatch", wrong_command, plain=False),
                                         app_output("mismatch", body, plain=False)])
        self.assertEqual(evidence["other_root_same_content_read_counts"], {"SKILL.md": 0, names[0]: 1, names[1]: 1})

    def test_relative_paths_require_explicit_workdir(self):
        events = self.reads(("SKILL.md",))
        events[0] = js_call("read", "Get-Content -Raw 'SKILL.md'", workdir=str(self.skill))
        self.assertEqual(self.evidence(events)["read_counts"]["SKILL.md"], 1)
        events[0] = js_call("read", "Get-Content -Raw 'SKILL.md'")
        self.assert_no_reads(events)

    def test_rule_text_may_contain_diagnostic_examples(self):
        path = self.skill / "SKILL.md"
        path.write_bytes(b"error failed permission denied truncated\nWarning: truncated output\nGet-Content: example\n")
        for plain in (True, False):
            with self.subTest(plain=plain):
                self.assertEqual(self.evidence(self.reads(("SKILL.md",), plain=plain))["read_counts"]["SKILL.md"], 1)

    def test_real_failure_statuses_even_with_complete_body(self):
        for code in (1, -1, 7):
            self.assert_no_reads(self.reads(plain=False, code=code))
        for override in ({"isError": True}, {"status": "failed"}, {"error": "failure"}, {"session_id": 123}):
            self.assert_no_reads(self.reads(plain=False, **override))
        for code in (None, False, "0"):
            self.assert_no_reads(self.reads(plain=False, code=code))
        self.assert_no_reads(self.reads(success=False))
        events = self.reads()
        events[0]["payload"]["status"] = "in_progress"
        self.assert_no_reads(events)
        events = self.reads()
        events[1]["payload"]["isError"] = True
        self.assert_no_reads(events)

    def test_plain_failed_command_diagnostic_outside_file(self):
        events = self.reads()
        events[1]["payload"]["output"][1]["text"] += "\nGet-Content: Cannot find path\n"
        self.assertEqual(self.assert_no_reads(events)["rejected_calls"], {"failed": 1})

    def test_missing_status_wrapper_missing_output_and_orphans(self):
        events = self.reads()
        self.assert_no_reads(events[:1])
        self.assert_no_reads(events[1:])
        for header in ("", "Script running with cell ID abc", "Script completed"):
            altered = copy.deepcopy(events)
            altered[1]["payload"]["output"][0]["text"] = header
            self.assert_no_reads(altered)
        events[1]["payload"]["call_id"] = "wrong-call"
        self.assert_no_reads(events)

    def test_truncation_and_partial_output_never_count(self):
        for plain in (True, False):
            for marker in ("Warning: truncated output (original token count: 10000)", "…500 tokens truncated…", "[output truncated]"):
                events = self.reads(plain=plain)
                if plain:
                    events[1]["payload"]["output"][1]["text"] += "\n" + marker
                else:
                    data = json.loads(events[1]["payload"]["output"][1]["text"])
                    data["output"] += "\n" + marker
                    events[1]["payload"]["output"][1]["text"] = json.dumps(data)
                self.assert_no_reads(events)
        self.assert_no_reads(self.reads(plain=False, truncated=True))
        events = self.reads(("SKILL.md",))
        events[1]["payload"]["output"][1]["text"] = (self.skill / "SKILL.md").read_text()[:-5]
        self.assert_no_reads(events)

    def test_same_call_and_operands_are_deduplicated_distinct_calls_prove_reread(self):
        events = self.reads()
        mirrored = copy.deepcopy(events)
        mirrored[1]["payload"]["id"] = "different-transport-record"
        evidence = self.evidence(events + mirrored)
        self.assertEqual(evidence["read_counts"], dict.fromkeys(collector.FILES, 1))
        self.assertFalse(evidence["reference_reread_proven"])
        repeated_operand = self.reads(("SKILL.md", "SKILL.md"))
        self.assertEqual(self.evidence(repeated_operand)["read_counts"]["SKILL.md"], 1)
        reread = self.evidence(events + self.reads(collector.FILES[1:], identifier="reread"))
        self.assertTrue(reread["reference_reread_proven"])
        self.assertEqual(reread["read_counts"]["SKILL.md"], 1)

    def test_conflicting_duplicate_outputs_fail_closed(self):
        events = self.reads()
        conflict = copy.deepcopy(events[1])
        conflict["payload"]["output"][0]["text"] = "Script failed\nWall time 0.3 seconds\nOutput:\n"
        self.assert_no_reads(events + [conflict])

    def test_shell_path_mentions_partial_reads_and_injected_echoes_are_not_evidence(self):
        target = self.skill / "SKILL.md"
        commands = [
            f"Write-Output '{target}'", f"echo \"Get-Content '{target}'\"",
            f"Get-Content -Raw '{target}'; Write-Output 'fabricated file contents'",
            f"if ($false) {{ Get-Content '{target}' }}", f"Get-Content -TotalCount 1 '{target}'",
            f"Get-Content '{target}' | Select-Object -First 1",
            f"cat '{target}' > somewhere", f"Get-Content -Raw '{target}' # comment",
            "Get-Content -Raw 'unrelated.md'",
        ]
        for command in commands:
            with self.subTest(command=command):
                events = self.reads(("SKILL.md",))
                events[0] = js_call("read", command)
                self.assert_no_reads(events)

    def test_untrusted_js_cannot_forge_path_execution_or_text_forwarding(self):
        base = self.reads(("SKILL.md",))
        code = base[0]["payload"]["input"]
        commands = [
            "text(" + json.dumps(code) + ");", "if (false) { " + code + " }",
            "// " + code.replace("\n", " "),
            code + 'text("injected");',
            code.replace("text(r.output)", 'text("injected")'),
            code.replace("text(r.output)", 'text(r.output + "injected")'),
            code.replace("text(r.output)", 'r.output = "injected"; text(r.output)'),
            "const tools = {exec_command: async () => ({output: 'fake'})}; " + code,
            "const text = () => {}; " + code,
            code.replace('"cmd":', 'get cmd() { return "fake"; }, "cmd":'),
            code.replace('"cmd":', '"cmd": "fake", "cmd":'),
            code.replace("tools.exec_command", "unknown.exec_command"),
            code.replace("await tools.exec_command", "await eval"),
        ]
        for candidate in commands:
            events = copy.deepcopy(base)
            events[0]["payload"]["input"] = candidate
            self.assert_no_reads(events)

    def test_direct_exec_command_and_cli_completed_item(self):
        command = f"Get-Content -Raw '{self.skill / 'SKILL.md'}'"
        body = (self.skill / "SKILL.md").read_text()
        direct = [
            event({"type": "function_call", "name": "exec_command", "call_id": "direct",
                   "arguments": json.dumps({"cmd": command})}),
            event({"type": "function_call_output", "call_id": "direct",
                   "output": json.dumps({"exit_code": 0, "output": body})}),
        ]
        cli = {"type": "item.completed", "item": {"type": "command_execution", "id": "cli",
               "command": command, "exit_code": 0, "status": "completed", "aggregated_output": body}}
        self.assertEqual(self.evidence(direct + [cli])["read_counts"]["SKILL.md"], 2)
        cli["type"] = "item.started"
        self.assert_no_reads([cli])

    def test_snapshot_contents_and_root_are_both_required(self):
        events = self.reads(("SKILL.md",))
        wrong_path = ROOT / "SKILL.md"  # No repository contents are read for this assertion.
        events[0] = js_call("read", f"Get-Content -Raw '{wrong_path}'")
        evidence = self.assert_no_reads(events)
        self.assertEqual(evidence["other_root_same_content_read_counts"]["SKILL.md"], 1)
        events = self.reads(("SKILL.md",))
        events[1]["payload"]["output"][1]["text"] = "different version of SKILL.md"
        self.assert_no_reads(events)

    def test_latest_complete_final_hashes_and_frozen_review_real_subprocess(self):
        text = "\ufeff最新正文。\r\n\r\n保留原样；  \t\r\n"
        latest = final(text, "latest")
        events = self.reads() + [final("旧答案", "old"), latest, copy.deepcopy(latest),
                                 final("未完整消息", "partial", status="in_progress")]
        output, result, evidence, review = self.collect(events)
        self.assertTrue(result["completed"])
        self.assertEqual(review["status"], "COMPLETED")
        self.assertEqual(review["format"]["finding_count"], 1)  # Distinct frozen stub, not ROOT checker.
        self.assertEqual(review["reviewer_sha256"], collector.sha256_bytes(FROZEN_REVIEWER.encode()))
        self.assertEqual((output / "final.md").read_bytes(), text.encode())
        self.assertEqual(evidence["visible_final_turns"], 2)
        self.assertEqual(evidence["original_final_sha256"], evidence["redacted_final_sha256"])
        self.assertFalse(evidence["redaction_applied"])
        self.assertEqual(review["beginner_understanding"], "NOT_ASSESSED")
        self.assertEqual(review["format"]["repair_rounds"], 0)
        self.assertNotIn("DO_NOT_COPY_REVIEWER_TEXT", (output / "writing-review.json").read_text())
        self.assertEqual({path.name for path in output.iterdir()}, {"final.md", "read-evidence.json", "writing-review.json"})
        self.assertFalse(list(self.skill.rglob("*.pyc")))

    def test_collect_spacing_is_explicit_recorded_and_preserves_sources_and_outputs(self):
        (self.skill / collector.REVIEWER).write_bytes(SPACING_REVIEWER.encode("utf-8"))
        body = "\ufeff- 父项\r\n\r\n  - 子项；  \t\r\n- 下一项\n\n  - 子项\n"
        # Include two LF-separated nested lists without normalizing the original bytes.
        body += "- 最后一项\n\n  - 子项\n"
        sources = {p.relative_to(self.skill): p.read_bytes() for p in self.skill.rglob("*") if p.is_file()}
        saved_outputs = {}
        for name, options, expected_count in (
            ("default", {}, 2),
            ("compact", {"nested_list_spacing": "compact"}, 2),
            ("host-required", {"nested_list_spacing": "host-required"}, 0),
        ):
            with self.subTest(name=name), patch.object(collector.subprocess, "run", wraps=subprocess.run) as run:
                output, result, evidence, review = self.collect([final(body)], name=name, **options)
                choice = options.get("nested_list_spacing", "compact")
                self.assertEqual(result["review_status"], "COMPLETED")
                self.assertEqual(evidence["nested_list_spacing"], choice)
                self.assertEqual(review["nested_list_spacing"], choice)
                self.assertEqual(review["format"]["finding_count"], expected_count)
                self.assertEqual(review["reviewer_sha256"], collector.sha256_bytes(SPACING_REVIEWER.encode()))
                run.assert_called_once()
                command = run.call_args.args[0]
                expected = [sys.executable, "-I", "-B", "-X", "utf8", str(self.skill / collector.REVIEWER),
                            "--input", str(output / "final.md"), "--report", str(output / "writing-review.json")]
                if choice == "host-required":
                    expected += ["--nested-list-spacing", "host-required"]
                self.assertEqual(command, expected)
                self.assertEqual((output / "final.md").read_bytes(), body.encode("utf-8"))
                self.assertEqual(evidence["original_final_sha256"], evidence["redacted_final_sha256"])
                self.assertEqual({p.name for p in output.iterdir()},
                                 {"final.md", "read-evidence.json", "writing-review.json"})
                saved_outputs[output] = {p.name: p.read_bytes() for p in output.iterdir()}
        self.assertEqual(sources, {p.relative_to(self.skill): p.read_bytes()
                                  for p in self.skill.rglob("*") if p.is_file()})
        for output, saved in saved_outputs.items():
            with self.assertRaises(FileExistsError):
                collector.collect(self.session, self.skill, output, nested_list_spacing="host-required")
            self.assertEqual(saved, {p.name: p.read_bytes() for p in output.iterdir()})

    def test_invalid_spacing_is_not_recorded_as_an_actual_review_choice(self):
        self.write_session([final("正文")])
        output = self.root / "invalid-spacing"
        for choice in (None, "HOST_REQUIRED", "host-required ", ""):
            with self.subTest(choice=choice), patch.object(collector.subprocess, "run", side_effect=AssertionError("invalid choice")):
                with self.assertRaises(ValueError):
                    collector.collect(self.session, self.skill, output, nested_list_spacing=choice)
                with self.assertRaises(ValueError):
                    collector.mechanical_review(self.skill, output, b"body", nested_list_spacing=choice)
                self.assertFalse(output.exists())

    def test_mechanical_review_default_and_explicit_compact_support_legacy_frozen_reviewer(self):
        for name, options in (("default", {}), ("explicit", {"nested_list_spacing": "compact"})):
            with self.subTest(name=name), patch.object(collector.subprocess, "run", wraps=subprocess.run) as run:
                output = self.root / name
                output.mkdir()
                body = b"- parent\n\n  - child\n"
                (output / "final.md").write_bytes(body)
                review = collector.mechanical_review(self.skill, output, body, **options)
                self.assertEqual(review["status"], "COMPLETED")
                self.assertEqual(review["nested_list_spacing"], "compact")
                self.assertEqual(review["format"]["finding_count"], 1)
                run.assert_called_once()
                self.assertNotIn("--nested-list-spacing", run.call_args.args[0])

    def test_cli_spacing_selection_and_unsupported_frozen_option_never_fall_back(self):
        body = "- 父项\n\n  - 子项\n"
        self.write_session([final(body)])
        original = self.session.read_bytes()
        for name, reviewer, flags, choice, status, exit_code in (
            ("legacy-default", FROZEN_REVIEWER, [], "compact", "COMPLETED", 0),
            ("legacy-compact", FROZEN_REVIEWER, ["--nested-list-spacing", "compact"], "compact", "COMPLETED", 0),
            ("supported-host", SPACING_REVIEWER, ["--nested-list-spacing", "host-required"], "host-required", "COMPLETED", 0),
            ("unsupported-host", FROZEN_REVIEWER, ["--nested-list-spacing", "host-required"], "host-required", "FROZEN_REVIEW_FAILED", 2),
        ):
            with self.subTest(name=name):
                (self.skill / collector.REVIEWER).write_bytes(reviewer.encode())
                sources = {p.relative_to(self.skill): p.read_bytes() for p in self.skill.rglob("*") if p.is_file()}
                output = self.root / name
                with patch.object(collector.subprocess, "run", wraps=subprocess.run) as run, patch("builtins.print"):
                    code = collector.main(["--session", str(self.session), "--skill-root", str(self.skill),
                                           "--output", str(output), *flags])
                self.assertEqual(code, exit_code)
                run.assert_called_once()
                command = run.call_args.args[0]
                self.assertEqual(command[5], str(self.skill / collector.REVIEWER))
                self.assertEqual(command[10:], ["--nested-list-spacing", "host-required"]
                                 if choice == "host-required" else [])
                review = json.loads((output / "writing-review.json").read_bytes())
                evidence = json.loads((output / "read-evidence.json").read_bytes())
                self.assertEqual(review["status"], status)
                self.assertEqual(review["nested_list_spacing"], choice)
                self.assertEqual(evidence["nested_list_spacing"], choice)
                self.assertEqual(review["reviewer_sha256"], collector.sha256_bytes(reviewer.encode()))
                self.assertEqual(review["exit_code"], exit_code)
                if status == "FROZEN_REVIEW_FAILED":
                    self.assertNotIn("format", review)
                self.assertEqual((output / "final.md").read_bytes(), body.encode())
                self.assertEqual(self.session.read_bytes(), original)
                self.assertEqual(sources, {p.relative_to(self.skill): p.read_bytes()
                                          for p in self.skill.rglob("*") if p.is_file()})

    def test_hidden_user_commentary_and_tool_private_data_are_not_serialized(self):
        events = [
            event({"type": "reasoning", "summary": "HIDDEN_CANARY", "encrypted_content": "HIDDEN_CIPHER"}),
            event({"type": "message", "role": "user", "content": [{"type": "input_text", "text": "USER_CANARY"}]}),
            {"type": "event_msg", "payload": {"type": "agent_reasoning", "text": "HIDDEN_CANARY"}},
            {"type": "event_msg", "payload": {"type": "agent_message", "phase": "final_answer", "message": "mirror"}},
            final("COMMENTARY_CANARY", phase="commentary"),
        ] + self.reads() + [final("可见正文")]
        events[-2]["payload"]["output"][1]["text"] += "\nTOOL_CANARY password=credential\n"
        output, _, evidence, _ = self.collect(events)
        saved = "".join(path.read_text(encoding="utf-8") for path in output.iterdir())
        projected = json.dumps(collector.load_events(self.session))
        for marker in ("HIDDEN_CANARY", "HIDDEN_CIPHER", "USER_CANARY", "COMMENTARY_CANARY"):
            self.assertNotIn(marker, projected)
        for marker in ("HIDDEN_CANARY", "USER_CANARY", "TOOL_CANARY", "credential", "Get-Content", str(self.session)):
            self.assertNotIn(marker, saved)
        self.assertEqual(evidence["visible_final_turns"], 1)

    def test_redaction_tracks_original_and_redacted_hashes(self):
        original = 'token=abc123\n"password": "two words"\n-----BEGIN PRIVATE KEY-----\nsecret-key\n-----END PRIVATE KEY-----'
        output, _, evidence, review = self.collect([final(original)])
        saved = (output / "final.md").read_bytes()
        self.assertTrue(evidence["redaction_applied"])
        self.assertEqual(evidence["original_final_sha256"], collector.sha256_bytes(original.encode()))
        self.assertEqual(evidence["redacted_final_sha256"], collector.sha256_bytes(saved))
        self.assertNotEqual(evidence["original_final_sha256"], evidence["redacted_final_sha256"])
        self.assertEqual(review["format"]["input_sha256"], evidence["redacted_final_sha256"])
        for secret in ("abc123", "two words", "secret-key"):
            self.assertNotIn(secret, "".join(p.read_text(encoding="utf-8") for p in output.iterdir()))
        self.assertNotIn("unfinished-key", collector.redact_credentials("-----BEGIN RSA PRIVATE KEY-----\nunfinished-key"))

    def test_no_final_is_status_only_and_never_runs_reviewer(self):
        with patch.object(collector.subprocess, "run", side_effect=AssertionError("no final to review")):
            output, result, evidence, review = self.collect(self.reads())
        self.assertFalse(result["completed"])
        self.assertFalse((output / "final.md").exists())
        self.assertEqual(evidence["status"], "INCOMPLETE_NO_FINAL")
        self.assertIsNone(evidence["original_final_sha256"])
        self.assertIsNone(evidence["redacted_final_sha256"])
        self.assertEqual(review["status"], "NOT_RUN_NO_FINAL")

    def test_missing_frozen_reviewer_is_reported_without_fallback(self):
        (self.skill / collector.REVIEWER).unlink()
        with patch.object(collector.subprocess, "run", side_effect=AssertionError("fallback forbidden")):
            output, _, _, review = self.collect([final("正文")])
        self.assertEqual((output / "final.md").read_text(encoding="utf-8"), "正文")
        self.assertEqual(review["status"], "NOT_RUN_FROZEN_REVIEWER_MISSING")
        self.assertIsNone(review["reviewer_sha256"])

    def test_frozen_reviewer_failure_does_not_expose_subprocess_output(self):
        (self.skill / collector.REVIEWER).write_text('raise RuntimeError("PRIVATE_DIAGNOSTIC")', encoding="utf-8")
        output, _, _, review = self.collect([final("正文")])
        self.assertEqual(review["status"], "FROZEN_REVIEW_FAILED")
        self.assertNotIn("PRIVATE_DIAGNOSTIC", "".join(p.read_text(encoding="utf-8") for p in output.iterdir()))

    def test_refuses_existing_empty_directory_files_repo_and_frozen_output(self):
        self.write_session([final("正文")])
        for name, is_dir in (("empty", True), ("existing-file", False)):
            destination = self.root / name
            if is_dir:
                destination.mkdir()
            else:
                destination.write_bytes(b"KEEP")
            with self.assertRaises(FileExistsError):
                collector.collect(self.session, self.skill, destination)
        self.assertEqual((self.root / "existing-file").read_bytes(), b"KEEP")
        for destination in (collector.ROOT / "must-not-create-evidence", self.skill / "must-not-create"):
            with self.assertRaises(ValueError):
                collector.collect(self.session, self.skill, destination)
            self.assertFalse(destination.exists())

    def test_second_collection_never_overwrites_previous_report(self):
        output, _, _, _ = self.collect([final("第一份")])
        saved = {p.name: p.read_bytes() for p in output.iterdir()}
        self.write_session([final("第二份")])
        with self.assertRaises(FileExistsError):
            collector.collect(self.session, self.skill, output)
        self.assertEqual(saved, {p.name: p.read_bytes() for p in output.iterdir()})

    def test_invalid_jsonl_does_not_create_output_or_leak_line(self):
        self.session.write_text("SECRET_MALFORMED_JSON", encoding="utf-8")
        output = self.root / "invalid"
        with self.assertRaisesRegex(ValueError, "invalid JSONL at line 1"):
            collector.collect(self.session, self.skill, output)
        self.assertFalse(output.exists())


@unittest.skipUnless(os.environ.get("NATIVE_WRITING_D4_SESSION") and os.environ.get("NATIVE_WRITING_D4_SKILL"),
                     "real D4 regression requires explicit private paths")
class RealD4Tests(unittest.TestCase):
    def test_explicit_d4_read_counts_and_frozen_reviewer(self):
        session = Path(os.environ["NATIVE_WRITING_D4_SESSION"]).resolve()
        skill = Path(os.environ["NATIVE_WRITING_D4_SKILL"]).resolve()
        before = collector.sha256_bytes(session.read_bytes())
        snapshots = {name: collector.sha256_bytes((skill / name).read_bytes())
                     for name in (*collector.FILES, collector.REVIEWER)}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "new-private"
            # Real process and real frozen reviewer; stdout contains status only.
            result = subprocess.run([sys.executable, "-B", str(ROOT / "scripts/collect_native_writing_evidence.py"),
                                     "--session", str(session), "--skill-root", str(skill), "--output", str(output)],
                                    capture_output=True, timeout=60)
            self.assertEqual(result.returncode, 0)
            read = json.loads((output / "read-evidence.json").read_bytes())
            review = json.loads((output / "writing-review.json").read_bytes())
            self.assertEqual(read["read_counts"], dict.fromkeys(collector.FILES, 1))
            self.assertTrue(read["complete_skill_and_two_references"])
            self.assertFalse(read["reference_reread_proven"])
            self.assertEqual(read["rejected_calls"].get("failed"), 1)
            self.assertEqual(read["visible_final_turns"], 1)
            self.assertEqual(review["status"], "COMPLETED")
            self.assertEqual(review["reviewer_sha256"], snapshots[collector.REVIEWER])
            self.assertEqual(read["redacted_final_sha256"], collector.sha256_bytes((output / "final.md").read_bytes()))
        self.assertEqual(before, collector.sha256_bytes(session.read_bytes()))
        self.assertEqual(snapshots, {name: collector.sha256_bytes((skill / name).read_bytes()) for name in snapshots})


if __name__ == "__main__":
    unittest.main()
