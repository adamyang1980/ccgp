import asyncio
import base64

import ccgp_core.spider as spider_mod
import ccgp_sites.xinjiang.impl as xinjiang


class DummyResponse:
    def __init__(self, json_data=None, status_code=200, text="", headers=None):
        self._json = json_data or {}
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}

    def json(self):
        return self._json


def _make_spider(tmp_path, monkeypatch, **config):
    monkeypatch.setattr(
        spider_mod,
        "prepare_results_dir",
        lambda site, resume=False: str(tmp_path),
    )
    cfg = {"verbose": False, "interactive": False}
    cfg.update(config)
    return xinjiang.XinjiangCCGPSearch(cfg)


def test_build_search_payload_includes_filters(tmp_path, monkeypatch):
    spider = _make_spider(
        tmp_path,
        monkeypatch,
        start_date="2024-01-01",
        end_date="2024-01-31",
        region="650100",
        keywords=["abc"],
    )
    payload = spider._build_search_payload(2)
    assert payload["pageNo"] == 2
    assert payload["pageSize"] == 15
    assert payload["keyword"] == "abc"
    assert payload["districtCode"] == ["650100"]
    assert payload["publishDateBegin"] == "2024-01-01"
    assert payload["publishDateEnd"] == "2024-01-31"


def test_do_probe_request_ok(tmp_path, monkeypatch):
    spider = _make_spider(tmp_path, monkeypatch)
    spider._http_warmed = True

    def fake_post(url, json=None, timeout=None):
        return DummyResponse(
            json_data={"result": {}},
            status_code=200,
            headers={"content-type": "application/json"},
        )

    spider.session.post = fake_post
    assert spider._do_probe_request() == "ok"


def test_do_probe_request_slider_on_non_json(tmp_path, monkeypatch):
    spider = _make_spider(tmp_path, monkeypatch)
    spider._http_warmed = True

    def fake_post(url, json=None, timeout=None):
        return DummyResponse(
            json_data={},
            status_code=405,
            text="aliyun_waf",
            headers={"content-type": "text/html"},
        )

    spider.session.post = fake_post
    assert spider._do_probe_request() == "slider"


def test_capture_captcha_images_decodes(tmp_path, monkeypatch):
    spider = _make_spider(tmp_path, monkeypatch)
    payload = base64.b64encode(b"img").decode("ascii")

    class FakeFrame:
        async def evaluate(self, js):
            return {
                "bg": f"data:image/png;base64,{payload}",
                "shadow": f"data:image/png;base64,{payload}",
            }

    shadow, bg = asyncio.run(spider._capture_captcha_images(FakeFrame()))
    assert shadow == b"img"
    assert bg == b"img"


def test_detect_gap_distance_handles_missing_inputs(tmp_path, monkeypatch):
    spider = _make_spider(tmp_path, monkeypatch)
    assert spider._detect_gap_distance(None, None) is None


def test_detect_gap_distance_returns_int(tmp_path, monkeypatch):
    spider = _make_spider(tmp_path, monkeypatch)
    bg = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x00\x00\x00\x00\x3a\x7e\x9b\x55\x00\x00\x00\nIDATx\x9cc`\x00\x00\x00\x02\x00\x01\xe2!\xbc3\x00\x00\x00\x00IEND\xaeB`\x82"
    shadow = bg
    result = spider._detect_gap_distance(shadow, bg)
    assert isinstance(result, (int, type(None)))


def test_generate_human_track_shape(tmp_path, monkeypatch):
    spider = _make_spider(tmp_path, monkeypatch)
    track = spider._generate_human_track(10, duration=0.1)
    assert track
    assert all("x" in p and "y" in p for p in track)


def test_handle_slider_captcha_no_slider(tmp_path, monkeypatch):
    spider = _make_spider(tmp_path, monkeypatch)

    class FakePage:
        async def is_visible(self, sel):
            return False

    found, passed = asyncio.run(spider._handle_slider_captcha(FakePage()))
    assert found is False
    assert passed is True


def test_extract_item_id_fallback(tmp_path, monkeypatch):
    spider = _make_spider(tmp_path, monkeypatch)
    assert spider.extract_item_id({"articleId": 123}) == "123"
    assert spider.extract_item_id({"id": "x"}) == "x"
    assert spider.extract_item_id({}) == ""
