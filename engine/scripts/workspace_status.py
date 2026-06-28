#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]


@dataclass
class Finding:
    level: str
    path: str
    message: str


@dataclass
class FormStatus:
    form_id: str
    folder: str
    exists: bool
    submissions: int = 0
    extracted_projects: int = 0
    projects_with_code: int = 0
    results: int = 0


@dataclass
class EvaluationStatus:
    section_code: str
    ev_id: str
    title: str
    folder_exists: bool
    forms: list[FormStatus] = field(default_factory=list)
    effective_students: int = 0
    assigned_students: int = 0
    assignments: int = 0
    results: int = 0
    plan_status_counts: dict[str, int] = field(default_factory=dict)
    step: str = "unknown"
    findings: list[Finding] = field(default_factory=list)


@dataclass
class SectionStatus:
    code: str
    course_title: str
    master_students: int = 0
    evaluations: list[EvaluationStatus] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)


def rel(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def load_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    if not path.exists():
        return None, "missing"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON: {exc.msg} at line {exc.lineno}, column {exc.colno}"
    if not isinstance(payload, dict):
        return None, "JSON root must be an object"
    return payload, None


def add(finding_list: list[Finding], level: str, path: Path | str, message: str) -> None:
    path_text = rel(path) if isinstance(path, Path) else path
    finding_list.append(Finding(level, path_text, message))


def duplicate_values(items: list[dict[str, Any]], key: str) -> list[str]:
    seen: set[str] = set()
    dupes: set[str] = set()
    for item in items:
        value = item.get(key)
        if value in (None, ""):
            continue
        value = str(value)
        if value in seen:
            dupes.add(value)
        seen.add(value)
    return sorted(dupes)


def section_dirs() -> list[Path]:
    evaluations = ROOT / "evaluations"
    if not evaluations.exists():
        return []
    return sorted(path for path in evaluations.iterdir() if path.is_dir() and (path / "config.json").exists())


def resolve_sections(requested: str | None, findings: list[Finding]) -> list[Path]:
    sections = section_dirs()
    by_name = {path.name: path for path in sections}

    if requested == "all":
        return sections
    if requested:
        section = ROOT / "evaluations" / requested
        if not section.exists():
            add(findings, "ERROR", section, "SECTION_CODE points to a section folder that does not exist.")
            return []
        if not (section / "config.json").exists():
            add(findings, "ERROR", section / "config.json", "Section is missing config.json.")
            return []
        return [section]

    env_section = os.environ.get("SECTION_CODE", "").strip()
    if env_section:
        return resolve_sections(env_section, findings)

    if len(sections) == 1:
        add(findings, "OK", "SECTION_CODE", f"Not set, inferred {sections[0].name} because it is the only section.")
        return sections
    if not sections:
        return []

    add(findings, "ERROR", "SECTION_CODE", "Not set and multiple sections exist. Export SECTION_CODE or pass --section.")
    add(findings, "INFO", "evaluations/", "Available sections: " + ", ".join(path.name for path in sections))
    return []


def count_files(path: Path, suffixes: tuple[str, ...] | None = None) -> int:
    if not path.exists() or not path.is_dir():
        return 0
    total = 0
    for child in path.iterdir():
        if not child.is_file():
            continue
        if suffixes and child.suffix.lower() not in suffixes:
            continue
        total += 1
    return total


def project_dirs(form_dir: Path) -> list[Path]:
    if not form_dir.exists():
        return []
    ignored = {"submissions", "results", "support"}
    return sorted(path for path in form_dir.iterdir() if path.is_dir() and path.name not in ignored)


def has_code_files(path: Path) -> bool:
    return any(child.is_file() and child.suffix.lower() in {".psc", ".pseint"} for child in path.rglob("*"))


def parse_plan_statuses(plan_path: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    if not plan_path.exists():
        return counts

    for line in plan_path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or stripped.startswith("| ---"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) < 6:
            continue
        if cells[0].lower() == "order":
            continue
        status = cells[3]
        if status and status != "-":
            counts[status] = counts.get(status, 0) + 1
    return counts


def result_ruts_from_paths(ev_dir: Path) -> set[str]:
    ruts: set[str] = set()
    for result in ev_dir.glob("form-*/results/*.md"):
        ruts.add(result.stem)
    return ruts


def detect_step(ev: EvaluationStatus) -> str:
    if not ev.folder_exists:
        return "missing folder"
    if any(f.level == "ERROR" for f in ev.findings):
        return "needs repair"
    if ev.effective_students == 0:
        return "pending form assignments"
    if ev.assigned_students < ev.effective_students:
        return "pending assigned forms"
    if sum(form.submissions for form in ev.forms) == 0 and sum(form.extracted_projects for form in ev.forms) == 0:
        return "pending submissions"
    if sum(form.extracted_projects for form in ev.forms) == 0:
        return "pending extraction"
    if sum(form.projects_with_code for form in ev.forms) == 0:
        return "review extraction output"
    if ev.results == 0:
        return "pending grading"
    if ev.results < ev.effective_students:
        return "grading in progress"
    return "ready to export"


def analyze_evaluation(section_dir: Path, config: dict[str, Any], master_students: list[dict[str, Any]], ev_id: str) -> EvaluationStatus:
    meta = config.get("evaluations", {}).get(ev_id, {})
    ev_dir = section_dir / ev_id
    ev = EvaluationStatus(
        section_code=section_dir.name,
        ev_id=ev_id,
        title=str(meta.get("title") or ev_id),
        folder_exists=ev_dir.exists(),
    )

    if not ev.folder_exists:
        add(ev.findings, "ERROR", ev_dir, "Evaluation is registered in config.json but the folder is missing.")
        ev.step = detect_step(ev)
        return ev

    required = ["plan.md", "base.md", "students.json", "assignments.json"]
    for filename in required:
        path = ev_dir / filename
        if not path.exists():
            add(ev.findings, "ERROR", path, f"Missing required evaluation file: {filename}.")

    forms = meta.get("forms", [])
    if not isinstance(forms, list) or not forms:
        add(ev.findings, "ERROR", section_dir / "config.json", f"{ev_id} has no forms in config.json.")
        forms = []

    ev_students_payload, students_error = load_json(ev_dir / "students.json")
    ev_students = []
    if students_error:
        add(ev.findings, "ERROR", ev_dir / "students.json", students_error)
    else:
        ev_students = ev_students_payload.get("students", []) if ev_students_payload else []
        if not isinstance(ev_students, list):
            add(ev.findings, "ERROR", ev_dir / "students.json", "students must be a list.")
            ev_students = []
        payload_forms = ev_students_payload.get("forms", []) if ev_students_payload else []
        configured_ids = {form.get("id") for form in forms if isinstance(form, dict)}
        payload_ids = {form.get("id") for form in payload_forms if isinstance(form, dict)}
        if configured_ids and payload_ids and configured_ids != payload_ids:
            add(ev.findings, "WARN", ev_dir / "students.json", "forms differ from config.json; run prepare-evaluation.")

    ev.effective_students = len(ev_students)
    ev.assigned_students = sum(1 for student in ev_students if student.get("assignedForm"))

    master_ruts = {str(student.get("rut")) for student in master_students if student.get("rut")}
    ev_ruts = {str(student.get("rut")) for student in ev_students if student.get("rut")}
    for rut in sorted(ev_ruts - master_ruts):
        add(ev.findings, "ERROR", ev_dir / "students.json", f"Student {rut} is in EV roster but not in section roster.")
    for rut in duplicate_values(ev_students, "rut"):
        add(ev.findings, "ERROR", ev_dir / "students.json", f"Duplicate student rut in EV roster: {rut}.")

    valid_forms = {str(form.get("id")).upper() for form in forms if isinstance(form, dict) and form.get("id")}
    for student in ev_students:
        rut = student.get("rut", "-")
        assigned = student.get("assignedForm")
        if not assigned:
            add(ev.findings, "WARN", ev_dir / "students.json", f"Student {rut} has no assignedForm.")
        elif str(assigned).upper() not in valid_forms:
            add(ev.findings, "ERROR", ev_dir / "students.json", f"Student {rut} has invalid assignedForm {assigned}.")

    assignments_payload, assignments_error = load_json(ev_dir / "assignments.json")
    assignments = []
    if assignments_error:
        add(ev.findings, "ERROR", ev_dir / "assignments.json", assignments_error)
    else:
        assignments = assignments_payload.get("assignments", []) if assignments_payload else []
        if not isinstance(assignments, list):
            add(ev.findings, "ERROR", ev_dir / "assignments.json", "assignments must be a list.")
            assignments = []
    ev.assignments = len(assignments)

    assignment_ruts: set[str] = set()
    for item in assignments:
        rut = item.get("rut") or item.get("studentId")
        assigned = item.get("assignedForm")
        if not rut:
            add(ev.findings, "ERROR", ev_dir / "assignments.json", "Assignment row without rut/studentId.")
            continue
        rut = str(rut)
        if rut in assignment_ruts:
            add(ev.findings, "ERROR", ev_dir / "assignments.json", f"Duplicate assignment for student {rut}.")
        assignment_ruts.add(rut)
        if rut not in ev_ruts:
            add(ev.findings, "WARN", ev_dir / "assignments.json", f"Assignment for {rut} is not in EV students.json.")
        if assigned and str(assigned).upper() not in valid_forms:
            add(ev.findings, "ERROR", ev_dir / "assignments.json", f"Assignment for {rut} uses invalid form {assigned}.")

    if ev_ruts and assignment_ruts:
        for rut in sorted(ev_ruts - assignment_ruts):
            add(ev.findings, "WARN", ev_dir / "assignments.json", f"Student {rut} is in EV roster but not in assignments.json.")

    for form in forms:
        if not isinstance(form, dict):
            continue
        form_id = str(form.get("id") or "").upper()
        folder = str(form.get("folder") or "")
        form_dir = ev_dir / folder
        status = FormStatus(form_id=form_id, folder=folder, exists=form_dir.exists())
        if not folder:
            add(ev.findings, "ERROR", section_dir / "config.json", f"{ev_id} has a form without folder.")
            continue
        if not form_dir.exists():
            add(ev.findings, "ERROR", form_dir, f"Missing folder for form {form_id}.")
        else:
            for expected in ("case.md", "submissions", "results"):
                expected_path = form_dir / expected
                if not expected_path.exists():
                    level = "WARN" if expected in {"submissions", "results"} else "ERROR"
                    add(ev.findings, level, expected_path, f"Missing form item: {expected}.")
            status.submissions = count_files(form_dir / "submissions", (".zip", ".rar"))
            projects = project_dirs(form_dir)
            status.extracted_projects = len(projects)
            status.projects_with_code = sum(1 for project in projects if has_code_files(project))
            status.results = count_files(form_dir / "results", (".md",))
        ev.forms.append(status)

    ev.results = sum(form.results for form in ev.forms)
    result_ruts = result_ruts_from_paths(ev_dir)
    unknown_result_ruts = sorted(result_ruts - ev_ruts)
    for rut in unknown_result_ruts:
        add(ev.findings, "WARN", ev_dir, f"Result file {rut}.md does not match an EV student rut.")

    ev.plan_status_counts = parse_plan_statuses(ev_dir / "plan.md")
    ev.step = detect_step(ev)
    return ev


def analyze_section(section_dir: Path) -> SectionStatus:
    config_path = section_dir / "config.json"
    students_path = section_dir / "students.json"
    config, config_error = load_json(config_path)
    students_payload, students_error = load_json(students_path)

    section = SectionStatus(code=section_dir.name, course_title="-")
    if config_error:
        add(section.findings, "ERROR", config_path, config_error)
        return section
    if students_error:
        add(section.findings, "ERROR", students_path, students_error)
        students_payload = {"students": []}

    course = config.get("course", {}) if config else {}
    section.course_title = str(course.get("title") or "-")
    config_name = course.get("name")
    if config_name and str(config_name) != section_dir.name:
        add(section.findings, "WARN", config_path, f"course.name is {config_name}, folder is {section_dir.name}.")

    master_students = students_payload.get("students", []) if students_payload else []
    if not isinstance(master_students, list):
        add(section.findings, "ERROR", students_path, "students must be a list.")
        master_students = []
    section.master_students = len(master_students)
    for rut in duplicate_values(master_students, "rut"):
        add(section.findings, "ERROR", students_path, f"Duplicate student rut in section roster: {rut}.")
    for student in master_students:
        missing = [key for key in ("rut", "names", "lastName", "fullName") if not student.get(key)]
        if missing:
            add(section.findings, "WARN", students_path, f"Student row is missing {', '.join(missing)}.")

    configured_evs = config.get("evaluations", {}) if config else {}
    if not isinstance(configured_evs, dict):
        add(section.findings, "ERROR", config_path, "evaluations must be an object.")
        configured_evs = {}

    ev_dirs = {path.name for path in section_dir.iterdir() if path.is_dir() and re.match(r"^EV\\w*", path.name)}
    configured_ids = set(configured_evs)
    for ev_id in sorted(ev_dirs - configured_ids):
        add(section.findings, "WARN", section_dir / ev_id, "Evaluation folder exists but is not registered in config.json.")

    for ev_id in sorted(configured_ids | ev_dirs):
        section.evaluations.append(analyze_evaluation(section_dir, config or {}, master_students, ev_id))

    expected_indexes = ["evaluations.json", "grades.json"]
    for filename in expected_indexes:
        path = section_dir / filename
        if not path.exists():
            add(section.findings, "WARN", path, f"Missing section index {filename}; run sync/export scripts when needed.")

    return section


def check_workspace_files() -> list[Finding]:
    findings: list[Finding] = []
    required_files = [
        "README.md",
        "START_HERE.es.md",
        "AGENTS.md",
        "engine/templates/evaluation-base-template.md",
        "engine/templates/evaluation-case-template.md",
        "engine/templates/evaluation-assignments-template.json",
        "engine/templates/evaluation-plan-template.md",
        "engine/templates/result-template.md",
        "scripts/init-course.sh",
        "scripts/add_evaluation.sh",
        "scripts/prepare-evaluation.sh",
        "scripts/assign-forms.sh",
        "scripts/extract-submissions.sh",
        "scripts/review-batch.sh",
        "scripts/export-results.sh",
    ]
    required_dirs = ["docs", "engine", "evaluations", "exports", "scripts"]
    for item in required_dirs:
        path = ROOT / item
        if not path.is_dir():
            add(findings, "ERROR", path, "Missing required directory.")
    for item in required_files:
        path = ROOT / item
        if not path.is_file():
            add(findings, "ERROR", path, "Missing required file.")
    return findings


def check_environment(selected_sections: list[Path]) -> list[Finding]:
    findings: list[Finding] = []
    all_sections = section_dirs()
    section_env = os.environ.get("SECTION_CODE", "").strip()
    if len(all_sections) > 1 and not section_env:
        add(findings, "INFO", "SECTION_CODE", "Required when more than one section exists.")
    elif section_env:
        add(findings, "OK", "SECTION_CODE", f"Set to {section_env}.")
    elif len(all_sections) == 1:
        add(findings, "OK", "SECTION_CODE", f"Not set; scripts can infer {all_sections[0].name}.")
    else:
        add(findings, "WARN", "SECTION_CODE", "Not set; initialize a section before normal operation.")

    ava_config = ROOT / "automation" / "ava" / "config.json"
    if ava_config.exists():
        add(findings, "OK", ava_config, "AVA automation config exists.")
        if os.environ.get("AVA_JSESSIONID"):
            add(findings, "OK", "AVA_JSESSIONID", "Set for this shell.")
        else:
            add(findings, "INFO", "AVA_JSESSIONID", "Not set; manual Playwright login can still be used.")
    else:
        add(findings, "INFO", ava_config, "Missing; only needed for AVA import automation.")

    if selected_sections:
        selected = ", ".join(section.name for section in selected_sections)
        add(findings, "INFO", "selected sections", selected)
    return findings


def level_rank(level: str) -> int:
    return {"ERROR": 3, "WARN": 2, "INFO": 1, "OK": 0}.get(level, 1)


def print_findings(title: str, findings: list[Finding], min_level: str = "OK") -> None:
    min_rank = level_rank(min_level)
    visible = [finding for finding in findings if level_rank(finding.level) >= min_rank or finding.level == "OK" and min_level == "OK"]
    if not visible:
        return
    print(f"\n## {title}")
    for finding in visible:
        print(f"[{finding.level}] {finding.path}: {finding.message}")


def print_report(workspace_findings: list[Finding], env_findings: list[Finding], selection_findings: list[Finding], sections: list[SectionStatus]) -> None:
    print("# Workspace status")
    print(f"Root: {ROOT}")

    all_findings = workspace_findings + env_findings + selection_findings
    for section in sections:
        all_findings.extend(section.findings)
        for ev in section.evaluations:
            all_findings.extend(ev.findings)

    errors = sum(1 for finding in all_findings if finding.level == "ERROR")
    warnings = sum(1 for finding in all_findings if finding.level == "WARN")
    print(f"Summary: {errors} error(s), {warnings} warning(s), {len(sections)} section(s)")

    print_findings("Workspace files", workspace_findings, "INFO")
    print_findings("Environment", env_findings + selection_findings, "INFO")

    if not sections:
        print("\n## Sections")
        print("No initialized sections were analyzed.")
        return

    print("\n## Sections")
    for section in sections:
        print(f"- {section.code}: {section.course_title} | students={section.master_students} | evaluations={len(section.evaluations)}")
        for ev in section.evaluations:
            forms = ", ".join(
                f"{form.form_id or form.folder}: sub={form.submissions}, extracted={form.extracted_projects}, code={form.projects_with_code}, results={form.results}"
                for form in ev.forms
            ) or "no forms"
            plan_status = ", ".join(f"{key}={value}" for key, value in sorted(ev.plan_status_counts.items())) or "no plan statuses"
            print(
                f"  - {ev.ev_id}: {ev.title} | step={ev.step} | students={ev.effective_students} "
                f"| assigned={ev.assigned_students} | assignments={ev.assignments} | results={ev.results}"
            )
            print(f"    forms: {forms}")
            print(f"    plan: {plan_status}")

    section_findings: list[Finding] = []
    ev_findings: list[Finding] = []
    for section in sections:
        section_findings.extend(section.findings)
        for ev in section.evaluations:
            ev_findings.extend(ev.findings)
    print_findings("Section issues", section_findings, "WARN")
    print_findings("Evaluation issues", ev_findings, "WARN")


def to_payload(
    workspace_findings: list[Finding],
    env_findings: list[Finding],
    selection_findings: list[Finding],
    sections: list[SectionStatus],
) -> dict[str, Any]:
    def finding_payload(finding: Finding) -> dict[str, str]:
        return {"level": finding.level, "path": finding.path, "message": finding.message}

    return {
        "root": str(ROOT),
        "workspaceFindings": [finding_payload(item) for item in workspace_findings],
        "environmentFindings": [finding_payload(item) for item in env_findings],
        "selectionFindings": [finding_payload(item) for item in selection_findings],
        "sections": [
            {
                "code": section.code,
                "courseTitle": section.course_title,
                "masterStudents": section.master_students,
                "findings": [finding_payload(item) for item in section.findings],
                "evaluations": [
                    {
                        "id": ev.ev_id,
                        "title": ev.title,
                        "step": ev.step,
                        "effectiveStudents": ev.effective_students,
                        "assignedStudents": ev.assigned_students,
                        "assignments": ev.assignments,
                        "results": ev.results,
                        "planStatusCounts": ev.plan_status_counts,
                        "forms": [form.__dict__ for form in ev.forms],
                        "findings": [finding_payload(item) for item in ev.findings],
                    }
                    for ev in section.evaluations
                ],
            }
            for section in sections
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Reports workspace health without modifying files.")
    parser.add_argument("--section", help="Section code to analyze. Use 'all' to analyze every section.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero when warnings are present.")
    args = parser.parse_args()

    workspace_findings = check_workspace_files()
    selection_findings: list[Finding] = []
    selected_section_dirs = resolve_sections(args.section, selection_findings)
    env_findings = check_environment(selected_section_dirs)
    sections = [analyze_section(section_dir) for section_dir in selected_section_dirs]

    payload = to_payload(workspace_findings, env_findings, selection_findings, sections)
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print_report(workspace_findings, env_findings, selection_findings, sections)

    all_findings = workspace_findings + env_findings + selection_findings
    for section in sections:
        all_findings.extend(section.findings)
        for ev in section.evaluations:
            all_findings.extend(ev.findings)

    if any(finding.level == "ERROR" for finding in all_findings):
        return 2
    if args.strict and any(finding.level == "WARN" for finding in all_findings):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
