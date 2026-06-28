#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def value_from_row(row: dict[str, str | None], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value is not None:
            cleaned = value.strip()
            if cleaned:
                return cleaned
    return ""


def parse_assignments_csv(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("The CSV does not contain headers.")

        required_aliases = {
            "rut": ("rut",),
            "assignedForm": ("assignedForm", "form", "forma"),
        }

        missing = []
        for logical_key, aliases in required_aliases.items():
            if not any(alias in reader.fieldnames for alias in aliases):
                missing.append(logical_key)
        if missing:
            raise ValueError(
                "The CSV must include these columns: rut and assignedForm "
                "(form or forma are also accepted). "
                f"Missing: {', '.join(missing)}"
            )

        assignments: list[dict[str, str]] = []
        seen_ruts: set[str] = set()
        for index, row in enumerate(reader, start=2):
            rut = value_from_row(row, "rut")
            assigned_form = value_from_row(row, "assignedForm", "form", "forma").upper()

            if not rut and not assigned_form:
                continue
            if not rut:
                raise ValueError(f"Row {index}: missing rut.")
            if not assigned_form:
                raise ValueError(f"Row {index}: missing assignedForm/form/forma for rut {rut}.")
            if rut in seen_ruts:
                raise ValueError(f"Row {index}: duplicate rut in the CSV: {rut}.")

            seen_ruts.add(rut)
            assignments.append({"rut": rut, "assignedForm": assigned_form})

    return assignments


def build_student_payload(source: dict, assigned_form: str, existing: dict | None = None) -> dict:
    existing = existing or {}
    payload = {
        "order": source.get("order", existing.get("order")),
        "rut": source.get("rut", existing.get("rut")),
        "lastName": source.get("lastName", existing.get("lastName")),
        "secondLastName": source.get("secondLastName", existing.get("secondLastName", "")),
        "names": source.get("names", existing.get("names")),
        "fullName": source.get("fullName", existing.get("fullName")),
        "repoUrl": source.get("repoUrl", existing.get("repoUrl")),
        "avaUser": source.get("avaUser", existing.get("avaUser")),
        "assignedForm": assigned_form,
    }
    for key, value in existing.items():
        if key not in payload:
            payload[key] = value
    return payload


def apply_assignments(
    payload: dict, assignments: list[dict[str, str]], course_payload: dict | None = None
) -> tuple[dict, int, int]:
    forms = payload.get("forms", [])
    students = payload.get("students", [])
    available_form_ids = {form.get("id") for form in forms if form.get("id")}

    students_by_rut = {student.get("rut"): student for student in students if student.get("rut")}
    course_students_by_rut = {
        student.get("rut"): student
        for student in (course_payload or {}).get("students", [])
        if student.get("rut")
    }
    next_students = []
    updated_count = 0
    created_count = 0

    for item in assignments:
        rut = item["rut"]
        assigned_form = item["assignedForm"]

        if assigned_form not in available_form_ids:
            valid = ", ".join(sorted(available_form_ids))
            raise ValueError(f"Invalid form for {rut}: {assigned_form}. Valid forms: {valid}")
        existing = students_by_rut.get(rut)
        source = course_students_by_rut.get(rut) or existing
        if not source:
            raise ValueError(
                f"Rut {rut} does not exist in the master roster or this evaluation's students.json."
            )

        student = build_student_payload(source, assigned_form, existing)
        if not existing:
            created_count += 1
        elif existing.get("assignedForm") != assigned_form:
            updated_count += 1
        next_students.append(student)

    payload["students"] = sorted(next_students, key=lambda item: (item.get("order", 9999), item.get("rut", "")))
    return payload, updated_count, created_count


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Loads assignedForm values for an evaluation from a CSV."
    )
    parser.add_argument("--csv", required=True, help="Path to the CSV with rut and assignedForm")
    parser.add_argument("--students", required=True, help="Path to evaluations/<SECTION_CODE>/<EV>/students.json")
    parser.add_argument("--course-students", help="Path to evaluations/<SECTION_CODE>/students.json")
    parser.add_argument("--dry-run", action="store_true", help="Validate and show a summary without writing changes")
    args = parser.parse_args()

    csv_path = Path(args.csv).resolve()
    students_path = Path(args.students).resolve()

    if not csv_path.exists():
        raise SystemExit(f"Error: the specified CSV does not exist: {csv_path}")
    if not students_path.exists():
        raise SystemExit(f"Error: the evaluation file does not exist: {students_path}")

    payload = load_json(students_path)
    course_payload = load_json(Path(args.course_students).resolve()) if args.course_students else None
    assignments = parse_assignments_csv(csv_path)
    original_count = len(payload.get("students", []))
    assignment_ruts = {item["rut"] for item in assignments}
    existing_ruts = {student.get("rut") for student in payload.get("students", []) if student.get("rut")}
    removed_count = len(existing_ruts - assignment_ruts)
    updated_payload, updated_count, created_count = apply_assignments(payload, assignments, course_payload)
    final_count = len(updated_payload.get("students", []))

    if args.dry_run:
        print(
            f"Dry run OK: {len(assignments)} assignments read, "
            f"{created_count} students to add, {updated_count} forms to update, "
            f"{removed_count} students outside the effective roster in {students_path}"
        )
        return

    students_path.write_text(
        json.dumps(updated_payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        f"Form assignment updated in {students_path} "
        f"({len(assignments)} rows read, {created_count} students added, "
        f"{updated_count} forms updated, {removed_count} students removed from the effective roster; "
        f"{original_count} -> {final_count})."
    )


if __name__ == "__main__":
    main()
