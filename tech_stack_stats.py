#!/usr/bin/env python3
import argparse
import ast
import csv
import os
from collections import Counter, defaultdict
from typing import Iterable, List


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compute technology stack ratings from a categorized CSV."
    )
    parser.add_argument(
        "--input",
        default="Output.csv",
        help="Input CSV path with technology_stack and field_type columns.",
    )
    parser.add_argument(
        "--out-dir",
        default="out_cpp_ue",
        help="Directory for output CSV files.",
    )
    parser.add_argument(
        "--count-duplicates",
        action="store_true",
        help="Count duplicate tech entries within a single row.",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=20,
        help="Print top N technologies to stdout.",
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


def write_csv(path: str, header: List[str], rows: Iterable[List[str]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    overall = Counter()
    by_field = defaultdict(Counter)

    with open(args.input, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            techs = parse_tech_stack(row.get("technology_stack", ""))
            techs = list(iter_unique(techs, args.count_duplicates))
            if not techs:
                continue
            overall.update(techs)
            field = (row.get("field_type") or "Unknown").strip() or "Unknown"
            by_field[field].update(techs)

    overall_rows = [
        [tech, str(count)]
        for tech, count in sorted(overall.items(), key=lambda item: (-item[1], item[0]))
    ]
    by_field_rows = []
    for field, counter in sorted(by_field.items()):
        for tech, count in sorted(counter.items(), key=lambda item: (-item[1], item[0])):
            by_field_rows.append([field, tech, str(count)])

    overall_path = os.path.join(args.out_dir, "tech_rating.csv")
    by_field_path = os.path.join(args.out_dir, "tech_rating_by_field.csv")
    write_csv(overall_path, ["technology", "count"], overall_rows)
    write_csv(by_field_path, ["field_type", "technology", "count"], by_field_rows)

    top = args.top if args.top > 0 else 0
    if top:
        print("Top technologies:")
        for tech, count in overall.most_common(top):
            print(f"{tech}: {count}")


if __name__ == "__main__":
    main()
