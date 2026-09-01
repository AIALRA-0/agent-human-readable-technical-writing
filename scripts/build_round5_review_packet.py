"""Build the five-case round-five manual review packet from current candidates."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FORWARD = ROOT / "evals" / "forward" / "round-1"
OUTPUT = ROOT / "evals" / "reviews" / "vnext-1.1-round-5-REVIEW-PACKET.md"


def read_json(path: Path) -> dict[str, Any]:
    """Read one UTF-8 lifecycle record."""

    return json.loads(path.read_text(encoding="utf-8"))


def render_source(source: dict[str, Any]) -> str:
    """Render immutable original material without rewording it."""

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
    """Write one packet while preserving every candidate answer byte for byte."""

    c03 = read_json(ROOT / "evals" / "candidate" / "CANDIDATE-03-R6.json")
    forward_paths = sorted((FORWARD / "lifecycle" / "candidate").glob("CANDIDATE-FWD-R1-*-R3.json"))
    forward = [read_json(path) for path in forward_paths]
    if len(forward) != 4:
        raise SystemExit(f"expected four forward R3 candidates, found {len(forward)}")
    lines = [
        "# vNext 1.1 第五轮修订候选审核包",
        "",
        "本审核包只包含第四轮明确拒绝后生成的 5 个新 Candidate；自动检查通过不能把任何答案转为 Gold",
        "",
        "第一轮首次未见成绩永久保持为 8/20；第四轮人工结果为接受 8、拒绝 5，本包不改写这些历史成绩",
        "",
        "请逐项回复接受或拒绝；拒绝时指出具体位置和原因，系统会保留当前版本并生成下一修订版",
        "",
        "## 1. CANDIDATE-03-R6",
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
        "本次修订依据：",
        "",
    ]
    lines.extend(f"* {item}" for item in c03["review"]["regression_requirements"])
    lines.extend(["", "审核决定：接受或拒绝；拒绝时请指出具体位置和原因"])
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
        "status": "PASS",
        "cases": 5,
        "output": str(OUTPUT.relative_to(ROOT)).replace("\\", "/"),
        "reason": "审核包从五个当前 Candidate 生成，没有改写答案或产生用户接受决定",
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
