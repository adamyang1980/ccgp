import asyncio
import ctypes
import html
import json
import logging
import os
import random
import re
import subprocess
import sys
import time
from ctypes import windll, wintypes
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, quote, urljoin, urlparse

import cv2
import numpy as np
import requests
from dotenv import load_dotenv
from playwright.async_api import async_playwright

from ccgp_core.antibot import ChallengeStateMachine, RunContext, prepare_results_dir
from ccgp_core.fs import sanitize_filename
from ccgp_core.human_track import create_human_track
from ccgp_core.spider import BaseSpider

# --- Window Controller helper ---
SW_SHOWMINNOACTIVE = 7
SW_RESTORE = 9

class WindowController:
    @staticmethod
    def find_window(keyword="新疆政府采购"):
        found_hwnds = []
        def callback(hwnd, section):
            length = windll.user32.GetWindowTextLengthW(hwnd)
            buff = ctypes.create_unicode_buffer(length + 1)
            windll.user32.GetWindowTextW(hwnd, buff, length + 1)
            title = buff.value
            if keyword in title and windll.user32.IsWindowVisible(hwnd):
                found_hwnds.append((hwnd, title))
            return True
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, ctypes.POINTER(ctypes.c_int))
        windll.user32.EnumWindows(WNDENUMPROC(callback), 0)
        if found_hwnds: return found_hwnds[0][0]
        return None

    @staticmethod
    def ensure_minimized(keyword="新疆政府采购"):
        hwnd = WindowController.find_window(keyword)
        if not hwnd: hwnd = WindowController.find_window("Google Chrome")
        if hwnd:
            if windll.user32.IsIconic(hwnd): return True
            windll.user32.ShowWindow(hwnd, SW_SHOWMINNOACTIVE)
            return True
        return False

    @staticmethod
    def restore(keyword="新疆政府采购"):
        hwnd = WindowController.find_window(keyword)
        if not hwnd: hwnd = WindowController.find_window("Google Chrome")
        if hwnd:
            windll.user32.ShowWindow(hwnd, SW_RESTORE)
            windll.user32.SetForegroundWindow(hwnd)
            return True
        return False

    @staticmethod
    def minimize(keyword="新疆政府采购"):
        return WindowController.ensure_minimized(keyword)

load_dotenv()
_env_cdp = os.getenv("CHROME_CDP_URL")
CHROME_CDP_URL = _env_cdp if _env_cdp else ""
DETAIL_RENDER_TIMEOUT_MS = 20000
MANUAL_CAPTCHA_MODE = os.getenv("MANUAL_CAPTCHA_MODE", "1") == "1"

