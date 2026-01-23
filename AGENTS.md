# PROJECT KNOWLEDGE BASE (CCGP)

Generated: 2026-01-23
Branch: main
Commit: 8e9b08a

Unified China Government Procurement scraping framework (Python).
Primary entrypoint: `scripts/run_site.py` (sites: jiangsu/xinjiang/zhejiang).

## Canonical Rules (Must Follow)
- AI/dev rules live in `.agent/rules/` (treat as source of truth).
- High-risk edits require regression tests first (see `.agent/rules/core.md`).
- Do not commit secrets; do not commit `.env` (keep `.env.example` only).

## Repo Structure (Human Map)
ccgp/
- `.agent/` assistant rules and workflows
- `ccgp_core/` core framework (BaseSpider lifecycle, antibot/checkpoints, OCR, output)
- `ccgp_sites/` site implementations (auto-discovered registry + per-site spiders)
- `scripts/` CLI entrypoints + test workflow helper (MUST remain thin)
- `tests/` pytest regression/unit tests (avoid real network/browser)
- `docs/` engineering docs (testing workflow, slider optimization)
- `results/` scrape outputs (generated; not source)

## Where To Look (Task -> Location)
| Task | Location |
|------|----------|
| Unified CLI + config wiring | `scripts/run_site.py` |
| Site discovery + registry logic | `ccgp_sites/_registry.py` |
| Base crawler lifecycle (probe/search/details) | `ccgp_core/spider.py` |
| Antibot state machine + checkpointing | `ccgp_core/antibot.py`, `ccgp_core/runtime.py` |
| Output writing + filename safety | `ccgp_core/output.py`, `ccgp_core/fs.py` |
| Request fingerprinting + random delays | `ccgp_core/request_fingerprint.py` |
| OCR service | `ccgp_core/ocr_service.py`, `tests/test_ocr_service.py`, `debug_ocr.py` |
| Jiangsu site (OCR captcha) | `ccgp_sites/jiangsu/impl.py` |
| Xinjiang site (slider + Playwright) | `ccgp_sites/xinjiang/impl.py` |
| Zhejiang site (API) | `ccgp_sites/zhejiang/impl.py` |
| Test workflow docs | `docs/testing_workflow.md`, `.agent/workflows/test-cycle.md` |
| Slider behavior analysis | `docs/slider_captcha_optimization.md` |

## AGENTS.md Hierarchy
- `AGENTS.md` (this file)
- `ccgp_core/AGENTS.md`
- `ccgp_sites/AGENTS.md`
- `ccgp_sites/jiangsu/AGENTS.md`
- `ccgp_sites/xinjiang/AGENTS.md`
- `ccgp_sites/zhejiang/AGENTS.md`
- `scripts/AGENTS.md`
- `tests/AGENTS.md`

## High-Risk Areas (Changes Need Tests + Clear Rationale)
- Jiangsu (`ccgp_sites/jiangsu/impl.py`)
  - `recognize_captcha_local`, `recognize_captcha_api`, `recognize_captcha`, `get_captcha`
- Xinjiang (`ccgp_sites/xinjiang/impl.py`)
  - `_handle_slider_captcha`, `_capture_captcha_images`, `_detect_gap_distance`
  - `_generate_human_track`, `_solve_slider_async`

## Commands (Local)
Run a site:
- `python scripts/run_site.py <site> [args]`
Examples:
- `python scripts/run_site.py jiangsu`
- `python scripts/run_site.py xinjiang --start-date 2026-01-01 --end-date 2026-01-15`
- `python scripts/run_site.py zhejiang --keywords "医疗" "设备"`

Common args:
- `--start-date`, `--end-date`, `--region`, `--keywords`
- `--max-pages` (default 100), `--max-results` (default 1000)
- `--secondary-filter` (optional secondary keyword filter)
- `--resume` (checkpoint resume)
- `--non-interactive` (for CI/cron)
- `--verbose`

Run tests:
- `python -m pytest`
- `python -m pytest tests/test_jiangsu_spider.py -v`

Test-cycle helper (optional):
- `python scripts/test_cycle_helper.py init`
- `python scripts/test_cycle_helper.py parse`
- `python scripts/test_cycle_helper.py summary`

## Conventions (Project-Specific)
- Naming:
  - Classes: `PascalCase` (e.g. `JiangsuCCGPSearch`)
  - Functions/vars: `snake_case`
  - Constants: `UPPER_SNAKE_CASE`
- Site module layout (per site dir):
  - `impl.py`: actual spider class inheriting `BaseSpider`
  - `adapter.py`: re-export spider class for registry discovery
  - `config.py`: default config
- Testing:
  - Use pytest; avoid real network requests; prefer mocks/monkeypatch.

## Hard Rules / Anti-Patterns
- Do not change scraping behavior from `scripts/` (only CLI parsing/UX improvements). See `.agent/rules/core.md`.
- Do not add or commit secrets (tokens/cookies/passwords).
- Do not treat generated directories as source:
  - `results/` (scrape output)
  - `tests/report/` (reports/coverage)
  - `chrome_debug_profile/` (local browser artifacts)

## Notes / Gotchas
- Xinjiang uses Playwright + asyncio in `ccgp_sites/xinjiang/impl.py`; keep async boundaries clear and mockable.
- `BaseSpider` writes incremental `search_results.json` and details under `results/<site>/.../details/` (see `docs/testing_workflow.md`).
