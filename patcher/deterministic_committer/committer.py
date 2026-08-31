"""Apply SHA-256-bound exact replacements without regenerating a document.

The committer intentionally supports only literal replacement.  It validates the
original document, node ranges, occurrence counts, and edit overlap before any
file is written.  Optional validators run against the complete in-memory result.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence


class PatchError(ValueError):
    """Raised when a patch transaction cannot be proven safe to apply."""


Validator = Callable[[str], Sequence[str] | None]


@dataclass(frozen=True)
class _Edit:
    """One literal character-range replacement calculated on the old document."""

    patch_id: str
    start: int
    end: int
    old_text: str
    new_text: str


def sha256_text(text: str) -> str:
    """Return the UTF-8 SHA-256 used by patch contracts."""

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _require_mapping(value: object, label: str) -> Mapping[str, object]:
    """Reject malformed contract sections before field access."""

    if not isinstance(value, Mapping):
        raise PatchError(f"{label} must be an object")
    return value


def _find_occurrences(text: str, needle: str) -> list[int]:
    """Find non-overlapping literal occurrences in deterministic left-to-right order."""

    positions: list[int] = []
    cursor = 0
    while True:
        position = text.find(needle, cursor)
        if position < 0:
            return positions
        positions.append(position)
        cursor = position + len(needle)


def _prepare_edits(
    text: str,
    patches: Iterable[Mapping[str, object]],
    node_ranges: Mapping[str, tuple[int, int]],
) -> list[_Edit]:
    """Validate every patch against the same old document and build edit ranges."""

    document_hash = sha256_text(text)
    edits: list[_Edit] = []

    for patch in patches:
        identity = _require_mapping(patch.get("identity"), "identity")
        target = _require_mapping(patch.get("target"), "target")
        replacement = _require_mapping(patch.get("replacement"), "replacement")
        authorization = _require_mapping(patch.get("authorization"), "authorization")
        verification = _require_mapping(patch.get("verification"), "verification")

        patch_id = str(identity.get("patch_id", ""))
        if not patch_id or not identity.get("finding_id"):
            raise PatchError("identity must include patch_id and finding_id")
        if identity.get("operation") != "replace_exact":
            raise PatchError(f"{patch_id}: unsupported operation")
        if not authorization.get("reason") or authorization.get("repair_scope") not in {
            "token",
            "phrase",
            "sentence",
            "segment",
            "adjacent_segments",
            "section",
            "blueprint",
        }:
            raise PatchError(f"{patch_id}: invalid authorization")
        if not isinstance(authorization.get("preserve"), list):
            raise PatchError(f"{patch_id}: preserve must be a list")
        rerun_validators = verification.get("rerun_validators")
        if not isinstance(rerun_validators, list) or not rerun_validators:
            raise PatchError(f"{patch_id}: rerun_validators must be a non-empty list")
        if target.get("document_sha256") != document_hash:
            raise PatchError(f"{patch_id}: document hash mismatch")

        node_id = str(target.get("node_id", ""))
        if node_id not in node_ranges:
            raise PatchError(f"{patch_id}: unknown node_id {node_id}")
        node_start, node_end = node_ranges[node_id]
        if not (0 <= node_start <= node_end <= len(text)):
            raise PatchError(f"{patch_id}: invalid node range")

        old_text = replacement.get("old_text")
        new_text = replacement.get("new_text")
        expected = replacement.get("expected_occurrences")
        if not isinstance(old_text, str) or not old_text:
            raise PatchError(f"{patch_id}: old_text must be non-empty")
        if not isinstance(new_text, str):
            raise PatchError(f"{patch_id}: new_text must be text")
        if not isinstance(expected, int) or isinstance(expected, bool) or expected < 1:
            raise PatchError(f"{patch_id}: expected_occurrences must be a positive integer")

        positions = _find_occurrences(text, old_text)
        if len(positions) != expected:
            raise PatchError(
                f"{patch_id}: expected {expected} occurrence(s), found {len(positions)}"
            )
        if any(position < node_start or position + len(old_text) > node_end for position in positions):
            raise PatchError(f"{patch_id}: old_text occurs outside the authorized node")

        edits.extend(
            _Edit(
                patch_id=patch_id,
                start=position,
                end=position + len(old_text),
                old_text=old_text,
                new_text=new_text,
            )
            for position in positions
        )

    edits.sort(key=lambda edit: (edit.start, edit.end, edit.patch_id))
    for previous, current in zip(edits, edits[1:]):
        if current.start < previous.end:
            raise PatchError(
                f"overlapping patches: {previous.patch_id} and {current.patch_id}"
            )
    return edits


def apply_transaction(
    text: str,
    patches: Iterable[Mapping[str, object]],
    node_ranges: Mapping[str, tuple[int, int]],
    validators: Iterable[Validator] = (),
) -> str:
    """Return the fully validated result without changing any file."""

    edits = _prepare_edits(text, patches, node_ranges)
    result = text

    # Reverse-order replacement preserves offsets calculated on the old document.
    for edit in reversed(edits):
        if result[edit.start : edit.end] != edit.old_text:
            raise PatchError(f"{edit.patch_id}: old text changed during transaction")
        result = result[: edit.start] + edit.new_text + result[edit.end :]

    failures: list[str] = []
    for validator in validators:
        failures.extend(validator(result) or ())
    if failures:
        raise PatchError("validator failure: " + " | ".join(failures))
    return result


def commit_document(
    path: str | os.PathLike[str],
    patches: Iterable[Mapping[str, object]],
    node_ranges: Mapping[str, tuple[int, int]],
    validators: Iterable[Validator] = (),
) -> str:
    """Validate the full transaction, then atomically replace one UTF-8 document."""

    document_path = Path(path)
    original = document_path.read_text(encoding="utf-8")
    result = apply_transaction(original, patches, node_ranges, validators)

    # The temporary file lives beside the target so os.replace stays on one volume.
    descriptor, temporary_name = tempfile.mkstemp(
        dir=document_path.parent,
        prefix=f".{document_path.name}.",
        suffix=".tmp",
        text=True,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(result)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, document_path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise

    return sha256_text(result)