def launch_chrome_for_cdp():
    possible_paths = [
        os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    chrome_path = None
    for path in possible_paths:
        if os.path.exists(path):
            chrome_path = path
            break
    if not chrome_path: return None
    user_data_dir = os.path.join(os.getcwd(), "chrome_debug_profile")
    cmd = [
        chrome_path, "--remote-debugging-port=9222", f"--user-data-dir={user_data_dir}",
        "--no-first-run", "--no-default-browser-check", "--start-minimized",
    ]
    try:
        subprocess.Popen(cmd)
        time.sleep(3)
        for _ in range(10):
            time.sleep(1)
            if WindowController.ensure_minimized(): break
        return "http://127.0.0.1:9222"
    except: return None

class XinjiangCCGPSearch(BaseSpider):
    def __init__(self, config: Dict[str, Any]):
        super().__init__("xinjiang", config)
        self.base_url = "http://www.ccgp-xinjiang.gov.cn"
        self.api_url = f"{self.base_url}/portal/category"
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "X-Requested-With": "XMLHttpRequest",
        })
        self._http_warmed = False
        
        # Params
        self.start_date = config.get("start_date")
        self.end_date = config.get("end_date")
        self.region = config.get("region", "650000")
        
    def get_landing_url(self) -> str:
        return f"{self.base_url}/site/category?parentId=3661"

    def _ensure_http_warmed(self):
        if self._http_warmed: return
        try:
             self.session.get(self.get_landing_url(), timeout=15)
        except: pass
        self._http_warmed = True

    def _do_probe_request(self) -> str:
        # Check if HTTP is blocked or WAF'd
        self._ensure_http_warmed()
        payload = self._build_search_payload(1)
        try:
            r = self.session.post(self.api_url, json=payload, timeout=20)
            ct = r.headers.get("content-type", "")
            if "json" in ct and r.status_code == 200:
                try:
                    js = r.json()
                    # Check if response is valid JSON structure
                    if isinstance(js.get("result"), dict):
                        return "ok"
                except: pass
            
            # Use pipeline detector if available, or just heuristic
            text = r.text[:4000].lower()
            if "aliyun_waf" in text or "captcha" in text or r.status_code == 405:
                return "slider"
            return "slider" # Fallback to assume slider if HTTP fails
        except Exception:
            return "slider" # Network error likely means blocked or needs browser

    def solve_slider_cdp(self) -> bool:
        # Spin up Playwright to solve slider
        global CHROME_CDP_URL
        if not CHROME_CDP_URL:
             CHROME_CDP_URL = launch_chrome_for_cdp()
        
        if not CHROME_CDP_URL:
            self.log_error("Could not launch Chrome for CDP.")
            return False

        return asyncio.run(self._solve_slider_async())

    async def _solve_slider_async(self):
        async with async_playwright() as p:
            try:
                browser = await p.chromium.connect_over_cdp(CHROME_CDP_URL)
                if browser.contexts: context = browser.contexts[0]
                else: context = await browser.new_context()
                
                page = await context.new_page()
                try:
                    await page.goto(self.get_landing_url(), timeout=30000)
                    # Trigger slider check (often on load or first request)
                    # We might need to trigger a search to see the slider
                    
                    found, passed = await self._handle_slider_captcha(page, manual_mode=self.interactive)
                    if passed:
                        # Sync cookies
                        cookies = await context.cookies()
                        for c in cookies:
                            self.session.cookies.set(c['name'], c['value'], domain=c['domain'], path=c['path'])
                        return True
                    return False
                finally:
                   await page.close()
            except Exception as e:
                self.log_error(f"CDP Slider Solve Error: {e}")
                return False

    def fetch_page_items(self, page_no: int) -> List[Dict[str, Any]]:
        # Try HTTP first
        payload = self._build_search_payload(page_no)
        items = []
        try:
            r = self.session.post(self.api_url, json=payload, timeout=30)
            data = r.json()
            if data:
                 res = data.get("result", {})
                 if isinstance(res, dict):
                      items = res.get("data", [])
        except Exception as e:
            # If HTTP fails, we might need to use browser to fetch items too?
            # Or just let the loop continue and next probe will trigger slider solve again.
            self.log_error(f"Fetch page HTTP failed: {e}")
            raise # Raise to trigger probe_phase

        # Normalization
        for item in items:
            item["title"] = item.get("title", "No Title")
            item_id = item.get("articleId")
            if item_id:
                item["detail_url"] = f"http://www.ccgp-xinjiang.gov.cn/site/detail?parentId=3661&articleId={quote(str(item_id))}"
        return items

    def _build_search_payload(self, page_no: int) -> Dict[str, Any]:
        payload = {
            "pageNo": page_no,
            "pageSize": self.config.get("page_size", 15),
            "categoryCode": "ZcyAnnouncement2",
            "_t": str(int(time.time() * 1000)),
        }
        if self.keywords:
            payload["keyword"] = self.keywords[0]
        if self.region:
            payload["districtCode"] = [self.region]
        if self.start_date:
            payload["publishDateBegin"] = self.start_date
        if self.end_date:
            payload["publishDateEnd"] = self.end_date
        return payload

    def extract_item_timestamp(self, item: Dict[str, Any]) -> Optional[int]:
        pd = item.get("publishDate")
        if pd:
             try: return int(pd)
             except: pass
        return None

    def extract_item_id(self, item: Dict[str, Any]) -> str:
         return str(item.get("articleId", "")) or str(item.get("id", ""))

    def fetch_detail(self, item_id: str) -> Dict[str, Any]:
        # Using item_id alone is hard because Xinjiang detail URL construction needs params
        # BaseSpider flow passes item_id. But our BaseSpider implementation in process_details
        # calls fetch_detail(item_id). 
        # But Xinjiang needs announcementUrl or other params from list item.
        # So I might need to override process_details in BaseSpider to pass full item?
        # OR, I can cache items in a dict in this class?
        # Actually BaseSpider::process_details iterates items and calls fetch_detail.
        # I should simply store 'current_item' or just use URL if possible.
        # Wait, BaseSpider.process_details calls: detail_data = self.fetch_detail(item_id)
        # This is a bit restrictive for detailed flow. 
        # I will hack it by storing the items map or overriding process_details.
        # But wait, BaseSpider::process_details is:
        # for idx, item in enumerate(collected): ... fetch_detail(item_id)
        # I previously implemented fetch_detail taking only item_id.
        
        # Let's override process_details in this subclass to be safe, or just utilize the fact that
        # I can look up the item from `self.collected` (if I had access).
        # Actually, `fetch_detail` in my BaseSpider definition takes `item_id`.
        # I will implement `fetch_detail` to return empty wrapper and do the real work in `save_detail`
        # OR, better: `BaseSpider` passes `item` to `save_detail`, but `fetch_detail` only gets ID.
        
        # NOTE: I will override `process_details` to handle the complexity of Xinjiang where
        # we might need to use Playwright to fetch detail if HTTP fails.
        raise NotImplementedError("Overridden process_details")

    def process_details(self, collected: List[Dict[str, Any]]):
        details_dir = os.path.join(self.out_dir, "details")
        ensure_dir(details_dir)
        done_ids = set(self.ctx.checkpoint.get("detail_done_ids", []))

        for idx, item in enumerate(collected):
            item_id = self.extract_item_id(item)
            if not item_id or str(item_id) in done_ids: continue
            
            self.log_info(f"Fetching detail {item_id} ({idx+1}/{len(collected)})")
            
            detail_data = {}
            # Try HTTP
            try:
                detail_data = self._get_detail_http(item)
            except Exception:
                pass
                
            # If HTTP failed (empty html) or blocked, try browser
            if not detail_data.get("html"):
                 try:
                     # ensure CDP
                     if not CHROME_CDP_URL: launch_chrome_for_cdp()
                     detail_data = asyncio.run(self.get_detail_with_playwright(item))
                 except Exception as e:
                     self.log_error(f"Browser detail fetch failed: {e}")

            if detail_data.get("html") or detail_data.get("offline_html"):
                 self.save_detail(item, detail_data, details_dir)
                 done_ids.add(str(item_id))
                 self.ctx.set_checkpoint(detail_done_ids=list(done_ids))
                 self.ctx.save_checkpoint()
            else:
                 self.log_error(f"Failed to fetch detail {item_id}")

    def save_detail(self, item: Dict[str, Any], detail: Dict[str, Any], base_dir: str):
        title = item.get("title", "detail")
        item_id = self.extract_item_id(item)
        safe_title = sanitize_filename(f"{item_id}_{title}")
        item_dir = os.path.join(base_dir, safe_title)
        ensure_dir(item_dir)
        
        write_json(os.path.join(item_dir, "item.json"), item)
        # detail is just dict with html, final_url etc
        
        html_c = detail.get("offline_html") or detail.get("html", "")
        if html_c:
             with open(os.path.join(item_dir, "detail.html"), "w", encoding="utf-8") as f:
                 f.write(html_c)

    # --- HTTP/Browser Detail Helpers (ported/simplified) ---
    def _get_detail_http(self, item):
         url = item.get("detail_url") or item.get("announcementUrl")
         if not url: return {}
         self._ensure_http_warmed()
         r = self.session.get(url, timeout=30)
         return {"html": r.text, "final_url": r.url, "offline_html": r.text}

    async def get_detail_with_playwright(self, item):
         url = item.get("detail_url") or item.get("announcementUrl")
         if not url: return {}
         async with async_playwright() as p:
             browser = await p.chromium.connect_over_cdp(CHROME_CDP_URL)
             context = browser.contexts[0] if browser.contexts else await browser.new_context()
             page = await context.new_page()
             try:
                 await page.goto(url, timeout=40000, wait_until="domcontentloaded")
                 
                 # Check captcha
                 found, passed = await self._handle_slider_captcha(page)
                 if found and not passed: return {} # Failed
                 
                 # Wait for content
                 try:
                      await page.wait_for_selector(".detail-content", timeout=10000)
                 except: pass
                 
                 return {"html": await page.content(), "final_url": page.url}
             finally:
                 await page.close()

    # --- Slider Logic (Ported) ---
    async def _handle_slider_captcha(self, page, manual_mode=False):
        SLIDER_SELECTORS = [
            "#aliyunCaptcha-sliding-slider", ".aliyunCaptcha-sliding-slider", 
            "#nc_1_n1z", ".nc-container .btn_slide"
        ]
        
        slider = None
        for sel in SLIDER_SELECTORS:
             try: 
                 if await page.is_visible(sel):
                     slider = await page.wait_for_selector(sel, timeout=1000)
                     break
             except: pass
        
        if not slider: 
            return False, True # No captcha found (passed)

        print("[验证码] 检测到滑块，准备破解...")
        
        # 1. Capture images
        shadow_bytes, bg_bytes = await self._capture_captcha_images(page)
        gap_distance = 0
        
        if shadow_bytes and bg_bytes:
            gap_distance = self._detect_gap_distance(shadow_bytes, bg_bytes)
            # Scale adjustment if needed (simplified here, in real scenario we check element width vs image width)
            # Assuming 1:1 for simplicity or that detect_gap returns pixels relative to image which matches element
            # Often need scaling:
            try:
                bg_el = await page.query_selector(".aliyunCaptcha-sliding-img img")
                if bg_el:
                    bbox = await bg_el.bounding_box()
                    # If we could read real image width from bytes
                    arr = np.frombuffer(bg_bytes, np.uint8)
                    real_img = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
                    if real_img is not None:
                        real_w = real_img.shape[1]
                        scale = bbox["width"] / real_w
                        gap_distance = int(gap_distance * scale)
            except Exception:
                pass
        
        if gap_distance == 0:
            gap_distance = 260 # Fallback
            
        # 2. Generate track
        track = self._generate_human_track(gap_distance)
        
        # 3. Slide
        box = await slider.bounding_box()
        if not box: return True, False
        
        start_x = box["x"] + box["width"] / 2
        start_y = box["y"] + box["height"] / 2
        
        await page.mouse.move(start_x, start_y)
        await page.mouse.down()
        for p in track:
            await page.mouse.move(start_x + p["x"], start_y + p["y"])
            # await asyncio.sleep(p["delay"]) # create_human_track usually has delays, but here p is dict
            if "delay" in p:
                await asyncio.sleep(p["delay"])
            else:
                 await asyncio.sleep(0.01)
        await page.mouse.up()
        
        # 4. Check result
        await asyncio.sleep(2)
        if not await slider.is_visible():
            return True, True

        if manual_mode:
             print("[验证码] 自动破解失败，请手动滑动...")
             await WindowController.restore()
             # Wait loop
             for _ in range(30):
                 if not await slider.is_visible():
                     await WindowController.minimize()
                     return True, True
                 await asyncio.sleep(1)
             await WindowController.minimize()
        
        return True, False

    async def _capture_captcha_images(self, frame):
        # frame can be page or frame
        js = """
        async () => {
            function getDataUrl(img) {
                const canvas = document.createElement('canvas');
                canvas.width = img.naturalWidth;
                canvas.height = img.naturalHeight;
                canvas.getContext('2d').drawImage(img, 0, 0);
                return canvas.toDataURL('image/png');
            }
            const bg = document.querySelector('.aliyunCaptcha-sliding-img img');
            const shadow = document.querySelector('.aliyunCaptcha-sliding-block img'); // selector varies
            if (!bg) return null;
            return {
                bg: getDataUrl(bg),
                shadow: shadow ? getDataUrl(shadow) : null
            };
        }
        """
        try:
             # Try generic selectors for aliyun
             # Note: Actual logic invokes 'evaluate' on frame
             data = await frame.evaluate(js)
             if not data: return None, None
             
             import base64
             def decode(d):
                 if not d: return None
                 return base64.b64decode(d.split(',')[1])
                 
             return decode(data.get("shadow")), decode(data.get("bg"))
        except:
             return None, None

    def _detect_gap_distance(self, shadow_bytes, bg_bytes):
        if not shadow_bytes or not bg_bytes: return None
        try:
            shadow_arr = np.frombuffer(shadow_bytes, np.uint8)
            bg_arr = np.frombuffer(bg_bytes, np.uint8)
            
            shadow = cv2.imdecode(shadow_arr, cv2.IMREAD_GRAYSCALE)
            bg = cv2.imdecode(bg_arr, cv2.IMREAD_GRAYSCALE)
            
            if shadow is None or bg is None: return None
            
            # Simple template matching or edge detection
            # Aliyun often has the gap in BG directly or we match shadow to BG
            # Here we assume standard gap detection: Canny edge + max diff or template match
            
            # Simplified robust logic:
            # 1. Edge detection on bg
            bg_edge = cv2.Canny(bg, 100, 200)
            shadow_edge = cv2.Canny(shadow, 100, 200)
            
            res = cv2.matchTemplate(bg_edge, shadow_edge, cv2.TM_CCOEFF_NORMED)
            min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)
            
            return max_loc[0] # x coordinate
        except:
            return None

    def _generate_human_track(self, distance, duration=0.5):
        # Wrapper around ccgp_core.human_track.create_human_track if available, 
        # or inline logic to satisfy regression test of exact distance sum
        from ccgp_core.human_track import create_human_track
        return create_human_track(distance, duration=duration)
