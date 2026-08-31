"""Build one human review packet from the twelve structured candidate cases."""

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
    """Load cases in numeric order and regenerate the complete review packet."""

    case_paths = sorted(CANDIDATE_DIRECTORY.glob("CANDIDATE-??.json"))
    sections = [
        "# vNext 1.1 首批候选锚点审核包",
        "",
        "本审核包包含 12 个由 Codex 生成的候选版本；所有案例的状态都是 `candidate`，并且 `approved_by_user` 均为 `false`",
        "",
        "请对每个案例给出接受、拒绝或修改意见；系统只有在收到你的明确判断后，才能把接受版本复制到金标区",
    ]

    for path in case_paths:
        case = json.loads(path.read_text(encoding="utf-8"))
        identity = case["identity"]
        task = case["task"]
        sections.extend(
            [
                "",
                f"## {identity['case_id']}",
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
                "候选答案：",
                "",
                case["candidate"]["answer"],
                "",
                "审核问题：",
                "",
            ]
        )
        sections.extend(f"- {question}" for question in case["review"]["questions"])

    OUTPUT_PATH.write_text("\n".join(sections).rstrip() + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
