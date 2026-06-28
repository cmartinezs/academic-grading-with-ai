#!/usr/bin/env python3
from __future__ import annotations

"""Export normalized section data for an external publication workspace.

Sources:
- evaluations/<SECTION_CODE>/config.json + evaluations/<SECTION_CODE>/*/plan.md

Output:
- exports/publication-input/manifest.json
- exports/publication-input/course/*.json
"""

import json
import os
import re
import statistics
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ENGINE_DIR = ROOT / "engine"
DEFAULTS_PATH = ENGINE_DIR / "defaults.json"
EXPORT_DIR = ROOT / "exports" / "publication-input"

MANIFEST_FILE = "manifest.json"
COURSE_FILE = "course.json"
STUDENTS_FILE = "students.json"
EVALUATIONS_FILE = "evaluations.json"
RESULTS_FILE = "results.json"
COURSE_SUMMARY_FILE = "course-summary.json"


@dataclass
class PlanEntry:
    student_name: str
    rut: str
    status: str
    score: float | None
    form: str | None
    result_path: Path | None


def deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def normalize_weight(weight: float | int | None) -> float:
    try:
        parsed = float(weight)
    except (TypeError, ValueError):
        return 1.0
    return parsed if parsed > 0 else 1.0


def percent_to_grade(score: float | None, grading: dict) -> float | None:
    if score is None:
        return None

    passing_percent = float(grading.get("passingPercent", 60))
    min_grade = float(grading.get("minGrade", 1))
    passing_grade = float(grading.get("passingGrade", 4))
    max_grade = float(grading.get("maxGrade", 7))

    if score >= passing_percent:
        return round(
            passing_grade + ((score - passing_percent) / (100 - passing_percent)) * (max_grade - passing_grade),
            2,
        )
    return round(min_grade + (score / passing_percent) * (passing_grade - min_grade), 2)


def weighted_average(items: list[tuple[float, float]]) -> float | None:
    if not items:
        return None
    weighted_sum = sum(score * normalize_weight(weight) for score, weight in items)
    total_weight = sum(normalize_weight(weight) for _, weight in items)
    return round(weighted_sum / total_weight, 2) if total_weight else None


def slugify(text: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", str(text).strip())
    cleaned = cleaned.strip("-._")
    return cleaned or "course"


def resolve_section_code() -> str:
    explicit = os.environ.get("SECTION_CODE", "").strip()
    if explicit:
        return explicit

    candidates = [
        path.name
        for path in sorted((ROOT / "evaluations").iterdir())
        if path.is_dir() and (path / "config.json").exists()
    ] if (ROOT / "evaluations").exists() else []

    if len(candidates) == 1:
        return candidates[0]

    if not candidates:
        raise SystemExit("Error: no active section was found. Define SECTION_CODE before exporting.")

    raise SystemExit("Error: more than one section exists in evaluations/. Define SECTION_CODE before exporting.")


def parse_percent(value: str) -> float | None:
    match = re.search(r"(\d+(?:[.,]\d+)?)\s*%", value or "")
    return float(match.group(1).replace(",", ".")) if match else None


def performance_label(percent: float | None) -> str | None:
    if percent is None:
        return None
    labels = {
        100.0: "Excellent performance",
        80.0: "Good performance",
        60.0: "Acceptable performance",
        30.0: "Early performance",
        0.0: "Not achieved",
    }
    return labels.get(round(percent, 2), f"Combined performance ({percent:.2f}%)")


def parse_table_row(line: str) -> list[str] | None:
    stripped = line.strip()
    if not stripped.startswith("|") or stripped.count("|") < 2:
        return None
    cells = [cell.strip() for cell in stripped.strip("|").split("|")]
    return cells


def is_separator_row(cells: list[str]) -> bool:
    return all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells)


def normalize_header(text: str) -> str:
    return (
        text.lower()
        .replace("ó", "o")
        .replace("í", "i")
        .replace("á", "a")
        .replace("é", "e")
        .replace("ú", "u")
        .strip()
    )


def normalize_status(text: str) -> str:
    normalized = normalize_header(text)
    return {
        "evaluada": "Evaluada",
        "graded": "Evaluada",
        "en revision": "En revisión",
        "under review": "En revisión",
        "pendiente": "Pendiente",
        "pending": "Pendiente",
        "observada": "Observada",
        "flagged": "Observada",
        "requiere conversacion": "Requiere conversación",
        "needs conversation": "Requiere conversación",
    }.get(normalized, text.strip() or "Pendiente")


