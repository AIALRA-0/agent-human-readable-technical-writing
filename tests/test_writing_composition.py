"""Independent mechanical contract tests; all fixtures are synthetic.

No historical answers, semantic grading, or implementation mocks are used.
Missing implementation modules deliberately fail collection rather than skip.
"""

from __future__ import annotations

import copy
import io
import json
import os
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from runtime.composition import render_document  # noqa: E402
from scripts.compose_writing import main  # noqa: E402
from scripts.review_writing import review_text  # noqa: E402
from patcher.deterministic_committer import PatchError  # noqa: E402


def paragraph(text="正文"):
    return {"type": "paragraph", "text": text}


def document(*blocks):
    return {"blocks": list(blocks)}


def term():
    return {
        "type": "term",
        "zh": "缓存",
        "en": "Cache",
        "definition": ["保存已有结果", "减少重复读取", "命中时直接返回"],
    }


def nested_list():
    return {
        "type": "list",
        "ordered": True,
        "items": [
            {
                "text": "第一步。",
                "children": [
                    {
                        "text": "分支甲；",
                        "children_ordered": True,
                        "children": [{"text": "动作一"}, {"text": "动作二"}],
                    },
                    {"text": "分支乙"},
                ],
            },
            {"text": "第二步"},
        ],
    }


