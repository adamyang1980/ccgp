"""
请求指纹随机化模块
提供 User-Agent 轮换、请求头随机化、随机延迟等反反爬虫工具
"""

import random
import time
from typing import Dict, List, Optional, Tuple

# 常见桌面浏览器 User-Agent 列表 (2024-2026 版本)
USER_AGENTS: List[str] = [
    # Chrome (Windows)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    # Chrome (Mac)
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    # Edge (Windows)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Edg/121.0.0.0",
    # Firefox (Windows)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
    # Firefox (Mac)
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0",
]

ACCEPT_LANGUAGES: List[str] = [
    "zh-CN,zh;q=0.9,en;q=0.8",
    "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "zh-CN,zh;q=0.8,zh-TW;q=0.7,en;q=0.6",
    "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
]

ACCEPT_ENCODINGS: List[str] = [
    "gzip, deflate, br",
    "gzip, deflate",
    "gzip, deflate, br, zstd",
]


class RandomUserAgentPool:
    """User-Agent 轮换池"""
    
    def __init__(self, user_agents: Optional[List[str]] = None):
        self.user_agents = user_agents or USER_AGENTS
        self._last_ua: Optional[str] = None
    
    def get(self) -> str:
        """获取一个随机 User-Agent (避免连续相同)"""
        if len(self.user_agents) == 1:
            return self.user_agents[0]
        
        available = [ua for ua in self.user_agents if ua != self._last_ua]
        chosen = random.choice(available)
        self._last_ua = chosen
        return chosen
    
    def get_consistent(self) -> str:
        """获取一个一致的 User-Agent (整个会话使用同一个)"""
        if self._last_ua is None:
            self._last_ua = random.choice(self.user_agents)
        return self._last_ua


class RandomHeadersGenerator:
    """随机请求头生成器"""
    
    def __init__(self, ua_pool: Optional[RandomUserAgentPool] = None):
        self.ua_pool = ua_pool or RandomUserAgentPool()
    
    def generate(self, rotate_ua: bool = False) -> Dict[str, str]:
        """
        生成随机化的请求头
        
        Args:
            rotate_ua: 是否每次轮换 User-Agent (False 则保持一致)
        """
        ua = self.ua_pool.get() if rotate_ua else self.ua_pool.get_consistent()
        
        headers = {
            "User-Agent": ua,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": random.choice(ACCEPT_LANGUAGES),
            "Accept-Encoding": random.choice(ACCEPT_ENCODINGS),
            "Connection": "keep-alive",
            "Cache-Control": random.choice(["no-cache", "max-age=0"]),
        }
        
        # 随机添加一些可选头部
        if random.random() < 0.7:
            headers["Pragma"] = "no-cache"
        
        if random.random() < 0.5:
            headers["Upgrade-Insecure-Requests"] = "1"
        
        return headers
    
    def update_session_headers(self, session, rotate_ua: bool = False):
        """直接更新 requests.Session 的头部"""
        new_headers = self.generate(rotate_ua=rotate_ua)
        session.headers.update(new_headers)


def random_delay(min_seconds: float = 1.0, max_seconds: float = 3.0) -> float:
    """
    执行随机延迟
    
    Args:
        min_seconds: 最小延迟秒数
        max_seconds: 最大延迟秒数
    
    Returns:
        实际延迟的秒数
    """
    delay = random.uniform(min_seconds, max_seconds)
    time.sleep(delay)
    return delay


def get_random_delay_value(min_seconds: float = 1.0, max_seconds: float = 3.0) -> float:
    """获取随机延迟值 (不执行 sleep)"""
    return random.uniform(min_seconds, max_seconds)


# 全局默认实例
_default_ua_pool: Optional[RandomUserAgentPool] = None
_default_headers_gen: Optional[RandomHeadersGenerator] = None


def get_default_ua_pool() -> RandomUserAgentPool:
    """获取默认 UA 池"""
    global _default_ua_pool
    if _default_ua_pool is None:
        _default_ua_pool = RandomUserAgentPool()
    return _default_ua_pool


def get_default_headers_generator() -> RandomHeadersGenerator:
    """获取默认请求头生成器"""
    global _default_headers_gen
    if _default_headers_gen is None:
        _default_headers_gen = RandomHeadersGenerator()
    return _default_headers_gen
