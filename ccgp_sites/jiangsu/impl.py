import base64
import json
import logging
import os
import re
import shutil
import time
import warnings
from datetime import datetime, timedelta
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import requests
import urllib3
from PIL import Image, ImageEnhance, ImageFilter
from urllib3.exceptions import InsecureRequestWarning

from ccgp_core.fs import sanitize_filename
from ccgp_core.output import ensure_dir, write_json
from ccgp_core.spider import BaseSpider

urllib3.disable_warnings(InsecureRequestWarning)

OCR_API_URL = os.getenv("OCR_API_URL", "")
OCR_API_TOKEN = os.getenv("OCR_API_TOKEN", "")

# OCR Service
from ccgp_core.ocr_service import OCRService

CAPTCHA_CONFIDENCE_THRESHOLD = 0.4
CAPTCHA_MAX_RETRIES = 10

CACHE_DIR = os.path.join(os.getcwd(), ".cache", "ccgp")
CACHE_PAGES_DIR = os.path.join(CACHE_DIR, "pages")
CACHE_ATTACHMENTS_DIR = os.path.join(CACHE_DIR, "attachments")

class JiangsuCCGPSearch(BaseSpider):
    def __init__(self, config: Dict[str, Any]):
        super().__init__("jiangsu", config)
        self.base_url = "http://www.ccgp-jiangsu.gov.cn"
        self.search_page_url = f"{self.base_url}/jiangsu/cggg_search.html?lmid=cggg&qh=notic_c4"
        self.search_url = f"{self.base_url}/pss/jsp/search_cggg.jsp"
        self.captcha_url = f"{self.base_url}/pss/servlet/validateCodeServlet"
        
        self.session.headers.update({
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Connection": "keep-alive",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": self.search_page_url,
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        })
        
        
        # Initialize OCR Service
        self.ocr_service = OCRService.get_instance()
        self._init_cache_dirs()
        self.current_captcha = None
        
        # Params mapping
        self.start_ts = self._parse_date_ms(self.start_date, False)
        self.end_ts = self._parse_date_ms(self.end_date, True)
        
        # Initialize session
        try:
             self.session.get(self.search_page_url, timeout=15)
             area_url = self.base_url + "/pss/jsp/getNewArea.jsp"
             self.session.post(area_url, data={"pid": "32"}, timeout=15)
        except Exception:
             pass

    # _init_ocr removed (handled by OCRService)

    def _init_cache_dirs(self):
        os.makedirs(CACHE_PAGES_DIR, exist_ok=True)
        os.makedirs(CACHE_ATTACHMENTS_DIR, exist_ok=True)

    def _parse_date_ms(self, date_str: Optional[str], end_of_day: bool) -> int:
        if not date_str:
            return 0 if not end_of_day else int(time.time() * 1000)
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            if end_of_day:
                dt = dt.replace(hour=23, minute=59, second=59)
            return int(dt.timestamp() * 1000)
        except:
             return 0 if not end_of_day else int(time.time() * 1000)

    def get_landing_url(self) -> str:
        return self.search_page_url

    def _do_probe_request(self) -> str:
        # Jiangsu always requires captcha for search.
        if self.current_captcha:
            return "ok"
        return "captcha"

    def handle_verification(self, kind: str) -> bool:
        if kind == "captcha":
            self.log_info(f"探测到验证码，开始自动 OCR 识别 (API/Local)...")
            code = self.get_captcha()
            if code:
                self.current_captcha = code
                self.log_info(f"OCR 识别成功: {code}")
                return True
            else:
                self.log_error("OCR 识别失败，已重试多次")
        return False

    def fetch_page_items(self, page_no: int) -> List[Dict[str, Any]]:
        if not self.current_captcha:
            self.current_captcha = self.get_captcha()
            if not self.current_captcha:
                raise Exception("Failed to get captcha")

        params = {
            "cgr": "", "xmbh": "", "qy": self.config.get("region") or "", "pqy": "",
            "sd": self.start_ts, "ed": self.end_ts,
            "dljg": "", "cglx": "", 
            "bt": self.keywords[0] if self.keywords else "", # Use first keyword as main filter? Or loop?
            # Note: Unified keywords is list. Jiangsu accepts 'bt' (title) and 'nr' (content).
            # We will put partial keywords in 'bt' if available.
            "code": self.current_captcha,
            "nr": "", "cgfs": "",
            "page": page_no, "pageSize": self.config.get("page_size", 15)
        }
        
        res = self.session.get(self.search_url, params=params, timeout=30)
        try:
            data = res.json()
        except Exception:
            # If response is not JSON, it's likely an error page (WAF, session timeout, etc.)
            # We must reset captcha to force a fresh probe/login cycle.
            self.log_error(f"非 JSON 响应 (Invalid JSON response): {res.text[:200]}")
            self.current_captcha = None
            raise Exception("Invalid JSON response")

        if data.get("code") != 200:
             msg = data.get("message", "")
             # If explicit error or any non-200, better to reset captcha just in case
             # especially if we can't be sure it's NOT a captcha error.
             self.log_error(f"API 返回错误: {msg}")
             self.current_captcha = None 
             if "验证码" in msg:
                 raise Exception("captcha_error")
             raise Exception(f"API Error: {msg}")

        items = data.get("result", {}).get("list", []) or []
        for item in items:
            item_id = item.get("id")
            gg_code = item.get("ggCode")
            if item_id and gg_code:
                item["detail_url"] = f"{self.base_url}/jiangsu/js_cggg/details.html?gglb={gg_code}&ggid={item_id}"
        return items

    def extract_item_timestamp(self, item: Dict[str, Any]) -> Optional[int]:
        # Jiangsu already filters by date in backend parameters sd/ed.
        # But we implement this for BaseSpider filtering if needed.
        pd = item.get("publishDate")
        if pd:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                try:
                    return int(datetime.strptime(pd, fmt).timestamp() * 1000)
                except: continue
        return None

    def extract_item_id(self, item: Dict[str, Any]) -> str:
        return str(item.get("id", ""))

    def fetch_detail(self, item_id: str) -> Dict[str, Any]:
        # Jiangsu detail is fetched via POST to /pss/jsp/relevantCgggGetById.jsp
        url = f"{self.base_url}/pss/jsp/relevantCgggGetById.jsp"
        resp = self.session.post(url, data={"ggid": item_id}, timeout=30, verify=False)
        data = resp.json()
        if data.get("msg") != "OK":
            raise Exception(f"Detail API Error: {data.get('msg')}")
        
        # 反反爬虫: 详情页请求后随机延迟
        from ccgp_core.request_fingerprint import random_delay
        random_delay(0.5, 1.5)
        
        return data.get("data", {})

    def save_detail(self, item: Dict[str, Any], detail: Dict[str, Any], base_dir: str):
        title = detail.get("title", item.get("title", "untitled"))
        content = detail.get("content", "")
        publish_date = detail.get("publishDate", "")
        files = detail.get("files", [])
        
        item_id = self.extract_item_id(item)
        safe_title = sanitize_filename(f"{item_id}_{title}")
        item_dir = os.path.join(base_dir, safe_title)
        ensure_dir(item_dir)
        
        write_json(os.path.join(item_dir, "item.json"), item)
        write_json(os.path.join(item_dir, "detail.json"), detail)
        
        # Build HTML (legacy logic)
        html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><title>{title}</title></head>
