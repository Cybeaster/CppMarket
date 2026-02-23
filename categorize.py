#!/usr/bin/env python3
import argparse
import csv
import json
import os
import re
import sys
import traceback
import time
from typing import Any, Dict, Optional

from openai import OpenAI
from openai import APIError, APITimeoutError, RateLimitError


DEFAULT_MODEL = "gpt-5-mini"

OUTPUT_FIELDS = [
    "company_name",
    "summarized_description",
    "technology_stack",
    "field_type",
    "salary",
    "location",
    "years_required",
]

DEFAULT_SYSTEM = (
    "You are a strict classifier. Return only valid JSON with fields: "
    f"{', '.join(OUTPUT_FIELDS)}. "
    "summarized_description must be written in the same language as the vacancy text. "
    "field type can be: {Game Development, Rendering & Graphics, Embedded & Firmware, "
    "Backend & High-Load Services, Browsers & Web Engines, Frontend, "
    "Operating Systems & Toolchains, Robotics & Computer Vision & AI, Video & Media, "
    "Desktop Applications & CAD, Scientific Computing & HPC, Security & Reverse Engineering}"
)
DEFAULT_USER_TEMPLATE = (
    "Vacancy data (CSV row JSON):\n{row_json}\n\n"
    "Respond with a JSON object using the required fields only."
)
MAX_COMPACT_DESC_CHARS = 2000


class SafeDict(dict):
    def __missing__(self, key: str) -> str:
        return ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Categorize vacancies via OpenAI and write results to CSV."
    )
    parser.add_argument("--input", required=True, help="Input vacancies CSV path.")
    parser.add_argument("--output", required=True, help="Output categorized CSV path.")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="OpenAI model name.")
    parser.add_argument("--system", default=DEFAULT_SYSTEM, help="System instruction.")
    parser.add_argument(
        "--user-template",
        default=DEFAULT_USER_TEMPLATE,
        help="User prompt template. Supports {row_json} and CSV column names.",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=7.0,
        help="Seconds to sleep between API calls.",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.2,
        help="Sampling temperature for the model.",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=1024,
        help="Max tokens for the completion.",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="Max retries per request on transient failures.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of rows to process (default: no limit).",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print raw JSON response content to stderr.",
    )
    parser.add_argument(
        "--remove-processed",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Remove successfully processed rows from the input CSV.",
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("OPENAI_API_KEY", ""),
        help="OpenAI API key (or set OPENAI_API_KEY).",
    )
    return parser.parse_args()


def build_user_prompt(template: str, row: Dict[str, Any]) -> str:
    row_json = json.dumps(row, ensure_ascii=False)
    data = SafeDict(row)
    data["row_json"] = row_json
    return template.format_map(data)


def build_compact_prompt(row: Dict[str, Any]) -> str:
    description = (
        row.get("Vacancy description")
        or row.get("description")
        or row.get("Vacancy Description")
        or ""
    )
    if len(description) > MAX_COMPACT_DESC_CHARS:
        description = description[:MAX_COMPACT_DESC_CHARS].rstrip() + "..."
    data = {
        "Vacancy name": row.get("Vacancy name") or row.get("name") or "",
        "Company name": row.get("Company name") or row.get("employer") or "",
        "Vacancy description": description,
        "Core technologies": row.get("Core technologies") or row.get("skills") or "",
        "salary": row.get("salary") or "",
        "required_experience": row.get("required_experience")
        or row.get("experience_name")
        or "",
        "location": row.get("location") or row.get("area") or "",
    }
    return (
        "Vacancy data (condensed JSON):\n"
        f"{json.dumps(data, ensure_ascii=False)}\n\n"
        "Respond with a JSON object using the required fields only."
    )


def extract_json(text: str) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    snippet = text[start : end + 1]
    try:
        return json.loads(snippet)
    except json.JSONDecodeError:
        return None


def call_openai(
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    fallback_user_prompt: Optional[str],
    max_tokens: int,
    max_retries: int,
    debug: bool,
) -> Dict[str, Any]:
    client = OpenAI(api_key=api_key)

    prompt_candidates = [user_prompt]
    if fallback_user_prompt:
        prompt_candidates.append(fallback_user_prompt)

    last_content: Optional[str] = None
    for prompt_index, prompt in enumerate(prompt_candidates, start=1):
        for attempt in range(1, max_retries + 1):
            try:
                response = client.chat.completions.create(
                    model=model,
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt},
                    ],
                )
            except RateLimitError as exc:
                if attempt == max_retries:
                    raise RuntimeError(f"Rate limited: {exc}") from exc
                retry_after = None
                response = getattr(exc, "response", None)
                if response is not None:
                    retry_after = response.headers.get("retry-after")
                if retry_after:
                    try:
                        sleep_for = float(retry_after)
                    except ValueError:
                        sleep_for = 20.0
                else:
                    match = re.search(r"try again in (\d+(?:\.\d+)?)s", str(exc))
                    sleep_for = float(match.group(1)) if match else 20.0
                time.sleep(sleep_for)
                continue
            except (APIError, APITimeoutError) as exc:
                if attempt == max_retries:
                    raise RuntimeError(f"Request failed: {exc}") from exc
                time.sleep(1.5 * attempt)
                continue
            except Exception as exc:
                raise RuntimeError(f"Request failed: {exc}") from exc

            content = response.choices[0].message.content
            last_content = content
            if debug:
                print(f"Raw response content: {content}", file=sys.stderr)
            usage = getattr(response, "usage", None)
            if usage:
                log_event(
                    "Usage tokens: "
                    f"prompt={usage.prompt_tokens}, "
                    f"completion={usage.completion_tokens}, "
                    f"total={usage.total_tokens}"
                )
            raw_response = getattr(response, "response", None)
            if raw_response is None:
                raw_response = getattr(response, "_response", None)
            headers = getattr(raw_response, "headers", None)
            if headers:
                remaining_tokens = headers.get("x-ratelimit-remaining-tokens")
                if remaining_tokens:
                    log_event(f"Rate limit remaining tokens: {remaining_tokens}")
            parsed = extract_json(content or "")
            if parsed is None:
                log_event("Failed to parse JSON response.")
                break
            return parsed
        if prompt_index < len(prompt_candidates):
            log_event("Failed to parse JSON response, trying compact prompt.")

    raise RuntimeError(f"Failed to parse JSON from response: {last_content}")


