"""Generate randomized, source-only cases for clean-agent trigger and format testing.

The generator deliberately writes requests and source material only.  It never
creates an expected answer, score, Gold record, or reviewer hint.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path
from typing import Any

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "contracts" / "forward-request.schema.json"
LENGTHS = ("very_short", "short", "medium", "long", "extended")
RANGES = {
    "very_short": (1, 80), "short": (81, 250), "medium": (251, 700),
    "long": (701, 1500), "extended": (1501, 3000),
}
AUDIENCES = ("zero_prior_knowledge", "operator", "technical_practitioner", "decision_maker", "auditor")
TASKS = ("tutorial", "operation", "reference", "explanation", "decision", "status", "audit")
OPERATIONS = ("TRANSFORM", "TRANSLATE", "COMPRESS", "EXPLAIN", "GENERATE", "FORMAT_ONLY")
AUGMENTATIONS = ("NONE", "GLOSS", "EXPLANATORY", "TEACHING")
COMPONENT_SETS = (
    ("TEXT",), ("TEXT",), ("TEXT", "TABLE"), ("TEXT", "CODE"),
    ("TEXT", "IMAGE"), ("TEXT", "TABLE", "CODE"), ("TEXT", "CODE", "IMAGE"),
)
THEMES = (
    ("校园实验室冷却系统", "冷却曲线", "阀门状态"),
    ("城市雨水调蓄池", "水位阈值", "排水窗口"),
    ("移动端离线地图", "缓存范围", "路线版本"),
    ("博物馆展柜照明", "照度读数", "开放时段"),
    ("社区共享电池柜", "充电上限", "温度告警"),
    ("远程课堂录播流程", "音频延迟", "字幕版本"),
    ("小型风机维护计划", "振动幅值", "停机条件"),
    ("食品冷链交接记录", "箱内温度", "交接时间"),
    ("图书馆自助借还设备", "识别次数", "人工接管"),
    ("农田灌溉排班", "土壤含水率", "降雨例外"),
    ("医院候诊叫号屏", "叫号延迟", "断网模式"),
    ("社区空气质量监测", "颗粒物读数", "校准周期"),
    ("海边潮汐观测站", "潮位基线", "风暴警戒"),
    ("仓库机器人路线", "避障距离", "人工通道"),
    ("公共充电站预约", "预约时段", "占用状态"),
    ("家庭网络设备升级", "固件版本", "回退窗口"),
    ("影视素材归档", "帧率标记", "代理文件"),
    ("小区门禁访客登记", "通行时限", "消防疏散"),
    ("河道浮标传感器", "采样间隔", "漂移范围"),
    ("社区厨房库存盘点", "批次数量", "过期处理"),
    ("天文社团望远镜预约", "观测时长", "云量限制"),
    ("电商退货质检", "缺陷等级", "退款条件"),
    ("公共自行车调度", "站点余量", "临时关闭"),
    ("小型数据中心巡检", "机柜温度", "告警级别"),
    ("出版社校样流转", "校样轮次", "编辑确认"),
    ("校园食堂排队分析", "等待分钟数", "高峰时段"),
    ("建筑工地材料验收", "批次编号", "复检要求"),
    ("海岛淡水储罐", "液位比例", "供水优先级"),
    ("公园夜间照明", "照明区段", "节能时段"),
    ("本地音乐会入场", "座位区域", "迟到处理"),
    ("社区应急物资", "库存下限", "领取范围"),
    ("高架桥伸缩缝巡查", "缝宽变化", "复测时间"),
    ("校车路线调整", "到站时间", "临时绕行"),
    ("果园霜冻预警", "叶面温度", "覆盖措施"),
    ("小型印刷机换版", "版面编号", "清洁步骤"),
    ("公益热线工单", "响应分钟数", "转交条件"),
    ("社区停车引导", "空位数量", "夜间规则"),
    ("实验样本冷藏", "保存温度", "取样次数"),
    ("线上课程证书发放", "完成比例", "复核状态"),
    ("街区垃圾分类巡查", "投放时段", "误投类型"),
)


def digest(value: Any) -> str:
    raw = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def control_json(target_chars: int) -> str:
    """Create valid JSON of approximately the requested source size."""
    payload: dict[str, Any] = {"status": "ok", "count": 2, "note": ""}
    base_length = len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    payload["note"] = "x" * max(0, target_chars - base_length)
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def material_text(theme: str, term_a: str, term_b: str, rng: random.Random, target: int) -> str:
    facts = [
        f"{theme}的本轮记录使用编号 V-{rng.randrange(1000, 9999)}，主记录在周三上午建立",
        f"{term_a}第一次记录为 {rng.choice(['12', '18', '24', '35', '42'])}，这个数值只适用于东侧区域",
        f"{term_b}的有效范围是 {rng.choice(['8 至 12 分钟', '15 至 20 分钟', '30 至 45 分钟', '0.4 至 0.8 米'])}，不能外推到其他区域",
        "来源甲来自现场记录，来源乙来自上一轮摘要，两者冲突时保留两条记录并优先核对来源甲",
        "附加说明指出某个例外只在维护人员到场时成立，普通运行期间不能套用这个例外",
        "一条后续修正取消了早先的统一处理方式，但没有取消停止操作和保留原始记录的要求",
        "材料中有重复段落、顺序混乱的备注和一条没有明确作者的判断，不能把它们当成新的事实",
        "若记录缺少完整时间段，只能说明已覆盖的时间范围，不能声称全时段已经确认",
        "同一个词在说明部分表示设备状态，在审核部分表示记录状态，两种含义必须分开",
        "最终结论必须保留已知限制、否定条件、数值归属和仍待核对的项目",
    ]
    rng.shuffle(facts)
    if target <= 80:
        return f"{term_a}{rng.randrange(1, 9)}；{term_b}待核"
    text = "\n\n".join(f"第 {index} 节\n{fact}" for index, fact in enumerate(facts, start=1))
    while len(text) < target:
        fact = rng.choice(facts)
        text += f"\n\n补充记录：{fact}；这一段不能替代其他章节的条件、范围或例外"
    return text[:target]


def table_text(theme: str, term_a: str, term_b: str) -> str:
    return (
        f"| 区域 | {term_a} | {term_b} | 状态 |\n"
        "|---|---:|---:|---|\n"
        f"| 东侧 | 18 | 0.4 | 已记录 |\n"
        f"| 西侧 | 24 | 0.8 | 待复核 |\n"
        f"| 中央 | 12 | 0.6 | 例外 |\n\n"
        f"{theme}表格的数值来自同一轮记录，但表格没有提供测量误差、设备型号或完整时间段"
    )


def code_text(theme: str, term_a: str, term_b: str) -> str:
    if len(theme) % 2:
        return (
            "def select_records(records, limit):\n"
            "    selected = []\n"
            "    for record in records:\n"
            "        if record.value >= limit:\n"
            "            selected.append(record)\n"
            "    return selected"
        )
    return (
        "SELECT area, reading, status\n"
        "FROM observation_log\n"
        "WHERE status <> 'discarded'\n"
        "ORDER BY reading DESC;"
    )


def source_for(theme: str, term_a: str, term_b: str, components: tuple[str, ...], rng: random.Random, target: int) -> tuple[str, Any]:
    if "CODE" in components:
        code = code_text(theme, term_a, term_b)
        text = material_text(theme, term_a, term_b, rng, max(target - len(code) - 20, 81))
        return "code", f"{code}\n\n附属说明：{text}"
    if "TABLE" in components:
        table = table_text(theme, term_a, term_b)
        text = material_text(theme, term_a, term_b, rng, max(target - len(table) - 20, 81))
        return "table", f"{table}\n\n补充材料：{text}"
    if "IMAGE" in components:
        image = {
            "path": f"assets/{theme[:4]}-diagram.svg",
            "alt": f"{theme}的节点、数值和例外关系示意图",
            "visible_elements": ["三个数据节点", "一条警戒线", "两条连接关系"],
            "visible_limits": "图片不提供实际运行结果、测量误差或未显示的机制",
        }
        text = material_text(theme, term_a, term_b, rng, max(target - 180, 81))
        return "image", {"image": image, "description": text}
    if rng.random() < 0.15:
        turns = [
            f"第一轮：记录 {term_a}，保留原始时间",
            f"追加：把 {term_a} 的适用区域限定为东侧",
            f"修正：不再修改 {term_b}，只记录当前状态并保留待核对项",
        ]
        return "multi_turn", turns
    return "text", material_text(theme, term_a, term_b, rng, target)


def build_cases(seed: int, count: int, round_number: int) -> list[dict[str, Any]]:
    if count != 20:
        raise ValueError("the variability qualification requires exactly 20 cases")
    rng = random.Random(seed)
    themes = rng.sample(THEMES, count)
    lengths = list(LENGTHS) * 4
    audiences = list(AUDIENCES) * 4
    rng.shuffle(lengths)
    rng.shuffle(audiences)
    tasks = list(TASKS) * 3
    tasks.extend(["status", "audit"])
    rng.shuffle(tasks)
    trigger_modes = ["explicit"] * 7 + ["implicit"] * 9 + ["non_triggering_control"] * 4
    rng.shuffle(trigger_modes)
    variation_pool = [
        "distributed_condition", "conflicting_sources", "noisy_input", "mixed_format",
        "correction_turn", "numeric_scope", "negation_exception", "urgency_or_emotion",
    ]
    rows: list[dict[str, Any]] = []
    for index, ((theme, term_a, term_b), length_class, audience, task, trigger_mode) in enumerate(
        zip(themes, lengths, audiences, tasks, trigger_modes), start=1
    ):
        low, high = RANGES[length_class]
        target = rng.randint(low, high)
        if trigger_mode == "non_triggering_control":
            if length_class == "very_short":
                request = "原样保留"
                components = ("TEXT",)
                material_type = "text"
                content = "{\"ok\":1}"
            elif length_class == "short":
                request = "原样输出下面的 JSON，不添加解释"
                components = ("TEXT",)
                material_type = "text"
                content = control_json(max(1, target - len(request)))
            else:
                request = rng.choice([
                    "原样输出下面的 JSON，不添加解释，不改变任何字符",
                    "逐字复制下面的日志，只返回原始日志内容",
                    "只返回下面的纯代码，不添加任何说明或格式处理",
                ])
                components = ("CODE",) if "代码" in request else ("TEXT",)
                material_type = "code" if "代码" in request else "text"
                content = control_json(max(1, target - len(request)))
            references = []
        else:
            if length_class in {"very_short", "short"}:
                components = ("TEXT",)
            else:
                components = rng.choice(COMPONENT_SETS)
            explicit = trigger_mode == "explicit"
            if length_class == "very_short":
                request = f"整理{theme[:4]}"
            elif length_class == "short":
                request = f"整理{theme[:6]}并保留限制"
            else:
                prefix = "请按中文格式规范整理并说明" if explicit else "请把这些材料整理成读者可以直接使用的说明"
                request = (
                    f"{prefix} {theme} 的完整记录，保留所有事实、条件、数值、否定、例外、来源和未确认项；"
                    f"读者是{audience}，任务重点是{task}，不要补写材料外事实"
                )
                if trigger_mode == "implicit":
                    request = request.replace("请把这些材料整理成读者可以直接使用的说明", "请整理这些材料")
            references = [
                {"id": f"REF-{index:03d}-A", "content": f"来源甲确认 {term_a} 只适用于东侧区域，来源乙不能扩大这个范围"},
                {"id": f"REF-{index:03d}-B", "content": f"记录保留 {term_b} 的例外和未核对状态，不能把待核对写成已完成"},
            ]
            if length_class == "short":
                references = references[:1]
            elif length_class == "very_short":
                references = []
        content_budget = max(1, target - len(request) - sum(len(item["content"]) for item in references))
        if trigger_mode == "non_triggering_control":
            pass
        elif length_class == "very_short":
            material_type, content = "text", f"{term_a}为 2；{term_b}待核"
        else:
            source_target = max(content_budget, 81) if length_class == "short" else content_budget
            material_type, content = source_for(theme, term_a, term_b, components, rng, source_target)
        source = {"material_type": material_type, "content": content}
        source["sha256"] = digest(content)
        content_length = len(content if isinstance(content, str) else json.dumps(content, ensure_ascii=False, sort_keys=True))
        serialized_length = len(request) + content_length + sum(len(item["content"]) for item in references)
        if not low <= serialized_length <= high:
            raise ValueError(f"{length_class} generated {serialized_length} characters, expected {low}-{high}")
        if trigger_mode == "non_triggering_control":
            variation_tags = ["mixed_format"] if material_type == "code" else []
        else:
            tags = rng.sample(variation_pool, rng.randint(3, 6))
            variation_tags = sorted(set(tags))
        rows.append({
            "case_id": f"FWD-R{round_number}-{index:03d}",
            "round": round_number,
            "base_operation": "FORMAT_ONLY" if trigger_mode == "non_triggering_control" else rng.choice(OPERATIONS),
            "augmentation": "NONE" if trigger_mode == "non_triggering_control" else rng.choice(AUGMENTATIONS),
            "genre": f"random_{theme[:6]}",
            "audience": audience,
            "content_task": task,
            "length_class": length_class,
            "input_char_count": serialized_length,
            "topic_id": f"TOPIC-R{round_number}-{index:03d}",
            "core_terms": [theme, term_a, term_b],
            "trigger_mode": trigger_mode,
            "variation_tags": variation_tags,
            "components": list(components),
            "request": request,
            "source": source,
            "references": references,
        })
    return rows


def validate_rows(rows: list[dict[str, Any]]) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    for row in rows:
        validator.validate(row)
    if len({row["topic_id"] for row in rows}) != len(rows):
        raise ValueError("duplicate topic id")
    if len({digest(row["source"]["content"]) for row in rows}) != len(rows):
        raise ValueError("duplicate source material")
    for field, expected in (("length_class", 4), ("audience", 4), ("trigger_mode", None)):
        counts: dict[str, int] = {}
        for row in rows:
            counts[row[field]] = counts.get(row[field], 0) + 1
        if field != "trigger_mode" and set(counts.values()) != {expected}:
            raise ValueError(f"{field} distribution is not balanced: {counts}")
    if sum(row["trigger_mode"] == "non_triggering_control" for row in rows) != 4:
        raise ValueError("expected four non-triggering controls")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--round", type=int, default=8)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.round < 2:
        raise SystemExit("round must be at least 2")
    rows = build_cases(args.seed, 20, args.round)
    validate_rows(rows)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8", newline="\n",
    )
    print(json.dumps({"status": "PASS", "seed": args.seed, "cases": len(rows), "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
