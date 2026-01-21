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
from ccgp_core.output import ensure_dir, write_json
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
        os.getenv("CHROME_BIN"),
        os.getenv("CHROME_EXECUTABLE_PATH"),
        os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    # Filter out None and non-existent paths
    chrome_path = None
    for path in possible_paths:
        if path and os.path.exists(path):
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
        
        # 浏览器模式标志：当 WAF 使用 JS 挑战时，使用 Playwright 获取数据
        self._use_browser_mode = False
        self._browser_context = None
        
        # Params
        self.start_date = config.get("start_date")
        self.end_date = config.get("end_date")
        self.region = config.get("region", "650000")
        self.window_keyword = config.get("window_keyword", "新疆政府采购")
        
    def get_landing_url(self) -> str:
        return f"{self.base_url}/site/category?parentId=3661"

    def _ensure_http_warmed(self):
        if self._http_warmed: return
        try:
             self.session.get(self.get_landing_url(), timeout=15)
        except: pass
        self._http_warmed = True

    def _do_probe_request(self) -> str:
        """
        探测请求：检测 HTTP 是否被 WAF 拦截
        返回: 'ok', 'slider', 'captcha', 'network_error'
        """
        self._ensure_http_warmed()
        payload = self._build_search_payload(1)
        
        try:
            self.log_info(f"[探测] 发起 HTTP 探测请求到 {self.api_url}")
            self.log_info(f"[探测] Session cookies: {list(self.session.cookies.keys())}")
            
            r = self.session.post(self.api_url, json=payload, timeout=20)
            ct = r.headers.get("content-type", "")
            
            self.log_info(f"[探测] HTTP 响应: status={r.status_code}, content-type={ct}")
            self.log_info(f"[探测] 响应内容预览: {r.text[:500]}")
            
            # 检查是否是正常的 JSON 响应
            if r.status_code == 200 and "json" in ct.lower():
                try:
                    js = r.json()
                    # 检查 JSON 结构 - 放宽条件
                    result = js.get("result")
                    if result is not None:
                        # result 可以是 dict、list 或其他非空值
                        self.log_info(f"[探测] JSON 响应有效，result 类型: {type(result).__name__}")
                        return "ok"
                    elif "data" in js:
                        self.log_info("[探测] JSON 响应有效 (包含 data 字段)")
                        return "ok"
                    else:
                        self.log_info(f"[探测] JSON 响应结构不符预期: {list(js.keys())}")
                except Exception as e:
                    self.log_error(f"[探测] JSON 解析失败: {e}")
            
            # 检测 WAF/验证码标记
            text = r.text[:4000].lower()
            if "aliyun" in text or "waf" in text or "captcha" in text or "滑块" in text:
                self.log_info("[探测] 检测到 WAF/验证码关键词，自动启用浏览器模式")
                self._use_browser_mode = True
                return "ok"  # 返回 ok 因为浏览器模式可以处理
            
            if r.status_code == 405:
                self.log_info("[探测] HTTP 405 错误，可能需要验证")
                return "slider"
            
            if r.status_code >= 400:
                self.log_info(f"[探测] HTTP 错误 {r.status_code}")
                return "slider"
            
            # 如果响应是 200 但不是预期的 JSON，可能需要验证
            self.log_info("[探测] 响应非预期格式，假定需要验证")
            return "slider"
            
        except requests.exceptions.Timeout:
            self.log_error("[探测] 请求超时")
            return "network_error"
        except Exception as e:
            self.log_error(f"[探测] 请求异常: {e}")
            return "slider"

    def solve_slider_cdp(self) -> bool:
        """
        使用 CDP 解决滑块验证码。
        如果成功，会启用浏览器模式来绑定后续所有请求。
        """
        global CHROME_CDP_URL
        if not CHROME_CDP_URL:
            CHROME_CDP_URL = launch_chrome_for_cdp()
        
        if not CHROME_CDP_URL:
            self.log_error("Could not launch Chrome for CDP.")
            return False

        return asyncio.run(self._solve_slider_async())

    async def _solve_slider_async(self):
        """
        通过 Playwright/CDP 解决滑块验证码
        关键：需要在浏览器中触发 API 请求才能显示阿里云滑块
        """
        async with async_playwright() as p:
            try:
                browser = await p.chromium.connect_over_cdp(CHROME_CDP_URL)
                if browser.contexts:
                    context = browser.contexts[0]
                else:
                    context = await browser.new_context()
                
                page = await context.new_page()
                try:
                    self.log_info(f"[滑块] 导航到: {self.get_landing_url()}")
                    await page.goto(self.get_landing_url(), timeout=30000, wait_until="domcontentloaded")
                    
                    # 等待页面加载
                    await asyncio.sleep(2)
                    
                    # 策略1: 首先检查页面上是否已经有滑块
                    found, passed = await self._handle_slider_captcha(page, manual_mode=self.interactive)
                    if found and passed:
                        self.log_info("[滑块] 首次检查通过")
                        cookies = await context.cookies()
                        for c in cookies:
                            self.session.cookies.set(c['name'], c['value'], domain=c.get('domain', ''), path=c.get('path', '/'))
                        return True
                    
                    # 策略2: 如果没有找到滑块，尝试在浏览器中触发 API 请求
                    if not found:
                        self.log_info("[滑块] 页面上未发现滑块，尝试触发 API 请求...")
                        
                        # 在浏览器中执行 fetch 请求来触发阿里云滑块
                        payload = self._build_search_payload(1)
                        trigger_js = f"""
                        async () => {{
                            try {{
                                const response = await fetch('{self.api_url}', {{
                                    method: 'POST',
                                    headers: {{
                                        'Content-Type': 'application/json',
                                        'Accept': 'application/json, text/plain, */*',
                                        'X-Requested-With': 'XMLHttpRequest'
                                    }},
                                    body: JSON.stringify({json.dumps(payload)})
                                }});
                                
                                const text = await response.text();
                                return {{
                                    status: response.status,
                                    ok: response.ok,
                                    contentType: response.headers.get('content-type') || '',
                                    bodyPreview: text.substring(0, 500)
                                }};
                            }} catch (e) {{
                                return {{error: e.toString()}};
                            }}
                        }}
                        """
                        
                        try:
                            result = await page.evaluate(trigger_js)
                            self.log_info(f"[滑块] API 请求结果: status={result.get('status')}, ok={result.get('ok')}")
                            
                            if result.get('error'):
                                self.log_error(f"[滑块] API 请求错误: {result.get('error')}")
                        except Exception as e:
                            self.log_error(f"[滑块] 执行 API 请求失败: {e}")
                        
                        # 等待滑块出现
                        await asyncio.sleep(2)
                        
                        # 再次检查滑块
                        found2, passed2 = await self._handle_slider_captcha(page, manual_mode=self.interactive)
                        if passed2:
                            self.log_info("[滑块] 第二次检查通过")
                            cookies = await context.cookies()
                            for c in cookies:
                                self.session.cookies.set(c['name'], c['value'], domain=c.get('domain', ''), path=c.get('path', '/'))
                            return True
                        elif found2:
                            # 找到了滑块但未通过
                            self.log_info("[滑块] 检测到滑块但自动破解失败")
                            return False
                    
                    # 策略3: 尝试点击页面上的搜索按钮触发
                    self.log_info("[滑块] 尝试点击搜索触发...")
                    search_btn_selectors = [
                        ".search-btn", 
                        "button[type='submit']",
                        ".btn-search",
                        "input[type='submit']",
                    ]
                    for sel in search_btn_selectors:
                        try:
                            btn = await page.query_selector(sel)
                            if btn and await btn.is_visible():
                                await btn.click()
                                await asyncio.sleep(2)
                                
                                found3, passed3 = await self._handle_slider_captcha(page, manual_mode=self.interactive)
                                if passed3:
                                    self.log_info("[滑块] 点击搜索后验证通过")
                                    cookies = await context.cookies()
                                    for c in cookies:
                                        self.session.cookies.set(c['name'], c['value'], domain=c.get('domain', ''), path=c.get('path', '/'))
                                    return True
                                break
                        except Exception:
                            pass
                    
                    # 如果所有策略都失败，尝试手动模式
                    if self.interactive:
                        self.log_info("[滑块] 所有自动策略失败，等待人工验证...")
                        WindowController.restore(self.window_keyword)
                        
                        for _ in range(60):
                            # 检查是否通过（页面变化或cookies出现）
                            cookies = await context.cookies()
                            cookie_names = [c['name'] for c in cookies]
                            if any('aliyun' in name.lower() or 'acw' in name.lower() for name in cookie_names):
                                WindowController.minimize(self.window_keyword)
                                self.log_info("[滑块] 检测到验证 cookies，人工验证成功")
                                for c in cookies:
                                    self.session.cookies.set(c['name'], c['value'], domain=c.get('domain', ''), path=c.get('path', '/'))
                                return True
                            await asyncio.sleep(1)
                        
                        WindowController.minimize(self.window_keyword)
                    
                    self.log_error("[滑块] 所有验证策略均失败")
                    return False
                    
                finally:
                    await page.close()
            except Exception as e:
                self.log_error(f"CDP Slider Solve Error: {e}")
                import traceback
                traceback.print_exc()
                return False

    def fetch_page_items(self, page_no: int) -> List[Dict[str, Any]]:
        """
        获取列表页数据。
        如果启用了浏览器模式，使用 Playwright 获取；否则使用 HTTP Session。
        """
        if self._use_browser_mode:
            return asyncio.run(self._fetch_page_items_browser(page_no))
        
        # HTTP 模式
        payload = self._build_search_payload(page_no)
        items = []
        try:
            r = self.session.post(self.api_url, json=payload, timeout=30)
            ct = r.headers.get("content-type", "").lower()
            
            # 检查是否被 WAF 拦截
            if "json" not in ct or "aliyun" in r.text[:1000].lower():
                self.log_info("[获取] HTTP 请求被 WAF 拦截，切换到浏览器模式")
                self._use_browser_mode = True
                return asyncio.run(self._fetch_page_items_browser(page_no))
            
            data = r.json()
            if data:
                res = data.get("result", {})
                if isinstance(res, dict):
                    items = res.get("data", [])
        except Exception as e:
            self.log_error(f"Fetch page HTTP failed: {e}")
            # 尝试使用浏览器模式
            self._use_browser_mode = True
            return asyncio.run(self._fetch_page_items_browser(page_no))

        # Normalization
        for item in items:
            item["title"] = item.get("title", "No Title")
            item_id = item.get("articleId")
            if item_id:
                item["detail_url"] = f"http://www.ccgp-xinjiang.gov.cn/site/detail?parentId=3661&articleId={quote(str(item_id))}"
        return items

    async def _fetch_page_items_browser(self, page_no: int) -> List[Dict[str, Any]]:
        """
        使用 Playwright 浏览器获取列表页数据（绕过 WAF JS 挑战）
        """
        global CHROME_CDP_URL
        
        # 确保 Chrome 已启动
        if not CHROME_CDP_URL:
            self.log_info("[浏览器模式] Chrome 未启动，正在启动...")
            CHROME_CDP_URL = launch_chrome_for_cdp()
            if not CHROME_CDP_URL:
                self.log_error("[浏览器模式] 无法启动 Chrome")
                return []
            self.log_info(f"[浏览器模式] Chrome 启动成功: {CHROME_CDP_URL}")
        
        self.log_info(f"[浏览器模式] 获取第 {page_no} 页数据...")
        
        payload = self._build_search_payload(page_no)
        items = []
        
        async with async_playwright() as p:
            try:
                browser = await p.chromium.connect_over_cdp(CHROME_CDP_URL)
                if browser.contexts:
                    context = browser.contexts[0]
                else:
                    context = await browser.new_context()
                
                page = await context.new_page()
                try:
                    await page.goto(self.get_landing_url(), timeout=30000, wait_until="domcontentloaded")
                    await asyncio.sleep(1)
                    
                    # 模拟人类行为：滚动和点击，增加真实感
                    try:
                        await page.evaluate("window.scrollTo({top: 100, behavior: 'smooth'})")
                        await asyncio.sleep(0.5)
                        await page.mouse.move(100, 100)
                        await page.mouse.click(100, 100)
                    except: pass

                    result = {}
                    if page_no == 1:
                        self.log_info("[浏览器模式] 尝试通过页面交互捕获真实 API 请求...")
                        try:
                            # 尝试点击搜索并拦截请求
                            async with page.expect_response(
                                lambda r: r.status == 200 and r.request.method == "POST" and "json" in r.headers.get("content-type", "").lower() and len(r.url) > 20,
                                timeout=60000
                            ) as response_info:
                                search_clicked = False
                                for sel in [".search-btn", ".btn-search", "button[type='button']", "input[type='submit']", ".icon-search"]:
                                    if await page.is_visible(sel):
                                        await page.click(sel)
                                        search_clicked = True
                                        break
                                if not search_clicked:
                                    self.log_info("[浏览器模式] Warning: 未找到搜索按钮，等待可能自动发出的请求...")
                            
                            response = await response_info.value
                            self.log_info(f"[浏览器模式] 捕获到真实 API URL: {response.url}")
                            self.api_url = response.url
                            json_data = await response.json()
                            result = {"success": True, "data": json_data}
                        except Exception as capture_err:
                            self.log_info(f"[浏览器模式] Warning: 捕获请求超时或失败: {capture_err}，尝试回退到 fetch")

                    if not result.get("success"):
                        # 使用 json.dumps 确保 JS 代码安全
                        payload_json = json.dumps(payload)
                        fetch_js = """
                        async () => {
                            try {
                                const response = await fetch('""" + self.api_url + """', {
                                    method: 'POST',
                                    headers: {
                                        'Content-Type': 'application/json',
                                        'Accept': 'application/json, text/plain, */*',
                                        'X-Requested-With': 'XMLHttpRequest'
                                    },
                                    body: JSON.stringify(""" + payload_json + """)
                                });
                                
                                if (!response.ok) {
                                    return {error: 'HTTP ' + response.status};
                                }
                                
                                const data = await response.json();
                                return {success: true, data: data};
                            } catch (e) {
                                return {error: e.toString()};
                            }
                        }
                        """
                        
                        self.log_info(f"[浏览器模式] 执行 API 请求 (URL: {self.api_url})...")
                        result = await page.evaluate(fetch_js)
                    
                    if not isinstance(result, dict):
                        self.log_error(f"[浏览器模式] 异常：evaluate返回非字典类型 {type(result)}")
                        return []
                    
                    if result.get("error"):
                        self.log_error(f"[浏览器模式] API 请求失败: {result.get('error')}")
                        
                        # 检查是否需要处理滑块
                        found, passed = await self._handle_slider_captcha(page, manual_mode=self.interactive)
                        if found and not passed:
                            self.log_error("[浏览器模式] 滑块验证失败")
                            return []
                        
                        # 重试请求
                        await asyncio.sleep(1)
                        result = await page.evaluate(fetch_js)
                        
                        if not isinstance(result, dict) or result.get("error"):
                            self.log_error(f"[浏览器模式] 重试失败: {result.get('error') if isinstance(result, dict) else result}")
                            return []
                    
                    if result.get("success"):
                        data = result.get("data")
                        if isinstance(data, dict):
                            res = data.get("result")
                            if isinstance(res, dict):
                                raw_items = res.get("data")
                                if isinstance(raw_items, list):
                                    items = [i for i in raw_items if isinstance(i, dict)]
                                elif isinstance(raw_items, dict):
                                    self.log_info(f"[浏览器模式] res['data'] 是字典，尝试查找列表字段 (keys: {list(raw_items.keys())})")
                                    possible_keys = ["data", "records", "rows", "list", "content", "result", "children"]
                                    found_list = None
                                    for k in possible_keys:
                                        if isinstance(raw_items.get(k), list):
                                            found_list = raw_items.get(k)
                                            break
                                    
                                    if found_list is not None:
                                        items = [i for i in found_list if isinstance(i, dict)]
                                    else:
                                        self.log_error(f"[浏览器模式] 无法在 res['data'] 中找到列表数据")
                                else:
                                    self.log_error(f"[浏览器模式] res['data'] 不是列表: {type(raw_items)}")
                            else:
                                self.log_error(f"[浏览器模式] data['result'] 不是字典: {type(res)}")
                        else:
                            self.log_error(f"[浏览器模式] result['data'] 不是字典: {type(data)}")
                        
                        self.log_info(f"[浏览器模式] 获取到 {len(items)} 条数据")
                    
                finally:
                    await page.close()
                    
            except Exception as e:
                self.log_error(f"[浏览器模式] 异常: {e}")
                import traceback
                traceback.print_exc()
        
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
         
         # 反反爬虫: 详情页请求后随机延迟
         from ccgp_core.request_fingerprint import random_delay
         random_delay(0.5, 1.5)
         
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

    # --- Slider Logic (Enhanced) ---
    async def _handle_slider_captcha(self, page, manual_mode=False, max_retries=3):
        """
        增强版滑块验证码处理
        - 支持多种选择器适配不同版本阿里云滑块
        - 最多重试 max_retries 次
        - 改进的间隙检测和轨迹生成
        """
        # 扩展的滑块选择器列表（支持多版本阿里云滑块）
        SLIDER_SELECTORS = [
            # 新版阿里云滑块
            "#aliyunCaptcha-sliding-slider",
            ".aliyunCaptcha-sliding-slider",
            "[class*='aliyunCaptcha'][class*='slider']",
            # 旧版阿里云滑块  
            "#nc_1_n1z",
            "#nc_2_n1z",
            ".nc-container .btn_slide",
            ".nc_scale_text .btn_slide",
            ".nc_iconfont.btn_slide",
            # 通用滑块选择器
            ".slider-btn",
            ".slide-btn",
            "[class*='slider'][class*='btn']",
        ]
        
        slider = None
        matched_selector = None
        
        # 等待页面完全加载
        await asyncio.sleep(0.5)
        
        for sel in SLIDER_SELECTORS:
            try:
                if await page.is_visible(sel):
                    slider = await page.wait_for_selector(sel, timeout=2000)
                    matched_selector = sel
                    break
            except Exception:
                pass
        
        if not slider:
            self.log_info("[滑块] 未检测到滑块验证码，跳过")
            return False, True  # No captcha found (passed)

        self.log_info(f"[滑块] 检测到滑块验证码 (选择器: {matched_selector})，准备自动破解...")
        
        for attempt in range(1, max_retries + 1):
            self.log_info(f"[滑块] 第 {attempt}/{max_retries} 次尝试...")
            
            # 1. 捕获验证码图片
            shadow_bytes, bg_bytes = await self._capture_captcha_images(page)
            gap_distance = None
            
            if shadow_bytes and bg_bytes:
                # 尝试检测间隙距离
                gap_distance = self._detect_gap_distance(shadow_bytes, bg_bytes)
                self.log_info(f"[滑块] 检测到间隙距离: {gap_distance} 像素")
                
                # 缩放校正
                if gap_distance:
                    try:
                        # 尝试多种背景图选择器
                        bg_selectors = [
                            ".aliyunCaptcha-sliding-img img",
                            "[class*='aliyunCaptcha'] img:not([class*='block'])",
                            ".nc_bg img",
                            ".yundun-captcha img",
                        ]
                        bg_el = None
                        for bg_sel in bg_selectors:
                            try:
                                bg_el = await page.query_selector(bg_sel)
                                if bg_el:
                                    break
                            except:
                                pass
                        
                        if bg_el:
                            bbox = await bg_el.bounding_box()
                            if bbox:
                                arr = np.frombuffer(bg_bytes, np.uint8)
                                real_img = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
                                if real_img is not None:
                                    real_w = real_img.shape[1]
                                    if real_w > 0:
                                        scale = bbox["width"] / real_w
                                        gap_distance = int(gap_distance * scale)
                                        self.log_info(f"[滑块] 缩放后间隙距离: {gap_distance} 像素 (scale: {scale:.2f})")
                    except Exception as e:
                        self.log_error(f"[滑块] 缩放校正失败: {e}")
            else:
                self.log_info("[滑块] 无法捕获验证码图片，使用动态fallback")
            
            # 动态 fallback 距离（根据尝试次数微调）
            if not gap_distance or gap_distance <= 0:
                # 使用随机fallback以增加成功概率
                base_distances = [220, 240, 260, 280]
                gap_distance = base_distances[(attempt - 1) % len(base_distances)] + random.randint(-10, 10)
                self.log_info(f"[滑块] 使用动态fallback距离: {gap_distance} 像素")
            
            # 2. 生成人类轨迹（根据尝试次数调整速度）
            duration = 0.4 + (attempt - 1) * 0.15  # 每次尝试稍微慢一点
            track = self._generate_human_track(gap_distance, duration=duration)
            
            # 3. 执行滑动
            box = await slider.bounding_box()
            if not box:
                self.log_error("[滑块] 无法获取滑块位置")
                await asyncio.sleep(1)
                continue
            
            start_x = box["x"] + box["width"] / 2
            start_y = box["y"] + box["height"] / 2
            
            # 模拟真实的鼠标移动
            await page.mouse.move(start_x + random.uniform(-5, 5), start_y + random.uniform(-3, 3))
            await asyncio.sleep(random.uniform(0.1, 0.3))
            await page.mouse.move(start_x, start_y)
            await asyncio.sleep(random.uniform(0.05, 0.15))
            
            await page.mouse.down()
            await asyncio.sleep(random.uniform(0.02, 0.08))
            
            for p in track:
                await page.mouse.move(start_x + p["x"], start_y + p["y"])
                if "delay" in p:
                    await asyncio.sleep(p["delay"])
                else:
                    await asyncio.sleep(0.01)
            
            await asyncio.sleep(random.uniform(0.05, 0.15))
            await page.mouse.up()
            
            # 4. 检查结果
            await asyncio.sleep(1.5 + random.uniform(0, 0.5))
            
            # 检查滑块是否消失（验证成功）
            slider_still_visible = False
            try:
                slider_still_visible = await page.is_visible(matched_selector)
            except:
                pass
            
            if not slider_still_visible:
                self.log_info(f"[滑块] ✓ 验证成功！(第 {attempt} 次尝试)")
                return True, True
            
            # 检查是否有错误提示
            error_indicators = [
                ".aliyunCaptcha-sliding-tips",
                ".nc_iconfont.icon_warn",
                "[class*='error']",
                "[class*='fail']",
            ]
            has_error = False
            for err_sel in error_indicators:
                try:
                    if await page.is_visible(err_sel):
                        has_error = True
                        break
                except:
                    pass
            
            if has_error:
                self.log_info(f"[滑块] 第 {attempt} 次尝试失败，检测到错误提示")
            else:
                self.log_info(f"[滑块] 第 {attempt} 次尝试未通过验证")
            
            # 等待重试
            if attempt < max_retries:
                wait_time = 1.5 + attempt * 0.5
                self.log_info(f"[滑块] 等待 {wait_time:.1f} 秒后重试...")
                await asyncio.sleep(wait_time)
                
                # 刷新滑块（如果需要）
                try:
                    refresh_btn = await page.query_selector(".aliyunCaptcha-sliding-refresh, .nc_iconfont.icon_refresh")
                    if refresh_btn and await refresh_btn.is_visible():
                        await refresh_btn.click()
                        await asyncio.sleep(1)
                except:
                    pass

        # 所有自动尝试失败
        self.log_info(f"[滑块] 自动破解失败（共 {max_retries} 次尝试）")
        
        if manual_mode:
            self.log_info("[滑块] 请手动完成滑块验证...")
            WindowController.restore(self.window_keyword)
            
            # 等待人工验证完成
            for _ in range(60):  # 最多等待60秒
                try:
                    if not await page.is_visible(matched_selector):
                        WindowController.minimize(self.window_keyword)
                        self.log_info("[滑块] ✓ 人工验证成功！")
                        return True, True
                except:
                    pass
                await asyncio.sleep(1)
            
            WindowController.minimize(self.window_keyword)
        
        return True, False




    async def _capture_captcha_images(self, frame):
        """
        增强版验证码图片捕获
        支持多种阿里云滑块版本的选择器
        """
        # 多版本选择器的JS代码
        js = """
        async () => {
            function getDataUrl(img) {
                if (!img) return null;
                try {
                    const canvas = document.createElement('canvas');
                    canvas.width = img.naturalWidth || img.width;
                    canvas.height = img.naturalHeight || img.height;
                    const ctx = canvas.getContext('2d');
                    ctx.drawImage(img, 0, 0);
                    return canvas.toDataURL('image/png');
                } catch (e) {
                    return null;
                }
            }
            
            // 多种背景图选择器
            const bgSelectors = [
                '.aliyunCaptcha-sliding-img img',
                '[class*="aliyunCaptcha"] [class*="img"] img',
                '.nc_bg img',
                '.yundun-captcha-img img',
                'img[class*="captcha-bg"]',
                'img[src*="captcha"]',
            ];
            
            // 多种滑块图选择器
            const shadowSelectors = [
                '.aliyunCaptcha-sliding-block img',
                '[class*="aliyunCaptcha"] [class*="block"] img',
                '.nc_jig img',
                '.yundun-captcha-block img',
                'img[class*="captcha-block"]',
            ];
            
            let bg = null;
            let shadow = null;
            
            // 查找背景图
            for (const sel of bgSelectors) {
                try {
                    const el = document.querySelector(sel);
                    if (el && el.complete && el.naturalWidth > 0) {
                        bg = el;
                        break;
                    }
                } catch (e) {}
            }
            
            // 查找滑块图
            for (const sel of shadowSelectors) {
                try {
                    const el = document.querySelector(sel);
                    if (el && el.complete && el.naturalWidth > 0) {
                        shadow = el;
                        break;
                    }
                } catch (e) {}
            }
            
            if (!bg) return null;
            
            return {
                bg: getDataUrl(bg),
                shadow: getDataUrl(shadow)
            };
        }
        """
        try:
            data = await frame.evaluate(js)
            if not data:
                self.log_info("[滑块] 无法通过JS捕获验证码图片")
                return None, None
            
            import base64
            def decode(d):
                if not d:
                    return None
                try:
                    return base64.b64decode(d.split(',')[1])
                except Exception:
                    return None
            
            shadow_data = decode(data.get("shadow"))
            bg_data = decode(data.get("bg"))
            
            if bg_data:
                self.log_info(f"[滑块] 成功捕获背景图 ({len(bg_data)} bytes)")
            if shadow_data:
                self.log_info(f"[滑块] 成功捕获滑块图 ({len(shadow_data)} bytes)")
            
            return shadow_data, bg_data
        except Exception as e:
            self.log_error(f"[滑块] 捕获验证码图片异常: {e}")
            return None, None

    def _detect_gap_distance(self, shadow_bytes, bg_bytes):
        """
        增强版间隙检测算法
        使用多种边缘检测参数和模板匹配方法的组合
        """
        if not shadow_bytes or not bg_bytes:
            return None
        
        try:
            shadow_arr = np.frombuffer(shadow_bytes, np.uint8)
            bg_arr = np.frombuffer(bg_bytes, np.uint8)
            
            shadow = cv2.imdecode(shadow_arr, cv2.IMREAD_GRAYSCALE)
            bg = cv2.imdecode(bg_arr, cv2.IMREAD_GRAYSCALE)
            
            if shadow is None or bg is None:
                self.log_error("[滑块] 无法解码验证码图片")
                return None
            
            self.log_info(f"[滑块] 背景图尺寸: {bg.shape}, 滑块图尺寸: {shadow.shape}")
            
            # 检查尺寸是否合理
            if shadow.shape[0] > bg.shape[0] or shadow.shape[1] > bg.shape[1]:
                self.log_error("[滑块] 滑块图尺寸大于背景图，无法匹配")
                return None
            
            # 多种检测方法尝试
            results = []
            
            # 方法1: 边缘检测 + 模板匹配 (多种Canny参数)
            canny_params = [
                (50, 150),
                (100, 200),
                (80, 180),
            ]
            
            for low, high in canny_params:
                try:
                    bg_edge = cv2.Canny(bg, low, high)
                    shadow_edge = cv2.Canny(shadow, low, high)
                    
                    res = cv2.matchTemplate(bg_edge, shadow_edge, cv2.TM_CCOEFF_NORMED)
                    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)
                    
                    if max_val > 0.3:  # 置信度阈值
                        results.append({
                            'x': max_loc[0],
                            'confidence': max_val,
                            'method': f'Canny({low},{high})+TM_CCOEFF'
                        })
                except Exception as e:
                    pass
            
            # 方法2: 直接模板匹配 (适用于部分滑块)
            match_methods = [
                (cv2.TM_CCOEFF_NORMED, 'TM_CCOEFF_NORMED'),
                (cv2.TM_CCORR_NORMED, 'TM_CCORR_NORMED'),
            ]
            
            for method, method_name in match_methods:
                try:
                    res = cv2.matchTemplate(bg, shadow, method)
                    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)
                    
                    if max_val > 0.4:
                        results.append({
                            'x': max_loc[0],
                            'confidence': max_val,
                            'method': f'Direct+{method_name}'
                        })
                except Exception:
                    pass
            
            # 方法3: 高斯模糊后匹配
            try:
                bg_blur = cv2.GaussianBlur(bg, (5, 5), 0)
                shadow_blur = cv2.GaussianBlur(shadow, (5, 5), 0)
                
                res = cv2.matchTemplate(bg_blur, shadow_blur, cv2.TM_CCOEFF_NORMED)
                min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)
                
                if max_val > 0.35:
                    results.append({
                        'x': max_loc[0],
                        'confidence': max_val,
                        'method': 'GaussianBlur+TM_CCOEFF'
                    })
            except Exception:
                pass
            
            if not results:
                self.log_info("[滑块] 所有检测方法均未找到有效间隙")
                return None
            
            # 选择置信度最高的结果
            best = max(results, key=lambda r: r['confidence'])
            self.log_info(f"[滑块] 最佳检测结果: x={best['x']}, 置信度={best['confidence']:.3f}, 方法={best['method']}")
            
            # 验证结果合理性（间隙通常在图像中间偏右位置）
            bg_width = bg.shape[1]
            if best['x'] < 20 or best['x'] > bg_width - 20:
                self.log_info(f"[滑块] 检测到的间隙位置({best['x']})可能不合理，但仍尝试使用")
            
            return best['x']
            
        except Exception as e:
            self.log_error(f"[滑块] 间隙检测异常: {e}")
            return None

    def _generate_human_track(self, distance, duration=0.5):
        # Wrapper around ccgp_core.human_track.create_human_track if available
        from ccgp_core.human_track import create_human_track
        return create_human_track(distance, duration=duration)
