import math
import argparse
import sys
import requests
import os
from typing import List, Dict, Any, Tuple
from anchorheal.models import Anchor
from anchorheal.ranker import score_candidate, calculate_success_confidence

# Scenarios for local unit-level benchmark
SCENARIOS: List[Dict[str, Any]] = [
    {
        "name": "Class Rename / Position Preserved",
        "description": "Target class changes from '.price' to '.amt', but stays in same position. Distractor has class '.price' but is in header.",
        "anchor": Anchor(
            caller_id="test1", primary_selector=".price", tag="span", classes=["price"],
            text_pattern="\\$19.99", xpath="//div/span[1]",
            rel_position={"x_pct": 0.75, "y_pct": 0.35}, bbox={"x": 750, "y": 350, "w": 60, "h": 20}, viewport={"w": 1000, "h": 1000}
        ),
        "candidates": [
            # Candidate 0: Distractor (has original class '.price' but wrong text & wrong position)
            {
                "tag": "span", "classes": ["price"], "id_attr": None, "text": "Cart Items", "xpath": "//header/span",
                "rel_position": {"x_pct": 0.10, "y_pct": 0.05}, "bbox": {"x": 100, "y": 50, "w": 60, "h": 20},
                "parent_chain": ["header"], "sibling_text": []
            },
            # Candidate 1: True Target (renamed class, correct position, correct text)
            {
                "tag": "span", "classes": ["amt"], "id_attr": None, "text": "$19.99", "xpath": "//div/span[1]",
                "rel_position": {"x_pct": 0.76, "y_pct": 0.36}, "bbox": {"x": 760, "y": 360, "w": 60, "h": 20},
                "parent_chain": ["div"], "sibling_text": ["Product details"]
            }
        ],
        "target_index": 1
    },
    {
        "name": "Drastic DOM Churn / Position Preserved",
        "description": "Entire DOM hierarchy and classes change. Only text and visual position match.",
        "anchor": Anchor(
            caller_id="test2", primary_selector=".add-to-cart", tag="button", classes=["btn", "add-to-cart"],
            text_pattern="Add to Cart", xpath="//form/button",
            rel_position={"x_pct": 0.50, "y_pct": 0.80}, bbox={"x": 500, "y": 800, "w": 120, "h": 40}, viewport={"w": 1000, "h": 1000}
        ),
        "candidates": [
            # Candidate 0: True Target (different tag, class, xpath; same position, same text)
            {
                "tag": "div", "classes": ["purchase-link"], "id_attr": "buy-now", "text": "Add to Cart", "xpath": "//section/div[3]",
                "rel_position": {"x_pct": 0.51, "y_pct": 0.81}, "bbox": {"x": 510, "y": 810, "w": 120, "h": 40},
                "parent_chain": ["section", "main"], "sibling_text": []
            },
            # Candidate 1: Distractor (same tag and class btn, wrong text, wrong position)
            {
                "tag": "button", "classes": ["btn", "add-to-cart"], "id_attr": None, "text": "Cancel", "xpath": "//footer/button",
                "rel_position": {"x_pct": 0.20, "y_pct": 0.95}, "bbox": {"x": 200, "y": 950, "w": 80, "h": 30},
                "parent_chain": ["footer"], "sibling_text": []
            }
        ],
        "target_index": 0
    },
    {
        "name": "Text Update / DOM Preserved",
        "description": "Element text updates (e.g. stock count), but DOM and position are fully preserved.",
        "anchor": Anchor(
            caller_id="test3", primary_selector="#stock-lvl", tag="span", classes=["badge"], id_attr="stock-lvl",
            text_pattern="In Stock \\(5\\)", xpath="//span[@id='stock-lvl']",
            rel_position={"x_pct": 0.20, "y_pct": 0.40}, bbox={"x": 200, "y": 400, "w": 80, "h": 20}, viewport={"w": 1000, "h": 1000}
        ),
        "candidates": [
            # Candidate 0: True Target (text changed to 'Out of Stock', DOM & position same)
            {
                "tag": "span", "classes": ["badge"], "id_attr": "stock-lvl", "text": "Out of Stock", "xpath": "//span[@id='stock-lvl']",
                "rel_position": {"x_pct": 0.20, "y_pct": 0.40}, "bbox": {"x": 200, "y": 400, "w": 80, "h": 20},
                "parent_chain": ["div"], "sibling_text": []
            },
            # Candidate 1: Distractor (same text but totally different section and position)
            {
                "tag": "span", "classes": ["badge"], "id_attr": "other-lvl", "text": "In Stock (5)", "xpath": "//sidebar/span",
                "rel_position": {"x_pct": 0.90, "y_pct": 0.15}, "bbox": {"x": 900, "y": 150, "w": 80, "h": 20},
                "parent_chain": ["sidebar"], "sibling_text": []
            }
        ],
        "target_index": 0
    },
    {
        "name": "Table Row Selection / Same Class",
        "description": "Grid of elements with identical classes. We must pick the correct row based on sibling context and location.",
        "anchor": Anchor(
            caller_id="test4", primary_selector=".cell-qty", tag="td", classes=["cell-qty"],
            text_pattern="42", xpath="//tr[3]/td[2]", parent_chain=["tr", "tbody", "table"], sibling_text=["Item A", "$10"],
            rel_position={"x_pct": 0.40, "y_pct": 0.50}, bbox={"x": 400, "y": 500, "w": 50, "h": 30}, viewport={"w": 1000, "h": 1000}
        ),
        "candidates": [
            # Candidate 0: Row 1 qty cell (distractor - same tag/class/text, different position and siblings)
            {
                "tag": "td", "classes": ["cell-qty"], "id_attr": None, "text": "42", "xpath": "//tr[1]/td[2]",
                "rel_position": {"x_pct": 0.40, "y_pct": 0.40}, "bbox": {"x": 400, "y": 400, "w": 50, "h": 30},
                "parent_chain": ["tr", "tbody", "table"], "sibling_text": ["Item B", "$20"]
            },
            # Candidate 1: Row 3 qty cell (true target - matching position, sibling context, and text)
            {
                "tag": "td", "classes": ["cell-qty"], "id_attr": None, "text": "42", "xpath": "//tr[3]/td[2]",
                "rel_position": {"x_pct": 0.40, "y_pct": 0.50}, "bbox": {"x": 400, "y": 500, "w": 50, "h": 30},
                "parent_chain": ["tr", "tbody", "table"], "sibling_text": ["Item A", "$10"]
            }
        ],
        "target_index": 1
    },
    {
        "name": "Slight Layout Shift",
        "description": "Banner pushing main content down. True element shifted by 15% Y viewport units.",
        "anchor": Anchor(
            caller_id="test5", primary_selector="#hero-title", tag="h1", classes=["hero"], id_attr="hero-title",
            text_pattern="Welcome", xpath="//h1",
            rel_position={"x_pct": 0.50, "y_pct": 0.20}, bbox={"x": 500, "y": 200, "w": 200, "h": 50}, viewport={"w": 1000, "h": 1000}
        ),
        "candidates": [
            # Candidate 0: True Target (shifted down, identical features)
            {
                "tag": "h1", "classes": ["hero"], "id_attr": "hero-title", "text": "Welcome", "xpath": "//h1",
                "rel_position": {"x_pct": 0.50, "y_pct": 0.35}, "bbox": {"x": 500, "y": 350, "w": 200, "h": 50},
                "parent_chain": ["div"], "sibling_text": []
            },
            # Candidate 1: Distractor (at old position, different text and id)
            {
                "tag": "h2", "classes": ["banner"], "id_attr": "promo", "text": "Discount Alert!", "xpath": "//h2",
                "rel_position": {"x_pct": 0.50, "y_pct": 0.20}, "bbox": {"x": 500, "y": 200, "w": 300, "h": 60},
                "parent_chain": ["div"], "sibling_text": []
            }
        ],
        "target_index": 0
    },
    {
        "name": "Renamed Container ID / Content Shift",
        "description": "ID matches partially, position shifts slightly. DOM-only would struggle if xpath changes, visual helps disambiguate.",
        "anchor": Anchor(
            caller_id="test6", primary_selector=".desc", tag="p", classes=["desc"], id_attr="desc-v1",
            text_pattern="Product description goes here", xpath="//div[@id='desc-v1']/p",
            rel_position={"x_pct": 0.30, "y_pct": 0.60}, bbox={"x": 300, "y": 600, "w": 400, "h": 100}, viewport={"w": 1000, "h": 1000}
        ),
        "candidates": [
            # Candidate 0: Distractor (similar tag/class, wrong text, wrong position)
            {
                "tag": "p", "classes": ["desc"], "id_attr": "desc-header", "text": "Header summary", "xpath": "//header/p",
                "rel_position": {"x_pct": 0.30, "y_pct": 0.10}, "bbox": {"x": 300, "y": 100, "w": 400, "h": 50},
                "parent_chain": ["header"], "sibling_text": []
            },
            # Candidate 1: True Target (renamed container ID 'desc-v2', shifted slightly)
            {
                "tag": "p", "classes": ["desc"], "id_attr": "desc-v2", "text": "Product description goes here", "xpath": "//div[@id='desc-v2']/p",
                "rel_position": {"x_pct": 0.31, "y_pct": 0.62}, "bbox": {"x": 310, "y": 620, "w": 400, "h": 100},
                "parent_chain": ["div"], "sibling_text": []
            }
        ],
        "target_index": 1
    },
    {
        "name": "Sidebar Advertisement Hijack",
        "description": "Ad injection shifts target. Original selector class is hijacked by the ad.",
        "anchor": Anchor(
            caller_id="test7", primary_selector=".side-item", tag="a", classes=["side-item"],
            text_pattern="My Profile", xpath="//aside/a[2]",
            rel_position={"x_pct": 0.15, "y_pct": 0.40}, bbox={"x": 150, "y": 400, "w": 100, "h": 30}, viewport={"w": 1000, "h": 1000}
        ),
        "candidates": [
            # Candidate 0: Ad Hijacker (at old visual position, same class, totally different text and link)
            {
                "tag": "a", "classes": ["side-item"], "id_attr": None, "text": "Buy Crypto NOW!", "xpath": "//aside/a[1]",
                "rel_position": {"x_pct": 0.15, "y_pct": 0.40}, "bbox": {"x": 150, "y": 400, "w": 100, "h": 30},
                "parent_chain": ["aside"], "sibling_text": []
            },
            # Candidate 1: True Target (pushed down to y=450, same text)
            {
                "tag": "a", "classes": ["side-item"], "id_attr": None, "text": "My Profile", "xpath": "//aside/a[3]",
                "rel_position": {"x_pct": 0.15, "y_pct": 0.45}, "bbox": {"x": 150, "y": 450, "w": 100, "h": 30},
                "parent_chain": ["aside"], "sibling_text": ["Buy Crypto NOW!"]
            }
        ],
        "target_index": 1
    },
    {
        "name": "Multiple Identical Buttons",
        "description": "Three identical 'Buy' buttons. The user clicked the second one. Visual coordinates are key.",
        "anchor": Anchor(
            caller_id="test8", primary_selector=".buy-btn", tag="button", classes=["buy-btn"],
            text_pattern="Buy", xpath="//div[2]/button",
            rel_position={"x_pct": 0.50, "y_pct": 0.50}, bbox={"x": 500, "y": 500, "w": 80, "h": 30}, viewport={"w": 1000, "h": 1000}
        ),
        "candidates": [
            # Candidate 0: Button 1 (identical features, y_pct=0.30)
            {
                "tag": "button", "classes": ["buy-btn"], "id_attr": None, "text": "Buy", "xpath": "//div[1]/button",
                "rel_position": {"x_pct": 0.50, "y_pct": 0.30}, "bbox": {"x": 500, "y": 300, "w": 80, "h": 30},
                "parent_chain": ["div"], "sibling_text": []
            },
            # Candidate 1: Button 2 (true target, y_pct=0.50)
            {
                "tag": "button", "classes": ["buy-btn"], "id_attr": None, "text": "Buy", "xpath": "//div[2]/button",
                "rel_position": {"x_pct": 0.50, "y_pct": 0.50}, "bbox": {"x": 500, "y": 500, "w": 80, "h": 30},
                "parent_chain": ["div"], "sibling_text": []
            },
            # Candidate 2: Button 3 (identical features, y_pct=0.70)
            {
                "tag": "button", "classes": ["buy-btn"], "id_attr": None, "text": "Buy", "xpath": "//div[3]/button",
                "rel_position": {"x_pct": 0.50, "y_pct": 0.70}, "bbox": {"x": 500, "y": 700, "w": 80, "h": 30},
                "parent_chain": ["div"], "sibling_text": []
            }
        ],
        "target_index": 1
    }
]

