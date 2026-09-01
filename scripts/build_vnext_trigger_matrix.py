"""Build the public 72-case trigger matrix without storing model output."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "evals" / "trigger-matrix" / "vnext-1.1-72-cases.jsonl"

FAMILY_CODES = {
    "code_explanation": "CODE",
    "explanatory_translation": "TRANS",
    "status_audit": "AUDIT",
}
EXPECTATION_CODES = {
    "explicit_trigger": "EXP",
    "implicit_trigger": "IMP",
    "negative_no_trigger": "NEG",
    "rule_adherence": "RULE",
}


def evaluator(kind: str = "activation_only", required: list[str] | None = None, forbidden: list[str] | None = None) -> dict[str, object]:
    """Create one deterministic evaluator declaration."""

    return {"kind": kind, "required_patterns": required or [], "forbidden_patterns": forbidden or []}


def activation_cases(family: str, expectation: str, prompts: list[str], expected: bool) -> list[dict[str, object]]:
    """Create six activation-boundary cases for one family and expectation."""

    return [
        {
            "case_id": f"TRG-{FAMILY_CODES[family]}-{EXPECTATION_CODES[expectation]}-{index:02d}",
            "family": family,
            "expectation": expectation,
            "ordinal": index,
            "prompt": prompt,
            "expected_activation": expected,
            "evaluator": evaluator(),
        }
        for index, prompt in enumerate(prompts, start=1)
    ]


def rule_cases(family: str, rows: list[tuple[str, dict[str, object]]]) -> list[dict[str, object]]:
    """Create six rule-adherence cases for one family."""

    return [
        {
            "case_id": f"TRG-{FAMILY_CODES[family]}-RULE-{index:02d}",
            "family": family,
            "expectation": "rule_adherence",
            "ordinal": index,
            "prompt": prompt,
            "expected_activation": True,
            "evaluator": checks,
        }
        for index, (prompt, checks) in enumerate(rows, start=1)
    ]


def build_cases() -> list[dict[str, object]]:
    """Return three families with 6 explicit, implicit, negative, and rule cases each."""

    cases: list[dict[str, object]] = []
    cases += activation_cases("code_explanation", "explicit_trigger", [
        "使用 $human-readable-technical-writing 给初学者解释 Python 代码 `total = price * count`",
        "调用 human-readable-technical-writing Skill 解释 `enabled = retries < 3` 的作用",
        "按人类可读技术写作规则解释 `items.append(value)`，保留原代码",
        "使用指定写作 Skill 解释 `if ready:\n    start()`，不要扩写业务背景",
        "请让 human-readable-technical-writing 解释 `name = record.get('name')`",
        "用 $human-readable-technical-writing 解释 `result = parse(raw)` 的数据流",
    ], True)
    cases += activation_cases("code_explanation", "implicit_trigger", [
        "给第一次接触 Python 的人解释 `cache[key] = value`，保留原代码并逐句说明",
        "把 `for row in rows:\n    save(row)` 解释得自然清楚",
        "解释 `timeout = max(1, requested)` 是什么、为什么有用",
        "请逐行解释 `path = root / filename`，不要假设读者懂路径对象",
        "说明 `return payload if valid else None` 的输入、判断和结果",
        "给非技术同事解释 `queue.put(job)` 在流程中的位置",
    ], True)
    cases += activation_cases("code_explanation", "negative_no_trigger", [
        "只输出 Python 表达式 `19 * 7` 的整数结果",
        "原样输出 `READY`，不要解释",
        "只返回合法 JSON：{\"ok\":true}",
        "写一行 Python，把变量 x 加 1；只输出代码",
        "判断 `2 < 3`，只输出 true 或 false",
        "把标识符 user_name 改成 camelCase，只输出结果",
    ], False)
    cases += rule_cases("code_explanation", [
        ("解释下面 Python；每个有效语句都添加同行注释，并按最长可注释代码行对齐：\n```python\nx = 1\nlong_name = x + 2\nprint(long_name)\n```", evaluator("inline_alignment")),
        ("解释下面含制表符的 Python；按 4 列制表位计算显示宽度，同行注释统一对齐：\n```python\nif ready:\n\tstart_job()\n\tresult = collect_result()\n```", evaluator("inline_alignment")),
        ("解释下面代码；最长行不要为了注释换行，允许增加总行宽：\n```python\nshort = 1\nvery_descriptive_result_name = calculate_value(source_record)\n```", evaluator("inline_alignment")),
        ("解释下面代码；纯闭合符不要求注释，其余有效语句同行对齐：\n```python\nvalues = [\n    load_value(),\n]\n```", evaluator("inline_alignment")),
        ("解释这个 JSON；JSON 不能添加合法注释，因此保留原文并逐行解释：\n```json\n{\"enabled\": true, \"limit\": 4}\n```", evaluator("json_fallback", ["enabled", "limit"], [r"(?m)^\s*[/#]", r"//\s*(enabled|limit)"])),
        ("解释下面 Python；禁止把注释放到下一行，所有有效语句必须同行对齐：\n```python\nsource = read()\nnormalized_value = normalize(source)\nwrite(normalized_value)\n```", evaluator("inline_alignment")),
    ])

    cases += activation_cases("explanatory_translation", "explicit_trigger", [
        "使用 $human-readable-technical-writing 完整翻译并解释：The valve remains closed until pressure drops.",
        "调用 human-readable-technical-writing 翻译并说明术语边界：A lease expires after 30 minutes.",
        "按人类可读技术写作 Skill 翻译：The sample was stored at 4 °C before analysis.",
        "使用指定写作 Skill 翻译并区分原文与背景：The checksum covers the payload only.",
        "请让 human-readable-technical-writing 翻译：The upper layer formed later than the lower layer.",
        "用 $human-readable-technical-writing 翻译并解释：The token grants read access but not write access.",
    ], True)
    cases += activation_cases("explanatory_translation", "implicit_trigger", [
        "完整翻译并给零基础读者解释：The backup contains metadata but excludes cached files.",
        "翻译并说明因果关系：The motor stopped because the thermal relay opened.",
        "把这句译清楚，并标出原文结论和补充解释：The estimate excludes taxes.",
        "完整翻译：The reading is valid only within the calibrated range，并解释限制",
        "翻译并解释术语：The manifest records each artifact digest.",
        "给第一次接触该概念的人翻译：The replica may lag behind the primary.",
    ], True)
    cases += activation_cases("explanatory_translation", "negative_no_trigger", [
        "Translate hello into Spanish and output one word",
        "把 cat 翻译成中文，只输出一个词",
        "Translate `READY` into lowercase and output only the result",
        "把数字 42 原样输出",
        "Translate yes into French; output one word only",
        "把 `alpha_beta` 改成大写，只输出结果",
    ], False)
    cases += rule_cases("explanatory_translation", [
        ("完整翻译并解释，必须保留 12、9、3：The batch contains 12 files; 9 passed validation and 3 lack signatures.", evaluator("translation_coverage", ["12", "9", "3"], [])),
        ("翻译并解释；`snapshot` 是此处固定术语，不要译成截图：The snapshot preserves repository state at one commit.", evaluator("translation_coverage", ["snapshot", "commit"], ["截图"])),
        ("完整翻译并明确条件边界：The alarm sounds only when both sensors report smoke.", evaluator("translation_coverage", ["only|只有|仅", "both|两个|两只"], [])),
        ("翻译并区分原文与补充背景：The archive was verified before the branch was deleted.", evaluator("translation_coverage", ["归档", "分支", "删除"], [])),
        ("完整翻译，不要把可能性写成确定事实：The delay may be caused by network congestion.", evaluator("translation_coverage", ["可能|may"], ["确定|必然"])),
        ("完整翻译并解释范围：The warranty covers the device but excludes removable batteries.", evaluator("translation_coverage", ["设备", "电池", "不包括|排除"], [])),
    ])

    cases += activation_cases("status_audit", "explicit_trigger", [
        "使用 $human-readable-technical-writing 写状态：14 项完成 11 项，3 项等待输入文件",
        "调用 human-readable-technical-writing 审计这次变更：本地通过，远端尚未运行",
        "按人类可读技术写作 Skill 总结：迁移完成，安装未开始，原因是等待审批",
        "使用指定写作 Skill 写项目变化：新增 2 个合同并删除 1 个旧入口",
        "请让 human-readable-technical-writing 说明证据边界：日志只证明构建成功",
        "用 $human-readable-technical-writing 写事故状态：命令被中断，是否产生副作用未知",
    ], True)
    cases += activation_cases("status_audit", "implicit_trigger", [
        "给零基础读者写项目状态：检查 30 项，通过 28 项，2 项因缺少凭据未运行",
        "总结这次仓库变化，并说明改了什么、为什么、影响、验证和未完成项",
        "审计结论要区分事实和推断：提交存在，但没有找到推送记录",
        "把发布状态写清楚：候选 CI 成功，主分支没有变化，安装未执行",
        "说明一个删除动作的证据：清单显示文件消失，但没有保留命令输出",
        "写恢复报告：本地分支领先远端 2 个提交，工作树干净",
    ], True)
    cases += activation_cases("status_audit", "negative_no_trigger", [
        "只输出 7 加 8 的结果",
        "只输出 JSON 字面量 {\"status\":\"ok\"}",
        "把 DONE 原样输出",
        "列出 A、B、C，用逗号连接且不要解释",
        "判断 11 是否大于 9，只输出 yes",
        "把字符串 audit 改成大写，只输出结果",
    ], False)
    cases += rule_cases("status_audit", [
        ("按项目变化七张卡写状态：新增 `verify.py`；为避免漏检；验证 32/32；尚未推送；证据只有本地测试输出", evaluator("status_aemp", ["新增|改了什么", "避免漏检|原因", "32/32", "未推送", "本地测试|证据"], [])),
        ("解释审计结论并绑定主张与证据：Git status 显示 2 个未跟踪文件；没有远端证据；不要推断已推送", evaluator("status_aemp", ["2", "未跟踪", "远端.*(缺失|没有)|没有.*远端"], ["已推送"])),
        ("写事故状态：测试进程退出码 1；日志最后一行是 schema mismatch；根因尚未证明", evaluator("status_aemp", ["退出码 1", "schema mismatch", "根因.*(未知|未证明)|尚未证明"], ["根因是"])),
        ("写删除测试结论：删掉来源句后，结论失去唯一证据，因此不能保留；说明为何重要", evaluator("status_aemp", ["删除", "证据", "不能保留|失去"], [])),
        ("用三层展示写状态：先给结论，再给最小上下文，最后给证据；事实是候选通过、用户尚未接受", evaluator("status_aemp", ["候选", "通过", "用户", "尚未接受"], [])),
        ("审计项目变化：合同新增字段；运行时开始拒绝缺字段输入；测试新增正反例；部署未执行", evaluator("status_aemp", ["合同", "运行时", "测试", "部署未执行|尚未部署"], [])),
    ])
    return cases


def main() -> int:
    """Write a stable public case manifest and report exact group counts."""

    cases = build_cases()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("".join(json.dumps(case, ensure_ascii=False, sort_keys=True) + "\n" for case in cases), encoding="utf-8", newline="\n")
    print(json.dumps({"status": "PASS", "cases": len(cases), "output": OUTPUT.as_posix()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
