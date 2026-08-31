"""Build the 13-case round-four manual review packet from lifecycle artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FORWARD = ROOT / "evals" / "forward" / "round-1"
OUTPUT = ROOT / "evals" / "reviews" / "vnext-1.1-round-4-REVIEW-PACKET.md"


def render_source(source: dict[str, Any]) -> str:
    """Render the immutable original material without rewording it."""

    content = source["content"]
    material = source["material_type"]
    if material == "image":
        return f"![{content['alt']}](../forward/round-1/{content['path']})"
    if material == "code":
        return "```text\n" + content + "\n```"
    if material == "table":
        return content
    if isinstance(content, list):
        return "\n".join(f"* {item}" for item in content)
    return content or "本案例没有原始正文，只使用请求中明确提供的事实"


def main() -> int:
    """Write one packet while keeping every candidate answer byte-for-byte unchanged."""

    c03 = json.loads((ROOT / "evals" / "candidate" / "CANDIDATE-03-R5.json").read_text(encoding="utf-8"))
    forward_paths = sorted((FORWARD / "lifecycle" / "candidate").glob("CANDIDATE-FWD-R1-*-R2.json"))
    forward = [json.loads(path.read_text(encoding="utf-8")) for path in forward_paths]
    lines = [
        "# vNext 1.1 第三轮修订候选审核包",
        "",
        "本审核包包含 1 个锚点修订版和 12 个第一轮前向修订版；全部答案仍为 Candidate，只有用户明确接受后才能转为 Gold",
        "",
        "第一轮前向测试的原始成绩永久保持为 8/20；本包只验证修订是否解决已发现问题，不改变第一次未见测试结果",
        "",
        "## 1. CANDIDATE-03-R5",
        "",
        "用户请求：",
        "",
        "> " + c03["task"]["request"],
        "",
        "原始材料：",
        "",
        "> " + c03["source"]["content"],
        "",
        "修订答案：",
        "",
        c03["artifact"]["answer"],
        "",
        "审核要求：确认 npm 说明是否自然且符合官方事实，并确认命令主体、退出码、CI 与证据边界是否清楚",
    ]
    for index, case in enumerate(forward, start=2):
        request = case["task"]
        lines.extend([
            "",
            f"## {index}. {case['identity']['case_id']}",
            "",
            "用户请求：",
            "",
            "> " + request["request"],
            "",
            "原始材料：",
            "",
            render_source(request["source"]),
            "",
            "修订答案：",
            "",
            case["artifact"]["answer"],
            "",
            "本次修订依据：",
            "",
        ])
        lines.extend(f"* {item}" for item in case["review"]["regression_requirements"])
        lines.extend(["", "审核决定：接受或拒绝；拒绝时请指出具体位置和原因"])
    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({
        "status": "PASS", "cases": 13, "output": str(OUTPUT.relative_to(ROOT)).replace("\\", "/"),
        "reason": "审核包从当前生命周期候选生成，没有改写任何候选答案",
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
