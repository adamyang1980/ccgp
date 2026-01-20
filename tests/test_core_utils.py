import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout

from ccgp_core.cache import FileCache
from ccgp_core.fs import sanitize_filename
from ccgp_core.output import build_output_dir, write_json, write_text
from ccgp_core.runtime import exit_code, print_final_message


class TestCoreUtils(unittest.TestCase):
    def test_sanitize_filename_removes_unsafe_chars_and_truncates(self):
        raw = 'a<b>c:d"e/f\\g|h?i*j'
        safe = sanitize_filename(raw, max_length=10)
        self.assertNotIn("<", safe)
        self.assertNotIn(">", safe)
        self.assertNotIn(":", safe)
        self.assertNotIn('"', safe)
        self.assertNotIn("/", safe)
        self.assertNotIn("\\", safe)
        self.assertNotIn("|", safe)
        self.assertNotIn("?", safe)
        self.assertNotIn("*", safe)
        self.assertLessEqual(len(safe), 10)

    def test_filecache_page_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            pages_dir = os.path.join(tmp, "pages")
            cache = FileCache(pages_dir=pages_dir)
            cache.ensure_dirs()

            page_id = "123"
            filename = "index.html"
            content = "<html>ok</html>"

            self.assertFalse(cache.is_page_cached(page_id, filename))
            cache.save_page_text(page_id, filename, content)
            self.assertTrue(cache.is_page_cached(page_id, filename))
            self.assertEqual(cache.get_page_text(page_id, filename), content)

    def test_filecache_attachment_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = FileCache(
                pages_dir=os.path.join(tmp, "pages"),
                attachments_dir=os.path.join(tmp, "attachments"),
            )
            cache.ensure_dirs()

            page_id = "ggid"
            filename = "a.bin"
            payload = b"\x00\x01\x02"

            self.assertFalse(cache.is_attachment_cached(page_id, filename))
            cache.save_attachment_bytes(page_id, filename, payload)
            self.assertTrue(cache.is_attachment_cached(page_id, filename))
            self.assertEqual(cache.get_attachment_bytes(page_id, filename), payload)
            self.assertTrue(cache.get_attachment_path_if_exists(page_id, filename))

    def test_output_write_text_and_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = os.path.join(tmp, build_output_dir("case", timestamp="20260101_000000"))
            text_path = os.path.join(out_dir, "a.txt")
            json_path = os.path.join(out_dir, "b.json")

            write_text(text_path, "hello")
            write_json(json_path, {"x": 1})

            with open(text_path, "r", encoding="utf-8") as f:
                self.assertEqual(f.read(), "hello")
            with open(json_path, "r", encoding="utf-8") as f:
                self.assertIn('"x": 1', f.read())

    def test_runtime_exit_code_and_print(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            print_final_message(True)
            print_final_message(False)
        s = buf.getvalue()
        self.assertIn("[+] 搜索完成", s)
        self.assertIn("[-] 搜索失败", s)
        self.assertEqual(exit_code(True), 0)
        self.assertEqual(exit_code(False), 1)

