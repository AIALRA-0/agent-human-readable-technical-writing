"""Deterministic validators for the 176 auditable vNext minimal fixtures.

Each rule checks an observable structure or exact registered form.  The module
does not score naturalness or claim semantic equivalence.
"""

from __future__ import annotations

import re
from typing import Any, Callable


ValidationResult = list[str]


TERM_REQUIREMENTS = {
    "TERM_NPM": ["npm 包管理器", "JavaScript", "TypeScript"],
    "TERM_CI": ["CI 持续集成（Continuous Integration）", "自动", "测试"],
    "TERM_HTTP_POST": ["HTTP 超文本传输协议（Hypertext Transfer Protocol）", "`POST /tasks`", "新任务"],
    "TERM_HTTP_202_TASK_ID": ["`202`", "尚未完成", "`task_id`", "查询标识"],
    "TERM_FPGA": ["FPGA 现场可编程门阵列（Field-Programmable Gate Array）", "配置"],
    "TERM_SYNTHESIS_TIMING": ["综合（Synthesis）", "时序分析（Timing Analysis）"],
    "TERM_BITSTREAM": ["位流（Bitstream）", "写入 FPGA"],
    "TERM_SETUP_HOLD": ["建立时间（Setup Time）", "保持时间（Hold Time）"],
    "TERM_METASTABILITY": ["亚稳态（Metastability）", "`0`", "`1`"],
    "TERM_IDEMPOTENCY_ORDER": ["幂等键（Idempotency Key）", "`order_id`", "订单标识"],
    "TERM_POWERSHELL": ["PowerShell", "命令行", "自动化"],
    "TERM_STRING": ["`string`", "按顺序", "字符", "字符串类型"],
    "TERM_SHA256": ["SHA-256 安全散列算法（Secure Hash Algorithm 256-bit）", "摘要"],
}


def _missing_text(text: str, required: list[str]) -> ValidationResult:
    """Return every required registered fragment missing from text."""

    return [f"missing text: {item}" for item in required if item not in text]


def validate_lifecycle(rule_id: str, payload: dict[str, Any]) -> ValidationResult:
    """Validate one independent lifecycle invariant."""

    identity = payload.get("identity", {})
    review = payload.get("review", {})
    checks: dict[str, bool] = {
        "LIFECYCLE_CASE_ID": bool(
            re.fullmatch(r"GOLD-\d{2}|REJECTED-\d{2}(?:-R\d+)?|CANDIDATE-\d{2}-R\d+", str(identity.get("case_id", "")))
        ),
        "LIFECYCLE_GOLD_APPROVED": identity.get("status") != "gold" or identity.get("approved_by_user") is True,
        "LIFECYCLE_REJECTED_NOT_APPROVED": identity.get("status") != "rejected" or identity.get("approved_by_user") is False,
        "LIFECYCLE_CANDIDATE_PENDING": identity.get("status") != "candidate" or review.get("decision") == "pending",
        "LIFECYCLE_REVISION_POSITIVE": isinstance(identity.get("revision"), int) and not isinstance(identity.get("revision"), bool) and identity["revision"] > 0,
        "LIFECYCLE_GOLD_REVIEW_DATE": identity.get("status") != "gold" or isinstance(identity.get("reviewed_at"), str),
        "LIFECYCLE_CANDIDATE_REVIEW_DATE": identity.get("status") != "candidate" or identity.get("reviewed_at") is None,
        "LIFECYCLE_ORIGIN_ID": bool(re.fullmatch(r"CANDIDATE-\d{2}", str(identity.get("origin_case_id", "")))),
        "LIFECYCLE_PRIVACY": review.get("privacy", {}).get("status") == "public_safe",
        "LIFECYCLE_USER_AUTHORITY": review.get("decision_source") == "explicit_user_review",
    }
    return [] if checks.get(rule_id, False) else [f"{rule_id} failed"]


