"""Record mechanical findings for frozen forward answers without human scoring."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from runtime.self_iteration import deterministic_findings  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--round", type=int, required=True, dest="round_number")
    parser.add_argument("--require-pass", action="store_true", help="return nonzero when frozen answers have mechanical findings")
    return parser.parse_args()


def visible_prose(text: str) -> str:
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith(">") and not line.lstrip().startswith("!["))


def display_width(text: str) -> int:
    column = 0
    for character in text:
        column = column + (4 - column % 4) if character == "\t" else column + 1
    return column


def code_alignment_findings(answer: str) -> list[str]:
    blocks = [match.group(2).rstrip("\n") for match in re.finditer(r"```([^\n]*)\n(.*?)```", answer, re.DOTALL) if "#" in match.group(2)]
    if not blocks:
        return ["没有找到带同行注释的代码块"]
    errors: list[str] = []
    for block_number, block in enumerate(blocks, start=1):
        units: list[tuple[int, int, int]] = []
        for line_number, line in enumerate(block.splitlines(), start=1):
            if not line.strip() or re.fullmatch(r"\s*[\]\[{}(),;]+\s*", line):
                continue
            marker = line.find("#")
            if marker < 0:
                errors.append(f"注释块 {block_number} 第 {line_number} 行缺少同行注释")
                continue
            code = line[:marker].rstrip(" \t")
            units.append((display_width(code), display_width(line[:marker]) + 1, line_number))
            if line.rstrip(" \t") != line:
                errors.append(f"注释块 {block_number} 第 {line_number} 行含行尾空白")
        if units:
            target = max(width for width, _, _ in units) + 2
            errors.extend(f"注释块 {block_number} 第 {line_number} 行注释列为 {actual}，目标列为 {target}" for _, actual, line_number in units if actual != target)
    return errors


def finding(case_id: str, rule_id: str, evidence: str) -> dict[str, str]:
    return {
        "case_id": case_id,
        "rule_id": rule_id,
        "message": evidence,
        "evidence": evidence,
        "impact": "首次答案保持原样；机械失败不能被记为用户接受",
        "next": "提交人工审核并在用户拒绝后只生成下一修订版",
    }


def main() -> int:
    args = parse_args()
    directory = ROOT / "evals" / "forward" / f"round-{args.round_number}"
    requests = {item["case_id"]: item for item in [json.loads(line) for line in (directory / "requests.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]}
    closure_path = directory / "closure-results.jsonl"
    if closure_path.exists():
        candidates = [json.loads(line) for line in closure_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        findings: list[dict[str, str]] = []
        for candidate in candidates:
            case_id = candidate["case_id"]
            label = f"{case_id}:{candidate['model']}"
            if candidate.get("status") != "PASS":
                findings.append(finding(label, "CLOSURE_NOT_COMPLETE", "三轮以内没有完成自迭代闭环"))
                continue
            manifest = {key: candidate[key] for key in ("term_uses", "parallel_groups", "section_plan", "boundary_visibility")}
            for item in deterministic_findings(candidate["answer"], manifest):
                findings.append(finding(label, item["rule_id"], f"{item['location']} {item['reason']}"))
        expected = 20 * 3
        if len(candidates) != expected:
            findings.append(finding(f"round-{args.round_number}", "CROSS_MODEL_COUNT", f"闭环结果为 {len(candidates)}，预期 {expected}"))
        result: dict[str, Any] = {
            "round": args.round_number,
            "status": "PASS" if not findings else "FAIL",
            "checked_candidates": len(candidates),
            "models": sorted({item.get("model") for item in candidates}),
            "hard_error_count": len(findings),
            "findings": findings,
            "user_decisions": 0,
            "next_round_allowed": False,
            "automated_checks_are_user_acceptance": False,
        }
        (directory / "deterministic-findings.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        print(json.dumps({"status": result["status"], "round": args.round_number, "checked": len(candidates), "hard_errors": len(findings)}, ensure_ascii=False))
        return 0 if not findings or not args.require_pass else 1

    candidates = [json.loads(line) for line in (directory / "candidates.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    findings: list[dict[str, str]] = []
    for candidate in candidates:
        case_id = candidate["case_id"]
        request = requests[case_id]
        answer = candidate["answer"]
        prose = visible_prose(answer)
        if "。" in prose:
            findings.append(finding(case_id, "LUCAS_NO_CHINESE_FULL_STOP", "生成正文含中文句号"))
        if "\n\n\n" in answer:
            findings.append(finding(case_id, "EXCESSIVE_BLANK_LINES", "答案含两个以上连续空行"))
        restart = next(reference["content"] for reference in request["references"] if reference["id"] == "REF-RESTART")
        batch = re.search(r"B[0-9]+", restart).group(0)
        if batch not in answer:
            findings.append(finding(case_id, "PROTECTED_BATCH_ID", f"答案缺少受保护复核编号 {batch}"))
        material = request["source"]["material_type"]
        source = request["source"]["content"]
        if material == "image":
            if f"]({source['path']})" not in answer:
                findings.append(finding(case_id, "SOURCE_IMAGE_PRESENCE", f"答案没有先保留原图 {source['path']}"))
        elif material == "table" and source not in answer:
            findings.append(finding(case_id, "SOURCE_TABLE_PRESENCE", "答案没有原样保留输入表格"))
        elif material == "code":
            if source not in answer:
                findings.append(finding(case_id, "SOURCE_CODE_PRESENCE", "答案没有原样保留原始代码"))
            for evidence in code_alignment_findings(answer):
                findings.append(finding(case_id, "INLINE_COMMENT_ALIGNMENT", evidence))
    result: dict[str, Any] = {
        "round": args.round_number,
        "status": "PASS" if not findings else "FAIL",
        "checked_candidates": len(candidates),
        "hard_error_count": len(findings),
        "findings": findings,
        "user_decisions": 0,
        "next_round_allowed": False,
        "automated_checks_are_user_acceptance": False,
    }
    (directory / "deterministic-findings.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"status": result["status"], "round": args.round_number, "checked": len(candidates), "hard_errors": len(findings)}, ensure_ascii=False))
    return 0 if not findings or not args.require_pass else 1


if __name__ == "__main__":
    sys.exit(main())
