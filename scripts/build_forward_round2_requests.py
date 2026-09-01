"""Build the gated 20-case broad-coverage second forward round."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "evals" / "forward" / "round-2" / "requests.jsonl"

SLOTS = [
    ("TRANSFORM", "NONE", ["TEXT"]),
    ("TRANSLATE", "GLOSS", ["TEXT"]),
    ("COMPRESS", "NONE", ["TEXT"]),
    ("EXPLAIN", "TEACHING", ["TEXT"]),
    ("GENERATE", "GLOSS", ["TEXT"]),
    ("FORMAT_ONLY", "NONE", ["TEXT"]),
    ("EXPLAIN", "EXPLANATORY", ["IMAGE", "TEXT"]),
    ("EXPLAIN", "GLOSS", ["TABLE", "TEXT"]),
    ("EXPLAIN", "TEACHING", ["CODE", "TEXT"]),
    ("TRANSFORM", "GLOSS", ["TEXT"]),
    ("TRANSFORM", "EXPLANATORY", ["TEXT"]),
    ("TRANSLATE", "EXPLANATORY", ["TEXT"]),
    ("EXPLAIN", "TEACHING", ["TEXT"]),
    ("COMPRESS", "GLOSS", ["TEXT"]),
    ("GENERATE", "EXPLANATORY", ["TEXT"]),
    ("FORMAT_ONLY", "NONE", ["TEXT"]),
    ("EXPLAIN", "EXPLANATORY", ["IMAGE", "TEXT"]),
    ("EXPLAIN", "GLOSS", ["TABLE", "TEXT"]),
    ("EXPLAIN", "TEACHING", ["CODE", "TEXT"]),
    ("TRANSFORM", "GLOSS", ["TEXT"]),
]

TASKS = [
    "status", "operation", "audit", "tutorial", "operation",
    "reference", "explanation", "decision", "tutorial", "operation",
    "reference", "explanation", "decision", "audit", "tutorial",
    "status", "reference", "explanation", "decision", "audit",
]
AUDIENCES = ["zero_prior_knowledge", "operator", "technical_practitioner", "decision_maker", "auditor"] * 4
LENGTHS = ["very_short"] * 4 + ["short"] * 4 + ["medium"] * 4 + ["long"] * 4 + ["extended"] * 4
TARGET_COUNTS = {"very_short": 1, "short": 150, "medium": 420, "long": 900, "extended": 1750}
RANGES = {"very_short": (1, 80), "short": (81, 250), "medium": (251, 700), "long": (701, 1500), "extended": (1501, 3000)}


CASES: list[dict[str, Any]] = [
    {
        "topic": "sync-window-status", "genre": "sync_status", "terms": ["同步窗口", "只读校验"],
        "request": "改写为清楚的同步状态，不补事实",
        "source": {"material_type": "text", "content": "12 项已核对，2 项待权限恢复；当前只读，未复制。"}, "references": [],
        "tags": ["numeric_scope", "negation_exception"],
        "facts": ["核对对象共 14 项", "已完成 12 项只读核对", "2 项因权限未恢复而等待", "尚未执行复制"],
    },
    {
        "topic": "pump-lockout", "genre": "safety_operation", "terms": ["lockout", "残余压力"],
        "request": "翻译成操作员可执行的中文并解释术语",
        "source": {"material_type": "text", "content": "Lock out the pump; pressure may remain."}, "references": [],
        "tags": ["negation_exception"],
        "facts": ["lockout 指隔离并锁定能源", "停泵不等于压力已经释放", "确认压力为零后才可拆接头", "无法确认时停止操作"],
    },
    {
        "topic": "invoice-sample-audit", "genre": "finance_audit", "terms": ["抽样发票", "税额差异"],
        "request": "压缩审计发现，数字和限制都要保留",
        "source": {"material_type": "text", "content": "抽查 18 张；17 张一致，1 张税额差 3 元；未检查其余 62 张。"}, "references": [],
        "tags": ["numeric_scope"],
        "facts": ["本次只抽查 18 张", "17 张未发现差异", "1 张税额相差 3 元", "其余 62 张不在本次结论范围"],
    },
    {
        "topic": "battery-voltage-basics", "genre": "electrical_tutorial", "terms": ["开路电压", "负载电压"],
        "request": "从零解释两种电压为什么可能不同",
        "source": {"material_type": "text", "content": "无负载读数 12.6 V；接入负载后为 11.9 V。"}, "references": [],
        "tags": ["numeric_scope"],
        "facts": ["开路电压是在未接负载时测得", "负载电压是在设备耗电时测得", "读数下降可能与内阻有关", "两次读数不能单独证明电池必然损坏"],
    },
    {
        "topic": "humidity-sensor-pairing", "genre": "device_setup", "terms": ["配对窗口", "校准偏移"],
        "request": "依据给定事实写首次配对步骤，并就近解释术语",
        "source": {"material_type": "none", "content": ""},
        "references": [{"id": "REF-001", "content": "按住圆键 4 秒进入 45 秒配对窗口；白灯慢闪。连接后先不要改校准偏移。"}],
        "tags": ["distributed_condition", "negation_exception"],
        "facts": ["圆键需要持续按住 4 秒", "白灯慢闪表示配对窗口开启", "配对窗口持续 45 秒", "首次连接后不要立即修改校准偏移"],
    },
    {
        "topic": "archive-cli-reference", "genre": "command_reference", "terms": ["dry-run", "清单文件"],
        "request": "只整理为命令参考版式，不改原词和参数",
        "source": {"material_type": "text", "content": "archive scan --dry-run 只检查 archive pack --list manifest.txt 按清单打包 注意 不要删除源目录"},
        "references": [], "tags": ["mixed_format", "negation_exception"],
        "facts": ["scan 子命令用于检查", "--dry-run 表示不执行写入", "pack 子命令执行打包", "--list 后接清单文件", "源目录不得删除"],
    },
    {
        "topic": "cleanroom-airflow-diagram", "genre": "image_explanation", "terms": ["压差箭头", "回风口"],
        "request": "保留图，解释箭头、区域和图中不能证明的内容",
        "source": {"material_type": "image", "content": {"path": "assets/cleanroom-airflow.svg", "alt": "洁净室气流与压差示意图"}},
        "references": [{"id": "REF-001", "content": "箭头表示设计气流方向；+15 Pa 是设定压差，不是本次实测值。图未给出颗粒计数。"}],
        "tags": ["mixed_format", "numeric_scope", "negation_exception"],
        "facts": ["送风从顶部进入洁净区", "回风口位于低处", "+15 Pa 标的是设计压差", "图中没有实时传感器数据", "不能据图断言洁净度已经达标"],
    },
    {
        "topic": "warehouse-route-choice", "genre": "decision_table", "terms": ["拥堵窗口", "冷链上限"],
        "request": "保留表格，为决策者说明可选路线、限制和缺失证据",
        "source": {"material_type": "table", "content": "| 路线 | 常态耗时 | 限制 |\n|---|---:|---|\n| 东门 | 18 分钟 | 8:00–9:00 拥堵 |\n| 北门 | 24 分钟 | 冷链不得超过 25 分钟 |"},
        "references": [{"id": "REF-001", "content": "没有当天路况或车辆故障数据，不能保证实际到达时间。"}],
        "tags": ["mixed_format", "distributed_condition", "numeric_scope"],
        "facts": ["东门常态耗时较短", "东门在 8:00 到 9:00 有拥堵限制", "北门常态耗时 24 分钟", "冷链运输上限为 25 分钟", "表中没有当天实时路况"],
    },
    {
        "topic": "retry-backoff-code", "genre": "code_tutorial", "terms": ["退避等待", "最大重试"],
        "request": "保留 Python，同行对齐注释并解释重试边界和运行方式",
        "source": {"material_type": "code", "content": "def fetch(call, waits=(1, 2, 4)):\n    for delay in waits:\n        result = call()\n        if result.ok:\n            return result\n        time.sleep(delay)\n    raise RuntimeError('failed')"},
        "references": [{"id": "REF-001", "content": "waits 中每个值是失败后等待秒数；函数最多调用 call 三次；仅 result.ok 为真时返回。"}],
        "tags": ["mixed_format", "distributed_condition", "negation_exception"],
        "facts": ["默认等待序列是 1、2、4 秒", "每轮先调用再判断结果", "成功时立即返回", "三次均失败才抛出异常", "代码没有区分可重试与不可重试错误"],
    },
    {
        "topic": "cooling-alarm-runbook", "genre": "multi_turn_operation", "terms": ["冷却告警", "旁路阀"],
        "request": "合并多轮指令，明确最新要求和被覆盖的旧要求",
        "source": {"material_type": "multi_turn", "content": ["初始：告警后先关主机，5 分钟后检查温度", "修正：不要关主机，先把负载降到 40%", "最新：若温度超过 78°C，立即关主机；否则降载到 40%，10 分钟后复查；不得开启旁路阀"]},
        "references": [], "tags": ["correction_turn", "distributed_condition", "numeric_scope", "urgency_or_emotion", "negation_exception"],
        "facts": ["最新要求按 78°C 分支处理", "超过阈值时立即关主机", "未超过阈值时降载到 40%", "复查等待时间已改为 10 分钟", "旁路阀禁止开启", "旧的统一关机与 5 分钟要求已经失效"],
    },
    {
        "topic": "sensor-api-fields", "genre": "api_reference", "terms": ["sample_age_ms", "quality_flag"],
        "request": "改写为技术人员可查阅的字段参考，保留单位和空值语义",
        "source": {"material_type": "text", "content": "payload: value number; sample_age_ms integer; quality_flag ok|stale|missing; value=null only when quality_flag=missing. sample_age_ms is measured when the response is created, not when the client reads it."},
        "references": [{"id": "REF-001", "content": "stale 表示样本超过设备配置的时效阈值；接口材料没有提供该阈值的具体毫秒数。"}],
        "tags": ["mixed_format", "distributed_condition", "negation_exception"],
        "facts": ["value 是数值或受条件约束的空值", "sample_age_ms 的单位为毫秒", "quality_flag 有 ok、stale、missing 三种", "只有 missing 时 value 才能为空", "样本年龄在服务端创建响应时计算", "材料没有给出 stale 的固定阈值"],
    },
    {
        "topic": "museum-humidity-incident", "genre": "incident_explanation", "terms": ["相对湿度", "采样缺口"],
        "request": "完整翻译事故说明，并区分原文事实、来源冲突和补充解释",
        "source": {"material_type": "text", "content": "Gallery B exceeded 60% relative humidity from 14:10 to 14:28 according to the wall logger. The portable meter recorded 58% at 14:20. No portable reading exists for the beginning or end of the interval. The door alarm was inactive, but this does not prove the door stayed closed."},
        "references": [{"id": "REF-001", "content": "墙面记录器连续采样，便携表只有单点记录；两种来源校准日期不同，现有材料没有指定哪一来源优先。"}],
        "tags": ["conflicting_sources", "distributed_condition", "numeric_scope", "negation_exception"],
        "facts": ["墙面记录器报告 14:10 至 14:28 超过 60%", "便携表只在 14:20 记录 58%", "区间起止没有便携表读数", "门禁告警未激活不等于门必然关闭", "两个仪表的校准日期不同", "来源优先级尚未确定"],
    },
    {
        "topic": "database-cutover-choice", "genre": "migration_decision", "terms": ["双写窗口", "回退点"],
        "request": "从零解释迁移选项并给出有条件建议，不隐藏冲突证据",
        "source": {"material_type": "text", "content": "方案甲在周六 01:00 停写 35 分钟，验证完成后切换；方案乙连续双写 48 小时，不停写，但现有监控不能自动发现两端字段级差异。运维估计甲回退需 12 分钟，开发记录显示上次演练用了 19 分钟。业务要求任何单次不可写不超过 20 分钟。回退脚本只在测试库验证过。"},
        "references": [{"id": "REF-OPS", "content": "运维估计来源于本周会议纪要。"}, {"id": "REF-DEV", "content": "19 分钟来自上次完整演练日志，时间包含连接重新建立。"}],
        "tags": ["conflicting_sources", "distributed_condition", "numeric_scope", "urgency_or_emotion"],
        "facts": ["方案甲计划停写 35 分钟", "业务上限是不超过 20 分钟", "方案乙双写 48 小时", "现有监控无法自动发现字段级差异", "回退时间有 12 与 19 分钟两种来源", "回退脚本尚未在生产库验证"],
    },
    {
        "topic": "laboratory-chain-audit", "genre": "custody_audit", "terms": ["交接链", "封签编号"],
        "request": "压缩为审核者可复核的结论，保留异常、例外和证据缺口",
        "source": {"material_type": "text", "content": "样品 S-17 在登记表中于 09:42 由林交给周，封签编号 A184。冰箱日志显示 09:45 开门，09:48 关门。摄像记录从 09:43 到 09:47 缺失。周的接收签名时间是 09:50。程序要求交接双方在同一分钟签名，但停电期间可在恢复供电后 15 分钟内补签；值班表称 09:40 到 09:46 停电，UPS 日志称 09:41 到 09:44。现有材料没有说明哪个停电记录优先。样品温度贴纸显示 4°C，但贴纸没有校准日期。"},
        "references": [{"id": "REF-PROC", "content": "交接程序第 4 条：通常双方同分钟签名；停电例外需要在恢复后 15 分钟内补签并注明原因。"}],
        "tags": ["conflicting_sources", "noisy_input", "distributed_condition", "numeric_scope", "negation_exception"],
        "facts": ["登记交接时间为 09:42", "接收签名时间为 09:50", "停电记录的起止时间互相冲突", "程序存在停电补签例外", "摄像记录缺失覆盖部分交接时段", "4°C 贴纸缺少校准日期", "不能仅凭当前材料判定交接合规"],
    },
    {
        "topic": "cache-invalidation-tutorial", "genre": "systems_tutorial", "terms": ["缓存键", "失效广播"],
        "request": "根据事实写长教程，解释正常路径、失败路径、例外和排查顺序",
        "source": {"material_type": "none", "content": ""},
        "references": [{"id": "REF-ARCH", "content": "写入服务提交数据库后发布失效广播；边缘节点按缓存键删除副本。广播最多重试 3 次，每次间隔 5 秒。节点离线时可能错过广播，但缓存最长 10 分钟自动过期。管理员可以按租户清除，不能按单个用户清除。监控只统计成功接收广播的在线节点。"}],
        "tags": ["distributed_condition", "mixed_format", "numeric_scope", "negation_exception"],
        "facts": ["数据库提交发生在广播之前", "边缘节点按缓存键失效", "广播最多重试 3 次", "每次重试间隔 5 秒", "离线节点可能错过广播", "缓存最长 10 分钟自动过期", "人工清除粒度是租户而不是用户", "监控统计不覆盖离线节点"],
    },
    {
        "topic": "release-readiness-status", "genre": "release_status", "terms": ["阻断项", "条件通过"],
        "request": "只整理为发布状态页，保留原句、负责人空缺和条件关系",
        "source": {"material_type": "text", "content": "发布候选 4.8.0  构建 218  时间 16:20  已完成 单元测试 684/684  数据迁移演练 2/2  条件通过 Android 14 冒烟 12/12 但仅覆盖 Pixel 设备  阻断项 支付回调重放测试未完成 负责人未定  风险 客服脚本仍写旧退款时限 48 小时 实际新规则 72 小时  决定 未解决阻断项不得发布  紧急说明 市场活动明早 9:00 开始 这不是跳过门禁的例外"},
        "references": [],
        "tags": ["noisy_input", "distributed_condition", "numeric_scope", "urgency_or_emotion", "negation_exception"],
        "facts": ["候选版本为 4.8.0 构建 218", "单元测试 684/684", "迁移演练 2/2", "Android 冒烟只覆盖 Pixel", "支付回调重放测试尚未完成", "阻断项负责人未定", "客服脚本时限仍为 48 小时", "实际新规则是 72 小时", "市场活动不构成跳过门禁的例外"],
    },
    {
        "topic": "solar-combiner-diagram", "genre": "diagram_reference", "terms": ["汇流箱", "隔离开关"],
        "request": "保留图并写成技术参考，逐项绑定标注、条件、异常和证据边界",
        "source": {"material_type": "image", "content": {"path": "assets/solar-combiner.svg", "alt": "光伏组串、汇流箱与隔离开关示意图"}},
        "references": [{"id": "REF-DESIGN", "content": "图示 3 路组串进入 CB-2 汇流箱，再经 DS-1 直流隔离开关到逆变器。每路标注 12 A 是设计最大电流，不是现场读数。F2 标红表示图纸修订时待确认，不等于保险已经熔断。只有 DS-1 断开且验电为零后才允许打开汇流箱；紧急消防处置另按现场消防程序执行。图纸版本 D3，未附电缆长度、压降计算、设备序列号或现场照片。"}],
        "tags": ["mixed_format", "distributed_condition", "numeric_scope", "negation_exception"],
        "facts": ["三路组串汇入 CB-2", "DS-1 位于汇流箱与逆变器之间", "12 A 是设计上限而非实测", "F2 标红是待确认标记", "开箱需要断开并验电为零", "消防处置按独立程序", "图纸版本为 D3", "图中缺少压降和现场状态证据"],
    },
    {
        "topic": "fermentation-trial-table", "genre": "experiment_explanation", "terms": ["接种批次", "终点酸度"],
        "request": "保留长表，解释分组、异常值、缺失项、来源冲突和可下结论的范围",
        "source": {"material_type": "table", "content": "| 批次 | 温度 | 24h pH | 48h pH | 终点酸度 | 备注 |\n|---|---:|---:|---:|---:|---|\n| A1 | 30°C | 5.2 | 4.6 | 0.71% | 正常 |\n| A2 | 30°C | 5.1 | 4.5 | 0.74% | 正常 |\n| B1 | 34°C | 5.0 | — | 0.82% | 记录器离线 |\n| B2 | 34°C | 5.0 | 4.2 | 0.80% | 取样晚 18 分钟 |"},
        "references": [{"id": "REF-LAB", "content": "实验记录称各批次使用同一接种母液；库存系统却把 B2 记为下一接种批次。负责人尚未签署更正。破折号表示没有 48 小时读数，不代表 pH 为零。终点酸度由另一台仪器测得，该仪器校准在试验前 6 天完成。方案只预先定义比较 30°C 与 34°C 两组平均终点酸度，没有预先定义排除 B2。样本每组只有两个，不能据此概括全部生产批次。"}],
        "tags": ["conflicting_sources", "noisy_input", "mixed_format", "distributed_condition", "numeric_scope", "negation_exception"],
        "facts": ["两组温度分别为 30°C 与 34°C", "B1 缺少 48 小时 pH", "B2 取样晚 18 分钟", "B2 接种批次来源冲突", "终点酸度仪器校准早于试验 6 天", "方案未预定义排除 B2", "每组只有两个样本", "结论不能外推到全部生产"],
    },
    {
        "topic": "tenant-quota-code", "genre": "code_decision", "terms": ["软配额", "突发额度"],
        "request": "保留代码并同行对齐注释，为决策者解释行为、边界、风险和可选修改",
        "source": {"material_type": "code", "content": "def permit(used, soft_limit, burst, is_admin):\n    ceiling = soft_limit + burst\n    if used < soft_limit:\n        return True, 'normal'\n    if is_admin and used < ceiling:\n        return True, 'burst'\n    return False, 'blocked'"},
        "references": [{"id": "REF-POLICY", "content": "soft_limit 是租户常规额度；burst 是只供管理员请求临时使用的附加额度。used 等于 soft_limit 时普通请求被拒绝。used 等于 ceiling 时管理员请求也被拒绝。代码没有检查负数、整数溢出或租户身份，调用方负责这些校验。产品文档旧版称所有用户都可使用突发额度，新版变更单明确只允许管理员；变更单优先。监控按返回标签 normal、burst、blocked 计数，不记录输入值。"}],
        "tags": ["conflicting_sources", "mixed_format", "distributed_condition", "numeric_scope", "negation_exception"],
        "facts": ["ceiling 等于常规额度加突发额度", "普通路径使用严格小于 soft_limit", "管理员突发路径使用严格小于 ceiling", "等于边界时会拒绝", "调用方负责输入合法性", "新版变更单优先于旧产品文档", "监控只记录结果标签", "代码本身不识别租户"],
    },
    {
        "topic": "retention-policy-audit", "genre": "policy_audit", "terms": ["法律保留", "删除队列"],
        "request": "合并多轮政策材料，形成可审计说明；指出失效旧要求、冲突来源和证据缺口",
        "source": {"material_type": "multi_turn", "content": ["初版：普通导出文件保留 30 天，之后进入删除队列；法律保留对象不删除。", "修订一：普通导出改为 14 天；已经创建的文件仍按 30 天。", "修订二：安全事件导出保留 90 天；若同时属于法律保留，以法律保留为准。", "最新澄清：14 天规则从 2026-10-01 00:00 UTC 创建的文件开始；删除队列每 6 小时执行，进入队列不代表已经物理删除。"]},
        "references": [{"id": "REF-CONFIG", "content": "生产配置快照仍显示 default_days=30、security_days=90，快照时间为 2026-09-30 22:00 UTC。"}, {"id": "REF-TICKET", "content": "部署工单计划在 2026-10-01 00:00 UTC 将 default_days 改为 14；现无部署完成日志。"}],
        "tags": ["correction_turn", "conflicting_sources", "noisy_input", "distributed_condition", "mixed_format", "numeric_scope", "negation_exception", "urgency_or_emotion"],
        "facts": ["普通导出新规则是 14 天", "规则只适用于指定生效时间后创建的文件", "既有文件保持 30 天", "安全事件导出保留 90 天", "法律保留优先且不删除", "删除队列每 6 小时执行", "入队不等于物理删除", "配置快照早于计划切换", "缺少部署完成日志", "不能声称 14 天配置已经生效"],
    },
]


def source_digest(content: Any) -> str:
    serialized = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def material_text(source: dict[str, Any]) -> str:
    content = source["content"]
    if source["material_type"] == "image":
        return str(content["alt"])
    if isinstance(content, list):
        return "".join(str(item) for item in content)
    return str(content)


def input_char_count(case: dict[str, Any]) -> int:
    return len(case["request"]) + len(material_text(case["source"])) + sum(len(item["content"]) for item in case["references"])


def extend_to_target(case: dict[str, Any], target: int) -> None:
    """Add topic-specific audit material until the selected real length band is reached."""

    if input_char_count(case) >= target:
        return
    sections: list[str] = []
    cycle = 0
    dimensions = ["事实归属", "条件边界", "数值范围", "例外处理", "来源状态", "可验证结论", "不可外推内容", "复核提示"]
    while input_char_count(case) + len("".join(sections)) < target:
        fact = case["facts"][cycle % len(case["facts"])]
        dimension = dimensions[cycle % len(dimensions)]
        sections.append(f"核对段{cycle + 1}（{dimension}）：{fact}；本段只支持这项陈述，不能替代其他段落的条件或证据。")
        cycle += 1
    appendix = "".join(sections)
    if case["references"]:
        case["references"].append({"id": "REF-COVERAGE", "content": appendix})
    else:
        case["references"] = [{"id": "REF-COVERAGE", "content": appendix}]


def check_gate() -> None:
    ledger = json.loads((ROOT / "evals" / "reviews" / "vnext-1.1-round-5.json").read_text(encoding="utf-8"))["review_round"]
    if ledger["review_result"] != {"reviewed": 5, "accepted": 5, "rejected": 0, "new_candidates": 0, "automated_checks_are_user_acceptance": False}:
        raise SystemExit("round 2 is gated until all five round-5 candidates are explicitly accepted")
    if ledger["post_review_counts"]["combined"] != {"gold": 32, "rejected": 30, "candidate": 0, "total": 62}:
        raise SystemExit("round-5 lifecycle counts do not permit round 2")


def main() -> int:
    check_gate()
    if len(CASES) != 20 or len(SLOTS) != 20:
        raise SystemExit("round 2 must contain exactly 20 cases and slots")
    output: list[dict[str, Any]] = []
    for index, raw in enumerate(CASES, start=1):
        case = json.loads(json.dumps(raw, ensure_ascii=False))
        active_index = index + 20
        case["references"].append({"id": "REF-RESTART", "content": f"复核编号 B{active_index}，须保留"})
        facts = case.pop("facts")
        case["facts"] = facts
        extend_to_target(case, TARGET_COUNTS[LENGTHS[index - 1]])
        case.pop("facts")
        operation, augmentation, components = SLOTS[index - 1]
        item = {
            "case_id": f"FWD-R2-{active_index:03d}", "round": 2,
            "base_operation": operation, "augmentation": augmentation,
            "genre": case["genre"], "audience": AUDIENCES[index - 1],
            "content_task": TASKS[index - 1], "length_class": LENGTHS[index - 1],
            "topic_id": f"TOPIC-R2-{active_index:03d}", "core_terms": case["terms"],
            "variation_tags": case["tags"], "components": components,
            "request": case["request"], "source": case["source"], "references": case["references"],
        }
        item["source"] = dict(item["source"])
        item["source"]["sha256"] = source_digest(item["source"]["content"])
        item["input_char_count"] = input_char_count(item)
        low, high = RANGES[item["length_class"]]
        if not low <= item["input_char_count"] <= high:
            raise SystemExit(f"{item['case_id']} has {item['input_char_count']} chars outside {low}-{high}")
        output.append(item)

    if Counter(item["content_task"] for item in output) != Counter({"tutorial": 3, "operation": 3, "reference": 3, "explanation": 3, "decision": 3, "status": 2, "audit": 3}):
        raise SystemExit("round-2 content-task distribution differs")
    if any(value != 4 for value in Counter(item["audience"] for item in output).values()):
        raise SystemExit("round-2 audience distribution differs")
    if any(value != 4 for value in Counter(item["length_class"] for item in output).values()):
        raise SystemExit("round-2 length distribution differs")
    quotas = {"distributed_condition": 4, "conflicting_sources": 2, "noisy_input": 3, "mixed_format": 4, "correction_turn": 2, "numeric_scope": 3, "negation_exception": 3, "urgency_or_emotion": 2}
    observed = Counter(tag for item in output for tag in item["variation_tags"])
    missing = {tag: minimum for tag, minimum in quotas.items() if observed[tag] < minimum}
    if missing:
        raise SystemExit(f"round-2 variation quotas are incomplete: {missing}")
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text("".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in output), encoding="utf-8", newline="\n")
    print(json.dumps({"status": "PASS", "round": 2, "requests": 20, "lengths": Counter(item["length_class"] for item in output), "audiences": Counter(item["audience"] for item in output), "tasks": Counter(item["content_task"] for item in output), "variations": observed}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
