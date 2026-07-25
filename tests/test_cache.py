"""Tests for ccgp_core.cache module."""

import pytest

from ccgp_core.cache import FileCache


@pytest.fixture
def cache(tmp_path):
    pages_dir = str(tmp_path / "pages")
    attachments_dir = str(tmp_path / "attachments")
    c = FileCache(pages_dir, attachments_dir)
    c.ensure_dirs()
    return c


@pytest.fixture
def cache_no_attachments(tmp_path):
    pages_dir = str(tmp_path / "pages_only")
    return FileCache(pages_dir)


class TestFileCachePages:
    def test_ensure_dirs_creates_directories(self, tmp_path):
        pages_dir = str(tmp_path / "new_pages")
        attachments_dir = str(tmp_path / "new_attachments")
        c = FileCache(pages_dir, attachments_dir)
        c.ensure_dirs()
        assert (tmp_path / "new_pages").exists()
        assert (tmp_path / "new_attachments").exists()

    def test_page_path(self, cache):
        path = cache.page_path("123", "index.html")
        assert "123" in path
        assert "index.html" in path

    def test_is_page_cached_false_initially(self, cache):
        assert cache.is_page_cached("123", "index.html") is False

    def test_save_and_get_page_text(self, cache):
        cache.save_page_text("123", "index.html", "<html>test</html>")
        assert cache.is_page_cached("123", "index.html") is True
        content = cache.get_page_text("123", "index.html")
        assert content == "<html>test</html>"

    def test_get_page_text_nonexistent_returns_none(self, cache):
        assert cache.get_page_text("999", "nope.html") is None


class TestFileCacheAttachments:
    def test_attachment_path(self, cache):
        path = cache.attachment_path("123", "file.pdf")
        assert "123" in path
        assert "file.pdf" in path

    def test_is_attachment_cached_false_initially(self, cache):
        assert cache.is_attachment_cached("123", "file.pdf") is False

    def test_save_and_get_attachment_bytes(self, cache):
        data = b"\x00\x01\x02binary"
        cache.save_attachment_bytes("123", "file.pdf", data)
        assert cache.is_attachment_cached("123", "file.pdf") is True
        result = cache.get_attachment_bytes("123", "file.pdf")
        assert result == data

    def test_get_attachment_bytes_nonexistent_returns_none(self, cache):
        assert cache.get_attachment_bytes("999", "nope.pdf") is None

    def test_get_attachment_path_if_exists(self, cache):
        assert cache.get_attachment_path_if_exists("123", "file.pdf") is None
        cache.save_attachment_bytes("123", "file.pdf", b"data")
        path = cache.get_attachment_path_if_exists("123", "file.pdf")
        assert path is not None


class TestFileCacheNoAttachments:
    def test_attachment_path_raises_without_config(self, cache_no_attachments):
        with pytest.raises(RuntimeError):
            cache_no_attachments.attachment_path("123", "file.pdf")

    def test_is_attachment_cached_false_without_config(self, cache_no_attachments):
        assert cache_no_attachments.is_attachment_cached("123", "file.pdf") is False

    def test_get_attachment_bytes_none_without_config(self, cache_no_attachments):
        assert cache_no_attachments.get_attachment_bytes("123", "file.pdf") is None

    def test_save_attachment_raises_without_config(self, cache_no_attachments):
        with pytest.raises(RuntimeError):
            cache_no_attachments.save_attachment_bytes("123", "f.pdf", b"x")
