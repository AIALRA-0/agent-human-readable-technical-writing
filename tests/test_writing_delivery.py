"""Regression checks for local, bounded writing review without a model runner."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from patcher.deterministic_committer import PatchError, sha256_text
from runtime.align_inline_comments import check_alignment
from runtime.format_validation import deterministic_format_findings, deterministic_format_replacements
from scripts import review_writing as review


def exact_patch(text: str, old: str, new: str, node: str = "LINE-0001") -> dict:
    return {
        "identity": {"patch_id": "PATCH-001", "finding_id": "local-review", "operation": "replace_exact"},
        "target": {"document_sha256": sha256_text(text), "node_id": node},
        "replacement": {"old_text": old, "new_text": new, "expected_occurrences": 1},
        "authorization": {"reason": "修复已确认的局部问题", "repair_scope": "token", "preserve": ["原始信息"]},
        "verification": {"rerun_validators": ["format", "protected_material"]},
    }


class FormatRegressionTests(unittest.TestCase):
    def test_local_review_trigger_contract_is_consistent(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        local_review = (ROOT / "references" / "local-review.md").read_text(encoding="utf-8")
        for content in (skill, readme, local_review):
            self.assertIn("纯聊天", content)
            self.assertIn("本地文档", content)
            self.assertIn("用户明确要求", content)
        self.assertNotIn("有本地工具时先把内部初稿", skill)
        self.assertNotIn("普通写作不要求运行仓库工具", readme)

    def test_source_contradiction_rule_keeps_relation_and_field_uncertainty(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        explanation = (ROOT / "references" / "explanation-framework.md").read_text(encoding="utf-8")
        for content in (skill, explanation):
            self.assertIn("核算", content)
            self.assertIn("仅凭当前材料无法确定哪个原始字段有误", content)
            self.assertIn("原始字段", content)
            self.assertIn("不能停在计算结果", content)

    def test_parenthetical_term_payload_rejects_aliases_explanations_and_separators(self):
        invalid = (
            "解析布局（Layout Resolution，也称 布局解析）",
            "解析布局（Layout Resolution，布局解析）",
            "解析布局（Layout Resolution, Layout Parsing）",
            "解析布局（Layout Resolution also known as Layout Parsing）",
            "应用程序接口（Application Programming Interface，API）",
            "解析布局（Layout Resolution；负责解析布局）",
        )
        for text in invalid:
            with self.subTest(text=text):
                rules = {item["rule_id"] for item in deterministic_format_findings(text)}
                self.assertIn("FORMAT_PARENTHETICAL_TERM_CONTENT", rules)

    def test_parenthetical_term_payload_preserves_valid_and_protected_content(self):
        valid = (
            "解析布局（Layout Resolution），中文别名为“布局解析”",
            "API 应用程序接口（Application Programming Interface）",
            "解析布局，也称布局解析",
            "本次共 3 项（其中 1 项待核对）",
            "Node.js（在服务端运行 JavaScript）负责接收请求",
            "> 原文写成解析布局（Layout Resolution，也称布局解析）\n",
            "```text\n解析布局（Layout Resolution，也称布局解析）\n```\n",
        )
        for text in valid:
            with self.subTest(text=text):
                rules = {item["rule_id"] for item in deterministic_format_findings(text)}
                self.assertNotIn("FORMAT_PARENTHETICAL_TERM_CONTENT", rules)

    def test_host_nested_blank_is_explicit_and_does_not_loosen_peer_spacing(self):
        source = "1. 主步骤\n\n   - 子项甲\n\n   - 子项乙\n\n2. 下一步\n"
        expected = "1. 主步骤\n\n   - 子项甲\n   - 子项乙\n2. 下一步\n"
        fixed, report = review.review_text(source, fix_safe=True, host_nested_blank=True)
        self.assertEqual(fixed, expected)
        self.assertEqual(report["format"]["nested_list_spacing"], "host-required")
        self.assertEqual(report["format"]["findings"], [])
        self.assertEqual(review.review_text(fixed, fix_safe=True, host_nested_blank=True)[0], fixed)
        compact, report = review.review_text(source, fix_safe=True)
        self.assertEqual(compact, expected.replace("\n\n", "\n"))
        self.assertEqual(report["format"]["nested_list_spacing"], "compact")

    def test_host_nested_blank_inserts_only_at_new_deeper_lists(self):
        for ending in ("\n", "\r\n"):
            source = "- 父项\n    1. 子项\n        - 孙项\n    2. 另一子项\n- 另一父项\n".replace("\n", ending)
            expected = "- 父项\n\n    1. 子项\n\n        - 孙项\n    2. 另一子项\n- 另一父项\n".replace("\n", ending)
            fixed, report = review.review_text(source, fix_safe=True, host_nested_blank=True)
            self.assertEqual(fixed, expected)
            self.assertEqual(report["format"]["repair_rounds"], 1)
            self.assertEqual(report["format"]["findings"], [])

    def test_python_highlighted_literal_inputs_and_results_do_not_need_comments(self):
        for caption in ("给定的示例输入是：", "最终返回的新列表是：", "5. 三条都看完后交回下面的新列表", "## 最终结果"):
            for data in ('[{"id": "Z-1", "count": 2}]', "{'ok': True}", "42"):
                source = caption + "\n\n```python\n" + data + "\n```\n"
                findings = deterministic_format_findings(source)
                self.assertFalse(any(item["rule_id"] == "FORMAT_CODE_COMMENT_COVERAGE" for item in findings))
                self.assertEqual(review.review_text(source, fix_safe=True)[0], source)

    def test_data_caption_cannot_exempt_execution_or_leak_across_a_block(self):
        for code in ("x = [1]", "print([1])", "[x for x in items]", "1 + 2"):
            source = "给定的示例输入是：\n\n```python\n" + code + "\n```\n"
            self.assertTrue(any(item["rule_id"] == "FORMAT_CODE_COMMENT_COVERAGE" for item in deterministic_format_findings(source)))
        for separation in ("## 新代码\n\n", "```text\nsource\n```\n\n"):
            source = "最终结果\n\n" + separation + "```python\n[1]\n```\n"
            self.assertTrue(any(item["rule_id"] == "FORMAT_CODE_COMMENT_COVERAGE" for item in deterministic_format_findings(source)))

    def test_negated_data_caption_does_not_exempt_a_code_literal(self):
        for caption in ("下面的 Python 代码不是输入数据：", "它并非最终结果", "这不能当作输出数据："):
            source = caption + "\n\n```python\n[1]\n```\n"
            self.assertTrue(any(f["rule_id"] == "FORMAT_CODE_COMMENT_COVERAGE" for f in deterministic_format_findings(source)))
        source = "不是原代码，最终结果是：\n\n```python\n[1]\n```\n"
        self.assertFalse(any(f["rule_id"] == "FORMAT_CODE_COMMENT_COVERAGE" for f in deterministic_format_findings(source)))

    def test_negated_code_roles_neither_exempt_new_code_nor_open_original_comments(self):
        source = "这不是原始代码，是新写的演示\n\n```python\nx = 1\n```\n"
        self.assertTrue(any(f["rule_id"] == "FORMAT_CODE_COMMENT_COVERAGE" for f in deterministic_format_findings(source)))
        original = "这不是解释副本，而是原始代码\n\n```python\nx = 1 # 原注释\n```\n"
        self.assertFalse(any(f["rule_id"] == "FORMAT_CODE_COMMENT_COVERAGE" for f in deterministic_format_findings(original)))
        with self.assertRaises(PatchError):
            review.review_text(original, transactions=[[exact_patch(original, "原注释", "新注释", "LINE-0004")]])
        authored = "不是原始代码，而是解释副本\n\n```python\nx = 1 # 旧说明\n```\n"
        fixed, _ = review.review_text(authored, transactions=[[exact_patch(authored, "旧说明", "新说明", "LINE-0004")]])
        self.assertIn("新说明", fixed)

    def test_indented_list_continuation_is_not_an_independent_paragraph(self):
        source = "- 父项\n  延续说明\n  - 子项\n"
        self.assertEqual(review.review_text(source, fix_safe=True)[0], source)
        expected = "- 父项\n  延续说明\n\n  - 子项\n"
        self.assertEqual(review.review_text(source, fix_safe=True, host_nested_blank=True)[0], expected)
        same = "- 父项\n  延续说明\n- 同级项\n"
        self.assertEqual(review.review_text(same, fix_safe=True, host_nested_blank=True)[0], same)
        separate = "- 父项\n  延续说明\n1. 新步骤\n"
        self.assertEqual(review.review_text(separate, fix_safe=True)[0], separate.replace("\n1.", "\n\n1."))

    def test_different_peer_list_blocks_keep_or_gain_one_separator(self):
        for ending in ("\n", "\r\n"):
            for first, second in (("- 状态为待复核", "1. 提交登记"), ("1. 提交登记", "- 已收到"), ("- 第一组", "* 第二组")):
                with self.subTest(ending=ending, first=first, second=second):
                    correct = first + ending * 2 + second + ending
                    self.assertEqual(deterministic_format_replacements(correct), [])
                    fixed, report = review.review_text(first + ending + second + ending, fix_safe=True)
                    self.assertEqual(fixed, correct)
                    self.assertEqual(report["format"]["repair_rounds"], 1)
                    self.assertEqual(deterministic_format_replacements(fixed), [])

    def test_same_list_and_mixed_nested_list_stay_compact(self):
        for first, second in (("- 第一项", "- 第二项"), ("1. 第一步", "2. 第二步"), ("- 父项", "    1. 子步骤"), ("    1. 子步骤", "- 下一父项")):
            with self.subTest(first=first, second=second):
                compact = first + "\n" + second + "\n"
                self.assertEqual(review.review_text(first + "\n\n" + second + "\n", fix_safe=True)[0], compact)
                self.assertEqual(deterministic_format_replacements(compact), [])

    def test_new_peer_list_after_nested_child_keeps_its_separator(self):
        for ending in ("\n", "\r\n"):
            for child_indent in ("   ", "    ", "\t"):
                with self.subTest(ending=ending, child_indent=child_indent):
                    steps = "1. 确认安排日期\n" + child_indent + "- 日期不是无条件保证\n"
                    following = "- 缺材料不占制作位置\n- 缺尺寸不占制作位置\n"
                    correct = (steps + "\n" + following).replace("\n", ending)
                    self.assertEqual(deterministic_format_replacements(correct), [])
                    fixed, report = review.review_text((steps + following).replace("\n", ending), fix_safe=True)
                    self.assertEqual(fixed, correct)
                    self.assertEqual(report["format"]["repair_rounds"], 1)
                    self.assertEqual(deterministic_format_replacements(fixed), [])

    def test_nested_peer_boundary_is_not_confused_with_return_to_parent(self):
        cases = (
            ("- 父组\n    1. 子步骤\n        - 子说明\n\n    - 子条件\n", True),
            ("- 父组\n    1. 子步骤\n        - 子说明\n\n- 下个父组\n", False),
            ("1. 步骤\n    - 子说明\n\n2. 下一步骤\n", False),
        )
        for text, keep in cases:
            with self.subTest(text=text):
                fixed, _ = review.review_text(text, fix_safe=True)
                self.assertEqual(fixed, text if keep else text.replace("\n\n", "\n"))
                self.assertEqual(deterministic_format_replacements(fixed), [])

    def test_long_physical_lines_lose_only_their_terminal_punctuation(self):
        paragraphs = [
            f"第 {number} 项检查已经完成软件侧的输入读取、字段核对和结果导出，记录中的 12 条样本均来自本次测试，"
            "其中没有包含现场设备的数据，也没有验证断网后的恢复过程。只有现场复测确认了相同的输入条件、"
            "设备版本和供电状态，才可以比较两次输出是否一致；目前仍不能据此认定所有部署环境都已通过验证"
            + ("。" if number % 2 else "；")
            for number in range(1, 49)
        ]
        text = "\n\n".join(paragraphs)
        fixed, report = review.review_text(text, fix_safe=True)
        self.assertEqual(fixed, "\n\n".join(paragraph[:-1] for paragraph in paragraphs))
        self.assertEqual(report["format"]["repair_rounds"], 1)
        self.assertEqual(report["format"]["status"], "ISSUES_REMAIN")  # Interior full stops still need review.
        self.assertEqual(len(report["format"]["rounds"][0]["patches"]), 48)
        self.assertEqual(deterministic_format_replacements(fixed), [])

    def test_block_separator_and_terminal_punctuation_form_one_proposal(self):
        for ending in ("\n", "\r\n"):
            for terminal in ("。", "；"):
                with self.subTest(ending=ending, terminal=terminal):
                    item = "- 软件验证通过。现场尚未验证" + terminal + "  \t" + ending
                    text = "说明" + ending + item
                    proposals = deterministic_format_replacements(text)
                    self.assertEqual(len(proposals), 1)
                    self.assertEqual(proposals[0]["node_id"], "LINE-0002")
                    self.assertEqual(proposals[0]["old_text"], item)
                    self.assertIn("FORMAT_BLOCK_SPACING+", proposals[0]["rule_id"])
                    expected = "说明" + ending * 2 + "- 软件验证通过。现场尚未验证  \t" + ending
                    fixed, report = review.review_text(text, fix_safe=True)
                    self.assertEqual(fixed, expected)
                    self.assertEqual(report["format"]["repair_rounds"], 1)

    def test_other_endings_quotes_and_interior_punctuation_remain_exact(self):
        untouched = [
            "前句。后句没有末尾句号", "同一行；后续内容", "保留逗号，", "保留冒号：",
            "真的？", "确认！", "省略……", "保留破折号——", "英文句点.", "英文分号;",
            "‘原件。’", "'原件。'", '"原件。"', "“原件。”", "引用内分号‘原件；’",
            "末尾句号后有感叹号。！", "`代码。`", "$\\text{公式。}$",
            "[链接原文。](https://example.test/路径。)", "https://example.test/原样。",
        ]
        text = "\n\n".join(untouched)
        self.assertEqual(deterministic_format_replacements(text), [])
        self.assertEqual(review.review_text(text, fix_safe=True)[0], text)
        outside = "‘原件。’。\n\n`字段；`；\n\n[链接原文。](https://example.test/路径。)。\n\n$\\text{公式。}$。"
        expected = "‘原件。’\n\n`字段；`\n\n[链接原文。](https://example.test/路径。)\n\n$\\text{公式。}$"
        self.assertEqual(review.review_text(outside, fix_safe=True)[0], expected)

    def test_literal_originals_with_bom_are_never_punctuation_repaired(self):
        originals = [
            "```text\n原文。\n原文；\n```\n",
            "~~~log\n原始日志。\n日志；\n~~~\n",
            "原样代码\n\n```python\nx = 1 # 注释。\nlong_name = 2 # 注释；\n```\n",
            "> 引文。\n> 引文；\n",
            "| 列 | 值 |\n| --- | --- |\n| 甲。 | 乙； |\n",
            "列 | 值\n--- | ---\n甲 | 原始值。\n乙 | 原始值；\n",
            "$$\n\\text{原始公式。}\n原式；\n$$\n",
            "\\[\n原始公式。\n原式；\n\\]\n",
            "[source]: https://example.test/原样。\n",
        ]
        for original in originals:
            for bom in ("", "\ufeff"):
                with self.subTest(original=original, bom=bom):
                    text = bom + original.replace("\n", "\r\n")
                    self.assertEqual(deterministic_format_replacements(text), [])
                    self.assertEqual(review.review_text(text, fix_safe=True)[0].encode("utf-8"), text.encode("utf-8"))

    def test_literal_objects_are_exempt_but_adjacent_prose_is_checked(self):
        text = (
            "# 标题。\n\n> 原文。\n>\n> 保留。\n\n"
            "| 原始列。 | 值 |\n| --- | --- |\n| 单元格。 | 0 |\n\n"
            "列 | 值\n--- | ---\n原始值。 | 缺失\n\n"
            "$$\n\\text{公式。}\n\n\n x=1\n$$\n\n"
            "\\[\n\\text{公式。}\n\\]\n\n"
            "[原始链接。](https://example.test/路径。)\n\n"
            "[引用。][source]\n\n[source]: https://example.test/原文。\n\n"
            "`原样。` 与 $\\text{公式。}$，正文。\n\n"
            "[链接。](https://example.test/a_(路径。)) 后文。\n\n"
            "![图。](image.svg) 题注。\n\n"
            "- 列表。\n\n表外说明。\n\n"
            "~~~text\n原样。\n~~~\n\n"
            "````text\n```\n仍是原始文本。\n````\n"
        )
        findings = deterministic_format_findings(text)
        stops = [item for item in findings if item["rule_id"] == "FORMAT_NO_CHINESE_FULL_STOP"]
        self.assertEqual(len(stops), 6)
        self.assertTrue(all(item["status"] == "FAIL" for item in stops))
        self.assertNotIn("FORMAT_EXCESSIVE_BLANK_LINES", {item["rule_id"] for item in findings})

    def test_fields_are_not_headings_and_semantics_remain_candidates(self):
        findings = deterministic_format_findings("操作：具体内容\n\n操作：`实际命令`\n\n术语：普通解释\n\n软件（iPhone）\n\n审核人员（auditor）\n\n操作：")
        headings = [item for item in findings if item["rule_id"] == "FORMAT_COLON_PSEUDO_HEADING"]
        self.assertEqual(len(headings), 1)
        self.assertEqual(headings[0]["old_text"], "操作：")
        self.assertTrue(all(item["status"] == "REVIEW_REQUIRED" for item in findings))
        self.assertTrue(all(item["severity"] == "MACHINE_CANDIDATE" for item in findings))

    def test_heading_hierarchy_rejects_skipped_levels(self):
        text = "## 公式说明\n\n#### 每个符号代表什么\n\n- `$x$` 表示输入值"
        findings = deterministic_format_findings(text)
        skipped = [item for item in findings if item["rule_id"] == "FORMAT_HEADING_LEVEL_SKIP"]
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0]["status"], "FAIL")
        self.assertEqual(skipped[0]["location"], "LINE-0003")

    def test_heading_numbering_inherits_one_peer_style(self):
        consistent = "## 当前状态\n\n内容甲\n\n## 下一步\n\n内容乙"
        self.assertFalse(any(
            item["rule_id"] == "FORMAT_HEADING_NUMBERING_REVIEW"
            for item in deterministic_format_findings(consistent)
        ))
        mixed = "## 1. 当前状态\n\n内容甲\n\n## 下一步\n\n内容乙"
        findings = deterministic_format_findings(mixed)
        numbering = [item for item in findings if item["rule_id"] == "FORMAT_HEADING_NUMBERING_REVIEW"]
        self.assertEqual(len(numbering), 1)
        self.assertEqual(numbering[0]["status"], "REVIEW_REQUIRED")

    def test_one_semantic_block_needs_no_heading(self):
        text = "当前版本已保存全部修改，下一步可以运行本地检查"
        heading_rules = {
            item["rule_id"] for item in deterministic_format_findings(text)
            if item["rule_id"].startswith("FORMAT_HEADING_")
        }
        self.assertEqual(heading_rules, set())

    def test_independent_intro_blocks_before_heading_require_review(self):
        text = "第一块说明\n\n第二块说明\n\n## 后续步骤\n\n继续处理"
        findings = deterministic_format_findings(text)
        intro = [item for item in findings if item["rule_id"] == "FORMAT_HEADING_INTRO_SCOPE_REVIEW"]
        self.assertEqual(len(intro), 1)
        self.assertEqual(intro[0]["status"], "REVIEW_REQUIRED")

    def test_complete_formula_explanation_has_no_formula_candidates(self):
        text = (
            "## 平均速度公式\n\n"
            "这条关系把总路程和总时间换算成平均每秒经过的路程\n\n"
            "$$\n"
            "v = \\frac{d}{t}\n"
            "$$\n\n"
            "### 每个符号代表什么\n\n"
            "- `$v$` 表示平均速度，是最终结果，单位由路程单位和时间单位共同决定\n"
            "- `$d$` 表示总路程，是需要被平均的总量\n"
            "- `$t$` 表示总时间，是计算的时间范围，并且必须大于零\n\n"
            "### 公式组分怎样理解\n\n"
            "- `$d / t$` 表示总路程除以总时间，得到单位时间内经过的平均路程\n"
        )
        findings = deterministic_format_findings(text)
        formula_rules = {item["rule_id"] for item in findings if item["rule_id"].startswith("FORMAT_FORMULA_")}
        self.assertEqual(formula_rules, set())

    def test_incomplete_formula_explanation_identifies_review_targets(self):
        text = "$$\ny_k = x_k + \\beta_k(x_k - x_{k-1})\n$$"
        findings = deterministic_format_findings(text)
        formula_rules = {item["rule_id"] for item in findings if item["rule_id"].startswith("FORMAT_FORMULA_")}
        self.assertEqual(formula_rules, {
            "FORMAT_FORMULA_HEADING_REVIEW",
            "FORMAT_FORMULA_SYMBOL_REVIEW",
            "FORMAT_FORMULA_COMPONENT_REVIEW",
        })
        self.assertTrue(all(
            item["status"] == "REVIEW_REQUIRED"
            for item in findings if item["rule_id"].startswith("FORMAT_FORMULA_")
        ))
        symbol_finding = next(item for item in findings if item["rule_id"] == "FORMAT_FORMULA_SYMBOL_REVIEW")
        self.assertIn(r"\beta", symbol_finding["reason"])

    def test_formula_scanner_ignores_literal_code_and_quotes(self):
        text = "> $$ x = y $$\n\n```text\n$$\nx = y\n$$\n```"
        self.assertFalse(any(
            item["rule_id"].startswith("FORMAT_FORMULA_")
            for item in deterministic_format_findings(text)
        ))

    def test_follow_up_substitution_does_not_repeat_formula_definitions(self):
        text = (
            "## 长方形面积公式\n\n"
            "$$\nA = w \\times h\n$$\n\n"
            "### 每个符号代表什么\n\n"
            "- `$A$` 表示面积，是最终结果\n"
            "- `$w$` 表示宽度，是第一个输入\n"
            "- `$h$` 表示高度，是第二个输入\n"
            "- `$w \\times h$` 表示宽度乘以高度，得到覆盖的平面大小\n\n"
            "### 代入一个具体例子\n\n"
            "$$\nA = 3 \\times 2 = 6\n$$\n\n"
            "这个演示结果表示长方形覆盖了 6 个单位面积\n"
        )
        self.assertFalse(any(
            item["rule_id"].startswith("FORMAT_FORMULA_")
            for item in deterministic_format_findings(text)
        ))

    def test_punctuation_after_display_math_is_still_prose(self):
        for formula in (r"$$\text{原样。}$$。", r"\[\text{原样。}\]。"):
            findings = deterministic_format_findings(formula)
            self.assertEqual([item["rule_id"] for item in findings].count("FORMAT_NO_CHINESE_FULL_STOP"), 1)

    def test_complete_inline_comments_need_no_header_and_enumeration_is_not_proof(self):
        text = "```sql\nSELECT a, b -- 返回 a、b 两个字段\nFROM t      -- 读取记录\n```"
        findings = deterministic_format_findings(text)
        self.assertNotIn("FORMAT_CODE_BLOCK_HEADER", {item["rule_id"] for item in findings})
        self.assertNotIn("FORMAT_CODE_COMMENT_COVERAGE", {item["rule_id"] for item in findings})
        enumeration = [item for item in findings if item["rule_id"] == "FORMAT_CODE_COMMENT_ENUMERATION"]
        self.assertEqual(enumeration[0]["status"], "REVIEW_REQUIRED")

    def test_real_list_spacing_alignment_and_coverage_are_still_detected(self):
        text = "- 甲\n\n- 乙\n\n```python\nx = 1 # 甲\nlong_name = 2 # 乙\nmissing = 3\n```"
        rules = {item["rule_id"] for item in deterministic_format_findings(text) if item["status"] == "FAIL"}
        self.assertTrue({"FORMAT_LIST_INTERNAL_BLANK", "FORMAT_CODE_COMMENT_ALIGNMENT", "FORMAT_CODE_COMMENT_COVERAGE"} <= rules)

    def test_safe_fixes_keep_source_objects_and_crlf_byte_for_byte(self):
        original = (
            "原样代码\n\n```python\nx = 1 # 原始注释。\nlong_name = 2 # 不对齐。\n\n\n```\n\n"
            "> 原文。\n> - 第一点。\n>\n> - 第二点。\n\n"
            "| 列。 | 值 |\n| --- | --- |\n| 原始值。 | 0 |\n\n"
            "$$\n- 公式。\n\n- 不可删除空行。\n$$\n\n"
            "[来源。](https://example.test/来源。) 和 `字段。`\n\n"
            "~~~log\n- 原始日志。\n\n- 日志保持。\n~~~\n\n"
        ).replace("\n", "\r\n")
        text = original + "- 甲\r\n\r\n- 乙\r\n\r\n```python\r\nx = 1 # 短\r\nlong_name = 2 # 长\r\n```"
        fixed, report = review.review_text(text, fix_safe=True)
        self.assertTrue(fixed.startswith(original))
        self.assertIn("- 甲\r\n- 乙", fixed)
        self.assertNotIn("\n", fixed.replace("\r\n", ""))
        body = fixed.rsplit("```python\r\n", 1)[1].removesuffix("```")
        self.assertEqual(check_alignment(body)["status"], "PASS")
        self.assertLessEqual(report["format"]["repair_rounds"], 2)
        self.assertEqual(report["content"]["user_acceptance"], "NOT_ASSESSED")

    def test_multiline_string_markers_are_never_auto_aligned(self):
        for text in (
            '```python\npayload = """\nx = 1 # literal\nlong_name = 2 # literal\n"""\n```',
            "```sql\nSELECT 'first\nx # literal -- literal\nlast';\n```",
            "```bash\ncat <<EOF\nx # literal\nlong_name # literal\nEOF\n```",
        ):
            with self.subTest(text=text):
                self.assertFalse(deterministic_format_replacements(text))
                self.assertEqual(review.review_text(text, fix_safe=True)[0], text)

    def test_explanation_copy_mentioning_original_is_checked_and_aligned(self):
        for caption in (
            "下面这份是解释副本，执行语句与原始代码相同，只加了注释",
            "下面是与原代码相同的注释版",
            "## 带注释的解释副本\n\n下面的注释只说明每一行，不改变原来的执行方式",
            "## 带注释的读法\n\n下面这一份只增加中文注释，代码语句本身与原始代码相同",
        ):
            for ending in ("\n", "\r\n"):
                with self.subTest(caption=caption, ending=ending):
                    text = (caption + "\n\n```python\nx = 1 # 短\nlong_name = 2 # 长\n```\n").replace("\n", ending)
                    rules = {item["rule_id"] for item in deterministic_format_findings(text)}
                    self.assertIn("FORMAT_CODE_COMMENT_ALIGNMENT", rules)
                    fixed, report = review.review_text(text, fix_safe=True)
                    self.assertNotEqual(fixed, text)
                    self.assertEqual(report["format"]["repair_rounds"], 1)
                    self.assertNotIn("FORMAT_CODE_COMMENT_ALIGNMENT", {item["rule_id"] for item in deterministic_format_findings(fixed)})
                    self.assertEqual(review.review_text(fixed, fix_safe=True)[0], fixed)

    def test_original_heading_exempts_comments_and_preserves_existing_padding(self):
        for heading in ("## 原代码和给定订单", "## 原始代码", "## 逐字保留的原件", "## 带注释的原始代码"):
            for body in ("x = 1", "x = 1 # 原文\nlong_name = 2 # 原文"):
                text = heading + "\n\n```python\n" + body + "\n```\n"
                with self.subTest(heading=heading, body=body):
                    rules = {item["rule_id"] for item in deterministic_format_findings(text)}
                    self.assertNotIn("FORMAT_CODE_COMMENT_COVERAGE", rules)
                    self.assertNotIn("FORMAT_CODE_COMMENT_ALIGNMENT", rules)
                    self.assertEqual(review.review_text(text, fix_safe=True)[0], text)
                    if "#" in body:
                        with self.assertRaises(PatchError):
                            review.review_text(text, transactions=[[exact_patch(text, " #", "  #", "LINE-0004")]])

    def test_source_role_does_not_leak_across_fence_or_new_heading(self):
        original = "## 原代码\n\n```python\nx = 1\n```\n\n"
        for separation in ("", "## 新的处理步骤\n\n"):
            text = original + separation + "```python\ny = 2\n```"
            findings = [item for item in deterministic_format_findings(text) if item["rule_id"] == "FORMAT_CODE_COMMENT_COVERAGE"]
            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0]["old_text"], "y = 2")

    def test_parallel_review_targets_are_advisory_and_never_auto_split(self):
        text = "- 费用：是否收费、是否需要押金\n- 盒盖关紧后，水汽较难进入，物品更不易受潮\n"
        targets = [item for item in deterministic_format_findings(text) if item["rule_id"] == "FORMAT_PARALLEL_ITEMS_REVIEW"]
        self.assertEqual(len(targets), 2)  # Syntax is a review target, not a semantic verdict.
        self.assertTrue(all(item["status"] == "REVIEW_REQUIRED" and item["severity"] == "MACHINE_CANDIDATE" for item in targets))
        fixed, report = review.review_text(text, fix_safe=True)
        self.assertEqual(fixed, text)
        self.assertEqual(report["format"]["findings"], [])
        self.assertFalse(report["format"]["delivery_blocked"])

    def test_multiple_authored_questions_are_review_targets_not_automatic_errors(self):
        text = '- “费用是多少？在哪里领取？”\n- 能借到吗？\n\n> 费用是多少？在哪里领取？\n'
        fixed, report = review.review_text(text, fix_safe=True)
        targets = [item for item in report["format"]["candidates"] if item["rule_id"] == "FORMAT_PARALLEL_ITEMS_REVIEW"]
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0]["location"], "LINE-0001")
        self.assertEqual(fixed, text)
        self.assertEqual(report["format"]["findings"], [])

    def test_paragraph_parallel_targets_are_advisory_without_automatic_splitting(self):
        text = "先发送通知，再登记时间\n\n盒盖关紧后，水汽较难进入，物品更不易受潮\n"
        fixed, report = review.review_text(text, fix_safe=True)
        targets = [item for item in report["format"]["candidates"] if item["rule_id"] == "FORMAT_PARALLEL_ITEMS_REVIEW"]
        self.assertEqual([item["location"] for item in targets], ["LINE-0001", "LINE-0003"])
        self.assertTrue(all(item["severity"] == "MACHINE_CANDIDATE" for item in targets))
        self.assertEqual(fixed, text)  # A comma cannot distinguish independent actions from a causal explanation.
        self.assertEqual(report["format"]["findings"], [])
        self.assertFalse(report["format"]["delivery_blocked"])

    def test_paragraph_review_does_not_expand_into_protected_or_heading_content(self):
        text = (
            "## 接收、登记与处理\n\n"
            "> 接收、登记\n\n"
            "```text\n接收、登记\n```\n\n"
            "| 项目 | 说明 |\n|---|---|\n| 一 | 接收、登记 |\n\n"
            "$$\na,b\n$$\n\n"
            "- 记录（Record）：保留已发生的事情；它用于核对，不代表许可\n"
        )
        self.assertFalse(any(item["rule_id"] == "FORMAT_PARALLEL_ITEMS_REVIEW" for item in deterministic_format_findings(text)))

    def test_supplied_images_need_embedded_objects_and_nonempty_alt(self):
        images = ["F:/fixtures/flow chart.png", "https://example.test/route.png"]
        text = '<div align="center">\n\n![办理流程](<F:/fixtures/flow chart.png>)\n\n</div>\n\n[第二张图](https://example.test/route.png)\n'
        fixed, report = review.review_text(text, source_images=images)
        self.assertEqual(fixed, text)
        self.assertEqual([f["rule_id"] for f in report["format"]["findings"]], ["FORMAT_SOURCE_IMAGE_MISSING"])
        complete = text.replace("[第二张图](https://example.test/route.png)", '<div align="center">\n\n![第二张图](https://example.test/route.png)\n\n</div>')
        self.assertEqual(review.review_text(complete, source_images=images)[1]["format"]["findings"], [])
        empty_alt = complete.replace("![第二张图]", "![]")
        self.assertEqual([f["rule_id"] for f in review.review_text(empty_alt, source_images=images)[1]["format"]["findings"]], ["FORMAT_SOURCE_IMAGE_ALT_MISSING"])

    def test_image_address_matching_preserves_case_sensitive_urls_and_literal_blocks(self):
        source = "https://example.test/Route.png"
        for text in ("```text\n![图](" + source + ")\n```", "`![图](" + source + ")`", "![图](https://example.test/route.png)"):
            self.assertTrue(any(f["rule_id"] == "FORMAT_SOURCE_IMAGE_MISSING" for f in review.review_text(text, source_images=[source])[1]["format"]["findings"]))
        source = "F:/fixtures/a (1).png"
        text = '<div align="center">\n\n![图](F:/fixtures/a%20%281%29.png "题注")\n\n</div>'
        self.assertEqual(review.review_text(text, source_images=[source, source])[1]["format"]["findings"], [])
        self.assertEqual(review.review_text("", source_images=[source])[1]["format"]["findings"][0]["location"], "DOCUMENT")

    def test_image_presence_sees_rendered_table_and_quote_images_without_decoding_url_queries(self):
        source = "https://example.test/image?name=a%26b"
        table = '<div align="center">\n\n| 图片 |\n|:---:|\n| ![图](' + source + ') |\n\n</div>'
        for text in ("> ![图](" + source + ")", table):
            self.assertEqual(review.review_text(text, source_images=[source])[1]["format"]["findings"], [])
        changed = "![图](https://example.test/image?name=a&b)"
        self.assertTrue(any(f["rule_id"] == "FORMAT_SOURCE_IMAGE_MISSING" for f in review.review_text(changed, source_images=[source])[1]["format"]["findings"]))
        percent_file = "F:/fixtures/a%20b.png"
        percent_text = '<div align="center">\n\n![图](F:/fixtures/a%2520b.png)\n\n</div>'
        self.assertEqual(review.review_text(percent_text, source_images=[percent_file])[1]["format"]["findings"], [])

    def test_local_image_addresses_and_reference_images_are_recognized(self):
        for source in ("assets/flow chart.png", "/tmp/flow chart.png"):
            body = '<div align="center">\n\n![流程](' + source.replace(" ", "%20") + ')\n\n</div>'
            self.assertEqual(review.review_text(body, source_images=[source])[1]["format"]["findings"], [])
        for use in ("![流程][FLOW]", "![flow][]"):
            text = '<div align="center">\n\n' + use + "\n\n</div>\n\n[flow]: https://example.test/flow.png\n"
            self.assertEqual(review.review_text(text, source_images=["https://example.test/flow.png"])[1]["format"]["findings"], [])
        text = "![流程][flow]\n\n```text\n[flow]: https://example.test/flow.png\n```\n"
        self.assertTrue(any(f["rule_id"] == "FORMAT_SOURCE_IMAGE_MISSING" for f in review.review_text(text, source_images=["https://example.test/flow.png"])[1]["format"]["findings"]))

    def test_images_and_captions_must_share_one_centered_container(self):
        uncentered = "![流程](flow.png)\n\n图 1 流程"
        rules = {item["rule_id"] for item in deterministic_format_findings(uncentered)}
        self.assertIn("FORMAT_IMAGE_NOT_CENTERED", rules)
        self.assertIn("FORMAT_IMAGE_CAPTION_NOT_CENTERED", rules)

        centered = '<div align="center">\n\n![流程](flow.png)\n\n图 1 流程\n\n</div>'
        rules = {item["rule_id"] for item in deterministic_format_findings(centered)}
        self.assertNotIn("FORMAT_IMAGE_NOT_CENTERED", rules)
        self.assertNotIn("FORMAT_IMAGE_CAPTION_NOT_CENTERED", rules)

        detached = '<div align="center">\n\n![流程](flow.png)\n\n</div>\n\n图 1 流程'
        self.assertIn(
            "FORMAT_IMAGE_CAPTION_NOT_CENTERED",
            {item["rule_id"] for item in deterministic_format_findings(detached)},
        )

    def test_tables_captions_image_cells_and_overflow_are_checked(self):
        raw = "| 左图 | 右图 |\n|---|---|\n| ![左](left.png) | ![右](right.png) |\n\n表 1 对照"
        rules = {item["rule_id"] for item in deterministic_format_findings(raw)}
        self.assertIn("FORMAT_TABLE_NOT_CENTERED", rules)
        self.assertIn("FORMAT_TABLE_CAPTION_NOT_CENTERED", rules)
        self.assertIn("FORMAT_TABLE_IMAGE_CELL_NOT_CENTERED", rules)

        centered = (
            '<div align="center">\n\n<div style="max-width: 100%; overflow-x: auto;">\n\n'
            "| 左图 | 右图 |\n|:---:|:---:|\n| ![左](left.png) | ![右](right.png) |\n\n"
            "</div>\n\n表 1 对照\n\n</div>"
        )
        rules = {item["rule_id"] for item in deterministic_format_findings(centered)}
        self.assertFalse(rules & {
            "FORMAT_IMAGE_NOT_CENTERED", "FORMAT_TABLE_NOT_CENTERED",
            "FORMAT_TABLE_CAPTION_NOT_CENTERED", "FORMAT_TABLE_IMAGE_CELL_NOT_CENTERED",
            "FORMAT_WIDE_TABLE_OVERFLOW_REVIEW",
        })

        wide = '<div align="center">\n\n| 第一列 | 第二列 |\n|:---:|:---:|\n| ' + "很长" * 70 + " | 内容 |\n\n</div>"
        self.assertIn(
            "FORMAT_WIDE_TABLE_OVERFLOW_REVIEW",
            {item["rule_id"] for item in deterministic_format_findings(wide)},
        )

        html_table = (
            '<div align="center">\n\n<div style="max-width: 100%; overflow-x: auto;">\n\n'
            '<table>\n<tr><th>左图</th><th>右图</th></tr>\n'
            '<tr><td align="center"><img src="left.png" alt="左图" /></td>'
            '<td style="text-align: center"><img src="right.png" alt="右图" /></td></tr>\n</table>\n\n'
            '</div>\n\n表 2 HTML 图片对照\n\n</div>'
        )
        rules = {item["rule_id"] for item in deterministic_format_findings(html_table)}
        self.assertFalse(rules & {
            "FORMAT_IMAGE_NOT_CENTERED", "FORMAT_TABLE_NOT_CENTERED",
            "FORMAT_TABLE_CAPTION_NOT_CENTERED", "FORMAT_TABLE_IMAGE_CELL_NOT_CENTERED",
        })

        broken_html = (
            '<div align="center">\n<table><tr><td><img src="left.png" alt="左图" /></td></tr></table>\n</div>\n\n'
            '表 3 分离题注'
        )
        rules = {item["rule_id"] for item in deterministic_format_findings(broken_html)}
        self.assertIn("FORMAT_TABLE_CAPTION_NOT_CENTERED", rules)
        self.assertIn("FORMAT_TABLE_IMAGE_CELL_NOT_CENTERED", rules)

    def test_term_candidates_use_document_definitions_not_a_global_word_gate(self):
        text = (
            "先查看列表\n\n"
            "- 集合（Set）：用来判断编号是否出现；它与列表不同，不强调顺序\n"
            "- 列表（List）：按顺序保存项目；需要保留顺序时使用\n"
        )
        rules = {item["rule_id"] for item in deterministic_format_findings(text)}
        self.assertIn("FORMAT_DEFINED_TERM_EARLY_USE_REVIEW", rules)
        self.assertIn("FORMAT_NESTED_DEFINED_TERM_REVIEW", rules)
        self.assertNotIn("FORMAT_PARALLEL_ITEMS_REVIEW", rules)  # Five-part definitions stay single blocks.
        corrected = text.replace("先查看列表", "先看这批记录").replace("它与列表不同", "它与列表（List）不同")
        self.assertFalse(any(item["rule_id"].startswith(("FORMAT_DEFINED_TERM", "FORMAT_NESTED_DEFINED_TERM")) for item in deterministic_format_findings(corrected)))
        self.assertTrue(any(item["rule_id"] == "FORMAT_NESTED_DEFINED_TERM_REVIEW" for item in deterministic_format_findings(corrected.replace("它与列表（List）", "它与列表（Set）"))))
        ordinary = "列表在这里指一张纸，尚未声明任何专业概念"
        self.assertFalse(any(item["rule_id"].startswith(("FORMAT_DEFINED_TERM", "FORMAT_NESTED_DEFINED_TERM")) for item in deterministic_format_findings(ordinary)))

    def test_review_targets_do_not_read_literal_quotes_or_code_as_authored_uses(self):
        text = "> - 列表、集合\n\n```text\n- 列表、集合\n```\n\n- 集合（Set）：记录不重复编号\n- 列表（List）：按顺序保存记录\n"
        self.assertFalse(any(item["rule_id"].startswith(("FORMAT_PARALLEL_ITEMS", "FORMAT_DEFINED_TERM", "FORMAT_NESTED_DEFINED_TERM")) for item in deterministic_format_findings(text)))


