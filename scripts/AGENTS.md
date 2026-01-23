# scripts (CLI + Test Workflow Helpers)

## Overview
- Thin entrypoints only; must not change scraping behavior.

## Where To Look
- Main CLI: `scripts/run_site.py`
- Test-cycle helper: `scripts/test_cycle_helper.py`
- Site discovery: `ccgp_sites/_registry.py`

## Hard Rule
- `scripts/` can change argument parsing/UX only; do not modify crawler logic here (see `.agent/rules/core.md`).

## Commands
- `python scripts/run_site.py <site> [args]`
- `python scripts/test_cycle_helper.py init`
- `python scripts/test_cycle_helper.py parse`
- `python scripts/test_cycle_helper.py summary`
