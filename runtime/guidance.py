"""Small, mode-aware helpers for the writing guidance layer.

The skill has two deliberately different jobs:

* protect source meaning and explicit task contracts
* suggest a readable presentation without turning taste into a universal gate

This module keeps that distinction in one place so the compiler, verifier and
self-review path do not each invent a different interpretation of "light".
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


GUIDANCE_MODES = ("light", "strict")
DEPTHS = ("minimal", "guided", "expanded")
EXPAND_TRIGGERS = (
    "long_input",
    "high_risk",
    "material_ambiguity",
    "user_request",
    "multi_step",
)

# These rules describe presentation preference rather than preservation of
# source meaning.  They may still become blocking when the task explicitly
# asks for a format contract, or when a component-specific contract says so.
STYLE_RULES = frozenset(
    {
        "LUCAS_PUNCTUATION",
        "LUCAS_NO_CHINESE_FULL_STOP",
        "LUCAS_NO_TRAILING_SEMICOLON",
        "COLON_PSEUDO_HEADING",
        "SECTION_PLAN_MISSING",
        "SECTION_PLAN_UNNECESSARY",
        "SECTION_LEVEL_MISMATCH",
        "COMPONENT_ALIGNMENT",
        "CAPTION_ALIGNMENT",
        "ALIGNMENT_LIMITATION",
        "GITHUB_RENDER_EVIDENCE",
        "MERMAID_VERTICAL_DEFAULT",
        "EXCESSIVE_BLANK_LINES",
        "MISSING_BLOCK_SEPARATOR",
        "LIST_INTERNAL_BLANK_LINE",
        "NESTED_LIST_AMBIGUOUS_CONTINUATION",
        "COMMA_SEMICOLON_CHOICE",
        "ORDINARY_SENTENCE_RHYTHM",
        "LOCAL_NOTATION_CONSISTENCY",
        "PARENTHETICAL_ENGLISH_CASE",
        "CODE_COMMENT_ALIGNMENT_MODE",
        "CODE_COMMENT_ALIGNMENT_TARGET",
        "CODE_COMMENT_ALIGNMENT_UNITS",
        "CODE_COMMENT_ALIGNMENT_NOT_APPLICABLE",
        "PARALLEL_GROUP_LAYOUT",
        "PARALLEL_GROUP_COVERAGE",
        "PARALLEL_GROUP_LEDGER",
        "SOURCE_COMPONENT_ORDER",
    }
)


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    """Return a mapping or raise a useful error for malformed input."""

    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def normalize_mode(value: object, *, default: str = "light") -> str:
    """Normalize the public aliases while exposing only the two runtime modes."""

    aliases = {"advisory": "light", "contract": "strict", "task_required": "strict"}
    mode = aliases.get(str(value), str(value)) if value is not None else default
    if mode not in GUIDANCE_MODES:
        raise ValueError(f"guidance mode must be one of {GUIDANCE_MODES}")
    return mode


def _unique_triggers(values: list[str]) -> list[str]:
    """Keep trigger order stable while rejecting unknown trigger names."""

    result: list[str] = []
    for value in values:
        if value not in EXPAND_TRIGGERS:
            raise ValueError(f"unknown guidance expansion trigger: {value}")
        if value not in result:
            result.append(value)
    return result


def _infer_triggers(
    specification: Mapping[str, Any],
    *,
    length_class: str,
    section_count: int,
    clarification_status: str,
) -> list[str]:
    """Infer only observable triggers; never infer a topic's risk from prose."""

    triggers: list[str] = []
    if length_class in {"long", "extended"} or bool(specification.get("long_input")):
        triggers.append("long_input")
    if bool(specification.get("high_risk")) or str(specification.get("risk_level", "")).lower() in {
        "high",
        "critical",
    }:
        triggers.append("high_risk")
    if bool(specification.get("material_ambiguity")) or clarification_status == "BLOCKED":
        triggers.append("material_ambiguity")
    if bool(specification.get("user_requested_detail")) or bool(specification.get("expand_requested")):
        triggers.append("user_request")
    if bool(specification.get("multi_step")) or section_count > 1:
        triggers.append("multi_step")
    return triggers


def _effective_depth(default_depth: str, triggers: list[str], requested: object) -> str:
    """Choose the smallest useful depth, allowing an explicit user override."""

    if requested is not None:
        selected = str(requested)
        if selected not in DEPTHS:
            raise ValueError(f"guidance depth must be one of {DEPTHS}")
        return selected
    if "high_risk" in triggers or "material_ambiguity" in triggers or "user_request" in triggers:
        return "expanded"
    if "long_input" in triggers or "multi_step" in triggers:
        return "guided"
    return default_depth


