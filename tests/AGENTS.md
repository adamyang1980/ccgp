# tests (pytest)

## Overview
- Unit/regression tests; avoid real network and real browser execution.

## Where To Look
- Base framework tests: `tests/test_base_spider.py`
- Site tests: `tests/test_jiangsu_spider.py`, `tests/test_xinjiang_spider.py`, `tests/test_zhejiang_spider.py`
- OCR tests: `tests/test_ocr_service.py`

## Conventions
- Use mocks/monkeypatch for `requests` to avoid live calls.
- Generated artifacts go under `tests/report/` (HTML, coverage, junit).

## Commands
- `python -m pytest`
- `python -m pytest tests/test_jiangsu_spider.py -v`

## Docs
- `docs/testing_workflow.md`
- `.agent/workflows/test-cycle.md`