def extract_markdown_link(text: str) -> str | None:
    match = re.search(r"\[[^\]]+\]\(([^)]+)\)", text or "")
    return match.group(1) if match else None


def parse_result_file(path: Path) -> dict:
    lines = path.read_text(encoding="utf-8").splitlines()

    student_name = ""
    form = None
    score = None
    feedback_lines: list[str] = []
    ies: list[dict] = []

    in_ies = False
    ie_header_seen = False
    ie_format = None
    in_feedback = False

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("**Student:**"):
            student_name = stripped.split("**Student:**", 1)[1].strip()
            continue

        if stripped.startswith("**Alumno:**"):
            student_name = stripped.split("**Alumno:**", 1)[1].strip()
            continue

        if stripped.startswith("**Form:**"):
            form_text = stripped.split("**Form:**", 1)[1].strip()
            form_match = re.match(r"^([A-Z])\b", form_text)
            form = form_match.group(1) if form_match else form_text.split("—", 1)[0].strip()
            continue

        if stripped.startswith("**Forma:**"):
            form_text = stripped.split("**Forma:**", 1)[1].strip()
            form_match = re.match(r"^([A-Z])\b", form_text)
            form = form_match.group(1) if form_match else form_text.split("—", 1)[0].strip()
            continue

        if (
            stripped.startswith("## Checklist")
            or stripped.startswith("## Lista de cotejo")
            or stripped == "## IE review"
            or stripped == "## Evaluación por IE"
        ):
            in_ies = True
            ie_header_seen = False
            ie_format = None
            continue

        if in_ies:
            if stripped.startswith("## "):
                in_ies = False
            else:
                cells = parse_table_row(line)
                if cells:
                    if not ie_header_seen:
                        ie_header_seen = True
                        normalized_cells = [normalize_header(cell) for cell in cells]
                        if "desemp. ej1" in normalized_cells and "desemp. ej2" in normalized_cells:
                            ie_format = (
                                "direct_ava"
                                if "nivel ava" in normalized_cells
                                else "weighted_exercises"
                            )
                        else:
                            ie_format = "checklist"
                        continue
                    if is_separator_row(cells):
                        continue
                    if ie_format == "direct_ava" and len(cells) >= 9:
                        if normalize_header(cells[0]).strip("*") == "total":
                            score = parse_percent(cells[7])
                            continue
                        ies.append(
                            {
                                "id": cells[0],
                                "description": cells[1],
                                "exercise1Percent": parse_percent(cells[2]),
                                "exercise2Percent": parse_percent(cells[3]),
                                "level": cells[4],
                                "levelPercent": parse_percent(cells[5]),
                                "weightPercent": parse_percent(cells[6]),
                                "awardedPoints": parse_percent(cells[7]),
                                "feedback": cells[8],
                            }
                        )
                    elif ie_format == "weighted_exercises" and len(cells) >= 7:
                        if normalize_header(cells[0]).strip("*") == "total":
                            score = parse_percent(cells[5])
                            continue
                        weight_percent = parse_percent(cells[4])
                        awarded_points = parse_percent(cells[5])
                        level_percent = (
                            round((awarded_points / weight_percent) * 100, 2)
                            if awarded_points is not None and weight_percent
                            else None
                        )
                        ies.append(
                            {
                                "id": cells[0],
                                "description": cells[1],
                                "exercise1Percent": parse_percent(cells[2]),
                                "exercise2Percent": parse_percent(cells[3]),
                                "weightPercent": weight_percent,
                                "level": performance_label(level_percent),
                                "levelPercent": level_percent,
                                "awardedPoints": awarded_points,
                                "feedback": cells[6],
                            }
                        )
                    elif len(cells) >= 7:
                        ies.append(
                            {
                                "id": cells[0],
                                "description": cells[1],
                                "weightPercent": parse_percent(cells[2]),
                                "level": cells[3],
                                "levelPercent": parse_percent(cells[4]),
                                "awardedPoints": parse_percent(cells[5]),
                                "feedback": cells[6],
                            }
                        )
                    elif len(cells) >= 6:
                        weight_percent = parse_percent(cells[3])
                        status = normalize_header(cells[4])
                        achieved = status in {"logrado", "achieved", "yes"}
                        ies.append(
                            {
                                "id": cells[0],
                                "description": cells[1],
                                "exercise": cells[2],
                                "weightPercent": weight_percent,
                                "level": "Excellent performance" if achieved else "Not achieved",
                                "levelPercent": 100.0 if achieved else 0.0,
                                "awardedPoints": weight_percent if achieved else 0.0,
                                "feedback": cells[5],
                            }
                        )
                    elif len(cells) >= 5:
                        weight_percent = parse_percent(cells[2])
                        status = normalize_header(cells[3])
                        achieved = status in {"logrado", "achieved", "yes"}
                        ies.append(
                            {
                                "id": cells[0],
                                "description": cells[0],
                                "exercise": cells[1],
                                "weightPercent": weight_percent,
                                "level": "Excellent performance" if achieved else "Not achieved",
                                "levelPercent": 100.0 if achieved else 0.0,
                                "awardedPoints": weight_percent if achieved else 0.0,
                                "feedback": cells[4],
                            }
                        )
                continue

        if stripped in {"## Percentage achieved", "## Porcentaje alcanzado"}:
            continue

        if stripped.startswith("**") and stripped.endswith("%**"):
            percent_match = re.search(r"(\d+(?:\.\d+)?)", stripped)
            if percent_match:
                score = float(percent_match.group(1))
            continue

        if stripped in {"## Final Feedback", "## Feedback final", "## Feedback", "## Retroalimentación"}:
            in_feedback = True
            continue

        if in_feedback:
            feedback_lines.append(line.rstrip())

    final_feedback = "\n".join(line for line in feedback_lines).strip()

    return {
        "studentName": student_name,
        "form": form,
        "score": score,
        "finalFeedback": final_feedback,
        "ies": ies,
    }


