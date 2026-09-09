"""Validate candidate inputs, never model prose or a preferred answer template.

Run: python -B -X utf8 -m unittest discover -s tests -p test_two_layer_cases.py
"""

import ast
import hashlib
import importlib.util
import json
import re
import unittest
from collections import Counter
from decimal import Decimal
from pathlib import Path

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "two_layer_cases", ROOT / "scripts/build_two_layer_cases.py")
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)


class TwoLayerCasesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows, cls.coverage = BUILDER.build_cases()
        cls.by_topic = {row["core_terms"][0]: row for row in cls.rows}

    def source(self, topic):
        return self.by_topic[topic]["source"]["content"]

    def test_forward_schema_and_source_digests(self):
        schema = json.loads((ROOT / "contracts/forward-request.schema.json").read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)
        validator = jsonschema.Draft202012Validator(schema)
        self.assertEqual(len(self.rows), 20)
        for row in self.rows:
            with self.subTest(case=row["case_id"]):
                validator.validate(row)
                content = row["source"]["content"]
                canonical = content if isinstance(content, str) else json.dumps(
                    content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                self.assertEqual(row["source"]["sha256"],
                                 hashlib.sha256(canonical.encode("utf-8")).hexdigest())

    def test_real_length_distribution_and_substantive_chapters(self):
        ranges = {"very_short": (1, 80), "short": (81, 250), "medium": (251, 700),
                  "long": (701, 1500), "extended": (1501, 3000)}
        for row in self.rows:
            content = row["source"]["content"]
            raw = content if isinstance(content, str) else json.dumps(
                content, ensure_ascii=False, sort_keys=True)
            count = len(row["request"]) + len(raw) + sum(len(ref["content"]) for ref in row["references"])
            with self.subTest(case=row["case_id"]):
                self.assertEqual(row["input_char_count"], count)
                low, high = ranges[row["length_class"]]
                self.assertLessEqual(low, count)
                self.assertLessEqual(count, high)
        distribution = Counter(row["length_class"] for row in self.rows)
        self.assertEqual(set(distribution), set(ranges))
        self.assertGreaterEqual(distribution["extended"], 2)
        long_articles = [item for item in self.coverage["cases"]
                         if "multi_section_article" in item["features"]]
        self.assertGreaterEqual(len(long_articles), 2)
        for article in long_articles:
            row = next(row for row in self.rows if row["case_id"] == article["case_id"])
            source = row["source"]["content"]
            self.assertTrue(1500 <= len(source) <= 3000)
            chapters = re.split(r"第[一二三四五六七八九十]+章：[^\n]+\n", source)[1:]
            self.assertGreaterEqual(len(chapters), 3)
            # Check source construction for padding; not a naturalness gate on answers.
            self.assertTrue(all(len(chapter.strip()) >= 150 for chapter in chapters))
            sentences = [part.strip() for part in re.split(r"[。\n]", source) if len(part.strip()) >= 20]
            self.assertEqual(len(sentences), len(set(sentences)))
        self.assertEqual(dict(distribution), self.coverage["length_distribution"])

    def test_independent_topics_and_implicit_requests(self):
        for values in ([row["case_id"] for row in self.rows],
                       [row["topic_id"] for row in self.rows],
                       [row["core_terms"][0] for row in self.rows],
                       [row["source"]["sha256"] for row in self.rows]):
            self.assertEqual(len(set(values)), 20)
        # Detect reused raw paragraphs, not stylistic similarity of model output.
        paragraphs = []
        for row in self.rows:
            content = row["source"]["content"]
            if isinstance(content, str):
                paragraphs.extend(p.strip() for p in content.split("\n") if len(p.strip()) > 80)
        self.assertEqual(len(paragraphs), len(set(paragraphs)))
        implicit = [row for row in self.rows if row["trigger_mode"] == "implicit"]
        self.assertGreaterEqual(len(implicit), 4)
        for row in implicit:
            self.assertNotIn("human-readable-technical-writing", row["request"])
            self.assertNotIn("EXPL-", row["request"])

    def test_private_coverage_schema_and_generated_artifacts(self):
        # Separation is a data contract, not a model-output score.
        review_schema = {
            "type": "object", "required": ["case_id", "topic", "features", "fact_checkpoints",
                "prerequisite_checkpoints", "retelling_questions", "transfer_questions"],
            "properties": {key: {"type": "array", "items": {"type": "string", "minLength": 1}}
                           for key in ("features", "fact_checkpoints", "prerequisite_checkpoints",
                                       "retelling_questions", "transfer_questions")},
        }
        self.assertEqual({item["case_id"] for item in self.coverage["cases"]},
                         {row["case_id"] for row in self.rows})
        for row, review in zip(self.rows, self.coverage["cases"]):
            jsonschema.validate(review, review_schema)
            if row["trigger_mode"] != "non_triggering_control":
                for key in ("fact_checkpoints", "prerequisite_checkpoints", "retelling_questions", "transfer_questions"):
                    self.assertTrue(review[key])
            visible = json.dumps({key: row[key] for key in ("request", "source", "references")}, ensure_ascii=False)
            for question in review["retelling_questions"] + review["transfer_questions"]:
                self.assertNotIn(question, visible)
            self.assertNotIn("EXPL-", visible)
        directory = ROOT / "evals/candidate/two-layer"
        saved_rows = [json.loads(line) for line in (directory / "requests.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(saved_rows, self.rows)
        self.assertEqual(json.loads((directory / "coverage.json").read_text(encoding="utf-8")), self.coverage)

    def test_pure_format_controls_are_real_code_json_and_number(self):
        controls = [row for row in self.rows if row["trigger_mode"] == "non_triggering_control"]
        self.assertGreaterEqual(len(controls), 2)
        kinds = set()
        for row in controls:
            review = next(item for item in self.coverage["cases"] if item["case_id"] == row["case_id"])
            contract = review["output_contract"]
            kinds.add(contract["kind"])
            self.assertEqual(row["base_operation"], "FORMAT_ONLY")
            self.assertEqual(row["augmentation"], "NONE")
            self.assertFalse(contract["explanation_allowed"])
            self.assertFalse(contract["fences_allowed"])
            self.assertEqual(row["references"], [])
            source = row["source"]["content"]
            if contract["kind"] == "python":
                tree = ast.parse(source)
                self.assertIsInstance(tree.body[0], ast.FunctionDef)
                self.assertNotIn("#", source)
            elif contract["kind"] == "json":
                value = json.loads(source)
                self.assertIsInstance(value, dict)
                self.assertIs(value["checked"], False)
            else:
                self.assertRegex(source, r"^[0-9]+$")
        self.assertEqual(kinds, {"python", "json", "integer"})
        embedded = json.loads(self.source("天文展台轮播配置"))
        self.assertIs(embedded["caption"], None)
        self.assertIs(embedded["shuffle"], False)
        self.assertEqual(embedded["slides"], ["moon", "mars"])

    def test_table_and_status_numeric_consistency(self):
        table = self.source("读书会反馈满意比例")
        groups = [tuple(map(int, match)) for match in re.findall(
            r"\| (?:上午组|下午组) \| (\d+) \| (\d+) \| (\d+) \|", table)]
        self.assertEqual(len(groups), 2)
        for attended, returned, satisfied in groups:
            self.assertTrue(0 <= satisfied <= returned <= attended)
        totals = tuple(map(sum, zip(*groups)))
        self.assertEqual(totals, (100, 40, 26))
        self.assertEqual(Decimal(totals[2]) / totals[1], Decimal("0.65"))
        status = self.source("剧场实时字幕试点")
        total, met, limit, missed = map(int, re.search(
            r"共 (\d+) 句，其中 (\d+) 句延迟不超过 (\d+) s，(\d+) 句超过", status).groups())
        target = int(re.search(r"至少 (\d+)%", status)[1])
        self.assertEqual(met + missed, total)
        self.assertEqual(limit, 2)
        self.assertEqual(Decimal(met) / total, Decimal("0.9"))
        self.assertEqual(Decimal(total) * target / 100, Decimal(57))

    def test_formula_prices_and_conflicting_measurements(self):
        geometry = self.source("露天电影银幕尺寸计算")
        width = Decimal(re.search(r"W = ([\d.]+) m", geometry)[1])
        total = Decimal(re.search(r"布料总高 ([\d.]+) m", geometry)[1])
        edge = Decimal(re.search(r"上下各留 ([\d.]+) m", geometry)[1])
        self.assertEqual(width * 9 / 16, total - 2 * edge)
        self.assertEqual(width * 9 / 16, Decimal("1.8"))
        pricing = self.source("种子交换会说明卡印制")
        quotes = re.findall(r"(?:开机费|制版费) (\d+) 元，每张 ([\d.]+) 元，确认(?:稿件)?后 (\d+) 天", pricing)
        self.assertEqual(len(quotes), 2)
        count = int(re.search(r"需要 (\d+) 张", pricing)[1])
        costs = [Decimal(fixed) + Decimal(each) * count for fixed, each, _ in quotes]
        self.assertEqual(costs, [Decimal("232"), Decimal("240")])
        next_costs = [Decimal(fixed) + Decimal(each) * 800 for fixed, each, _ in quotes]
        self.assertEqual(next_costs, [Decimal("680"), Decimal("380")])
        mass = self.source("岩石标本称量记录冲突")
        gross, tare, net_a, net_b = map(int, re.findall(r"(?:总质量|容器皮重|净质量) (\d+) g", mass))
        self.assertEqual(gross - tare, net_a)
        # The disagreement is intentional source evidence, not a typo to normalize.
        self.assertNotEqual(net_a, net_b)


if __name__ == "__main__":
    unittest.main()
