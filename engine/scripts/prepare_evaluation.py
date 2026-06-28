#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates"


def parse_weight(raw: str | None):
    if raw is None:
        return None
    value = float(raw)
    return int(value) if value.is_integer() else value


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "general"


def parse_forms(raw: str | None) -> list[dict] | None:
    if raw is None:
        return None
    forms = []
    seen = set()
    for token in raw.split(","):
        cleaned = token.strip()
        if not cleaned:
            continue
        form_id = cleaned.upper()
        if form_id in seen:
            continue
        seen.add(form_id)
        forms.append({"id": form_id, "folder": f"form-{slugify(cleaned)}"})
    if not forms:
        raise ValueError("You must provide at least one form.")
    return forms


def load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_text_atomic(path: Path, content: str) -> None:
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp_path.write_text(content, encoding="utf-8")
    tmp_path.replace(path)


def write_json_atomic(path: Path, payload: dict) -> None:
    write_text_atomic(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def read_template(name: str) -> str:
    return (TEMPLATE_DIR / name).read_text(encoding="utf-8")


def render_template(name: str, values: dict[str, object]) -> str:
    content = read_template(name)
    for key, value in values.items():
        content = content.replace(f"{{{{{key}}}}}", str(value))
    unresolved = sorted(set(re.findall(r"\{\{[A-Z_]+\}\}", content)))
    if unresolved:
        raise ValueError(f"Unresolved placeholders in {name}: {', '.join(unresolved)}")
    return content.rstrip() + "\n"


def normalize_text(value: str | None) -> str:
    raw = unicodedata.normalize("NFKD", value or "")
    stripped = "".join(char for char in raw if not unicodedata.combining(char))
    cleaned = re.sub(r"[^A-Z0-9]+", " ", stripped.upper()).strip()
    return re.sub(r"\s+", " ", cleaned)


def compact_text(value: str | None) -> str:
    return normalize_text(value).replace(" ", "")


def build_student_signature(student: dict) -> str:
    given_names = normalize_text(student.get("names", "")).split()
    initials = "".join(name[0] for name in given_names if name)
    last_name = compact_text(student.get("lastName", ""))
    return f"{initials}{last_name}"


def extract_form_id(value: str | None) -> str | None:
    match = re.search(r"[A-Z]", normalize_text(value))
    return match.group(0) if match else None


def parse_score(value: str | None) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)\s*%", value or "")
    return float(match.group(1)) if match else None


def parse_result_summary(path: Path) -> dict | None:
    student_name = ""
    form = None
    score = None
    after_score_heading = False

    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("**Student:**"):
            student_name = stripped.split("**Student:**", 1)[1].strip()
            continue
        if stripped.startswith("**Alumno:**"):
            student_name = stripped.split("**Alumno:**", 1)[1].strip()
            continue
        if stripped.startswith("**Form:**"):
            form = extract_form_id(stripped.split("**Form:**", 1)[1].strip())
            continue
        if stripped.startswith("**Forma:**"):
            form = extract_form_id(stripped.split("**Forma:**", 1)[1].strip())
            continue
        if stripped in {"## Percentage achieved", "## Porcentaje alcanzado"}:
            after_score_heading = True
            continue
        if after_score_heading:
            score = parse_score(stripped)
            if score is not None:
                break

    if not student_name:
        return None

    normalized_name = normalize_text(student_name)
    return {
        "path": path,
        "studentName": student_name,
        "normalizedName": normalized_name,
        "compactName": normalized_name.replace(" ", ""),
        "tokens": set(normalized_name.split()),
        "form": form,
        "score": score,
    }


def discover_result_summaries(evaluation_dir: Path) -> list[dict]:
    summaries = []
    for path in sorted(evaluation_dir.glob("form-*/results/*.md")):
        summary = parse_result_summary(path)
        if summary:
            summaries.append(summary)
    return summaries