# Standard Weights
DOM_ONLY_WEIGHTS = {"dom": 0.80, "visual": 0.00, "text": 0.15, "context": 0.05}
FULL_RANKER_WEIGHTS = {"dom": 0.45, "visual": 0.25, "text": 0.20, "context": 0.10}

def compute_ablation_attribution(candidates: List[Dict[str, Any]], anchor: Anchor, target_idx: int) -> List[str]:
    """
    Identifies which signals are decisive/necessary by dropping them one-by-one.
    If dropping a signal causes the correct pick to break (either score falls below 0.60,
    or another candidate outscores it), then that signal is Decisive.
    """
    signals = ["dom", "visual", "text", "context"]
    decisive_signals = []
    
    # 1. Full ranker result
    best_idx = -1
    best_score = -1.0
    for idx, c in enumerate(candidates):
        score, _, _ = score_candidate(c, anchor, FULL_RANKER_WEIGHTS)
        if score > best_score:
            best_score = score
            best_idx = idx
            
    if best_idx != target_idx or best_score < 0.60:
        # Fails even with full ranker, no ablation possible
        return []
        
    # 2. Drop each signal
    for sig in signals:
        # Copy weights
        weights = FULL_RANKER_WEIGHTS.copy()
        weights[sig] = 0.0
        
        # Renormalize remaining weights to sum to 1.0
        active_sum = sum(weights.values())
        if active_sum > 0:
            for k in weights:
                weights[k] /= active_sum
                
        # Evaluate under ablated weights
        best_ablated_idx = -1
        best_ablated_score = -1.0
        for idx, c in enumerate(candidates):
            score, _, _ = score_candidate(c, anchor, weights)
            if score > best_ablated_score:
                best_ablated_score = score
                best_ablated_idx = idx
                
        # If removing the signal broke correctness or dropped below threshold, it's decisive
        if best_ablated_idx != target_idx or best_ablated_score < 0.60:
            decisive_signals.append(sig)
            
    return decisive_signals