def _normalized_key(key: str) -> str:
    return re.sub(r"[\s_]+", "", key).lower()


def _value_by_keys(data: Dict[str, Any], keys: list[str]) -> Optional[Any]:
    if not data:
        return None
    normalized = {_normalized_key(k): k for k in data.keys()}
    for key in keys:
        direct = data.get(key)
        if direct is not None:
            return direct
        lookup = normalized.get(_normalized_key(key))
        if lookup is not None:
            value = data.get(lookup)
            if value is not None:
                return value
    return None


def normalize_output(model_json: Dict[str, Any], row: Dict[str, Any]) -> Dict[str, str]:
    output: Dict[str, str] = {}
    field_key_map = {
        "Company Name": ["Company Name", "Company name", "company_name", "Vacancy company"],
        "summarized description": ["summarized description", "summary", "Vacancy description"],
        "Technology stack": [
            "Technology stack",
            "technology_stack",
            "unified technology stack",
            "Core technologies",
        ],
        "field type": ["field type", "field_type"],
        "salary": ["salary", "salary_from", "salary_to"],
        "location": ["location", "area", "city"],
        "years required": ["years required", "years_required", "required_experience"],
    }
    for field in OUTPUT_FIELDS:
        value = _value_by_keys(model_json, field_key_map.get(field, [field]))
        if value is None:
            value = _value_by_keys(row, field_key_map.get(field, [field])) or ""
        output[field] = str(value)

    return output


def log_event(message: str) -> None:
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}", file=sys.stderr)


def write_remaining_rows(
    path: str, fieldnames: list[str], rows: list[Dict[str, Any]]
) -> None:
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", newline="", encoding="utf-8") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp_path, path)


def main() -> int:
    args = parse_args()
    if not args.api_key:
        print("OPENAI_API_KEY is required.", file=sys.stderr)
        return 1

    with open(args.input, newline="", encoding="utf-8") as input_file:
        reader = csv.DictReader(input_file)
        if reader.fieldnames is None:
            print("Input CSV has no header.", file=sys.stderr)
            return 1
        input_fieldnames = list(reader.fieldnames)
        remaining_rows = list(reader)

        output_exists = os.path.exists(args.output)
        output_has_data = output_exists and os.path.getsize(args.output) > 0
        output_mode = "a" if output_has_data else "w"
        with open(args.output, output_mode, newline="", encoding="utf-8") as output_file:
            writer = csv.DictWriter(output_file, fieldnames=OUTPUT_FIELDS)
            if not output_has_data:
                writer.writeheader()

            index = 0
            processed = 0
            while index < len(remaining_rows):
                if args.limit is not None and processed >= args.limit:
                    break
                row = remaining_rows[index]
                user_prompt = build_user_prompt(args.user_template, row)
                try:
                    log_event(
                        f"Requesting row {index + 1}: name={row.get('Vacancy name', '')!r} "
                    )
                    model_json = call_openai(
                        args.api_key,
                        args.model,
                        args.system,
                        user_prompt,
                        build_compact_prompt(row),
                        args.max_tokens,
                        args.max_retries,
                        args.debug,
                    )
                    log_event(
                        "Response JSON: "
                        + json.dumps(model_json, ensure_ascii=False, sort_keys=True)
                    )
                    output_row = normalize_output(model_json, row)
                    writer.writerow(output_row)
                    output_file.flush()
                    processed += 1
                    if not args.remove_processed:
                        index += 1
                    else:
                        del remaining_rows[index]
                        write_remaining_rows(
                            args.input, input_fieldnames, remaining_rows
                        )
                except Exception as exc:
                    log_event(
                        f"Row {index + 1} failed: {exc}\n{traceback.format_exc()}"
                    )
                    fallback = normalize_output({}, row)
                    writer.writerow(fallback)
                    output_file.flush()
                    processed += 1
                    index += 1

                if args.sleep > 0:
                    time.sleep(args.sleep)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
