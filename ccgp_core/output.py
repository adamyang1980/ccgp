import json
import os
from datetime import datetime
from typing import Any, Optional


def timestamp_now(fmt: str = "%Y%m%d_%H%M%S") -> str:
    return datetime.now().strftime(fmt)


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def write_text(path: str, content: str, encoding: str = "utf-8") -> None:
    ensure_dir(os.path.dirname(path) or ".")
    with open(path, "w", encoding=encoding) as f:
        f.write(content)


def write_json(path: str, data: Any, encoding: str = "utf-8", indent: int = 2) -> None:
    ensure_dir(os.path.dirname(path) or ".")
    with open(path, "w", encoding=encoding) as f:
        json.dump(data, f, ensure_ascii=False, indent=indent)


def build_output_dir(prefix: str, timestamp: Optional[str] = None) -> str:
    ts = timestamp if timestamp else timestamp_now()
    return f"{prefix}_{ts}"


def build_results_dir(
    site: str,
    *,
    prefix: str = "search_results",
    timestamp: Optional[str] = None,
    root_dir: str = "results",
) -> str:
    ts = timestamp if timestamp else timestamp_now()
    site_key = (site or "").strip().lower() or "unknown"
    return os.path.join(root_dir, site_key, f"{prefix}_{site_key}_{ts}")
