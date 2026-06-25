import inspect
import os
from typing import Any, Callable, Optional

from .store import AnchorStore
from .adapters.selenium import SeleniumAdapter
from .adapters.playwright import PlaywrightAdapter, PlaywrightElement
from .adapters.bs4 import BS4Adapter
from ._healing import (
    HEAL_THRESHOLD,
    attempt_heal,
    update_confidence_on_success,
)

__all__ = ["heal", "HealContext", "HealingProxy", "HEAL_THRESHOLD"]


def get_caller_id(selector: str) -> str:
    frame = inspect.currentframe()
    try:
        while frame:
            filename = frame.f_code.co_filename
            # Skip frames inside anchorheal library or testing framework internals
            if "anchorheal" not in filename and "conftest" not in filename and "pytest" not in filename:
                base_name = os.path.basename(filename)
                # Drop the line number to prevent orphaning saved anchors when the scraper code is edited
                return f"{base_name}:{selector}"
            frame = frame.f_back
    finally:
        del frame
    return selector


def _adapter_for(driver_type: str) -> Any:
    if driver_type == "selenium":
        return SeleniumAdapter()
    if driver_type == "playwright":
        return PlaywrightAdapter()
    if driver_type == "bs4":
        return BS4Adapter()
    raise ValueError(f"Unknown driver_type: {driver_type}")


class HealingProxy:
    def __init__(self, obj: Any, driver_type: str, adapter: Any, store: AnchorStore, caller_id: Optional[str] = None):
        self.__dict__["_obj"] = obj
        self.__dict__["_driver_type"] = driver_type
        self.__dict__["_adapter"] = adapter
        self.__dict__["_store"] = store
        self.__dict__["_caller_id"] = caller_id

    def __getattr__(self, name: str) -> Any:
        obj = self.__dict__["_obj"]
        driver_type = self.__dict__["_driver_type"]
        adapter = self.__dict__["_adapter"]
        store = self.__dict__["_store"]
        caller_id = self.__dict__["_caller_id"]

        attr = getattr(obj, name)

        if callable(attr):
            def wrapper(*args, **kwargs):
                # 1. Selenium interception
                if driver_type == "selenium" and name in ("find_element",):
                    # args is usually (By, selector)
                    selector = args[1] if len(args) > 1 else kwargs.get("value", args[0])
                    cid = get_caller_id(selector)
                    try:
                        res = attr(*args, **kwargs)
                        # Successfully found: update the continuous-confidence curve (may raise on a decoy).
                        features = adapter.extract_features(res)
                        update_confidence_on_success(store, adapter, obj, cid, selector, features)
                        return HealingProxy(res._el if hasattr(res, "_el") else res, "selenium_element", adapter, store, cid)
                    except Exception as exc:
                        # Find failed (or a decoy was detected): trigger healing.
                        anchor = store.get_anchor(cid)
                        if anchor:
                            healed = attempt_heal(store, adapter, obj, cid, selector, anchor)
                            if healed:
                                best_cand, _ = healed
                                return HealingProxy(best_cand, "selenium_element", adapter, store, cid)
                        raise exc

                # 2. Playwright interception
                elif driver_type == "playwright" and name == "locator":
                    selector = args[0]
                    cid = get_caller_id(selector)
                    res = attr(*args, **kwargs)
                    return HealingProxy(res, "playwright_locator", adapter, store, cid)

                elif driver_type == "playwright_locator" and name in (
                    "click", "fill", "inner_text", "text_content", "check",
                    "uncheck", "select_option", "press", "focus", "hover", "type"
                ):
                    cid = caller_id
                    orig_selector = cid.split(":")[-1] if cid else ""
                    page = obj.page
                    try:
                        res = attr(*args, **kwargs)
                        # Action succeeded: update confidence from the resolved element (may raise on a decoy).
                        loc_first = obj.first
                        if loc_first.count() > 0:
                            features = adapter.extract_features(PlaywrightElement(loc_first))
                            update_confidence_on_success(store, adapter, page, cid, orig_selector, features)
                        return res
                    except Exception as exc:
                        anchor = store.get_anchor(cid)
                        if anchor:
                            healed = attempt_heal(store, adapter, page, cid, orig_selector, anchor)
                            if healed:
                                best_cand, _ = healed
                                # Re-issue the action against the healed locator directly.
                                return getattr(best_cand, name)(*args, **kwargs)
                        raise exc

                # 3. BS4 interception
                elif driver_type == "bs4" and name in ("select_one", "find"):
                    selector = args[0] if len(args) > 0 else kwargs.get("selector")
                    if not selector:
                        selector = args[0] if len(args) > 0 else ""
                    cid = get_caller_id(selector)
                    try:
                        res = attr(*args, **kwargs)
                        if res is None:
                            raise Exception("Element not found")
                        features = adapter.extract_features(res)
                        update_confidence_on_success(store, adapter, obj, cid, selector, features)
                        return HealingProxy(res._tag if hasattr(res, "_tag") and res._tag is not None else res, "bs4_element", adapter, store, cid)
                    except Exception as exc:
                        anchor = store.get_anchor(cid)
                        if anchor:
                            healed = attempt_heal(store, adapter, obj, cid, selector, anchor)
                            if healed:
                                best_cand, _ = healed
                                tag = best_cand._tag if hasattr(best_cand, "_tag") and best_cand._tag is not None else best_cand
                                return HealingProxy(tag, "bs4_element", adapter, store, cid)
                        raise exc

                # Normal forwarding for other functions
                return attr(*args, **kwargs)
            return wrapper
        return attr

    def __setattr__(self, name: str, value: Any) -> None:
        obj = self.__dict__["_obj"]
        setattr(obj, name, value)


def heal(driver_type: str, db_path: str = "anchorheal.db") -> Callable:
    """
    Decorator for scraper entry points. Wraps driver/page objects with a HealingProxy.
    """
    store = AnchorStore(db_path=db_path)
    adapter = _adapter_for(driver_type)

    def decorator(func: Callable) -> Callable:
        def wrapper(*args, **kwargs):
            new_args = list(args)
            if len(new_args) > 0:
                # Wrap the first arg (driver/page/soup)
                new_args[0] = HealingProxy(new_args[0], driver_type, adapter, store)
            return func(*new_args, **kwargs)
        return wrapper
    return decorator


# --- Tier-1 Context Finder Fallback ---

class HealContext:
    def __init__(self, driver: Any, driver_type: str, db_path: str = "anchorheal.db"):
        self.driver = driver
        self.driver_type = driver_type
        self.store = AnchorStore(db_path=db_path)
        self.adapter = _adapter_for(driver_type)

    def find(self, field_name: str, selector: str) -> Any:
        cid = f"tier1:{field_name}"
        try:
            el = self.adapter.query(self.driver, selector)
            if el is None:
                raise Exception(f"Element not found: {selector}")
            features = self.adapter.extract_features(el)
            update_confidence_on_success(self.store, self.adapter, self.driver, cid, selector, features)
            return el._el if hasattr(el, "_el") else el
        except Exception as exc:
            anchor = self.store.get_anchor(cid)
            if anchor:
                healed = attempt_heal(self.store, self.adapter, self.driver, cid, selector, anchor)
                if healed:
                    best_cand, _ = healed
                    return best_cand._el if hasattr(best_cand, "_el") else best_cand
            raise exc
