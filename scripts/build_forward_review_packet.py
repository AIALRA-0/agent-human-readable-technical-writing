"""Render one immutable forward round as a canonical packet and review batches."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
BATCH_SIZE = 5
MODEL_ORDER = ("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna")
MODEL_LABELS = {"gpt-5.6-sol": "Sol", "gpt-5.6-terra": "Terra", "gpt-5.6-luna": "Luna"}


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


def closure_packet_header(round_number: int, count: int, *, batch: tuple[int, int] | None = None) -> list[str]:
    """Describe one three-model closed-result review page without implying acceptance."""

    title = f"# vNext 1.1 第 {round_number} 轮三模型闭环审核包"
    if batch is not None:
        title += f"：第 {batch[0]}–{batch[1]} 个案例"
    return [
        title,
        "",
        f"本页包含 {count} 个案例，每个案例并排展示 Sol、Terra、Luna 的闭环最终答案",
        "",
        "初稿、自动发现、最小补丁和闭环通过只属于运行证据，不代表用户接受",
        "",
        "每个模型必须单独获得明确决定，三个模型全部接受后，该案例才算人工通过",
        "",
        "第二轮已有 5 个 Sol 首稿被拒绝，因此本轮首稿最高为 15/20，修订接受不会改写该历史成绩",
    ]


def lifecycle_candidates(directory: Path) -> dict[tuple[str, str], dict[str, Any]]:
    """Load current pending candidates after closure materialization."""

    result: dict[tuple[str, str], dict[str, Any]] = {}
    for path in sorted((directory / "lifecycle" / "candidate").glob("*.json")):
        item = json.loads(path.read_text(encoding="utf-8"))
        identity = item["identity"]
        model = identity.get("model")
        if model:
            result[(identity["origin_case_id"], model)] = item
    return result


def render_closure_model(result: dict[str, Any], candidate: dict[str, Any]) -> list[str]:
    """Render auditable closure evidence and the exact final answer for one model."""

    identity = candidate["identity"]
    candidate_id = identity["case_id"]
    iterations = result["iterations"]
    rule_ids = list(dict.fromkeys(
        rule_id
        for round_record in iterations["rounds"]
        for rule_id in round_record.get("finding_rule_ids", [])
    ))
    patch_summaries = [
        summary
        for round_record in iterations["rounds"]
        for summary in round_record.get("patch_summaries", [])
    ]
    first_status = (
        "未命中已登记硬规则"
        if result["first_attempt_hard_errors"] == 0
        else f"命中 {result['first_attempt_hard_errors']} 项已登记硬规则"
    )
    lines = [
        "",
        f"### {MODEL_LABELS[result['model']]}｜`{candidate_id}`",
        "",
        f"最终答案 SHA-256：`{result['final_sha256']}`",
        "",
        f"首稿状态：{first_status}",
        "",
        f"自动修复轮数：{result['repair_rounds']}/3",
        "",
        f"闭环状态：`{result['status']}`",
        "",
        f"局部修复保真：`{result.get('preservation_status', '未登记')}`",
        "",
        "命中的规则：",
        "",
    ]
    lines.extend(f"- `{rule_id}`" for rule_id in rule_ids)
    if not rule_ids:
        lines.append("- 无")
    lines.extend(["", "最小补丁摘要：", ""])
    lines.extend(
        f"- `{item['patch_id']}`｜`{item['node_id']}`｜`{item['repair_scope']}`｜{review_safe_markdown(item['summary'])}"
        for item in patch_summaries
    )
    if not patch_summaries:
        lines.append("- 无需补丁")
    lines.extend([
        "",
        "闭环最终答案：",
        "",
        review_safe_markdown(result["answer"]),
        "",
        "人工决定：",
        "",
        f"- 接受：`{candidate_id} 可以，没问题`",
        f"- 拒绝：`{candidate_id} 拒绝：具体位置、原因和希望保留的正确部分`",
    ])
    return lines


def render_closure_case(
    index: int,
    request: dict[str, Any],
    results: dict[str, dict[str, Any]],
    candidates: dict[tuple[str, str], dict[str, Any]],
) -> list[str]:
    """Render one request once, followed by all three independently closed answers."""

    case_id = request["case_id"]
    lines = [
        "",
        f"## {index}. `{case_id}`",
        "",
        f"配置：`{request['base_operation']} + {request['augmentation']}`｜组件：`{', '.join(request['components'])}`｜受众：`{request.get('audience', '未登记')}`｜长度：`{request.get('length_class', '未登记')}`",
        "",
        "用户请求：",
        "",
        f"> {review_safe_markdown(request['request'])}",
        "",
        "原始材料：",
        "",
        render_source(request["source"]),
    ]
    for model in MODEL_ORDER:
        result = results[model]
        candidate = candidates[(case_id, model)]
        if candidate["artifact"]["answer_sha256"] != result["final_sha256"]:
            raise SystemExit(f"{case_id} {model}: lifecycle answer differs from closure result")
        lines.extend(render_closure_model(result, candidate))
    return lines


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
    closure_path = directory / "closure-results.jsonl"
    if closure_path.exists():
        closure_results = [json.loads(line) for line in closure_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        expected_keys = {(case_id, model) for case_id in requests for model in MODEL_ORDER}
        actual_keys = {(item["case_id"], item["model"]) for item in closure_results}
        if len(requests) != 20 or len(closure_results) != 60 or actual_keys != expected_keys:
            raise SystemExit("three-model review packet requires 20 requests and exactly 60 closure results")
        if any(item.get("status") != "PASS" for item in closure_results):
            raise SystemExit("REVIEW_REQUIRED closure results cannot enter a user review packet")
        candidates = lifecycle_candidates(directory)
        if set(candidates) != expected_keys:
            raise SystemExit("three-model lifecycle candidates must be materialized before building the packet")
        by_case = {
            case_id: {
                model: next(item for item in closure_results if item["case_id"] == case_id and item["model"] == model)
                for model in MODEL_ORDER
            }
            for case_id in requests
        }
        ordered_requests = [requests[case_id] for case_id in sorted(requests)]
        complete_lines = closure_packet_header(args.round_number, len(ordered_requests))
        for index, request in enumerate(ordered_requests, start=1):
            complete_lines.extend(render_closure_case(index, request, by_case[request["case_id"]], candidates))
        complete = directory / "REVIEW-PACKET.md"
        write_markdown(complete, complete_lines)

        batch_root = directory / "review-batches"
        outputs = [complete]
        index_lines = [
            f"# vNext 1.1 第 {args.round_number} 轮三模型分批审核索引",
            "",
            "请按顺序审核四批，每批 5 个案例、15 个模型答案",
            "",
            "完整单页版本：[REVIEW-PACKET.md](../REVIEW-PACKET.md)",
            "",
        ]
        for offset in range(0, len(ordered_requests), BATCH_SIZE):
            batch = ordered_requests[offset : offset + BATCH_SIZE]
            start, end = offset + 1, offset + len(batch)
            name = f"BATCH-{offset // BATCH_SIZE + 1:02d}.md"
            lines = closure_packet_header(args.round_number, len(batch), batch=(start, end))
            for index, request in enumerate(batch, start=start):
                lines.extend(render_closure_case(index, request, by_case[request["case_id"]], candidates))
            target = batch_root / name
            write_markdown(target, lines)
            outputs.append(target)
            index_lines.append(f"- 第 {start}–{end} 个案例：[{name}]({name})")
        index_path = batch_root / "INDEX.md"
        write_markdown(index_path, index_lines)
        outputs.append(index_path)
        print(json.dumps({
            "status": "PASS", "round": args.round_number, "cases": len(ordered_requests),
            "model_answers": len(closure_results), "automated_checks_are_user_acceptance": False,
            "outputs": [path.as_posix() for path in outputs],
        }, ensure_ascii=False))
        return 0

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
