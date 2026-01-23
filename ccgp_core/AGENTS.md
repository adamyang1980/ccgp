# ccgp_core (Core Framework)

## Overview
- Core crawler framework: unified probe/search/details pipeline + checkpointed antibot flow.

## Where To Look
| Task | File |
|------|------|
| Main lifecycle (`run` -> probe -> search -> details) | `ccgp_core/spider.py` |
| Checkpoints + manual intervention state machine | `ccgp_core/antibot.py`, `ccgp_core/runtime.py` |
| OCR service (local/API) | `ccgp_core/ocr_service.py` |
| Output helpers (json/text, dirs) | `ccgp_core/output.py`, `ccgp_core/fs.py` |
| Random headers + delays | `ccgp_core/request_fingerprint.py` |
| Cache utilities | `ccgp_core/cache.py` |
| Probe helper | `ccgp_core/pipeline.py` |
| Human track generation (slider flows) | `ccgp_core/human_track.py` |

## Key Behaviors
- `BaseSpider.__init__(site_name, config)` sets unified config + initializes `RunContext` and checkpointing.
- `probe_phase()` gates access; can trigger captcha OCR (`solve_captcha_ocr`) or slider (stubbed `solve_slider_cdp`).
- `search_phase()` persists incremental `search_results.json` and calls `process_details()`.
- `process_details()` calls `fetch_detail(item_id)` then `save_detail(item, detail, base_dir)`.

## Anti-Patterns
- Do not change crawler behavior from `scripts/` (CLI parsing only). See `.agent/rules/core.md`.
- High-risk captcha/slider changes require regression tests first.
