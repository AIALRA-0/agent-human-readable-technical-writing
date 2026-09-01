"""Deterministically validate Agent-produced writing contracts and coverage ledgers."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable

import jsonschema
from referencing import Registry, Resource


ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"
RULE_LEVELS = ["MACHINE_FINAL", "MACHINE_CANDIDATE", "PROFILE_REQUIRED", "ADVISORY"]
LENGTH_CLASSES = (
    (80, "very_short"),
    (250, "short"),
    (700, "medium"),
    (1500, "long"),
    (None, "extended"),
)


def _schema_registry() -> Registry:
    """Load every local schema into an in-memory registry so validation stays offline."""

    registry = Registry()
    for path in CONTRACTS.glob("*.schema.json"):
        schema = json.loads(path.read_text(encoding="utf-8"))
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    return registry


def _validate(instance: Any, schema_name: str) -> None:
    """Validate one public runtime object against its versioned JSON Schema."""

    schema = json.loads((CONTRACTS / schema_name).read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(
        schema, registry=_schema_registry(), format_checker=jsonschema.FormatChecker()
    )
    validator.validate(instance)


def classify_length(input_char_count: int) -> str:
    """Classify one Unicode-character count using the vNext low-token ranges."""

    if input_char_count < 1:
        raise ValueError("input_char_count must be at least 1")
    for upper, name in LENGTH_CLASSES:
        if upper is None or input_char_count <= upper:
            return name
    raise AssertionError("length classification is not exhaustive")


def compile_contract(specification: dict[str, Any]) -> dict[str, Any]:
    """Fill deterministic defaults without pretending to infer arbitrary natural language."""

    required = ["task_id", "base_operation", "augmentation", "audience", "genre", "media", "components"]
    missing = [key for key in required if key not in specification]
    if missing:
        raise ValueError("missing compile inputs: " + ", ".join(missing))

    base_operation = specification["base_operation"]
    reading_context = specification.get("reading_context", "standalone")
    known_terms = [] if reading_context == "standalone" else list(specification.get("known_terms", []))
    source_coverage = specification.get(
        "source_coverage_target", 1.0 if base_operation in {"TRANSFORM", "TRANSLATE"} else 0.0
    )
    component_order = list(specification.get("component_order", []))
    registered_components = {item["component_id"] for item in component_order}
    for component in specification["components"]:
        if component in {"IMAGE", "TABLE", "CODE"} and component not in registered_components:
            component_order.append({"component_id": component, "source_before_explanation": True})

    media = list(specification["media"])
    renderer_name = specification.get("renderer")
    if renderer_name is None:
        if "github_markdown" in media or "markdown" in media:
            renderer_name = "github_markdown"
        elif "word" in media:
            renderer_name = "word"
        elif "pdf" in media:
            renderer_name = "pdf"
        elif "html" in media:
            renderer_name = "html"
        elif "chat" in media:
            renderer_name = "chat"
        else:
            renderer_name = "other"
    exact_alignment = renderer_name in {"github_markdown", "html", "word", "pdf"}
    exact_caption_alignment = exact_alignment
    has_visual = any(item in {"IMAGE", "TABLE", "FLOWCHART"} for item in specification["components"])
    source_material = dict(specification.get("source_material", {}))
    source_material.setdefault("required", False)
    source_material.setdefault("format", "none")
    source_material.setdefault("reason", "当前任务没有要求逐字呈现原始材料")
    component_alignment = dict(specification.get("component_alignment", {}))
    component_alignment.setdefault("object", "center" if has_visual else "not_applicable")
    component_alignment.setdefault("caption", "center" if has_visual else "not_applicable")
    component_alignment.setdefault(
        "fallback",
        "GitHub 输出使用经过实际渲染验证的 HTML 容器或原生 Mermaid 加居中题注"
        if renderer_name == "github_markdown" and has_visual else "当前媒介能够执行登记的对齐方式",
    )

    input_char_count = int(specification.get("input_char_count", 1))
    length_class = specification.get("length_class", classify_length(input_char_count))
    if length_class != classify_length(input_char_count):
        raise ValueError("length_class differs from input_char_count")
    global_recheck_required = length_class in {"long", "extended"}

    term_requirements = []
    for provided in specification.get("term_requirements", []):
        requirement = dict(provided)
        registered = requirement.setdefault("registered", True)
        requirement.setdefault("official_case_verified", registered)
        requirement.setdefault("official_english", None)
        requirement.setdefault("abbreviation", None)
        requirement.setdefault("name_rationale", "术语名称依据登记表或官方来源")
        requirement.setdefault("name_rationale_source", f"registry:{requirement['term_id']}")
        requirement.setdefault("parenthetical_english_case", "title_case")
        requirement.setdefault("parenthetical_form", None)
        requirement.setdefault("official_case_precedence", True)
        requirement.setdefault("acronym_expansion_allowed", False)
        term_requirements.append(requirement)

    contract = {
        "identity": {"task_id": specification["task_id"], "contract_version": "1.1", "profile_revision": "round-5-inline-alignment-aemp"},
        "operation": {"base_operation": base_operation, "augmentation": specification["augmentation"], "source_coverage_target": source_coverage},
        "context": {
            "audience": specification["audience"], "genre": specification["genre"],
            "media": media, "components": list(specification["components"]),
            "user_profile": specification.get("user_profile", "lucas"), "reading_context": reading_context,
        },
        "long_context": {
            "content_task": specification.get("content_task", "explanation"),
            "input_char_count": input_char_count,
            "length_class": length_class,
            "section_count": int(specification.get("section_count", 1)),
            "global_recheck_required": specification.get("global_recheck_required", global_recheck_required),
            "anchor_requirements": list(specification.get("long_context_anchors", [])),
            "term_scope_requirements": list(specification.get("term_scope_requirements", [])),
            "source_priority_requirements": list(specification.get("source_priority_requirements", [])),
        },
        "terminology": {"known_terms": known_terms, "term_requirements": term_requirements},
        "structure": {"parallel_groups": list(specification.get("parallel_groups", []))},
        "components": {"component_order": component_order, "layout_exceptions": list(specification.get("layout_exceptions", []))},
        "code": {
            "coverage_mode": specification.get("code_coverage_mode", "not_applicable"),
            "unit_mappings": list(specification.get("code_unit_mappings", [])),
            "comment_alignment": specification.get("comment_alignment", {
                "mode": "longest_commentable_line" if specification.get("code_coverage_mode") == "annotated_code" else "not_applicable",
                "scope": "per_code_block",
                "overflow_policy": "allow",
            }),
        },
        "conversation": {
            "preserve_superseded_requirements": specification.get("preserve_superseded_requirements", False),
            "superseded_texts": list(specification.get("superseded_texts", [])),
            "reason": specification.get("superseded_reason", "当前任务没有要求保留已经撤销或替换的要求"),
        },
        "presentation": {
            "renderer": {
                "name": renderer_name,
                "exact_object_alignment": exact_alignment,
                "exact_caption_alignment": exact_caption_alignment,
            },
            "source_material": source_material,
            "component_alignment": component_alignment,
            "render_evidence": list(specification.get("render_evidence", [])),
        },
        "boundaries": {"boundary_requirements": list(specification.get("boundary_requirements", []))},
        "quality": {
            "provenance_required": specification.get("provenance_required", True),
            "protected_categories": list(specification.get("protected_categories", ["NUMBER", "DATE", "VERSION", "PATH", "CODE_IDENTIFIER", "NEGATION", "CONDITION", "SCOPE", "MODALITY"])),
            "rule_levels": list(specification.get("rule_levels", RULE_LEVELS)),
            "inline_code_tokens": list(specification.get("inline_code_tokens", [])),
        },
        "clarification": specification.get("clarification", {"status": "CLEAR", "blocking_questions": []}),
    }
    _validate(contract, "task-contract.schema.json")
    return contract


def _finding(rule_id: str, location: str, reason: str, impact: str, next_step: str, status: str = "FAIL") -> dict[str, str]:
    """Create one finding whose result, cause, effect, and next action stay together."""

    return {"rule_id": rule_id, "status": status, "location": location, "reason": reason, "impact": impact, "next": next_step}


def _duplicates(values: Iterable[str]) -> set[str]:
    """Return duplicate identifiers without changing their original order elsewhere."""

    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return duplicates


def verify_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    """Check structure, references, coverage, ordering, and exact preservation evidence."""

    try:
        _validate(bundle, "verification-bundle.schema.json")
    except jsonschema.ValidationError as error:
        report = _build_report([_finding("SCHEMA_VALIDATION", "/" + "/".join(map(str, error.absolute_path)), error.message, "运行时无法可靠读取该验证包", "修复结构后重新验证")], 1)
        _validate(report, "verification-report.schema.json")
        return report

    findings: list[dict[str, str]] = []
    checks = 0
    task = bundle["task_contract"]
    if task["clarification"]["status"] == "BLOCKED":
        findings.append(_finding("BLOCKING_CLARIFICATION", "task_contract/clarification", "任务合同仍有会改变结果的歧义", "继续成文可能改变事实、范围或输出规模", "取得用户决定后重新编译", "REVIEW_REQUIRED"))
    checks += 1

    long_task = task["long_context"]
    long_coverage = bundle["long_context_coverage"]
    expected_metadata = (
        long_task["input_char_count"], long_task["length_class"], long_task["section_count"]
    )
    actual_metadata = (
        long_coverage["input_char_count"], long_coverage["length_class"], long_coverage["section_count"]
    )
    if actual_metadata != expected_metadata:
        findings.append(_finding(
            "LONG_CONTEXT_METADATA", "long_context_coverage",
            "验证包登记的字符数、篇幅档或章节数与任务合同不一致",
            "全文检查可能针对错误版本或错误范围执行",
            "按任务合同重新登记长上下文元数据",
        ))
    checks += 1
    if long_task["global_recheck_required"] and not long_coverage["full_document_check"]:
        findings.append(_finding(
            "FULL_DOCUMENT_RECHECK", "long_context_coverage/full_document_check",
            "长篇任务只完成了局部检查，没有登记拼接后的全文复核",
            "远距离条件、例外、数字或术语漂移可能未被发现",
            "完成全文复核并重新生成验证包",
        ))
    checks += 1

    anchor_coverage = {item["anchor_id"]: item for item in long_coverage["anchors"]}
    for requirement in long_task["anchor_requirements"]:
        actual = anchor_coverage.get(requirement["anchor_id"])
        if actual is None:
            findings.append(_finding(
                "LONG_CONTEXT_ANCHOR_MISSING", requirement["anchor_id"],
                "任务合同登记的远距离事实、条件或例外没有覆盖记录",
                "长文中的关键约束可能在后续章节丢失",
                "定位对应输出并登记原值与输出位置",
            ))
        elif any(actual[field] != requirement[field] for field in ("kind", "source_locator", "expected_value")):
            findings.append(_finding(
                "LONG_CONTEXT_ANCHOR_BINDING", requirement["anchor_id"],
                "覆盖记录绑定了不同的锚点种类、来源位置或预期值",
                "验证结果不能证明当前任务合同中的原始约束",
                "恢复任务合同中的精确锚点声明",
            ))
        elif (
            actual["status"] != "preserved"
            or actual["observed_value"] != requirement["expected_value"]
            or not actual["output_locator"]
        ):
            findings.append(_finding(
                "LONG_CONTEXT_ANCHOR_VALUE", requirement["anchor_id"],
                "远距离锚点在输出中缺失、改变或无法定位",
                "事实、条件、否定、例外、数字或范围发生漂移",
                "恢复精确值并登记可核对的输出位置",
            ))
        checks += 1

    term_coverage = {(item["term"], item["scope_id"]): item for item in long_coverage["term_scopes"]}
    for requirement in long_task["term_scope_requirements"]:
        key = (requirement["term"], requirement["scope_id"])
        actual = term_coverage.get(key)
        if (
            actual is None
            or actual["expected_meaning"] != requirement["expected_meaning"]
            or actual["observed_meaning"] != requirement["expected_meaning"]
            or not actual["output_locator"]
        ):
            findings.append(_finding(
                "LONG_CONTEXT_TERM_SCOPE", requirement["scope_id"],
                "术语在指定章节作用域中缺失或改变含义",
                "同词跨章节可能被错误合并，或者同一含义发生漂移",
                "按作用域恢复术语含义并登记输出位置",
            ))
        checks += 1

    priority_coverage = {item["conflict_id"]: item for item in long_coverage["source_priorities"]}
    for requirement in long_task["source_priority_requirements"]:
        actual = priority_coverage.get(requirement["conflict_id"])
        if (
            actual is None
            or actual["selected_source_id"] != requirement["priority_source_id"]
            or (requirement["must_surface"] and not actual["surfaced"])
        ):
            findings.append(_finding(
                "LONG_CONTEXT_SOURCE_PRIORITY", requirement["conflict_id"],
                "冲突来源没有采用声明的优先来源，或没有向读者暴露冲突",
                "输出可能静默选择过期或低优先级事实",
                "采用登记的优先来源，并在要求时明确说明冲突",
            ))
        checks += 1

    id_groups = {
        "source_spans": [item["identity"]["source_span_id"] for item in bundle["source_spans"]],
        "source_atoms": [item["identity"]["atom_id"] for item in bundle["source_atoms"]],
        "background_atoms": [item["identity"]["atom_id"] for item in bundle["background_atoms"]],
        "inference_atoms": [item["identity"]["atom_id"] for item in bundle["inference_atoms"]],
        "segments": [item["identity"]["segment_id"] for item in bundle["segment_contracts"]],
        "support_maps": [item["identity"]["mapping_id"] for item in bundle["support_maps"]],
        "sentences": [item["sentence_id"] for item in bundle["rendered_document"]["sentences"]],
    }
    for group, values in id_groups.items():
        duplicates = _duplicates(values)
        if duplicates:
            findings.append(_finding("DUPLICATE_IDENTIFIER", group, "发现重复标识 " + ", ".join(sorted(duplicates)), "引用关系无法确定唯一对象", "为重复对象分配新标识"))
        checks += 1

    span_ids = set(id_groups["source_spans"])
    source_ids = set(id_groups["source_atoms"])
    background_ids = set(id_groups["background_atoms"])
    inference_ids = set(id_groups["inference_atoms"])
    atom_ids = source_ids | background_ids | inference_ids
    segment_ids = set(id_groups["segments"])
    sentence_ids = set(id_groups["sentences"])

    presentations_by_span = {item["source_span_id"]: item for item in bundle["source_presentations"]}
    source_presentation = task["presentation"]["source_material"]
    if source_presentation["required"]:
        missing_presentations = span_ids - set(presentations_by_span)
        if missing_presentations:
            findings.append(_finding("SOURCE_PRESENTATION", "source_presentations", "要求逐字展示的原始材料缺少呈现记录", "读者无法把解释与原始证据直接核对", "按照任务合同使用引用块、代码块、原图、原表或独立原文小节"))
        for span_id, presentation in presentations_by_span.items():
            if presentation["format"] != source_presentation["format"]:
                findings.append(_finding("SOURCE_PRESENTATION_FORMAT", span_id, "原始材料的呈现形式与任务合同不一致", "逐字证据可能被当成普通结论或使用错误媒介", "改用任务合同登记的呈现形式"))
            if not presentation["verbatim"]:
                findings.append(_finding("SOURCE_PRESENTATION_VERBATIM", span_id, "原始材料呈现记录没有声明逐字保留", "原始证据可能在展示时被改写", "恢复逐字内容并把 verbatim 设为 true"))
            if presentation["rendered_excerpt"] not in bundle["rendered_document"]["text"]:
                findings.append(_finding("SOURCE_PRESENTATION_PRESENCE", span_id, "登记的原始材料没有出现在最终正文", "读者无法看到需要核对的原始内容", "把登记片段恢复到最终正文"))
            checks += 3
    checks += 1

    for span in bundle["source_spans"]:
        actual = hashlib.sha256(span["content"]["text"].encode("utf-8")).hexdigest()
        if actual != span["content"]["sha256"]:
            findings.append(_finding("SOURCE_SPAN_HASH", span["identity"]["source_span_id"], "原文片段摘要与内容不一致", "来源锚点可能已经变化", "重新提取片段并更新摘要"))
        checks += 1

    for atom in bundle["source_atoms"]:
        if atom["source_linkage"]["source_span_id"] not in span_ids:
            findings.append(_finding("SOURCE_LINKAGE", atom["identity"]["atom_id"], "源语义单元指向不存在的原文片段", "该主张无法追溯到原文", "补齐正确的 source_span_id"))
        checks += 1

    for atom in bundle["inference_atoms"]:
        missing_support = set(atom["support"]["supported_by"]) - (source_ids | background_ids)
        if missing_support:
            findings.append(_finding("INFERENCE_SUPPORT", atom["identity"]["atom_id"], "推断引用不存在的来源单元", "推断没有可核对依据", "修复 supported_by 或删除推断"))
        checks += 1

    assigned_source: set[str] = set()
    assigned_background: set[str] = set()
    assigned_inference: set[str] = set()
    for segment in bundle["segment_contracts"]:
        coverage = segment["coverage"]
        assigned_source.update(coverage["source_atoms"])
        assigned_background.update(coverage["background_atoms"])
        assigned_inference.update(coverage["inference_atoms"])
        unknown = (set(coverage["source_atoms"]) - source_ids) | (set(coverage["background_atoms"]) - background_ids) | (set(coverage["inference_atoms"]) - inference_ids)
        if unknown:
            findings.append(_finding("SEGMENT_UNKNOWN_ATOM", segment["identity"]["segment_id"], "段落合同引用不存在的语义单元", "覆盖矩阵包含无效关系", "删除或修复无效单元标识"))
        checks += 1
    required_source = {item["identity"]["atom_id"] for item in bundle["source_atoms"] if item["preservation"]["required"]}
    if required_source - assigned_source:
        findings.append(_finding("SOURCE_ATOM_ALLOCATION", "segment_contracts", "必需源语义单元尚未分配到段落", "源信息覆盖率低于任务要求", "把缺失单元分配到明确段落"))
    checks += 1
    if background_ids - assigned_background:
        findings.append(_finding("BACKGROUND_ATOM_ALLOCATION", "segment_contracts", "补充背景没有全部分配到允许段落", "背景来源覆盖率低于 100%", "把背景单元分配到明确段落，或删除无用途背景"))
    checks += 1
    if inference_ids - assigned_inference:
        findings.append(_finding("INFERENCE_ATOM_ALLOCATION", "segment_contracts", "推断没有全部分配到段落", "正文可能出现未追踪推断或登记了无用途推断", "分配推断或删除无用途推断"))
    checks += 1
    for atom in bundle["background_atoms"]:
        used_segments = {segment["identity"]["segment_id"] for segment in bundle["segment_contracts"] if atom["identity"]["atom_id"] in segment["coverage"]["background_atoms"]}
        if not used_segments <= set(atom["usage_limits"]["allowed_segments"]):
            findings.append(_finding("BACKGROUND_ALLOWED_SEGMENT", atom["identity"]["atom_id"], "补充背景进入了未授权段落", "背景知识可能抢占原文主线或改变来源边界", "移动到允许段落或更新经过审核的使用范围"))
        checks += 1

    mapped_atoms: set[str] = set()
    mapped_sentences: set[str] = set()
    for mapping in bundle["support_maps"]:
        target = mapping["target"]
        unknown = set(mapping["support"]["atom_ids"]) - atom_ids
        if target["segment_id"] not in segment_ids or target["sentence_id"] not in sentence_ids or unknown:
            findings.append(_finding("SUPPORT_MAP_REFERENCE", mapping["identity"]["mapping_id"], "支持映射引用不存在的句子、段落或语义单元", "正文句子无法完成可追溯核对", "修复支持映射中的目标和来源标识"))
        mapped_atoms.update(mapping["support"]["atom_ids"])
        mapped_sentences.add(target["sentence_id"])
        checks += 1
    if sentence_ids - mapped_sentences:
        findings.append(_finding("UNMAPPED_SENTENCE", "rendered_document/sentences", "存在没有支持映射的正文句子", "新增内容可能没有来源或必要作用", "为句子登记来源和角色，或删除无作用句子"))
    checks += 1
    if required_source - mapped_atoms:
        findings.append(_finding("SOURCE_ATOM_RENDERING", "support_maps", "必需源语义单元没有进入任何正文句子", "源信息覆盖率低于 100%", "补写对应信息并登记支持映射"))
    checks += 1
    if background_ids - mapped_atoms:
        findings.append(_finding("BACKGROUND_ATOM_RENDERING", "support_maps", "补充背景没有全部映射到正文句子", "背景来源覆盖率低于 100%", "补齐对应支持映射或删除未使用背景"))
    checks += 1
    if inference_ids - mapped_atoms:
        findings.append(_finding("INFERENCE_ATOM_RENDERING", "support_maps", "推断没有全部映射到正文句子", "推断来源和强度无法核对", "补齐对应支持映射或删除未使用推断"))
    checks += 1

    rendered = bundle["rendered_document"]
    if hashlib.sha256(rendered["text"].encode("utf-8")).hexdigest() != rendered["sha256"]:
        findings.append(_finding("RENDERED_DOCUMENT_HASH", "rendered_document", "正文摘要与当前文字不一致", "验证结果无法绑定最终正文", "重新计算摘要并重新验证"))
    checks += 1
    for span in bundle["source_spans"]:
        missing_tokens = [token for token in span["protection"]["protected_tokens"] if token not in rendered["text"]]
        if missing_tokens:
            findings.append(_finding("PROTECTED_TOKEN_PRESENCE", span["identity"]["source_span_id"], "受保护的数字或机器标识没有保留", "事实或机器含义可能发生漂移", "恢复受保护标识并重新验证"))
        checks += 1
    for sentence in rendered["sentences"]:
        if not sentence["verbatim"] and "。" in sentence["text"] and task["context"]["user_profile"] == "lucas":
            findings.append(_finding("LUCAS_PUNCTUATION", sentence["sentence_id"], "生成正文含有中文句号", "正文不符合当前用户配置", "只修改该句标点并重新验证"))
        checks += 1
    previous_actor: str | None = None
    for sentence in rendered["sentences"]:
        clarity = sentence["actor_clarity"]
        if sentence["verbatim"]:
            continue
        if clarity["status"] == "explicit":
            if not clarity["actor"]:
                findings.append(_finding("ACTOR_CLARITY", sentence["sentence_id"], "句子声明主体明确，但没有登记实际主体", "动作归属无法核对", "登记执行动作或产生结果的主体"))
            else:
                previous_actor = clarity["actor"]
        elif clarity["status"] == "carried":
            if not clarity["actor"] or previous_actor != clarity["actor"]:
                findings.append(_finding("ACTOR_CLARITY", sentence["sentence_id"], "句子省略主体，但前文没有同一主体可自然承接", "读者可能无法判断谁执行动作或产生结果", "补出主体，或修正承接关系"))
        elif clarity["actor"] is not None:
            findings.append(_finding("ACTOR_CLARITY", sentence["sentence_id"], "无动作句登记了执行主体", "主体账本与正文作用不一致", "清除主体，或把状态改为 explicit"))
        checks += 1

    if re.search(r"\n[ \t]*\n[ \t]*\n", rendered["text"]):
        findings.append(_finding("EXCESSIVE_BLANK_LINES", "rendered_document/text", "正文出现连续两个以上空行", "相关内容被过度拉开，阅读连续性下降", "把同一结构之间的空白缩减为 Markdown 解析所需数量"))
    checks += 1
    for token in task["quality"]["inline_code_tokens"]:
        if f"`{token}`" not in rendered["text"]:
            findings.append(_finding("INLINE_CODE_MARKUP", token, "命令、字段、路径或代码类型没有使用行内代码格式", "机器标识与普通文字难以区分", "只给该标识补充反引号"))
        checks += 1

    term_uses: dict[str, list[dict[str, Any]]] = {}
    for item in bundle["term_uses"]:
        term_uses.setdefault(item["term_id"], []).append(item)
    for requirement in task["terminology"]["term_requirements"]:
        uses = term_uses.get(requirement["term_id"], [])
        authored = next((item for item in uses if item["context"] == "authored_prose"), None)
        use = authored or (uses[0] if uses else None)
        if not requirement["registered"] or not requirement["official_case_verified"]:
            findings.append(_finding(
                "UNVERIFIED_OFFICIAL_CASE", requirement["term_id"],
                "术语登记表和官方来源都没有确认当前英文大小写",
                "程序无法安全决定括号英文或品牌名称应该采用哪种形式",
                "核对官方来源并登记正式写法后重新编译", "REVIEW_REQUIRED",
            ))
        elif authored:
            if authored["official_form"] != requirement["official_form"] or authored["official_form"] not in rendered["text"]:
                findings.append(_finding(
                    "REGISTERED_TERM_CASE", requirement["term_id"],
                    "生成正文没有使用术语登记表中的官方大小写",
                    "品牌、缩写或正式名称可能被错误改写",
                    "只把该术语恢复为登记的 official_form",
                ))
            expected_parenthetical = requirement["parenthetical_form"]
            if expected_parenthetical is not None and authored["parenthetical_form"] != expected_parenthetical:
                findings.append(_finding(
                    "PARENTHETICAL_ENGLISH_CASE", requirement["term_id"],
                    "括号内英文没有使用登记的标题式大小写",
                    "中文说明与当前用户确认的英文格式不一致",
                    "只把括号内英文恢复为登记形式",
                ))
            if not requirement["acronym_expansion_allowed"] and authored["claimed_expansion"] is not None:
                findings.append(_finding(
                    "ACRONYM_EXPANSION", requirement["term_id"],
                    "生成正文把不可展开的名称写成了首字母缩写",
                    "读者会把伪造的英文全称误认为官方名称",
                    "删除伪造展开，只保留官方名称和通用类别",
                ))
        if not use or not set(requirement["required_meanings"]) <= set(use["meanings_covered"]):
            findings.append(_finding("TERM_FIRST_USE_COVERAGE", requirement["term_id"], "术语首次形式或解释含义覆盖不足", "零先验读者无法完成当前判断或操作", "补齐正式名称和缺失的自然解释"))
        checks += 1

    parallel_coverage = {item["group_id"]: item for item in bundle["parallel_group_coverage"]}
    for requirement in task["structure"]["parallel_groups"]:
        actual = parallel_coverage.get(requirement["group_id"])
        if actual is None:
            findings.append(_finding(
                "PARALLEL_GROUP_LEDGER", requirement["group_id"],
                "任务合同登记了排比组，但验证包没有对应结构记录",
                "两个以上平行项目可能被压成难以扫描的连续语句",
                "登记每个项目及其列表位置后重新验证",
            ))
        else:
            required_items = set(requirement["item_ids"])
            if set(actual["item_ids"]) != required_items or not required_items <= set(actual["covered_item_ids"]):
                findings.append(_finding(
                    "PARALLEL_GROUP_COVERAGE", requirement["group_id"],
                    "排比组没有覆盖合同登记的全部项目",
                    "平行定义、步骤、比较对象或事实可能发生遗漏",
                    "恢复缺失项目，并保持原有自然顺序",
                ))
            if not actual["rendered_as_list"] or actual["nesting_depth"] < requirement["minimum_depth"]:
                findings.append(_finding(
                    "PARALLEL_GROUP_LAYOUT", requirement["group_id"],
                    "排比组没有使用合同要求的缩进列表层级",
                    "平行关系被埋在连续文本中，读者难以逐项核对",
                    "把各项目换行并按层级缩进，不改变项目内容",
                ))
        checks += 1

    if not task["conversation"]["preserve_superseded_requirements"]:
        leaked = [item for item in task["conversation"]["superseded_texts"] if item in rendered["text"]]
        if leaked:
            findings.append(_finding(
                "SUPERSEDED_REQUIREMENT_LEAK", "rendered_document/text",
                "最终答案仍然包含已经被追加要求替换的旧内容",
                "读者可能把失效要求误认为当前仍然有效",
                "删除失效内容；只有历史、审计或撤销说明任务才保留",
            ))
        checks += 1

    component_orders = {item["component_id"]: item for item in task["components"]["component_order"]}
    layout_exceptions = {item["component_id"] for item in task["components"]["layout_exceptions"]}
    covered_component_ids = {item["component_id"] for item in bundle["component_coverage"]}
    missing_components = set(component_orders) - covered_component_ids
    if missing_components:
        findings.append(_finding("COMPONENT_LEDGER_PRESENCE", "component_coverage", "任务合同登记的组件缺少覆盖账本", "原图、原表或原始代码无法证明已经保留并解释", "为每个组件增加覆盖记录"))
    checks += 1
    for component in bundle["component_coverage"]:
        component_id = component["component_id"]
        order = component_orders.get(component_id)
        if order and order["source_before_explanation"] and component["source_position"] > component["explanation_position"]:
            findings.append(_finding("SOURCE_COMPONENT_ORDER", component_id, "原始组件出现在解释之后", "读者无法先核对原图、原表或原始代码", "把原始组件移动到解释前"))
        if component["source_text"] not in rendered["text"]:
            findings.append(_finding("SOURCE_COMPONENT_PRESENCE", component_id, "最终正文没有保留原始组件", "解释失去可直接核对的原始证据", "恢复原始组件并保持内容不变"))
        missing_units = set(component["required_units"]) - set(component["covered_units"])
        if missing_units:
            findings.append(_finding("COMPONENT_UNIT_COVERAGE", component_id, "组件有效单元没有全部覆盖", "图片、表格或代码说明存在理解缺口", "补齐缺失单元的功能和作用说明"))
        if component["component_type"] == "TABLE" and set(component["table_cells"]["all"]) - set(component["table_cells"]["covered"]):
            findings.append(_finding("TABLE_CELL_COVERAGE", component_id, "表格数据格没有全部映射", "结论可能遗漏异常值或关键数据", "使用列定义、值词典、行映射或单格说明补齐覆盖"))
        code_coverage = component["code"]
        if component["component_type"] == "CODE":
            expected_mode = task["code"]["coverage_mode"]
            if code_coverage is None or expected_mode == "not_applicable" or code_coverage["coverage_mode"] != expected_mode:
                findings.append(_finding(
                    "CODE_COVERAGE_MODE", component_id,
                    "代码组件没有使用任务合同登记的注释或逐行解释路径",
                    "密集概述可能冒充逐行覆盖，零先验读者无法定位每个有效语句",
                    "选择 annotated_code 或 line_by_line_explanation，并登记每个有效代码单元",
                ))
            elif code_coverage["uncovered_units"]:
                findings.append(_finding(
                    "CODE_UNIT_COVERAGE", component_id,
                    "代码覆盖账本仍有未解释的有效语句",
                    "读者无法确认这些语句的动作、原因或结果",
                    "为每个未覆盖单元增加合法注释或独立可定位解释",
                ))
            else:
                task_units = {item["unit_id"] for item in task["code"]["unit_mappings"]}
                covered_units = {item["unit_id"] for item in code_coverage["unit_mappings"]}
                if task_units != covered_units:
                    findings.append(_finding(
                        "CODE_UNIT_MAPPING", component_id,
                        "代码组件的单元映射与任务合同不一致",
                        "部分有效语句可能没有独立解释位置",
                        "按任务合同补齐每个代码单元的解释映射",
                    ))
                alignment_contract = task["code"]["comment_alignment"]
                alignment = code_coverage["comment_alignment"]
                if expected_mode == "annotated_code":
                    if (
                        alignment_contract["mode"] != "longest_commentable_line"
                        or alignment["mode"] != "longest_commentable_line"
                        or not alignment["blocks"]
                    ):
                        findings.append(_finding(
                            "CODE_COMMENT_ALIGNMENT_MODE", component_id,
                            "注释代码没有使用最长可注释代码行作为同行对齐基准",
                            "同一代码块中的注释起点不稳定，读者难以逐行扫描",
                            "把所有可注释语句的注释标记移到最长代码行之后的同一列",
                        ))
                    else:
                        alignment_ids: set[str] = set()
                        target_failure = False
                        unit_failure = False
                        for block in alignment["blocks"]:
                            commentable = [item for item in block["units"] if item["commentable"]]
                            if not commentable:
                                unit_failure = True
                                continue
                            expected_column = max(item["code_width"] for item in commentable) + 2
                            alignment_ids.update(item["unit_id"] for item in commentable)
                            if block["target_column"] != expected_column:
                                target_failure = True
                            if any(not item["same_line"] or item["comment_column"] != expected_column for item in commentable):
                                unit_failure = True
                        if target_failure:
                            findings.append(_finding(
                                "CODE_COMMENT_ALIGNMENT_TARGET", component_id,
                                "至少一个代码块登记的注释目标列不是该块最长代码显示宽度加二",
                                "验证包不能证明每个代码块的注释真正从各自最长代码行之后开始",
                                "逐块去掉代码尾部空白，按四列制表位计算宽度并重新登记目标列",
                            ))
                        if alignment_ids != task_units or unit_failure:
                            findings.append(_finding(
                                "CODE_COMMENT_ALIGNMENT_UNITS", component_id,
                                "至少一个可注释语句缺少同行注释或注释起点没有在所属代码块内对齐",
                                "代码说明出现错列、换行或漏行，覆盖账本与实际呈现不一致",
                                "把每个可注释 CODE 单元的注释放在所属代码块的目标列并保持同行",
                            ))
                elif (
                    alignment_contract["mode"] != "not_applicable"
                    or alignment["mode"] != "not_applicable"
                    or alignment["blocks"]
                ):
                    findings.append(_finding(
                        "CODE_COMMENT_ALIGNMENT_NOT_APPLICABLE", component_id,
                        "逐行解释路径仍然登记了同行注释对齐证据",
                        "不能添加合法注释的格式可能被伪装成已注释代码",
                        "把同行对齐记为 not_applicable，并只保留逐行解释映射",
                    ))
        mermaid = component["mermaid"]
        if mermaid:
            if mermaid["direction"] in {"LR", "RL"} and component_id not in layout_exceptions:
                findings.append(_finding("MERMAID_VERTICAL_DEFAULT", component_id, "横向 Mermaid 没有登记不可替代理由", "图形违反当前纵向阅读配置", "改用 TD 或登记真实布局例外"))
            if any(not value.strip() for value in mermaid["post_explanation"].values()):
                findings.append(_finding("MERMAID_POST_EXPLANATION", component_id, "图后缺少节点关系、流程结果或证据边界", "读者只能看到结构，无法判断实际含义", "在图后补齐三项说明"))
        presentation = component["presentation"]
        renderer = task["presentation"]["renderer"]
        requested = task["presentation"]["component_alignment"]
        if presentation["renderer"] != renderer["name"]:
            findings.append(_finding("COMPONENT_RENDERER", component_id, "组件覆盖记录与任务合同登记了不同渲染器", "对齐能力和渲染限制无法可靠核对", "使用任务合同中的渲染器名称"))
        if requested["object"] == "center" and renderer["exact_object_alignment"] and presentation["object_alignment"] != "center":
            findings.append(_finding("COMPONENT_ALIGNMENT", component_id, "当前渲染器支持精确居中，但对象没有登记为居中", "视觉对象偏离用户的默认布局要求", "把对象与题注一起设为居中"))
        if requested["caption"] == "center" and renderer["exact_caption_alignment"] and presentation["caption_alignment"] != "center":
            findings.append(_finding("CAPTION_ALIGNMENT", component_id, "当前渲染器支持题注居中，但题注没有登记为居中", "题注与对象的视觉关系不一致", "把题注设为居中"))
        if requested["object"] == "center" and not renderer["exact_object_alignment"] and not presentation["limitation"].strip():
            findings.append(_finding("ALIGNMENT_LIMITATION", component_id, "渲染器不能保证对象精确居中，但覆盖记录没有说明限制", "系统可能把无法保证的布局误报为已经实现", "说明渲染限制，并完成实际渲染检查"))
        if renderer["name"] == "github_markdown" and component["component_type"] in {"IMAGE", "TABLE", "FLOWCHART"}:
            evidence = [item for item in task["presentation"]["render_evidence"] if item["component_id"] == component_id]
            combinations = {(item["viewport_width"], item["theme"]) for item in evidence}
            required_combinations = {(390, "light"), (390, "dark"), (1280, "light"), (1280, "dark")}
            failed_evidence = [item for item in evidence if not item["object_centered"] or not item["caption_centered"] or item["horizontal_overflow"]]
            if combinations != required_combinations or failed_evidence:
                findings.append(_finding(
                    "GITHUB_RENDER_EVIDENCE", component_id,
                    "GitHub 视觉对象缺少桌面、移动端、亮色或暗色实际渲染证据，或者渲染结果没有居中",
                    "源码中的居中标记不能证明用户看到的对象和题注已经居中且没有溢出",
                    "完成四种视口与主题组合的实际渲染检查，并修复失败结果",
                ))
        checks += 12

    boundary_coverage = {item["claim_id"]: item for item in bundle["boundary_coverage"]}
    for requirement in task["boundaries"]["boundary_requirements"]:
        actual = boundary_coverage.get(requirement["claim_id"])
        if not actual or any(not actual[field].strip() for field in ("missing_evidence", "importance", "next_verification")):
            findings.append(_finding("BOUNDARY_EVIDENCE", requirement["claim_id"], "证据边界缺少证据缺口、重要性或下一项验证", "裸露的否定结论不能指导后续核对", "补齐三项边界内容"))
        checks += 1

    report = _build_report(findings, checks)
    _validate(report, "verification-report.schema.json")
    return report


def _build_report(findings: list[dict[str, str]], checked_rules: int) -> dict[str, Any]:
    """Derive one stable status while preserving every finding's causal explanation."""

    failed = sum(item["status"] == "FAIL" for item in findings)
    review = sum(item["status"] == "REVIEW_REQUIRED" for item in findings)
    if failed:
        status, reason, impact, next_step = "FAIL", f"已确认 {failed} 项结构、引用或覆盖错误", "当前正文不能交付或修复", "按照问题位置局部修复后重新验证"
    elif review:
        status, reason, impact, next_step = "REVIEW_REQUIRED", f"存在 {review} 项需要用户决定的阻塞性歧义", "程序无法安全确定正确内容", "取得用户决定后重新编译任务合同"
    else:
        status, reason, impact, next_step = "PASS", "结构、引用、覆盖、顺序和精确保留检查全部通过", "验证包可以进入人工审核", "由用户判断表达是否达到最终阅读标准"
    return {"status": status, "summary": {"checked_rules": checked_rules, "failed_rules": failed, "review_rules": review, "reason": reason, "impact": impact, "next": next_step}, "findings": findings}


def report_summary(report: dict[str, Any]) -> dict[str, Any]:
    """Validate and return the stable report envelope without changing its decision."""

    _validate(report, "verification-report.schema.json")
    return report
