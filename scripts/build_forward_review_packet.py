"""Render one immutable forward round as a canonical packet and review batches."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
BATCH_SIZE = 5


def review_safe_markdown(text: str) -> str:
    """Remove invisible terminal whitespace from a derived review view only."""

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip(" \t") for line in normalized.split("\n"))


def render_source(source: dict[str, Any]) -> str:
    """Render source content without rewording visible content."""

    content = source["content"]
    material = source["material_type"]
    if material == "image":
        rendered = f"![{content['alt']}]({content['path']})"
    elif material == "code":
        rendered = "```text\n" + content + "\n```"
    elif material == "table":
        rendered = content
    elif isinstance(content, list):
        rendered = "\n".join(f"- {item}" for item in content)
    else:
        rendered = content or "本案例没有原始正文，只能使用已给事实生成说明"
    return review_safe_markdown(rendered)


def group_findings(items: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Keep every finding for a case in source order."""

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        grouped[item["case_id"]].append(item)
    return dict(grouped)


def packet_header(round_number: int, count: int, *, batch: tuple[int, int] | None = None) -> list[str]:
    """Describe the human-only gate and immutable evidence boundary."""

    title = f"# vNext 1.1 第 {round_number} 轮未见前向审核包"
    if batch is not None:
        title += f"：第 {batch[0]}–{batch[1]} 项"
    return [
        title,
        "",
        f"本页包含 {count} 个一次生成并立即冻结的答案；生成 Agent 未看到评分依据或预期答案",
        "",
        "确定性检查只提示机械问题，不能写入人工接受字段；接受或拒绝只能来自用户明确决定",
        "",
        "审核页为便于显示会移除不可见的行尾空白；答案是否被改写以页面所列 SHA-256 和 `candidates.jsonl` 为准",
        "",
        "本轮首稿成绩永久保留；只有首稿 20/20 才计入连续完美轮次",
    ]


def render_case(
    index: int,
    candidate: dict[str, Any],
    request: dict[str, Any],
    findings: list[dict[str, Any]],
) -> list[str]:
    """Render one bound review item with all deterministic findings."""

    lifecycle_id = f"CANDIDATE-{candidate['case_id']}-R1"
    lines = [
        "",
        f"## {index}. {lifecycle_id}",
        "",
        f"原始案例：`{candidate['case_id']}`；配置：`{request['base_operation']} + {request['augmentation']}`；组件：`{', '.join(request['components'])}`",
        "",
        f"答案 SHA-256：`{candidate['answer_sha256']}`",
        "",
        "用户请求：",
        "",
        f"> {review_safe_markdown(request['request'])}",
        "",
        "原始材料：",
        "",
        render_source(request["source"]),
        "",
        "首次生成答案：",
        "",
        review_safe_markdown(candidate["answer"]),
        "",
        "确定性检查：",
        "",
    ]
    if findings:
        lines.extend(f"- 失败 `{item['rule_id']}`：{review_safe_markdown(item['evidence'])}" for item in findings)
    else:
        lines.append("- 通过：没有发现已登记的机械格式问题")
    lines.extend(
        [
            "",
            "审核决定（请使用候选编号）：",
            "",
            f"- 接受：`{lifecycle_id} 可以，没问题`",
            f"- 拒绝：`{lifecycle_id} 拒绝：具体位置、原因和希望保留的正确部分`",
        ]
    )
    return lines


def write_markdown(path: Path, lines: list[str]) -> None:
    """Write a generated Markdown file with no terminal whitespace."""

    cleaned = [line.rstrip(" \t") for line in lines]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(cleaned) + "\n", encoding="utf-8", newline="\n")


def parse_args() -> argparse.Namespace:
    """Accept future rounds while keeping a concise command interface."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--round", type=int, default=1, dest="round_number")
    parser.add_argument("--directory", type=Path)
    return parser.parse_args()


def main() -> int:
    """Build the complete packet, four five-case pages, and a review index."""

    args = parse_args()
    if args.round_number < 1:
        raise SystemExit("round must be a positive integer")
    directory = args.directory or ROOT / "evals" / "forward" / f"round-{args.round_number}"
    requests = {
        item["case_id"]: item
        for item in [json.loads(line) for line in (directory / "requests.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    }
    candidates = [json.loads(line) for line in (directory / "candidates.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    finding_record = json.loads((directory / "deterministic-findings.json").read_text(encoding="utf-8"))
    findings = group_findings(finding_record["findings"])
    if len(candidates) != 20 or set(requests) != {item["case_id"] for item in candidates}:
        raise SystemExit("review packet requires exactly 20 matching requests and candidates")

    complete_lines = packet_header(args.round_number, len(candidates))
    for index, candidate in enumerate(candidates, start=1):
        complete_lines.extend(render_case(index, candidate, requests[candidate["case_id"]], findings.get(candidate["case_id"], [])))
    complete = directory / "REVIEW-PACKET.md"
    write_markdown(complete, complete_lines)

    batch_root = directory / "review-batches"
    outputs = [complete]
    index_lines = [
        f"# vNext 1.1 第 {args.round_number} 轮分批审核索引",
        "",
        "请按顺序审核四批；每批 5 项。决定会绑定候选编号和答案 SHA-256，自动检查不会替代你的决定",
        "",
        "完整单页版本：[REVIEW-PACKET.md](../REVIEW-PACKET.md)",
        "",
    ]
    for offset in range(0, len(candidates), BATCH_SIZE):
        batch = candidates[offset : offset + BATCH_SIZE]
        start, end = offset + 1, offset + len(batch)
        name = f"BATCH-{offset // BATCH_SIZE + 1:02d}.md"
        batch_lines = packet_header(args.round_number, len(batch), batch=(start, end))
        for index, candidate in enumerate(batch, start=start):
            batch_lines.extend(render_case(index, candidate, requests[candidate["case_id"]], findings.get(candidate["case_id"], [])))
        target = batch_root / name
        write_markdown(target, batch_lines)
        outputs.append(target)
        index_lines.append(f"- 第 {start}–{end} 项：[{name}]({name})")
    index_path = batch_root / "INDEX.md"
    write_markdown(index_path, index_lines)
    outputs.append(index_path)

    print(json.dumps({
        "status": "PASS",
        "round": args.round_number,
        "cases": len(candidates),
        "findings": sum(len(items) for items in findings.values()),
        "outputs": [path.as_posix() for path in outputs],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
