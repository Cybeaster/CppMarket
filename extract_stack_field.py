#!/usr/bin/env python3
import argparse
import csv
import sys


FIELDS = ["unified technology stack", "field type"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract unified technology stack and field type to a new CSV."
    )
    parser.add_argument("--input", required=True, help="Input CSV path.")
    parser.add_argument("--output", required=True, help="Output CSV path.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    with open(args.input, newline="", encoding="utf-8") as input_file:
        reader = csv.DictReader(input_file)
        if reader.fieldnames is None:
            print("Input CSV has no header.", file=sys.stderr)
            return 1

        with open(args.output, "w", newline="", encoding="utf-8") as output_file:
            writer = csv.DictWriter(output_file, fieldnames=FIELDS)
            writer.writeheader()

            for row in reader:
                writer.writerow(
                    {
                        "unified technology stack": row.get(
                            "unified technology stack", ""
                        ),
                        "field type": row.get("field type", ""),
                    }
                )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
