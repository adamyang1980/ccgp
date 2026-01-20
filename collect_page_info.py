#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
通用页面信息收集脚本 (Page Info Collector)
用于自动分析网页结构，收集HAR录制无法覆盖的信息：
1. 下拉选项映射 (显示文本 -> value)
2. 页面 DOM 结构 (Frame检测、关键元素)
3. Iframe 结构分析

支持 CDP 模式连接已打开的浏览器，或启动新浏览器实例。
"""

import asyncio
import json
import os
import argparse
import subprocess
import sys
import warnings
import atexit
from datetime import datetime
import time

# 抑制 Windows 上 asyncio 子进程清理产生的警告
warnings.filterwarnings("ignore", category=ResourceWarning, message=".*unclosed.*")

# 在程序退出时抑制 stderr 输出（Windows asyncio pipe 清理错误）
def _suppress_stderr_on_exit():
    """在退出时抑制 stderr，避免显示 asyncio 清理错误"""
    try:
        sys.stderr = open(os.devnull, 'w')
    except:
        pass

atexit.register(_suppress_stderr_on_exit)

# Windows 上的 asyncio 需要使用 ProactorEventLoop 才能正确处理子进程
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

def launch_chrome_for_cdp():
    """
    自动启动 Chrome 并开启远程调试端口。
    返回 CDP URL 或 None（如果失败）。
    """
    print("\n[CDP] 准备启动 Chrome...")
    
    # 检测 Chrome 路径
    possible_paths = [
        os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
    ]
    
    chrome_path = None
    for path in possible_paths:
        if os.path.exists(path):
            chrome_path = path
            break
            
    if not chrome_path:
        print("[Error] 未找到 Chrome 浏览器。请手动启动 Chrome 并开启调试端口。")
        return None
    
    # 使用专用的调试 profile，避免影响用户日常使用的 Chrome
    user_data_dir = os.path.join(os.getcwd(), "chrome_debug_profile")
    if not os.path.exists(user_data_dir):
        os.makedirs(user_data_dir)
    
    cmd = [
        chrome_path,
        "--remote-debugging-port=9222",
        f"--user-data-dir={user_data_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-blink-features=AutomationControlled",  # 减少自动化检测
    ]
    
    try:
        # 使用 shell 的 start 命令完全分离子进程，避免 pipe 警告
        if sys.platform == 'win32':
            # 将命令参数拼接成字符串，使用 start 命令启动
            cmd_str = f'start "" "{chrome_path}" --remote-debugging-port=9222 "--user-data-dir={user_data_dir}" --no-first-run --no-default-browser-check --disable-blink-features=AutomationControlled'
            os.system(cmd_str)
        else:
            subprocess.Popen(cmd, start_new_session=True)
        print(f"[CDP] Chrome 已启动 (端口: 9222)")
        print(f"      Profile 目录: {user_data_dir}")
        time.sleep(3)  # 等待 Chrome 启动
        return "http://127.0.0.1:9222"
    except Exception as e:
        print(f"[Error] 启动 Chrome 失败: {e}")
        return None

def parse_args():
    parser = argparse.ArgumentParser(description="通用页面信息收集工具")
    parser.add_argument("--url", required=True, help="目标页面URL")
    parser.add_argument("--output", default="./page_info_output", help="输出目录 (默认: ./page_info_output)")
    parser.add_argument("--cdp", action="store_true", help="尝试连接本地 Chrome (CDP调试端口 9222)")
    parser.add_argument("--interactive", action="store_true", help="交互模式：等待用户手动操作后再开始收集")
    parser.add_argument("--wait", type=int, default=5, help="加载等待时间(秒)，默认5秒")
    parser.add_argument("--max-events", type=int, default=500, help="最多保存的网络事件条数，默认500")
    parser.add_argument("--max-text-sample", type=int, default=5120, help="文本采样最大长度，默认5120")
    return parser.parse_args()

def safe_filename(name):
    """生成安全的文件名"""
    return "".join([c for c in name if c.isalnum() or c in (' ', '-', '_')]).strip()

def _trim_text(text, max_len):
    if not text:
        return ""
    if len(text) <= max_len:
        return text
    return text[:max_len]

def _is_suspected_list_json(data):
    if isinstance(data, list):
        return len(data) > 0
    if isinstance(data, dict):
        for k in ["list", "data", "records", "rows", "items", "result"]:
            v = data.get(k)
            if isinstance(v, list) and len(v) > 0:
                return True
        for k in ["total", "totalCount", "count"]:
            v = data.get(k)
            if isinstance(v, int) and v >= 0:
                return True
    return False

class PageInfoCollector:
    def __init__(self, output_dir):
        self.output_dir = output_dir
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
            
        self.result = {
            "timestamp": datetime.now().isoformat(),
            "target_url": "",
            "title": "",
            "framework": {},
            "dropdowns": {},
            "iframes": [],
            "dom_structure": {},
            "screenshots": [],
            "apis": {
                "requests": [],
                "responses": [],
                "suspected_list_endpoints": []
            },
            "storage": {
                "cookies_meta": [],
                "local_storage_keys": [],
                "session_storage_keys": []
            }
        }

    async def launch_browser(self, use_cdp=False):
        """启动或连接浏览器"""
        from playwright.async_api import async_playwright
        p = await async_playwright().start()
        
        browser = None
        context = None
        
        if use_cdp:
            print("[Info] 尝试连接本地 Chrome (CDP)...")
            cdp_url = "http://localhost:9222"
            
            # 第一次尝试连接
            try:
                browser = await p.chromium.connect_over_cdp(cdp_url)
            except Exception as e:
                print(f"[Info] 未检测到运行中的 Chrome CDP，尝试自动启动...")
                cdp_url = launch_chrome_for_cdp()
                if not cdp_url:
                    return None, None
                
                # 等待浏览器完全启动后重试连接
                try:
                    browser = await p.chromium.connect_over_cdp(cdp_url)
                except Exception as retry_e:
                    print(f"[Error] 连接 CDP 失败: {retry_e}")
                    return None, None
            
            # CDP 模式下也创建新的 context 以支持 HAR 录制
            har_path = os.path.join(self.output_dir, "network_record.har")
            print(f"[Info] 创建新会话并开启网络录制: {har_path}")
            context = await browser.new_context(
                viewport={"width": 1440, "height": 900},
                locale="zh-CN",
                record_har_path=har_path
            )
            print("[Success] 已连接到本地 Chrome (新会话，支持 HAR 录制)")
        else:
            print("[Info] 启动新浏览器实例...")
            browser = await p.chromium.launch(headless=False)
            
            # 开启 HAR 录制
            har_path = os.path.join(self.output_dir, "network_record.har")
            print(f"[Info] 开启网络录制: {har_path}")
            
            context = await browser.new_context(
                viewport={"width": 1440, "height": 900},
                locale="zh-CN",
                record_har_path=har_path
            )
            
        return browser, context

    async def _attach_network_listeners(self, page, max_events=500, max_text_sample=5120):
        async def on_request(req):
            try:
                payload = {
                    "url": req.url,
                    "method": req.method,
                    "resource_type": req.resource_type,
                    "headers_sample": {k: req.headers.get(k) for k in ["accept", "content-type", "x-requested-with"] if k in req.headers},
                    "post_data_len": (len(req.post_data or "") if hasattr(req, "post_data") else 0),
                }
                self.result["apis"]["requests"].append(payload)
                if len(self.result["apis"]["requests"]) > max_events:
                    self.result["apis"]["requests"] = self.result["apis"]["requests"][-max_events:]
            except Exception:
                pass

        async def on_response(resp):
            try:
                summary = {
                    "url": resp.url,
                    "status": resp.status,
                    "ok": resp.ok,
                    "headers_ct": resp.headers.get("content-type", ""),
                }
                text_sample = ""
                if "application/json" in (summary["headers_ct"] or "").lower():
                    try:
                        data = await resp.json()
                        keys = list(data.keys()) if isinstance(data, dict) else None
                        arr_len = (len(data) if isinstance(data, list) else None)
                        summary["json_keys"] = keys
                        summary["json_array_len"] = arr_len
                        if _is_suspected_list_json(data):
                            self.result["apis"]["suspected_list_endpoints"].append({"url": resp.url, "status": resp.status})
                    except Exception:
                        try:
                            text_sample = await resp.text()
                        except Exception:
                            text_sample = ""
                else:
                    try:
                        text_sample = await resp.text()
                    except Exception:
                        text_sample = ""
                if text_sample:
                    summary["text_sample"] = _trim_text(text_sample, max_text_sample)
                self.result["apis"]["responses"].append(summary)
                if len(self.result["apis"]["responses"]) > max_events:
                    self.result["apis"]["responses"] = self.result["apis"]["responses"][-max_events:]
            except Exception:
                pass

        page.on("request", lambda req: asyncio.create_task(on_request(req)))
        page.on("response", lambda resp: asyncio.create_task(on_response(resp)))

    async def detect_framework(self, page):
        """检测页面使用的前端框架"""
        print("[Task] 检测前端框架...")
        frameworks = {}
        
        # 检查常见的框架特征变量
        checks = {
            "Vue": "!!window.Vue",
            "React": "!!window.React || !!document.querySelector('[data-reactroot]')",
            "Angular": "!!window.angular || !!document.querySelector('[ng-version]')",
            "jQuery": "!!window.jQuery",
            "Bootstrap": "!!window.bootstrap"
        }
        
        for name, script in checks.items():
            try:
                is_present = await page.evaluate(script)
                if is_present:
                    frameworks[name] = True
                    # 尝试获取版本（简单尝试）
                    version = None
                    if name == "Vue":
                        version = await page.evaluate("window.Vue.version")
                    elif name == "jQuery":
                        version = await page.evaluate("window.jQuery.fn.jquery")
                    
                    if version:
                        frameworks[name] = {"version": version}
            except:
                pass
                
        self.result["framework"] = frameworks
        print(f"[Result] 检测到的框架: {json.dumps(frameworks)}")

    async def collect_dropdowns(self, page):
        """收集下拉框及选项映射"""
        print("[Task] 收集下拉框信息...")
        
        # 1. 原生 <select> 元素
        selects = await page.query_selector_all("select")
        print(f"[Info] 发现 {len(selects)} 个原生 <select> 元素")
        
        for idx, select in enumerate(selects):
            try:
                # 获取 name 或 id 作为标识
                name_attr = await select.get_attribute("name") or await select.get_attribute("id") or f"select_{idx}"
                options = await select.query_selector_all("option")
                
                option_map = []
                for opt in options:
                    txt = await opt.inner_text()
                    val = await opt.get_attribute("value")
                    if txt and val:
                        option_map.append({"text": txt.strip(), "value": val.strip()})
                
                if option_map:
                    self.result["dropdowns"][f"NativeSelect::{name_attr}"] = option_map
            except Exception as e:
                print(f"[Error] 处理 Select {idx} 失败: {e}")

        # 2. 常见的自定义下拉框 (Vue/ElementUI/AntDesign等)
        # ElementUI
        try:
            el_selects = await page.query_selector_all(".el-select")
            if el_selects:
                print(f"[Info] 发现 {len(el_selects)} 个 ElementUI 下拉框")
                dropdowns = await page.query_selector_all(".el-select-dropdown .el-select-dropdown__item")
                items = []
                for d in dropdowns:
                    try:
                        txt = (await d.inner_text()).strip()
                        val = await d.get_attribute("value")
                        if txt:
                            items.append({"text": txt, "value": (val or txt)})
                    except Exception:
                        pass
                if items:
                    self.result["dropdowns"]["ElementUI::global"] = items
        except Exception:
            pass

        # AntDesign
        try:
            ant_selects = await page.query_selector_all(".ant-select")
            if ant_selects:
                print(f"[Info] 发现 {len(ant_selects)} 个 AntDesign 下拉框")
                dropdowns = await page.query_selector_all(".ant-select-dropdown .ant-select-item")
                items = []
                for d in dropdowns:
                    try:
                        txt = (await d.inner_text()).strip()
                        val = await d.get_attribute("data-value")
                        if txt:
                            items.append({"text": txt, "value": (val or txt)})
                    except Exception:
                        pass
                if items:
                    self.result["dropdowns"]["AntD::global"] = items
        except Exception:
            pass

    async def collect_iframes(self, page):
        """收集 Iframe 信息"""
        print("[Task] 收集 Iframe 信息...")
        frames = page.frames
        iframe_list = []
        
        for frame in frames:
            if frame == page.main_frame:
                continue
                
            try:
                frame_info = {
                    "name": frame.name,
                    "url": frame.url,
                    "title": await frame.title(),
                    "parent": frame.parent_frame.name if frame.parent_frame else None
                }
                iframe_list.append(frame_info)
                
                # 对 iframe 内容截图
                try:
                    # 找到对应的 frame 元素来截图
                    frame_element = await frame.frame_element()
                    screenshot_name = f"iframe_{safe_filename(frame.name or 'unnamed')}_{int(time.time())}.png"
                    await frame_element.screenshot(path=os.path.join(self.output_dir, screenshot_name))
                    self.result["screenshots"].append(screenshot_name)
                except Exception as e:
                    print(f"Iframe 截图失败: {e}")

            except Exception as e:
                print(f"[Error] 读取 Frame 信息失败: {e}")
        
        self.result["iframes"] = iframe_list
        print(f"[Result] 发现 {len(iframe_list)} 个嵌套 Iframe")

    async def detect_captcha(self, page):
        """
        检测页面是否存在验证码/滑块验证
        返回 True 表示检测到验证码，需要人工介入
        """
        captcha_selectors = [
            # 阿里云盾滑块验证
            ".aliyun-slider",
            "#aliyunCaptcha",
            "[class*='aliyun']",
            "text=访问验证",
            "text=滑动验证",
            "text=请完成安全验证",
            # 腾讯验证码
            "#tcaptcha_iframe",
            ".tcaptcha-popup",
            # 通用滑块
            ".slider-btn",
            ".slide-verify",
            "[class*='captcha']",
            "[class*='slider']",
            # reCAPTCHA
            ".g-recaptcha",
            "iframe[src*='recaptcha']",
        ]
        
        for selector in captcha_selectors:
            try:
                element = await page.query_selector(selector)
                if element:
                    is_visible = await element.is_visible()
                    if is_visible:
                        print(f"[Captcha] 检测到验证码元素: {selector}")
                        return True
            except:
                pass
        
        return False


    async def analyze_dom_structure(self, page):
        """分析关键 DOM 结构"""
        print("[Task] 分析 DOM 结构...")
        
        structure = {}
        
        # 识别搜索区域
        search_candidates = [".search", "#search", "form", "[class*='search']", "[class*='filter']"]
        found_search = []
        for sel in search_candidates:
            elements = await page.query_selector_all(sel)
            if elements:
                found_search.append(f"{sel} ({len(elements)})")
        structure["search_areas"] = found_search
        
        # 识别列表/表格区域
        list_candidates = ["table", ".list", ".grid", "[class*='table']", "[class*='list']"]
        found_list = []
        for sel in list_candidates:
            elements = await page.query_selector_all(sel)
            if elements:
                found_list.append(f"{sel} ({len(elements)})")
        structure["list_areas"] = found_list
        
        self.result["dom_structure"] = structure

    async def collect_storage(self, context, page):
        try:
            cookies = await context.cookies()
            metas = []
            for c in cookies:
                metas.append({
                    "name": c.get("name"),
                    "domain": c.get("domain"),
                    "path": c.get("path"),
                    "secure": c.get("secure"),
                    "httpOnly": c.get("httpOnly"),
                    "sameSite": c.get("sameSite"),
                })
            self.result["storage"]["cookies_meta"] = metas
        except Exception:
            pass
        try:
            ls_keys = await page.evaluate("Object.keys(window.localStorage)")
            ss_keys = await page.evaluate("Object.keys(window.sessionStorage)")
            self.result["storage"]["local_storage_keys"] = ls_keys or []
            self.result["storage"]["session_storage_keys"] = ss_keys or []
        except Exception:
            pass

    async def run(self, args):
        browser, context = await self.launch_browser(use_cdp=args.cdp)
        if not browser:
            return
            
        try:
            # 获取当前页面或新建页面
            if context.pages:
                page = context.pages[0]
            else:
                page = await context.new_page()

            await self._attach_network_listeners(page, max_events=args.max_events, max_text_sample=args.max_text_sample)

            if not args.cdp:
                print(f"[Info] 导航到: {args.url}")
                await page.goto(args.url, wait_until="networkidle", timeout=60000)
            else:
                # CDP 模式下导航到目标 URL
                print(f"[Info] 导航到: {args.url}")
                try:
                    await page.goto(args.url, wait_until="domcontentloaded", timeout=60000)
                except Exception as nav_e:
                    print(f"[Warning] 导航遇到问题: {nav_e}")
                    print("[Info] 页面可能需要手动刷新，继续尝试...")
            
            self.result["target_url"] = page.url
            try:
                self.result["title"] = await page.title()
            except:
                pass

            # 等待加载
            print(f"[Info] 等待 {args.wait} 秒让页面完全渲染...")
            await asyncio.sleep(args.wait)

            # 智能验证码检测
            captcha_detected = await self.detect_captcha(page)
            
            if captcha_detected:
                print("\n" + "="*50)
                print("【检测到验证码】请在浏览器中手动完成验证码：")
                print("完成后，请按 Enter 键继续...")
                print("="*50 + "\n")
                await asyncio.get_event_loop().run_in_executor(None, input)
                # 验证码完成后再检测一次
                captcha_still_exists = await self.detect_captcha(page)
                if captcha_still_exists:
                    print("[Warning] 仍然检测到验证码，继续收集（可能数据不完整）")
            elif args.interactive:
                # 即使没有验证码，如果用户指定了交互模式，也暂停
                print("\n" + "="*50)
                print("【交互模式】页面已加载，未检测到验证码。")
                print("如需手动操作（如展开下拉框），请现在进行。")
                print("完成后，请按 Enter 键继续收集信息...")
                print("="*50 + "\n")
                await asyncio.get_event_loop().run_in_executor(None, input)
            else:
                print("[Info] 未检测到验证码，自动继续...")

            # 开始收集
            await self.detect_framework(page)
            await self.collect_dropdowns(page)
            await self.collect_iframes(page)
            await self.analyze_dom_structure(page)
            await self.collect_storage(context, page)
            
            # 全页截图
            print("[Task] 保存此页面截图...")
            screenshot_path = os.path.join(self.output_dir, "full_page.png")
            try:
                await page.screenshot(path=screenshot_path, full_page=True)
                self.result["screenshots"].insert(0, "full_page.png")
            except Exception as e:
                print(f"[Error] 截图失败: {e}")
                # 尝试非全页截图
                await page.screenshot(path=screenshot_path)

            # 保存结果到 JSON
            json_path = os.path.join(self.output_dir, "page_info.json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(self.result, f, ensure_ascii=False, indent=2)
            blueprint_path = os.path.join(self.output_dir, "site_blueprint.json")
            with open(blueprint_path, "w", encoding="utf-8") as f:
                json.dump({
                    "target_url": self.result["target_url"],
                    "framework": self.result["framework"],
                    "apis": {
                        "suspected_list_endpoints": self.result["apis"]["suspected_list_endpoints"],
                    },
                    "dropdowns": self.result["dropdowns"],
                    "storage": self.result["storage"],
                    "iframes": self.result["iframes"],
                    "dom_structure": self.result["dom_structure"],
                }, f, ensure_ascii=False, indent=2)
            
            # 关闭 context 以触发 HAR 文件写入（必须关闭才能保存 HAR）
            har_path = os.path.join(self.output_dir, "network_record.har")
            print(f"[Info] 保存 HAR 文件...")
            await context.close()
            
            print("\n" + "="*50)
            print(f"[Success] 收集完成！")
            print(f"报告文件: {os.path.abspath(json_path)}")
            print(f"HAR 文件: {os.path.abspath(har_path)}")
            print(f"截图目录: {os.path.abspath(self.output_dir)}")
            print("="*50)

        finally:
            if not args.cdp:
                await browser.close()
            # CDP 模式下不关闭浏览器，让用户可以继续使用（但 context 已关闭）

if __name__ == "__main__":
    import gc
    
    args = parse_args()
    collector = PageInfoCollector(args.output)
    
    try:
        asyncio.run(collector.run(args))
    finally:
        # 在清理阶段抑制 stderr，避免 asyncio 管道错误显示
        _original_stderr = sys.stderr
        try:
            sys.stderr = open(os.devnull, 'w')
        except:
            pass
        
        # 强制垃圾回收，清理所有 asyncio 相关资源
        gc.collect()
        # 给 asyncio 一点时间完成清理
        time.sleep(0.2)
        gc.collect()