def score_result_match(student: dict, result: dict) -> int | None:
    assigned_form = extract_form_id(student.get("assignedForm"))
    if assigned_form and result.get("form") and assigned_form != result["form"]:
        return None

    last_name = normalize_text(student.get("lastName"))
    second_last_name = normalize_text(student.get("secondLastName"))
    given_names = normalize_text(student.get("names", "")).split()
    first_given_name = given_names[0] if given_names else ""
    full_name = normalize_text(student.get("fullName"))
    signature = build_student_signature(student)
    compact_full_name = compact_text(student.get("fullName"))
    result_tokens = result["tokens"]
    result_compact = result["compactName"]

    score = 0
    intersection = len(set(full_name.split()) & result_tokens)
    if intersection:
        score += intersection * 10
    if last_name and last_name in result_tokens:
        score += 40
    elif last_name and last_name in result_compact:
        score += 25
    if second_last_name and second_last_name in result_tokens:
        score += 20
    for name in given_names:
        if name in result_tokens:
            score += 5
    if first_given_name and len(result_tokens) == 1 and first_given_name in result_tokens:
        score += 30
    if full_name and result["normalizedName"] == full_name:
        score += 50
    if compact_full_name and compact_full_name == result_compact:
        score += 50
    if signature and signature in result_compact:
        score += 45

    return score if score > 0 else None


def map_results_by_rut(evaluation_students: list[dict], result_summaries: list[dict]) -> dict[str, dict]:
    unmatched = list(result_summaries)
    mapped: dict[str, dict] = {}

    for student in evaluation_students:
        full_name = normalize_text(student.get("fullName"))
        assigned_form = extract_form_id(student.get("assignedForm"))
        exact_match = next(
            (
                result
                for result in unmatched
                if result["normalizedName"] == full_name
                and (not assigned_form or not result.get("form") or result["form"] == assigned_form)
            ),
            None,
        )
        if exact_match:
            mapped[student["rut"]] = exact_match
            unmatched.remove(exact_match)

    for student in evaluation_students:
        rut = student.get("rut")
        if not rut or rut in mapped:
            continue

        candidates = []
        for result in unmatched:
            score = score_result_match(student, result)
            if score is not None:
                candidates.append((score, result))

        if not candidates:
            continue

        candidates.sort(key=lambda item: item[0], reverse=True)
        best_score, best_result = candidates[0]
        if best_score < 30:
            continue

        mapped[rut] = best_result
        unmatched.remove(best_result)

    return mapped


def resolve_evaluation(config: dict, evaluation_id: str, args: argparse.Namespace) -> dict:
    existing = config.setdefault("evaluations", {}).get(evaluation_id, {})
    forms = parse_forms(args.forms)
    if forms is None:
        forms = existing.get("forms")

    title = args.title if args.title is not None else existing.get("title")
    evaluation_type = args.type if args.type is not None else existing.get("type", "regular")
    date = args.date if args.date is not None else existing.get("date")
    weight = parse_weight(args.weight) if args.weight is not None else existing.get("weight")

    missing = [
        name
        for name, value in (
            ("title", title),
            ("date", date),
            ("weight", weight),
            ("forms", forms),
        )
        if value in (None, "", [])
    ]
    if missing:
        raise ValueError(
            f"Evaluation {evaluation_id} needs these fields to be initialized: {', '.join(missing)}"
        )

    return {
        "title": title,
        "type": evaluation_type,
        "date": date,
        "weight": weight,
        "forms": forms,
    }


