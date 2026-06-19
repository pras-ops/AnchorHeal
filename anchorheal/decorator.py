import inspect
import os
import datetime
import math
from typing import Any, Callable, Dict, Optional, List
from .store import AnchorStore
from .models import Anchor, HealEvent
from .ranker import score_candidate, calculate_success_confidence, calculate_failure_confidence
from .adapters.selenium import SeleniumAdapter, SeleniumElement
from .adapters.playwright import PlaywrightAdapter, PlaywrightElement
from .adapters.bs4 import BS4Adapter, BS4Element

# Threshold score above which we accept healing
HEAL_THRESHOLD = 0.60

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
                        # Successfully found!
                        anchor = store.get_anchor(cid)
                        features = adapter.extract_features(res)
                        
                        if anchor is None:
                            # First time: save baseline anchor
                            anchor = Anchor(
                                caller_id=cid,
                                primary_selector=selector,
                                confidence=1.0,
                                **features
                            )
                            store.save_anchor(anchor)
                            store.log_confidence(cid, 1.0)
                        else:
                            # Subsequent success: score against baseline and log continuous confidence
                            score, _, _ = score_candidate(features, anchor)
                            new_conf = calculate_success_confidence(anchor.confidence, score)
                            store.log_confidence(cid, new_conf)
                            if score < HEAL_THRESHOLD:
                                # Soft decoy check: only heal if there is a significantly better candidate on the page
                                tag = anchor.tag or "*"
                                candidates = adapter.query_candidates(obj, tag)
                                if not candidates:
                                    candidates = adapter.query_candidates(obj, "*")
                                features_list = adapter.extract_features_bulk(obj, candidates)
                                best_cand_score = -1.0
                                for f in features_list:
                                    if not f:
                                        continue
                                    dist = 0.0
                                    if anchor.rel_position and f.get("rel_position"):
                                        dx = anchor.rel_position["x_pct"] - f["rel_position"]["x_pct"]
                                        dy = anchor.rel_position["y_pct"] - f["rel_position"]["y_pct"]
                                        dist = math.sqrt(dx*dx + dy*dy)
                                        if dist > 0.40:
                                            continue
                                    cand_score, _, _ = score_candidate(f, anchor)
                                    if cand_score > best_cand_score:
                                        best_cand_score = cand_score
                                if best_cand_score > score + 0.15 and best_cand_score >= HEAL_THRESHOLD:
                                    raise Exception(f"Decoy element detected (score {score:.2f} < threshold {HEAL_THRESHOLD} and better candidate score {best_cand_score:.2f} exists)")
                        
                        # Return wrapped element proxy
                        return HealingProxy(res._el if hasattr(res, "_el") else res, "selenium_element", adapter, store, cid)
                    except Exception as exc:
                        # Find element failed. Trigger healing!
                        anchor = store.get_anchor(cid)
                        if anchor:
                            driver = obj
                            # Prune candidates: query by anchor.tag first
                            tag = anchor.tag or "*"
                            candidates = adapter.query_candidates(driver, tag)
                            if not candidates:
                                candidates = adapter.query_candidates(driver, "*")
                                
                            # Batch extract features
                            features_list = adapter.extract_features_bulk(driver, candidates)
                            
                            best_cand = None
                            best_score = -1.0
                            best_signal = "dom"
                            best_features = {}
                            
                            pruned_candidates = []
                            for i, f in enumerate(features_list):
                                if not f:
                                    continue
                                dist = 0.0
                                if anchor.rel_position and f.get("rel_position"):
                                    dx = anchor.rel_position["x_pct"] - f["rel_position"]["x_pct"]
                                    dy = anchor.rel_position["y_pct"] - f["rel_position"]["y_pct"]
                                    dist = math.sqrt(dx*dx + dy*dy)
                                    if dist > 0.40:
                                        continue
                                pruned_candidates.append((candidates[i], f, dist))
                            
                            # Sort by distance and cap at nearest 300
                            pruned_candidates.sort(key=lambda x: x[2])
                            pruned_candidates = [(cand, f) for cand, f, d in pruned_candidates[:300]]
                                    
                            for cand_el, f in pruned_candidates:
                                score, signal, _ = score_candidate(f, anchor)
                                if score > best_score:
                                    best_score = score
                                    best_cand = cand_el
                                    best_signal = signal
                                    best_features = f
                                    
                            if best_score >= HEAL_THRESHOLD and best_cand:
                                # Heal successful! Refresh baseline golden snapshot
                                before_conf = anchor.confidence
                                after_conf = calculate_success_confidence(before_conf, best_score)
                                
                                healed_anchor = Anchor(
                                    caller_id=cid,
                                    primary_selector=selector,
                                    confidence=after_conf,
                                    **best_features
                                )
                                store.save_anchor(healed_anchor)
                                
                                # Log healing event
                                event = HealEvent(
                                    caller_id=cid,
                                    timestamp=datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None),
                                    old_selector=selector,
                                    new_selector=best_features.get("xpath") or selector,
                                    healed_features=best_features,
                                    confidence_before=before_conf,
                                    confidence_after=after_conf,
                                    primary_winning_signal=best_signal
                                )
                                store.log_heal_event(event)
                                store.log_confidence(cid, after_conf)
                                
                                # Return the winning candidate directly
                                return HealingProxy(best_cand, "selenium_element", adapter, store, cid)
                            else:
                                # Decrease confidence score on failure
                                store.log_confidence(cid, calculate_failure_confidence(anchor.confidence))
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
                    
                    try:
                        res = attr(*args, **kwargs)
                        # Success. Save/Update anchor features
                        page = obj.page
                        loc_first = obj.first
                        if loc_first.count() > 0:
                            wrapped_el = PlaywrightElement(loc_first)
                            features = adapter.extract_features(wrapped_el)
                            anchor = store.get_anchor(cid)
                            
                            if anchor is None:
                                anchor = Anchor(
                                    caller_id=cid,
                                    primary_selector=orig_selector,
                                    confidence=1.0,
                                    **features
                                )
                                store.save_anchor(anchor)
                                store.log_confidence(cid, 1.0)
                            else:
                                score, _, _ = score_candidate(features, anchor)
                                new_conf = calculate_success_confidence(anchor.confidence, score)
                                store.log_confidence(cid, new_conf)
                                if score < HEAL_THRESHOLD:
                                    # Soft decoy check: only heal if there is a significantly better candidate on the page
                                    tag = anchor.tag or "*"
                                    candidates = page.locator(tag).all()
                                    if not candidates:
                                        candidates = page.locator("*").all()
                                    features_list = adapter.extract_features_bulk(page, candidates)
                                    best_cand_score = -1.0
                                    for f in features_list:
                                        if not f:
                                            continue
                                        dist = 0.0
                                        if anchor.rel_position and f.get("rel_position"):
                                            dx = anchor.rel_position["x_pct"] - f["rel_position"]["x_pct"]
                                            dy = anchor.rel_position["y_pct"] - f["rel_position"]["y_pct"]
                                            dist = math.sqrt(dx*dx + dy*dy)
                                            if dist > 0.40:
                                                continue
                                        cand_score, _, _ = score_candidate(f, anchor)
                                        if cand_score > best_cand_score:
                                            best_cand_score = cand_score
                                    if best_cand_score > score + 0.15 and best_cand_score >= HEAL_THRESHOLD:
                                        raise Exception(f"Decoy element detected (score {score:.2f} < threshold {HEAL_THRESHOLD} and better candidate score {best_cand_score:.2f} exists)")
                        return res
                    except Exception as exc:
                        anchor = store.get_anchor(cid)
                        if anchor:
                            page = obj.page
                            # Prune candidates: query by anchor.tag first
                            tag = anchor.tag or "*"
                            candidates = page.locator(tag).all()
                            if not candidates:
                                candidates = page.locator("*").all()
                                
                            # Batch extract features
                            features_list = adapter.extract_features_bulk(page, candidates)
                            
                            best_cand = None
                            best_score = -1.0
                            best_signal = "dom"
                            best_features = {}
                            
                            pruned_candidates = []
                            for i, f in enumerate(features_list):
                                if not f:
                                    continue
                                dist = 0.0
                                if anchor.rel_position and f.get("rel_position"):
                                    dx = anchor.rel_position["x_pct"] - f["rel_position"]["x_pct"]
                                    dy = anchor.rel_position["y_pct"] - f["rel_position"]["y_pct"]
                                    dist = math.sqrt(dx*dx + dy*dy)
                                    if dist > 0.40:
                                        continue
                                pruned_candidates.append((candidates[i], f, dist))
                            
                            # Sort by distance and cap at nearest 300
                            pruned_candidates.sort(key=lambda x: x[2])
                            pruned_candidates = [(cand, f) for cand, f, d in pruned_candidates[:300]]
                                    
                            for cand_el, f in pruned_candidates:
                                score, signal, _ = score_candidate(f, anchor)
                                if score > best_score:
                                    best_score = score
                                    best_cand = cand_el
                                    best_signal = signal
                                    best_features = f
                                    
                            if best_score >= HEAL_THRESHOLD and best_cand:
                                before_conf = anchor.confidence
                                after_conf = calculate_success_confidence(before_conf, best_score)
                                
                                healed_anchor = Anchor(
                                    caller_id=cid,
                                    primary_selector=orig_selector,
                                    confidence=after_conf,
                                    **best_features
                                )
                                store.save_anchor(healed_anchor)
                                
                                event = HealEvent(
                                    caller_id=cid,
                                    timestamp=datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None),
                                    old_selector=orig_selector,
                                    new_selector=best_features.get("xpath") or orig_selector,
                                    healed_features=best_features,
                                    confidence_before=before_conf,
                                    confidence_after=after_conf,
                                    primary_winning_signal=best_signal
                                )
                                store.log_heal_event(event)
                                store.log_confidence(cid, after_conf)
                                
                                # Call the action on the healed locator directly
                                action_method = getattr(best_cand, name)
                                return action_method(*args, **kwargs)
                            else:
                                store.log_confidence(cid, calculate_failure_confidence(anchor.confidence))
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
                        # Successfully found!
                        anchor = store.get_anchor(cid)
                        features = adapter.extract_features(res)
                        
                        if anchor is None:
                            # First time: save baseline anchor
                            anchor = Anchor(
                                caller_id=cid,
                                primary_selector=selector,
                                confidence=1.0,
                                **features
                            )
                            store.save_anchor(anchor)
                            store.log_confidence(cid, 1.0)
                        else:
                            # Subsequent success: score against baseline and log continuous confidence
                            score, _, _ = score_candidate(features, anchor)
                            new_conf = calculate_success_confidence(anchor.confidence, score)
                            store.log_confidence(cid, new_conf)
                            if score < HEAL_THRESHOLD:
                                # Soft decoy check: only heal if there is a significantly better candidate on the page
                                tag = anchor.tag or "*"
                                candidates = adapter.query_candidates(obj, tag)
                                if not candidates:
                                    candidates = adapter.query_candidates(obj, "*")
                                features_list = adapter.extract_features_bulk(obj, candidates)
                                best_cand_score = -1.0
                                for f in features_list:
                                    if not f:
                                        continue
                                    dist = 0.0
                                    # BS4 has no coordinates/positions, so dist is always 0.0
                                    cand_score, _, _ = score_candidate(f, anchor)
                                    if cand_score > best_cand_score:
                                        best_cand_score = cand_score
                                if best_cand_score > score + 0.15 and best_cand_score >= HEAL_THRESHOLD:
                                    raise Exception(f"Decoy element detected (score {score:.2f} < threshold {HEAL_THRESHOLD} and better candidate score {best_cand_score:.2f} exists)")
                        
                        # Return wrapped element proxy
                        return HealingProxy(res._tag if hasattr(res, "_tag") and res._tag is not None else res, "bs4_element", adapter, store, cid)
                    except Exception as exc:
                        # Find element failed. Trigger healing!
                        anchor = store.get_anchor(cid)
                        if anchor:
                            # Prune candidates: query by anchor.tag first
                            tag = anchor.tag or "*"
                            candidates = adapter.query_candidates(obj, tag)
                            if not candidates:
                                candidates = adapter.query_candidates(obj, "*")
                                
                            # Batch extract features
                            features_list = adapter.extract_features_bulk(obj, candidates)
                            
                            best_cand = None
                            best_score = -1.0
                            best_signal = "dom"
                            best_features = {}
                            
                            pruned_candidates = []
                            for i, f in enumerate(features_list):
                                if not f:
                                    continue
                                dist = 0.0
                                pruned_candidates.append((candidates[i], f, dist))
                            
                            # Sort by distance (all 0.0 for BS4, but keeps DOM structure) and cap at nearest 300
                            pruned_candidates.sort(key=lambda x: x[2])
                            pruned_candidates = [(cand, f) for cand, f, d in pruned_candidates[:300]]
                                    
                            for cand_el, f in pruned_candidates:
                                score, signal, _ = score_candidate(f, anchor)
                                if score > best_score:
                                    best_score = score
                                    best_cand = cand_el
                                    best_signal = signal
                                    best_features = f
                                    
                            if best_score >= HEAL_THRESHOLD and best_cand:
                                # Heal successful! Refresh baseline golden snapshot
                                before_conf = anchor.confidence
                                after_conf = calculate_success_confidence(before_conf, best_score)
                                
                                healed_anchor = Anchor(
                                    caller_id=cid,
                                    primary_selector=selector,
                                    confidence=after_conf,
                                    **best_features
                                )
                                store.save_anchor(healed_anchor)
                                
                                # Log healing event
                                event = HealEvent(
                                    caller_id=cid,
                                    timestamp=datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None),
                                    old_selector=selector,
                                    new_selector=best_features.get("xpath") or selector,
                                    healed_features=best_features,
                                    confidence_before=before_conf,
                                    confidence_after=after_conf,
                                    primary_winning_signal=best_signal
                                )
                                store.log_heal_event(event)
                                store.log_confidence(cid, after_conf)
                                
                                # Return the winning candidate directly
                                return HealingProxy(best_cand._tag if hasattr(best_cand, "_tag") and best_cand._tag is not None else best_cand, "bs4_element", adapter, store, cid)
                            else:
                                # Decrease confidence score on failure
                                store.log_confidence(cid, calculate_failure_confidence(anchor.confidence))
                        raise exc

                # Normal forwarding for other functions
                res = attr(*args, **kwargs)
                if isinstance(res, (HealingProxy,)):
                    return res
                return res
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
    
    if driver_type == "selenium":
        adapter = SeleniumAdapter()
    elif driver_type == "playwright":
        adapter = PlaywrightAdapter()
    elif driver_type == "bs4":
        adapter = BS4Adapter()
    else:
        raise ValueError(f"Unknown driver_type: {driver_type}")

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
        
        if driver_type == "selenium":
            self.adapter = SeleniumAdapter()
        elif driver_type == "playwright":
            self.adapter = PlaywrightAdapter()
        elif driver_type == "bs4":
            self.adapter = BS4Adapter()

    def find(self, field_name: str, selector: str) -> Any:
        cid = f"tier1:{field_name}"
        try:
            # Query element
            el = self.adapter.query(self.driver, selector)
            if el is None:
                raise Exception(f"Element not found: {selector}")
                
            features = self.adapter.extract_features(el)
            anchor = self.store.get_anchor(cid)
            
            if anchor is None:
                anchor = Anchor(
                    caller_id=cid,
                    primary_selector=selector,
                    confidence=1.0,
                    **features
                )
                self.store.save_anchor(anchor)
                self.store.log_confidence(cid, 1.0)
            else:
                score, _, _ = score_candidate(features, anchor)
                new_conf = calculate_success_confidence(anchor.confidence, score)
                self.store.log_confidence(cid, new_conf)
                if score < HEAL_THRESHOLD:
                    # Soft decoy check: only heal if there is a significantly better candidate on the page
                    tag = anchor.tag or "*"
                    candidates = self.adapter.query_candidates(self.driver, tag)
                    if not candidates:
                        candidates = self.adapter.query_candidates(self.driver, "*")
                    features_list = self.adapter.extract_features_bulk(self.driver, candidates)
                    best_cand_score = -1.0
                    for f in features_list:
                        if not f:
                            continue
                        dist = 0.0
                        if anchor.rel_position and f.get("rel_position"):
                            dx = anchor.rel_position["x_pct"] - f["rel_position"]["x_pct"]
                            dy = anchor.rel_position["y_pct"] - f["rel_position"]["y_pct"]
                            dist = math.sqrt(dx*dx + dy*dy)
                            if dist > 0.40:
                                continue
                        cand_score, _, _ = score_candidate(f, anchor)
                        if cand_score > best_cand_score:
                            best_cand_score = cand_score
                    if best_cand_score > score + 0.15 and best_cand_score >= HEAL_THRESHOLD:
                        raise Exception(f"Decoy element detected (score {score:.2f} < threshold {HEAL_THRESHOLD} and better candidate score {best_cand_score:.2f} exists)")
                
            return el._el if hasattr(el, "_el") else el
        except Exception as exc:
            anchor = self.store.get_anchor(cid)
            if anchor:
                # Prune candidates
                tag = anchor.tag or "*"
                candidates = self.adapter.query_candidates(self.driver, tag)
                if not candidates:
                    candidates = self.adapter.query_candidates(self.driver, "*")
                    
                # Batch extract features
                features_list = self.adapter.extract_features_bulk(self.driver, candidates)
                
                best_cand = None
                best_score = -1.0
                best_signal = "dom"
                best_features = {}
                
                pruned_candidates = []
                for i, f in enumerate(features_list):
                    if not f:
                        continue
                    dist = 0.0
                    if anchor.rel_position and f.get("rel_position"):
                        dx = anchor.rel_position["x_pct"] - f["rel_position"]["x_pct"]
                        dy = anchor.rel_position["y_pct"] - f["rel_position"]["y_pct"]
                        dist = math.sqrt(dx*dx + dy*dy)
                        if dist > 0.40:
                            continue
                    pruned_candidates.append((candidates[i], f, dist))
                
                # Sort by distance and cap at nearest 300
                pruned_candidates.sort(key=lambda x: x[2])
                pruned_candidates = [(cand, f) for cand, f, d in pruned_candidates[:300]]
                        
                for cand_el, f in pruned_candidates:
                    score, signal, _ = score_candidate(f, anchor)
                    if score > best_score:
                        best_score = score
                        best_cand = cand_el
                        best_signal = signal
                        best_features = f
                        
                if best_score >= HEAL_THRESHOLD and best_cand:
                    before_conf = anchor.confidence
                    after_conf = calculate_success_confidence(before_conf, best_score)
                    
                    healed_anchor = Anchor(
                        caller_id=cid,
                        primary_selector=selector,
                        confidence=after_conf,
                        **best_features
                    )
                    self.store.save_anchor(healed_anchor)
                    
                    event = HealEvent(
                        caller_id=cid,
                        timestamp=datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None),
                        old_selector=selector,
                        new_selector=best_features.get("xpath") or selector,
                        healed_features=best_features,
                        confidence_before=before_conf,
                        confidence_after=after_conf,
                        primary_winning_signal=best_signal
                    )
                    self.store.log_heal_event(event)
                    self.store.log_confidence(cid, after_conf)
                    
                    return best_cand._el if hasattr(best_cand, "_el") else best_cand
                else:
                    self.store.log_confidence(cid, calculate_failure_confidence(anchor.confidence))
            raise exc
