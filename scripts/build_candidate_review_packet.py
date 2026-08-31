"""Build the second manual review packet from the ten structured R2 cases."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CANDIDATE_DIRECTORY = ROOT / "evals" / "candidate"
OUTPUT_PATH = CANDIDATE_DIRECTORY / "REVIEW-PACKET.md"


def render_source(source: dict[str, object]) -> str:
    """Render text directly and structured source material as readable JSON."""

    content = source["content"]
    if isinstance(content, str):
        return content
    return "```json\n" + json.dumps(content, ensure_ascii=False, indent=2) + "\n```"


def main() -> None:
    """Load R2 cases in numeric order and regenerate the complete review packet."""

    case_paths = sorted(CANDIDATE_DIRECTORY.glob("CANDIDATE-??-R2.json"))
    if len(case_paths) != 10:
        raise SystemExit(f"expected 10 R2 candidates, found {len(case_paths)}")
    sections = [
        "# vNext 1.1 第二轮候选审核包",
        "",
        "本审核包包含 10 个根据首轮用户反馈修订的 R2 候选；所有案例的状态仍为 `candidate`，`approved_by_user` 仍为 `false`",
        "",
        "自动检查只确认来源映射、结构和已登记硬规则；请逐项决定接受、拒绝或继续修改，系统收到明确判断后才能把接受版本转入金标区",
    ]

    for ordinal, path in enumerate(case_paths, start=1):
        case = json.loads(path.read_text(encoding="utf-8"))
        identity = case["identity"]
        task = case["task"]
        rejected_path = ROOT / "evals" / "rejected" / f"REJECTED-{identity['origin_case_id'][-2:]}.json"
        rejected = json.loads(rejected_path.read_text(encoding="utf-8"))
        sections.extend(
            [
                "",
                f"## {ordinal}. {identity['case_id']}",
                "",
                f"任务配置：`{task['base_operation']} + {task['augmentation']}`；类型为 `{identity['category']}`",
                "",
                "用户请求：",
                "",
                f"> {task['request']}",
                "",
                "原始材料：",
                "",
                render_source(case["source"]),
                "",
                "R2 候选答案：",
                "",
                case["artifact"]["answer"],
                "",
                "首轮拒绝原因：",
                "",
            ]
        )
        sections.extend(f"- {reason}" for reason in rejected["review"]["reasons"])
        sections.extend(["", "本轮复审要点：", ""])
        sections.extend(f"- {requirement}" for requirement in case["review"]["regression_requirements"])
        sections.extend(
            [
                "",
                "请给出一个明确决定：接受、拒绝，或指出需要修改的具体位置与原因",
            ]
        )

    OUTPUT_PATH.write_text("\n".join(sections).rstrip() + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