def merge_students(course_students: list[dict], existing_students: list[dict], forms: list[dict]) -> list[dict]:
    available_form_ids = {form["id"] for form in forms}
    course_by_rut = {student.get("rut"): student for student in course_students if student.get("rut")}
    existing_by_rut = {student.get("rut"): student for student in existing_students if student.get("rut")}
    merged = []

    for student in existing_students:
        rut = student.get("rut")
        if not rut:
            continue
        base = course_by_rut.get(rut, {})
        existing = existing_by_rut.get(rut, student)
        assigned_form = existing.get("assignedForm") or student.get("assignedForm")
        payload = {
            "order": base.get("order", student.get("order")),
            "rut": rut,
            "lastName": base.get("lastName", student.get("lastName")),
            "secondLastName": base.get("secondLastName", student.get("secondLastName", "")),
            "names": base.get("names", student.get("names")),
            "fullName": base.get("fullName", student.get("fullName")),
            "repoUrl": base.get("repoUrl", student.get("repoUrl")),
            "avaUser": base.get("avaUser", student.get("avaUser")),
            "assignedForm": assigned_form if assigned_form in available_form_ids else None,
        }
        for key, value in existing.items():
            if key not in payload:
                payload[key] = value
        merged.append(payload)

    return sorted(merged, key=lambda item: (item.get("order", 9999), item.get("rut", "")))


def ensure_case_files(evaluation_dir: Path, evaluation_id: str, evaluation_title: str, forms: list[dict]) -> None:
    for form in forms:
        form_dir = evaluation_dir / form["folder"]
        form_dir.mkdir(exist_ok=True)
        case_path = form_dir / "case.md"
        if case_path.exists():
            continue
        write_text_atomic(
            case_path,
            render_template(
                "evaluation-case-template.md",
                {
                    "EVALUATION_ID": evaluation_id,
                    "EVALUATION_TITLE": evaluation_title,
                    "FORM_ID": form["id"],
                },
            ),
        )


def ensure_base_file(evaluation_dir: Path, evaluation_id: str, evaluation_meta: dict) -> None:
    base_path = evaluation_dir / "base.md"
    if base_path.exists():
        return
    write_text_atomic(
        base_path,
        render_template(
            "evaluation-base-template.md",
            {
                "EVALUATION_ID": evaluation_id,
                "EVALUATION_TITLE": evaluation_meta["title"],
                "EVALUATION_TYPE": evaluation_meta["type"],
                "EVALUATION_DATE": evaluation_meta["date"],
                "EVALUATION_WEIGHT": evaluation_meta["weight"],
            },
        ),
    )


def build_form_links(forms: list[dict]) -> str:
    return "\n".join(f"  - Form {form['id']} → [`{form['folder']}/case.md`]({form['folder']}/case.md)" for form in forms)


def build_review_order(
    forms: list[dict], grouped: dict[str, list[dict]], results_by_rut: dict[str, dict], evaluation_dir: Path
) -> str:
    lines = []
    for form in forms:
        form_id = form["id"]
        lines.extend(
            [
                f"### Form {form_id}",
                "",
                "| Order | Student | RUT | Status | Final outcome | Notes |",
                "| ---: | --- | ---: | --- | --- | --- |",
            ]
        )
        students_in_form = grouped.get(form_id, [])
        if students_in_form:
            for student in students_in_form:
                result = results_by_rut.get(student.get("rut", ""))
                status = "Pending"
                situation = "-"
                observations = "-"
                if result:
                    status = "Graded"
                    if result.get("score") is not None:
                        score_value = result["score"]
                        situation = f"{int(score_value)}%" if float(score_value).is_integer() else f"{score_value}%"
                    relative_result_path = result["path"].relative_to(evaluation_dir)
                    observations = f"[{relative_result_path.name}]({relative_result_path.as_posix()})"
                lines.append(
                    f"| {student.get('order', '-')} | {student.get('fullName', '-')} | {student.get('rut', '-')} | {status} | {situation} | {observations} |"
                )
        else:
            lines.append("| - | No students assigned | - | - | - | - |")
        lines.extend(["", ""])

    return "\n".join(lines).rstrip()


def build_unassigned_rows(grouped: dict[str, list[dict]]) -> str:
    lines = []
    unassigned_students = grouped.get("SIN_ASIGNAR", [])
    if unassigned_students:
        for student in unassigned_students:
            lines.append(
                f"| {student.get('order', '-')} | {student.get('fullName', '-')} | {student.get('rut', '-')} | - | Assign a form in this EV's `assignments.json`. |"
            )
    else:
        lines.append("| - | All students have an assigned form | - | - | - |")
    return "\n".join(lines)


