import importlib
import sys
import types
import unittest


def _install_stub(module_name: str) -> types.ModuleType:
    mod = types.ModuleType(module_name)
    sys.modules[module_name] = mod
    return mod


class TestRegistryDiscovery(unittest.TestCase):
    def test_registry_lists_sites(self):
        sys.modules.pop("ccgp_sites._registry", None)

        if "playwright" not in sys.modules:
            _install_stub("playwright")
        if "playwright.async_api" not in sys.modules:
            async_api = _install_stub("playwright.async_api")

            async def async_playwright():
                raise RuntimeError("stub")

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

        reg = importlib.import_module("ccgp_sites._registry")
        sites = reg.list_sites()
        self.assertIn("jiangsu", sites)
        self.assertIn("xinjiang", sites)
        self.assertTrue(callable(reg.get_searcher("jiangsu")))
        self.assertTrue(callable(reg.get_searcher("xinjiang")))

