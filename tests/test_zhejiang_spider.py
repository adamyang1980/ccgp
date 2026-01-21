import ccgp_core.spider as spider_mod
import ccgp_sites.zhejiang.impl as zhejiang


class DummyResponse:
    def __init__(self, status_code=200, content=b"", headers=None):
        self.status_code = status_code
        self._content = content
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("http error")

    def iter_content(self, chunk_size=8192):
        yield self._content

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _make_spider(tmp_path, monkeypatch):
    monkeypatch.setattr(
        spider_mod,
        "prepare_results_dir",
        lambda site, resume=False: str(tmp_path),
    )
    return zhejiang.ZhejiangCCGPSearch({"verbose": False, "interactive": False})


def test_extract_list_items_from_known_shape(tmp_path, monkeypatch):
    spider = _make_spider(tmp_path, monkeypatch)
    payload = {"success": True, "result": {"data": {"data": [{"id": 1}]}}}
    assert spider._extract_list_items(payload) == [{"id": 1}]


def test_extract_list_items_fallback(tmp_path, monkeypatch):
    spider = _make_spider(tmp_path, monkeypatch)
    payload = {"data": [{"id": "x"}]}
    assert spider._extract_list_items(payload) == [{"id": "x"}]


def test_extract_content_html(tmp_path, monkeypatch):
    spider = _make_spider(tmp_path, monkeypatch)
    detail = {"result": {"data": {"content": "<p>ok</p>"}}}
    assert spider._extract_content_html(detail) == "<p>ok</p>"
    assert spider._extract_content_html({}) is None


def test_extract_attachment_urls(tmp_path, monkeypatch):
    spider = _make_spider(tmp_path, monkeypatch)
    html = (
        '<a href="/files/a.pdf">a</a>'
        '<a href="/files/a.pdf#hash">dup</a>'
        '<a href="javascript:void(0)">skip</a>'
        '<img src="/files/b.JPG" />'
        '<a href="/files/c.txt">skip</a>'
        '<a href="/files/d.docx">doc</a>'
    )
    urls = spider._extract_attachment_urls(html)
    # Only document extensions are extracted: pdf, doc, docx, xls, xlsx, zip, rar
    assert any(u.endswith("/files/a.pdf") for u in urls)
    assert any("d.docx" in u for u in urls)
    # Image files and txt files should NOT be extracted
    assert all("b.JPG" not in u for u in urls)
    assert all("c.txt" not in u for u in urls)
    # Should have 2 unique urls: a.pdf and d.docx (duplicate a.pdf#hash is filtered)
    assert len(urls) == 2


def test_download_file_writes_content(tmp_path, monkeypatch):
    spider = _make_spider(tmp_path, monkeypatch)
    content = b"data"

    def fake_get(url, stream=True, timeout=60):
        return DummyResponse(status_code=200, content=content)

    spider.session.get = fake_get
    dest = tmp_path / "out" / "file.bin"
    ok = spider._download_file("http://example/file.bin", str(dest))
    assert ok is True
    assert dest.exists()
    assert dest.read_bytes() == content
