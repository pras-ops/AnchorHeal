import pytest
from anchorheal.models import Anchor
from anchorheal.ranker import (
    dom_similarity,
    visual_similarity,
    text_similarity,
    context_similarity,
    score_candidate,
    calculate_success_confidence,
    calculate_failure_confidence
)
from benchmark.benchmark import compute_ablation_attribution

def test_dom_similarity():
    anchor = Anchor(
        caller_id="test",
        primary_selector=".btn",
        tag="button",
        classes=["btn", "primary"],
        id_attr="submit",
        xpath="//button[@id='submit']"
    )
    
    # Exact match
    cand_exact = {
        "tag": "button",
        "classes": ["btn", "primary"],
        "id_attr": "submit",
        "xpath": "//button[@id='submit']"
    }
    assert dom_similarity(cand_exact, anchor) == pytest.approx(1.0)

    # Partial match
    cand_partial = {
        "tag": "button",
        "classes": ["btn"], # missing primary
        "id_attr": "other",
        "xpath": "//button"
    }
    score = dom_similarity(cand_partial, anchor)
    assert 0.4 <= score < 1.0

def test_visual_similarity():
    anchor = Anchor(
        caller_id="test",
        primary_selector=".btn",
        tag="button",
        rel_position={"x_pct": 0.5, "y_pct": 0.5}
    )

    # Missing rel_position
    assert visual_similarity({"tag": "button"}, anchor) is None

    # Exact position
    cand_exact = {"rel_position": {"x_pct": 0.5, "y_pct": 0.5}}
    assert visual_similarity(cand_exact, anchor) == pytest.approx(1.0)

    # Shifted position
    cand_shifted = {"rel_position": {"x_pct": 0.5, "y_pct": 0.7}}
    score = visual_similarity(cand_shifted, anchor)
    assert 0.0 < score < 1.0

def test_text_similarity():
    anchor = Anchor(
        caller_id="test",
        primary_selector=".btn",
        tag="button",
        text_pattern="Submit.*"
    )

    # Regex Match
    assert text_similarity({"text": "Submit Now"}, anchor) == pytest.approx(1.0)

    # Fuzzy match
    assert text_similarity({"text": "Submit"}, anchor) == pytest.approx(1.0)
    assert 0.0 < text_similarity({"text": "Sub"}, anchor) < 1.0
    assert text_similarity({"text": "Cancel"}, anchor) < 0.5

def test_weight_weight_renormalization():
    anchor = Anchor(
        caller_id="test",
        primary_selector=".btn",
        tag="button",
        classes=["btn"],
        xpath="",
        text_pattern="Click me",
        parent_chain=["div"],
        sibling_text=[]
    )

    # 1. With visual similarity (should use original weights: 0.45, 0.25, 0.20, 0.10)
    cand_with_vis = {
        "tag": "button",
        "classes": ["btn"],
        "id_attr": None,
        "xpath": "",
        "text": "Click me",
        "parent_chain": ["div"],
        "sibling_text": [],
        "rel_position": {"x_pct": 0.1, "y_pct": 0.1}
    }
    anchor.rel_position = {"x_pct": 0.1, "y_pct": 0.1}
    
    score1, sig1, raw1 = score_candidate(cand_with_vis, anchor)
    assert score1 == pytest.approx(1.0)
    assert sig1 == "dom" or sig1 == "visual"
    assert "visual" in raw1
    assert raw1["visual"] == pytest.approx(1.0)

    # 2. Without visual similarity (should renormalize weights to sum to 1.0)
    cand_no_vis = {
        "tag": "button",
        "classes": ["btn"],
        "id_attr": None,
        "xpath": "",
        "text": "Click me",
        "parent_chain": ["div"],
        "sibling_text": [],
        "rel_position": None # visual is missing!
    }
    score2, sig2, raw2 = score_candidate(cand_no_vis, anchor)
    assert score2 == pytest.approx(1.0)
    assert raw2["visual"] == 0.0

def test_confidence_math():
    # Success (EMA update: 0.7 * current + 0.3 * score)
    assert calculate_success_confidence(0.8, 0.9) == pytest.approx(0.8 * 0.7 + 0.9 * 0.3)
    assert calculate_success_confidence(0.99, 1.0) == pytest.approx(0.99 * 0.7 + 1.0 * 0.3)

    # Failure
    assert calculate_failure_confidence(0.8) == pytest.approx(0.8 * 0.85 - 0.05)
    assert calculate_failure_confidence(0.0) == pytest.approx(0.0)


def test_ablation_attribution_class_rename():
    # Setup scenario where class rename happens. Without visual, the pick would break.
    anchor = Anchor(
        caller_id="test",
        primary_selector=".price",
        tag="span",
        classes=["price"],
        text_pattern="\\$19.99",
        xpath="//div/span[1]",
        rel_position={"x_pct": 0.75, "y_pct": 0.35},
        bbox={"x": 750, "y": 350, "w": 60, "h": 20},
        viewport={"w": 1000, "h": 1000}
    )

    candidates = [
        # Candidate 0: Distractor (has original class '.price' but wrong text & wrong position)
        {
            "tag": "span", "classes": ["price"], "id_attr": None, "text": "Cart Items", "xpath": "//header/span",
            "rel_position": {"x_pct": 0.10, "y_pct": 0.05}, "bbox": {"x": 100, "y": 50, "w": 60, "h": 20},
            "parent_chain": ["header"], "sibling_text": []
        },
        # Candidate 1: True Target (renamed class 'amt', correct position, correct text, correct context)
        # Note: if we make text pattern very loose (no pattern) or drop text, visual will be decisive!
        # E.g. let's make text match identical for both, so text cannot help distinguish.
        {
            "tag": "span", "classes": ["amt"], "id_attr": None, "text": "Cart Items", "xpath": "//div/span[1]",
            "rel_position": {"x_pct": 0.76, "y_pct": 0.36}, "bbox": {"x": 760, "y": 360, "w": 60, "h": 20},
            "parent_chain": ["div"], "sibling_text": []
        }
    ]
    
    # We change anchor text pattern to "Cart Items" so text score is 1.0 for both candidates
    anchor.text_pattern = "Cart Items"

    # In this case:
    # Candidate 0 (Distractor): dom is high (matching class 'price'), text is high, context is low, visual is extremely low.
    # Candidate 1 (Target): dom is low (mismatching class 'amt'), text is high, context is high, visual is high.
    
    # Let's run ablation. Removing visual should break the correct pick!
    decisives = compute_ablation_attribution(candidates, anchor, target_idx=1)
    
    # Verify that visual was indeed decisive/necessary
    assert "visual" in decisives