def validate_term(rule_id: str, payload: dict[str, Any]) -> ValidationResult:
    """Validate registered first-use forms or isolated-context reset."""

    if rule_id == "TERM_STANDALONE_RESET":
        return [] if payload.get("reading_context") != "standalone" or payload.get("known_terms") == [] else ["standalone known_terms must be empty"]
    return _missing_text(str(payload.get("text", "")), TERM_REQUIREMENTS[rule_id])


def validate_layout(rule_id: str, payload: dict[str, Any]) -> ValidationResult:
    """Validate deterministic paragraph, list, punctuation, and numbering forms."""

    text = str(payload.get("text", ""))
    checks = {
        "LAYOUT_COLON_NEWLINE": bool(re.search(r"：\n\n?- ", text)),
        "LAYOUT_COLON_LIST": text.count("\n- ") >= 2,
        "LAYOUT_NESTED_INDENT": bool(re.search(r"\n  - ", text)),
        "LAYOUT_TOPIC_PARAGRAPH": "\n\n" in text,
        "LAYOUT_SINGLE_NO_COLON": "唯一说明：" not in text,
        "LAYOUT_NO_EMPTY_LEAD": "原文完整翻译如下" not in text,
        "LAYOUT_LIST_GROUPED": text.count("### ") >= 2 and text.count("\n- ") >= 4,
        "LAYOUT_HEADING_LEVEL1": bool(re.search(r"^# 1\. \S", text, re.MULTILINE)),
        "LAYOUT_HEADING_LEVEL2": bool(re.search(r"^## 1\.1\. \S", text, re.MULTILINE)),
        "LAYOUT_NO_CHINESE_PERIOD": "。" not in text,
    }
    return [] if checks.get(rule_id, False) else [f"{rule_id} failed"]


def _diagram_bounds(text: str) -> tuple[int, int]:
    """Return Mermaid block bounds, or -1 values when the block is absent."""

    start = text.find("```mermaid")
    if start < 0:
        return -1, -1
    end = text.find("```", start + len("```mermaid"))
    return start, end


def validate_mermaid(rule_id: str, payload: dict[str, Any]) -> ValidationResult:
    """Validate default direction, caption order, and required post-diagram explanation."""

    text = str(payload.get("text", ""))
    start, end = _diagram_bounds(text)
    after = text[end + 3 :] if end >= 0 else ""
    checks = {
        "MERMAID_DEFAULT_TD": "flowchart TD" in text,
        "MERMAID_NO_LR": "flowchart LR" not in text,
        "MERMAID_CAPTION_AFTER": end >= 0 and re.search(r"图 \d+\. ", after) is not None,
        "MERMAID_EXPLANATION_AFTER": end >= 0 and "节点关系" in after,
        "MERMAID_NODE_RELATIONS": "先进入" in after and "再进入" in after,
        "MERMAID_FLOW_RESULT": "流程结果" in after,
        "MERMAID_EVIDENCE_BOUNDARY": all(item in after for item in ("缺少", "影响", "下一步")),
        "MERMAID_LR_EXCEPTION": "flowchart LR" not in text or bool(payload.get("layout_exception_reason")),
    }
    return [] if checks.get(rule_id, False) else [f"{rule_id} failed"]


