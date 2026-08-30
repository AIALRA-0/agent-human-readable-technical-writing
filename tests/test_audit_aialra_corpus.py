from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from audit_aialra_corpus import (  # noqa: E402
    DEFAULT_EXCLUDES,
    DEFAULT_EXTENSIONS,
    RootSpec,
    audit,
    build_public_roots,
    markdown_zones,
    read_config,
    redact_excerpt,
    relative_report_path,
)


class CorpusAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.config_path = Path(__file__).resolve().parents[1] / "config" / "suspect-patterns.json"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_markdown_fence_tracks_body_lines(self) -> None:
        zones = markdown_zones(["正文", "```text", "门禁", "```", "正文"])
        self.assertEqual(zones, ["prose", "fence", "fence", "fence", "prose"])

    def test_report_path_never_contains_local_root(self) -> None:
        file_path = self.root / "docs" / "report.md"
        file_path.parent.mkdir()
        file_path.write_text("门禁", encoding="utf-8")
        spec = RootSpec("owner/repo", self.root, "public_github_repository")
        value = relative_report_path(spec, file_path)
        self.assertEqual(value, "owner/repo/docs/report.md")
        self.assertNotIn(str(self.root), value)

    def test_secret_and_absolute_path_are_redacted(self) -> None:
        value = redact_excerpt("token=demo_token_value path=C:\\Example\\secret.txt")
        self.assertNotIn("demo_token_value", value)
        self.assertNotIn("C:\\Example", value)
        self.assertIn("<REDACTED_SECRET>", value)
        self.assertIn("<REDACTED_PATH>", value)

    def test_unconfirmed_public_root_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            build_public_roots([self.root], confirmed=False)

    def test_audit_counts_prose_and_fence_separately(self) -> None:
        document = self.root / "sample.md"
        document.write_text("门禁\n\n```text\n门禁\n```\n", encoding="utf-8")
        spec = RootSpec("owner/repo", self.root, "public_github_repository")
        result = audit([spec], read_config(self.config_path), 4, DEFAULT_EXTENSIONS, DEFAULT_EXCLUDES)
        row = next(item for item in result["terms"] if item["term"] == "门禁")
        self.assertEqual(row["matching_files"], 1)
        self.assertEqual(row["occurrences"], 2)
        self.assertEqual(row["zones"], {"prose": 1, "fence": 1})


if __name__ == "__main__":
    unittest.main()
