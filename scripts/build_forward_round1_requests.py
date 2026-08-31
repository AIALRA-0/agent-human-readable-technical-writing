"""Build 20 source-diverse round-one forward requests without expected answers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "evals" / "forward" / "round-1" / "requests.jsonl"


def source_digest(content: Any) -> str:
    """Hash source content with stable JSON encoding for structured values."""

    serialized = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


CASES: list[dict[str, Any]] = [
    {
        "base_operation": "TRANSFORM", "augmentation": "NONE", "genre": "status", "components": ["TEXT"],
        "request": "把状态说明改得清楚自然，不增加任何新事实",
        "source": {"material_type": "text", "content": "本次同步发现 7 个文件。由于目标目录没有写入权限，复制尚未开始。请保留源文件，管理员修复权限后再执行同步。"}, "references": [],
    },
    {
        "base_operation": "TRANSLATE", "augmentation": "GLOSS", "genre": "safety_notice", "components": ["TEXT"],
        "request": "翻译成零基础读者能直接执行的中文，并就近解释陌生术语",
        "source": {"material_type": "text", "content": "Disconnect the appliance from mains power before removing the rear panel. The capacitor may retain a hazardous charge for five minutes after disconnection."},
        "references": [{"id": "REF-001", "content": "mains power 指建筑供电线路提供的市电；capacitor 是能够暂时储存电荷的电容器"}],
    },
    {
        "base_operation": "COMPRESS", "augmentation": "NONE", "genre": "project_update", "components": ["TEXT"],
        "request": "压缩成一段项目进展，保留每个数字、未完成项和下一步",
        "source": {"material_type": "text", "content": "团队检查了 42 个页面，其中 39 个页面显示正常，3 个页面的移动端导航遮挡正文。桌面端没有发现遮挡。修复尚未部署。下一步是在 360 像素和 390 像素宽度下复测这 3 个页面。"}, "references": [],
    },
    {
        "base_operation": "EXPLAIN", "augmentation": "TEACHING", "genre": "science_tutorial", "components": ["TEXT"],
        "request": "从零开始解释为什么保温杯不能让热水永远保持原温，并说明三种热量传递方式",
        "source": {"material_type": "text", "content": "保温杯通过真空夹层减少传导和对流，通过反射层减少辐射；杯盖、杯口和密封结构仍会让热量逐渐散失。"},
        "references": [{"id": "REF-001", "content": "热传导通过物质内部接触传递能量；对流依靠流体运动传递能量；热辐射以电磁波形式传递能量"}],
    },
    {
        "base_operation": "GENERATE", "augmentation": "GLOSS", "genre": "setup_guide", "components": ["TEXT"],
        "request": "根据给定事实写一份蓝牙温度计首次配对说明，读者没有使用经验",
        "source": {"material_type": "none", "content": ""},
        "references": [{"id": "REF-001", "content": "长按设备侧键 3 秒进入配对；指示灯蓝色闪烁；手机系统设置中选择 Thermo Mini；连接成功后指示灯常亮 5 秒；若 60 秒内未连接，设备退出配对"}],
    },
    {
        "base_operation": "FORMAT_ONLY", "augmentation": "NONE", "genre": "maintenance_schedule", "components": ["TEXT"],
        "request": "只整理层级和版式，不改变任何文字、日期或负责人",
        "source": {"material_type": "text", "content": "设备维护 9月2日 清洁滤网 负责人林青 9月4日 检查皮带 负责人周川 9月6日 记录噪声 负责人林青 注意 停机后才能打开护罩"}, "references": [],
    },
    {
        "base_operation": "EXPLAIN", "augmentation": "EXPLANATORY", "genre": "image_explanation", "components": ["IMAGE", "TEXT"],
        "request": "保留原图，从零解释图中每个有效元素、连接方向、控制结果和图中不能证明的内容",
        "source": {"material_type": "image", "content": {"path": "assets/greenhouse-control.svg", "alt": "温室灌溉控制图"}},
        "references": [{"id": "REF-001", "content": "图中的 35% 是控制器比较土壤湿度时使用的阈值；图没有提供传感器误差、水泵流量或实际种植结果"}],
    },
    {
        "base_operation": "EXPLAIN", "augmentation": "GLOSS", "genre": "table_explanation", "components": ["TABLE", "TEXT"],
        "request": "保留原表，先解释列和值，再说明比较结论、缺失证据和下一步",
        "source": {"material_type": "table", "content": "| 模式 | 每次保存内容 | 恢复速度 | 额外存储 |\n|---|---|---|---|\n| 完整备份 | 全部文件 | 快 | 高 |\n| 增量备份 | 上次任意备份后变化的文件 | 较慢 | 低 |\n| 差异备份 | 上次完整备份后变化的文件 | 中等 | 中等 |"},
        "references": [{"id": "REF-001", "content": "表格没有给出文件数量、设备速度、保存周期或故障恢复实测数据"}],
    },
    {
        "base_operation": "EXPLAIN", "augmentation": "TEACHING", "genre": "code_explanation", "components": ["CODE", "TEXT"],
        "request": "保留原始 Python 代码，逐步解释输入、循环、条件、输出、运行方法和证据边界",
        "source": {"material_type": "code", "content": "def count_large(values, limit):\n    total = 0\n    for value in values:\n        if value > limit:\n            total += 1\n    return total"},
        "references": [{"id": "REF-001", "content": "values 应当是可逐项读取的数值集合；limit 是比较阈值；函数返回严格大于阈值的元素数量"}],
    },
    {
        "base_operation": "TRANSFORM", "augmentation": "GLOSS", "genre": "multi_turn_instruction", "components": ["TEXT"],
        "request": "合并追加要求，写成一份连续说明；后来的要求覆盖冲突的旧要求",
        "source": {"material_type": "multi_turn", "content": ["第一轮：校准前让探头在室温下静置 10 分钟，每次记录 3 个读数", "追加：静置时间改为 15 分钟", "追加：如果 3 个读数的最大差值超过 0.4 摄氏度，就重新连接探头并再次测量"]}, "references": [],
    },
    {
        "base_operation": "TRANSFORM", "augmentation": "EXPLANATORY", "genre": "access_policy", "components": ["TEXT"],
        "request": "改写成普通员工能理解的访问规则，完整保留条件、例外和期限",
        "source": {"material_type": "text", "content": "访客通行证仅在接待人员在场时有效。临时离开楼层不需要归还，但超过 30 分钟必须重新登记。消防疏散期间不执行重新登记要求。"}, "references": [],
    },
    {
        "base_operation": "TRANSLATE", "augmentation": "EXPLANATORY", "genre": "academic_text", "components": ["TEXT"],
        "request": "完整翻译并补充理解这一地质过程所需的背景，明确区分原文结论和补充解释",
        "source": {"material_type": "text", "content": "The dated ash layer lies above the fossil bed. It therefore sets a minimum age for the burial event, but it does not establish how long the organisms lived before burial."},
        "references": [{"id": "REF-001", "content": "地层中较高的沉积层通常形成得更晚；火山灰层可以通过适当的同位素方法测年；上覆层的年龄只限制埋藏事件不能晚于该层形成时间"}],
    },
    {
        "base_operation": "EXPLAIN", "augmentation": "TEACHING", "genre": "network_tutorial", "components": ["TEXT"],
        "request": "从零解释域名查询中的缓存有效期为什么会影响修改生效速度",
        "source": {"material_type": "text", "content": "解析服务会在缓存有效期内复用已有地址记录。记录到期后，解析服务才需要重新查询权威来源。不同解析服务的缓存开始时间可能不同。"},
        "references": [{"id": "REF-001", "content": "缓存有效期常用 TTL 表示；它规定记录可以被复用多长时间，不承诺所有缓存会在同一时刻到期"}],
    },
    {
        "base_operation": "COMPRESS", "augmentation": "GLOSS", "genre": "privacy_notice", "components": ["TEXT"],
        "request": "压缩成易读的隐私说明，保留收集内容、用途、保存期限和删除例外",
        "source": {"material_type": "text", "content": "应用收集崩溃时间、设备型号和软件版本，用于定位稳定性问题。记录保存 30 天后自动清除。若记录已经进入正在进行的安全调查，保存期限延长到调查结束后 7 天。应用不收集文档正文。"}, "references": [],
    },
    {
        "base_operation": "GENERATE", "augmentation": "EXPLANATORY", "genre": "troubleshooting", "components": ["TEXT"],
        "request": "根据事实写一份电子书无法同步阅读位置时的排查说明，解释每一步为什么做和会看到什么",
        "source": {"material_type": "none", "content": ""},
        "references": [{"id": "REF-001", "content": "先确认两台设备登录同一账号；再确认阅读位置同步开关开启；手动同步后等待 20 秒；仍无变化时记录书名、设备型号和应用版本；重新安装会删除未同步的本地标注，因此不能作为首选步骤"}],
    },
    {
        "base_operation": "FORMAT_ONLY", "augmentation": "NONE", "genre": "meeting_record", "components": ["TEXT"],
        "request": "只整理标题、分组和缩进；禁止改写结论或补充缺失负责人",
        "source": {"material_type": "text", "content": "评审记录 结论 保留旧接口到10月15日 新接口10月1日开放 兼容性 安卓12已验证 安卓11未验证 后续 安卓11测试负责人未确定 文档由陈澄9月28日前更新"}, "references": [],
    },
    {
        "base_operation": "EXPLAIN", "augmentation": "EXPLANATORY", "genre": "image_explanation", "components": ["IMAGE", "TEXT"],
        "request": "保留原图，解释坐标、警戒线、每个数据点、趋势、异常、实际影响和证据边界",
        "source": {"material_type": "image", "content": {"path": "assets/river-gauge.svg", "alt": "河流水位变化图"}},
        "references": [{"id": "REF-001", "content": "警戒线表示需要加强监测的阈值，不等于必然发生洪水；图中没有降雨量、流速、堤防状态或预测模型"}],
    },
    {
        "base_operation": "EXPLAIN", "augmentation": "GLOSS", "genre": "experiment_table", "components": ["TABLE", "TEXT"],
        "request": "保留原表，解释列、行、缺失值和变化趋势，不逐格机械复述",
        "source": {"material_type": "table", "content": "| 样品 | 20 分钟 | 40 分钟 | 60 分钟 |\n|---|---:|---:|---:|\n| A | 22.1°C | 24.8°C | 26.0°C |\n| B | 22.0°C | — | 25.1°C |\n| C | 22.2°C | 23.0°C | 23.4°C |"},
        "references": [{"id": "REF-001", "content": "破折号表示该时间点没有记录，不等于温度为零；表格没有给出加热功率、环境温度误差或重复实验次数"}],
    },
    {
        "base_operation": "EXPLAIN", "augmentation": "TEACHING", "genre": "code_explanation", "components": ["CODE", "TEXT"],
        "request": "保留原始 SQL，解释查询目标、每一行、筛选条件、排序结果、执行方式和副作用",
        "source": {"material_type": "code", "content": "SELECT title, due_date\nFROM loans\nWHERE returned_at IS NULL\nORDER BY due_date ASC;"},
        "references": [{"id": "REF-001", "content": "loans 表保存借阅记录；returned_at 为空表示尚未归还；查询只读取 title 和 due_date，不修改数据"}],
    },
    {
        "base_operation": "TRANSFORM", "augmentation": "GLOSS", "genre": "multi_turn_schedule", "components": ["TEXT"],
        "request": "合并三轮信息，按时间顺序写成展柜维护安排，并明确撤销的旧要求",
        "source": {"material_type": "multi_turn", "content": ["第一轮：周二闭馆后更换 2 号展柜照明，完成后拍照", "追加：更换改到周三开馆前，照片仍然需要", "撤销：本周不更换照明，只在周三开馆前检查亮度并记录读数"]}, "references": [],
    },
]


def main() -> int:
    """Write requests with stable identifiers and source digests."""

    if len(CASES) != 20:
        raise SystemExit(f"expected 20 cases, found {len(CASES)}")
    output = []
    for index, case in enumerate(CASES, start=1):
        item = dict(case)
        item.update({"case_id": f"FWD-R1-{index:03d}", "round": 1, "audience": "zero_prior_knowledge"})
        item["source"] = dict(item["source"])
        item["source"]["sha256"] = source_digest(item["source"]["content"])
        output.append(item)
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text("".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in output), encoding="utf-8", newline="\n")
    print(json.dumps({"status": "PASS", "requests": len(output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
