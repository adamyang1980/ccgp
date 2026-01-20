import os
import tempfile
import time
import unittest

from ccgp_core.antibot import RunContext, find_latest_results_dir, prepare_results_dir


class TestAntibotCore(unittest.TestCase):
    def test_prepare_results_dir_creates_new_when_no_resume(self):
        with tempfile.TemporaryDirectory() as td:
            out = prepare_results_dir("demo", resume=False, root_dir=td)
            self.assertTrue(os.path.isdir(out))
            self.assertIn(os.path.join(td, "demo"), out)

    def test_find_latest_results_dir_returns_most_recent(self):
        with tempfile.TemporaryDirectory() as td:
            base = os.path.join(td, "demo")
            os.makedirs(base, exist_ok=True)

            d1 = os.path.join(base, "search_results_demo_1")
            d2 = os.path.join(base, "search_results_demo_2")
            os.makedirs(d1, exist_ok=True)
            time.sleep(0.01)
            os.makedirs(d2, exist_ok=True)

            latest = find_latest_results_dir("demo", root_dir=td)
            self.assertEqual(latest, d2)

            out = prepare_results_dir("demo", resume=True, root_dir=td)
            self.assertEqual(out, d2)

    def test_run_context_checkpoint_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            out = prepare_results_dir("demo", resume=False, root_dir=td)
            ctx = RunContext(site="demo", out_dir=out, interactive=False)
            ctx.load_checkpoint()
            ctx.set_checkpoint(page_no=3, detail_done_ids=["a"])
            ctx.save_checkpoint()

            ctx2 = RunContext(site="demo", out_dir=out, interactive=False)
            cp = ctx2.load_checkpoint()
            self.assertEqual(cp.get("page_no"), 3)
            self.assertEqual(cp.get("detail_done_ids"), ["a"])

