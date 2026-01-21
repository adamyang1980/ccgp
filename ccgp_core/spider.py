import logging
import os
import time
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import requests
from ccgp_core.antibot import ChallengeStateMachine, RunContext, prepare_results_dir
from ccgp_core.fs import sanitize_filename
from ccgp_core.output import ensure_dir, write_json, write_text
from ccgp_core.pipeline import probe_with_http_request
from ccgp_core.request_fingerprint import RandomHeadersGenerator, random_delay, get_random_delay_value

logger = logging.getLogger(__name__)

class BaseSpider(ABC):
    """
    通用爬虫基类，实现了统一的采集流程。
    """

    def __init__(self, site_name: str, config: Dict[str, Any]):
        self.site_name = site_name
        self.config = config
        
        # 1a. 统一输入参数
        self.start_date = config.get("start_date")
        self.end_date = config.get("end_date")
        self.region = config.get("region")
        self.keywords = config.get("keywords") or []
        self.max_pages = config.get("max_pages", 100)
        self.max_results = config.get("max_results", 1000)
        
        # 1h. 江苏特有参数 (keywords 复用)
        self.secondary_filter = config.get("secondary_filter", False)
        
        self.resume = config.get("resume", False)
        self.interactive = config.get("interactive", True)
        self.verbose = config.get("verbose", True)
        
        # 反反爬虫配置
        self.request_delay_range = config.get("request_delay_range", (1.0, 3.0))
        self.headers_generator = RandomHeadersGenerator()
        
        # 初始化上下文
        self.out_dir = prepare_results_dir(site_name, resume=self.resume)
        self.ctx = RunContext(site=site_name, out_dir=self.out_dir, interactive=self.interactive)
        if self.resume:
            self.ctx.load_checkpoint()
        self.sm = ChallengeStateMachine(self.ctx)
        
        self.session = requests.Session()
        self.configure_session()

        # 1. Date parsing (Unified)
        self.start_ts = self._parse_date_to_ts(self.start_date, end_of_day=False)
        self.end_ts = self._parse_date_to_ts(self.end_date, end_of_day=True)

        # 1g. 统一日志输出 (这里简单 print, 实际可以使用 logging)
        if self.verbose:
            self.log_info(f"启动爬虫: {site_name}")
            self.log_info(f"配置: {config}")

    def log_info(self, msg: str):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] [INFO] {msg}")

    def log_error(self, msg: str):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] [ERROR] {msg}")

    def configure_session(self):
        # 使用随机化请求头
        self.headers_generator.update_session_headers(self.session, rotate_ua=False)

    def run(self) -> bool:
        """
        主流程
        """
        try:
            # 1b. 统一试探流程
            if not self.probe_phase():
                self.log_error("Probe phase failed. Aborting.")
                return False

            # 1e. 搜索爬取
            success = self.search_phase()
            
            self.sm.passed(kind="none", message="done")
            return success
        except Exception as e:
            self.log_error(f"Critical error during run: {e}")
            import traceback
            traceback.print_exc()
            return False

    def probe_phase(self) -> bool:
        """
        试探阶段：检测验证码/滑块
        """
        self.log_info("开始试探阶段...")
        
        for attempt in range(2):
            result = self.perform_probe()
            if result == "ok":
                return True
            
            self.log_info(f"检测到访问限制: {result}")
            
            # 1c, 1d. 处理验证
            if not self.handle_verification(result):
                if not self.interactive:
                    return False
                # 人工介入
                self.sm.manual_required(
                    kind=result,
                    url=self.get_landing_url(),
                    message=f"需人工验证 ({result})",
                    wait_seconds=60
                )
                if not self.ctx.wait_for_manual():
                    return False
        return False

    def handle_verification(self, kind: str) -> bool:
        """
        自动处理验证码/滑块
        """
        if kind == "captcha":
            # 1c. OCR 识别流程
            self.log_info("尝试 OCR 识别...")
            return self.solve_captcha_ocr()
        elif kind == "slider":
            # 1d. CDP 模式自动破解
            self.log_info("尝试 CDP 滑块破解...")
            return self.solve_slider_cdp()
        return False

    def solve_captcha_ocr(self) -> bool:
        """
        Default OCR solving flow:
        1. Fetch captcha image from self.get_captcha_url().
        2. Use OCRService to recognize.
        3. Store result in self.current_captcha.
        """
        url = self.get_captcha_url()
        if not url:
            self.log_error("Captcha URL not defined.")
            return False

        try:
            from ccgp_core.ocr_service import OCRService
            service = OCRService.get_instance()
            
            # Fetch image
            resp = self.session.get(url, timeout=10)
            if resp.status_code != 200:
                self.log_error(f"Failed to fetch captcha: {resp.status_code}")
                return False
            
            # Recognize
            text, score = service.recognize_captcha(resp.content)
            if text and score >= 0.4: # Default threshold
                self.current_captcha = text
                self.log_info(f"OCR Recognized: {text} (Score: {score:.2f})")
                return True
            else:
                self.log_error(f"OCR failed or low confidence: {text} ({score:.2f})")
                return False
        except Exception as e:
            self.log_error(f"solve_captcha_ocr error: {e}")
            return False

    def get_captcha_url(self) -> Optional[str]:
        """
        Return the URL to fetch captcha image. Subclasses can override or set self.captcha_url.
        """
        return getattr(self, "captcha_url", None)


    def solve_slider_cdp(self) -> bool:
        # TODO: 集成 CDP 滑块破解
        self.log_info("CDP 滑块破解尚未集成, 跳过")
        return False

    def perform_probe(self) -> str:
        """
        执行具体的试探请求
        返回: 'ok', 'captcha', 'slider', 'other'
        """
        # 默认实现，子类可覆盖
        try:
            return self._do_probe_request()
        except Exception as e:
            self.log_error(f"Probe request error: {e}")
            return "network_error"

    @abstractmethod
    def _do_probe_request(self) -> str:
        pass

    @abstractmethod
    def get_landing_url(self) -> str:
        pass

    def search_phase(self) -> bool:
        """
        1e. 搜索爬取阶段
        """
        collected = []
        
        # 1f. 恢复逻辑
        summary_path = os.path.join(self.out_dir, "search_results.json")
        if self.resume and os.path.exists(summary_path):
            try:
                with open(summary_path, "r", encoding="utf-8") as f:
                    import json
                    collected = json.load(f)
                self.log_info(f"已恢复 {len(collected)} 条记录")
            except Exception:
                pass
        
        page_no = 1
        if self.resume and self.ctx.checkpoint.get("page_no"):
            page_no = int(self.ctx.checkpoint.get("page_no"))

        while len(collected) < self.max_results and page_no <= self.max_pages:
            self.log_info(f"正在抓取第 {page_no} 页...")
            
            try:
                items = self.fetch_page_items(page_no)
            except Exception as e:
                self.log_error(f"Fetch page {page_no} failed: {e}")
                # 再次试探
                if not self.probe_phase():
                    return False
                continue

            if not items:
                self.log_info("没有更多数据，停止翻页")
                break

            valid_items = []
            for item in items:
                # 1a. 日期/关键词过滤
                if self.filter_item(item):
                    valid_items.append(item)
            
            collected.extend(valid_items)
            self.log_info(f"第 {page_no} 页获取 {len(valid_items)} 条有效数据 (总计: {len(collected)})")
            
            page_no += 1
            self.ctx.set_checkpoint(page_no=page_no, collected_count=len(collected))
            self.ctx.save_checkpoint()
            
            # 保存中间结果
            write_json(summary_path, collected)
            
            # 反反爬虫: 随机延迟
            if page_no <= self.max_pages and len(collected) < self.max_results:
                delay = random_delay(self.request_delay_range[0], self.request_delay_range[1])
                if self.verbose:
                    self.log_info(f"等待 {delay:.1f} 秒...")

        # 详情页抓取
        self.process_details(collected)
        return True



    def _parse_date_to_ts(self, date_str: Optional[str], end_of_day: bool = False) -> Optional[int]:
        if not date_str: return None
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            if end_of_day:
                dt = dt.replace(hour=23, minute=59, second=59, microsecond=999999)
            else:
                 dt = dt.replace(hour=0, minute=0, second=0, microsecond=0)
            return int(dt.timestamp() * 1000)
        except Exception:
            self.log_error(f"Failed to parse date: {date_str}")
            return None

    def filter_item(self, item: Dict[str, Any]) -> bool:
        """
        基础过滤: 日期范围 + 关键词
        """
        # 1h. 二次过滤参数 (默认不开启)
        if self.secondary_filter and self.keywords:
             title = item.get("title", "")
             # 简单的关键词检查 (ANY match)
             if not any(k in title for k in self.keywords):
                 return False

        # 日期过滤
        item_ts = self.extract_item_timestamp(item)
        if item_ts is not None:
             if self.start_ts is not None and item_ts < self.start_ts:
                 return False
             if self.end_ts is not None and item_ts > self.end_ts:
                 return False
        
        return True

    @abstractmethod
    def fetch_page_items(self, page_no: int) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    def extract_item_timestamp(self, item: Dict[str, Any]) -> Optional[int]:
        pass

    def process_details(self, collected: List[Dict[str, Any]]):
        """
        处理详情页
        """
        details_dir = os.path.join(self.out_dir, "details")
        ensure_dir(details_dir)
        
        done_ids = set()
        if self.ctx.checkpoint.get("detail_done_ids"):
             done_ids = set(self.ctx.checkpoint.get("detail_done_ids"))

        for idx, item in enumerate(collected):
            item_id = self.extract_item_id(item)
            if not item_id or str(item_id) in done_ids:
                continue

            self.log_info(f"正在抓取详情: {item_id} ({idx + 1}/{len(collected)})")
            
            try:
                detail_data = self.fetch_detail(item_id)
                self.save_detail(item, detail_data, details_dir)
                done_ids.add(str(item_id))
                self.ctx.set_checkpoint(detail_done_ids=list(done_ids))
                self.ctx.save_checkpoint()
            except Exception as e:
                self.log_error(f"Failed to fetch detail {item_id}: {e}")
                # 重新试探
                if self.probe_phase():
                    # 重试一次
                    try:
                        detail_data = self.fetch_detail(item_id)
                        self.save_detail(item, detail_data, details_dir)
                        done_ids.add(str(item_id))
                    except Exception:
                        pass

    @abstractmethod
    def extract_item_id(self, item: Dict[str, Any]) -> str:
        pass

    @abstractmethod
    def fetch_detail(self, item_id: str) -> Dict[str, Any]:
        pass

    @abstractmethod
    def save_detail(self, item: Dict[str, Any], detail: Dict[str, Any], base_dir: str):
        pass
