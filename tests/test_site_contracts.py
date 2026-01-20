import importlib
import sys
import types
import unittest


def _install_stub(module_name: str) -> types.ModuleType:
    mod = types.ModuleType(module_name)
    sys.modules[module_name] = mod
    return mod


def _ensure_xinjiang_import_deps():
    if "playwright" not in sys.modules:
        _install_stub("playwright")
    if "playwright.async_api" not in sys.modules:
        async_api = _install_stub("playwright.async_api")

        class AsyncContextManagerStub:
             async def __aenter__(self):
                 return self
             async def __aexit__(self, exc_type, exc, tb):
                 pass
             def chromium(self): pass
             
        async def async_playwright():
            return AsyncContextManagerStub()

        async_api.async_playwright = async_playwright

    if "cv2" not in sys.modules:
        cv2 = _install_stub("cv2")
        cv2.IMREAD_GRAYSCALE = 0
        cv2.TM_CCOEFF_NORMED = 0

        def _not_called(*args, **kwargs):
            raise RuntimeError("stub")

        cv2.imdecode = _not_called
        cv2.GaussianBlur = _not_called
        cv2.Canny = _not_called
        cv2.matchTemplate = _not_called
        cv2.minMaxLoc = _not_called


class TestSiteContracts(unittest.TestCase):
    def test_discovered_sites_have_init_config_and_run(self):
        _ensure_xinjiang_import_deps()
        reg = importlib.import_module("ccgp_sites._registry")
        sites = reg.list_sites()
        self.assertIn("jiangsu", sites)
        self.assertIn("xinjiang", sites)
        self.assertIn("zhejiang", sites)

        for site_name, searcher_cls in sites.items():
            # Check 1: Should inherit from BaseSpider
            from ccgp_core.spider import BaseSpider
            self.assertTrue(issubclass(searcher_cls, BaseSpider))
            
            # Check 2: Can instantiate with config dict
            try:
                inst = searcher_cls({})
            except Exception as e:
                self.fail(f"Could not instantiate {site_name} with empty config: {e}")
            
            # Check 3: Has run method
            self.assertTrue(hasattr(inst, "run"))
            self.assertTrue(callable(inst.run))

            # Check 4: config module exists
            mod = importlib.import_module(f"ccgp_sites.{site_name}.config")
            self.assertIsNotNone(mod)