def run_local_benchmark():
    print("=" * 80)
    print("           ANCHORHEAL SYNTHETIC SCENARIO BENCHMARK (ABLATION)")
    print("=" * 80)
    
    dom_successes = 0
    full_successes = 0
    total_scenarios = len(SCENARIOS)
    
    ablation_counts = {"dom": 0, "visual": 0, "text": 0, "context": 0}
    
    print(f"{'Scenario Name':<38} | {'DOM-Only':<8} | {'Full':<8} | {'Decisive Signals (Ablated)'}")
    print("-" * 85)
    
    for scene in SCENARIOS:
        name = scene["name"]
        anchor = scene["anchor"]
        candidates = scene["candidates"]
        target_idx = scene["target_index"]
        
        # Evaluate DOM-only
        best_dom_idx = -1
        best_dom_score = -1.0
        for i, c in enumerate(candidates):
            score, _, _ = score_candidate(c, anchor, DOM_ONLY_WEIGHTS)
            if score > best_dom_score:
                best_dom_score = score
                best_dom_idx = i
        dom_ok = (best_dom_idx == target_idx and best_dom_score >= 0.60)
        if dom_ok:
            dom_successes += 1
            
        # Evaluate Full
        best_full_idx = -1
        best_full_score = -1.0
        for i, c in enumerate(candidates):
            score, _, _ = score_candidate(c, anchor, FULL_RANKER_WEIGHTS)
            if score > best_full_score:
                best_full_score = score
                best_full_idx = i
        full_ok = (best_full_idx == target_idx and best_full_score >= 0.60)
        if full_ok:
            full_successes += 1
            
        # Determine decisive signals
        decisives = compute_ablation_attribution(candidates, anchor, target_idx)
        for sig in decisives:
            ablation_counts[sig] += 1
            
        dom_str = "PASS" if dom_ok else "FAIL"
        full_str = "PASS" if full_ok else "FAIL"
        dec_str = ", ".join(d.upper() for d in decisives) if decisives else "NONE"
        print(f"{name:<38} | {dom_str:<8} | {full_str:<8} | {dec_str}")
        
    dom_rate = dom_successes / total_scenarios
    full_rate = full_successes / total_scenarios
    lift = full_rate - dom_rate
    
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Total Scenarios: {total_scenarios}")
    print(f"DOM-Only Success Rate: {dom_rate:.1%}")
    print(f"Full Ranker Success:    {full_rate:.1%}")
    print(f"Net Lift:              {lift:+.1%}")
    
    print("\nDECISIVE ABLATION COUNTS (WHICH SIGNALS PREVENTED FAILURES):")
    for sig, count in ablation_counts.items():
        print(f"  - {sig.upper():<7}: {count} times")
    print("\nNote: In some scenarios like 'Class Rename / Position Preserved', ablation may report 'NONE' decisive.")
    print("This occurs because the correct element is rescued by multiple redundant signals (visual, text, context),")
    print("so no single signal's absence is enough to break the correct pick, even though the combination is required to beat DOM-only.")
    print("=" * 80)