def parse_plan_file(plan_path: Path) -> list[PlanEntry]:
    lines = plan_path.read_text(encoding="utf-8").splitlines()
    entries: list[PlanEntry] = []
    current_form = None
    in_target_table = False
    header_seen = False

    for line in lines:
        stripped = line.strip()
        form_match = re.match(r"^###\s+(?:Form|Forma)\s+(.+)$", stripped)
        if form_match:
            current_form = form_match.group(1).strip().split()[0]
            in_target_table = False
            header_seen = False
            continue

        cells = parse_table_row(line)
        if not cells:
            in_target_table = False
            header_seen = False
            continue

        normalized = [normalize_header(cell) for cell in cells]
        if normalized[:6] == ["order", "student", "rut", "status", "final outcome", "notes"] or normalized[:6] == ["orden", "alumno", "rut", "estado", "situacion final", "observaciones"]:
            in_target_table = True
            header_seen = True
            continue
        if normalized[:6] == ["order", "student or file", "form", "status", "final outcome", "notes"] or normalized[:6] == ["orden", "alumno o archivo", "forma", "estado", "situacion final", "observaciones"]:
            in_target_table = True
            header_seen = True
            current_form = None
            continue

        if not in_target_table:
            continue

        if is_separator_row(cells):
            continue

        if len(cells) < 6:
            continue
        if cells[3].strip() in {"-", "—"}:
            continue

        result_link = extract_markdown_link(cells[5])
        result_path = (plan_path.parent / result_link).resolve() if result_link else None
        form_value = current_form
        rut_value = ""
        if normalize_header(cells[1]) != "alumno" and normalize_header(cells[1]) != "alumno o archivo" and not current_form:
            form_value = re.sub(r"[^A-Za-z]", "", cells[2]).upper()[:1] or None
        entries.append(
            PlanEntry(
                student_name=cells[1],
                rut=rut_value if not current_form else re.sub(r"\D", "", cells[2]),
                status=normalize_status(cells[3]),
                score=parse_percent(cells[4]),
                form=form_value,
                result_path=result_path if result_path and result_path.exists() else None,
            )
        )

    return entries


def compute_distribution(values: list[float]) -> list[dict]:
    bands = [
        ("0", 0, 0),
        ("0.1-39.9", 0.1, 39.9),
        ("40-54.9", 40, 54.9),
        ("55-69.9", 55, 69.9),
        ("70-84.9", 70, 84.9),
        ("85-100", 85, 100),
    ]
    distribution = []
    for label, start, end in bands:
        count = sum(1 for value in values if start <= value <= end)
        distribution.append({"label": label, "count": count})
    return distribution


