import json
from datetime import datetime

import ccgp_core.spider as spider_mod


class DummySpider(spider_mod.BaseSpider):
    def __init__(self, config, pages=None, probe_sequence=None, fail_first=False):
        self._pages = pages or []
        self._probe_iter = iter(probe_sequence or ["ok"])
        self._fail_first = fail_first
        self._detail_calls = {}
        self.saved = []
        super().__init__("dummy", config)

    def _do_probe_request(self) -> str:
        return next(self._probe_iter)

    def get_landing_url(self) -> str:
        return "http://example.com"

    def fetch_page_items(self, page_no: int):
        idx = page_no - 1
        if 0 <= idx < len(self._pages):
            return self._pages[idx]
        return []

    def extract_item_timestamp(self, item):
        return item.get("ts")

    def extract_item_id(self, item):
        return str(item.get("id", ""))

    def fetch_detail(self, item_id: str):
        self._detail_calls[item_id] = self._detail_calls.get(item_id, 0) + 1
        if self._fail_first and self._detail_calls[item_id] == 1:
            raise RuntimeError("boom")
        return {"id": item_id}

    def save_detail(self, item, detail, base_dir: str):
        self.saved.append((item, detail, base_dir))


def _make_spider(
    tmp_path,
    monkeypatch,
    pages=None,
    probe_sequence=None,
    fail_first=False,
    **config,
):
    monkeypatch.setattr(
        spider_mod,
        "prepare_results_dir",
        lambda site, resume=False: str(tmp_path),
    )
    cfg = {"verbose": False, "interactive": False}
    cfg.update(config)
    return DummySpider(
        cfg,
        pages=pages,
        probe_sequence=probe_sequence,
        fail_first=fail_first,
    )


def test_parse_date_to_ts_valid_and_invalid(tmp_path, monkeypatch):
    spider = _make_spider(tmp_path, monkeypatch)
    date_str = "2024-01-02"
    expected_start = int(datetime.strptime(date_str, "%Y-%m-%d").timestamp() * 1000)
    expected_end = int(
        datetime.strptime(date_str, "%Y-%m-%d")
        .replace(hour=23, minute=59, second=59, microsecond=999999)
        .timestamp()
        * 1000
    )

    assert spider._parse_date_to_ts(date_str, end_of_day=False) == expected_start
    assert spider._parse_date_to_ts(date_str, end_of_day=True) == expected_end
    assert spider._parse_date_to_ts("bad-date", end_of_day=False) is None


def test_filter_item_secondary_and_date_range(tmp_path, monkeypatch):
    spider = _make_spider(
        tmp_path,
        monkeypatch,
        start_date="2024-01-01",
        end_date="2024-01-31",
        keywords=["alpha"],
        secondary_filter=True,
    )
    in_range_ts = int(datetime(2024, 1, 10).timestamp() * 1000)
    out_of_range_ts = int(datetime(2023, 12, 31).timestamp() * 1000)

    assert spider.filter_item({"title": "alpha ok", "ts": in_range_ts}) is True
    assert spider.filter_item({"title": "beta", "ts": in_range_ts}) is False
    assert spider.filter_item({"title": "alpha ok", "ts": out_of_range_ts}) is False


def test_probe_phase_noninteractive_returns_false(tmp_path, monkeypatch):
    spider = _make_spider(
        tmp_path,
        monkeypatch,
        interactive=False,
    )
    spider._probe_iter = iter(["captcha"])
    monkeypatch.setattr(spider, "handle_verification", lambda kind: False)
    assert spider.probe_phase() is False


def test_search_phase_collects_and_persists_results(tmp_path, monkeypatch):
    pages = [
        [{"id": "1", "ts": 10, "title": "one"}, {"id": "2", "ts": 20, "title": "two"}],
        [],
    ]
    spider = _make_spider(
        tmp_path,
        monkeypatch,
        max_pages=2,
        max_results=10,
    )
    spider._pages = pages
    captured = {}

    def fake_process(items):
        captured["items"] = items

    spider.process_details = fake_process
    assert spider.search_phase() is True
    assert len(captured["items"]) == 2

    summary_path = tmp_path / "search_results.json"
    assert summary_path.exists()
    with summary_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    assert len(data) == 2


def test_process_details_skips_done_and_retries(tmp_path, monkeypatch):
    spider = _make_spider(tmp_path, monkeypatch, fail_first=True)
    spider.ctx.set_checkpoint(detail_done_ids=["skip"])

    items = [
        {"id": "skip", "title": "skip"},
        {"id": "retry", "title": "retry"},
    ]

    monkeypatch.setattr(spider, "probe_phase", lambda: True)
    spider.process_details(items)

    assert spider._detail_calls["retry"] == 2
    assert len(spider.saved) == 1
