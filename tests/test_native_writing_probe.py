"""Synthetic events only: this module must never start the host CLI."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import run_native_writing_probe as probe


SESSION = "019abcdef-0000-0000-0000-000000000000"


def command_event(command, *, identifier="read-1", code=0, output="file contents", status="completed"):
    return {"type": "item.completed", "item": {
        "type": "command_execution", "id": identifier, "command": command,
        "status": status, "exit_code": code, "aggregated_output": output,
    }}


def mcp_event(path, *, result=None, tool="read_file", identifier="mcp-1"):
    return {"type": "item.completed", "item": {
        "type": "mcp_tool_call", "id": identifier, "server": "filesystem", "tool": tool,
        "arguments": {"path": str(path)}, "status": "completed",
        "result": result if result is not None else {"content": [{"type": "text", "text": "file contents"}]},
    }}


def cli_result(events=(), body="PRIVATE ANSWER", session=SESSION, code=0):
    return {"events": [*events, {"type": "turn.completed"}], "body": body,
            "stdout": "PRIVATE RAW EVENTS", "stderr": "PRIVATE STDERR", "thread_id": session,
            "exit_code": code}


class NativeProbeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=probe.ROOT.parent)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.task = self.root / "task"
        self.skill = self.task / ".agents" / "skills" / probe.SKILL
        for name in probe.FILES:
            path = self.skill / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"# {name}\nComplete synthetic file contents\n", encoding="utf-8")
        self.auth = self.root / "auth.json"
        self.auth.write_text('{"token":"PRIVATE AUTH"}', encoding="utf-8")
        # A forgotten mock is a test failure, never a paid/live model invocation.
        self.cli_guard = patch.object(probe, "run_codex", side_effect=AssertionError("real CLI forbidden"))
        self.cli_guard.start()
        self.addCleanup(self.cli_guard.stop)

    def reads(self, suffix=""):
        return [command_event(f"Get-Content -Raw '{self.skill / name}'", identifier=f"{index}{suffix}",
                              output=(self.skill / name).read_text(encoding="utf-8"))
                for index, name in enumerate(probe.FILES)]

    def test_real_command_reads_and_separate_rereads(self):
        evidence = probe.read_evidence(self.reads() + self.reads("again"), self.task)
        self.assertEqual(evidence["discovery"], "proven")
        self.assertEqual(evidence["reference_reread"], "proven")
        self.assertEqual(list(evidence["read_calls"].values()), [2, 2, 2])

    def test_mentions_claims_and_started_events_are_not_reads(self):
        path = self.skill / probe.FILES[0]
        events = [
            {"type": "user_message", "text": f"Get-Content '{path}'"},
            {"type": "item.completed", "item": {"type": "agent_message", "text": f"I read {path}"}},
            command_event(f"Write-Output '{path}'"),
            {"type": "item.started", "item": self.reads()[0]["item"]},
        ]
        evidence = probe.read_evidence(events, self.task)
        self.assertEqual(evidence["discovery"], "not_proven")
        self.assertEqual(sum(evidence["read_calls"].values()), 0)

    def test_failed_empty_partial_and_ambiguous_commands_do_not_prove_reads(self):
        path = self.skill / probe.FILES[0]
        examples = [
            command_event(f"cat '{path}'", code=1),
            command_event(f"cat '{path}'", output=""),
            command_event(f"Get-Content '{path}'", output="Get-Content : Cannot find path"),
            command_event(f"Get-Content -TotalCount 1 '{path}'"),
            command_event(f"cat '{path}' | head -1"),
            command_event(f"if ($false) {{ Get-Content '{path}' }}"),
            command_event(f"echo \"Get-Content '{path}'\""),
            command_event(f"cat '{path}'", output="contents truncated"),
            command_event(f"cat '{path}'", status="in_progress"),
        ]
        for event in examples:
            with self.subTest(command=event["item"]["command"]):
                self.assertEqual(sum(probe.read_evidence([event], self.task)["full_read_calls"].values()), 0)

    def test_filename_only_and_truncated_stdout_are_observed_but_not_full_reads(self):
        path = self.skill / "SKILL.md"
        for output in (str(path), "contents truncated", path.read_text()[:10]):
            evidence = probe.read_evidence([command_event(f"cat '{path}'", output=output)], self.task)
            self.assertEqual(evidence["read_calls"]["SKILL.md"], 1)
            self.assertEqual(evidence["full_read_calls"]["SKILL.md"], 0)
            self.assertEqual(evidence["discovery"], "not_proven")

    def test_event_and_operand_duplicates_do_not_prove_reread(self):
        path = self.skill / probe.FILES[1]
        event = command_event(f"cat '{path}' '{path}'")
        evidence = probe.read_evidence([event, event], self.task)
        self.assertEqual(evidence["read_calls"][probe.FILES[1]], 1)
        self.assertEqual(evidence["reference_reread"], "not_proven")
        without_id = json.loads(json.dumps(event))
        without_id["item"].pop("id")
        self.assertEqual(probe.read_evidence([without_id, without_id], self.task)["read_calls"][probe.FILES[1]], 1)

    def test_relative_mixed_paths_shell_wrapper_and_wrong_install_root(self):
        relative = f".agents/skills/{probe.SKILL}/references/../SKILL.md"
        command = f'''pwsh.exe -NoProfile -Command "Get-Content -Raw '{relative}'"'''
        self.assertEqual(probe.read_evidence([command_event(command)], self.task)["read_calls"]["SKILL.md"], 1)
        paths = [self.skill / probe.SKILL / "SKILL.md", self.root / "home" / "skills" / probe.SKILL / "SKILL.md"]
        for path in paths:
            self.assertEqual(sum(probe.read_evidence([command_event(f"cat '{path}'")], self.task)["read_calls"].values()), 0)

    def test_mcp_requires_successful_actual_read_tool_and_result(self):
        events = [mcp_event(self.skill / name, identifier=str(index), result={"content": [
            {"type": "text", "text": (self.skill / name).read_text(encoding="utf-8")}
        ]}) for index, name in enumerate(probe.FILES)]
        self.assertEqual(probe.read_evidence(events, self.task)["discovery"], "proven")
        failures = [
            mcp_event(self.skill / "SKILL.md", result={"isError": True, "content": [{"type": "text", "text": "failure"}]}),
            mcp_event(self.skill / "SKILL.md", result={}),
            mcp_event(self.skill / "SKILL.md", result={"content": [{"type": "text", "text": "Error: not found"}]}),
            mcp_event(self.skill / "SKILL.md", tool="search_files"),
        ]
        partial = mcp_event(self.skill / "SKILL.md")
        partial["item"]["arguments"]["head"] = 1
        failures.append(partial)
        for event in failures:
            self.assertEqual(probe.read_evidence([event], self.task)["discovery"], "not_proven")
        uri_event = mcp_event((self.skill / "SKILL.md").as_uri(), tool="read_resource")
        uri_event["item"]["arguments"] = json.dumps({"uri": (self.skill / "SKILL.md").as_uri()})
        self.assertEqual(probe.read_evidence([uri_event], self.task)["read_calls"]["SKILL.md"], 1)

    def test_pure_json_requires_normal_body_no_reads_and_complete_turn(self):
        valid = '{"count":3,"enabled":true}'
        self.assertEqual(probe.summarize_turn(cli_result(body=valid), self.task, 0, True)["negative"], "passed")
        for body in ("```json\n" + valid + "\n```", '{"count":true,"enabled":true}', 'text ' + valid):
            self.assertEqual(probe.summarize_turn(cli_result(body=body), self.task, 0, True)["negative"], "failed")
        self.assertEqual(probe.summarize_turn(cli_result(self.reads(), body=valid), self.task, 0, True)["negative"], "failed")
        for events in ([command_event("python unknown.py")], [command_event("cat missing", code=1)]):
            self.assertEqual(probe.summarize_turn(cli_result(events, body=valid), self.task, 0, True)["negative"], "not_proven")
        result = cli_result(body=valid, code=124)
        self.assertEqual(probe.summarize_turn(result, self.task, 0, True)["negative"], "not_proven")
        result = cli_result(body=valid)
        result["events"] = []
        self.assertEqual(probe.summarize_turn(result, self.task, 0, True)["negative"], "not_proven")

    def test_positive_summary_does_not_access_answer(self):
        class UnreadableBody(dict):
            def __getitem__(self, key):
                if key == "body":
                    raise AssertionError("positive body was inspected")
                return super().__getitem__(key)
        result = probe.summarize_turn(UnreadableBody(cli_result(self.reads())), self.task, 0, False)
        self.assertNotIn("body", result)

    def test_hidden_host_denial_is_not_an_error_free_negative(self):
        result = cli_result(body='{"count":3,"enabled":true}')
        result["stderr"] = 'ERROR codex_core::tools::router: error=exec_command failed: PRIVATE-PATH rejected: blocked by policy'
        summary = probe.summarize_turn(result, self.task, 0, True)
        self.assertTrue(summary["completed"])  # The answer really completed.
        self.assertTrue(summary["host_policy_denial_observed"])
        self.assertEqual(summary["negative"], "not_proven")
        self.assertNotIn("PRIVATE-PATH", json.dumps(summary))
        result["stderr"] = "unrelated warning"
        result["body"] = "A quoted phrase: rejected: blocked by policy"
        self.assertFalse(probe.summarize_turn(result, self.task, 0, False)["host_policy_denial_observed"])

    def test_private_root_and_report_refuse_overwrite(self):
        run, report = self.root / "run", self.root / "report.json"
        private = probe.prepare_root(run, report, self.auth)
        probe.write_new(private / "events.json", {"body": "PRIVATE"})
        with self.assertRaises(ValueError):
            probe.prepare_root(run, report, self.auth)
        with self.assertRaises(FileExistsError):
            probe.write_new(private / "events.json", {})
        self.assertIn("PRIVATE", (private / "events.json").read_text())
        report.write_text("KEEP", encoding="utf-8")
        with self.assertRaises(ValueError):
            probe.prepare_root(self.root / "new", report, self.auth)
        self.assertEqual(report.read_text(), "KEEP")
        for bad_run, bad_report in ((probe.ROOT / "probe-run", self.root / "public.json"),
                                    (self.root / "other", self.root / "other" / "report.json")):
            with self.assertRaises(ValueError):
                probe.prepare_root(bad_run, bad_report, self.auth)

    def test_install_only_native_skill_and_auth_and_strip_user_environment(self):
        home, task = probe.install_case(self.root / "isolated", self.auth)
        self.assertEqual({path.name for path in home.iterdir()}, {"auth.json"})
        self.assertEqual({path.name for path in task.iterdir()}, {".agents"})
        installed = task / ".agents" / "skills" / probe.SKILL
        for relative in probe.RUNTIME_ITEMS:
            self.assertTrue((installed / relative).exists(), relative)
        self.assertFalse((home / "skills").exists())
        self.assertFalse((task / "AGENTS.md").exists())
        with patch.dict(os.environ, {"OPENAI_API_KEY": "SECRET", "CODEX_THREAD_ID": "SECRET",
                                     "AIALRA_EVAL_SKILL_ROOT": "SECRET", "CODEX_HOME": "user-home"}):
            environment = probe.environment_for(home)
        self.assertNotIn("SECRET", json.dumps(environment))
        self.assertEqual(environment["CODEX_HOME"], str(home))
        self.assertEqual(environment["USERPROFILE"], str(home))

    def test_mocked_run_same_session_stdin_and_allowlisted_report(self):
        run, report = self.root / "run", self.root / "report.json"
        calls = []

        def fake_cli(command, environment, timeout, stdin_text=None):
            calls.append((command, environment, timeout, stdin_text))
            if "--help" in command:
                if "exec" not in command:
                    self.assertEqual(command, ["codex", "--help"])
                return {**cli_result(), "stdout": "--ignore-user-config --ignore-rules --sandbox -C --disable --config --json --skip-git-repo-check --model"}
            case_home = Path(environment["CODEX_HOME"])
            self.assertEqual(set(path.name for path in case_home.iterdir()), {"auth.json"})
            body = '{"count":3,"enabled":true}' if "合法 JSON" in stdin_text else "PRIVATE ANSWER"
            return cli_result(body=body)

        with patch.object(probe, "run_codex", side_effect=fake_cli):
            self.assertEqual(probe.main(["--auth", str(self.auth), "--run-root", str(run), "--report", str(report),
                                         "--model", "model-a", "--model", "model-b", "--workers", "3"]), 0)
        public_text = report.read_text(encoding="utf-8")
        for secret in ("PRIVATE", str(run), str(self.auth), SESSION, "stdout", "stderr", "body\"", "prompt"):
            self.assertNotIn(secret, public_text)
        public = json.loads(public_text)
        self.assertEqual((public["case_count"], public["turn_count"]), (8, 12))
        writer_calls = [call for call in calls if "--help" not in call[0]]
        self.assertEqual(len(writer_calls), 12)
        self.assertEqual(len({call[1]["CODEX_HOME"] for call in writer_calls}), 8)
        for command, environment, timeout, prompt in writer_calls:
            self.assertEqual(command[:2], ["codex", "exec"])
            scope = command.index("resume") if "resume" in command else command.index("exec")
            for option in ("--ignore-user-config", "--ignore-rules"):
                self.assertGreater(command.index(option), scope)
            if "resume" in command:
                self.assertLess(command.index("--sandbox"), scope)
                self.assertLess(command.index("-C"), scope)
            self.assertEqual(command[-1], "-")
            self.assertNotIn(prompt, command)
            self.assertIn("workspace-write", command)
            self.assertEqual(command[command.index("-C") + 1], str(Path(environment["CODEX_HOME"]).parent / "task"))
            self.assertEqual(timeout, 300)
            for feature in probe.FEATURES:
                self.assertIn(feature, command)
        resumes = [call for call in writer_calls if "resume" in call[0]]
        self.assertEqual(len(resumes), 4)
        self.assertTrue(all(call[0][-2] == SESSION for call in resumes))
        self.assertEqual(len(list((run / "private").glob("m*-c*/turn-*.json"))), 12)
        for case in public["cases"]:
            if case["id"] == "multi_turn":
                self.assertEqual(case["return_reference_reads"], "not_proven")

    def test_timeout_and_missing_session_stop_without_retry(self):
        case_root = self.root / "case"
        case_root.mkdir()
        for result in (cli_result(session=None), cli_result(code=124)):
            with tempfile.TemporaryDirectory(dir=case_root) as directory:
                with patch.object(probe, "run_codex", return_value=result) as runner:
                    value = probe.run_case("codex", "model-a", probe.CASES[-1], Path(directory), self.root / "home", self.task, 30)
                self.assertEqual(runner.call_count, 1)
                self.assertEqual(value["same_session_resume"], "not_proven")

    def test_workers_and_timeout_are_bounded(self):
        base = ["--auth", "auth", "--run-root", "run", "--report", "report", "--model", "model-a"]
        for extra in (["--workers", "4"], ["--timeout-seconds", "0"], ["--timeout-seconds", "901"]):
            with patch("sys.stderr"), self.assertRaises(SystemExit):
                probe.parse_args(base + extra)
        self.assertEqual(probe.parse_args(base[:-2]).model, list(probe.MODELS))
        self.assertEqual(probe.parse_args(base[:-1] + ["gpt-6-astra"]).model, ["gpt-6-astra"])

    def test_help_failure_identifies_private_evidence_and_never_starts_writer(self):
        run, report = self.root / "bad-help", self.root / "report.json"
        result = {**cli_result(code=2), "stdout": "", "stderr": "PRIVATE CLI parser error"}
        with patch.object(probe, "run_codex", return_value=result) as runner:
            with self.assertRaises(ValueError) as caught:
                probe.main(["--auth", str(self.auth), "--run-root", str(run), "--report", str(report)])
        self.assertEqual(runner.call_count, 1)
        self.assertIn("--help", runner.call_args.args[0])
        self.assertIn("exit_code=2", str(caught.exception))
        self.assertIn(str(run / "private" / "help-0.json"), str(caught.exception))
        self.assertIn(str(run / "private" / "startup-error.json"), str(caught.exception))
        self.assertNotIn("PRIVATE CLI parser error", str(caught.exception))
        self.assertTrue((run / "private" / "startup-error.json").is_file())
        self.assertFalse(report.exists())

    def test_single_case_diagnostic_respects_explicit_executable(self):
        run, report = self.root / "single", self.root / "single.json"
        summary = {"id": "explicit_skill", "model": "gpt-5.6-sol", "turn_count": 1, "turns": []}
        with patch.object(probe, "check_host_help") as help_check, patch.object(
            probe, "run_case", return_value=summary
        ) as runner:
            probe.main(["--auth", str(self.auth), "--run-root", str(run), "--report", str(report),
                        "--codex", "bundled-codex.exe", "--model", "gpt-5.6-sol",
                        "--case-id", "explicit_skill", "--workers", "1"])
        runner.assert_called_once()
        self.assertEqual(runner.call_args.args[:3], ("bundled-codex.exe", "gpt-5.6-sol", probe.CASES[1]))
        self.assertEqual(help_check.call_args.args[0], "bundled-codex.exe")
        self.assertEqual(json.loads(report.read_text())["case_count"], 1)
        self.assertEqual(len(list((run / "private").glob("m*-c*"))), 1)


if __name__ == "__main__":
    unittest.main()
