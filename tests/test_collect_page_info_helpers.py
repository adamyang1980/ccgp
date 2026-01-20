import unittest

import collect_page_info as cpi


class TestCollectPageInfoHelpers(unittest.TestCase):
    def test_trim_text(self):
        self.assertEqual(cpi._trim_text("", 3), "")
        self.assertEqual(cpi._trim_text("abc", 3), "abc")
        self.assertEqual(cpi._trim_text("abcd", 3), "abc")

    def test_is_suspected_list_json(self):
        self.assertFalse(cpi._is_suspected_list_json({}))
        self.assertTrue(cpi._is_suspected_list_json({"total": 0}))
        self.assertTrue(cpi._is_suspected_list_json({"data": [{"a": 1}]}))
        self.assertTrue(cpi._is_suspected_list_json([{"a": 1}]))
        self.assertFalse(cpi._is_suspected_list_json([]))

