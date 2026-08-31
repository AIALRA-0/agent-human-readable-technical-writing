<div align="center">

<h1 align="center">AIALRA Verifiable Chinese Writing</h1>

<p><strong>Preserve complete source information, track explanatory additions separately, and produce Chinese that can be read, audited, and repaired locally</strong></p>

<p><strong>Status: vNext 1.1 candidate awaiting C03-R3 and first-round forward review</strong></p>

<p>
  <a href="evals/candidate/REVIEW-PACKET.md">C03-R3 review packet</a> ·
  <a href="evals/forward/round-1/REVIEW-PACKET.md">20 forward cases</a> ·
  <a href="docs/design/vnext-1.1-authoritative-plan.md">Authoritative design</a> ·
  <a href="docs/audits/2026-08-31-vnext-1.1-round-2/audit.md">Round-two audit</a> ·
  <a href="README.md">简体中文</a>
</p>

</div>

This repository maintains the `human-readable-technical-writing` Codex Skill. vNext 1.1 models each task as a base operation plus an augmentation level, then records source claims, user-supplied facts, external background, and inference separately.

Two anchor-review rounds produced 11 gold and 11 rejected cases. Only `CANDIDATE-03-R3` remains undecided, while 20 unseen cases measure whether the rules work beyond the original material.

## 1. Problem and scope

Ordinary rewriting can preserve only the gist. Ordinary explanation can add unsupported background or present an explanatory addition as the source author's conclusion.

vNext 1.1 protects four requirements:

- Source completeness: every source item that carries information remains represented.
- Explanatory provenance: definitions, mechanisms, examples, and inference are tracked separately.
- Bounded repair: a defect in a phrase or segment does not authorize whole-document regeneration.
- User authority: model scores cannot promote a candidate to gold.

The system does not impose a universal Chinese style. Facts, conditions, scope, quantities, provenance, and source completeness are hard boundaries; tone and ordinary narrative order are calibrated through user-approved gold examples.

## 2. Processing path

```mermaid
flowchart TD
    A[Compile operation, augmentation, and audience] --> B{Would ambiguity change facts, scope, or output size}
    B -->|Yes| C[Ask once with choices, recommendation, and impact]
    C --> A
    B -->|No| D[Register source atoms, background, and inference]
    D --> E[Build segment contracts and coverage]
    E --> F[Render the target text]
    F --> G[Run deterministic and structural validation]
    G --> H[Create digest-bound exact patches]
    H --> I[Validate the affected area and whole document]
    I --> J[User review]
    J -->|Accept| K[Promote to gold]
    J -->|Reject| L[Record as rejected and create another candidate]
```

<p align="center">Figure 2.1 vNext 1.1 path from task compilation to user-approved gold</p>

The first half protects provenance and coverage. The second half makes deterministic defects locatable and reversible. Automated checks can create a review packet, but only an explicit user decision can create gold.

## 3. Task contract

| Dimension | Values | Decision |
| --- | --- | --- |
| Base operation | `TRANSFORM`, `TRANSLATE`, `COMPRESS`, `EXPLAIN`, `GENERATE`, `FORMAT_ONLY` | What to do with the source material |
| Augmentation | `NONE`, `GLOSS`, `EXPLANATORY`, `TEACHING`, `RESEARCHED` | How much explanation outside the source may be added |

<p align="center">Table 3.1 Independent task dimensions</p>

For example, `TRANSLATE + EXPLANATORY` means complete translation plus the background and mechanism needed to understand the source. Additions retain separate provenance and cannot compensate for omitted source content.

## 4. Provenance and coverage

The intermediate representation distinguishes:

- `SOURCE`: directly stated by the source and linked to its location.
- `USER_SUPPLIED`: supplied by the user for the active task.
- `EXTERNAL_BACKGROUND`: added for understanding and linked to a reference.
- `INFERENCE`: derived from registered material with evidence and confidence retained.

`CANDIDATE-03-R3` currently maps three of three source atoms and five of five background atoms. This proves structural allocation only; it does not prove that the user accepts the wording.

## 5. Executable runtime

The local entry point provides:

