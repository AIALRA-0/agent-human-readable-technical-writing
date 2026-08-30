#!/usr/bin/env python3
"""Read-only audit for public repositories and explicitly approved samples."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence


DEFAULT_EXTENSIONS = {
    ".md", ".mdx", ".txt", ".rst", ".tsx", ".ts", ".jsx", ".js",
    ".py", ".ps1", ".json", ".jsonl", ".yaml", ".yml", ".toml",
    ".html", ".vue", ".svelte", ".java", ".go", ".rs", ".cs",
}
DEFAULT_EXCLUDES = {
    ".git", "node_modules", "dist", "build", ".next", "coverage",
    ".venv", "venv", "__pycache__", ".cache", "vendor",
}
SECRET_PATTERNS = (
    re.compile(r"(?i)(?:api[_-]?key|token|secret|password)\s*[:=]\s*['\"]?[^\s'\"]+"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"(?i)authorization:\s*bearer\s+\S+"),
)
ABSOLUTE_PATH_PATTERNS = (
    re.compile(r"(?i)(?<![A-Za-z0-9_])[A-Z]:[\\/][^\s；，：]+"),
    re.compile(r"(?<![A-Za-z0-9_])/(?:Users|home)/[^\s；，：]+"),
)


@dataclass(frozen=True)
class RootSpec:
    label: str
    path: Path
    source: str


@dataclass(frozen=True)
class Sample:
    term: str
    category: str
    severity: str
    path: str
    line: int
    zone: str
    excerpt: str


def read_config(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        vocabulary = data["vocabulary"]
        if not isinstance(vocabulary.get("terms"), list):
            raise ValueError("vocabulary.terms must be an array")
        if not isinstance(vocabulary.get("patterns"), list):
            raise ValueError("vocabulary.patterns must be an array")
        return data
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError) as exc:
        raise ValueError(f"cannot read scanner configuration: {exc}") from exc


def get_github_remote(path: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(path), "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise ValueError("a repository root does not have an origin remote")
    remote = result.stdout.strip()
    if not re.match(r"^(?:https://github\.com/|git@github\.com:)[^/]+/[^/]+(?:\.git)?$", remote):
        raise ValueError("a repository root is not backed by a GitHub origin")
    return remote


def repository_label(remote: str) -> str:
    value = re.sub(r"^(?:https://github\.com/|git@github\.com:)", "", remote)
    return value.removesuffix(".git")


def build_public_roots(paths: Sequence[Path], confirmed: bool) -> list[RootSpec]:
    if paths and not confirmed:
        raise ValueError("public repository scanning requires --confirm-public")
    roots: list[RootSpec] = []
    for path in paths:
        resolved = path.expanduser().resolve()
        if not resolved.is_dir():
            raise ValueError("a repository root does not exist or is not a directory")
        remote = get_github_remote(resolved)
        roots.append(RootSpec(label=repository_label(remote), path=resolved, source="public_github_repository"))
    return roots


def build_approved_samples(paths: Sequence[Path]) -> list[RootSpec]:
    samples: list[RootSpec] = []
    for index, path in enumerate(paths, 1):
        resolved = path.expanduser().resolve()
        if not resolved.is_file():
            raise ValueError("an approved sample does not exist or is not a file")
        samples.append(RootSpec(label=f"approved-sample-{index}", path=resolved, source="explicitly_approved_sample"))
    return samples


def iter_files(roots: Sequence[RootSpec], extensions: set[str], excludes: set[str]) -> Iterable[tuple[RootSpec, Path]]:
    seen: set[Path] = set()
    for root in roots:
        if root.path.is_file():
            if root.path.suffix.lower() in extensions and root.path not in seen:
                seen.add(root.path)
                yield root, root.path
            continue
        for dirpath, dirnames, filenames in os.walk(root.path):
            dirnames[:] = [name for name in dirnames if name not in excludes]
            current = Path(dirpath)
            for filename in filenames:
                path = current / filename
                if path.suffix.lower() not in extensions or path in seen:
                    continue
                seen.add(path)
                yield root, path


def relative_report_path(root: RootSpec, path: Path) -> str:
    if root.path.is_file():
        return f"{root.label}/{root.path.name}"
    return f"{root.label}/{path.relative_to(root.path).as_posix()}"


def redact_excerpt(value: str) -> str:
    redacted = value
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub("<REDACTED_SECRET>", redacted)
    for pattern in ABSOLUTE_PATH_PATTERNS:
        redacted = pattern.sub("<REDACTED_PATH>", redacted)
    return redacted


def trim_excerpt(line: str, term: str, width: int = 180) -> str:
    clean = redact_excerpt(re.sub(r"\s+", " ", line).strip())
    if len(clean) <= width:
        return clean
    index = clean.find(term)
    if index < 0:
        return clean[:width] + "…"
    left = max(0, index - width // 2)
    right = min(len(clean), left + width)
    return ("…" if left else "") + clean[left:right] + ("…" if right < len(clean) else "")


def markdown_zones(lines: Sequence[str]) -> list[str]:
    zones: list[str] = []
    fence: str | None = None
    for line in lines:
        marker = re.match(r"^\s*(```+|~~~+)", line)
        if marker:
            token = marker.group(1)[0]
            if fence is None:
                fence = token
            elif fence == token:
                fence = None
            zones.append("fence")
            continue
        zones.append("fence" if fence is not None else "prose")
    return zones


def classify_zones(path: Path, lines: Sequence[str]) -> list[str]:
    if path.suffix.lower() in {".md", ".mdx", ".txt", ".rst"}:
        return markdown_zones(lines)
    zones: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(("//", "#", "/*", "*", "<!--", "--")):
            zones.append("comment")
        elif re.search(r"['\"`].+?['\"`]", line):
            zones.append("string_or_ui_copy")
        else:
            zones.append("code_or_identifier")
    return zones


def audit(roots: Sequence[RootSpec], config: dict, max_samples: int, extensions: set[str], excludes: set[str]) -> dict:
    vocabulary = config["vocabulary"]
    regex_rules: list[tuple[dict, re.Pattern[str]]] = []
    for rule in vocabulary["patterns"]:
        try:
            regex_rules.append((rule, re.compile(rule["pattern"])))
        except (KeyError, re.error) as exc:
            raise ValueError(f"invalid pattern definition: {exc}") from exc

    occurrence_count = Counter()
    matching_files: dict[str, set[str]] = defaultdict(set)
    zone_count: dict[str, Counter] = defaultdict(Counter)
    samples: list[Sample] = []
    sample_count = Counter()
    regex_count = Counter()
    file_count = 0
    unreadable: list[dict] = []

    for root, path in iter_files(roots, extensions, excludes):
        file_count += 1
        report_path = relative_report_path(root, path)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            unreadable.append({"path": report_path, "error_type": type(exc).__name__})
            continue
        lines = text.splitlines()
        zones = classify_zones(path, lines)
        for term_rule in vocabulary["terms"]:
            term = term_rule["surface"]
            total = text.count(term)
            if total == 0:
                continue
            occurrence_count[term] += total
            matching_files[term].add(report_path)
            for line_number, line in enumerate(lines, 1):
                count = line.count(term)
                if count == 0:
                    continue
                zone = zones[line_number - 1]
                zone_count[term][zone] += count
                if sample_count[term] < max_samples:
                    samples.append(Sample(
                        term=term,
                        category=term_rule["category"],
                        severity=term_rule["severity"],
                        path=report_path,
                        line=line_number,
                        zone=zone,
                        excerpt=trim_excerpt(line, term),
                    ))
                    sample_count[term] += 1
        for rule, pattern in regex_rules:
            regex_count[rule["name"]] += len(pattern.findall(text))

    term_rows = []
    for rule in vocabulary["terms"]:
        term = rule["surface"]
        term_rows.append({
            "term": term,
            "category": rule["category"],
            "severity": rule["severity"],
            "matching_files": len(matching_files[term]),
            "occurrences": occurrence_count[term],
            "zones": dict(zone_count[term]),
        })
    term_rows.sort(key=lambda row: (-row["matching_files"], -row["occurrences"], row["term"]))
    return {
        "scope": [{"label": root.label, "source": root.source} for root in roots],
        "files_considered": file_count,
        "unreadable_files": unreadable,
        "terms": term_rows,
        "samples": [asdict(sample) for sample in samples],
        "pattern_summary": dict(regex_count),
        "counting_note": "matching_files counts unique files and occurrences counts literal matches; a match requires contextual review and does not prove an error",
    }


def write_report(result: dict, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("roots", nargs="*", type=Path)
    parser.add_argument("--confirm-public", action="store_true")
    parser.add_argument("--approved-sample", action="append", default=[], type=Path)
    parser.add_argument("--config", type=Path, default=Path(__file__).resolve().parents[1] / "config" / "suspect-patterns.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-samples", type=int, default=4)
    parser.add_argument("--extension", action="append", default=[])
    parser.add_argument("--exclude", action="append", default=[])
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        roots = build_public_roots(args.roots, args.confirm_public)
        roots.extend(build_approved_samples(args.approved_sample))
        if not roots:
            raise ValueError("provide a confirmed public repository or an explicitly approved sample")
        config = read_config(args.config)
        extensions = set(DEFAULT_EXTENSIONS)
        extensions.update(ext if ext.startswith(".") else "." + ext for ext in args.extension)
        result = audit(roots, config, max(1, args.max_samples), extensions, DEFAULT_EXCLUDES | set(args.exclude))
        write_report(result, args.output)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({
        "status": "PASS",
        "files_considered": result["files_considered"],
        "unreadable_file_count": len(result["unreadable_files"]),
        "report": args.output.name,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
