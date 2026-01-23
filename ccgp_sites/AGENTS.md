# ccgp_sites (Site Implementations)

## Overview
- Per-province spiders + auto-discovery registry.

## Registry / Discovery
- `ccgp_sites/_registry.py` scans `ccgp_sites/<site>/` and imports `ccgp_sites.<site>.adapter`.
- Exported spider resolution order:
  - `<Site>CCGPSearch` (e.g. `JiangsuCCGPSearch`)
  - `CCGPSearch`
  - fallback known names (legacy compatibility)

## Per-Site Layout (Conventions)
- `impl.py`: implementation (must inherit `BaseSpider`)
- `adapter.py`: re-export spider class for registry discovery
- `config.py`: default config values

## High-Risk Notes
- Jiangsu OCR captcha and Xinjiang slider flows are high risk; see `.agent/rules/core.md` and per-site AGENTS.