- `compile`: fill deterministic defaults and validate a task contract.
- `verify`: check provenance, segments, terms, components, support maps, and evidence boundaries.
- `repair`: validate an exact patch and perform the smallest authorized replacement.
- `report`: return `PASS`, `FAIL`, or `REVIEW_REQUIRED` with cause, impact, and next action.

```powershell
python scripts/run_vnext.py --help # List compile, verify, repair, and report without changing a file
```

The runtime does not infer arbitrary natural-language meaning. The Agent builds the semantic model; deterministic code checks structure, references, coverage, and exact edits.

## 6. Validation

Use Python 3.12 or a compatible version with `jsonschema` and `PyYAML`.

```powershell
python scripts/validate_vnext_foundation.py # Check the authority digest, contracts, grouped YAML, links, SVG, and public-file privacy patterns

python scripts/run_vnext_fixtures.py # Execute all 176 deterministic positive and negative cases

python scripts/validate_vnext_round2.py # Check 23 lifecycle records, approved snapshots, rejected regressions, and C03-R3 mappings

python scripts/validate_context_cases.py # Check 12 contextual fixtures without automating semantic decisions

python scripts/validate_forward_round1.py # Check 20 first-attempt candidates, digests, declared mappings, source components, and privacy

python -m unittest discover -s tests -p "test_deterministic_committer.py" -v # Execute 18 digest, range, conflict, rollback, and atomic-write tests

python -m unittest discover -s tests -p "test_vnext_runtime.py" -v # Execute 11 compile, verify, repair, and report tests

python scripts/build_candidate_review_packet.py # Regenerate the C03-R3 review packet

python scripts/build_forward_review_packet.py # Regenerate the 20-case forward-review packet without changing answers
```

Current local evidence:

- All 176 deterministic fixtures match their reviewed expectations.
- All 23 lifecycle records are valid: 11 gold, 11 rejected, and one candidate.
- Nine new gold answers have zero digest changes from their reviewed snapshots.
- All 12 contextual fixtures prohibit automatic semantic decisions.
- All 18 exact-patch tests and all 11 runtime tests pass.
- Three of the 20 first-attempt forward answers contain a prohibited Chinese full stop. The answers remain unchanged as failure evidence, round one is `FAIL`, and round-two generation is blocked.

These numbers do not constitute user acceptance.

## 7. Repository map

| Directory | Responsibility |
| --- | --- |
| `constitution/` | Source priority, provenance, rule levels, and user-gold boundary |
| `runtime/` | Task compilation, source understanding, blueprinting, rendering, validation, and repair |
| `contracts/` | Schemas for tasks, provenance, segments, support, findings, patches, and lifecycle cases |
| `profiles/` | Operations, augmentation, genres, media, audiences, components, and Lucas preferences |
| `registries/` | Terms, units, and protected patterns |
| `validators/` | Deterministic rules, contextual candidates, and advisory checks |
| `patcher/` | Patch planning, conflict handling, transaction validation, and exact commits |
| `evals/` | Candidate, gold, rejected, and deterministic cases |

<p align="center">Table 7.1 vNext 1.1 directory responsibilities</p>

Read the [authoritative design](docs/design/vnext-1.1-authoritative-plan.md) for the complete model and the [round-two audit](docs/audits/2026-08-31-vnext-1.1-round-2/audit.md) for evidence, gaps, and re-review conditions.

## 8. Privacy and security

The public repository stores synthetic cases, redacted technical feedback, repository-relative paths, and public references. It does not store raw conversations, account data, personal absolute paths, credentials, or unreviewed screenshots.

An independent publication safety gate runs before every remote push. If a real secret reaches a remote, routine updates stop until the credential is rotated and the incident process addresses history.

## 9. Current boundary and next step

`main` remains frozen until C03-R3 and both forward rounds pass, and the candidate Skill is not installed into the active user Skill directory.

The next step is to review [C03-R3](evals/candidate/REVIEW-PACKET.md) and the [first 20 forward candidates](evals/forward/round-1/REVIEW-PACKET.md). Round one must reach at least 18 acceptances with zero factual hard errors before round two is generated.

## 10. License

The repository uses the [MIT License](LICENSE). Third-party methods and copied material are listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
