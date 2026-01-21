# Repository Guidelines

## Project Structure & Module Organization
- `ccgp_core/` holds the shared framework (spider base class, pipeline, anti-bot, OCR, runtime utilities).
- `ccgp_sites/<site>/` contains site implementations (`impl.py`) plus site config/adapters (`config.py`, `adapter.py`).
- `scripts/` contains entry points such as `scripts/run_site.py`.
- `tests/` contains pytest-based regression tests.
- `docs/` and root-level helper scripts/images are used for debugging and OCR/captcha analysis.

## Build, Test, and Development Commands
- `python scripts/run_site.py jiangsu` runs the Jiangsu scraper via the unified entry point.
- `python scripts/run_site.py xinjiang --start-date 2026-01-01 --end-date 2026-01-15` runs Xinjiang with date filters.
- `pytest` runs the full test suite in `tests/`.
- `python collect_page_info.py` and `python analyze_page_info_output.py` help scaffold new site implementations.

## Coding Style & Naming Conventions
- Use Python PEP 8 conventions with 4-space indentation.
- Name classes in `CapWords`, functions/variables in `snake_case`, and constants in `UPPER_SNAKE_CASE`.
- Keep site-specific logic inside the relevant `ccgp_sites/<site>/` module and share utilities through `ccgp_core/`.
- Favor explicit parameters and small helper methods for request/parse steps to ease debugging.

## Testing Guidelines
- Tests live in `tests/` and follow `test_*.py` file naming and `test_*` function naming.
- Use pytest fixtures/mocks for external calls; avoid network access in unit tests.
- Run tests inside the conda env: `conda activate web` then `python -m pytest`.
- When touching captcha or anti-bot logic, add or update regression tests to cover edge cases.

## Commit & Pull Request Guidelines
- Commit history follows Conventional Commits (`feat: ...`, `fix: ...`, `chore: ...`); keep subjects short and scoped.
- PRs should include a brief summary, relevant test commands run (e.g., `pytest`), and sample run parameters if behavior changes.
- Link related issues and include logs/screenshots when changes affect captcha or browser flows.

## Security & Configuration Tips
- Do not commit real tokens, cookies, or credentials; keep secrets in local `.env` only.
- If configuration changes are needed, update `.env.example` and document new keys.

## Agent-Specific Guardrails
- Follow `AGENT.md` for high-risk areas (Jiangsu captcha and Xinjiang slider/browser logic); any changes require clear motivation and regression coverage.
- If adding a new site or changing entry points, ensure `ccgp_sites/_registry.py` can discover it.