def summarize_scores(entries: list[dict], approval_threshold: float) -> dict:
    scores = [entry["score"] for entry in entries if entry["score"] is not None]
    evaluated = [entry for entry in entries if entry["status"] == "Evaluada" and entry["score"] is not None]
    evaluated_scores = [entry["score"] for entry in evaluated]
    submitted = len([entry for entry in entries if entry["status"] == "Evaluada"])
    missing = len([entry for entry in entries if entry["status"] != "Evaluada"])
    approved = len([entry for entry in evaluated if entry["score"] >= approval_threshold])

    return {
        "students": len(entries),
        "evaluated": submitted,
        "missing": missing,
        "averageAll": round(sum(scores) / len(scores), 2) if scores else None,
        "averageEvaluated": round(sum(evaluated_scores) / len(evaluated_scores), 2) if evaluated_scores else None,
        "medianEvaluated": round(statistics.median(evaluated_scores), 2) if evaluated_scores else None,
        "minEvaluated": min(evaluated_scores) if evaluated_scores else None,
        "maxEvaluated": max(evaluated_scores) if evaluated_scores else None,
        "approvalCount": approved,
        "approvalRate": round((approved / len(evaluated)) * 100, 2) if evaluated else 0,
        "distribution": compute_distribution(scores),
    }


def summarize_ies(entries: list[dict]) -> list[dict]:
    bucket: dict[str, dict] = {}
    for entry in entries:
        if entry["status"] != "Evaluada":
            continue
        for ie in entry.get("ies", []):
            ie_id = ie.get("id")
            if not ie_id:
                continue
            current = bucket.setdefault(
                ie_id,
                {
                    "id": ie_id,
                    "description": ie.get("description"),
                    "weightPercent": ie.get("weightPercent"),
                    "levelPercents": [],
                    "awardedPoints": [],
                    "levels": Counter(),
                },
            )
            if ie.get("levelPercent") is not None:
                current["levelPercents"].append(float(ie["levelPercent"]))
            if ie.get("awardedPoints") is not None:
                current["awardedPoints"].append(float(ie["awardedPoints"]))
            if ie.get("level"):
                current["levels"][ie["level"]] += 1

    summary = []
    for item in bucket.values():
        summary.append(
            {
                "id": item["id"],
                "description": item["description"],
                "weightPercent": item["weightPercent"],
                "averageLevelPercent": round(sum(item["levelPercents"]) / len(item["levelPercents"]), 2)
                if item["levelPercents"]
                else None,
                "averageAwardedPoints": round(sum(item["awardedPoints"]) / len(item["awardedPoints"]), 2)
                if item["awardedPoints"]
                else None,
                "levelCounts": dict(item["levels"]),
            }
        )
    return sorted(summary, key=lambda item: item["id"])


def summarize_performance_levels(entries: list[dict]) -> list[dict]:
    bucket: dict[tuple[str, float], dict] = {}
    for entry in entries:
        if entry["status"] != "Evaluada":
            continue
        for ie in entry.get("ies", []):
            label = ie.get("level")
            percent = ie.get("levelPercent")
            if not label or percent is None:
                continue
            key = (label, float(percent))
            current = bucket.setdefault(key, {"label": label, "percent": float(percent), "count": 0})
            current["count"] += 1
    return sorted(bucket.values(), key=lambda item: (-item["percent"], item["label"]))


def build_students(evaluations: list[dict], approval_threshold: float, grading: dict) -> list[dict]:
    students: dict[str, dict] = {}
    evaluation_weight_by_id = {evaluation["id"]: evaluation.get("weight") for evaluation in evaluations}
    presentation_weight = float(grading.get("presentationWeight", 60))
    exam_weight = float(grading.get("examWeight", 40))

    for evaluation in evaluations:
        for result in evaluation["results"]:
            student = students.setdefault(
                result["studentId"],
                {
                    "id": result["studentId"],
                    "name": result.get("studentName", ""),
                    "rut": result.get("rut", ""),
                    "forms": set(),
                    "results": [],
                },
            )
            if not student["name"] and result.get("studentName"):
                student["name"] = result["studentName"]
            if not student["rut"] and result.get("rut"):
                student["rut"] = result["rut"]
            if result.get("form"):
                student["forms"].add(result["form"])
            student["results"].append(
                {
                    "evaluationId": evaluation["id"],
                    "status": result["status"],
                    "score": result["score"],
                    "grade": result.get("grade"),
                    "weight": evaluation_weight_by_id.get(evaluation["id"]),
                }
            )

    built = []
    for student in students.values():
        evaluated = [
            (item["score"], item["weight"])
            for item in student["results"]
            if item["status"] == "Evaluada" and item["score"] is not None
        ]
        evaluated_scores = [score for score, _ in evaluated]
        missing = [item for item in student["results"] if item["status"] != "Evaluada"]
        rut = student["rut"]
        presentation_percent = weighted_average(evaluated)
        presentation_grade = percent_to_grade(presentation_percent, grading)
        built.append(
            {
                "id": student["id"],
                "name": student["name"] or student["id"],
                "rut": student["rut"],
                "forms": sorted(student["forms"]),
                "summary": {
                    "evaluationsTracked": len(student["results"]),
                    "evaluatedCount": len(evaluated),
                    "missingCount": len(missing),
                    "averageScore": presentation_percent,
                    "presentationPercent": presentation_percent,
                    "presentationGrade": presentation_grade,
                    "presentationWeight": presentation_weight,
                    "examWeight": exam_weight,
                    "examGrade": None,
                    "finalGrade": None,
                    "bestScore": max(evaluated_scores) if evaluated_scores else None,
                    "worstScore": min(evaluated_scores) if evaluated_scores else None,
                    "approvedCount": len([score for score in evaluated_scores if score >= approval_threshold]),
                },
            }
        )

    return sorted(built, key=lambda item: item["name"])