<body><h1>{title}</h1><div>发布时间: {publish_date}</div><div>{content}</div></body></html>"""
        
        with open(os.path.join(item_dir, "index.html"), "w", encoding="utf-8") as f:
             f.write(html_content)
             
        # Download attachments
        if files:
            att_dir = os.path.join(item_dir, "attachments")
            ensure_dir(att_dir)
            for file in files:
                fname = file.get("name", "")
                furl = file.get("url", "")
                if fname and furl:
                    try:
                        r = self.session.get(furl, timeout=30, verify=False)
                        safe_fname = sanitize_filename(fname)
                        with open(os.path.join(att_dir, safe_fname), "wb") as f:
                            f.write(r.content)
                    except Exception as e:
                        self.log_error(f"Attachment download failed: {e}")

    # --- OCR Helper Methods ---
    def recognize_captcha_local(self, image_bytes: bytes) -> Tuple[Optional[str], float]:
        return self.ocr_service.recognize_captcha(image_bytes)

    def recognize_captcha_api(self, image_bytes: bytes) -> Tuple[Optional[str], float]:
        if not OCR_API_URL:
            return None, 0.0

        try:
            b64_img = base64.b64encode(image_bytes).decode('ascii')
            payload = {"file": b64_img}
            headers = {"Authorization": f"Bearer {OCR_API_TOKEN}"}
            
            response = requests.post(OCR_API_URL, json=payload, headers=headers, timeout=5)
            response.raise_for_status()
            data = response.json()
            

            results = data.get("result", {}).get("ocrResults", [])
            if results:
                pruned = results[0].get("prunedResult", {})
                texts = pruned.get("rec_texts", [])
                scores = pruned.get("rec_scores", [])
                
                text = "".join(texts).replace(" ", "").upper()
                score = sum(scores) / len(scores) if scores else 0.0
                return text, score
        except Exception:
            pass
        return None, 0.0

    def recognize_captcha(self, image_bytes: bytes) -> Tuple[Optional[str], float]:
        # Helper to choose method
        return self.recognize_captcha_local(image_bytes)

    def get_captcha(self, max_retries=CAPTCHA_MAX_RETRIES) -> Optional[str]:
        for attempt in range(max_retries):
            try:
                r = self.session.get(self.captcha_url, timeout=10)
                if r.status_code == 200:
                    code, conf = self.recognize_captcha(r.content)
                    if code and conf >= CAPTCHA_CONFIDENCE_THRESHOLD:
                        return code
                    else:
                        if attempt % 3 == 0:
                            self.log_info(f"OCR 识别置信度不足 ({conf:.2f} < {CAPTCHA_CONFIDENCE_THRESHOLD}) 或结果为空: {code}")
                            try:
                                with open(f"failed_captcha_{attempt}.jpg", "wb") as f:
                                    f.write(r.content)
                            except: pass
                else:
                    self.log_error(f"无法获取验证码图片，状态码: {r.status_code}")
                    pass
            except Exception as e:
                self.log_error(f"获取/识别验证码异常: {e}")
                pass
            time.sleep(0.5)
        return None
