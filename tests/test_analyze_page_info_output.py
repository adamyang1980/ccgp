import unittest

import analyze_page_info_output as apio


class TestAnalyzePageInfoOutput(unittest.TestCase):
    def test_detects_best_list_and_detail_from_har(self):
        har = {
            "log": {
                "entries": [
                    {
                        "request": {
                            "method": "POST",
                            "url": "https://example.test/portal/category",
                            "postData": {"text": "{\"pageNo\":1,\"pageSize\":15,\"categoryCode\":\"X\"}"},
                        },
                        "response": {
                            "content": {
                                "text": "{\"success\":true,\"result\":{\"data\":{\"total\":2,\"data\":[{\"articleId\":\"a\"}]}}}"
                            }
                        },
                    },
                    {
                        "request": {
                            "method": "GET",
                            "url": "https://example.test/portal/detail?articleId=a&timestamp=1",
                        },
                        "response": {
                            "content": {
                                "text": "{\"success\":true,\"result\":{\"data\":{\"title\":\"t\",\"content\":\"<div>ok</div>\"}}}"
                            }
                        },
                    },
                ]
            }
        }

        endpoints = apio.find_best_endpoints_from_har(har)
        self.assertEqual(endpoints["best_list"]["url"], "https://example.test/portal/category")
        self.assertEqual(endpoints["best_list"]["method"], "POST")
        self.assertEqual(endpoints["best_detail"]["url"], "https://example.test/portal/detail?articleId=a&timestamp=1")

    def test_generate_site_skeleton_files(self):
        analysis = {
            "har_endpoints": {
                "best_list": {
                    "url": "https://example.test/portal/category",
                    "method": "POST",
                    "request_json": {"pageNo": 1, "pageSize": 15},
                },
                "best_detail": {
                    "url": "https://example.test/portal/detail?articleId=a&timestamp=1",
                    "method": "GET",
                    "request_json": None,
                },
            }
        }
        files = apio.generate_site_skeleton("zhejiang", analysis, "ccgp_sites")
        self.assertTrue(any(p.endswith("ccgp_sites\\zhejiang\\impl.py") for p in files.keys()))
        impl = files[[p for p in files.keys() if p.endswith("impl.py")][0]]
        self.assertIn("class ZhejiangCCGPSearch(BaseSpider):", impl)
        self.assertIn("from ccgp_core.spider import BaseSpider", impl)
        self.assertIn('super().__init__("zhejiang", config)', impl)