def build_course_summary(evaluations: list[dict], approval_threshold: float) -> dict:
    all_results = [result for evaluation in evaluations for result in evaluation["results"]]
    summary = summarize_scores(all_results, approval_threshold)
    summary["students"] = len({result["studentId"] for result in all_results})
    return summary


def build_evaluation_items(evaluations: list[dict]) -> list[dict]:
    return [
        {
            "id": evaluation["id"],
            "title": evaluation["title"],
            "type": evaluation["type"],
            "date": evaluation["date"],
            "weight": evaluation["weight"],
            "forms": evaluation["forms"],
            "summary": evaluation["summary"],
            "ieSummary": evaluation["ieSummary"],
            "performanceLevels": evaluation["performanceLevels"],
        }
        for evaluation in evaluations
    ]


def build_result_items(evaluations: list[dict]) -> list[dict]:
    items = []
    for evaluation in evaluations:
        for result in evaluation["results"]:
            items.append(
                {
                    "studentId": result["studentId"],
                    "evaluationId": evaluation["id"],
                    "form": result["form"],
                    "status": result["status"],
                    "score": result["score"],
                    "grade": result.get("grade"),
                    "resultPath": result["resultPath"],
                    "finalFeedback": result["finalFeedback"],
                    "ies": result["ies"],
                }
            )
    return items


def discover_course_instance() -> dict:
    section_code = resolve_section_code()
    section_dir = ROOT / "evaluations" / section_code
    config_path = section_dir / "config.json"
    if not config_path.exists():
        raise FileNotFoundError(f"Missing evaluations/{section_code}/config.json")

    config = json.loads(config_path.read_text(encoding="utf-8"))
    course_id = config.get("course", {}).get("name") or "course"
    return {
        "id": course_id,
        "slug": slugify(course_id),
        "config_path": config_path,
        "evaluations_dir": section_dir,
    }


