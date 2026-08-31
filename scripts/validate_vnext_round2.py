"""Validate the 22 lifecycle records and ten unapproved R2 candidates."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import jsonschema
from referencing import Registry, Resource


ROOT = Path(__file__).resolve().parents[1]


class ValidationFailure(RuntimeError):
    """Represent one deterministic round-two validation failure."""


def require(condition: bool, message: str) -> None:
    """Stop at the first deterministic defect with an auditable message."""

    if not condition:
        raise ValidationFailure(message)


def lifecycle_validator() -> jsonschema.Draft202012Validator:
    """Build a validator that resolves the local candidate-case reference."""

    schema = json.loads((ROOT / "contracts" / "evaluation-case.schema.json").read_text(encoding="utf-8"))
    candidate_schema = json.loads((ROOT / "contracts" / "candidate-case.schema.json").read_text(encoding="utf-8"))
    registry = Registry().with_resource(candidate_schema["$id"], Resource.from_contents(candidate_schema))
    return jsonschema.Draft202012Validator(schema, registry=registry, format_checker=jsonschema.FormatChecker())


def load_lifecycle_cases() -> list[tuple[Path, dict[str, Any]]]:
    """Load the exact 2 gold, 10 rejected, and 10 R2 candidate records."""

    paths = (
        sorted((ROOT / "evals" / "gold").glob("GOLD-??.json"))
        + sorted((ROOT / "evals" / "rejected").glob("REJECTED-??.json"))
        + sorted((ROOT / "evals" / "candidate").glob("CANDIDATE-??-R2.json"))
    )
    require(len(paths) == 22, f"expected 22 lifecycle records, found {len(paths)}")
    return [(path, json.loads(path.read_text(encoding="utf-8"))) for path in paths]


def support_coverage(case: dict[str, Any]) -> tuple[int, int, int, int]:
    """Return source and background covered/total counts."""

    source_ids = {atom["id"] for atom in case["semantics"]["source_atoms"]}
    background_ids = {atom["id"] for atom in case["semantics"]["background_atoms"]}
    support_ids = {
        support
        for mapping in case["artifact"]["support_map"]
        for support in mapping.get("supports", [])
    }
    return (
        len(source_ids & support_ids),
        len(source_ids),
        len(background_ids & support_ids),
        len(background_ids),
    )


def visible_text_without_verbatim(answer: str) -> str:
    """Remove fenced code and quoted source before checking generated punctuation."""

    without_fences = re.sub(r"```.*?```", "", answer, flags=re.DOTALL)
    return "\n".join(line for line in without_fences.splitlines() if not line.startswith(">"))


def validate_component_retention(number: str, case: dict[str, Any]) -> list[str]:
    """Check original image, table, or code appears before its explanation."""

    answer = case["artifact"]["answer"]
    material_type = case["source"]["material_type"]
    failures: list[str] = []
    if material_type in {"table", "code"}:
        source = case["source"]["content"]
        if source not in answer:
            failures.append(f"CANDIDATE-{number}-R2: original {material_type} is missing")
        elif answer.index(source) > answer.find("解释") >= 0:
            failures.append(f"CANDIDATE-{number}-R2: original {material_type} must precede explanation")
    elif material_type == "image":
        filename = Path(case["source"]["content"]["path"]).name
        first_nonempty = next((line for line in answer.splitlines() if line.strip()), "")
        if filename not in first_nonempty or not first_nonempty.startswith("!["):
            failures.append(f"CANDIDATE-{number}-R2: original image must be first")
    return failures


def validate_all() -> dict[str, Any]:
    """Run lifecycle, regression, coverage, provenance, and component checks."""

    validator = lifecycle_validator()
    lifecycle_cases = load_lifecycle_cases()
    counts = {"gold": 0, "rejected": 0, "candidate": 0}
    for path, case in lifecycle_cases:
        errors = sorted(validator.iter_errors(case), key=lambda error: list(error.path))
        require(not errors, f"{path.name}: {errors[0].message if errors else ''}")
        counts[case["identity"]["status"]] += 1
    require(counts == {"gold": 2, "rejected": 10, "candidate": 10}, f"lifecycle counts mismatch: {counts}")

    expectations = json.loads(
        (ROOT / "evals" / "deterministic" / "round1-rejected-expectations.json").read_text(encoding="utf-8")
    )["cases"]
    rejected_detected = 0
    r2_passed = 0
    source_covered = source_total = 0
    background_covered = background_total = 0
    hard_failures: list[str] = []

    for number, expectation in sorted(expectations.items()):
        rejected = json.loads((ROOT / "evals" / "rejected" / f"REJECTED-{number}.json").read_text(encoding="utf-8"))
        candidate = json.loads((ROOT / "evals" / "candidate" / f"CANDIDATE-{number}-R2.json").read_text(encoding="utf-8"))
        old_answer = rejected["artifact"]["answer"]
        new_answer = candidate["artifact"]["answer"]

        old_findings = [item for item in expectation["required_all"] if item not in old_answer]
        old_findings.extend(item for item in expectation["forbidden_all"] if item in old_answer)
        if old_findings:
            rejected_detected += 1
        else:
            hard_failures.append(f"REJECTED-{number}: known rejected answer escaped its regression lock")

        new_findings = [item for item in expectation["required_all"] if item not in new_answer]
        new_findings.extend(item for item in expectation["forbidden_all"] if item in new_answer)
        new_findings.extend(validate_component_retention(number, candidate))
        if "flowchart LR" in new_answer:
            new_findings.append("horizontal Mermaid layout without exception")
        if "。" in visible_text_without_verbatim(new_answer):
            new_findings.append("generated text contains Chinese full stop")
        if candidate["artifact"]["self_claims"]:
            new_findings.append("candidate contains ungrounded self claims")
        if candidate["artifact"]["original_case_sha256"] != rejected["artifact"]["original_case_sha256"]:
            new_findings.append("original candidate digest changed")

        reference_ids = {reference["id"] for reference in candidate["source"]["references"]}
        for atom in candidate["semantics"]["background_atoms"]:
            if atom["source_reference"] not in reference_ids:
                new_findings.append(f"background atom {atom['id']} has unresolved source reference")

        source_count, source_expected, background_count, background_expected = support_coverage(candidate)
        source_covered += source_count
        source_total += source_expected
        background_covered += background_count
        background_total += background_expected
        if source_count != source_expected:
            new_findings.append(f"source coverage {source_count}/{source_expected}")
        if background_count != background_expected:
            new_findings.append(f"background coverage {background_count}/{background_expected}")

        if new_findings:
            hard_failures.extend(f"CANDIDATE-{number}-R2: {finding}" for finding in new_findings)
        else:
            r2_passed += 1

    require(rejected_detected == 10, f"rejected regression detected {rejected_detected}/10")
    require(not hard_failures, " | ".join(hard_failures))
    require(source_covered == source_total, f"source coverage {source_covered}/{source_total}")
    require(background_covered == background_total, f"background coverage {background_covered}/{background_total}")
    require(r2_passed == 10, f"R2 hard-rule pass {r2_passed}/10")

    return {
        "lifecycle": counts,
        "lifecycle_total": 22,
        "rejected_regression": "10/10",
        "r2_hard_rule_pass": "10/10",
        "source_coverage": f"{source_covered}/{source_total}",
        "background_coverage": f"{background_covered}/{background_total}",
        "hard_errors": 0,
        "ungrounded_additions": 0,
    }


def main() -> int:
    """Print a causal validation report and return a process status."""

    try:
        results = validate_all()
    except (ValidationFailure, jsonschema.ValidationError, json.JSONDecodeError) as error:
        print(
            json.dumps(
                {
                    "status": "FAIL",
                    "reason": str(error),
                    "impact": "the R2 review packet cannot be generated because at least one lifecycle, provenance, regression, or component invariant failed",
                    "next": "repair the named case or validator and rerun this command",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    print(
        json.dumps(
            {
                "status": "PASS",
                "results": results,
                "reason": "all 22 lifecycle records are valid, every rejected answer triggers its case-specific regression lock, and every R2 answer preserves complete source and background mappings",
                "impact": "the ten R2 answers can enter the second manual review packet but remain unapproved candidates",
                "next": "generate the review packet and wait for explicit user decisions before changing approved_by_user",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
