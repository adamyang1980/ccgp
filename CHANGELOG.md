# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased] - 2026-01-21

### Changed
- **Jiangsu Spider**: Updated `CACHE_DIR` to use an absolute path (`os.getcwd()/.cache/ccgp`) to avoid issues with relative paths in different execution contexts.
- **Xinjiang Spider**:
  - Enhanced `launch_chrome_for_cdp` to respect `CHROME_BIN` and `CHROME_EXECUTABLE_PATH` environment variables for specifying custom Chrome executable paths.
  - Added configurability for the browser window title keyword via `window_keyword` in config, improving stability if the site title changes.
- **Tests**:
  - Fixed `DummyResponse` in `test_jiangsu_spider.py` to include `raise_for_status()`.
  - Refined `test_zhejiang_spider.py` to correctly filter for document attachments instead of images.
- **Dependency Management**:
  - Cleaned up unused variables and imports across multiple files during review.
