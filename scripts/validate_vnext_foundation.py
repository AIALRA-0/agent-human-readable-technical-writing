"""Validate the vNext 1.1 candidate foundation without running legacy style tests."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote
from xml.etree import ElementTree

import jsonschema
import yaml
from referencing import Registry, Resource


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_PLAN_SHA256 = "9b6f47ba8702c8c1c2c0bc4e7a75c0739f6b6f8bdce893968e409de3978cbc15"
class ValidationFailure(RuntimeError):
    """Collect one deterministic foundation failure."""


def require(condition: bool, message: str) -> None:
    """Raise a stable failure when one deterministic condition is false."""

    if not condition:
        raise ValidationFailure(message)


def validate_contract_schemas() -> int:
    """Check every JSON Schema and return the number of valid contracts."""

    schema_paths = sorted((ROOT / "contracts").glob("*.schema.json"))
    required_names = {
        "context-case.schema.json", "evaluation-case.schema.json", "forward-candidate.schema.json",
        "forward-request.schema.json", "task-contract.schema.json", "verification-bundle.schema.json",
    }
    actual_names = {path.name for path in schema_paths}
    require(required_names <= actual_names, f"required contract schemas are missing: {sorted(required_names - actual_names)}")
    for path in schema_paths:
        schema = json.loads(path.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)
    return len(schema_paths)


def validate_authoritative_plan() -> int:
    """Verify the saved authority document has not changed since extraction."""

    path = ROOT / "docs" / "design" / "vnext-1.1-authoritative-plan.md"
    raw = path.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == EXPECTED_PLAN_SHA256, "authoritative plan hash mismatch")
    text = raw.decode("utf-8")
    require(text.startswith("# AIALRA 可验证写作系统 vNext 1.1 全量计划书"), "authoritative plan heading mismatch")
    require(len(re.findall(r"^# [0-9]+\.", text, re.MULTILINE)) == 29, "authoritative plan must contain 29 numbered sections")
    require("candidate 案例不得标记为 gold" in text, "candidate-to-gold boundary missing")
    return 1


def validate_yaml_grouping() -> int:
    """Require each YAML document to begin with one explicit classification root."""

    yaml_paths = sorted(
        path
        for parent in (ROOT / "profiles", ROOT / "registries", ROOT / "validators")
        for path in parent.rglob("*.yaml")
    )
    for path in yaml_paths:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        require(isinstance(data, dict), f"{path}: YAML root must be an object")
        require(len(data) == 1, f"{path}: YAML root must contain one classification")
        require(next(iter(data)) in {"profile", "registry"}, f"{path}: invalid YAML classification")
    return len(yaml_paths)


def validate_reviewed_cases() -> int:
    """Validate the exact 11 accepted and 13 rejected anchor lifecycle records."""

    schema = json.loads((ROOT / "contracts" / "evaluation-case.schema.json").read_text(encoding="utf-8"))
    candidate_schema = json.loads((ROOT / "contracts" / "candidate-case.schema.json").read_text(encoding="utf-8"))
    registry = Registry().with_resource(candidate_schema["$id"], Resource.from_contents(candidate_schema))
    validator = jsonschema.Draft202012Validator(schema, registry=registry, format_checker=jsonschema.FormatChecker())
    gold_paths = sorted((ROOT / "evals" / "gold").glob("GOLD-??.json"))
    rejected_paths = sorted((ROOT / "evals" / "rejected").glob("REJECTED-??*.json"))
    paths = gold_paths + rejected_paths
    require(len(gold_paths) == 11, f"expected 11 gold cases, found {len(gold_paths)}")
    require(len(rejected_paths) == 13, f"expected 13 rejected cases, found {len(rejected_paths)}")
    require(not list((ROOT / "evals" / "candidate").glob("CANDIDATE-??.json")), "reviewed round-1 files must not remain candidate")

    for path in paths:
        case = json.loads(path.read_text(encoding="utf-8"))
        errors = sorted(validator.iter_errors(case), key=lambda error: list(error.path))
        require(not errors, f"{path.name}: {errors[0].message if errors else ''}")

        source_ids = {atom["id"] for atom in case["semantics"]["source_atoms"]}
        background_ids = {atom["id"] for atom in case["semantics"]["background_atoms"]}
        inference_ids = {atom["id"] for atom in case["semantics"]["inference_atoms"]}
        supported_ids = {
            atom_id
            for mapping in case["artifact"]["support_map"]
            for atom_id in mapping["supports"]
        }
        require(source_ids <= supported_ids, f"{path.name}: unmapped source atoms {sorted(source_ids - supported_ids)}")
        require(background_ids <= supported_ids, f"{path.name}: unmapped background atoms {sorted(background_ids - supported_ids)}")
        require(inference_ids <= supported_ids, f"{path.name}: unmapped inference atoms {sorted(inference_ids - supported_ids)}")
        answer_without_code = re.sub(r"```.*?```", "", case["artifact"]["answer"], flags=re.DOTALL)
        generated_lines = [line for line in answer_without_code.splitlines() if not line.lstrip().startswith(">")]
        require("。" not in "\n".join(generated_lines), f"{path.name}: generated answer contains Chinese full stop")

        if case["source"]["material_type"] == "image":
            image_path = ROOT / case["source"]["content"]["path"]
            require(image_path.is_file(), f"{path.name}: image asset missing")

    review = json.loads((ROOT / "evals" / "reviews" / "vnext-1.1-round-1.json").read_text(encoding="utf-8"))["review_round"]
    require(len(review["decisions"]) == 12, "round-1 review must preserve 12 explicit decisions")
    return len(paths)


def validate_examples() -> int:
    """Validate Finding and Patch examples, including the sample document digest."""

    for name, schema_name in (("finding.json", "finding.schema.json"), ("patch.json", "patch.schema.json")):
        instance = json.loads((ROOT / "patcher" / "examples" / name).read_text(encoding="utf-8"))
        schema = json.loads((ROOT / "contracts" / schema_name).read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(schema).validate(instance)

    document = (ROOT / "patcher" / "examples" / "sample-document.md").read_text(encoding="utf-8")
    patch = json.loads((ROOT / "patcher" / "examples" / "patch.json").read_text(encoding="utf-8"))
    require(hashlib.sha256(document.encode("utf-8")).hexdigest() == patch["target"]["document_sha256"], "example patch hash mismatch")
    return 2


def validate_skill_entrypoint() -> int:
    """Check the Skill metadata and every local resource loaded by the entrypoint."""

    path = ROOT / "SKILL.md"
    text = path.read_text(encoding="utf-8")
    match = re.match(r"\A---\n(.*?)\n---\n", text, re.DOTALL)
    require(match is not None, "SKILL.md frontmatter missing")
    metadata = yaml.safe_load(match.group(1))
    require(metadata.get("name") == "human-readable-technical-writing", "SKILL.md name mismatch")
    require(isinstance(metadata.get("description"), str) and metadata["description"].strip(), "SKILL.md description missing")

    resource_paths = re.findall(r"`((?:constitution|runtime|contracts|profiles|registries|validators)/[^`]+)`", text)
    require(resource_paths, "SKILL.md resource routing missing")
    for resource_path in resource_paths:
        require((ROOT / resource_path).is_file(), f"SKILL.md resource missing: {resource_path}")
    return len(set(resource_paths))


def validate_relative_links() -> int:
    """Resolve local Markdown links in vNext documentation and bilingual entrypoints."""

    markdown_paths = [ROOT / "README.md", ROOT / "README.en.md"]
    for directory in ("constitution", "runtime", "patcher", "evals", "docs"):
        markdown_paths.extend((ROOT / directory).rglob("*.md"))

    checked = 0
    link_pattern = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
    for path in sorted(set(markdown_paths)):
        text = path.read_text(encoding="utf-8")
        for target in link_pattern.findall(text):
            target = target.strip().strip("<>")
            if not target or target.startswith(("#", "http://", "https://", "mailto:")):
                continue
            file_part = unquote(target.split("#", 1)[0])
            resolved = (path.parent / file_part).resolve()
            require(resolved.exists(), f"{path.relative_to(ROOT)}: broken local link {target}")
            checked += 1
    return checked


def validate_svg_assets() -> int:
    """Reject active, remote, or inaccessible SVG content in candidate assets."""

    paths = sorted((ROOT / "evals").rglob("*.svg"))
    require(len(paths) == 3, f"expected three reviewed or forward SVG assets, found {len(paths)}")
    for path in paths:
        text = path.read_text(encoding="utf-8")
        lowered = text.lower()
        require("<!doctype" not in lowered and "<!entity" not in lowered, f"{path.name}: declarations are forbidden")
        require("<script" not in lowered and "<foreignobject" not in lowered, f"{path.name}: active SVG content is forbidden")
        require(re.search(r"url\((?!#)", lowered) is None and "data:" not in lowered, f"{path.name}: remote or data references are forbidden")
        root = ElementTree.fromstring(text)
        require(root.tag.endswith("svg"), f"{path.name}: invalid SVG root")
        require(root.get("viewBox") is not None or (root.get("width") and root.get("height")), f"{path.name}: stable dimensions missing")
        child_names = {child.tag.rsplit("}", 1)[-1] for child in root}
        require("title" in child_names and "desc" in child_names, f"{path.name}: title and description required")
        for element in root.iter():
            for attribute, value in element.attrib.items():
                require(not attribute.lower().startswith("on"), f"{path.name}: event handler forbidden")
                require(not (attribute.lower().endswith("href") and value), f"{path.name}: href forbidden")
    return len(paths)


def validate_privacy() -> int:
    """Reject common personal paths, session metadata, and credential markers."""

    allowed_suffixes = {".md", ".json", ".jsonl", ".yaml", ".yml", ".py", ".ps1", ".svg"}
    forbidden = [
        re.compile(r"[A-Za-z]:\\Users\\", re.IGNORECASE),
        re.compile(r"[A-Za-z]:\\AIALRA", re.IGNORECASE),
        re.compile(r"\.codex[\\/]sessions", re.IGNORECASE),
        re.compile(r"ghp_[A-Za-z0-9]{20,}"),
        re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    ]
    scanned = 0
    for path in ROOT.rglob("*"):
        if not path.is_file() or ".git" in path.parts or path.suffix.lower() not in allowed_suffixes:
            continue
        text = path.read_text(encoding="utf-8")
        for pattern in forbidden:
            require(not pattern.search(text), f"{path.relative_to(ROOT)}: privacy pattern {pattern.pattern}")
        scanned += 1
    return scanned


def main() -> int:
    """Run vNext-only checks and print one result with source, cause, impact, and next step."""

    checks = [
        ("authoritative_plan", validate_authoritative_plan),
        ("contract_schemas", validate_contract_schemas),
        ("yaml_grouping", validate_yaml_grouping),
        ("reviewed_cases", validate_reviewed_cases),
        ("structured_examples", validate_examples),
        ("skill_resources", validate_skill_entrypoint),
        ("local_links", validate_relative_links),
        ("svg_assets", validate_svg_assets),
        ("privacy_files", validate_privacy),
    ]
    results: dict[str, int] = {}
    try:
        for name, check in checks:
            results[name] = check()
    except (ValidationFailure, jsonschema.ValidationError, jsonschema.SchemaError, json.JSONDecodeError, yaml.YAMLError) as error:
        print(json.dumps({"status": "FAIL", "completed": results, "reason": str(error), "impact": "candidate branch must not be published", "next": "repair the reported deterministic defect and rerun"}, ensure_ascii=False, indent=2))
        return 1

    print(json.dumps({"status": "PASS", "results": results, "reason": "all vNext foundation checks completed without deterministic defects", "impact": "the authority document, contracts, reviewed records, links, assets, and public-file privacy patterns are internally consistent", "next": "run the 220 fixtures, lifecycle validation, contextual cases, and forward-candidate checks"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
