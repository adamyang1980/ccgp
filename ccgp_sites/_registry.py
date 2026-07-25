import importlib
import inspect
import pkgutil
from typing import Dict, Type

from ccgp_core.spider import BaseSpider


def _discover_sites() -> Dict[str, Type]:
    searchers: Dict[str, Type] = {}
    try:
        import ccgp_sites
    except Exception:
        return searchers

    for module_info in pkgutil.iter_modules(ccgp_sites.__path__):
        name = module_info.name
        if name.startswith("_"):
            continue
        try:
            adapter = importlib.import_module(f"ccgp_sites.{name}.adapter")
        except Exception:
            continue
        # 优先按约定命名查找: {Name}CCGPSearch
        searcher = getattr(adapter, f"{name.capitalize()}CCGPSearch", None)
        # 通用 fallback: 遍历 adapter 模块中所有 BaseSpider 子类
        if searcher is None:
            for attr_name in dir(adapter):
                obj = getattr(adapter, attr_name)
                if (
                    inspect.isclass(obj)
                    and issubclass(obj, BaseSpider)
                    and obj is not BaseSpider
                ):
                    searcher = obj
                    break
        if searcher is not None:
            searchers[name] = searcher
    return searchers


SEARCHERS: Dict[str, Type] = _discover_sites()


def list_sites() -> Dict[str, Type]:
    return dict(SEARCHERS)


def get_searcher(site: str) -> Type:
    key = (site or "").strip().lower()
    if key not in SEARCHERS:
        raise KeyError(f"Unknown site: {site}")
    return SEARCHERS[key]
