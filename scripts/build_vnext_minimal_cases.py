"""Generate exactly 188 auditable pass/fail fixtures for vNext 1.1."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "evals" / "deterministic" / "vnext-1.1-minimal-cases.jsonl"


RULES = {
    "lifecycle_schema": [
        "LIFECYCLE_CASE_ID",
        "LIFECYCLE_GOLD_APPROVED",
        "LIFECYCLE_REJECTED_NOT_APPROVED",
        "LIFECYCLE_CANDIDATE_PENDING",
        "LIFECYCLE_REVISION_POSITIVE",
        "LIFECYCLE_GOLD_REVIEW_DATE",
        "LIFECYCLE_CANDIDATE_REVIEW_DATE",
        "LIFECYCLE_ORIGIN_ID",
        "LIFECYCLE_PRIVACY",
        "LIFECYCLE_USER_AUTHORITY",
    ],
    "terms_official_standalone": [
        "TERM_NPM",
        "TERM_CI",
        "TERM_HTTP_POST",
        "TERM_HTTP_202_TASK_ID",
        "TERM_FPGA",
        "TERM_SYNTHESIS_TIMING",
        "TERM_BITSTREAM",
        "TERM_SETUP_HOLD",
        "TERM_METASTABILITY",
        "TERM_IDEMPOTENCY_ORDER",
        "TERM_POWERSHELL",
        "TERM_STRING",
        "TERM_SHA256",
        "TERM_STANDALONE_RESET",
        "TERM_CASE_PACKAGE_MANAGER",
        "TERM_CASE_CONTINUOUS_INTEGRATION",
        "TERM_CASE_NOT_ALL_CAPS",
        "TERM_CASE_NPM_OFFICIAL",
        "TERM_CASE_OFFICIAL_MIXED",
        "TERM_CASE_NPM_NO_ACRONYM",
    ],
    "layout_lists_paragraphs": [
        "LAYOUT_COLON_NEWLINE",
        "LAYOUT_COLON_LIST",
        "LAYOUT_NESTED_INDENT",
        "LAYOUT_TOPIC_PARAGRAPH",
        "LAYOUT_SINGLE_NO_COLON",
        "LAYOUT_NO_EMPTY_LEAD",
        "LAYOUT_LIST_GROUPED",
        "LAYOUT_HEADING_LEVEL1",
        "LAYOUT_HEADING_LEVEL2",
        "LAYOUT_NO_CHINESE_PERIOD",
    ],
    "mermaid_caption_explanation": [
        "MERMAID_DEFAULT_TD",
        "MERMAID_NO_LR",
        "MERMAID_CAPTION_AFTER",
        "MERMAID_EXPLANATION_AFTER",
        "MERMAID_NODE_RELATIONS",
        "MERMAID_FLOW_RESULT",
        "MERMAID_EVIDENCE_BOUNDARY",
        "MERMAID_LR_EXCEPTION",
    ],
    "provenance_support_boundary": [
        "PROVENANCE_SOURCE_COVERAGE",
        "PROVENANCE_BACKGROUND_COVERAGE",
        "PROVENANCE_SUPPORT_KNOWN",
        "PROVENANCE_BACKGROUND_REFERENCE",
        "PROVENANCE_INFERENCE_SUPPORT",
        "PROVENANCE_INFERENCE_CONFIDENCE",
        "PROVENANCE_BOUNDARY_MISSING",
        "PROVENANCE_BOUNDARY_IMPORTANCE",
        "PROVENANCE_BOUNDARY_NEXT",
        "PROVENANCE_NO_SELF_CLAIMS",
    ],
    "image_explanation": [
        "IMAGE_ORIGINAL_FIRST",
        "IMAGE_ELEMENT_COVERAGE",
        "IMAGE_APPEARANCE",
        "IMAGE_FUNCTION",
        "IMAGE_CONNECTIONS",
        "IMAGE_PROVENANCE_LAYERS",
        "IMAGE_BOUNDARY",
        "IMAGE_NEXT_VERIFICATION",
    ],
    "table_explanation": [
        "TABLE_ORIGINAL_FIRST",
        "TABLE_CAPTION_AFTER",
        "TABLE_COLUMNS",
        "TABLE_ROWS",
        "TABLE_VALUE_DICTIONARY",
        "TABLE_CELL_LEDGER",
        "TABLE_ANOMALIES",
        "TABLE_CONCLUSION_BOUNDARY",
    ],
    "code_explanation": [
        "CODE_SOURCE_RETAINED",
        "CODE_TOOL",
        "CODE_INPUT",
        "CODE_SYNTAX",
        "CODE_EXECUTION",
        "CODE_RESULT",
        "CODE_FAILURE_SIDE_EFFECT",
        "CODE_BOUNDARY",
    ],
    "privacy_source_retention": [
        "PRIVACY_NO_SECRET",
        "PRIVACY_NO_PERSONAL_PATH",
        "PRIVACY_NO_RAW_CONVERSATION",
        "PRIVACY_SOURCE_RETAINED",
    ],
    "presentation_spacing": [
        "PRESENTATION_MAX_ONE_BLANK_LINE",
        "PRESENTATION_LIST_ITEMS_CONTIGUOUS",
        "PRESENTATION_SHORT_SOURCE_BLOCKQUOTE",
        "PRESENTATION_NO_GENERATED_BLOCKQUOTE",
        "PRESENTATION_INLINE_CODE",
        "PRESENTATION_IMAGE_CENTER",
        "PRESENTATION_TABLE_CENTER_OR_LIMITATION",
        "PRESENTATION_MERMAID_CAPTION_CENTER",
    ],
}


TERM_TEXT = {
    "TERM_NPM": "npm 是 Node.js 生态使用的包管理器（Package Manager）、命令行工具和软件包仓库；开发者使用它安装、更新和管理 JavaScript 或 TypeScript 依赖",
    "TERM_CI": "CI 持续集成（Continuous Integration）会自动运行构建和测试",
    "TERM_HTTP_POST": "`POST /tasks` 借助 HTTP 超文本传输协议（Hypertext Transfer Protocol）提交新任务",
    "TERM_HTTP_202_TASK_ID": "`202` 表示处理尚未完成；`task_id` 是查询标识",
    "TERM_FPGA": "FPGA 现场可编程门阵列（Field-Programmable Gate Array）可以通过配置改变逻辑",
    "TERM_SYNTHESIS_TIMING": "综合（Synthesis）之后执行时序分析（Timing Analysis）",
    "TERM_BITSTREAM": "位流（Bitstream）是写入 FPGA 的配置文件",
    "TERM_SETUP_HOLD": "建立时间（Setup Time）和保持时间（Hold Time）都需要满足",
    "TERM_METASTABILITY": "亚稳态（Metastability）使输出暂时不能确定为 `0` 或 `1`",
    "TERM_IDEMPOTENCY_ORDER": "幂等键（Idempotency Key）让重试返回已有 `order_id` 订单标识",
    "TERM_POWERSHELL": "PowerShell 是命令行与自动化环境",
    "TERM_STRING": "`string` 是按顺序保存字符的字符串类型",
    "TERM_SHA256": "SHA-256 安全散列算法（Secure Hash Algorithm 256-bit）用于计算摘要",
}


def lifecycle_payload(rule_id: str, passing: bool) -> dict[str, Any]:
    """Build one valid lifecycle record, then break only the target invariant."""

    status = "candidate"
    if rule_id in {"LIFECYCLE_GOLD_APPROVED", "LIFECYCLE_GOLD_REVIEW_DATE"}:
        status = "gold"
    elif rule_id == "LIFECYCLE_REJECTED_NOT_APPROVED":
        status = "rejected"
    payload = {
        "identity": {
            "case_id": "CANDIDATE-03-R2" if status == "candidate" else ("GOLD-01" if status == "gold" else "REJECTED-03"),
            "origin_case_id": "CANDIDATE-03",
            "status": status,
            "revision": 2,
            "approved_by_user": status == "gold",
            "reviewed_at": None if status == "candidate" else "2026-08-30",
        },
        "review": {
            "decision": "pending" if status == "candidate" else ("accepted" if status == "gold" else "rejected"),
            "decision_source": "explicit_user_review",
            "privacy": {"status": "public_safe"},
        },
    }
    if passing:
        return payload
    if rule_id == "LIFECYCLE_CASE_ID":
        payload["identity"]["case_id"] = "CASE-3"
    elif rule_id == "LIFECYCLE_GOLD_APPROVED":
        payload["identity"]["approved_by_user"] = False
    elif rule_id == "LIFECYCLE_REJECTED_NOT_APPROVED":
        payload["identity"]["approved_by_user"] = True
    elif rule_id == "LIFECYCLE_CANDIDATE_PENDING":
        payload["review"]["decision"] = "accepted"
    elif rule_id == "LIFECYCLE_REVISION_POSITIVE":
        payload["identity"]["revision"] = 0
    elif rule_id == "LIFECYCLE_GOLD_REVIEW_DATE":
        payload["identity"]["reviewed_at"] = None
    elif rule_id == "LIFECYCLE_CANDIDATE_REVIEW_DATE":
        payload["identity"]["reviewed_at"] = "2026-08-30"
    elif rule_id == "LIFECYCLE_ORIGIN_ID":
        payload["identity"]["origin_case_id"] = "GOLD-03"
    elif rule_id == "LIFECYCLE_PRIVACY":
        payload["review"]["privacy"]["status"] = "contains_private_data"
    elif rule_id == "LIFECYCLE_USER_AUTHORITY":
        payload["review"]["decision_source"] = "model_score"
    return payload


def term_payload(rule_id: str, passing: bool) -> dict[str, Any]:
    """Build official-form or standalone-context fixtures."""

    if rule_id == "TERM_STANDALONE_RESET":
        return {"reading_context": "standalone", "known_terms": [] if passing else ["HTTP"]}
    contextual = {
        "TERM_CASE_PACKAGE_MANAGER": (
            {"context": "authored_prose", "text": "npm 包管理器（Package Manager）用于管理项目依赖"},
            {"context": "authored_prose", "text": "npm 包管理器（package manager）用于管理项目依赖"},
        ),
        "TERM_CASE_CONTINUOUS_INTEGRATION": (
            {"context": "authored_prose", "text": "CI 持续集成（Continuous Integration）会自动运行测试"},
            {"context": "authored_prose", "text": "CI 持续集成（continuous integration）会自动运行测试"},
        ),
        "TERM_CASE_NOT_ALL_CAPS": (
            {"context": "authored_prose", "text": "Node.js 使用 npm 管理项目依赖"},
            {"context": "authored_prose", "text": "npm 包管理器（PACKAGE MANAGER）用于管理项目依赖"},
        ),
        "TERM_CASE_NPM_OFFICIAL": (
            {"context": "authored_prose", "text": "npm 调用项目脚本"},
            {"context": "authored_prose", "text": "NPM 调用项目脚本"},
        ),
        "TERM_CASE_OFFICIAL_MIXED": (
            {"context": "authored_prose", "text": "Node.js 服务向 iOS 客户端返回结果"},
            {"context": "authored_prose", "text": "node.js 服务向 IOS 客户端返回结果"},
        ),
        "TERM_CASE_NPM_NO_ACRONYM": (
            {"context": "verbatim", "text": "> NPM"},
            {"context": "authored_prose", "text": "npm Node Package Manager 用于管理依赖"},
        ),
    }
    if rule_id in contextual:
        return contextual[rule_id][0 if passing else 1]
    return {"text": TERM_TEXT[rule_id] if passing else "术语已经出现，但没有提供登记形式和用途"}


def layout_payload(rule_id: str, passing: bool) -> dict[str, Any]:
    """Build list and paragraph fixtures with one target distinction."""

    good = {
        "LAYOUT_COLON_NEWLINE": "需要检查：\n\n- 链接\n- 图片",
        "LAYOUT_COLON_LIST": "包括：\n\n- 链接\n- 图片",
        "LAYOUT_NESTED_INDENT": "- 构建\n  - Windows\n  - Linux",
        "LAYOUT_TOPIC_PARAGRAPH": "软件检查已经通过\n\n硬件测试尚未开始",
        "LAYOUT_SINGLE_NO_COLON": "唯一说明是保留原始代码",
        "LAYOUT_NO_EMPTY_LEAD": "研究人员加入了两级同步器",
        "LAYOUT_LIST_GROUPED": "### 软件\n\n- 构建\n- 测试\n\n### 硬件\n\n- 上电\n- 接口",
        "LAYOUT_HEADING_LEVEL1": "# 1. 简介",
        "LAYOUT_HEADING_LEVEL2": "## 1.1. 范围",
        "LAYOUT_NO_CHINESE_PERIOD": "检查已经通过；下一步核对板卡",
    }
    bad = {
        "LAYOUT_COLON_NEWLINE": "需要检查：链接、图片",
        "LAYOUT_COLON_LIST": "包括：链接、图片",
        "LAYOUT_NESTED_INDENT": "- 构建\n- Windows\n- Linux",
        "LAYOUT_TOPIC_PARAGRAPH": "软件检查已经通过；硬件测试尚未开始",
        "LAYOUT_SINGLE_NO_COLON": "唯一说明：保留原始代码",
        "LAYOUT_NO_EMPTY_LEAD": "原文完整翻译如下\n\n研究人员加入了两级同步器",
        "LAYOUT_LIST_GROUPED": "- 构建\n- 测试\n- Windows\n- Linux",
        "LAYOUT_HEADING_LEVEL1": "# 1 简介",
        "LAYOUT_HEADING_LEVEL2": "## 1.1 范围",
        "LAYOUT_NO_CHINESE_PERIOD": "检查已经通过。",
    }
    return {"text": good[rule_id] if passing else bad[rule_id]}


def mermaid_payload(rule_id: str, passing: bool) -> dict[str, Any]:
    """Build diagram fixtures with visible post-diagram evidence."""

    direction = "TD"
    reason = ""
    if rule_id == "MERMAID_LR_EXCEPTION":
        direction = "LR"
        reason = "横向时间轴需要与原图方向一致" if passing else ""
    text = (
        f"```mermaid\nflowchart {direction}\n    A[输入] --> B[检查]\n    B --> C[结果]\n```\n\n"
        "图 1. 检查流程\n\n"
        "节点关系说明输入先进入检查，再进入结果；流程结果是得到检查状态；"
        "当前缺少真实运行日志，这会影响对实际成功的判断，下一步运行并保存日志"
    )
    if not passing:
        replacements = {
            "MERMAID_DEFAULT_TD": ("flowchart TD", "flowchart LR"),
            "MERMAID_NO_LR": ("flowchart TD", "flowchart LR"),
            "MERMAID_CAPTION_AFTER": ("图 1. 检查流程", "检查流程"),
            "MERMAID_EXPLANATION_AFTER": ("节点关系", "流程"),
            "MERMAID_NODE_RELATIONS": ("输入先进入检查，再进入结果", "输入连接检查和结果"),
            "MERMAID_FLOW_RESULT": ("流程结果", "得到"),
            "MERMAID_EVIDENCE_BOUNDARY": ("下一步运行并保存日志", "等待后续处理"),
        }
        if rule_id in replacements:
            text = text.replace(*replacements[rule_id])
    return {"text": text, "layout_exception_reason": reason}


def provenance_payload(rule_id: str, passing: bool) -> dict[str, Any]:
    """Build provenance graphs and remove one required edge for negative fixtures."""

    payload = {
        "source_atoms": ["ATOM-001", "ATOM-002"],
        "background_atoms": ["BG-001"],
        "inference_atoms": ["INF-001"],
        "support_ids": ["ATOM-001", "ATOM-002", "BG-001"],
        "reference_ids": ["REF-001"],
        "background_references": ["REF-001"],
        "inference_support": ["ATOM-001", "BG-001"],
        "inference_confidence": "high",
        "boundary": {
            "missing_evidence": "缺少板卡测试",
            "why_important": "无法判断真实硬件行为",
            "next_verification": "执行板卡测试",
        },
        "self_claims": [],
    }
    if passing:
        return payload
    if rule_id == "PROVENANCE_SOURCE_COVERAGE":
        payload["support_ids"].remove("ATOM-002")
    elif rule_id == "PROVENANCE_BACKGROUND_COVERAGE":
        payload["support_ids"].remove("BG-001")
    elif rule_id == "PROVENANCE_SUPPORT_KNOWN":
        payload["support_ids"].append("ATOM-999")
    elif rule_id == "PROVENANCE_BACKGROUND_REFERENCE":
        payload["background_references"] = ["REF-999"]
    elif rule_id == "PROVENANCE_INFERENCE_SUPPORT":
        payload["inference_support"] = ["ATOM-999"]
    elif rule_id == "PROVENANCE_INFERENCE_CONFIDENCE":
        payload["inference_confidence"] = "certain"
    elif rule_id == "PROVENANCE_BOUNDARY_MISSING":
        payload["boundary"]["missing_evidence"] = ""
    elif rule_id == "PROVENANCE_BOUNDARY_IMPORTANCE":
        payload["boundary"]["why_important"] = ""
    elif rule_id == "PROVENANCE_BOUNDARY_NEXT":
        payload["boundary"]["next_verification"] = ""
    elif rule_id == "PROVENANCE_NO_SELF_CLAIMS":
        payload["self_claims"] = ["没有来源的新事实"]
    return payload


def image_payload(rule_id: str, passing: bool) -> dict[str, Any]:
    """Build image ledgers and omit one required coverage field when failing."""

    elements = ["control", "FF1", "FF2", "arrow"]
    payload = {
        "component_order": ["source_image", "explanation"],
        "effective_elements": elements,
        "covered_elements": elements.copy(),
        "appearance_elements": elements.copy(),
        "function_elements": elements.copy(),
        "connections": ["control -> FF1 -> FF2"],
        "provenance_layers": ["visible_fact", "background", "inference", "unknown"],
        "boundary": {
            "missing_evidence": "缺少波形与板卡结果",
            "why_important": "无法确认实际行为",
            "next_verification": "检查报告并运行板卡测试",
        },
    }
    if passing:
        return payload
    if rule_id == "IMAGE_ORIGINAL_FIRST":
        payload["component_order"] = ["explanation", "source_image"]
    elif rule_id == "IMAGE_ELEMENT_COVERAGE":
        payload["covered_elements"].remove("arrow")
    elif rule_id == "IMAGE_APPEARANCE":
        payload["appearance_elements"].remove("FF2")
    elif rule_id == "IMAGE_FUNCTION":
        payload["function_elements"].remove("FF1")
    elif rule_id == "IMAGE_CONNECTIONS":
        payload["connections"] = []
    elif rule_id == "IMAGE_PROVENANCE_LAYERS":
        payload["provenance_layers"].remove("unknown")
    elif rule_id == "IMAGE_BOUNDARY":
        payload["boundary"]["why_important"] = ""
    elif rule_id == "IMAGE_NEXT_VERIFICATION":
        payload["boundary"]["next_verification"] = ""
    return payload


def table_payload(rule_id: str, passing: bool) -> dict[str, Any]:
    """Build table ledgers with value definitions instead of repetitive prose."""

    payload = {
        "component_order": ["source_table", "explanation"],
        "caption_position": "below",
        "columns": ["版本", "软件检查", "板卡测试"],
        "explained_columns": ["版本", "软件检查", "板卡测试"],
        "rows": ["A", "B"],
        "explained_rows": ["A", "B"],
        "values": ["通过", "未运行"],
        "defined_values": ["通过", "未运行"],
        "cells": ["A1", "A2", "B1", "B2"],
        "covered_cells": ["A1", "A2", "B1", "B2"],
        "anomalies": ["A2"],
        "explained_anomalies": ["A2"],
        "conclusion": {
            "basis": "软件和板卡都通过",
            "impact": "决定发布条件",
            "missing_evidence": "缺少性能数据",
            "next_verification": "核对表外要求",
        },
    }
    if passing:
        return payload
    mutations = {
        "TABLE_ORIGINAL_FIRST": ("component_order", ["explanation", "source_table"]),
        "TABLE_CAPTION_AFTER": ("caption_position", "above"),
        "TABLE_COLUMNS": ("explained_columns", ["版本", "软件检查"]),
        "TABLE_ROWS": ("explained_rows", ["A"]),
        "TABLE_VALUE_DICTIONARY": ("defined_values", ["通过"]),
        "TABLE_CELL_LEDGER": ("covered_cells", ["A1", "A2", "B1"]),
        "TABLE_ANOMALIES": ("explained_anomalies", []),
    }
    if rule_id in mutations:
        key, value = mutations[rule_id]
        payload[key] = value
    elif rule_id == "TABLE_CONCLUSION_BOUNDARY":
        payload["conclusion"]["next_verification"] = ""
    return payload


def code_payload(rule_id: str, passing: bool) -> dict[str, Any]:
    """Build code explanation ledgers and remove one required field when failing."""

    code = "param([string]$Path)\nGet-FileHash -Algorithm SHA256 -LiteralPath $Path"
    payload = {
        "source_code": code,
        "rendered_code": code,
        "tool_explanation": "PowerShell 命令行与自动化环境",
        "input_explanation": "Path 是字符串类型的文件路径",
        "syntax_explanation": "LiteralPath 按原样解释路径",
        "execution_method": ".\\script.ps1 -Path .\\file.bin",
        "observable_result": "显示算法、摘要和路径",
        "failure": "路径无效时返回退出码 2",
        "side_effects": "只读取文件，不写入文件",
        "boundary": {
            "cause": "摘要只比较内容",
            "missing_evidence": "缺少来源签名",
            "verification_method": "核对数字签名",
        },
    }
    if passing:
        return payload
    if rule_id == "CODE_SOURCE_RETAINED":
        payload["rendered_code"] = "Get-FileHash $Path"
    elif rule_id == "CODE_TOOL":
        payload["tool_explanation"] = ""
    elif rule_id == "CODE_INPUT":
        payload["input_explanation"] = ""
    elif rule_id == "CODE_SYNTAX":
        payload["syntax_explanation"] = ""
    elif rule_id == "CODE_EXECUTION":
        payload["execution_method"] = ""
    elif rule_id == "CODE_RESULT":
        payload["observable_result"] = ""
    elif rule_id == "CODE_FAILURE_SIDE_EFFECT":
        payload["side_effects"] = ""
    elif rule_id == "CODE_BOUNDARY":
        payload["boundary"]["verification_method"] = ""
    return payload


def privacy_payload(rule_id: str, passing: bool) -> dict[str, Any]:
    """Build public-safe fixtures and insert one prohibited value when failing."""

    payload = {
        "text": "公开技术案例只包含合成标识和仓库相对路径",
        "text_chunks": [],
        "source_component": "Get-FileHash -Algorithm SHA256",
        "rendered_component": "Get-FileHash -Algorithm SHA256",
    }
    if passing:
        return payload
    if rule_id == "PRIVACY_NO_SECRET":
        payload["text"] = "token="
        payload["text_chunks"] = ["ghp_", "A" * 24]
    elif rule_id == "PRIVACY_NO_PERSONAL_PATH":
        payload["text"] = "C:\\Users\\private-user\\secret.txt"
    elif rule_id == "PRIVACY_NO_RAW_CONVERSATION":
        payload["text"] = "<conversation>raw private turn</conversation>"
    elif rule_id == "PRIVACY_SOURCE_RETAINED":
        payload["rendered_component"] = "Get-FileHash"
    return payload


def presentation_payload(rule_id: str, passing: bool) -> dict[str, Any]:
    """Build deterministic spacing, source-format, inline-code, and alignment fixtures."""

    payload = {
        "text": "第一段\n\n第二段",
        "source_kind": "short_verbatim",
        "source_format": "blockquote",
        "content_role": "source_evidence",
        "inline_tokens": ["task_id"],
        "object_type": "image",
        "renderer_exact_alignment": True,
        "object_alignment": "center",
        "caption_alignment": "center",
        "renderer_limitation": "",
    }
    if rule_id == "PRESENTATION_LIST_ITEMS_CONTIGUOUS":
        payload["text"] = "- 第一项\n- 第二项" if passing else "- 第一项\n\n- 第二项"
    elif rule_id == "PRESENTATION_INLINE_CODE":
        payload["text"] = "使用 `task_id` 查询状态" if passing else "使用 task_id 查询状态"
    elif rule_id == "PRESENTATION_TABLE_CENTER_OR_LIMITATION":
        payload.update({"object_type": "table", "renderer_exact_alignment": False, "object_alignment": "renderer_default", "caption_alignment": "center", "renderer_limitation": "GitHub 原生 Markdown 表格不能可靠控制对象居中"})
    elif rule_id == "PRESENTATION_MERMAID_CAPTION_CENTER":
        payload.update({"object_type": "mermaid", "renderer_exact_alignment": False, "object_alignment": "renderer_default", "caption_alignment": "center", "renderer_limitation": "Mermaid 对象位置由渲染器决定"})
    if passing:
        return payload
    if rule_id == "PRESENTATION_MAX_ONE_BLANK_LINE":
        payload["text"] = "第一段\n\n\n第二段"
    elif rule_id == "PRESENTATION_SHORT_SOURCE_BLOCKQUOTE":
        payload["source_format"] = "plain_paragraph"
    elif rule_id == "PRESENTATION_NO_GENERATED_BLOCKQUOTE":
        payload.update({"content_role": "generated_summary", "source_format": "blockquote"})
    elif rule_id == "PRESENTATION_IMAGE_CENTER":
        payload["object_alignment"] = "renderer_default"
    elif rule_id == "PRESENTATION_TABLE_CENTER_OR_LIMITATION":
        payload["renderer_limitation"] = ""
    elif rule_id == "PRESENTATION_MERMAID_CAPTION_CENTER":
        payload["caption_alignment"] = "renderer_default"
    return payload


BUILDERS = {
    "lifecycle_schema": lifecycle_payload,
    "terms_official_standalone": term_payload,
    "layout_lists_paragraphs": layout_payload,
    "mermaid_caption_explanation": mermaid_payload,
    "provenance_support_boundary": provenance_payload,
    "image_explanation": image_payload,
    "table_explanation": table_payload,
    "code_explanation": code_payload,
    "privacy_source_retention": privacy_payload,
    "presentation_spacing": presentation_payload,
}


def build_cases() -> list[dict[str, Any]]:
    """Build one passing and one failing fixture for every registered rule."""

    cases: list[dict[str, Any]] = []
    ordinal = 1
    for category, rule_ids in RULES.items():
        builder = BUILDERS[category]
        for rule_id in rule_ids:
            for passing in (True, False):
                cases.append(
                    {
                        "case_id": f"VNEXT-MIN-{ordinal:03d}",
                        "category": category,
                        "rule_id": rule_id,
                        "expected": "PASS" if passing else "FAIL",
                        "payload": builder(rule_id, passing),
                    }
                )
                ordinal += 1
    return cases


def main() -> int:
    """Write the stable JSONL fixture collection."""

    cases = build_cases()
    if len(cases) != 188:
        raise SystemExit(f"expected 188 cases, built {len(cases)}")
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(
        "".join(json.dumps(case, ensure_ascii=False, sort_keys=True) + "\n" for case in cases),
        encoding="utf-8",
    )
    print(json.dumps({"status": "PASS", "cases": len(cases)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
