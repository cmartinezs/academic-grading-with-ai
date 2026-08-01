"""Legacy export model: reads the normalized export produced by
``export-publication-data.py`` (the legacy flow).

This module only parses and represents the legacy semantics; it never recalculates
grades. It is the entry point of the C1 legacy adapter.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .errors import LegacyCourseMismatchError, MissingLegacyExportError

COURSE_FILE = "course.json"
STUDENTS_FILE = "students.json"
EVALUATIONS_FILE = "evaluations.json"
RESULTS_FILE = "results.json"
COURSE_SUMMARY_FILE = "course-summary.json"
MANIFEST_FILE = "manifest.json"

COURSE_FILES = (COURSE_FILE, STUDENTS_FILE, EVALUATIONS_FILE, RESULTS_FILE, COURSE_SUMMARY_FILE)

LEGACY_SCHEMA_VERSION = 1


@dataclass
class LegacyExport:
    """Parsed representation of ``exports/publication-input/`` for one course."""

    export_dir: Path
    course: dict = field(default_factory=dict)
    students: list[dict] = field(default_factory=list)
    evaluations: list[dict] = field(default_factory=list)
    results: list[dict] = field(default_factory=list)
    course_summary: dict = field(default_factory=dict)
    manifest: dict = field(default_factory=dict)
    source_hashes: list[dict] = field(default_factory=list)

    def course_id(self) -> str:
        """Best-effort course identifier declared by the legacy export."""
        value = None
        for candidate in (
            self.manifest.get("course", {}).get("id"),
            self.course.get("course", {}).get("name"),
            self.course.get("course", {}).get("id"),
        ):
            if value is None and candidate:
                value = str(candidate)
        return value or ""

    def course_title(self) -> str:
        for key in ("title", "name"):
            value = self.course.get("course", {}).get(key)
            if value:
                return str(value)
        return ""

    def effective_defaults(self) -> dict:
        return dict(self.course.get("defaults", {}) or {})

    def evaluation_weights(self) -> dict[str, float]:
        weights: dict[str, float] = {}
        for evaluation in self.evaluations:
            weight = evaluation.get("weight")
            if weight is not None:
                weights[str(evaluation["id"])] = float(weight)
        return weights


def _sha256(path: Path) -> str:
    import hashlib

    hasher = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _normalized_sha256(path: Path) -> str:
    """sha256 of the JSON document with volatile operational keys stripped.

    ``generatedAt`` is written by the legacy export at build time; normalizing it
    keeps the source hash stable across regenerations (P0 hashes, item 7).
    """
    from .jsonutil import normalized_sha256_bytes

    return normalized_sha256_bytes(path.read_bytes())


def _load_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise MissingLegacyExportError(f"Missing legacy export file: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise MissingLegacyExportError(
            f"Invalid legacy export file {path.name}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise MissingLegacyExportError(
            f"Legacy export file must be a JSON object: {path.name}"
        )
    return payload


def default_legacy_export_dir(workspace_root: Path) -> Path:
    return Path(workspace_root) / "exports" / "publication-input"


def load_legacy_export(
    export_dir: Path | str | None = None,
    workspace_root: Path | str | None = None,
) -> LegacyExport:
    """Load the legacy export from an explicit dir or the workspace default.

    ``workspace_root`` is only used when ``export_dir`` is None.
    """
    if export_dir is not None:
        resolved = Path(export_dir)
    elif workspace_root is not None:
        resolved = default_legacy_export_dir(workspace_root)
    else:
        raise MissingLegacyExportError("No legacy export directory configured")

    course_dir = Path(resolved) / "course"
    if not course_dir.is_dir():
        raise MissingLegacyExportError(
            "Legacy export missing course/ directory in the configured legacy "
            "export (run ./scripts/export-results.sh)"
        )

    source_hashes: list[dict] = []
    for name in COURSE_FILES:
        path = course_dir / name
        if not path.exists():
            raise MissingLegacyExportError(f"Legacy export missing course/{name}")
        source_hashes.append(
            {
                "ref": f"legacy-export/{name}",
                "sha256": _normalized_sha256(path),
                "size": path.stat().st_size,
            }
        )
    manifest_path = Path(resolved) / MANIFEST_FILE
    if manifest_path.exists():
        source_hashes.append(
            {
                "ref": f"legacy-export/{MANIFEST_FILE}",
                "sha256": _normalized_sha256(manifest_path),
                "size": manifest_path.stat().st_size,
            }
        )
        manifest = _load_json(manifest_path)
    else:
        manifest = {}

    course = _load_json(course_dir / COURSE_FILE)
    students = _load_json(course_dir / STUDENTS_FILE).get("items", [])
    evaluations = _load_json(course_dir / EVALUATIONS_FILE).get("items", [])
    results = _load_json(course_dir / RESULTS_FILE).get("items", [])
    course_summary = _load_json(course_dir / COURSE_SUMMARY_FILE)

    return LegacyExport(
        export_dir=Path(resolved),
        course=course,
        students=students,
        evaluations=evaluations,
        results=results,
        course_summary=course_summary,
        manifest=manifest,
        source_hashes=source_hashes,
    )


def require_course_matches(legacy: LegacyExport, section_id: str) -> None:
    """Fail closed when the legacy export does not correspond to the section."""
    declared = legacy.course_id()
    if declared and declared != section_id:
        raise LegacyCourseMismatchError(
            f"Legacy export course {declared!r} does not match section {section_id!r}."
        )


def resolve_section_code_from_env() -> Optional[str]:
    return os.environ.get("SECTION_CODE", "").strip() or None
