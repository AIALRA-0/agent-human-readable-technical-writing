"""Create a new writing draft from explicit structure; never overwrite a draft."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from runtime.composition import render_document


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    """Reject duplicate JSON members before a dictionary can discard an original."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("JSON contains a duplicate object member")
        result[key] = value
    return result


def main(argv: list[str] | None = None) -> int:
    """Validate entirely in memory, then exclusively create the requested draft."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--document", type=Path, required=True)
    parser.add_argument("--sources", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--nested-list-spacing", choices=["compact", "host-required"], default="compact")
    args = parser.parse_args(argv)
    try:
        if args.output.exists() or args.output.is_symlink():
            raise ValueError("output already exists; use the exact patch middleware for revisions")
        document = json.loads(args.document.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
        sources = json.loads(args.sources.read_text(encoding="utf-8"), object_pairs_hook=_unique_object) if args.sources else None
        answer = render_document(document, sources=sources,
                                 host_nested_blank=args.nested_list_spacing == "host-required")
        encoded = answer.encode("utf-8")
        with args.output.open("xb") as destination:
            destination.write(encoded)
    except (ValueError, OSError, RecursionError) as exc:
        print(json.dumps({"status": "NOT_COMPOSED", "error": str(exc), "user_acceptance": False}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": "DRAFT_COMPOSED", "output": str(args.output),
                      "semantic_verification": "NOT_PERFORMED", "user_acceptance": False}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
