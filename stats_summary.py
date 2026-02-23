#!/usr/bin/env python3
import argparse
import ast
import csv
import json
import os
from collections import Counter, defaultdict
from typing import Iterable, List


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compute salary coverage by field_type and top technologies per field_type."
        )
    )
    parser.add_argument(
        "--input",
        default="Output.csv",
        help="Input CSV path with technology_stack, field_type, salary columns.",
    )
    parser.add_argument(
        "--out",
        default=os.path.join("out_cpp_ue", "stats_summary.json"),
        help="Output JSON path for combined summary.",
    )
    parser.add_argument(
        "--count-duplicates",
        action="store_true",
        help="Count duplicate tech entries within a single row.",
    )
    return parser.parse_args()


def parse_tech_stack(raw: str) -> List[str]:
    if not raw:
        return []
    value = raw.strip()
    if not value:
        return []
    if value.startswith("[") and value.endswith("]"):
        try:
            parsed = ast.literal_eval(value)
        except (ValueError, SyntaxError):
            return []
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def iter_unique(items: Iterable[str], allow_dups: bool) -> Iterable[str]:
    if allow_dups:
        return items
    return list(dict.fromkeys(items))


def main() -> None:
    args = parse_args()

    salary_by_field: dict[str, Counter] = defaultdict(Counter)
    tech_by_field: dict[str, Counter] = defaultdict(Counter)
    overall_tech = Counter()

    total_rows = 0
    with_salary_total = 0

    with open(args.input, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(
            handle, delimiter=",", quotechar='"', skipinitialspace=True
        )
        for row in reader:
            total_rows += 1
            field = (row.get("field_type") or "Unknown").strip() or "Unknown"
            salary = (row.get("salary") or "").strip()
            has_salary = bool(salary)
            if has_salary:
                with_salary_total += 1
            salary_by_field[field]["total"] += 1
            salary_by_field[field]["with_salary"] += int(has_salary)

            techs = parse_tech_stack(row.get("technology_stack", ""))
            techs = list(iter_unique(techs, args.count_duplicates))
            if techs:
                tech_by_field[field].update(techs)
                overall_tech.update(techs)

    salary_coverage = []
    for field, counts in sorted(salary_by_field.items()):
        total = counts["total"]
        with_salary = counts["with_salary"]
        without_salary = total - with_salary
        coverage_pct = round((with_salary / total * 100.0), 2) if total else 0.0
        salary_coverage.append(
            {
                "field_type": field,
                "total": total,
                "with_salary": with_salary,
                "without_salary": without_salary,
                "coverage_pct": coverage_pct,
            }
        )

    top_tech_by_field = []
    for field, counter in sorted(tech_by_field.items()):
        if not counter:
            continue
        top_techs = [
            {"technology": tech, "count": count}
            for tech, count in counter.most_common(10)
        ]
        top_tech_by_field.append(
            {"field_type": field, "top_technologies": top_techs}
        )

    overall_top_tech = [
        {"technology": tech, "count": count}
        for tech, count in overall_tech.most_common(20)
    ]

    summary = {
        "source": args.input,
        "total_rows": total_rows,
        "with_salary_total": with_salary_total,
        "without_salary_total": total_rows - with_salary_total,
        "salary_coverage_by_field_type": salary_coverage,
        "top_technologies_by_field_type": top_tech_by_field,
        "overall_top_technology": overall_top_tech,
        "notes": {
            "count_duplicates_within_row": bool(args.count_duplicates),
            "tech_counting": "unique per row" if not args.count_duplicates else "raw",
            "csv_reader": "skipinitialspace enabled",
        },
    }

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
