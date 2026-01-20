import os
import subprocess
import sys
import unittest


class TestEntrypointsImportable(unittest.TestCase):
    def _run_import_check(self, rel_script: str) -> None:
        env = os.environ.copy()
        env["CCGP_IMPORT_CHECK"] = "1"
        proc = subprocess.run([sys.executable, rel_script], env=env, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("import_ok", (proc.stdout or ""))

    def test_run_jiangsu_importable(self):
        self._run_import_check(os.path.join("scripts", "run_jiangsu.py"))

    def test_run_xinjiang_importable(self):
        self._run_import_check(os.path.join("scripts", "run_xinjiang.py"))

