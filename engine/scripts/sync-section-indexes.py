#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def resolve_section_code(explicit: str | None = None) -> str:
    if explicit:
        return explicit

    env_section = os.environ.get("SECTION_CODE", "").strip()
    if env_section:
        return env_section

    candidates = [
        path.name
        for path in sorted((ROOT / "evaluations").iterdir())
        if path.is_dir() and (path / "config.json").exists()
    ] if (ROOT / "evaluations").exists() else []

    if len(candidates) == 1:
        return candidates[0]

    if not candidates:
        raise SystemExit("Error: no active section was found. Define SECTION_CODE or use --section.")

    raise SystemExit("Error: more than one section exists in evaluations/. Define SECTION_CODE or use --section.")


def load_json(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"No existe {path.relative_to(ROOT)}")
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Syncs the indexes for a section in evaluations/<section_code>.")
    parser.add_argument("--section")
    args = parser.parse_args()

    section_code = resolve_section_code(args.section)
    section_dir = ROOT / "evaluations" / section_code
    if not section_dir.exists():
        raise SystemExit(f"No existe {section_dir.relative_to(ROOT)}")

    config_path = section_dir / "config.json"
    students_path = section_dir / "students.json"
    current_config = load_json(config_path)
    current_students = load_json(students_path)

    course = current_config.get("course", {})
    defaults = current_config.get("defaults", {})
    access = current_config.get("access", {})
    metadata_by_id = current_config.get("evaluations", {})
    students = current_students.get("students", [])

    section_config = {
        "schemaVersion": 1,
        "sectionCode": section_code,
        "course": course,
        "defaults": defaults,
        "access": access,
        "evaluations": metadata_by_id,
    }

    students_payload = {
        "schemaVersion": 1,
        "sectionCode": section_code,
        "students": students,
    }

    evaluations_payload = {
        "schemaVersion": 1,
        "sectionCode": section_code,
        "evaluations": [],
    }
    for ev_dir in sorted(path for path in section_dir.iterdir() if path.is_dir() and path.name.startswith("EV")):
        ev_id = ev_dir.name
        metadata = metadata_by_id.get(ev_id, {})
        evaluations_payload["evaluations"].append(
            {
                "id": ev_id,
                "title": metadata.get("title", ev_id),
                "type": metadata.get("type", defaults.get("evaluationType", "regular")),
                "date": metadata.get("date"),
                "weight": metadata.get("weight"),
                "forms": metadata.get("forms", []),
                "folder": ev_id,
                "files": {
                    "base": f"{ev_id}/base.md",
                    "plan": f"{ev_id}/plan.md",
                    "rubric": f"{ev_id}/rubric.md",
                },
            }
        )

        ev_students_path = ev_dir / "students.json"
        ev_students = load_json(ev_students_path) if ev_students_path.exists() else {"students": []}
        evaluation_assignments = []
        for student in ev_students.get("students", []):
            student_id = student.get("rut")
            if not student_id:
                continue
            evaluation_assignments.append({
                "studentId": str(student_id),
                "assignedForm": student.get("assignedForm"),
                "status": student.get("status"),
            })
        write_json(
            ev_dir / "assignments.json",
            {
                "schemaVersion": 1,
                "sectionCode": section_code,
                "evaluationId": ev_id,
                "assignments": evaluation_assignments,
            },
        )

    grades_payload = {
        "schemaVersion": 1,
                "sectionCode": section_code,
        "grades": [],
    }
    export_results = ROOT / "exports" / "publication-input" / "course" / "results.json"
    if export_results.exists():
        raw_results = load_json(export_results)
        for item in raw_results.get("items", []):
            grade = dict(item)
            result_path = grade.get("resultPath")
            if isinstance(result_path, str) and result_path.startswith("evaluations/EV"):
                grade["resultPath"] = result_path.replace("evaluations/", f"evaluations/{args.section}/", 1)
            grades_payload["grades"].append(grade)

    write_json(config_path, section_config)
    write_json(students_path, students_payload)
    write_json(section_dir / "evaluations.json", evaluations_payload)
    legacy_assignments_path = section_dir / "assignments.json"
    if legacy_assignments_path.exists():
        legacy_assignments_path.unlink()
    write_json(section_dir / "grades.json", grades_payload)


if __name__ == "__main__":
    main()
