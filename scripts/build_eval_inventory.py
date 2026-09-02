"""Build deterministic inventories for version-controlled evaluation JSONL files."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def build(directory: Path, grouping_key: str) -> dict[str, object]:
    """Summarize exact files, hashes, row counts, and the declared distribution."""

    files: list[dict[str, object]] = []
    aggregate: Counter[str] = Counter()
    total = 0
    for path in sorted(directory.glob("*.jsonl")):
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        counts = Counter(str(row[grouping_key]) for row in rows)
        aggregate.update(counts)
        total += len(rows)
        files.append({
            "path": path.name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "rows": len(rows),
            "distribution": dict(sorted(counts.items())),
        })
    return {
        "schema_version": 1,
        "grouping_key": grouping_key,
        "total_rows": total,
        "distribution": dict(sorted(aggregate.items())),
        "files": files,
    }


def main() -> int:
    """Regenerate both inventories from their committed JSONL sources."""

    targets = [
        (ROOT / "evals" / "deterministic", "category"),
        (ROOT / "evals" / "contextual", "dimension"),
    ]
    reports = {}
    for directory, key in targets:
        inventory = build(directory, key)
        target = directory / "inventory.json"
        target.write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        reports[directory.name] = inventory["total_rows"]
    print(json.dumps({"status": "PASS", "inventories": reports}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
