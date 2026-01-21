# Unified CCGP Scraper Framework

This repository provides a unified framework for scraping Chinese government procurement (CCGP) sites.

## Supported Sites
- **Jiangsu** (OCR Captcha)
- **Xinjiang** (Slider/Chrome CDP/Playwright)
- **Zhejiang** (Standard REST API)

## Structure

- `ccgp_core/`: Core infrastructure
  - `spider.py`: `BaseSpider` abstract base class defining the unified flow.
  - `antibot.py`, `human_track.py`: Anti-bot handling utilities.
- `ccgp_sites/`: Site implementations
  - Each site folder contains `impl.py` (inherits `BaseSpider`), `config.py`.
- `scripts/`: Entry points
  - `run_site.py`: Unified entry point for all sites.


## Usage

Use the unified script `scripts/run_site.py` for all sites.

### Basic Usage

```bash
# Run Jiangsu
python scripts/run_site.py jiangsu

# Run Xinjiang
python scripts/run_site.py xinjiang

# Run Zhejiang
python scripts/run_site.py zhejiang
```

### Common Parameters

All sites support the following parameters:

- `--start-date YYYY-MM-DD`: Filter by start date.
- `--end-date YYYY-MM-DD`: Filter by end date.
- `--keywords "kw1" "kw2"`: Filter by keywords.
- `--region CODE`: Filter by region code or name.
- `--max-pages N`: Limit number of pages.
- `--max-results N`: Limit total number of results.
- `--resume`: Resume from checkpoint.
- `--verbose`: Enable verbose logging.
- `--non-interactive`: Disable manual intervention (useful for CI/scheduled tasks).

### Examples

Search Xinjiang for "medical" in Urumqi (650100) from Jan 1st to Jan 15th 2026:

```bash
python scripts/run_site.py xinjiang --keywords "medical" --region 650100 --start-date 2026-01-01 --end-date 2026-01-15
```

## Adding a New Site

1. Create a new directory `ccgp_sites/<site_name>`.
2. Create `impl.py` defining a class inheriting from `ccgp_core.spider.BaseSpider`.
3. Implement the required abstract methods:
   - `fetch_page_items`
   - `extract_item_timestamp`
   - `extract_item_id`
   - `fetch_detail`
   - `save_detail`
   - `get_landing_url`
   - `_do_probe_request`
4. Register the site in `ccgp_sites/_registry.py` (or ensure auto-discovery works by naming convention).
5. Add `config.py` with default configuration.

You can use `analyze_page_info_output.py` to generate a skeleton implementation if you have collected page info using `collect_page_info.py`.


