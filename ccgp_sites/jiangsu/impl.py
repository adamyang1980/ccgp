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
from ccgp_core.spider import BaseSpider

urllib3.disable_warnings(InsecureRequestWarning)

OCR_API_URL = os.getenv("OCR_API_URL", "")
OCR_API_TOKEN = os.getenv("OCR_API_TOKEN", "")

CAPTCHA_CONFIDENCE_THRESHOLD = 0.8
CAPTCHA_PREPROCESS_SCALE = 3
CAPTCHA_BRIGHTNESS_FACTOR = 1.2
CAPTCHA_CONTRAST_FACTOR = 3.0
CAPTCHA_BINARY_THRESHOLD = 120
CAPTCHA_MAX_RETRIES = 10
RETRY_BACKOFF_FACTOR = 2
MAX_RETRY_DELAY = 60

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
        
        self.ocr = None
        self._init_ocr()
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

    def _init_ocr(self):
        try:
            os.environ["DISABLE_MODEL_SOURCE_CHECK"] = "True"
            logging.getLogger("ppocr").setLevel(logging.ERROR)
            logging.getLogger("paddle").setLevel(logging.ERROR)
            warnings.filterwarnings("ignore")
            from paddleocr import PaddleOCR
            self.ocr = PaddleOCR(
                lang="en",
                use_textline_orientation=False,
                enable_mkldnn=True,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
            )
        except Exception as e:
            self.log_error(f"PaddleOCR Init Failed: {e}")
            self.ocr = None

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
            code = self.get_captcha()
            if code:
                self.current_captcha = code
                return True
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
        except:
            raise Exception("Invalid JSON response")

        if data.get("code") != 200:
             msg = data.get("message", "")
             if "验证码" in msg:
                 self.current_captcha = None
                 raise Exception("captcha_error") # Will trigger re-probe
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
    # --- OCR Helper Methods ---
    def preprocess_captcha(self, image):
        gray = image.convert("L")
        enhancer = ImageEnhance.Contrast(gray)
        contrast = enhancer.enhance(self.config.get("CAPTCHA_CONTRAST_FACTOR", 3.0))
        width, height = contrast.size
        # Using module constant for scaling if available, else 3
        scale = getattr(self, "CAPTCHA_PREPROCESS_SCALE", 3)
        resized = contrast.resize((width * scale, height * scale), Image.LANCZOS)
        binary = resized.point(lambda x: 0 if x < CAPTCHA_BINARY_THRESHOLD else 255, "1")
        denoised = binary.convert("L").filter(ImageFilter.MedianFilter(size=3))
        sharpened = denoised.filter(ImageFilter.SHARPEN)
        return sharpened

    def preprocess_captcha_for_local_ocr(self, image: Image.Image) -> Image.Image:
        """Specific preprocessing for paddleocr (expects RGB usually but we enhance it)"""
        gray = image.convert("L")
        # Increase contrast
        enhancer = ImageEnhance.Contrast(gray)
        contrast = enhancer.enhance(2.0)
        
        # Scale up
        width, height = contrast.size
        scale = 4
        resized = contrast.resize((width * scale, height * scale), Image.LANCZOS)
        
        # Binarize
        binary = resized.point(lambda x: 0 if x < 140 else 255, "1")
        
        # Denoise
        denoised = binary.convert("RGB")
        return denoised

    def recognize_captcha_local(self, image_bytes: bytes) -> Tuple[Optional[str], float]:
        if not self.ocr:
            return None, 0.0
        
        try:
            image = Image.open(BytesIO(image_bytes))
            # Preprocess
            processed_img = self.preprocess_captcha_for_local_ocr(image)
            img_array = np.array(processed_img)
            
            result = self.ocr.ocr(img_array, cls=False)
            
            # PaddleOCR result shape: [[[[pts], (text, score)], ...]]
            # Sometimes it returns None or empty list
            if not result or not result[0]:
                return None, 0.0

            text_results = []
            scores = []
            

            
            res = result[0]
            # Handle list of lines
            full_text = ""
            total_score = 0.0
            count = 0
            

            if isinstance(res, list):
                for line in res:
                    # line structure: [points, (text, score)]
                    if len(line) == 2 and isinstance(line[1], tuple):
                        t = line[1][0]
                        s = line[1][1]
                        full_text += t
                        total_score += s
                        count += 1
            
            if count > 0:
                return full_text.replace(" ", "").upper(), total_score / count
            
            return None, 0.0

        except Exception as e:
            # logging.error(f"Local OCR Error: {e}")
            return None, 0.0

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
            except Exception: pass
            time.sleep(0.5)
        return None
