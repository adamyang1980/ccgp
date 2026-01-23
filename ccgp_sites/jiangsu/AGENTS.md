# ccgp_sites/jiangsu (OCR Captcha)

## Overview
- OCR image captcha flow; uses `requests` and OCR service/API.

## Where To Look
- Spider: `ccgp_sites/jiangsu/impl.py`
- Adapter/export: `ccgp_sites/jiangsu/adapter.py`
- Defaults: `ccgp_sites/jiangsu/config.py`
- OCR service: `ccgp_core/ocr_service.py`
- OCR debug helper: `debug_ocr.py`

## High-Risk Methods (Require Tests)
- `recognize_captcha_local`
- `recognize_captcha_api`
- `recognize_captcha`
- `get_captcha`

## Tests
- `tests/test_jiangsu_spider.py`
- `tests/test_ocr_service.py`
