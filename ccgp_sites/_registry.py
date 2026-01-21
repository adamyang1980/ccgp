import importlib
import pkgutil
from typing import Dict, Type


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
        searcher = getattr(adapter, f"{name.capitalize()}CCGPSearch", None)


        if searcher is None:
            searcher = getattr(adapter, "CCGPSearch", None)
        if searcher is None:
            for attr in ("JiangsuCCGPSearch", "XinjiangCCGPSearch"):
                if hasattr(adapter, attr):
                    searcher = getattr(adapter, attr)
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
