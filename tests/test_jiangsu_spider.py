from io import BytesIO

import pytest
from PIL import Image
import os
import sys

# Add project root to path
sys.path.append(os.getcwd())

import requests

import ccgp_core.spider as spider_mod
import ccgp_sites.jiangsu.impl as jiangsu
from unittest.mock import MagicMock


class DummyResponse:
    def __init__(self, json_data=None, status_code=200, text="", content=b"", headers=None):
        self._json = json_data or {}
        self.status_code = status_code
        self.text = text
        self.content = content
        self.headers = headers or {}

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP error {self.status_code}")


def _make_spider(tmp_path, monkeypatch):
    monkeypatch.setattr(
        spider_mod,
        "prepare_results_dir",
        lambda site, resume=False: str(tmp_path),
    )
    # _init_ocr removed from class, so don't patch it.
    # Instead mock OCRService.get_instance
    mock_ocr_service = MagicMock()
    # Ensure it returns a dummy object with recognize_captcha
    mock_ocr_service.recognize_captcha.return_value = (None, 0.0)
    
    monkeypatch.setattr("ccgp_sites.jiangsu.impl.OCRService.get_instance", lambda: mock_ocr_service)

    monkeypatch.setattr(jiangsu.JiangsuCCGPSearch, "_init_cache_dirs", lambda self: None)
    monkeypatch.setattr(
        requests.Session,
        "get",
        lambda self, *args, **kwargs: DummyResponse(),
    )
    monkeypatch.setattr(
        requests.Session,
        "post",
        lambda self, *args, **kwargs: DummyResponse(),
    )
    spider = jiangsu.JiangsuCCGPSearch({"verbose": False, "interactive": False})
    spider.ocr_service = mock_ocr_service # Ensure we have ref
    return spider


def _image_bytes():
    img = Image.new("RGB", (2, 2), color=(255, 255, 255))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_parse_date_ms_defaults(tmp_path, monkeypatch):
    spider = _make_spider(tmp_path, monkeypatch)
    monkeypatch.setattr(jiangsu.time, "time", lambda: 1234.0)
    assert spider._parse_date_ms(None, False) == 0
    assert spider._parse_date_ms(None, True) == 1234000



def test_preprocess_captcha(tmp_path, monkeypatch):
    # Only test default preprocess (BaseSpider does not have specific captcha preprocess exposed as public api unless custom)
    # The helper `preprocess_captcha_for_local_ocr` was removed.
    pass

def test_recognize_captcha_local_delegates_to_service(tmp_path, monkeypatch):
    spider = _make_spider(tmp_path, monkeypatch)
    
    # Mock ocr_service
    mock_service = spider.ocr_service = DummyResponse(json_data={}) # Just an object
    # Mock recognize_captcha method on instance
    spider.ocr_service.recognize_captcha = lambda x: ("MOCK", 0.99)

    code, score = spider.recognize_captcha_local(_image_bytes())
    assert code == "MOCK"
    assert score == 0.99
    



def test_recognize_captcha_api_success(tmp_path, monkeypatch):
    spider = _make_spider(tmp_path, monkeypatch)
    monkeypatch.setattr(jiangsu, "OCR_API_URL", "http://example")
    monkeypatch.setattr(jiangsu, "OCR_API_TOKEN", "token")

    def fake_post(url, json=None, headers=None, timeout=None):
        return DummyResponse(
            json_data={
                "result": {
                    "ocrResults": [
                        {"prunedResult": {"rec_texts": ["a", "b"], "rec_scores": [0.5, 1.0]}}
                    ]
                }
            }
        )

    monkeypatch.setattr(jiangsu.requests, "post", fake_post)
    code, score = spider.recognize_captcha_api(b"img")
    assert code == "AB"
    assert score == pytest.approx(0.75, rel=1e-3)


def test_get_captcha_retries_until_confident(tmp_path, monkeypatch):
    spider = _make_spider(tmp_path, monkeypatch)
    calls = {"count": 0}

    def fake_get(*args, **kwargs):
        calls["count"] += 1
        return DummyResponse(status_code=200, content=b"img")

    results = [(None, 0.1), ("OK", 0.9)]

    def fake_recognize(image_bytes):
        return results.pop(0)

    spider.session.get = fake_get
    monkeypatch.setattr(spider, "recognize_captcha", fake_recognize)
    monkeypatch.setattr(jiangsu.time, "sleep", lambda _: None)
    code = spider.get_captcha(max_retries=3)
    assert code == "OK"
    assert calls["count"] == 2


def test_fetch_page_items_adds_detail_url(tmp_path, monkeypatch):
    spider = _make_spider(tmp_path, monkeypatch)
    spider.current_captcha = "CODE"

    def fake_get(url, params=None, timeout=None):
        return DummyResponse(
            json_data={
                "code": 200,
                "result": {"list": [{"id": 1, "ggCode": "A1"}]},
            }
        )

    spider.session.get = fake_get
    items = spider.fetch_page_items(1)
    assert items[0]["detail_url"].endswith("gglb=A1&ggid=1")


def test_fetch_page_items_clears_captcha_on_error(tmp_path, monkeypatch):
    spider = _make_spider(tmp_path, monkeypatch)
    spider.current_captcha = "CODE"

    def fake_get(url, params=None, timeout=None):
        return DummyResponse(
            json_data={"code": 500, "message": "\u9a8c\u8bc1\u7801\u9519\u8bef"},
        )

    spider.session.get = fake_get
    with pytest.raises(Exception):
        spider.fetch_page_items(1)
    assert spider.current_captcha is None