def run_live_benchmark():
    # Verify testsite is running
    url = "http://localhost:5000"
    try:
        r = requests.get(url, timeout=2.0)
        if r.status_code != 200:
            raise Exception()
    except Exception:
        print("[Error] Test website is not running at http://localhost:5000.")
        print("Please start testsite/app.py in a separate shell first.")
        sys.exit(1)
        
    print("=" * 80)
    print("             ANCHORHEAL LIVE TESTSITE BENCHMARK (--LIVE)")
    print("=" * 80)
    
    # We will drive Selenium directly
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from anchorheal import heal
        from anchorheal.store import AnchorStore
    except ImportError:
        print("[Error] Selenium or anchorheal not installed properly.")
        sys.exit(1)
        
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    driver = webdriver.Chrome(options=chrome_options)
    
    # Fresh sqlite DBs for benchmarking to avoid contamination
    db_path_dom = "benchmark_live_dom.db"
    db_path_full = "benchmark_live_full.db"
    
    for db_p in [db_path_dom, db_path_full]:
        if os.path.exists(db_p):
            os.remove(db_p)
            
    store_dom = AnchorStore(db_path=db_path_dom)
    store_full = AnchorStore(db_path=db_path_full)
    
    # 1. Scraper definitions
    # A. Scraper wrapped in full-ranker @heal
    @heal(driver_type="selenium", db_path=db_path_full)
    def scrape_full(drv):
        # We query the price-tag on whatever page we are on
        el = drv.find_element("css selector", ".price-tag")
        return el.text
        
    # B. DOM-Only baseline scraper (manual simulation with visual = 0)
    # We load saved baseline from store_dom, find all candidates, score using DOM_ONLY_WEIGHTS
    def scrape_dom_only(drv, original_selector, caller_id):
        anchor = store_dom.get_anchor(caller_id)
        if not anchor:
            # First pass: capture features
            try:
                el = drv.find_element("css selector", original_selector)
                # save baseline
                from anchorheal.adapters.selenium import SeleniumAdapter
                adapter = SeleniumAdapter()
                features = adapter.extract_features(el)
                anchor = Anchor(caller_id=caller_id, primary_selector=original_selector, confidence=1.0, **features)
                store_dom.save_anchor(anchor)
                return el.text
            except Exception:
                return None
        else:
            # Find and score candidates using DOM-only weights
            try:
                el = drv.find_element("css selector", original_selector)
                return el.text
            except Exception:
                # Trigger manual DOM-only healing
                from anchorheal.adapters.selenium import SeleniumAdapter
                adapter = SeleniumAdapter()
                cands = adapter.query_candidates(drv, anchor.tag or "*")
                if not cands:
                    cands = adapter.query_candidates(drv, "*")
                features_list = adapter.extract_features_bulk(drv, cands)
                
                best_cand = None
                best_score = -1.0
                for i, f in enumerate(features_list):
                    if not f: continue
                    score, _, _ = score_candidate(f, anchor, DOM_ONLY_WEIGHTS)
                    if score > best_score:
                        best_score = score
                        best_cand = cands[i]
                if best_score >= 0.60 and best_cand:
                    return best_cand.text
                return None
                
    # 2. Run across v1 to v5
    scenarios = [
        ("v1 (Baseline)", "/product?v=1", True),
        ("v2 (Class Rename)", "/product?v=2", True),
        ("v3 (Layout Shift)", "/product?v=3", True),
        ("v4 (Drastic Re-Tree)", "/product?v=4", True),
        ("v5 (Decoy Hijack)", "/product?v=5", True),
    ]
    
    print(f"{'Scenario':<25} | {'DOM-Only Scraped':<18} | {'DOM-Only Status':<15} | {'Full Scraped':<16} | {'Full Status'}")
    print("-" * 95)
    
    dom_successes = 0
    full_successes = 0
    
    caller_id_dom = "benchmark_dom.py:.price-tag"
    
    for name, path, expects_healed in scenarios:
        # Run DOM-only Scraper
        driver.get(url + path)
        text_dom = scrape_dom_only(driver, ".price-tag", caller_id_dom)
        
        # Run Full Scraper (requires fresh driver state / reload)
        driver.get(url + path)
        try:
            text_full = scrape_full(driver)
        except Exception:
            text_full = None
            
        # Verify correctness: we expect "$19.99"
        dom_ok = (text_dom == "$19.99")
        full_ok = (text_full == "$19.99")
        
        if dom_ok: dom_successes += 1
        if full_ok: full_successes += 1
        
        dom_status = "✅ PASS" if dom_ok else "❌ FAIL"
        full_status = "✅ PASS" if full_ok else "❌ FAIL"
        
        print(f"{name:<25} | {str(text_dom):<18} | {dom_status:<15} | {str(text_full):<16} | {full_status}")
        
    driver.quit()
    for db_p in [db_path_dom, db_path_full]:
        if os.path.exists(db_p):
            os.remove(db_p)
            
    print("=" * 80)
    print(f"LIVE TESTSITE BENCHMARK SUMMARY")
    print("=" * 80)
    print(f"DOM-Only Success: {dom_successes}/5 ({(dom_successes/5.0):.1%})")
    print(f"Full-Ranker Success: {full_successes}/5 ({(full_successes/5.0):.1%})")
    print(f"Net Visual/Blended Lift: {(full_successes - dom_successes)/5.0:+.1%}")
    print("=" * 80)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Run live browser tests against Flask Testsites")
    args = parser.parse_args()
    
    if args.live:
        run_live_benchmark()
    else:
        run_local_benchmark()