def validate_provenance(rule_id: str, payload: dict[str, Any]) -> ValidationResult:
    """Validate source/background/support and evidence-boundary bookkeeping."""

    source_ids = set(payload.get("source_atoms", []))
    background_ids = set(payload.get("background_atoms", []))
    support_ids = set(payload.get("support_ids", []))
    known_ids = source_ids | background_ids | set(payload.get("inference_atoms", []))
    reference_ids = set(payload.get("reference_ids", []))
    background_references = set(payload.get("background_references", []))
    inference_support = set(payload.get("inference_support", []))
    boundary = payload.get("boundary", {})
    checks = {
        "PROVENANCE_SOURCE_COVERAGE": source_ids <= support_ids,
        "PROVENANCE_BACKGROUND_COVERAGE": background_ids <= support_ids,
        "PROVENANCE_SUPPORT_KNOWN": support_ids <= known_ids,
        "PROVENANCE_BACKGROUND_REFERENCE": background_references <= reference_ids,
        "PROVENANCE_INFERENCE_SUPPORT": bool(inference_support) and inference_support <= source_ids | background_ids,
        "PROVENANCE_INFERENCE_CONFIDENCE": payload.get("inference_confidence") in {"low", "medium", "high"},
        "PROVENANCE_BOUNDARY_MISSING": bool(boundary.get("missing_evidence")),
        "PROVENANCE_BOUNDARY_IMPORTANCE": bool(boundary.get("why_important")),
        "PROVENANCE_BOUNDARY_NEXT": bool(boundary.get("next_verification")),
        "PROVENANCE_NO_SELF_CLAIMS": payload.get("self_claims") == [],
    }
    return [] if checks.get(rule_id, False) else [f"{rule_id} failed"]


def validate_image(rule_id: str, payload: dict[str, Any]) -> ValidationResult:
    """Validate the image coverage ledger and explanation ordering."""

    elements = set(payload.get("effective_elements", []))
    checks = {
        "IMAGE_ORIGINAL_FIRST": payload.get("component_order", [])[:2] == ["source_image", "explanation"],
        "IMAGE_ELEMENT_COVERAGE": elements <= set(payload.get("covered_elements", [])),
        "IMAGE_APPEARANCE": elements <= set(payload.get("appearance_elements", [])),
        "IMAGE_FUNCTION": elements <= set(payload.get("function_elements", [])),
        "IMAGE_CONNECTIONS": bool(payload.get("connections")),
        "IMAGE_PROVENANCE_LAYERS": set(payload.get("provenance_layers", [])) >= {"visible_fact", "background", "inference", "unknown"},
        "IMAGE_BOUNDARY": bool(payload.get("boundary", {}).get("missing_evidence")) and bool(payload.get("boundary", {}).get("why_important")),
        "IMAGE_NEXT_VERIFICATION": bool(payload.get("boundary", {}).get("next_verification")),
    }
    return [] if checks.get(rule_id, False) else [f"{rule_id} failed"]


def validate_table(rule_id: str, payload: dict[str, Any]) -> ValidationResult:
    """Validate table interpretation without requiring mechanical cell narration."""

    checks = {
        "TABLE_ORIGINAL_FIRST": payload.get("component_order", [])[:2] == ["source_table", "explanation"],
        "TABLE_CAPTION_AFTER": payload.get("caption_position") == "below",
        "TABLE_COLUMNS": set(payload.get("columns", [])) <= set(payload.get("explained_columns", [])),
        "TABLE_ROWS": set(payload.get("rows", [])) <= set(payload.get("explained_rows", [])),
        "TABLE_VALUE_DICTIONARY": set(payload.get("values", [])) <= set(payload.get("defined_values", [])),
        "TABLE_CELL_LEDGER": set(payload.get("cells", [])) <= set(payload.get("covered_cells", [])),
        "TABLE_ANOMALIES": set(payload.get("anomalies", [])) <= set(payload.get("explained_anomalies", [])),
        "TABLE_CONCLUSION_BOUNDARY": all(payload.get("conclusion", {}).get(key) for key in ("basis", "impact", "missing_evidence", "next_verification")),
    }
    return [] if checks.get(rule_id, False) else [f"{rule_id} failed"]