class CompositionRenderingTests(unittest.TestCase):
    def assertBody(self, actual, expected):
        """Ordinary document EOF may have one terminating newline."""
        self.assertIn(actual, (expected, expected + "\n"))

    def assertFenced(self, rendered, payload, language):
        opening, separator, remainder = rendered.partition("\n")
        self.assertEqual(separator, "\n")
        match = re.fullmatch(r"(`{3,})(.*)", opening)
        self.assertIsNotNone(match, opening)
        fence, actual_language = match.groups()
        self.assertEqual(actual_language, language)
        longest = max((len(run) for run in re.findall(r"`+", payload)), default=0)
        self.assertGreater(len(fence), longest)
        self.assertTrue(remainder.startswith(payload), repr(remainder))
        suffix = remainder[len(payload):]
        allowed = ["\n" + fence, "\n" + fence + "\n"]
        if payload.endswith("\n"):
            allowed.extend([fence, fence + "\n"])
        self.assertIn(suffix, allowed)

    def test_short_document_requires_no_title_or_template(self):
        self.assertBody(render_document(document(paragraph("只需一句话"))), "只需一句话")

    def test_sections_follow_nesting_and_restore_sibling_depth(self):
        blocks = [
            {"type": "section", "heading": "任意主题", "blocks": [
                paragraph("导语"),
                {"type": "section", "heading": "细节", "blocks": [paragraph("内容")]},
            ]},
            {"type": "section", "heading": "另一个主题", "blocks": [paragraph("结尾")]},
        ]
        expected = "## 任意主题\n\n导语\n\n### 细节\n\n内容\n\n## 另一个主题\n\n结尾"
        self.assertBody(render_document({"blocks": blocks}), expected)
        self.assertBody(render_document({"title": "  总标题。 ", "blocks": blocks}),
                        "# 总标题\n\n" + expected)

    def test_sixth_heading_level_is_allowed_seventh_is_rejected(self):
        block = paragraph("末层")
        for number in range(5, 0, -1):
            block = {"type": "section", "heading": f"层{number}", "blocks": [block]}
        for with_title in (False, True):
            doc = document(block)
            if with_title:
                doc["title"] = "总标题"
            with self.subTest(with_title=with_title):
                output = render_document(doc)
                self.assertIn("###### 层5\n\n末层", output)
                excessive = {"type": "section", "heading": "额外层", "blocks": [block]}
                doc["blocks"] = [excessive]
                with self.assertRaises(ValueError):
                    render_document(doc)

    def test_nested_list_compact_and_host_spacing(self):
        compact = "1. 第一步\n    - 分支甲\n        1. 动作一\n        2. 动作二\n    - 分支乙\n2. 第二步"
        host = "1. 第一步\n\n    - 分支甲\n\n        1. 动作一\n        2. 动作二\n    - 分支乙\n2. 第二步"
        doc = document(paragraph("开始"), nested_list(), paragraph("结束"))
        for spacing, expected in ((False, compact), (True, host)):
            with self.subTest(host_nested_blank=spacing):
                self.assertBody(render_document(doc, host_nested_blank=spacing),
                                "开始\n\n" + expected + "\n\n结束")

    def test_default_list_is_unordered_and_numbering_restarts(self):
        first = {"type": "list", "items": [{"text": "甲"}, {"text": "乙"}]}
        ordered = {"type": "list", "ordered": True, "items": [{"text": "丙"}, {"text": "丁"}]}
        self.assertBody(render_document(document(first)), "- 甲\n- 乙")
        self.assertBody(render_document(document(ordered, paragraph("中间"), ordered)),
                        "1. 丙\n2. 丁\n\n中间\n\n1. 丙\n2. 丁")

    def test_three_digit_parent_keeps_child_inside_its_content_indent(self):
        values = [{"text": str(i)} for i in range(1, 101)]
        values[-1]["children"] = [{"text": "子项", "children": [{"text": "孙项"}]}]
        output = render_document(document({"type": "list", "ordered": True, "items": values}))
        self.assertIn("100. 100\n     - 子项\n         - 孙项", output)

    def test_terms_are_one_item_with_three_to_five_definition_parts(self):
        definitions = ["保存已有结果。", "减少重复读取；", "命中时直接返回。", "重复查询时使用", "未命中时仍需读取原处"]
        for count in (3, 4, 5):
            for abbreviation in (None, "C"):
                block = term()
                block["definition"] = definitions[:count]
                if abbreviation is not None:
                    block["abbr"] = abbreviation
                with self.subTest(count=count, abbreviation=abbreviation):
                    prefix = "C " if abbreviation else ""
                    expected = "- " + prefix + "缓存（Cache）：" + "；".join(
                        part.rstrip("。；") for part in definitions[:count])
                    self.assertBody(render_document(document(block)), expected)

    def test_only_outer_whitespace_and_terminal_chinese_stops_are_removed(self):
        content = "中文A1  e\u0301\t路径 C:\\tmp\\a；句内。仍在，ASCII.;"
        for ending in ("", "。", "；", "。；。"):
            with self.subTest(ending=ending):
                output = render_document(document(paragraph(" \t" + content + ending + " \t")))
                self.assertBody(output, content)
        for ending in ("，", "：", "！", "？", ".", ";", "!", "?", "…"):
            with self.subTest(preserved=ending):
                self.assertBody(render_document(document(paragraph("文本" + ending))), "文本" + ending)

    def test_adjacent_terms_form_one_compact_list(self):
        first = term()
        second = dict(term(), zh="副本", en="Copy", abbr="C")
        self.assertBody(render_document(document(paragraph("术语如下"), first, second, paragraph("结束"))),
                        "术语如下\n\n- 缓存（Cache）：保存已有结果；减少重复读取；命中时直接返回\n"
                        "- C 副本（Copy）：保存已有结果；减少重复读取；命中时直接返回\n\n结束")

    def test_semantically_independent_items_in_paragraph_are_not_inferred(self):
        text = "检查输入，保存文件；关闭窗口。三项由模型挤在同一段"
        self.assertBody(render_document(document(paragraph(text))), text)
        structured = {"type": "list", "items": [
            {"text": "检查输入"}, {"text": "保存文件"}, {"text": "关闭窗口"},
        ]}
        self.assertBody(render_document(document(structured)), "- 检查输入\n- 保存文件\n- 关闭窗口")

    def test_no_word_ban_length_limit_or_semantic_definition_grading(self):
        text = "基于已有条件进行处理，" * 100 + "保留普通语序"
        self.assertBody(render_document(document(paragraph(text))), text)
        block = term()
        block["definition"] = ["甲，乙", "丙", "丁"]
        self.assertBody(render_document(document(block)), "- 缓存（Cache）：甲，乙；丙；丁")

    def test_inline_markdown_is_not_mistaken_for_block_markdown(self):
        text = "保留 `a_b`、**强调**、[链接](https://example.test/a)、$x_1$ 和 C#"
        self.assertBody(render_document(document(paragraph(text))), text)

    def test_raw_sources_preserve_code_table_quote_formula_and_line_endings(self):
        payloads = [
            '  print("原句。")\r\n\t# 原注释；\r\n\r\n',
            "| 名称 | 值 |\n| --- | ---: |\n| e\u0301 | 0.00； |\n\n",
            "> 原话。  \r\n>\r\n> 不代表确认；\r\n",
            "$$\n  x_{i+1} = x_i + 1 \\\\\n\\text{原样。；}\n$$\n",
        ]
        for payload in payloads:
            for presentation in (None, "raw"):
                block = {"type": "source", "id": "original"}
                if presentation is not None:
                    block["presentation"] = presentation
                with self.subTest(payload=payload, presentation=presentation):
                    output = render_document(document(block), sources={"original": payload})
                    self.assertTrue(output.startswith(payload), repr(output))
                    self.assertIn(output[len(payload):], ("", "\n"))

    def test_quote_source_only_adds_prefixes(self):
        payload = "  原话。\r\n\r\n> 内层引用；  \r\n末行。"
        output = render_document(document({"type": "source", "id": "q", "presentation": "quote"}),
                                 sources={"q": payload})
        restored = []
        for line in output.splitlines(keepends=True):
            self.assertTrue(line.startswith(">"), repr(line))
            restored.append(line[2:] if line.startswith("> ") else line[1:])
        self.assertIn("".join(restored), (payload, payload + "\n"))

    def test_code_and_code_sources_use_safe_fences_without_touching_payload(self):
        for payload in ('print("原样。；")', "\n```\n  `````` literal\r\n\t尾部；  \r\n\n"):
            with self.subTest(payload=payload):
                self.assertFenced(render_document(document({"type": "code", "language": "python", "text": payload})),
                                  payload, "python")
                block = {"type": "source", "id": "c", "presentation": "code", "language": "python"}
                self.assertFenced(render_document(document(block), sources={"c": payload}), payload, "python")

    def test_code_is_displayed_without_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            sentinel = Path(temp) / "must-not-exist.txt"
            payload = f"from pathlib import Path\nPath({str(sentinel)!r}).write_text('executed')"
            self.assertFenced(render_document(document({"type": "code", "language": "python", "text": payload})),
                              payload, "python")
            self.assertFalse(sentinel.exists())

    def test_source_coverage_uses_ids_and_follows_document_order(self):
        sources = {"a": "同一原文。", "b": "同一原文。", "c": "另一原文；"}
        blocks = [{"type": "source", "id": key} for key in ("c", "b", "a")]
        output = render_document(document(*blocks), sources=sources)
        self.assertEqual(output.count("同一原文。"), 2)
        self.assertLess(output.index("另一原文；"), output.index("同一原文。"))
        with self.assertRaises(ValueError):
            render_document(document(*blocks[:2]), sources=sources)

    def test_image_and_caption_share_a_centered_container(self):
        block = {"type": "image", "alt": "  流程图。 ", "url": "https://example.test/a(b).png"}
        expected = '<div align="center">\n\n<img src="https://example.test/a(b).png" alt="流程图" />\n\n</div>'
        self.assertBody(render_document(document(block)), expected)
        block["caption"] = "  图一； "
        expected = '<div align="center">\n\n<img src="https://example.test/a(b).png" alt="流程图" />\n\n<p>图一</p>\n\n</div>'
        self.assertBody(render_document(document(block)), expected)

    def test_image_alt_trailing_backslash_cannot_escape_closing_bracket(self):
        block = {"type": "image", "alt": "路径\\", "url": "https://example.test/a.png"}
        expected = '<div align="center">\n\n<img src="https://example.test/a.png" alt="路径\\" />\n\n</div>'
        self.assertBody(render_document(document(block)), expected)

    def test_generated_table_is_centered_scrollable_and_keeps_data(self):
        table = "| 名称 | 状态 |\n|---|---:|\n| A | 2 |"
        block = {"type": "table", "text": table, "caption": "表一；"}
        expected = (
            '<div align="center">\n\n<div style="max-width: 100%; overflow-x: auto;">\n\n'
            '| 名称 | 状态 |\n|:---:|:---:|\n| A | 2 |\n\n</div>\n\n<p>表一</p>\n\n</div>'
        )
        self.assertBody(render_document(document(block)), expected)
        self.assertIn("| A | 2 |", render_document(document(block)))

    def test_literal_visual_layout_only_adds_outer_containers(self):
        image = "![原图](asset.png)"
        table = "| 原表头 | 数值 |\n|---|---:|\n| 原行 | 7 |"
        blocks = [
            {"type": "source", "id": "image", "layout": "centered_image", "caption": "原图题注"},
            {"type": "source", "id": "table", "layout": "centered_table", "caption": "原表题"},
        ]
        output = render_document(document(*blocks), sources={"image": image, "table": table})
        self.assertIn(image, output)
        self.assertIn(table, output)
        self.assertIn('<div style="max-width: 100%; overflow-x: auto;">', output)
        self.assertEqual(output.count('<div align="center">'), 2)

    def test_formula_is_separate_and_its_characters_are_protected(self):
        payload = "  x_{i+1} = x_i + 1 \\\\\r\n\\text{原样。；}  "
        output = render_document(document(paragraph("公式之前"), {"type": "formula", "text": payload}, paragraph("公式之后")))
        self.assertBody(output, "公式之前\n\n$$\n" + payload + "\n$$\n\n公式之后")

    def test_deep_inputs_are_unchanged_on_success_and_failure(self):
        doc = document(nested_list(), term(), {"type": "section", "heading": "来源。", "blocks": [
            {"type": "source", "id": "original"},
        ]})
        sources = {"original": "原始。\r\n"}
        before = copy.deepcopy((doc, sources))
        compact = render_document(doc, sources=sources)
        render_document(doc, sources=sources, host_nested_blank=True)
        self.assertEqual((doc, sources), before)
        self.assertEqual(render_document(doc, sources=sources), compact)
        doc["blocks"].append({"type": "paragraph", "text": "末块", "unknown": True})
        before = copy.deepcopy((doc, sources))
        with self.assertRaises(ValueError):
            render_document(doc, sources=sources)
        self.assertEqual((doc, sources), before)


