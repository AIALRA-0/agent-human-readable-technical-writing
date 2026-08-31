"""Build the manual review packet for the only remaining anchor candidate."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CASE_PATH = ROOT / "evals" / "candidate" / "CANDIDATE-03-R3.json"
OUTPUT_PATH = ROOT / "evals" / "candidate" / "REVIEW-PACKET.md"


def main() -> None:
    """Render C03-R3 without changing the candidate text."""

    case = json.loads(CASE_PATH.read_text(encoding="utf-8"))
    lines = [
        "# vNext 1.1 C03-R3 审核包",
        "",
        "`CANDIDATE-03-R3` 已修复 R2 中的主语归属和 npm 官方命名问题；自动检查只能确认结构、来源和已登记硬要求，用户决定仍是唯一验收依据",
        "",
        "## 1. 用户请求",
        "",
        f"> {case['task']['request']}",
        "",
        "## 2. 原始材料",
        "",
        f"> {case['source']['content']}",
        "",
        "## 3. CANDIDATE-03-R3",
        "",
        case["artifact"]["answer"],
        "",
        "## 4. 本轮需要判断的内容",
        "",
        "- 主语是否已经明确，同时避免机械重复",
        "- npm 是否自然解释了包管理器、命令行工具和软件包仓库三种作用",
        "- npm 是否保持官方小写，并且没有伪造成英文全称",
        "- 段落和空行是否适合连续阅读",
        "",
        "请明确决定接受或拒绝；拒绝时请指出具体位置和原因",
    ]
    OUTPUT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
