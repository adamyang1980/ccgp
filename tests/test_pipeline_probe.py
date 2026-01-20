import unittest

from ccgp_core.pipeline import detect_challenge_http, detect_challenge_text


class TestPipelineProbe(unittest.TestCase):
    def test_detect_challenge_text_slider(self):
        self.assertEqual(detect_challenge_text("aliyunCaptcha nc_1"), "slider")
        self.assertEqual(detect_challenge_text("请完成滑动验证"), "slider")

    def test_detect_challenge_text_access_verify(self):
        self.assertEqual(detect_challenge_text("访问验证"), "access_verify")

    def test_detect_challenge_http_status(self):
        kind = detect_challenge_http(status_code=403, content_type="text/html", body_text="", expect_json=False)
        self.assertEqual(kind[0], "access_verify")

    def test_detect_challenge_http_json_expected_but_html(self):
        kind = detect_challenge_http(
            status_code=200,
            content_type="text/html",
            body_text="<html>访问验证</html>",
            expect_json=True,
        )
        self.assertEqual(kind[0], "access_verify")

