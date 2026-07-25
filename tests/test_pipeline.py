"""Tests for ccgp_core.pipeline module."""

import pytest

from ccgp_core.pipeline import (
    ChallengeDetected,
    ProbeResult,
    detect_challenge_http,
    detect_challenge_text,
    probe_with_http_request,
)


class TestDetectChallengeText:
    def test_empty_text_returns_none(self):
        assert detect_challenge_text("") is None
        assert detect_challenge_text("   ") is None

    def test_slider_keywords(self):
        assert detect_challenge_text("aliyun captcha") == "slider"
        assert detect_challenge_text("nc_1 wrapper") == "slider"
        assert detect_challenge_text("请完成滑块验证") == "slider"
        assert detect_challenge_text("滑动验证") == "slider"

    def test_captcha_keywords(self):
        assert detect_challenge_text("captcha required") == "captcha"
        assert detect_challenge_text("reCAPTCHA") == "captcha"

    def test_generic_verify_keywords(self):
        assert detect_challenge_text("访问验证") == "access_verify"
        assert detect_challenge_text("安全验证") == "access_verify"
        assert detect_challenge_text("人机验证") == "access_verify"

    def test_normal_text_returns_none(self):
        assert detect_challenge_text("正常页面内容") is None
        assert detect_challenge_text("hello world") is None


class TestDetectChallengeHttp:
    def test_401_returns_access_verify(self):
        result = detect_challenge_http(
            status_code=401,
            content_type="text/html",
            body_text="",
            expect_json=False,
        )
        assert result is not None
        assert result[0] == "access_verify"

    def test_403_returns_access_verify(self):
        result = detect_challenge_http(
            status_code=403,
            content_type="text/html",
            body_text="",
            expect_json=False,
        )
        assert result is not None
        assert result[0] == "access_verify"

    def test_429_returns_access_verify(self):
        result = detect_challenge_http(
            status_code=429,
            content_type="text/html",
            body_text="",
            expect_json=False,
        )
        assert result is not None
        assert result[0] == "access_verify"

    def test_200_json_expected_but_html_returned(self):
        result = detect_challenge_http(
            status_code=200,
            content_type="text/html",
            body_text="<html>aliyun slider</html>",
            expect_json=True,
        )
        assert result is not None
        assert result[0] == "slider"

    def test_200_json_valid_no_challenge(self):
        result = detect_challenge_http(
            status_code=200,
            content_type="application/json",
            body_text='{"data": []}',
            expect_json=True,
        )
        assert result is None

    def test_200_with_captcha_in_body(self):
        result = detect_challenge_http(
            status_code=200,
            content_type="text/html",
            body_text="please solve captcha",
            expect_json=False,
        )
        assert result is not None
        assert result[0] == "captcha"


class TestProbeWithHttpRequest:
    def test_normal_response_returns_none_kind(self):
        def req():
            return (200, "application/json", '{"ok": true}')

        pr = probe_with_http_request(request_fn=req, expect_json=True)
        assert pr.kind == "none"
        assert pr.engine == "HTTP"

    def test_blocked_response_returns_challenge(self):
        def req():
            return (403, "text/html", "<html>forbidden</html>")

        pr = probe_with_http_request(request_fn=req, expect_json=True)
        assert pr.kind == "access_verify"
        assert pr.engine == "BROWSER"

    def test_slider_response_uses_browser_engine(self):
        def req():
            return (200, "text/html", "aliyun slider page")

        pr = probe_with_http_request(request_fn=req, expect_json=True)
        assert pr.kind == "slider"
        assert pr.engine == "BROWSER"


class TestChallengeDetected:
    def test_exception_attributes(self):
        exc = ChallengeDetected("slider", "test message", {"key": "val"})
        assert exc.kind == "slider"
        assert exc.message == "test message"
        assert exc.evidence == {"key": "val"}

    def test_default_message_uses_kind(self):
        exc = ChallengeDetected("captcha")
        assert exc.message == "captcha"