def build_plan_content(
    course: dict, evaluation_id: str, evaluation_meta: dict, evaluation_students: list[dict], evaluation_dir: Path
) -> str:
    forms = evaluation_meta["forms"]
    results_by_rut = map_results_by_rut(evaluation_students, discover_result_summaries(evaluation_dir))
    grouped = defaultdict(list)
    for student in sorted(
        evaluation_students,
        key=lambda item: ((item.get("assignedForm") or "ZZZ"), item.get("order", 9999), item.get("rut", "")),
    ):
        form_key = (student.get("assignedForm") or "SIN_ASIGNAR").upper()
        grouped[form_key].append(student)

    return render_template(
        "evaluation-plan-template.md",
        {
            "COURSE_NAME": course["name"],
            "COURSE_TITLE": course["title"],
            "EVALUATION_ID": evaluation_id,
            "EVALUATION_TITLE": evaluation_meta["title"],
            "EVALUATION_WEIGHT": evaluation_meta["weight"],
            "FORM_LINKS": build_form_links(forms),
            "REVIEW_ORDER": build_review_order(forms, grouped, results_by_rut, evaluation_dir),
            "UNASSIGNED_ROWS": build_unassigned_rows(grouped),
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Syncs the base structure of an evaluation")
    parser.add_argument("--course-config", required=True)
    parser.add_argument("--course-students", required=True)
    parser.add_argument("--evaluation-dir", required=True)
    parser.add_argument("--evaluation-id", required=True)
    parser.add_argument("--title")
    parser.add_argument("--type")
    parser.add_argument("--date")
    parser.add_argument("--weight")
    parser.add_argument("--forms", help="Comma-separated list of forms, for example D,E,F")
    parser.add_argument("--refresh-plan", action="store_true")
    args = parser.parse_args()

    course_config_path = Path(args.course_config).resolve()
    evaluation_dir = Path(args.evaluation_dir).resolve()
    course_students_path = Path(args.course_students).resolve()

    config = load_json(course_config_path, {"course": {}, "evaluations": {}})
    evaluation_meta = resolve_evaluation(config, args.evaluation_id, args)
    config["evaluations"][args.evaluation_id] = evaluation_meta
    write_json_atomic(course_config_path, config)

    course_students = load_json(course_students_path, {"students": []}).get("students", [])
    evaluation_students_path = evaluation_dir / "students.json"
    existing_students_payload = load_json(evaluation_students_path, {"forms": evaluation_meta["forms"], "students": []})
    evaluation_students = merge_students(course_students, existing_students_payload.get("students", []), evaluation_meta["forms"])

    evaluation_dir.mkdir(parents=True, exist_ok=True)
    for dirname in ("support",):
        (evaluation_dir / dirname).mkdir(exist_ok=True)

    ensure_case_files(evaluation_dir, args.evaluation_id, evaluation_meta["title"], evaluation_meta["forms"])
    ensure_base_file(evaluation_dir, args.evaluation_id, evaluation_meta)

    write_json_atomic(evaluation_students_path, {"forms": evaluation_meta["forms"], "students": evaluation_students})
    assignments_path = evaluation_dir / "assignments.json"
    if not assignments_path.exists():
        write_text_atomic(
            assignments_path,
            render_template("evaluation-assignments-template.json", {"EVALUATION_ID": args.evaluation_id}),
        )

    plan_path = evaluation_dir / "plan.md"
    plan_updated = args.refresh_plan or not plan_path.exists()
    if plan_updated:
        plan_content = build_plan_content(config["course"], args.evaluation_id, evaluation_meta, evaluation_students, evaluation_dir)
        write_text_atomic(plan_path, plan_content)

    summary = {
        "evaluationId": args.evaluation_id,
        "forms": [form["id"] for form in evaluation_meta["forms"]],
        "students": len(evaluation_students),
        "planUpdated": plan_updated,
    }
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