def resolve_guidance(
    specification: Mapping[str, Any],
    *,
    length_class: str,
    section_count: int,
    clarification_status: str,
) -> dict[str, Any]:
    """Build the canonical light/strict guidance object for a task contract."""

    raw = _mapping(specification.get("guidance"), "guidance")
    requested_mode = raw.get("mode", specification.get("guidance_mode"))
    strict_requested = bool(specification.get("strict_contract")) or str(
        specification.get("evaluation_mode", "")
    ).lower() in {"strict", "qualification", "evaluation"}
    mode = normalize_mode("strict" if strict_requested else requested_mode, default="light")

    default_depth = str(raw.get("default_depth", "minimal"))
    if default_depth not in DEPTHS:
        raise ValueError(f"guidance default_depth must be one of {DEPTHS}")
    explicit_triggers = raw.get("expand_triggers", raw.get("expand_when"))
    if explicit_triggers is not None:
        if not isinstance(explicit_triggers, list):
            raise ValueError("guidance expand_triggers must be an array")
        triggers = _unique_triggers([str(value) for value in explicit_triggers])
    else:
        triggers = _infer_triggers(
            specification,
            length_class=length_class,
            section_count=section_count,
            clarification_status=clarification_status,
        )

    requested_depth = raw.get("selected_depth", raw.get("depth"))
    selected_depth = _effective_depth(default_depth, triggers, requested_depth)
    style_enforcement = str(
        raw.get("style_enforcement", "task_required" if mode == "strict" else "advisory")
    )
    if style_enforcement not in {"advisory", "task_required"}:
        raise ValueError("guidance style_enforcement must be advisory or task_required")

    review = _mapping(raw.get("self_review"), "guidance.self_review")
    default_rounds = int(review.get("default_rounds", 1))
    max_rounds = int(review.get("max_rounds", 3 if mode == "strict" else 1))
    if default_rounds < 0 or default_rounds > max_rounds:
        raise ValueError("guidance self_review.default_rounds must fit within max_rounds")
    if max_rounds < 0 or max_rounds > 3:
        raise ValueError("guidance self_review.max_rounds must be between 0 and 3")
    external_semantic_review = bool(
        review.get("external_semantic_review", mode == "strict")
    )
    local_patch_only = bool(review.get("local_patch_only", True))

    optional = _mapping(raw.get("optional_enhancements"), "guidance.optional_enhancements")
    return {
        "mode": mode,
        "default_depth": default_depth,
        "selected_depth": selected_depth,
        "expand_triggers": triggers,
        "style_enforcement": style_enforcement,
        "content_integrity_protection": bool(
            raw.get("content_integrity_protection", True)
        ),
        "self_review": {
            "default_rounds": default_rounds,
            "max_rounds": max_rounds,
            "external_semantic_review": external_semantic_review,
            "local_patch_only": local_patch_only,
        },
        "optional_enhancements": {
            "line_numbers": bool(optional.get("line_numbers", True)),
            "hover_term_cards": bool(optional.get("hover_term_cards", True)),
        },
    }


def task_guidance(task: Mapping[str, Any], *, legacy_mode: str = "strict") -> Mapping[str, Any]:
    """Read guidance from a task contract, treating pre-guidance contracts safely."""

    delivery = task.get("delivery", {})
    if isinstance(delivery, Mapping) and isinstance(delivery.get("guidance"), Mapping):
        return delivery["guidance"]
    # Older contracts were authored for the qualification-style closure path.
    # Keeping them strict avoids silently weakening an existing evaluation.
    normalized = normalize_mode(legacy_mode)
    return {
        "mode": normalized,
        "style_enforcement": "task_required" if normalized == "strict" else "advisory",
    }


def is_style_advisory(rule_id: str, task: Mapping[str, Any]) -> bool:
    """Return whether one finding is non-blocking for this particular task."""

    if rule_id not in STYLE_RULES:
        return False
    guidance = task_guidance(task)
    if guidance.get("mode") == "strict" or guidance.get("style_enforcement") == "task_required":
        return False

    structure = task.get("structure", {})
    code = task.get("code", {})
    presentation = task.get("presentation", {})
    if rule_id.startswith("PARALLEL_GROUP_") and structure.get("parallel_groups"):
        return False
    if rule_id.startswith("CODE_COMMENT_ALIGNMENT_") and code.get("coverage_mode") == "annotated_code":
        return False
    if rule_id == "SOURCE_COMPONENT_ORDER":
        # The source-before-explanation flag is an explicit component contract,
        # not a default taste preference
        return False
    if rule_id == "PARENTHETICAL_ENGLISH_CASE" and task.get("terminology", {}).get("term_requirements"):
        return False
    if rule_id in {"COMPONENT_ALIGNMENT", "CAPTION_ALIGNMENT", "ALIGNMENT_LIMITATION", "GITHUB_RENDER_EVIDENCE"}:
        if presentation.get("render_evidence"):
            return False
    if rule_id.startswith("SECTION_"):
        section_plan = structure.get("section_plan", {})
        if section_plan.get("enforced"):
            return False
    return True


def split_findings(
    findings: list[Mapping[str, Any]], task: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Separate blocking findings from style advisories without losing evidence."""

    blocking: list[dict[str, Any]] = []
    advisories: list[dict[str, Any]] = []
    for raw in findings:
        finding = dict(raw)
        if is_style_advisory(str(finding.get("rule_id", "")), task):
            advisories.append(finding)
        else:
            blocking.append(finding)
    return blocking, advisories
