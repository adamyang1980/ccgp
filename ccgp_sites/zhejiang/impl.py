import json
import os
import re
import time
from datetime import datetime
from html import unescape
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

import requests

from ccgp_core.fs import sanitize_filename
from ccgp_core.output import ensure_dir, write_json, write_text
from ccgp_core.pipeline import probe_with_http_request
from ccgp_core.spider import BaseSpider


class ZhejiangCCGPSearch(BaseSpider):
    def __init__(self, config: Dict[str, Any]):
        super().__init__("zhejiang", config)
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
                "Accept": "application/json, text/plain, */*",
                "X-Requested-With": "XMLHttpRequest",
            }
        )
        self.base_url = "https://zfcg.czt.zj.gov.cn"
        self.landing_url = "https://zfcg.czt.zj.gov.cn/site/category?parentId=600007"
        
        # Site specific config
        self.category_code = config.get("category_code", "110-175885")
        self.is_gov = config.get("is_gov", True)
        self.page_size = config.get("page_size", 15)
        self.exclude_district_prefix = config.get("exclude_district_prefix", ["90", "006011", "H0", "001111"])
        
        # Enforce secondary filter for keywords since API doesn't seem to support them in this implementation
        if "secondary_filter" not in config:
            self.secondary_filter = True

    def get_landing_url(self) -> str:
        return self.landing_url

    def _now_ms(self) -> int:
        return int(time.time() * 1000)

    def _now_ts(self) -> int:
        return int(time.time())

    def _do_probe_request(self) -> str:
        url = f"{self.base_url}/portal/category"

        def _req():
            payload: Dict[str, Any] = {
                "pageNo": 1,
                "pageSize": self.page_size,
                "categoryCode": self.category_code,
                "isGov": bool(self.is_gov),
                "excludeDistrictPrefix": self.exclude_district_prefix,
                "_t": self._now_ms(),
            }
            r = self.session.post(url, json=payload, timeout=20)
            ct = r.headers.get("content-type", "")
            return (r.status_code, ct, r.text[:4000])

        pr = probe_with_http_request(request_fn=_req, expect_json=True)
        if pr.kind != "none":
            return pr.kind
        return "ok"

    def fetch_page_items(self, page_no: int) -> List[Dict[str, Any]]:
        self.log_info(f"Checking page {page_no}...")
        url = f"{self.base_url}/portal/category"
        payload: Dict[str, Any] = {
            "pageNo": page_no,
            "pageSize": self.page_size,
            "categoryCode": self.category_code,
            "isGov": bool(self.is_gov),
            "excludeDistrictPrefix": self.exclude_district_prefix,
            "_t": self._now_ms(),
        }
        resp = self.session.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return self._extract_list_items(data)

    def _extract_list_items(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        if not isinstance(payload, dict):
            return []
        if payload.get("success") is True and isinstance(payload.get("result"), dict):
            data = payload["result"].get("data")
            if isinstance(data, dict) and isinstance(data.get("data"), list):
                return data.get("data")
        for k in ("data", "list", "records", "rows", "items"):
            v = payload.get(k)
            if isinstance(v, list):
                return v
            if isinstance(v, dict):
                vv = v.get(k)
                if isinstance(vv, list):
                    return vv
        return []

    def extract_item_timestamp(self, item: Dict[str, Any]) -> Optional[int]:
        # item['publishDate'] is milliseconds?
        # Original code: ts = item.get("publishDate") ... if start_ms is not None and ts < start_ms
        return item.get("publishDate")

    def extract_item_id(self, item: Dict[str, Any]) -> str:
        return str(item.get("articleId")) if item.get("articleId") else ""

    def fetch_detail(self, item_id: str) -> Dict[str, Any]:
        url = f"{self.base_url}/portal/detail"
        params = {"articleId": item_id, "timestamp": self._now_ts()}
        resp = self.session.get(url, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()



    def save_detail(self, item: Dict[str, Any], detail: Dict[str, Any], base_dir: str):
        item_id = self.extract_item_id(item)
        title = None
        if isinstance(detail, dict) and isinstance(detail.get("result"), dict):
            data = detail["result"].get("data")
            if isinstance(data, dict):
                title = data.get("title")
        
        dir_name = sanitize_filename(f"{item_id}_{title or 'unknown'}")
        item_dir = os.path.join(base_dir, dir_name)
        ensure_dir(item_dir)
        
        write_json(os.path.join(item_dir, "item.json"), item)
        write_json(os.path.join(item_dir, "detail.json"), detail)

        html = self._extract_content_html(detail)
        if html:
            write_text(os.path.join(item_dir, "detail.html"), html)
            atts = self._extract_attachment_urls(html)
            if atts:
                att_dir = os.path.join(item_dir, "attachments")
                ensure_dir(att_dir)
                for u in atts:
                    name = os.path.basename(urlparse(u).path) or "attachment"
                    name = sanitize_filename(name)
                    self._download_file(u, os.path.join(att_dir, name))

    def _extract_content_html(self, detail: Dict[str, Any]) -> Optional[str]:
        if not isinstance(detail, dict):
            return None
        result = detail.get("result")
        if not isinstance(result, dict):
            return None
        data = result.get("data")
        if not isinstance(data, dict):
            return None
        return data.get("content")

    def _extract_attachment_urls(self, html: str) -> List[str]:
        if not html:
            return []
        decoded = unescape(html)
        urls: List[str] = []
        for m in re.finditer(r'(?:href|src)=["\']([^"\']+)["\']', decoded, flags=re.IGNORECASE):
            u = m.group(1).strip()
            if not u or u.startswith("javascript:"):
                continue
            abs_u = urljoin(self.base_url, u)
            if re.search(r"\.(pdf|doc|docx|xls|xlsx|zip|rar)(?:\?|$)", abs_u, flags=re.IGNORECASE):
                urls.append(abs_u)
        out: List[str] = []
        seen = set()
        for u in urls:
            key = u.split("#", 1)[0]
            if key in seen:
                continue
            seen.add(key)
            out.append(u)
        return out

    def _download_file(self, url: str, dest_path: str) -> bool:
        try:
            with self.session.get(url, stream=True, timeout=60) as r:
                r.raise_for_status()
                ensure_dir(os.path.dirname(dest_path) or ".")
                with open(dest_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
            return True
        except Exception:
            return False
