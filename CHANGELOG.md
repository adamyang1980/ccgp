# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased] - 2026-01-21

### Added
- **Anti-Crawler Module**: Created `ccgp_core/request_fingerprint.py` with:
  - `RandomUserAgentPool`: Maintains a pool of common desktop browser User-Agents
  - `RandomHeadersGenerator`: Generates randomized Accept-Language, Accept-Encoding, and other headers
  - `random_delay()`: Executes random delays between requests

### Changed
- **BaseSpider**: 
  - Now uses randomized headers via `RandomHeadersGenerator`
  - Added `request_delay_range` config (default 1-3 seconds between page fetches)
  - Logs delay time when verbose mode is enabled
- **Jiangsu Spider**: Updated `CACHE_DIR` to absolute path; added 0.5-1.5s delay after detail fetches
- **Xinjiang Spider**:
  - Enhanced `launch_chrome_for_cdp` to respect `CHROME_BIN` and `CHROME_EXECUTABLE_PATH` env vars
  - Added `window_keyword` config for browser window control
  - Added 0.5-1.5s delay after detail fetches
  - **Fixed**: Implemented request interception in browser mode to dynamic capture real API URL, solving page 1 fetch failure.
  - **Fixed**: Enhanced API response parsing to handle dictionary-wrapped lists (supporting `children`, `rows`, etc.).
  - **Fixed**: Resolved `AttributeError` by replacing `log_warning` with `log_info`.
- **Tests**:
  - Fixed `DummyResponse` in `test_jiangsu_spider.py` to include `raise_for_status()`
  - Updated `test_preprocess_captcha_scales_and_modes` for new scale factor
  - Refined `test_zhejiang_spider.py` to correctly filter for document attachments

