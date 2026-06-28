#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def value_from_row(row: dict[str, str | None], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value is not None:
            cleaned = value.strip()
            if cleaned:
                return cleaned
    return ""


def parse_students_csv(csv_path: Path) -> list[dict]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("The CSV does not contain headers.")

        required = {"rut", "names", "lastName"}
        missing = sorted(required - set(reader.fieldnames))
        if missing:
            raise ValueError(
                "The CSV must include at least these columns: "
                + ", ".join(sorted(required))
                + f". Missing: {', '.join(missing)}"
            )

        students = []
        for index, row in enumerate(reader, start=1):
            rut = value_from_row(row, "rut")
            if not rut:
                continue

            names = value_from_row(row, "names")
            last_name = value_from_row(row, "lastName")
            second_last_name = value_from_row(row, "secondLastName")
            full_name = value_from_row(row, "fullName")
            if not full_name:
                full_name = " ".join(part for part in [names, last_name, second_last_name] if part)

            order_raw = value_from_row(row, "order")
            try:
                order = int(order_raw) if order_raw else index
            except ValueError:
                order = index

            students.append(
                {
                    "order": order,
                    "rut": rut,
                    "lastName": last_name,
                    "secondLastName": second_last_name or "",
                    "names": names,
                    "fullName": full_name,
                    "repoUrl": value_from_row(row, "repoUrl") or None,
                    "avaUser": value_from_row(row, "avaUser") or None,
                }
            )

    return sorted(students, key=lambda item: (item["order"], item["rut"]))


def main() -> None:
    parser = argparse.ArgumentParser(description="Converts a roster CSV into a section students.json")
    parser.add_argument("--csv", required=True, help="Input CSV path")
    parser.add_argument("--out", required=True, help="Output JSON path")
    args = parser.parse_args()

    csv_path = Path(args.csv).resolve()
    if not csv_path.exists():
        raise SystemExit(f"Error: no existe el CSV indicado: {csv_path}")

    students = parse_students_csv(csv_path)
    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"students": students}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