def validate_code(rule_id: str, payload: dict[str, Any]) -> ValidationResult:
    """Validate source-code retention and zero-prior-knowledge explanation coverage."""

    checks = {
        "CODE_SOURCE_RETAINED": payload.get("source_code") == payload.get("rendered_code"),
        "CODE_TOOL": bool(payload.get("tool_explanation")),
        "CODE_INPUT": bool(payload.get("input_explanation")),
        "CODE_SYNTAX": bool(payload.get("syntax_explanation")),
        "CODE_EXECUTION": bool(payload.get("execution_method")),
        "CODE_RESULT": bool(payload.get("observable_result")),
        "CODE_FAILURE_SIDE_EFFECT": bool(payload.get("failure")) and bool(payload.get("side_effects")),
        "CODE_BOUNDARY": all(payload.get("boundary", {}).get(key) for key in ("cause", "missing_evidence", "verification_method")),
    }
    return [] if checks.get(rule_id, False) else [f"{rule_id} failed"]


def validate_privacy(rule_id: str, payload: dict[str, Any]) -> ValidationResult:
    """Validate public-safe fixture content and original component retention."""

    text = str(payload.get("text", "")) + "".join(payload.get("text_chunks", []))
    checks = {
        "PRIVACY_NO_SECRET": re.search(r"(?:ghp_|github_pat_|AKIA)[A-Za-z0-9_]+", text) is None,
        "PRIVACY_NO_PERSONAL_PATH": re.search(r"[A-Za-z]:\\Users\\[^\\]+", text) is None,
        "PRIVACY_NO_RAW_CONVERSATION": "<conversation>" not in text and "account_email=" not in text,
        "PRIVACY_SOURCE_RETAINED": payload.get("source_component") == payload.get("rendered_component"),
    }
    return [] if checks.get(rule_id, False) else [f"{rule_id} failed"]


def validate_presentation(rule_id: str, payload: dict[str, Any]) -> ValidationResult:
    """Validate only observable Markdown spacing, source formats, and alignment records."""

    text = str(payload.get("text", ""))
    tokens = payload.get("inline_tokens", [])
    exact = payload.get("renderer_exact_alignment") is True
    checks = {
        "PRESENTATION_MAX_ONE_BLANK_LINE": re.search(r"\n[ \t]*\n[ \t]*\n", text) is None,
        "PRESENTATION_LIST_ITEMS_CONTIGUOUS": re.search(r"^- .+\n\n- ", text, re.MULTILINE) is None,
        "PRESENTATION_SHORT_SOURCE_BLOCKQUOTE": payload.get("source_kind") != "short_verbatim" or payload.get("source_format") == "blockquote",
        "PRESENTATION_NO_GENERATED_BLOCKQUOTE": payload.get("content_role") == "source_evidence" or payload.get("source_format") != "blockquote",
        "PRESENTATION_INLINE_CODE": all(f"`{token}`" in text for token in tokens),
        "PRESENTATION_IMAGE_CENTER": payload.get("object_type") != "image" or not exact or payload.get("object_alignment") == "center",
        "PRESENTATION_TABLE_CENTER_OR_LIMITATION": payload.get("object_type") != "table" or payload.get("object_alignment") == "center" or bool(payload.get("renderer_limitation")),
        "PRESENTATION_MERMAID_CAPTION_CENTER": payload.get("object_type") != "mermaid" or payload.get("caption_alignment") == "center",
    }
    return [] if checks.get(rule_id, False) else [f"{rule_id} failed"]


VALIDATORS: dict[str, Callable[[str, dict[str, Any]], ValidationResult]] = {
    "lifecycle_schema": validate_lifecycle,
    "terms_official_standalone": validate_term,
    "layout_lists_paragraphs": validate_layout,
    "mermaid_caption_explanation": validate_mermaid,
    "provenance_support_boundary": validate_provenance,
    "image_explanation": validate_image,
    "table_explanation": validate_table,
    "code_explanation": validate_code,
    "privacy_source_retention": validate_privacy,
    "presentation_spacing": validate_presentation,
}


def validate_fixture(category: str, rule_id: str, payload: dict[str, Any]) -> ValidationResult:
    """Run the category-owned deterministic validator for one fixture."""

    try:
        validator = VALIDATORS[category]
    except KeyError as error:
        raise ValueError(f"unknown fixture category: {category}") from error
    return validator(rule_id, payload)