class WritingDeliveryTests(unittest.TestCase):
    def test_source_image_address_correction_does_not_reject_other_local_repairs(self):
        old = "![流程](wrong.png)"
        new = "![流程](F:/fixtures/flow.png)"
        text = '<div align="center">\n\n' + old + "\n\n</div>\n\n正文。\n"
        edits = self.compact(text, old=old, new=new, node="LINE-0003", scope="sentence")
        edits["edits"].append({"node_id": "LINE-0007", "old_text": "。", "new_text": "", "scope": "token", "reason": "句末标点"})
        fixed, report = review.review_text(text, edit_transactions=[edits], source_images=["F:/fixtures/flow.png"])
        self.assertEqual(fixed, '<div align="center">\n\n' + new + "\n\n</div>\n\n正文\n")
        self.assertEqual(report["format"]["findings"], [])
        self.assertEqual(report["format"]["repair_rounds"], 1)
        with self.assertRaises(PatchError):
            review.review_text(text, edit_transactions=[edits])

    def test_source_image_local_edit_cannot_swap_sources_change_caption_or_change_other_links(self):
        first, second = "F:/fixtures/one.png", "F:/fixtures/two.png"
        for old, new in (
            (f"![图]({first})", f"![图]({second})"),
            ("![原说明](wrong.png)", f"![新说明]({first})"),
            ('![图](wrong.png "旧题注")', f'![图]({first} "新题注")'),
            ("[来源](wrong)", f"[来源]({first})"),
        ):
            with self.subTest(old=old, new=new), self.assertRaises(PatchError):
                review.review_text(old, edit_transactions=[self.compact(old, old=old, new=new, scope="sentence")], source_images=[first, second])
        text = f"> ![图]({first})"
        with self.assertRaises(PatchError):
            review.review_text(text, edit_transactions=[self.compact(text, old=f"![图]({first})", new=f"![图]({second})", scope="sentence")], source_images=[first, second])

    def test_empty_alt_can_be_filled_only_for_a_supplied_unchanged_image(self):
        old = "![](F:/fixtures/flow.png)"
        new = "![办理流程](F:/fixtures/flow.png)"
        text = '<div align="center">\n\n' + old + "\n\n</div>"
        fixed, report = review.review_text(text, edit_transactions=[self.compact(text, old=old, new=new, node="LINE-0003", scope="phrase")], source_images=["F:/fixtures/flow.png"])
        self.assertEqual(fixed, '<div align="center">\n\n' + new + "\n\n</div>")
        self.assertEqual(report["format"]["findings"], [])
        with self.assertRaises(PatchError):
            review.review_text(text, edit_transactions=[self.compact(text, old=old, new=new, node="LINE-0003", scope="phrase")], source_images=["F:/fixtures/other.png"])

    def compact(self, text, old="。", new="", node="LINE-0001", scope="token"):
        return {"document_sha256": sha256_text(text), "edits": [{
            "node_id": node, "old_text": old, "new_text": new, "scope": scope, "reason": "局部标点修复",
        }]}

    def test_compact_edits_keep_the_same_strict_committer(self):
        text = "首句。\r\n\r\n> 原文。\r\n"
        fixed, report = review.review_text(text, edit_transactions=[self.compact(text)])
        self.assertEqual(fixed, "首句\r\n\r\n> 原文。\r\n")
        self.assertEqual(report["format"]["repair_rounds"], 1)
        self.assertEqual(report["format"]["rounds"][0]["kind"], "compact")
        self.assertEqual(report["format"]["line_nodes"][-1], {"node_id": "LINE-0003", "text": "> 原文。\r\n"})
        with self.assertRaises(PatchError):
            review.review_text(text, edit_transactions=[self.compact(text, node="LINE-0003")])

    def test_compact_edits_reject_stale_ambiguous_wrong_node_and_broad_changes(self):
        text = "甲。乙。\n\n丙。"
        invalid = [
            self.compact(text), self.compact(text, old="不存在"),
            self.compact(text, node="LINE-9999"), self.compact(text, old="甲", scope="section"),
            self.compact(text, old="甲", new="甲"),
            {"document_sha256": "0" * 64, "edits": self.compact(text)["edits"]},
            {"document_sha256": sha256_text(text), "edits": []},
            {"document_sha256": sha256_text(text), "edits": [None]},
        ]
        for payload in invalid:
            with self.subTest(payload=payload), self.assertRaises(PatchError):
                review.review_text(text, edit_transactions=[payload])
        payload = self.compact(text, old="甲。", new="甲；")
        payload["edits"].append(copy.deepcopy(payload["edits"][0]))
        with self.assertRaises(PatchError):
            review.review_text(text, edit_transactions=[payload])
        fixed, _ = review.review_text(text, edit_transactions=[self.compact(text, old="甲。", new="甲；")])
        self.assertEqual(fixed, "甲；乙。\n\n丙。")

    def test_compact_transactions_share_two_round_budget(self):
        text = "甲。\n\n乙。\n\n丙。"
        first = self.compact(text)
        second = self.compact("甲\n\n乙。\n\n丙。", node="LINE-0003")
        fixed, report = review.review_text(text, edit_transactions=[first, second], fix_safe=True)
        self.assertEqual(fixed, "甲\n\n乙\n\n丙。")
        self.assertEqual(report["format"]["repair_rounds"], 2)
        with self.assertRaises(PatchError):
            review.review_text(text, edit_transactions=[first, second, second])
        with self.assertRaises(PatchError):
            review.review_text(text, transactions=[[exact_patch(text, "。", "")]], edit_transactions=[first])

    def test_explanation_copy_accepts_new_comments_then_machine_alignment(self):
        for ending in ("\n", "\r\n"):
            text = ("## 解释副本\n\n```python\nx = 1\nlong_name = 2\n```\n").replace("\n", ending)
            edits = self.compact(text, old="x = 1", new="x = 1 # 短值", node="LINE-0004", scope="sentence")
            edits["edits"].append({"node_id": "LINE-0005", "old_text": "long_name = 2", "new_text": "long_name = 2 # 长名值", "scope": "sentence", "reason": "补解释副本遗漏注释"})
            fixed, report = review.review_text(text, edit_transactions=[edits], fix_safe=True)
            self.assertIn("x = 1         # 短值", fixed)
            self.assertIn("long_name = 2 # 长名值", fixed)
            self.assertEqual(report["format"]["repair_rounds"], 2)
            self.assertEqual(report["format"]["status"], "PASS")
            self.assertEqual(review.review_text(fixed, fix_safe=True)[0], fixed)

    def test_authored_comment_text_and_header_can_change_but_code_cannot(self):
        text = "## 解释副本\n\n```python\nx = '#原始值' # 旧说明\n```\n"
        fixed, _ = review.review_text(text, edit_transactions=[self.compact(text, old="旧说明", new="新说明", node="LINE-0004", scope="phrase")])
        self.assertEqual(fixed, text.replace("旧说明", "新说明"))
        for old, new in (("x =", "y ="), ("#原始值", "#新值"), ("x =", "    x =")):
            with self.subTest(old=old), self.assertRaises(PatchError):
                review.review_text(text, edit_transactions=[self.compact(text, old=old, new=new, node="LINE-0004", scope="phrase")])
        header = "## 解释副本\n\n```python\nx = 1\n```\n"
        fixed, _ = review.review_text(header, edit_transactions=[self.compact(header, old="x = 1", new="# 建立一个值\nx = 1", node="LINE-0004", scope="sentence")])
        self.assertEqual(fixed, header.replace("x = 1", "# 建立一个值\nx = 1"))
        docstring = '## 解释副本\n\n```python\ndef f():\n    """原文 # 不是注释"""\n    return 1\n```\n'
        with self.assertRaises(PatchError):
            review.review_text(docstring, edit_transactions=[self.compact(docstring, old="原文", new="改写", node="LINE-0005", scope="phrase")])

    def test_original_and_unknown_code_do_not_gain_comment_edit_permission(self):
        for caption in ("## 原始代码", "## 未说明来源的代码"):
            text = caption + "\n\n```python\nx = 1 # 原有说明\n```\n"
            with self.subTest(caption=caption), self.assertRaises(PatchError):
                review.review_text(text, edit_transactions=[self.compact(text, old="原有说明", new="改写", node="LINE-0004", scope="phrase")])
        text = "## 原始代码\n\n```python\nx = 1\n```\n"
        payload = self.compact(text, old="原始代码", new="解释副本", scope="phrase")
        payload["edits"].append({"node_id": "LINE-0004", "old_text": "x = 1", "new_text": "x = 1 # 新说明", "scope": "sentence", "reason": "声称重新标记就可编辑"})
        with self.assertRaises(PatchError):
            review.review_text(text, edit_transactions=[payload])

    def test_literal_result_fence_can_be_corrected_without_changing_data(self):
        text = '返回结果\n\n```python\n[{"id": "R-1", "count": 2}]\n```\n'
        fixed, _ = review.review_text(text, edit_transactions=[self.compact(text, old="```python", new="```text", node="LINE-0003", scope="token")])
        self.assertEqual(fixed, text.replace("```python", "```text"))
        with self.assertRaises(PatchError):
            review.review_text(text, edit_transactions=[self.compact(text, old='"count": 2', new='"count": 3', node="LINE-0004", scope="phrase")])
        statement = text.replace('[{"id": "R-1", "count": 2}]', "write_result()")
        with self.assertRaises(PatchError):
            review.review_text(statement, edit_transactions=[self.compact(statement, old="```python", new="```text", node="LINE-0003", scope="token")])
        original = text.replace("返回结果", "## 原始代码")
        with self.assertRaises(PatchError):
            review.review_text(original, edit_transactions=[self.compact(original, old="```python", new="```text", node="LINE-0003", scope="token")])

    def test_splitting_explanation_can_repeat_and_reorder_unchanged_inline_references(self):
        text = "- `a = 1` 和 `b = 2` 中的 `=` 表示赋值\n"
        separated = "- `a = 1` 中的 `=` 表示赋值\n- `b = 2` 使用同一个 `=` 符号\n"
        fixed, _ = review.review_text(text, edit_transactions=[self.compact(text, old=text, new=separated, scope="sentence")])
        self.assertEqual(fixed, separated)
        for lost in (separated.replace("`a = 1`", "`a = 3`"), separated.replace("`b = 2`", "另一条")):
            with self.subTest(lost=lost), self.assertRaises(PatchError):
                review.review_text(text, edit_transactions=[self.compact(text, old=text, new=lost, scope="sentence")])
        twice = "`same` 对应 `same`\n"
        with self.assertRaises(PatchError):
            review.review_text(twice, edit_transactions=[self.compact(twice, old=twice, new="只留 `same`\n", scope="sentence")])

    def test_relabelling_cannot_unlock_original_in_a_later_round(self):
        text = "## 原始代码\n\n```python\nx = 1 # 原件注释\n```\n"
        for heading in ("解释副本", "新的标题"):
            first = self.compact(text, old="原始代码", new=heading, scope="phrase")
            after = text.replace("原始代码", heading)
            second = self.compact(after, old="原件注释", new="改写", node="LINE-0004", scope="phrase")
            with self.subTest(heading=heading), self.assertRaises(PatchError):
                review.review_text(text, edit_transactions=[first, second])
            with self.assertRaises(PatchError):
                review.review_text(text, edit_transactions=[first])

    def test_sql_header_comments_do_not_require_inline_comments(self):
        for language in ("sql", "postgresql", "mysql", "tsql"):
            text = f"## 解释副本\n\n```{language}\nSELECT 1;\n```\n"
            fixed, _ = review.review_text(text, edit_transactions=[self.compact(text, old="SELECT 1;", new="-- 读取一个值\nSELECT 1;", node="LINE-0004", scope="sentence")])
            changed, _ = review.review_text(fixed, edit_transactions=[self.compact(fixed, old="读取一个值", new="取回数字", node="LINE-0004", scope="phrase")])
            self.assertIn("-- 取回数字\nSELECT 1;", changed)

    def test_mysql_minus_is_never_treated_as_editable_comment(self):
        for expression in ("SELECT 1--1;", "SELECT 1--1; -- 说明", "SELECT 1--x;"):
            text = "## 解释副本\n\n```mysql\n" + expression + "\n```\n"
            self.assertEqual(deterministic_format_replacements(text), [])
            with self.subTest(expression=expression), self.assertRaises(PatchError):
                review.review_text(text, edit_transactions=[self.compact(text, old="1--", new="2--", node="LINE-0004", scope="phrase")])
            if "--1" in expression:
                with self.assertRaises(PatchError):
                    review.review_text(text, edit_transactions=[self.compact(text, old="--1", new="--2", node="LINE-0004", scope="phrase")])

    def test_code_trailing_padding_is_not_multiline_string_data(self):
        text = "## 解释副本\n\n```python\nx = 1  \n```\n"
        fixed, _ = review.review_text(text, edit_transactions=[self.compact(text, old="x = 1  ", new="x = 1  # 说明", node="LINE-0004", scope="sentence")])
        self.assertIn("x = 1  # 说明", fixed)
        literal = '## 解释副本\n\n```python\nx = """first  \ninside  \nlast"""\n```\n'
        for node, old, new in (("LINE-0004", "first  ", "first"), ("LINE-0005", "inside  ", "inside")):
            with self.subTest(node=node), self.assertRaises(PatchError):
                review.review_text(literal, edit_transactions=[self.compact(literal, old=old, new=new, node=node, scope="phrase")])

    def test_compact_cli_does_not_overwrite_inputs_or_alias_edits(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            source, output, report, edits = [directory / name for name in ("in.md", "out.md", "report.json", "edits.json")]
            source.write_text("甲。", encoding="utf-8")
            edits.write_text(json.dumps(self.compact("甲。")), encoding="utf-8")
            result = self.run_cli(directory, "--input", str(source), "--output", str(output), "--report", str(report), "--edits", str(edits))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(output.read_text(encoding="utf-8"), "甲")
            self.assertEqual(source.read_text(encoding="utf-8"), "甲。")
            result = self.run_cli(directory, "--input", str(source), "--output", str(edits), "--report", str(report), "--edits", str(edits))
            self.assertNotEqual(result.returncode, 0)

    def run_cli(self, directory: Path, *args: str):
        return subprocess.run(
            [sys.executable, "-X", "utf8", str(ROOT / "scripts/review_writing.py"), *args],
            cwd=directory, capture_output=True, text=True, encoding="utf-8",
        )

    def test_check_only_reports_issues_and_delivers_exact_text_with_zero_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            source = directory / "input.md"
            report = directory / "report.json"
            raw = "\ufeff正文。\r\n".encode("utf-8")
            source.write_bytes(raw)
            result = self.run_cli(directory, "--input", str(source), "--report", str(report))
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(set(payload), {"format", "content"})
            self.assertEqual(payload["format"]["status"], "ISSUES_REMAIN")
            self.assertFalse(payload["format"]["delivery_blocked"])
            self.assertEqual(payload["format"]["text"].encode("utf-8"), raw)
            self.assertEqual(source.read_bytes(), raw)

    def test_cli_host_nested_spacing_is_recorded_and_preserves_other_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            source, output, report = [directory / name for name in ("input.md", "out.md", "report.json")]
            source.write_text("- 父项。\n    - 子项\n", encoding="utf-8")
            result = self.run_cli(directory, "--input", str(source), "--output", str(output), "--report", str(report), "--fix-safe", "--nested-list-spacing", "host-required")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(output.read_text(encoding="utf-8"), "- 父项\n\n    - 子项\n")
            self.assertEqual(json.loads(report.read_text(encoding="utf-8"))["format"]["nested_list_spacing"], "host-required")

    def test_cli_source_image_missing_does_not_block_delivery_or_invent_image(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            source, report = [directory / name for name in ("input.md", "report.json")]
            source.write_text("仅有说明", encoding="utf-8")
            result = self.run_cli(directory, "--input", str(source), "--report", str(report), "--source-image", "https://example.test/diagram.png")
            self.assertEqual(result.returncode, 0, result.stderr)
            check = json.loads(report.read_text(encoding="utf-8"))["format"]
            self.assertEqual(check["text"], "仅有说明")
            self.assertEqual(check["source_images_checked"], ["https://example.test/diagram.png"])
            self.assertEqual(check["findings"][0]["rule_id"], "FORMAT_SOURCE_IMAGE_MISSING")
            self.assertFalse(check["delivery_blocked"])

    def test_valid_patch_and_safe_alignment_share_budget_and_preserve_input(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            text = "开头。\n\n```python\nx = 1 # 短\nlong_name = 2 # 长\n```\n\n结尾。仍需复核句中句号。"
            source, output, report, patch_file = [directory / name for name in ("input.md", "out.md", "report.json", "patch.json")]
            source.write_bytes(text.encode("utf-8"))
            patch_file.write_text(json.dumps({"patches": [exact_patch(text, "。", "")]}), encoding="utf-8")
            result = self.run_cli(directory, "--input", str(source), "--report", str(report), "--patch", str(patch_file), "--fix-safe", "--output", str(output))
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(payload["format"]["repair_rounds"], 2)
            self.assertEqual(payload["format"]["status"], "ISSUES_REMAIN")
            self.assertTrue(output.read_text(encoding="utf-8").startswith("开头\n"))
            self.assertTrue(output.read_text(encoding="utf-8").endswith("结尾。仍需复核句中句号"))
            self.assertEqual(source.read_bytes(), text.encode("utf-8"))

    def test_cli_terminal_deletion_keeps_bom_crlf_and_trailing_whitespace(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            source, output, report = [directory / name for name in ("input.md", "out.md", "report.json")]
            text = "\ufeff前句。仍需确认现场结果。  \t\r\n\r\n条件未变；\t\r\n\r\n‘原文。’\r\n"
            expected = "\ufeff前句。仍需确认现场结果  \t\r\n\r\n条件未变\t\r\n\r\n‘原文。’\r\n"
            source.write_bytes(text.encode("utf-8"))
            result = self.run_cli(directory, "--input", str(source), "--report", str(report), "--fix-safe", "--output", str(output))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(source.read_bytes(), text.encode("utf-8"))
            self.assertEqual(output.read_bytes(), expected.encode("utf-8"))
            payload = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(payload["format"]["repair_rounds"], 1)
            self.assertEqual(payload["format"]["status"], "ISSUES_REMAIN")

    def test_bad_patch_transactions_leave_input_and_existing_output_unchanged(self):
        text = "原文。\n第二行\n"
        base = exact_patch(text, "。", "")
        variants = []
        for section, field, value in (
            ("target", "document_sha256", "0" * 64),
            ("target", "node_id", "LINE-0002"),
            ("replacement", "old_text", "不存在"),
            ("replacement", "expected_occurrences", 2),
            ("authorization", "repair_scope", "section"),
            ("replacement", "new_text", "。"),
        ):
            bad = copy.deepcopy(base)
            bad[section][field] = value
            variants.append([bad])
        variants.extend(([base, copy.deepcopy(base)], [], [42]))
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            source, output, report, patch_file = [directory / name for name in ("input.md", "out.md", "report.json", "patch.json")]
            source.write_bytes(text.encode("utf-8"))
            output.write_bytes(b"previous output")
            report.write_bytes(b"previous report")
            for patches in variants:
                with self.subTest(patches=patches):
                    patch_file.write_text(json.dumps({"patches": patches}), encoding="utf-8")
                    result = self.run_cli(directory, "--input", str(source), "--report", str(report), "--patch", str(patch_file), "--output", str(output))
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(source.read_bytes(), text.encode("utf-8"))
                    self.assertEqual(output.read_bytes(), b"previous output")
                    self.assertEqual(report.read_bytes(), b"previous report")

    def test_manual_patch_cannot_change_literal_source(self):
        for text, old in (("> 原文。", "。"), ("| 原文。 |", "。"), ("$x=1$", "1"), ("[来源](https://example.test/old)", "old"), ("`raw`", "raw")):
            with self.subTest(text=text), self.assertRaises(PatchError):
                review.review_text(text, transactions=[[exact_patch(text, old, "changed")]])

    def test_two_supplied_rounds_stop_safe_repair_without_blocking_delivery(self):
        text = "甲。\n\n乙。\n\n- 一\n\n- 二"
        first = exact_patch(text, "。", "")
        intermediate = text.replace("甲。", "甲")
        second = exact_patch(intermediate, "。", "", "LINE-0003")
        with patch.object(review, "_safe_patches", side_effect=AssertionError("third repair round")):
            result, report = review.review_text(text, transactions=[[first], [second]], fix_safe=True)
        self.assertEqual(result, "甲\n\n乙\n\n- 一\n\n- 二")
        self.assertEqual(report["format"]["repair_rounds"], 2)
        self.assertEqual(report["format"]["status"], "ISSUES_REMAIN")
        self.assertFalse(report["format"]["delivery_blocked"])
        with self.assertRaises(PatchError):
            review.review_text(text, transactions=[[first], [second], [second]])

    def test_auto_repair_rechecks_and_stops_at_two_rounds(self):
        text = "首行\n正文。"
        first = exact_patch(text, "首行", "首行\n")
        intermediate = "首行\n\n正文。"
        second = exact_patch(intermediate, "正文。", "正文。\n", "LINE-0003")
        with patch.object(review, "_safe_patches", side_effect=[[first], [second]]) as safe:
            result, report = review.review_text(text, fix_safe=True)
        self.assertEqual(safe.call_count, 2)
        self.assertEqual(report["format"]["repair_rounds"], 2)
        self.assertEqual(report["format"]["status"], "ISSUES_REMAIN")
        self.assertEqual(result, "首行\n\n正文。\n")

    def test_output_must_be_explicit_and_paths_cannot_alias_input(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            source, report = directory / "input.md", directory / "report.json"
            source.write_bytes(b"original")
            base = ("--input", str(source), "--report", str(report))
            for extra in (("--fix-safe",), ("--fix-safe", "--output", str(source)), ("--output", str(report))):
                with self.subTest(extra=extra):
                    self.assertNotEqual(self.run_cli(directory, *base, *extra).returncode, 0)
                    self.assertEqual(source.read_bytes(), b"original")
            self.assertNotEqual(self.run_cli(directory, "--input", str(source), "--report", str(source)).returncode, 0)
            self.assertEqual(source.read_bytes(), b"original")

    def test_internal_error_returns_nonzero_before_any_write(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            source, output, report = [directory / name for name in ("in.md", "out.md", "report.json")]
            source.write_bytes(b"original")
            with patch.object(review, "deterministic_format_findings", side_effect=RuntimeError("test error")):
                status = review.main(["--input", str(source), "--report", str(report), "--output", str(output)])
            self.assertNotEqual(status, 0)
            self.assertFalse(output.exists())
            self.assertFalse(report.exists())


if __name__ == "__main__":
    unittest.main()
