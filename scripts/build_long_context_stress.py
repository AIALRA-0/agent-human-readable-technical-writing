"""Build eight synthetic 1200-3000 character long-context stress cases."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "evals" / "long-context" / "vnext-1.1-8-cases.jsonl"

CASES: list[dict[str, Any]] = [
    {"id": "LONG-001", "dimension": "distant_condition_exception", "title": "冷库除霜准入说明", "facts": ["常规准入条件是温度低于 -12°C 且当班主管批准", "维护演练窗口内可以在 -10°C 启动，但仍需主管批准", "消防紧急处置不适用温度条件，由现场指挥程序接管", "门磁未关闭时任何常规或演练准入都不得启动"], "required": ["-12", "-10", "主管", "消防", "门磁"], "forbidden": ["无需主管批准", "门磁未关闭也可"]},
    {"id": "LONG-002", "dimension": "cross_section_numeric_ownership", "title": "科研经费分段核对", "facts": ["设备预算 480 万元属于甲项目，不含税", "培训预算 36 万元属于乙项目，含税", "甲项目上限 500 万元只约束设备采购", "乙项目的差旅上限是 12 万元，与培训预算分开", "附录中的 8% 是设备采购税率假设，不是预算增长率"], "required": ["480", "甲项目", "36", "乙项目", "12", "8%"], "forbidden": ["乙项目的设备预算", "8%是预算增长率"]},
    {"id": "LONG-003", "dimension": "cross_section_term_consistency", "title": "数据冻结点解释", "facts": ["冻结点在本文始终指停止接收新业务记录的时间戳", "快照点指备份完成时刻，与冻结点不同", "恢复演练从快照点开始，但一致性核对以冻结点为边界", "任何章节都不得把冻结点改写成删除数据或关闭服务器"], "required": ["冻结点", "停止接收", "快照点", "一致性"], "forbidden": ["冻结点是删除数据", "冻结点是关闭服务器"]},
    {"id": "LONG-004", "dimension": "same_word_local_scope", "title": "两个窗口的局部含义", "facts": ["维护窗口是周日 01:00 至 02:00 的时间范围", "确认窗口是界面中显示确认按钮的对话框", "维护窗口结束后不得继续写数据库", "关闭确认窗口只取消当前界面动作，不结束维护窗口", "两个窗口同词不同义，解释时必须就近限定"], "required": ["维护窗口", "01:00", "确认窗口", "对话框"], "forbidden": ["关闭确认窗口会结束维护窗口"]},
    {"id": "LONG-005", "dimension": "conflicting_source_priority", "title": "保修期限来源冲突", "facts": ["正式保修条款版本 4 写明主机保修 24 个月", "客服速查表仍写 18 个月，更新时间早于版本 4", "内部会议口头提到 30 个月，但未形成批准文件", "来源优先级是正式条款高于速查表，速查表高于未批准口头说明", "结论必须展示冲突，不能静默取平均值"], "required": ["24", "18", "30", "正式条款", "优先"], "forbidden": ["平均值构成结论依据", "当前保修期为30个月", "三个来源一致"]},
    {"id": "LONG-006", "dimension": "table_prose_anomaly_binding", "title": "配送表异常绑定", "facts": ["表格中订单 Q7 的到达时间缺失，用破折号表示", "正文日志只说明 Q7 扫码器离线，不能证明订单未到达", "订单 Q8 晚 17 分钟，原因栏写道路封闭", "道路封闭来源是司机备注，尚无交通平台记录", "Q9 提前 4 分钟，不属于晚到异常"], "required": ["Q7", "缺失", "扫码器", "Q8", "17", "Q9"], "forbidden": ["Q7已确认未到达", "Q9晚到4分钟"]},
    {"id": "LONG-007", "dimension": "code_log_explanation_mix", "title": "队列处理代码与日志", "facts": ["原始 Python 每次取一条消息，成功后 ack，异常时 nack 且 requeue=True", "日志显示消息 m-17 已 nack 两次，第三次尚无日志", "配置 max_attempts=3 只由调用方检查，给出的函数内部没有读取该配置", "解释必须保留原始代码并另给同行对齐注释版", "不能据日志声称 m-17 已经进入死信队列"], "required": ["m-17", "nack", "requeue", "max_attempts", "不能.*死信"], "forbidden": ["m-17.*已经进入死信"]},
    {"id": "LONG-008", "dimension": "multi_turn_supersession", "title": "多轮发布门禁覆盖", "facts": ["初始要求是测试通过 95% 即可发布", "第二轮把门槛改为 100% 且零高严重度错误", "第三轮补充文档检查，但没有降低测试门槛", "最新要求取消周五强制发布时间，改为门禁满足后人工选择时间", "审计输出要保留变更历史，执行清单只展示当前有效要求"], "required": ["100%", "零高严重度", "文档", "人工选择", "变更历史"], "forbidden": ["当前门槛是95%", "当前仍须周五强制发布"]},
]


def expand(case: dict[str, Any]) -> str:
    sections = [f"# {case['title']}"]
    headings = ["背景记录", "条件记录", "数值记录", "例外记录", "来源记录", "跨节复核", "边界记录", "最终核对"]
    index = 0
    while len("\n\n".join(sections)) < 1300:
        fact = case["facts"][index % len(case["facts"])]
        heading = headings[index % len(headings)]
        sections.append(f"## {heading} {index + 1}\n记录：{fact}\n边界：本段只证明所列事实；如果其他章节出现相似词语，仍需按本段主体、时间、条件和来源重新绑定，不能用局部检查替代全篇复核")
        index += 1
    return "\n\n".join(sections)


def main() -> int:
    rows = []
    for case in CASES:
        material = expand(case)
        if not 1200 <= len(material) <= 3000:
            raise SystemExit(f"{case['id']} material length {len(material)} is outside 1200-3000")
        extra = "\n代码与日志原件：\n```python\ndef process(queue):\n    message = queue.get()\n    try:\n        handle(message)\n        message.ack()\n    except Exception:\n        message.nack(requeue=True)\n```\n```text\n10:00 m-17 nack attempt=1\n10:05 m-17 nack attempt=2\n```\n配置：max_attempts=3" if case["id"] == "LONG-007" else ""
        prompt = f"""用户配置 `round-5-inline-alignment-aemp` 已启用。请使用已安装的 human-readable-technical-writing Skill，把下面长材料写成面向审核者的中文说明。必须全篇复核，保留条件、否定、例外、数字归属、来源冲突和术语局部边界；结尾明确写出“已复核全篇”，但不得把自动检查写成人工接受。普通中文正文不使用中文句号。{('保留原始代码，并另给每条有效语句都有同行注释且始终同行对齐的 Python 代码块。' if case['id'] == 'LONG-007' else '')}\n\n{material}{extra}"""
        rows.append({"case_id": case["id"], "dimension": case["dimension"], "input_char_count": len(material + extra), "prompt": prompt, "required_patterns": case["required"] + ["已复核全篇"], "forbidden_patterns": case["forbidden"]})
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8", newline="\n")
    print(json.dumps({"status": "PASS", "cases": len(rows), "lengths": [row["input_char_count"] for row in rows]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
