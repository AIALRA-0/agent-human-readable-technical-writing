"""Render actual private model answers as readable Markdown, preserving failures."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def render(report_path: Path, run_root: Path, requests_path: Path, output: Path) -> dict:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    rows = [json.loads(line) for line in requests_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    requests = {row["case_id"]: row for row in rows}
    output.mkdir(parents=True, exist_ok=True)
    grouped: dict[str, list[dict]] = {}
    for result in report.get("results", []):
        grouped.setdefault(result["case_id"], []).append(result)
    pages = []
    for case_id, results in grouped.items():
        row = requests[case_id]
        if Path(case_id).name != case_id or any(char in case_id for char in "/\\"):
            raise ValueError("case identifier cannot be a path")
        page = [f"# {case_id}", "", "以下为实际模型输出，待用户审核，自动检查不代表用户接受", "",
                "## 原始需求", "", row["request"], "", "## 提供的材料", ""]
        material = row["source"]["content"]
        if isinstance(material, str):
            page.extend("> " + line for line in material.splitlines())
        else:
            page.extend(["```json", json.dumps(material, ensure_ascii=False, indent=2), "```"])
        page.append("")
        references = row.get("references", [])
        for reference in references:
            page.extend([f"- {reference.get('id', '来源')}：{reference.get('content', '')}"])
        if references:
            page.append("")
        for item in results:
            model_code = item["model_code"]
            if not model_code.isalnum():
                raise ValueError("model code cannot be a path")
            attempt = int(item.get("host_attempt", 1))
            result_file = run_root / f"{case_id}-{model_code}" / f"attempt-{attempt:02d}" / "result.json"
            payload = json.loads(result_file.read_text(encoding="utf-8")) if result_file.is_file() else {}
            writer = payload.get("private", {}).get("writer", {})
            answer = writer.get("answer", "")
            expected_digest = item.get("final_sha256")
            if item.get("expected_trigger") is False:
                answer = payload.get("private", {}).get("negative_output", {}).get("payload", {}).get("answer", "")
                expected_digest = item.get("negative_output_sha256")
                if item.get("negative_output_status") == "PASS" and answer != material:
                    raise ValueError(f"{case_id}/{model_code}: claimed exact negative output differs from source")
            if answer and hashlib.sha256(answer.encode("utf-8")).hexdigest() != expected_digest:
                raise ValueError(f"{case_id}/{model_code}: final answer digest mismatch")
            rules = item.get("final_finding_rule_ids", [])
            page.extend([f"## {model_code}", "",
                         f"运行状态为 `{item['status']}`，自动修复 {item.get('repair_rounds', 0)} 轮", ""])
            if rules:
                page.extend(["仍需处理的规则为 " + "、".join(f"`{rule}`" for rule in rules), ""])
            if answer:
                # Save the verified body separately without adding report headings.
                (output / f"{case_id}-{model_code}-answer.md").write_text(answer, encoding="utf-8")
                page.extend(["### 实际最终正文", "", answer, ""])
            else:
                page.extend(["该项没有可验证的实际输出，不能只凭分类结果认定通过", ""])
        target = output / f"{case_id}.md"
        target.write_text("\n".join(page), encoding="utf-8")
        pages.append((case_id, target.name))
    planned = int(report["case_count"]) * len(report["models"])
    index = ["# 实际写作结果", "",
             f"当前完成 {report.get('completed', 0)}/{planned} 项，通过 {report.get('passed', 0)} 项，未通过 {report.get('failed', 0)} 项", "",
             "点击案例即可看原始请求、素材和各模型实际正文；失败答案同样保留，模型结果不代替你的阅读判断", "",
             "这些结果测试注入规则后的执行，自动发现与读取技能需要查看单独的原生调用结果", ""]
    index.extend(f"- [{case_id}]({name})" for case_id, name in pages)
    (output / "index.md").write_text("\n".join(index) + "\n", encoding="utf-8")
    return {"rendered_cases": len(pages), "completed": report.get("completed", 0),
            "planned": planned, "automated_result_is_user_acceptance": False}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--requests", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(render(args.report, args.run_root, args.requests, args.output), ensure_ascii=False))


if __name__ == "__main__":
    main()
