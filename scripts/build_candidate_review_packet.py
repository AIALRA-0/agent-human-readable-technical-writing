"""Build the manual review packet for the only remaining anchor candidate."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CASE_PATH = ROOT / "evals" / "candidate" / "CANDIDATE-03-R4.json"
OUTPUT_PATH = ROOT / "evals" / "candidate" / "REVIEW-PACKET.md"


def main() -> None:
    """Render C03-R4 without changing the candidate text."""

    case = json.loads(CASE_PATH.read_text(encoding="utf-8"))
    lines = [
        "# vNext 1.1 C03-R4 审核包",
        "",
        "`CANDIDATE-03-R4` 只把 R3 的括号英文类别从 `package manager` 修复为 `Package Manager`；命令主体、npm 官方形式、CI 解释和证据边界保持不变；自动检查不能替代用户决定",
        "",
        "## 1. 用户请求",
        "",
        f"> {case['task']['request']}",
        "",
        "## 2. 原始材料",
        "",
        f"> {case['source']['content']}",
        "",
        "## 3. CANDIDATE-03-R4",
        "",
        case["artifact"]["answer"],
        "",
        "## 4. 本轮需要判断的内容",
        "",
        "- 主语是否已经明确，同时避免机械重复",
        "- `Package Manager` 的标题式大小写是否符合当前要求",
        "- npm 是否继续保持官方小写，并且没有伪造成英文全称",
        "- 其余已经确认正确的内容是否保持不变",
        "",
        "请明确决定接受或拒绝；拒绝时请指出具体位置和原因",
    ]
    OUTPUT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
