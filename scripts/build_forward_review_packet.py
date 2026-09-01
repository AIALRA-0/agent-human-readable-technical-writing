"""Render one round of first-attempt forward candidates for user review."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIRECTORY = ROOT / "evals" / "forward" / "round-1"


def render_source(source: dict[str, Any]) -> str:
    """Render source content without rewording it."""

    content = source["content"]
    material = source["material_type"]
    if material == "image":
        return f"![{content['alt']}]({content['path']})"
    if material == "code":
        return "```text\n" + content + "\n```"
    if material == "table":
        return content
    if isinstance(content, list):
        return "\n".join(f"- {item}" for item in content)
    return content or "本案例没有原始正文，只能使用已给事实生成说明"


def parse_args() -> argparse.Namespace:
    """Accept future rounds while keeping the original no-argument command."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--round", type=int, default=1, dest="round_number")
    parser.add_argument("--directory", type=Path)
    return parser.parse_args()


def main() -> int:
    """Build one packet while preserving every first-attempt answer exactly."""

    args = parse_args()
    if args.round_number < 1:
        raise SystemExit("round must be a positive integer")
    directory = args.directory or ROOT / "evals" / "forward" / f"round-{args.round_number}"
    output = directory / "REVIEW-PACKET.md"

    requests = {item["case_id"]: item for item in [json.loads(line) for line in (directory / "requests.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]}
    candidates = [json.loads(line) for line in (directory / "candidates.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    finding_record = json.loads((directory / "deterministic-findings.json").read_text(encoding="utf-8"))
    findings = {item["case_id"]: item for item in finding_record["findings"]}
    if args.round_number == 1:
        lines = [
            "# vNext 1.1 第一轮未见前向审核包",
            "",
            "这 20 个答案由隔离生成 Agent 各生成一次；生成前没有提供预期答案、怀疑问题或评分依据，当前全部处于 `pending_user_review`",
            "",
            "请逐项给出接受或拒绝；拒绝时指出事实、遗漏、来源、结构或表达问题；第一轮至少接受 18/20 且事实硬错误为 0，才会生成第二轮",
            "",
            "当前确定性结果为 `FAIL`；FWD-R1-012、FWD-R1-017 和 FWD-R1-018 各出现 1 个中文句号，首次答案保持原样作为失败证据，第二轮生成已经停止",
        ]
    else:
        lines = [
            f"# vNext 1.1 第 {args.round_number} 轮未见前向审核包",
            "",
            "这 20 个答案由隔离生成 Agent 各生成一次；生成前没有提供预期答案、怀疑问题或评分依据，当前全部处于 `pending_user_review`",
            "",
            "请逐项给出接受或拒绝；拒绝时指出事实、遗漏、来源、结构或表达问题；本轮成绩永久保留，只有首稿 20/20 才计入连续完美轮次",
            "",
            "确定性检查只登记机械结果，不写入人工接受字段；首次答案生成一次后立即以摘要冻结",
        ]
    for index, candidate in enumerate(candidates, start=1):
        request = requests[candidate["case_id"]]
        finding = findings.get(candidate["case_id"])
        lines.extend(
            [
                "",
                f"## {index}. {candidate['case_id']}",
                "",
                f"配置：`{request['base_operation']} + {request['augmentation']}`；组件为 `{', '.join(request['components'])}`",
                "",
                "用户请求：",
                "",
                f"> {request['request']}",
                "",
                "原始材料：",
                "",
                render_source(request["source"]),
                "",
                "首次生成答案：",
                "",
                candidate["answer"],
                "",
                "确定性检查：" + (f"失败；{finding['evidence']}" if finding else "通过；没有发现已登记的机械格式问题"),
                "",
                "审核决定：接受或拒绝；拒绝时请说明具体位置和原因",
            ]
        )
    output.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"status": "PASS", "round": args.round_number, "cases": len(candidates), "output": output.as_posix()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
