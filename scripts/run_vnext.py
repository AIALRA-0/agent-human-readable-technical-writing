"""Command-line entrypoint for deterministic vNext 1.1 runtime operations."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from patcher.deterministic_committer.committer import PatchError, commit_document, sha256_text
from runtime.engine import compile_contract, report_summary, verify_bundle
from runtime.self_iteration import close_answer


def read_json(path: str) -> dict:
    """Read one UTF-8 JSON input selected by the caller."""

    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> int:
    """Run one explicit operation and emit only structured JSON."""

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("compile", "verify", "report", "close"):
        command = subparsers.add_parser(name)
        command.add_argument("--input", required=True)
        command.add_argument("--output")
    repair = subparsers.add_parser("repair")
    repair.add_argument("--input", required=True)
    repair.add_argument("--output")
    arguments = parser.parse_args()

    try:
        payload = read_json(arguments.input)
        if arguments.command == "compile":
            result = compile_contract(payload)
        elif arguments.command == "verify":
            result = verify_bundle(payload)
        elif arguments.command == "report":
            result = report_summary(payload)
        elif arguments.command == "close":
            final_answer, iterations = close_answer(
                payload["initial_answer"], payload["model"], payload["worker_session_id"],
                payload["manifest"], payload.get("repair_rounds", []),
            )
            result = {"status": iterations["status"], "final_answer": final_answer, "iterations": iterations}
        else:
            document_path = Path(payload["document_path"])
            old_hash = sha256_text(document_path.read_text(encoding="utf-8"))
            node_ranges = {key: tuple(value) for key, value in payload["node_ranges"].items()}
            new_hash = commit_document(document_path, payload["patches"], node_ranges)
            result = {"status": "PASS", "document": document_path.name, "old_sha256": old_hash, "new_sha256": new_hash, "patch_count": len(payload["patches"]), "reason": "全部精确补丁通过摘要、位置、次数和冲突检查", "impact": "只修改了授权范围内的目标文字", "next": "重新运行局部和全文验证"}
    except (KeyError, ValueError, json.JSONDecodeError, jsonschema.ValidationError, PatchError, OSError) as error:
        result = {"status": "FAIL", "reason": str(error), "impact": "请求没有产生可接受的运行时结果", "next": "修复输入或补丁后重新执行"}

    encoded = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if arguments.output:
        Path(arguments.output).write_text(encoded, encoding="utf-8")
    else:
        sys.stdout.write(encoded)
    if result.get("status") == "PASS":
        return 0
    return 2 if result.get("status") == "REVIEW_REQUIRED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