def build_evaluations(config: dict, evaluations_dir: Path, grading: dict, approval_threshold: float) -> list[dict]:
    if not evaluations_dir.exists():
        return []

    metadata_by_id = config.get("evaluations", {})
    evaluations = []

    for evaluation_path in sorted(path for path in evaluations_dir.iterdir() if path.is_dir()):
        plan_path = evaluation_path / "plan.md"
        if not plan_path.exists():
            continue

        evaluation_id = evaluation_path.name
        metadata = metadata_by_id.get(evaluation_id, {})
        plan_entries = parse_plan_file(plan_path)
        if not any(entry.result_path for entry in plan_entries):
            students_path = evaluation_path / "students.json"
            if students_path.exists():
                roster = json.loads(students_path.read_text(encoding="utf-8")).get("students", [])
                result_paths: dict[str, Path] = {}
                for candidate in evaluation_path.glob("form-*/results/*.md"):
                    student_id = candidate.stem
                    if student_id:
                        result_paths[student_id] = candidate.resolve()
                plan_entries = [
                    PlanEntry(
                        student_name=student.get("fullName", ""),
                        rut=re.sub(r"\D", "", str(student.get("rut", ""))),
                        status="Evaluada" if str(student.get("rut", "")) in result_paths else "Pendiente",
                        score=None,
                        form=student.get("assignedForm"),
                        result_path=result_paths.get(str(student.get("rut", ""))),
                    )
                    for student in roster
                ]
        results = []
        forms = set()

        for entry in plan_entries:
            parsed = parse_result_file(entry.result_path) if entry.result_path else {}
            form = parsed.get("form") or entry.form
            if form:
                forms.add(form)

            score = parsed.get("score")
            if score is None:
                score = entry.score

            result_path = None
            if entry.result_path:
                result_path = str(entry.result_path.relative_to(ROOT).as_posix())

            result = {
                "studentId": entry.rut or slugify(entry.student_name),
                "studentName": parsed.get("studentName") or entry.student_name,
                "rut": entry.rut,
                "evaluationId": evaluation_id,
                "form": form,
                "status": entry.status,
                "score": score,
                "grade": percent_to_grade(score, grading) if entry.status == "Evaluada" and score is not None else None,
                "resultPath": result_path,
                "finalFeedback": parsed.get("finalFeedback", ""),
                "ies": parsed.get("ies", []),
            }
            results.append(result)

        evaluation = {
            "id": evaluation_id,
            "title": metadata.get("title") or evaluation_id,
            "type": metadata.get("type") or config.get("defaults", {}).get("evaluationType", "regular"),
            "date": metadata.get("date"),
            "weight": metadata.get("weight"),
            "forms": sorted(forms),
            "results": results,
        }

        if evaluation["weight"] is None:
            raise ValueError(f"{evaluation_id}: missing weight in course config")

        evaluation["summary"] = summarize_scores(results, approval_threshold)
        evaluation["ieSummary"] = summarize_ies(results)
        evaluation["performanceLevels"] = summarize_performance_levels(results)
        evaluations.append(evaluation)

    return sorted(evaluations, key=lambda item: (item.get("date") or "", item["id"]))


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_course_bundle(instance: dict, defaults: dict) -> dict:
    course_config = json.loads(instance["config_path"].read_text(encoding="utf-8"))
    config = deep_merge(defaults, course_config)
    approval_threshold = config.get("defaults", {}).get("approvalThreshold", 60)
    grading = config.get("defaults", {}).get("grading", {})
    evaluations = build_evaluations(config, instance["evaluations_dir"], grading, approval_threshold)
    generated_at = datetime.now().isoformat(timespec="seconds")

    course_payload = {
        "generatedAt": generated_at,
        "course": config.get("course", {}),
        "defaults": {
            "approvalThreshold": approval_threshold,
            "grading": grading,
        },
    }
    students_payload = {"items": build_students(evaluations, approval_threshold, grading)}
    evaluations_payload = {"items": build_evaluation_items(evaluations)}
    results_payload = {"items": build_result_items(evaluations)}
    course_summary_payload = build_course_summary(evaluations, approval_threshold)

    return {
        "id": instance["id"],
        "slug": instance["slug"],
        "generatedAt": generated_at,
        "course": course_payload,
        "students": students_payload,
        "evaluations": evaluations_payload,
        "results": results_payload,
        "courseSummary": course_summary_payload,
    }


def main() -> None:
    defaults = json.loads(DEFAULTS_PATH.read_text(encoding="utf-8"))
    instance = discover_course_instance()
    bundle = build_course_bundle(instance, defaults)

    base = EXPORT_DIR / "course"
    write_json(base / COURSE_FILE, bundle["course"])
    write_json(base / STUDENTS_FILE, bundle["students"])
    write_json(base / EVALUATIONS_FILE, bundle["evaluations"])
    write_json(base / RESULTS_FILE, bundle["results"])
    write_json(base / COURSE_SUMMARY_FILE, bundle["courseSummary"])

    manifest = {
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "schemaVersion": 1,
        "course": {
            "id": bundle["id"],
            "slug": bundle["slug"],
            "generatedAt": bundle["generatedAt"],
            "metadata": bundle["course"]["course"],
            "files": {
                "course": f"course/{COURSE_FILE}",
                "students": f"course/{STUDENTS_FILE}",
                "evaluations": f"course/{EVALUATIONS_FILE}",
                "results": f"course/{RESULTS_FILE}",
                "courseSummary": f"course/{COURSE_SUMMARY_FILE}",
            },
        },
    }
    write_json(EXPORT_DIR / MANIFEST_FILE, manifest)
    print(f"Export generated in {EXPORT_DIR.relative_to(ROOT)} for course {bundle['id']}.")


if __name__ == "__main__":
    main()
