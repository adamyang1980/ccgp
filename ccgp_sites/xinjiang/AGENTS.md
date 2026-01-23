# ccgp_sites/xinjiang (Slider + Playwright)

## Overview
- Aliyun slider captcha + browser automation; includes Playwright async flows.

## Where To Look
- Spider: `ccgp_sites/xinjiang/impl.py`
- Adapter/export: `ccgp_sites/xinjiang/adapter.py`
- Defaults: `ccgp_sites/xinjiang/config.py`
- Human track generator: `ccgp_core/human_track.py`
- Behavior analysis doc: `docs/slider_captcha_optimization.md`

## High-Risk Methods (Require Tests)
- `_handle_slider_captcha`
- `_capture_captcha_images`
- `_detect_gap_distance`
- `_generate_human_track`
- `_solve_slider_async`

## Gotchas
- Uses `playwright.async_api` + `asyncio`; avoid mixing blocking calls into async sections.

## Tests
- `tests/test_xinjiang_spider.py` (prefer mocking boundaries; avoid real browser in CI)
