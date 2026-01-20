import argparse
import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse


def _read_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _write_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _safe_site_name(name: str) -> str:
    s = (name or "").strip().lower()
    s = re.sub(r"[^a-z0-9_]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "newsite"


def _class_name_from_site(site: str) -> str:
    parts = [p for p in re.split(r"[_\-]+", site) if p]
    return "".join([p[:1].upper() + p[1:] for p in parts]) + "CCGPSearch"


def _json_loads_maybe(s: Optional[str]) -> Optional[Any]:
    if not s:
        return None
    try:
        return json.loads(s)
    except Exception:
        return None


def _is_list_like_json(data: Any) -> bool:
    if isinstance(data, list):
        return len(data) > 0
    if not isinstance(data, dict):
        return False
    for k in ("data", "list", "records", "rows", "items", "result"):
        v = data.get(k)
        if isinstance(v, list) and len(v) > 0:
            return True
        if isinstance(v, dict):
            for kk in ("data", "list", "records", "rows", "items"):
                vv = v.get(kk)
                if isinstance(vv, list) and len(vv) > 0:
                    return True
    return False


def _find_total_in_json(data: Any) -> Optional[int]:
    if not isinstance(data, dict):
        return None
    for k in ("total", "totalCount", "count"):
        if isinstance(data.get(k), int):
            return data.get(k)
    for k in ("data", "result"):
        v = data.get(k)
        if isinstance(v, dict):
            t = _find_total_in_json(v)
            if t is not None:
                return t
    return None


def _find_first_list_in_json(data: Any) -> Optional[List[Any]]:
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return None
    for k in ("data", "result", "list", "records", "rows", "items"):
        v = data.get(k)
        if isinstance(v, list):
            return v
        if isinstance(v, dict):
            nested = _find_first_list_in_json(v)
            if nested is not None:
                return nested
    return None


def _looks_like_detail_json(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    s = json.dumps(data, ensure_ascii=False)
    return ('"content":' in s and "<" in s) or ('"attachment' in s)

def _first_item_keys(resp_json: Optional[Dict[str, Any]]) -> List[str]:
    if not resp_json:
        return []
    items = _find_first_list_in_json(resp_json)
    if isinstance(items, list) and items:
        first = items[0]
        if isinstance(first, dict):
            return sorted(list(first.keys()))
    return []


def _dedupe_urls(urls: List[str]) -> List[str]:
    seen = set()
    out = []
    for u in urls:
        key = u.split("?", 1)[0]
        if key in seen:
            continue
        seen.add(key)
        out.append(u)
    return out


@dataclass
class HarEndpointCandidate:
    url: str
    method: str
    request_json: Optional[Dict[str, Any]]
    response_json: Optional[Dict[str, Any]]
    score: float


def _iter_har_entries(har: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    log = har.get("log") if isinstance(har, dict) else None
    if not isinstance(log, dict):
        return []
    entries = log.get("entries")
    if not isinstance(entries, list):
        return []
    return entries


def _extract_entry_payload(entry: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    req = entry.get("request") if isinstance(entry, dict) else None
    resp = entry.get("response") if isinstance(entry, dict) else None
    req_json = None
    resp_json = None
    if isinstance(req, dict):
        post = req.get("postData")
        if isinstance(post, dict):
            req_json_any = _json_loads_maybe(post.get("text"))
            if isinstance(req_json_any, dict):
                req_json = req_json_any
    if isinstance(resp, dict):
        content = resp.get("content")
        if isinstance(content, dict):
            resp_json_any = _json_loads_maybe(content.get("text"))
            if isinstance(resp_json_any, dict):
                resp_json = resp_json_any
    return req_json, resp_json


def _score_list_candidate(url: str, method: str, req_json: Optional[Dict[str, Any]], resp_json: Optional[Dict[str, Any]]) -> float:
    score = 0.0
    p = urlparse(url)
    path = (p.path or "").lower()
    if method.upper() in ("POST", "GET"):
        score += 0.5
    if "list" in path or "category" in path or "search" in path:
        score += 1.0
    if req_json:
        keys = set(req_json.keys())
        if any(k in keys for k in ("page", "pageNo", "pageNum", "pageIndex")):
            score += 2.0
        if any(k in keys for k in ("pageSize", "rows", "size", "limit")):
            score += 2.0
    if resp_json:
        if resp_json.get("success") is True:
            score += 1.0
        if _is_list_like_json(resp_json):
            score += 4.0
        total = _find_total_in_json(resp_json)
        if total is not None:
            score += 2.0
    return score


def _score_detail_candidate(url: str, method: str, req_json: Optional[Dict[str, Any]], resp_json: Optional[Dict[str, Any]]) -> float:
    score = 0.0
    p = urlparse(url)
    path = (p.path or "").lower()
    if "detail" in path:
        score += 3.0
    if "id" in (p.query or "").lower():
        score += 1.0
    if resp_json:
        if resp_json.get("success") is True:
            score += 1.0
        if _looks_like_detail_json(resp_json):
            score += 4.0
    return score


def find_best_endpoints_from_har(har: Dict[str, Any]) -> Dict[str, Any]:
    list_candidates: List[HarEndpointCandidate] = []
    detail_candidates: List[HarEndpointCandidate] = []
    seen = set()
    for entry in _iter_har_entries(har):
        req = entry.get("request") if isinstance(entry, dict) else None
        if not isinstance(req, dict):
            continue
        url = req.get("url")
        method = (req.get("method") or "").upper()
        if not isinstance(url, str) or not method:
            continue
        key = (method, url.split("?", 1)[0])
        if key in seen:
            continue
        seen.add(key)
        req_json, resp_json = _extract_entry_payload(entry)
        list_score = _score_list_candidate(url, method, req_json, resp_json)
        if list_score >= 4.0:
            list_candidates.append(HarEndpointCandidate(url=url, method=method, request_json=req_json, response_json=resp_json, score=list_score))
        detail_score = _score_detail_candidate(url, method, req_json, resp_json)
        if detail_score >= 5.0:
            detail_candidates.append(HarEndpointCandidate(url=url, method=method, request_json=req_json, response_json=resp_json, score=detail_score))

    list_candidates.sort(key=lambda c: c.score, reverse=True)
    detail_candidates.sort(key=lambda c: c.score, reverse=True)

    best_list = list_candidates[0] if list_candidates else None
    best_detail = detail_candidates[0] if detail_candidates else None

    return {
        "best_list": None if not best_list else {
            "url": best_list.url,
            "method": best_list.method,
            "request_json": best_list.request_json,
            "example_total": _find_total_in_json(best_list.response_json) if best_list.response_json else None,
            "example_first_item_keys": _first_item_keys(best_list.response_json),
        },
        "best_detail": None if not best_detail else {
            "url": best_detail.url,
            "method": best_detail.method,
            "request_json": best_detail.request_json,
        },
        "top_list_candidates": [
            {"url": c.url, "method": c.method, "score": c.score} for c in list_candidates[:10]
        ],
        "top_detail_candidates": [
            {"url": c.url, "method": c.method, "score": c.score} for c in detail_candidates[:10]
        ],
    }


def analyze_page_info_output(output_dir: str) -> Dict[str, Any]:
    info_path = os.path.join(output_dir, "page_info.json")
    blueprint_path = os.path.join(output_dir, "site_blueprint.json")
    har_path = os.path.join(output_dir, "network_record.har")

    info = _read_json(info_path) if os.path.exists(info_path) else {}
    blueprint = _read_json(blueprint_path) if os.path.exists(blueprint_path) else {}
    har = _read_json(har_path) if os.path.exists(har_path) else {}

    endpoints = find_best_endpoints_from_har(har)

    suspected_from_blueprint = []
    if isinstance(blueprint, dict):
        apis = blueprint.get("apis")
        if isinstance(apis, dict):
            lst = apis.get("suspected_list_endpoints")
            if isinstance(lst, list):
                suspected_from_blueprint = [x.get("url") for x in lst if isinstance(x, dict) and isinstance(x.get("url"), str)]

    suspected_from_blueprint = _dedupe_urls([u for u in suspected_from_blueprint if u])

    storage = {}
    if isinstance(blueprint, dict):
        storage = blueprint.get("storage") if isinstance(blueprint.get("storage"), dict) else {}

    return {
        "target_url": (info.get("target_url") if isinstance(info, dict) else None),
        "title": (info.get("title") if isinstance(info, dict) else None),
        "framework": (info.get("framework") if isinstance(info, dict) else {}),
        "dom_structure": (info.get("dom_structure") if isinstance(info, dict) else {}),
        "blueprint_suspected_endpoints": suspected_from_blueprint,
        "storage": storage,
        "har_endpoints": endpoints,
    }


def _render_markdown_report(analysis: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("# Page Info 分析报告")
    lines.append("")
    lines.append(f"- URL: {analysis.get('target_url')}")
    lines.append(f"- 标题: {analysis.get('title')}")
    lines.append(f"- 框架: {json.dumps(analysis.get('framework') or {}, ensure_ascii=False)}")
    lines.append("")
    lines.append("## 关键接口（从 HAR 推断）")
    har_endpoints = analysis.get("har_endpoints") or {}
    best_list = har_endpoints.get("best_list")
    best_detail = har_endpoints.get("best_detail")
    if best_list:
        lines.append(f"- 列表接口: {best_list.get('method')} {best_list.get('url')}")
        lines.append(f"- 示例 total: {best_list.get('example_total')}")
        lines.append(f"- 首条字段: {', '.join(best_list.get('example_first_item_keys') or [])}")
    else:
        lines.append("- 列表接口: 未识别")
    if best_detail:
        lines.append(f"- 详情接口: {best_detail.get('method')} {best_detail.get('url')}")
    else:
        lines.append("- 详情接口: 未识别")
    lines.append("")
    lines.append("## 存储线索")
    storage = analysis.get("storage") or {}
    cookies_meta = storage.get("cookies_meta") or []
    ls_keys = storage.get("local_storage_keys") or []
    ss_keys = storage.get("session_storage_keys") or []
    lines.append(f"- cookies_meta: {len(cookies_meta)}")
    if cookies_meta:
        lines.append("  - " + ", ".join([c.get("name") for c in cookies_meta if isinstance(c, dict) and c.get("name")]))
    lines.append(f"- localStorage keys: {', '.join(ls_keys)}")
    lines.append(f"- sessionStorage keys: {', '.join(ss_keys)}")
    lines.append("")
    lines.append("## 页面结构线索")
    dom = analysis.get("dom_structure") or {}
    lines.append(f"- search_areas: {', '.join(dom.get('search_areas') or [])}")
    lines.append(f"- list_areas: {', '.join(dom.get('list_areas') or [])}")
    lines.append("")
    return "\n".join(lines) + "\n"


def _generate_impl(site: str, analysis: Dict[str, Any]) -> str:
    cls_name = _class_name_from_site(site)
    har_endpoints = analysis.get("har_endpoints") or {}
    best_list = har_endpoints.get("best_list") or {}
    best_detail = har_endpoints.get("best_detail") or {}
    list_url = best_list.get("url") or ""
    list_method = best_list.get("method") or "POST"
    list_payload = best_list.get("request_json") or {}
    detail_url = best_detail.get("url") or ""
    
    parsed_list = urlparse(list_url) if list_url else None
    base_url = ""
    if parsed_list:
        base_url = f"{parsed_list.scheme}://{parsed_list.netloc}"

    payload_pretty = json.dumps(list_payload, ensure_ascii=False, indent=2)
    base_url_lit = json.dumps(base_url, ensure_ascii=False)
    landing_url_lit = json.dumps(analysis.get("target_url") or "", ensure_ascii=False)
    site_lit = json.dumps(_safe_site_name(site), ensure_ascii=False)

    return (
        "import json\n"
        "import os\n"
        "import re\n"
        "import time\n"
        "from datetime import datetime\n"
        "from html import unescape\n"
        "from typing import Any, Dict, List, Optional\n"
        "from urllib.parse import urljoin, urlparse\n"
        "\n"
        "import requests\n"
        "\n"
        "from ccgp_core.fs import sanitize_filename\n"
        "from ccgp_core.output import ensure_dir, write_json, write_text\n"
        "from ccgp_core.spider import BaseSpider\n"
        "from ccgp_core.pipeline import probe_with_http_request\n"
        "\n"
        f"class {cls_name}(BaseSpider):\n"
        "    def __init__(self, config: Dict[str, Any]):\n"
        f"        super().__init__({site_lit}, config)\n"
        "        self.session.headers.update({\n"
        "            \"User-Agent\": \"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36\",\n"
        "            \"Accept\": \"application/json, text/plain, */*\",\n"
        "            \"X-Requested-With\": \"XMLHttpRequest\",\n"
        "        })\n"
        "        # Config\n"
        "        self.category_code = config.get(\"category_code\", \"\")\n"
        "        self.is_gov = config.get(\"is_gov\", True)\n"
        "        self.exclude_district_prefix = config.get(\"exclude_district_prefix\", [])\n"
        "        self.page_size = config.get(\"page_size\", 15)\n"
        "\n"
        "    def get_landing_url(self) -> str:\n"
        f"        return {landing_url_lit}\n"
        "\n"
        "    def _do_probe_request(self) -> str:\n"
        "        # Default probe impl\n"
        "        if not self.get_landing_url(): return \"ok\"\n"
        "        try:\n"
        "            r = self.session.get(self.get_landing_url(), timeout=20)\n"
        "            if r.status_code == 200:\n"
        "                return \"ok\"\n"
        "        except Exception:\n"
        "            pass\n"
        "        return \"network_error\"\n"
        "\n"
        "    def _now_ms(self) -> int:\n"
        "        return int(time.time() * 1000)\n"
        "\n"
        "    def _now_ts(self) -> int:\n"
        "        return int(time.time())\n"
        "\n"
        "    def _parse_date_ms(self, date_str: Optional[str], *, end_of_day: bool) -> Optional[int]:\n"
        "        if not date_str:\n"
        "            return None\n"
        "        try:\n"
        "            dt = datetime.strptime(date_str, \"%Y-%m-%d\")\n"
        "            if end_of_day:\n"
        "                dt = dt.replace(hour=23, minute=59, second=59)\n"
        "            return int(dt.timestamp() * 1000)\n"
        "        except Exception:\n"
        "            return None\n"
        "\n"
        "    def _request_json(self, method: str, url: str, *, params: Optional[Dict[str, Any]] = None, json_body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:\n"
        "        resp = self.session.request(method, url, params=params, json=json_body, timeout=30)\n"
        "        resp.raise_for_status()\n"
        "        return resp.json()\n"
        "\n"
        "    def _extract_list_items(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:\n"
        "        if not isinstance(payload, dict):\n"
        "            return []\n"
        "        if payload.get(\"success\") is True and isinstance(payload.get(\"result\"), dict):\n"
        "            data = payload[\"result\"].get(\"data\")\n"
        "            if isinstance(data, dict) and isinstance(data.get(\"data\"), list):\n"
        "                return data.get(\"data\")\n"
        "        for k in (\"data\", \"list\", \"records\", \"rows\", \"items\"):\n"
        "            v = payload.get(k)\n"
        "            if isinstance(v, list):\n"
        "                return v\n"
        "            if isinstance(v, dict):\n"
        "                vv = v.get(k)\n"
        "                if isinstance(vv, list):\n"
        "                    return vv\n"
        "        return []\n"
        "\n"
        "    def extract_item_timestamp(self, item: Dict[str, Any]) -> Optional[int]:\n"
        "        ts = item.get(\"publishDate\") if isinstance(item, dict) else None\n"
        "        if isinstance(ts, int):\n"
        "             return ts\n"
        "        return None\n"
        "\n"
        "    def extract_item_id(self, item: Dict[str, Any]) -> str:\n"
        "        return str(item.get(\"articleId\")) if item.get(\"articleId\") else str(item.get(\"id\") or \"\")\n"
        "\n"
        "    def fetch_page_items(self, page_no: int) -> List[Dict[str, Any]]:\n"
        f"        url = {json.dumps(list_url, ensure_ascii=False)}\n"
        f"        method = {json.dumps(list_method, ensure_ascii=False)}\n"
        f"        base_payload = {payload_pretty}\n"
        "        payload = dict(base_payload)\n"
        "        if \"pageNo\" in payload:\n"
        "            payload[\"pageNo\"] = page_no\n"
        "        elif \"page\" in payload:\n"
        "             payload[\"page\"] = page_no\n"
        "        if \"pageSize\" in payload:\n"
        "            payload[\"pageSize\"] = self.page_size\n"
        "        if \"_t\" in payload:\n"
        "            payload[\"_t\"] = self._now_ms()\n"
        "        # Unified parameters override\n"
        "        # if self.category_code: payload[\"categoryCode\"] = self.category_code\n"
        "        return self._extract_list_items(self._request_json(method, url, json_body=payload))\n"
        "\n"
        "    def fetch_detail(self, item_id: str) -> Dict[str, Any]:\n"
        f"        detail_url = {json.dumps(detail_url, ensure_ascii=False)}\n"
        "        if not detail_url:\n"
        "            raise RuntimeError(\"detail endpoint not detected\")\n"
        "        u = urlparse(detail_url)\n"
        "        base = f\"{u.scheme}://{u.netloc}{u.path}\"\n"
        "        params = {\"articleId\": item_id, \"timestamp\": self._now_ts()}\n"
        "        return self._request_json(\"GET\", base, params=params)\n"
        "\n"
        "    def save_detail(self, item: Dict[str, Any], detail: Dict[str, Any], base_dir: str):\n"
        "        item_id = self.extract_item_id(item)\n"
        "        title = None\n"
        "        if isinstance(detail, dict) and isinstance(detail.get(\"result\"), dict):\n"
        "            data = detail[\"result\"].get(\"data\")\n"
        "            if isinstance(data, dict):\n"
        "                title = data.get(\"title\")\n"
        "        \n"
        "        safe_title = sanitize_filename(f\"{item_id}_{title or 'unknown'}\")\n"
        "        item_dir = os.path.join(base_dir, safe_title)\n"
        "        ensure_dir(item_dir)\n"
        "        write_json(os.path.join(item_dir, \"item.json\"), item)\n"
        "        write_json(os.path.join(item_dir, \"detail.json\"), detail)\n"
        "        html = self._extract_content_html(detail)\n"
        "        if html:\n"
        "            write_text(os.path.join(item_dir, \"detail.html\"), html)\n"
        "\n"
        "    def _extract_content_html(self, detail: Dict[str, Any]) -> Optional[str]:\n"
        "        if not isinstance(detail, dict):\n"
        "            return None\n"
        "        result = detail.get(\"result\")\n"
        "        if not isinstance(result, dict):\n"
        "            return None\n"
        "        data = result.get(\"data\")\n"
        "        if not isinstance(data, dict):\n"
        "            return None\n"
        "        content = data.get(\"content\")\n"
        "        if isinstance(content, str) and content.strip():\n"
        "            return content\n"
        "        return None\n"
    )


def _generate_config(analysis: Dict[str, Any]) -> str:
    har_endpoints = analysis.get("har_endpoints") or {}
    best_list = har_endpoints.get("best_list") or {}
    base_payload = best_list.get("request_json") or {}
    default: Dict[str, Any] = {"max_results": 30, "page_size": 15}
    if isinstance(base_payload, dict):
        if "pageSize" in base_payload and isinstance(base_payload.get("pageSize"), int):
            default["page_size"] = base_payload.get("pageSize")
        if "categoryCode" in base_payload:
            default["category_code"] = base_payload.get("categoryCode")
        if "isGov" in base_payload:
            default["is_gov"] = base_payload.get("isGov")
        if "excludeDistrictPrefix" in base_payload:
            default["exclude_district_prefix"] = base_payload.get("excludeDistrictPrefix")
    default["start_date"] = None
    default["end_date"] = None
    default["resume"] = False
    default["interactive"] = True
    default["verbose"] = True
    return "DEFAULT_CONFIG = " + json.dumps(default, ensure_ascii=False, indent=2) + "\n"


def _generate_adapter(site: str) -> str:
    cls_name = _class_name_from_site(site)
    return (
        f"from ccgp_sites.{site}.impl import {cls_name}\n\n"
        f"__all__ = [{json.dumps(cls_name, ensure_ascii=False)}]\n"
    )


def _generate_init() -> str:
    return "__all__ = []\n"


def generate_site_skeleton(site: str, analysis: Dict[str, Any], out_root: str) -> Dict[str, str]:
    site = _safe_site_name(site)
    out_dir = os.path.join(out_root, site)
    files: Dict[str, str] = {
        os.path.join(out_dir, "__init__.py"): _generate_init(),
        os.path.join(out_dir, "adapter.py"): _generate_adapter(site),
        os.path.join(out_dir, "config.py"): _generate_config(analysis),
        os.path.join(out_dir, "impl.py"): _generate_impl(site, analysis),
    }
    return files


def write_site_skeleton(files: Dict[str, str]) -> None:
    for path, content in files.items():
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="基于 collect_page_info 输出生成站点采集脚手架")
    p.add_argument("--input", default="page_info_output", help="page_info_output 目录")
    p.add_argument("--report", action="store_true", help="生成分析报告文件")
    p.add_argument("--site", default="", help="站点名（用于生成 ccgp_sites/<site>/）")
    p.add_argument("--out-root", default="ccgp_sites", help="输出根目录（默认 ccgp_sites）")
    p.add_argument("--write", action="store_true", help="写入生成文件")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    analysis = analyze_page_info_output(args.input)
    if args.report:
        _write_json(os.path.join(args.input, "analysis_report.json"), analysis)
        _write_text(os.path.join(args.input, "analysis_report.md"), _render_markdown_report(analysis))

    if args.site:
        files = generate_site_skeleton(args.site, analysis, args.out_root)
        if args.write:
            write_site_skeleton(files)
        else:
            print(json.dumps({"files": sorted(list(files.keys()))}, ensure_ascii=False, indent=2))

    if not args.report and not args.site:
        print(json.dumps(analysis, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
