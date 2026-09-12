"""Build the reviewable examples for the top-level format rule layer."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RULES_PATH = ROOT / "references" / "format-rules.md"
OUT_DIR = ROOT / "evals" / "candidate" / "format-layer"


def align_inline_comments(lines: list[tuple[str, str]]) -> str:
    """Align comment markers at L+2 for one code block."""
    width = max(len(code.expandtabs(4)) for code, _ in lines)
    rendered = []
    for code, comment in lines:
        padding = " " * (width - len(code.expandtabs(4)) + 1)
        rendered.append(f"{code}{padding}# {comment}")
    return "\n".join(rendered)


def cases() -> list[dict[str, object]]:
    aligned = align_inline_comments(
        [
            ("records = load_records(path)", "读取记录"),
            ("for record in records:", "逐条处理"),
            ("    result = normalize(record)", "规范化记录"),
            ("    save(result)", "保存结果"),
        ]
    )
    return [
        {
            "id": "FMT-CASE-001",
            "title": "短段落的中文句号与句末标点",
            "rules": ["FMT-009", "FMT-011", "FMT-015", "FMT-017", "FMT-018", "FMT-019"],
            "request": "把短说明改成符合顶层格式的正文",
            "input": "配置文件缺失。加载因此无法完成。要重新提供文件吗？",
            "output": "配置文件缺失；加载因此无法完成\n\n要重新提供文件吗？",
        },
        {
            "id": "FMT-CASE-002",
            "title": "长段落直接换行",
            "rules": ["FMT-010", "FMT-012", "FMT-016", "FMT-023"],
            "request": "保留长说明的全部信息，并把过长句群改成可读区块",
            "input": "系统先读取配置并确认运行环境。随后按照配置选择数据源、检查字段、记录缺失值、保留原始顺序、识别冲突条件、核对时间范围和数值单位。完成这些检查后，系统才生成结果。",
            "output": "系统依次完成以下操作\n\n1. 读取配置\n2. 确认运行环境\n3. 按照配置选择数据源\n4. 检查字段\n5. 记录缺失值\n6. 保留原始顺序\n7. 识别冲突条件\n8. 核对时间范围\n9. 核对数值单位\n\n完成这些检查后，系统才生成结果",
        },
        {
            "id": "FMT-CASE-003",
            "title": "没有冒号的独立并列项目",
            "rules": ["FMT-020", "FMT-036", "FMT-037", "FMT-038", "FMT-042", "FMT-043"],
            "request": "把并列动作改为分行结构",
            "input": "检查输入，保存原文，标记冲突，生成报告",
            "output": "本次处理包含以下动作\n\n- 检查输入\n- 保存原文\n- 标记冲突\n- 生成报告",
        },
        {
            "id": "FMT-CASE-004",
            "title": "有冒号的嵌套步骤",
            "rules": ["FMT-021", "FMT-036", "FMT-039", "FMT-040", "FMT-041", "FMT-043"],
            "request": "把带有子步骤的操作说明按语义层级排版",
            "input": "请按顺序完成：准备环境，安装依赖并检查版本，运行检查并记录失败项",
            "output": "请按顺序完成：\n\n1. 准备环境\n2. 安装依赖\n   - 检查版本\n3. 运行检查\n   - 记录失败项",
        },
        {
            "id": "FMT-CASE-005",
            "title": "冒号伪标题改为 Markdown 标题",
            "rules": ["FMT-026", "FMT-027", "FMT-029", "FMT-030", "FMT-035"],
            "request": "把多个内容区块整理成真正的标题层级",
            "input": "操作：先备份文件\n术语：工作树是当前文件目录\n证据边界：只使用已读取的记录",
            "output": "## 操作\n\n先备份文件\n\n## 术语\n\n工作树是当前文件目录\n\n## 证据范围\n\n只使用已读取的记录",
        },
        {
            "id": "FMT-CASE-006",
            "title": "单块省略标题与多区块对称标题",
            "rules": ["FMT-026", "FMT-031", "FMT-032", "FMT-033", "FMT-034"],
            "request": "单个连续语义块不强制标题，多项独立内容都使用同级标题，并沿用无编号标题体系",
            "input": "短内容：文件已保存\n\n多主题内容：已完成读取与校验，远端状态未确认，下一步读取远端提交并复核差异",
            "output": "文件已保存\n\n## 当前状态\n\n已完成读取与校验\n\n## 风险\n\n仍需确认远端状态\n\n## 下一步\n\n读取远端提交并复核差异",
        },
        {
            "id": "FMT-CASE-007",
            "title": "主题分段与列表空白",
            "rules": ["FMT-023", "FMT-024", "FMT-025", "FMT-028"],
            "request": "分开无关主题，并删除列表内部的空白",
            "input": "状态：已完成读取\n\n步骤：\n- 读取配置\n\n- 检查文件\n\n风险：远端结果未确认",
            "output": "## 状态\n\n已完成读取\n\n## 步骤\n\n- 读取配置\n- 检查文件\n\n## 风险\n\n远端结果未确认",
        },
        {
            "id": "FMT-CASE-008",
            "title": "中英文混排与可读空格",
            "rules": ["FMT-044", "FMT-045", "FMT-046", "FMT-047", "FMT-049"],
            "request": "修正独立英文和中英文之间的间距",
            "input": "使用 API 连接Dashboard，再检查JSON文件",
            "output": "使用 API 应用程序接口（Application Programming Interface）连接控制面板（Dashboard），再检查 JSON JavaScript 对象表示法（JavaScript Object Notation）文件",
        },
        {
            "id": "FMT-CASE-009",
            "title": "普通英文大小写与官方名称",
            "rules": ["FMT-048", "FMT-050", "FMT-062", "FMT-063", "FMT-064", "FMT-065", "FMT-066", "FMT-121"],
            "request": "修正普通英文名称的大小写，保留官方专名，并把中文别名移到英文括号外",
            "input": "使用 cloud storage 和 github Actions，连接 PostgreSQL；材料确认解析布局的官方英文为 Layout Resolution，中文别名为布局解析，原稿写成解析布局（Layout Resolution，也称 布局解析）",
            "output": "使用云存储（Cloud Storage）和 GitHub 自动化工作流（GitHub Actions），连接数据库系统（PostgreSQL）\n\n解析布局（Layout Resolution），中文别名为“布局解析”",
        },
        {
            "id": "FMT-CASE-010",
            "title": "专业术语首次定义",
            "rules": ["FMT-052", "FMT-054", "FMT-055", "FMT-056", "FMT-057", "FMT-059"],
            "request": "按完整术语定义合同说明首次出现的专业概念",
            "input": "材料说明：队列英文为 Queue，保存待处理项目，从一端加入，从另一端取出；本例先到先处理，不按重要性插队",
            "output": "- 队列（Queue）：它是保存等待处理项目的一种排列，作用是让项目按到达顺序等候；加入时把新项目放在末尾，处理时取出最前面的项目，例如先放入甲再放入乙，就先处理甲；它适用于本例中先到先处理的安排，不表示紧急项目可以自动插队",
        },
        {
            "id": "FMT-CASE-011",
            "title": "带缩写术语与定义内部术语",
            "rules": ["FMT-053", "FMT-055", "FMT-056", "FMT-058", "FMT-060"],
            "request": "按缩写格式定义一个首次出现的专业协议，并在定义内部保持术语全称",
            "input": "材料说明：FIFO 的全称是 First In First Out，中文为先进先出，它是一种先加入先取出的处理顺序；例子为先放入甲再放入乙，先取出甲，不按紧急程度排序",
            "output": "- FIFO 先进先出（First In First Out）：它是一种先加入的项目先取出的处理顺序，用于让等待项目按到达次序得到处理；处理时从最早加入的项目开始，例如甲先加入、乙后加入，就先取出甲；它适用于按先后顺序处理的场景，不等于按紧急程度决定谁先处理",
        },
        {
            "id": "FMT-CASE-012",
            "title": "英文不能单独出现在普通正文",
            "rules": ["FMT-044", "FMT-045", "FMT-046", "FMT-048", "FMT-051", "FMT-061"],
            "request": "把普通正文中的独立英文改成中文与英文配对形式",
            "input": "Agent 读取 README 后调用 API，并把结果写入 Dashboard",
            "output": "智能代理（Agent）读取项目说明文件（README），调用 API 应用程序接口（Application Programming Interface），并把结果写入控制面板（Dashboard）\n\n未确认官方英文名的术语只保留自然中文，不自行创造英文形式",
        },
        {
            "id": "FMT-CASE-013",
            "title": "LaTeX 公式的由浅入深解释",
            "rules": ["FMT-067", "FMT-068", "FMT-069", "FMT-070", "FMT-071"],
            "request": "保留公式，用相对大标题和一致的小标题解释符号、组分、算例、结果、边界与正式定义",
            "input": "准确率为\\(A = \\frac{c}{n}\\)。其中 c 是正确数量，n 是总数量",
            "output": (
                "## 准确率公式\n\n"
                "这条公式回答的是全部结果中有多少比例判断正确，例如检查 20 项并通过 18 项，准确率就是九成\n\n"
                "$$\nA = \\frac{c}{n}\n$$\n\n"
                "### 每个符号代表什么\n\n"
                "- `$A$` 表示准确率，是最终得到的比例，通常写成 0 到 1 之间的小数或换算成百分比\n"
                "- `$c$` 表示判断正确的数量，是分子，必须来自同一批被检查项目\n"
                "- `$n$` 表示全部被检查项目的数量，是分母，并且必须大于零\n\n"
                "### 公式组分怎样理解\n\n"
                "- `$c / n$` 表示用正确数量除以总数量，把绝对数量换算成可比较的正确比例\n\n"
                "### 代入一个具体例子\n\n"
                "若正确数量为 18，总数量为 20，则 `$A = 18 / 20 = 0.9$`，换算成百分比是 90%\n\n"
                "### 结果怎样理解\n\n"
                "结果越接近 1，表示这批项目中判断正确的比例越高；它只描述所选样本的正确比例，不能单独证明系统在所有场景中同样准确\n\n"
                "### 正式定义\n\n"
                "准确率是同一评估范围内正确判断数量与全部判断数量的比值，定义域要求总数量大于零"
            ),
        },
        {
            "id": "FMT-CASE-014",
            "title": "块级代码头行注释",
            "rules": ["FMT-003", "FMT-072", "FMT-079", "FMT-082"],
            "request": "为一个代码块添加块级说明，并保持可执行代码不变",
            "input": "保留下面的 Python 代码，只增加块级说明",
            "output": (
                "原始代码\n\n```python\nconfig = load_config(path)\nprint(config.enabled_items)\n```\n\n"
                "注释副本\n\n```python\n# 读取配置并输出启用的项目\n"
                "config = load_config(path)\nprint(config.enabled_items)\n```"
            ),
        },
        {
            "id": "FMT-CASE-015",
            "title": "同行注释按代码块独立对齐",
            "rules": ["FMT-073", "FMT-074", "FMT-075", "FMT-076", "FMT-077", "FMT-078", "FMT-079"],
            "request": "为每个可注释语句添加同行说明，纯闭合符不添加机械注释",
            "input": "给下面的代码添加同行注释，并保持注释列一致",
            "output": f"```python\n{aligned}\n```",
        },
        {
            "id": "FMT-CASE-016",
            "title": "JSON 使用逐行解释回退",
            "rules": ["FMT-080", "FMT-081", "FMT-082"],
            "request": "不要向 JSON 添加非法注释，改为逐行说明",
            "input": "解释下面的 JSON，并保持 JSON 原文合法",
            "output": "```json\n{\n  \"name\": \"demo\",\n  \"enabled\": true\n}\n```\n\n逐行说明\n\n- `{`：对象开始\n- `\"name\": \"demo\"`：名称为 demo\n- `\"enabled\": true`：启用状态为 true\n- `}`：对象结束",
        },
        {
            "id": "FMT-CASE-017",
            "title": "图片对象、替代文本与题注",
            "rules": ["FMT-013", "FMT-083", "FMT-084", "FMT-085", "FMT-086", "FMT-087", "FMT-088", "FMT-111", "FMT-112", "FMT-114", "FMT-120"],
            "request": "先保留图片，再补充可观察的图片说明和限制",
            "input": "解释这张流程图，不要凭空推断图中没有显示的机制",
            "output": "<div align=\"center\">\n\n![流程图示意：跨时间点的状态变化](../assets/CANDIDATE-09-clock-crossing.svg)\n\n*图 1：图中可见的流程节点与连接关系*\n\n</div>\n\n图中可以确认节点之间存在连接，并能看到流程的方向；无法从图片本身确认每个节点背后的实现机制，也无法仅凭图片确认运行结果",
        },
        {
            "id": "FMT-CASE-018",
            "title": "表格数据保留与表格外说明",
            "rules": ["FMT-089", "FMT-090", "FMT-091", "FMT-092", "FMT-093", "FMT-094", "FMT-115", "FMT-116", "FMT-117", "FMT-118", "FMT-119", "FMT-120"],
            "request": "保留原表数据，并把用途、字段和限制放在表格外",
            "input": "解释下面的比较表，不新增列，不改数字",
            "output": "<div align=\"center\">\n\n<div style=\"max-width: 100%; overflow-x: auto;\">\n\n| 方案 | 延迟 | 状态 |\n|---|---:|---|\n| A | 10 ms | 可用 |\n| B | 25 ms | 待核对 |\n\n</div>\n\n*表 1：两种方案的原始比较数据*\n\n</div>\n\n这张表用于比较两个方案的延迟和状态\n\n- 方案：比较对象名称\n- 延迟：以 ms 毫秒（millisecond）为单位的测量值\n- 状态：原始记录中的可用性标记\n\n`B` 的状态仍需核对，表格没有说明造成差异的原因",
        },
        {
            "id": "FMT-CASE-019",
            "title": "逐字引用与日志原样保留",
            "rules": ["FMT-003", "FMT-014", "FMT-095", "FMT-096", "FMT-097", "FMT-098", "FMT-099"],
            "request": "保留引用和日志原文，并把解释放在对象外",
            "input": "引用和日志中的句号都不能改写",
            "output": "> 原文：系统在 09:00 完成检查。\n\n```text\n2026-09-07T09:00:00Z check completed.\n```\n\n引用保留了原始中文句号，日志保留了原始英文句号；这些字符属于原样材料，不适用普通正文的标点替换",
        },
        {
            "id": "FMT-CASE-020",
            "title": "Mermaid 与混合媒介的区块顺序",
            "rules": ["FMT-001", "FMT-002", "FMT-004", "FMT-005", "FMT-006", "FMT-007", "FMT-008", "FMT-022", "FMT-100", "FMT-101", "FMT-102", "FMT-103", "FMT-104", "FMT-105", "FMT-106", "FMT-107", "FMT-108", "FMT-109", "FMT-110"],
            "request": "对混合媒介结果执行局部复核，保持原始对象并说明无法修复时的处理",
            "input": "保留流程图、公式和代码，修正说明中的格式错误，不要整段重写",
            "output": "## 处理流程\n\n```mermaid\ngraph TD\n    A[读取材料] --> B[检查格式]\n    B --> C[输出结果]\n```\n\n流程图默认从上到下展示读取、检查和输出三个节点；节点和连接关系保持原样\n\n## 计算关系\n\n结果满足 $R = A / N$，其中\n\n- `$R$` 表示通过比例，是最终结果\n- `$A$` 表示通过检查的项目数，是分子\n- `$N$` 表示全部项目数，是分母，并且必须大于零\n- `$A / N$` 表示用通过数量除以全部数量，把项目数换算成比例\n\n## 代码说明\n\n```python\n# 输出检查结果\nprint(result)\n```\n\n如果局部格式在两轮修复后仍无法安全调整，保留原始对象并继续输出，不重写其他区块",
        },
        {
            "id": "FMT-CASE-021",
            "title": "多图表格的图片单元格居中",
            "rules": ["FMT-113", "FMT-115", "FMT-116", "FMT-117", "FMT-118"],
            "request": "生成一个包含两张图片的对照表，每个图片单元格居中，宽表只在自身容器内滚动",
            "input": "左图是处理前状态，右图是处理后状态",
            "output": "<div align=\"center\">\n\n<div style=\"max-width: 100%; overflow-x: auto;\">\n\n| 处理前 | 处理后 |\n|:---:|:---:|\n| ![处理前状态](before.png) | ![处理后状态](after.png) |\n\n</div>\n\n*表 1：处理前后的图片对照*\n\n</div>",
        },
    ]


def load_rule_ids() -> set[str]:
    text = RULES_PATH.read_text(encoding="utf-8")
    return set(re.findall(r"`(FMT-\d{3})`", text))


def validate_case_coverage(items: list[dict[str, object]], rule_ids: set[str]) -> None:
    covered = {rule for item in items for rule in item["rules"]}
    unknown = sorted(covered - rule_ids)
    missing = sorted(rule_ids - covered)
    if unknown or missing:
        raise SystemExit(
            "format case coverage mismatch: "
            f"unknown={unknown or []}, missing={missing or []}"
        )


def write_outputs(items: list[dict[str, object]]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUT_DIR / "format-cases.json"
    md_path = OUT_DIR / "format-cases.md"
    json_path.write_text(
        json.dumps({"source": RULES_PATH.relative_to(ROOT).as_posix(), "cases": items}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    chunks = [
        "# 顶层格式规则案例",
        "",
        "这些手写片段只演示所登记条款，未由干净助手生成，不是完整文档或行为通过证据，也不代表用户接受",
        "",
        "条款登记覆盖只证明编号存在，完整任务结果须看独立模型测试",
        "",
    ]
    for index, item in enumerate(items, start=1):
        chunks.extend(
            [
                f"## {index}. {item['id']} {item['title']}",
                "",
                f"覆盖规则：{ '、'.join(f'`{rule}`' for rule in item['rules']) }",
                "",
                "### 请求",
                "",
                str(item["request"]),
                "",
                "### 原始输入",
                "",
                str(item["input"]),
                "",
                "### 条款示意片段",
                "",
                str(item["output"]),
                "",
            ]
        )
    md_path.write_text("\n".join(chunks), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="validate source and case coverage without writing")
    args = parser.parse_args()
    items = cases()
    if len(items) != 21:
        raise SystemExit(f"expected 21 cases, got {len(items)}")
    validate_case_coverage(items, load_rule_ids())
    if not args.check:
        write_outputs(items)
    print(f"format fragments: {len(items)}, registered rules: {len({rule for item in items for rule in item['rules']})}; behavioral pass not evaluated")


if __name__ == "__main__":
    main()
