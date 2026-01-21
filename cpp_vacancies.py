#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
cpp_vacancies.py - Fetch C++ vacancies from hh.ru and write VacanciesWithoutSalary.csv.
"""

from __future__ import annotations

import argparse
import csv
import random
import re
import time
from html import unescape
from typing import Any, Dict, Iterable, List, Optional

import requests
from bs4 import BeautifulSoup
import logging


API_BASE = "https://api.hh.ru"

TECH_SYNONYMS = {
    "c++": "C++",
    "cpp": "C++",
    "c#": "C#",
    "unreal": "Unreal Engine",
    "unreal engine": "Unreal Engine",
    "ue4": "Unreal Engine",
    "ue5": "Unreal Engine",
    "directx": "DirectX",
    "d3d11": "DirectX 11",
    "d3d12": "DirectX 12",
    "vulkan": "Vulkan",
    "opengl": "OpenGL",
    "metal": "Metal",
    "cmake": "CMake",
    "git": "Git",
}


def build_session(user_agent: str, timeout_s: float) -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": user_agent,
        "Accept": "application/json",
    })
    session.request = _wrap_request_with_timeout(session.request, timeout_s)
    return session


def _wrap_request_with_timeout(request_func, timeout_s: float):
    def wrapped(method, url, **kwargs):
        if "timeout" not in kwargs:
            kwargs["timeout"] = timeout_s
        return request_func(method, url, **kwargs)
    return wrapped


def backoff_sleep(attempt: int, base: float = 0.7, cap: float = 8.0) -> None:
    t = min(cap, base * (2 ** attempt)) + random.uniform(0.0, 0.25)
    time.sleep(t)


def api_get_json(session: requests.Session, url: str, params: Optional[Dict[str, Any]] = None,
                 max_retries: int = 5) -> Dict[str, Any]:
    for attempt in range(max_retries):
        r = session.get(url, params=params)
        if r.status_code == 429:
            ra = r.headers.get("Retry-After")
            if ra:
                try:
                    time.sleep(float(ra))
                except ValueError:
                    backoff_sleep(attempt)
            else:
                backoff_sleep(attempt)
            continue
        if r.status_code == 403:
            backoff_sleep(attempt, base=1.2, cap=12.0)
            continue
        if 500 <= r.status_code < 600:
            backoff_sleep(attempt)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"Failed after retries: GET {url}")


def search_vacancies(session: requests.Session, page: int, per_page: int,
                     area: Optional[str]) -> Dict[str, Any]:
    params: Dict[str, Any] = {
        "text": "C++",
        "page": page,
        "per_page": per_page,
    }
    if area:
        params["area"] = area
    return api_get_json(session, f"{API_BASE}/vacancies", params=params)


def fetch_vacancy_detail(session: requests.Session, vac_id: str) -> Dict[str, Any]:
    return api_get_json(session, f"{API_BASE}/vacancies/{vac_id}")


def strip_html_to_text(html: str) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator=" ")
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_tech(token: str) -> str:
    t = re.sub(r"\s+", " ", token.strip().lower())
    return TECH_SYNONYMS.get(t, token.strip())


def extract_tech_from_text(text: str) -> List[str]:
    if not text:
        return []
    text_l = text.lower()
    found: set[str] = set()
    for k in TECH_SYNONYMS.keys():
        if k in text_l:
            found.add(TECH_SYNONYMS[k])
    patterns = [
        (re.compile(r"\bc\+\+\b", re.IGNORECASE), "C++"),
        (re.compile(r"\bc#\b", re.IGNORECASE), "C#"),
        (re.compile(r"\bue\s*5\b|\bue5\b", re.IGNORECASE), "Unreal Engine"),
        (re.compile(r"\bue\s*4\b|\bue4\b", re.IGNORECASE), "Unreal Engine"),
        (re.compile(r"\bd3d\s*12\b|\bd3d12\b", re.IGNORECASE), "DirectX 12"),
        (re.compile(r"\bd3d\s*11\b|\bd3d11\b", re.IGNORECASE), "DirectX 11"),
        (re.compile(r"\bdirectx\s*12\b", re.IGNORECASE), "DirectX 12"),
        (re.compile(r"\bdirectx\s*11\b", re.IGNORECASE), "DirectX 11"),
        (re.compile(r"\bvulkan\b", re.IGNORECASE), "Vulkan"),
        (re.compile(r"\bopengl\b", re.IGNORECASE), "OpenGL"),
        (re.compile(r"\bmetal\b", re.IGNORECASE), "Metal"),
    ]
    for pat, name in patterns:
        if pat.search(text):
            found.add(name)
    return sorted(found)


def merge_core_tech(skills: Iterable[str], extra: Iterable[str]) -> str:
    merged = {normalize_tech(s) for s in skills if s}
    merged.update(extra)
    merged = {m for m in merged if m}
    return "; ".join(sorted(merged))


def format_salary(sal: Optional[Dict[str, Any]]) -> str:
    if not isinstance(sal, dict):
        return ""
    parts: List[str] = []
    if sal.get("from") is not None:
        parts.append(f"from {sal['from']}")
    if sal.get("to") is not None:
        parts.append(f"to {sal['to']}")
    currency = sal.get("currency")
    if currency:
        parts.append(str(currency))
    return " ".join(parts)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--area", default=113, help="HH area id (e.g., 1=Москва)")
    ap.add_argument("--pages", type=int, default=5,
                    help="How many pages to scan (0 = all available)")
    ap.add_argument("--per-page", type=int, default=50, help="Vacancies per page (<=100)")
    ap.add_argument("--sleep", type=float, default=0.15, help="Delay between vacancy detail requests")
    ap.add_argument("--page-sleep", type=float, default=0.5, help="Delay between page requests")
    ap.add_argument("--timeout", type=float, default=20.0, help="HTTP timeout in seconds")
    ap.add_argument("--out", default="Vacancies.csv", help="Output CSV filename")
    ap.add_argument("--user-agent", default="cpp_vacancies/1.0 (+https://example.local)",
                    help="User-Agent for hh.ru API")
    ap.add_argument("--log-level", default="INFO",
                    help="Logging level (DEBUG, INFO, WARNING, ERROR)")
    args = ap.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    log = logging.getLogger("cpp_vacancies")

    session = build_session(args.user_agent, args.timeout)

    seen_ids: set[str] = set()
    rows_written = 0

    with open(args.out, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "Company name",
                "Vacancy description",
                "Vacancy name",
                "Core technologies",
                "salary",
                "required_experience",
                "location",
            ],
        )
        writer.writeheader()
        page = 0
        max_pages: Optional[int] = None
        while True:
            log.info("Fetching page %s", page)
            data = search_vacancies(session, page, args.per_page, args.area)
            if max_pages is None:
                total_pages = data.get("pages")
                if isinstance(total_pages, int):
                    if args.pages > 0:
                        max_pages = min(args.pages, total_pages)
                    else:
                        max_pages = total_pages
                    log.info("Total pages available: %s (scanning %s)", total_pages, max_pages)
                else:
                    max_pages = args.pages if args.pages > 0 else 0
                    log.info("Total pages unknown; scanning %s pages", max_pages)

            items = data.get("items") or []
            if not items:
                log.info("No items on page %s, stopping", page)
                break
            page_rows: List[Dict[str, Any]] = []
            for it in items:
                vid = str(it.get("id"))
                if not vid or vid in seen_ids:
                    continue
                seen_ids.add(vid)

                try:
                    detail = fetch_vacancy_detail(session, vid)
                except Exception:
                    log.warning("Failed to fetch vacancy %s", vid)
                    continue

                desc_html = detail.get("description") or ""
                desc_text = strip_html_to_text(desc_html)
                key_skills = [ks.get("name", "").strip() for ks in (detail.get("key_skills") or [])]
                extra_tech = extract_tech_from_text(desc_text)
                core_tech = merge_core_tech(key_skills, extra_tech)
                salary_text = format_salary(detail.get("salary"))
                required_experience = (detail.get("experience") or {}).get("name", "")
                location = (detail.get("area") or {}).get("name", "")
                company_name = (
                    (detail.get("employer") or {}).get("name")
                    or (it.get("employer") or {}).get("name", "")
                )

                page_rows.append({
                    "company_name": company_name,
                    "vacancy_name": detail.get("name", ""),
                    "vacancy_description": desc_text,
                    "core_technologies": core_tech,
                    "salary": salary_text,
                    "required_experience": required_experience,
                    "location": location,
                })

                if args.sleep > 0:
                    time.sleep(args.sleep)

            for row in page_rows:
                writer.writerow(row)
            rows_written += len(page_rows)
            log.info("Wrote %s rows from page %s", len(page_rows), page)
            page_rows.clear()

            page += 1
            if max_pages is not None and page >= max_pages:
                log.info("Reached page limit (%s), stopping", max_pages)
                break
            if args.page_sleep > 0:
                time.sleep(args.page_sleep)

    log.info("Wrote %s rows to %s", rows_written, args.out)


if __name__ == "__main__":
    main()
