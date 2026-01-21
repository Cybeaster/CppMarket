# Repository Guidelines

## Project Structure & Module Organization
- `hhRuResearch.py` is the main script that queries the hh.ru API, parses vacancy descriptions, and writes reports.
- `out_cpp_ue/` contains generated outputs (e.g., `vacancies.csv`, `summary.json`). Treat this as data/output, not source.
- `.venv/` is a local virtual environment (if used); do not commit or rely on it for tooling.

## Build, Test, and Development Commands
- `python3 -m venv .venv` creates a local virtual environment.
- `. .venv/bin/activate` activates the virtual environment (Linux/macOS).
- `pip install requests beautifulsoup4` installs runtime dependencies used by the script.
- `python3 hhRuResearch.py --query "C++ Unreal" --area 1 --pages 5 --out out_cpp_ue` runs a sample search and writes outputs to `out_cpp_ue/`.

## Coding Style & Naming Conventions
- Python only. Follow PEP 8 with 4-space indentation and snake_case for functions/variables.
- Keep constants uppercase (e.g., `API_BASE`, `TECH_SYNONYMS`).
- Prefer small, focused helpers with type hints where practical.
- Avoid adding new dependencies unless required for API or parsing.

## Testing Guidelines
- No automated tests are currently present.
- If adding tests, use `pytest` and place files under `tests/` with `test_*.py` naming.
- Focus on parsing/normalization helpers (e.g., text cleanup, tech extraction, year parsing).

## Commit & Pull Request Guidelines
- No Git history is available in this directory, so no established commit style can be inferred.
- If you initialize Git, use clear, imperative commit messages (e.g., "Add salary parsing"), one logical change per commit.
- PRs should describe data/query changes, include sample outputs (or a short diff summary), and note any API or rate-limit impacts.

## Security & Configuration Tips
- The script queries a public API; avoid hard-coding credentials.
- Respect API rate limits: use `--sleep` between requests and keep `--pages` reasonable.
- Outputs may include sensitive employer data; avoid publishing raw CSVs unless intended.