class CompositionValidationTests(unittest.TestCase):
    def test_invalid_document_containers(self):
        cases = [None, False, [], "text", {}, {"blocks": []}, {"blocks": "text"},
                 {"blocks": {}}, {"blocks": [None]}, {"blocks": ["text"]},
                 {"blocks": [paragraph()], "unknown": 1}]
        for doc in cases:
            with self.subTest(document=doc), self.assertRaises(ValueError):
                render_document(doc)

    def test_required_fields_and_unknown_fields_for_every_block(self):
        blocks = [
            ({"type": "section", "heading": "标题", "blocks": [paragraph()]}, ("type", "heading", "blocks")),
            (paragraph(), ("type", "text")),
            ({"type": "list", "items": [{"text": "项目"}]}, ("type", "items")),
            (term(), ("type", "zh", "en", "definition")),
            ({"type": "source", "id": "s"}, ("type", "id")),
            ({"type": "code", "language": "python", "text": "x = 1"}, ("type", "language", "text")),
            ({"type": "image", "alt": "图", "url": "https://example.test/a.png"}, ("type", "alt", "url")),
            ({"type": "formula", "text": "x=1"}, ("type", "text")),
        ]
        for block, required in blocks:
            for key in (*required, "unknown"):
                invalid = copy.deepcopy(block)
                if key == "unknown":
                    invalid[key] = True
                else:
                    del invalid[key]
                sources = {"s": "原文"} if block["type"] == "source" else None
                with self.subTest(block=block["type"], key=key), self.assertRaises(ValueError):
                    render_document(document(invalid), sources=sources)

    def test_wrong_field_types_and_empty_containers(self):
        cases = [
            {"type": "unknown"}, {"type": []},
            {"type": "section", "heading": "标题", "blocks": []},
            {"type": "section", "heading": "标题", "blocks": {}},
            {"type": "list", "items": []}, {"type": "list", "items": "项目"},
            {"type": "list", "items": ["项目"]},
            {"type": "list", "items": [{}]},
            {"type": "list", "items": [{"text": "父", "children": "子"}]},
            {"type": "list", "items": [{"text": "父", "children": [{"text": "子", "unknown": 1}]}]},
            {"type": "list", "items": [{"text": "父", "children": [None]}]},
        ]
        for value in (0, 1, "false", None, []):
            cases.append({"type": "list", "ordered": value, "items": [{"text": "项目"}]})
            cases.append({"type": "list", "items": [{"text": "父", "children_ordered": value, "children": [{"text": "子"}]}]})
        for value in (None, "一，二，三", [], ["一", "二"], ["一"] * 6, ["一", "", "三"], ["一", 2, "三"]):
            cases.append(dict(term(), definition=value))
        for block in cases:
            with self.subTest(block=block), self.assertRaises(ValueError):
                render_document(document(block))

    def test_plain_text_fields_reject_types_empty_lines_and_block_markers(self):
        builders = [
            ("title", lambda value: dict(document(paragraph()), title=value)),
            ("heading", lambda value: document({"type": "section", "heading": value, "blocks": [paragraph()]})),
            ("paragraph", lambda value: document(paragraph(value))),
            ("item", lambda value: document({"type": "list", "items": [{"text": value}]})),
            ("child", lambda value: document({"type": "list", "items": [{"text": "父", "children": [{"text": value}]}]})),
            ("zh", lambda value: document(dict(term(), zh=value))),
            ("en", lambda value: document(dict(term(), en=value))),
            ("abbr", lambda value: document(dict(term(), abbr=value))),
            ("definition", lambda value: document(dict(term(), definition=["一", value, "三"]))),
            ("alt", lambda value: document({"type": "image", "alt": value, "url": "https://example.test/a.png"})),
            ("caption", lambda value: document({"type": "image", "alt": "图", "url": "https://example.test/a.png", "caption": value})),
        ]
        values = [None, True, 3, [], {}, "", " \t ", "。；", "甲\n乙", "甲\r乙", "甲\r\n乙",
                  "# 标题", "  ## 标题", "- 项目", "* 项目", "+ 项目", "1. 项目", "1) 项目",
                  "> 引用", "```python", "~~~text", "---", "| 甲 | 乙 |", "$$"]
        for field, build in builders:
            for value in values:
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    render_document(build(value))

    def test_protected_content_still_requires_nonempty_strings(self):
        for kind in ("code", "formula", "source"):
            for value in (None, False, 5, [], {}, "", " \t\r\n"):
                if kind == "source" and value == " \t\r\n":
                    # Literal whitespace is original data, not an empty authored field.
                    self.assertEqual(render_document(document({"type": "source", "id": "s"}),
                                                     sources={"s": value}), value)
                    continue
                block = {"type": kind, "text": value}
                sources = None
                if kind == "code":
                    block["language"] = "python"
                elif kind == "source":
                    block = {"type": "source", "id": "s"}
                    sources = {"s": value}
                with self.subTest(kind=kind, value=value), self.assertRaises(ValueError):
                    render_document(document(block), sources=sources)

    def test_source_reference_and_coverage_errors(self):
        cases = [
            ({"type": "source", "id": "missing"}, None),
            ({"type": "source", "id": "missing"}, {"other": "原文"}),
            ({"type": "source", "id": "s", "text": "伪造原文"}, {"s": "真实原文"}),
            ({"type": "source", "id": "s", "presentation": "html"}, {"s": "原文"}),
            ({"type": "source", "id": "s", "presentation": None}, {"s": "原文"}),
            ({"type": "source", "id": "s", "language": "python"}, {"s": "原文"}),
            ({"type": "source", "id": "s", "presentation": "quote", "language": "python"}, {"s": "原文"}),
        ]
        for value in (None, 1, [], "", " \t ", "a\nb"):
            cases.append(({"type": "source", "id": value}, {"s": "原文"}))
        for sources in ([], "source", 7, {"unused": "原文"}, {1: "原文"}):
            cases.append((paragraph(), sources))
        for block, sources in cases:
            with self.subTest(block=block, sources=sources), self.assertRaises(ValueError):
                render_document(document(block), sources=sources)

    def test_language_rejects_wrong_types_newlines_and_backticks(self):
        for value in (None, False, [], 3, "py\nthon", "py\rthon", "py`thon", "```python"):
            for kind in ("code", "source"):
                block = {"type": "code", "language": value, "text": "x=1"}
                sources = None
                if kind == "source":
                    block = {"type": "source", "id": "s", "presentation": "code", "language": value}
                    sources = {"s": "x=1"}
                with self.subTest(kind=kind, value=value), self.assertRaises(ValueError):
                    render_document(document(block), sources=sources)

    def test_image_rejects_invalid_url_and_bracketed_alt(self):
        for value in (None, 1, [], "", "  ", "a\nb", "a\rb", "<image.png>", "a>b", "a<b"):
            block = {"type": "image", "alt": "图", "url": value}
            with self.subTest(url=value), self.assertRaises(ValueError):
                render_document(document(block))
        for value in ("[图]", "左[图", "图]右"):
            block = {"type": "image", "alt": value, "url": "https://example.test/a.png"}
            with self.subTest(alt=value), self.assertRaises(ValueError):
                render_document(document(block))

    def test_host_spacing_requires_boolean(self):
        for value in (None, 0, 1, "false", []):
            with self.subTest(value=value), self.assertRaises(ValueError):
                render_document(document(nested_list()), host_nested_blank=value)


class CompositionCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.input_path = self.directory / "输入.json"
        self.sources_path = self.directory / "来源.json"
        self.output_path = self.directory / "输出.md"
        self.write_json(self.input_path, document(paragraph("中文输出。")))

    def write_json(self, path, value):
        path.write_bytes(json.dumps(value, ensure_ascii=False).encode("utf-8"))

    def invoke(self, *extra, output=None):
        arguments = ["--document", str(self.input_path), "--output", str(output or self.output_path), *extra]
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = main(arguments)
        return result, stdout.getvalue(), stderr.getvalue()

    def snapshot(self):
        return {path.name: path.read_bytes() for path in self.directory.iterdir() if path.is_file()}

    def assertRejectedUnchanged(self, *extra, output=None):
        before = self.snapshot()
        result, stdout, stderr = self.invoke(*extra, output=output)
        self.assertEqual(result, 2, (stdout, stderr))
        self.assertEqual(self.snapshot(), before)

    def test_success_creates_utf8_and_second_call_cannot_overwrite(self):
        original = self.input_path.read_bytes()
        result, stdout, stderr = self.invoke()
        self.assertEqual(result, 0, (stdout, stderr))
        self.assertIn(self.output_path.read_bytes(), ("中文输出".encode("utf-8"), "中文输出\n".encode("utf-8")))
        self.assertEqual(self.input_path.read_bytes(), original)
        self.assertRejectedUnchanged()

    def test_cli_sources_preserve_original_bytes_and_nested_spacing_modes(self):
        sources = {"s": "| 值 |\r\n| --- |\r\n| 原样。； |\r\n\r\n"}
        doc = document(nested_list(), {"type": "source", "id": "s"})
        self.write_json(self.input_path, doc)
        self.write_json(self.sources_path, sources)
        originals = self.snapshot()
        for mode, host_spacing in (("compact", False), ("host-required", True)):
            target = self.directory / (mode + ".md")
            with self.subTest(mode=mode):
                result, stdout, stderr = self.invoke("--sources", str(self.sources_path),
                    "--nested-list-spacing", mode, output=target)
                self.assertEqual(result, 0, (stdout, stderr))
                raw = target.read_bytes()
                self.assertEqual(raw, render_document(doc, sources=sources, host_nested_blank=host_spacing).encode("utf-8"))
                self.assertIn(sources["s"].encode("utf-8"), raw)
        for name, raw in originals.items():
            self.assertEqual((self.directory / name).read_bytes(), raw)

    def test_invalid_late_block_does_not_write_partial_output(self):
        self.write_json(self.input_path, document(paragraph("已完成的前文"), nested_list(),
                                                {"type": "paragraph", "text": "尾段", "unexpected": True}))
        self.assertRejectedUnchanged()
        self.assertFalse(self.output_path.exists())

    def test_malformed_json_invalid_utf8_and_missing_document(self):
        for raw in (b'{"blocks": [', b"\xff", b"null", b"[]"):
            self.input_path.write_bytes(raw)
            with self.subTest(raw=raw):
                self.assertRejectedUnchanged()
        self.input_path.unlink()
        self.assertRejectedUnchanged()

    def test_invalid_sources_and_unused_sources_do_not_create_output(self):
        self.write_json(self.input_path, document(paragraph("可先排版的正文"), {"type": "source", "id": "s"}))
        for sources in ([], {"s": 3}, {"other": "找不到所引用对象"}, {"s": "原文", "unused": "不能遗漏"}):
            self.write_json(self.sources_path, sources)
            with self.subTest(sources=sources):
                self.assertRejectedUnchanged("--sources", str(self.sources_path))
        self.sources_path.write_bytes(b"{")
        self.assertRejectedUnchanged("--sources", str(self.sources_path))
        self.sources_path.unlink()
        self.assertRejectedUnchanged("--sources", str(self.sources_path))

    def test_duplicate_source_and_document_keys_never_discard_content(self):
        self.write_json(self.input_path, document({"type": "source", "id": "s"}))
        self.sources_path.write_text('{"s":"原文甲。","s":"原文乙；"}', encoding="utf-8")
        self.assertRejectedUnchanged("--sources", str(self.sources_path))
        for raw in (
            '{"blocks":[],"blocks":[{"type":"paragraph","text":"后者"}]}',
            '{"blocks":[{"type":"paragraph","text":"前者","text":"后者"}]}',
        ):
            self.input_path.write_text(raw, encoding="utf-8")
            self.assertRejectedUnchanged()

    def test_invalid_surrogate_does_not_leave_a_file_and_valid_retry_succeeds(self):
        self.write_json(self.input_path, document({"type": "source", "id": "s"}))
        self.sources_path.write_bytes(b'{"s":"\\ud800"}')
        self.assertRejectedUnchanged("--sources", str(self.sources_path))
        self.assertFalse(self.output_path.exists())
        self.write_json(self.sources_path, {"s": "已核对的原文。"})
        result, stdout, stderr = self.invoke("--sources", str(self.sources_path))
        self.assertEqual(result, 0, (stdout, stderr))
        self.assertEqual(self.output_path.read_bytes(), "已核对的原文。\n".encode("utf-8"))

    def test_existing_output_and_input_paths_are_never_overwritten(self):
        self.output_path.write_bytes(b"\x00existing\xff\r\n")
        self.assertRejectedUnchanged()
        self.assertRejectedUnchanged(output=self.input_path)
        self.write_json(self.sources_path, {"s": "原文。"})
        self.write_json(self.input_path, document({"type": "source", "id": "s"}))
        self.assertRejectedUnchanged("--sources", str(self.sources_path), output=self.sources_path)

    def test_normalized_input_alias_is_rejected(self):
        subdirectory = self.directory / "subdirectory"
        subdirectory.mkdir()
        alias = subdirectory / ".." / self.input_path.name
        self.assertRejectedUnchanged(output=alias)

    def test_hard_link_input_alias_is_rejected(self):
        alias = self.directory / "input-alias.md"
        try:
            os.link(self.input_path, alias)
        except OSError as error:
            self.skipTest(f"Hard links unavailable on this filesystem: {error}")
        self.assertTrue(os.path.samefile(self.input_path, alias))
        self.assertRejectedUnchanged(output=alias)

    def test_symbolic_link_input_alias_is_rejected(self):
        alias = self.directory / "input-symlink.md"
        try:
            alias.symlink_to(self.input_path)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"Symbolic links unavailable on this filesystem: {error}")
        self.assertTrue(os.path.samefile(self.input_path, alias))
        self.assertRejectedUnchanged(output=alias)


class CompositionReviewIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.sources = {
            "table": "| 状态 | 数量 |\n|---|---|\n| READY | 2 |",
            "quote": "NOTICE: 原件必须保留。",
            "config": '{\n  "count": 2\n}',
        }
        self.draft = render_document(document(
            {"type": "source", "id": "table"},
            {"type": "source", "id": "quote", "presentation": "quote"},
            {"type": "source", "id": "config", "presentation": "code", "language": "json"},
            paragraph("先登记，再交接"),
        ), sources=self.sources)

    def proposal(self, report, old, new):
        node = next(item for item in report["format"]["line_nodes"] if old in item["text"])
        return {
            "document_sha256": report["format"]["document_sha256"],
            "edits": [{"node_id": node["node_id"], "old_text": old, "new_text": new,
                       "scope": "sentence", "reason": "将已确认的两个操作分别成项"}],
        }

    def test_composed_draft_accepts_local_structural_patch_without_changing_sources(self):
        checked, report = review_text(self.draft)
        self.assertEqual(checked, self.draft)
        self.assertTrue(any(item["rule_id"] == "FORMAT_PARALLEL_ITEMS_REVIEW" for item in report["format"]["candidates"]))
        proposal = self.proposal(report, "先登记，再交接", "1. 先登记\n2. 再交接")
        revised, final = review_text(self.draft, edit_transactions=[proposal])
        self.assertEqual(revised, self.draft.replace("先登记，再交接", "1. 先登记\n2. 再交接"))
        for raw in self.sources.values():
            self.assertIn(raw, revised)
        self.assertEqual(final["format"]["repair_rounds"], 1)
        self.assertFalse(final["format"]["delivery_blocked"])
        self.assertEqual(final["content"]["user_acceptance"], "NOT_ASSESSED")
        with self.assertRaises(PatchError):
            review_text(revised, edit_transactions=[proposal])  # A previous draft's hash cannot be reused.

    def test_one_protected_source_edit_rejects_the_whole_structural_patch(self):
        _, report = review_text(self.draft)
        proposal = self.proposal(report, "先登记，再交接", "1. 先登记\n2. 再交接")
        protected = self.proposal(report, "NOTICE: 原件必须保留。", "NOTICE: 改写过的原件")
        proposal["edits"].extend(protected["edits"])
        with self.assertRaises(PatchError):
            review_text(self.draft, edit_transactions=[proposal])
        self.assertEqual(review_text(self.draft)[0], self.draft)


if __name__ == "__main__":
    unittest.main()
