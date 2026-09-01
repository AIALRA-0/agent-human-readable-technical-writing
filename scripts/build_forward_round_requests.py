"""Build any gated post-round-two unseen request set from synthetic material."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FORWARD = ROOT / "evals" / "forward"
RANGES = {"very_short": (1, 80), "short": (81, 250), "medium": (251, 700), "long": (701, 1500), "extended": (1501, 3000)}
TARGETS = {"very_short": 60, "short": 180, "medium": 560, "long": 1250, "extended": 2200}
SLOTS = [
    ("TRANSFORM", "NONE", ["TEXT"]), ("TRANSLATE", "GLOSS", ["TEXT"]),
    ("COMPRESS", "NONE", ["TEXT"]), ("EXPLAIN", "TEACHING", ["TEXT"]),
    ("GENERATE", "GLOSS", ["TEXT"]), ("FORMAT_ONLY", "NONE", ["TEXT"]),
    ("EXPLAIN", "EXPLANATORY", ["IMAGE", "TEXT"]), ("EXPLAIN", "GLOSS", ["TABLE", "TEXT"]),
    ("EXPLAIN", "TEACHING", ["CODE", "TEXT"]), ("TRANSFORM", "GLOSS", ["TEXT"]),
    ("TRANSFORM", "EXPLANATORY", ["TEXT"]), ("TRANSLATE", "EXPLANATORY", ["TEXT"]),
    ("EXPLAIN", "TEACHING", ["TEXT"]), ("COMPRESS", "GLOSS", ["TEXT"]),
    ("GENERATE", "EXPLANATORY", ["TEXT"]), ("FORMAT_ONLY", "NONE", ["TEXT"]),
    ("EXPLAIN", "EXPLANATORY", ["IMAGE", "TEXT"]), ("EXPLAIN", "GLOSS", ["TABLE", "TEXT"]),
    ("EXPLAIN", "TEACHING", ["CODE", "TEXT"]), ("TRANSFORM", "GLOSS", ["TEXT"]),
]
EVEN_TASKS = ["status", "operation", "audit", "tutorial", "operation", "reference", "explanation", "decision", "tutorial", "operation", "reference", "explanation", "decision", "audit", "tutorial", "status", "reference", "explanation", "decision", "audit"]
ODD_TASKS = ["status", "operation", "audit", "tutorial", "operation", "reference", "explanation", "decision", "tutorial", "operation", "reference", "explanation", "status", "audit", "tutorial", "status", "reference", "explanation", "decision", "audit"]
AUDIENCES = ["zero_prior_knowledge", "operator", "technical_practitioner", "decision_maker", "auditor"] * 4
LENGTHS = ["very_short"] * 4 + ["short"] * 4 + ["medium"] * 4 + ["long"] * 4 + ["extended"] * 4
VARIATIONS = [
    ["numeric_scope", "negation_exception"], ["negation_exception"], ["numeric_scope"], ["numeric_scope"],
    ["distributed_condition", "negation_exception"], ["mixed_format", "negation_exception"], ["mixed_format", "numeric_scope"], ["mixed_format", "distributed_condition", "numeric_scope"],
    ["mixed_format", "distributed_condition", "negation_exception"], ["correction_turn", "distributed_condition", "numeric_scope", "urgency_or_emotion", "negation_exception"],
    ["mixed_format", "distributed_condition"], ["conflicting_sources", "distributed_condition", "numeric_scope", "negation_exception"],
    ["conflicting_sources", "distributed_condition", "numeric_scope", "urgency_or_emotion"], ["noisy_input", "distributed_condition", "negation_exception"],
    ["noisy_input", "correction_turn"], ["noisy_input", "numeric_scope"], ["mixed_format", "distributed_condition"],
    ["conflicting_sources", "numeric_scope"], ["mixed_format", "negation_exception"], ["distributed_condition", "numeric_scope", "negation_exception"],
]
FAMILIES = [
    ("潮闸巡检", "回流水位", "闸位确认", "把巡检结果改写成不越界的状态说明"),
    ("洁净蒸汽隔离", "残余蒸汽", "双阀隔离", "翻译成操作员可执行的中文并就近解释术语"),
    ("助学金抽样", "资格样本", "材料缺口", "压缩审核结论，保留样本范围和未检查部分"),
    ("声学校准", "参考声压", "背景噪声", "向零基础读者解释两个读数为何不能直接互换"),
    ("网状节点入网", "入网窗口", "频道锁定", "依据材料写首次入网步骤并解释术语"),
    ("快照命令", "预演模式", "索引清单", "只整理成命令参考，不改变参数含义"),
    ("灌溉分区图", "支路阀", "回流箭头", "保留图并说明图能证明与不能证明的内容"),
    ("无人机航线", "禁飞时段", "电量余量", "保留表格，为决策者解释限制和证据缺口"),
    ("校验和脚本", "分块摘要", "失败退出", "保留代码，同行对齐注释并解释执行边界"),
    ("冷库应急指令", "降载阈值", "旁路禁用", "合并多轮指令，明确最新要求和已失效要求"),
    ("遥测字段", "sample_window", "quality_state", "改写为技术人员可查阅的字段参考"),
    ("档案库渗水", "含水率", "采样断点", "完整翻译说明并区分来源冲突和补充解释"),
    ("车队切换", "并行派单", "回退时限", "从零解释两个方案并给出有条件建议"),
    ("标本交接", "交接链", "封签复核", "压缩成审核者可复核的结论，保留例外和缺口"),
    ("光伏逆变器", "直流隔离", "放电等待", "用给定材料写安全教程并处理修正指令"),
    ("批处理窗口", "完成批次", "待重跑批次", "只重排为清楚的状态版式，不补事实"),
    ("洪水风险图", "重现期", "高程基准", "保留图并解释颜色、范围和不能外推的结论"),
    ("采购报价", "含税价", "交付窗口", "保留表格并解释冲突报价和比较边界"),
    ("日志解析器", "容错分支", "未知级别", "保留代码，同行对齐注释并解释异常路径"),
    ("保留策略审计", "保留期", "法律保留", "改写审计记录，绑定分散条件、例外和来源优先级"),
]
ROUND_NAMES = ["青岚", "澄野", "栖潮", "砺川", "云岬", "星浦", "松原", "霁谷"]


def digest(value: Any) -> str:
    """Return a stable content digest."""

    payload = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def material_text(source: dict[str, Any]) -> str:
    """Flatten source content for the contract character count."""

    content = source["content"]
    if source["material_type"] == "image":
        return str(content["alt"])
    if isinstance(content, list):
        return "".join(str(item) for item in content)
    return str(content)


def input_chars(item: dict[str, Any]) -> int:
    """Count request, source, and references exactly as the validator does."""

    return len(item["request"]) + len(material_text(item["source"])) + sum(len(reference["content"]) for reference in item["references"])


def latest_by_origin(round_number: int) -> dict[str, dict[str, Any]]:
    """Load the terminal revision for every origin in one prior round."""

    lifecycle = FORWARD / f"round-{round_number}" / "lifecycle"
    latest: dict[str, dict[str, Any]] = {}
    for path in lifecycle.rglob("*.json"):
        record = json.loads(path.read_text(encoding="utf-8"))
        origin = record["identity"]["origin_case_id"]
        if origin not in latest or record["identity"]["revision"] > latest[origin]["identity"]["revision"]:
            latest[origin] = record
    return latest


def perfect_first_draft(round_number: int) -> bool:
    """Return whether every revision-one record in a round is Gold."""

    lifecycle = FORWARD / f"round-{round_number}" / "lifecycle"
    first = [json.loads(path.read_text(encoding="utf-8")) for path in lifecycle.rglob("*.json") if json.loads(path.read_text(encoding="utf-8"))["identity"]["revision"] == 1]
    return len(first) == 20 and all(item["identity"]["status"] == "gold" for item in first)


def check_gate(round_number: int, target_exists: bool) -> None:
    """Allow a new round only after all revisions in the prior round are Gold."""

    if round_number < 3:
        raise SystemExit("use build_forward_round2_requests.py for round 2")
    if target_exists:
        return
    previous = latest_by_origin(round_number - 1)
    if len(previous) != 20 or any(item["identity"]["status"] != "gold" for item in previous.values()):
        raise SystemExit(f"round {round_number} is gated until every round {round_number - 1} revision is explicitly accepted")
    if round_number >= 4 and perfect_first_draft(round_number - 1) and perfect_first_draft(round_number - 2):
        raise SystemExit("two consecutive perfect first-draft rounds already satisfy the release gate")


def source_for(round_number: int, index: int, terms: list[str], facts: list[str]) -> dict[str, Any]:
    """Build component-appropriate synthetic source material."""

    if index in (7, 17):
        return {"material_type": "image", "content": {"path": f"assets/forward-r{round_number}-{index:02d}.svg", "alt": f"{terms[0]}示意图，含{terms[1]}与{terms[2]}标记"}}
    if index in (8, 18):
        return {"material_type": "table", "content": f"| 选项 | 数值 | 限制 |\n|---|---:|---|\n| {terms[1]} | {round_number * 7 + index} | 仅适用已登记时段 |\n| {terms[2]} | {round_number * 9 + index} | 缺少现场复核 |"}
    if index in (9, 19):
        return {"material_type": "code", "content": f"def check_{round_number}_{index}(items):\n    for item in items:\n        if item.get('state') == 'ok':\n            continue\n        return False\n    return True"}
    if index == 10:
        return {"material_type": "multi_turn", "content": [facts[0], facts[1], facts[2]]}
    return {"material_type": "text", "content": "；".join(facts)}


def extend_references(item: dict[str, Any], facts: list[str], target: int) -> None:
    """Add varied evidence sections until the requested real length band is reached."""

    dimensions = ["范围", "前置条件", "数字归属", "否定边界", "例外", "来源", "跨节术语", "不可外推结论"]
    sections: list[str] = []
    cursor = 0
    while input_chars(item) + len("".join(sections)) < target:
        dimension = dimensions[cursor % len(dimensions)]
        fact = facts[cursor % len(facts)]
        sections.append(f"第{cursor + 1}节｜{dimension}：{fact}；这一节只支持本节陈述，复核全文时仍须保留其他章节的条件、数值归属与例外。")
        cursor += 1
    if sections:
        item["references"].append({"id": "REF-LONG-CONTEXT", "content": "".join(sections)})


def build_rows(round_number: int) -> list[dict[str, Any]]:
    """Build one deterministic 20-case round without reading expected answers."""

    label = ROUND_NAMES[(round_number - 3) % len(ROUND_NAMES)] + str((round_number - 3) // len(ROUND_NAMES) + 1)
    tasks = EVEN_TASKS if round_number % 2 == 0 else ODD_TASKS
    rows: list[dict[str, Any]] = []
    for index, family in enumerate(FAMILIES, start=1):
        topic, term_a, term_b, request = family
        terms = [f"{label}{topic}", term_a, term_b]
        serial = (round_number - 1) * 20 + index
        facts = [
            f"{label}{topic}记录编号为 R{round_number}-{index:02d}",
            f"{term_a}登记值为 {round_number * 10 + index}，只适用于第 {index} 项范围",
            f"{term_b}尚未完成现场复核，不能据此声称全部通过",
            f"例外条件是来源冲突时保留两种记录，不静默选择其一",
            f"最新修正覆盖旧的统一处理要求，但不覆盖安全停止条件",
            f"连续记录从 {8 + round_number}:10 到 {8 + round_number}:40，单点读数不能代表整个区间",
            f"主记录使用单位 U{index}，附录中的旧单位不得直接与它相加",
            f"来源 A 是本轮签署记录；来源 B 是早一轮草稿，冲突时 A 优先且 B 仍需展示",
            f"同词“状态”在操作章节表示设备状态，在审计章节表示证据审核状态，两者不可互换",
            f"缺少第 {index + 2} 站点材料，因此结论只覆盖已经列出的站点",
        ]
        source = source_for(round_number, index, terms, facts)
        operation, augmentation, components = SLOTS[index - 1]
        request_text = f"{request}；不得补充材料外事实；保留复核编号 R{round_number}-{index:02d}"
        references = [{"id": "REF-BOUNDARY", "content": "；".join(facts[1:])}]
        if LENGTHS[index - 1] == "very_short":
            source = {"material_type": "text", "content": f"{term_a}{round_number * 10 + index}；{term_b}未核"}
            request_text = request.split("，", 1)[0]
            references = []
        elif LENGTHS[index - 1] == "short":
            request_text = request.split("，", 1)[0]
            references = [{"id": "REF-BOUNDARY", "content": facts[2]}]
            if source["material_type"] == "text":
                source = {"material_type": "text", "content": "；".join(facts[:2])}
        item = {
            "case_id": f"FWD-R{round_number}-{serial:03d}",
            "round": round_number,
            "base_operation": operation,
            "augmentation": augmentation,
            "genre": f"synthetic_{topic}",
            "audience": AUDIENCES[(index + round_number - 3) % 20],
            "content_task": tasks[index - 1],
            "length_class": LENGTHS[index - 1],
            "topic_id": f"TOPIC-R{round_number}-{serial:03d}",
            "core_terms": terms,
            "variation_tags": VARIATIONS[index - 1],
            "components": components,
            "request": request_text,
            "source": source,
            "references": references,
        }
        target = 2850 if index == 20 else TARGETS[LENGTHS[index - 1]]
        if LENGTHS[index - 1] != "very_short":
            extend_references(item, facts, target)
        item["source"]["sha256"] = digest(item["source"]["content"])
        item["input_char_count"] = input_chars(item)
        low, high = RANGES[item["length_class"]]
        if not low <= item["input_char_count"] <= high:
            raise RuntimeError(f"{item['case_id']}: {item['input_char_count']} characters outside {low}-{high}")
        rows.append(item)
    return rows


def write_image_assets(rows: list[dict[str, Any]]) -> None:
    """Create inert local SVG evidence for the four IMAGE slots."""

    for item in rows:
        if item["source"]["material_type"] != "image":
            continue
        relative = item["source"]["content"]["path"]
        target = ROOT / "evals" / "forward" / f"round-{item['round']}" / relative
        title = item["source"]["content"]["alt"]
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="960" height="540" viewBox="0 0 960 540" role="img">\n'
            f'  <title>{title}</title>\n'
            '  <rect width="960" height="540" fill="#f4f7fb"/>\n'
            '  <rect x="90" y="110" width="300" height="260" rx="24" fill="#d9e8ff" stroke="#315b8a" stroke-width="4"/>\n'
            '  <rect x="570" y="110" width="300" height="260" rx="24" fill="#e4f3df" stroke="#3f7444" stroke-width="4"/>\n'
            '  <path d="M410 240 H540" stroke="#ad4d2f" stroke-width="10" marker-end="url(#arrow)"/>\n'
            '  <defs><marker id="arrow" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto"><path d="M0,0 L0,6 L9,3 z" fill="#ad4d2f"/></marker></defs>\n'
            f'  <text x="480" y="455" text-anchor="middle" font-family="sans-serif" font-size="28">{item["case_id"]} 合成评测图</text>\n'
            '</svg>\n'
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(svg, encoding="utf-8", newline="\n")


def parse_args() -> argparse.Namespace:
    """Select one post-round-two request set."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--round", type=int, required=True, dest="round_number")
    return parser.parse_args()


def main() -> int:
    """Write a gated deterministic request set for isolated generation."""

    args = parse_args()
    target = FORWARD / f"round-{args.round_number}" / "requests.jsonl"
    check_gate(args.round_number, target.exists())
    rows = build_rows(args.round_number)
    write_image_assets(rows)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in rows), encoding="utf-8", newline="\n")
    print(json.dumps({
        "status": "PASS", "round": args.round_number, "requests": len(rows),
        "lengths": Counter(item["length_class"] for item in rows),
        "audiences": Counter(item["audience"] for item in rows),
        "tasks": Counter(item["content_task"] for item in rows),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
