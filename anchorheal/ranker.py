import math
import re
from typing import Dict, Any, Optional, Tuple
from rapidfuzz import fuzz
from .models import Anchor

def dom_similarity(cand: Dict[str, Any], anchor: Anchor) -> float:
    # Tag match (weight 0.4)
    tag_score = 1.0 if cand["tag"] == anchor.tag else 0.0
    
    # Class list overlap (Jaccard similarity, weight 0.3)
    cand_classes = set(cand.get("classes") or [])
    anchor_classes = set(anchor.classes or [])
    union_len = len(cand_classes | anchor_classes)
    class_score = len(cand_classes & anchor_classes) / union_len if union_len > 0 else (1.0 if not anchor_classes else 0.0)
    
    # ID attribute match (weight 0.2)
    cand_id = cand.get("id_attr")
    id_score = 1.0 if cand_id == anchor.id_attr else (0.0 if (cand_id or anchor.id_attr) else 1.0)
    
    # XPath fuzzy match (weight 0.1)
    xpath_score = fuzz.ratio(cand.get("xpath") or "", anchor.xpath or "") / 100.0
    
    return 0.4 * tag_score + 0.3 * class_score + 0.2 * id_score + 0.1 * xpath_score

def visual_similarity(cand: Dict[str, Any], anchor: Anchor) -> Optional[float]:
    if not cand.get("rel_position") or not anchor.rel_position:
        return None
    
    c_pos = cand["rel_position"]
    a_pos = anchor.rel_position
    
    # Ensure keys exist
    if "x_pct" not in c_pos or "y_pct" not in c_pos or "x_pct" not in a_pos or "y_pct" not in a_pos:
        return None
        
    dx = c_pos["x_pct"] - a_pos["x_pct"]
    dy = c_pos["y_pct"] - a_pos["y_pct"]
    dist = math.sqrt(dx*dx + dy*dy)
    # Exponential decay to scale distance: dist=0 -> 1.0, dist=0.2 -> ~0.36
    return math.exp(-5.0 * dist)

def text_similarity(cand: Dict[str, Any], anchor: Anchor) -> float:
    cand_text = cand.get("text") or ""
    anchor_pattern = anchor.text_pattern or ""
    if not anchor_pattern:
        return 1.0 if not cand_text else 0.5
        
    # Attempt regex first
    try:
        if re.search(anchor_pattern, cand_text):
            return 1.0
    except Exception:
        pass
        
    # Fallback to fuzzy ratio
    return fuzz.ratio(cand_text, anchor_pattern) / 100.0

def context_similarity(cand: Dict[str, Any], anchor: Anchor) -> float:
    # Parent chain overlap
    cand_parents = set(cand.get("parent_chain") or [])
    anchor_parents = set(anchor.parent_chain or [])
    union_p = len(cand_parents | anchor_parents)
    parent_score = len(cand_parents & anchor_parents) / union_p if union_p > 0 else 1.0
    
    # Sibling text overlap
    cand_siblings = set(cand.get("sibling_text") or [])
    anchor_siblings = set(anchor.sibling_text or [])
    union_s = len(cand_siblings | anchor_siblings)
    sibling_score = len(cand_siblings & anchor_siblings) / union_s if union_s > 0 else 1.0
    
    return 0.5 * parent_score + 0.5 * sibling_score

def score_candidate(
    cand: Dict[str, Any], 
    anchor: Anchor, 
    weights: Optional[Dict[str, float]] = None
) -> Tuple[float, str, Dict[str, float]]:
    """
    Computes a unified score [0.0, 1.0] for a candidate element against a saved Anchor.
    If visual similarity is unavailable (None), renormalizes remaining weights so they sum to 1.0.
    """
    if weights is None:
        weights = {"dom": 0.45, "visual": 0.25, "text": 0.20, "context": 0.10}
        
    s_dom = dom_similarity(cand, anchor)
    s_visual = visual_similarity(cand, anchor)
    s_text = text_similarity(cand, anchor)
    s_context = context_similarity(cand, anchor)
    
    raw_scores = {
        "dom": s_dom,
        "visual": s_visual if s_visual is not None else 0.0,
        "text": s_text,
        "context": s_context
    }
    
    if s_visual is None:
        # Renormalize weights for DOM, text, context to sum to 1.0
        w_sum = weights["dom"] + weights["text"] + weights["context"]
        w_dom = weights["dom"] / w_sum
        w_text = weights["text"] / w_sum
        w_context = weights["context"] / w_sum
        
        score = w_dom * s_dom + w_text * s_text + w_context * s_context
        
        scores = {
            "dom": w_dom * s_dom,
            "text": w_text * s_text,
            "context": w_context * s_context
        }
        winning_signal = max(scores, key=scores.get)
    else:
        score = (weights["dom"] * s_dom + 
                 weights["visual"] * s_visual + 
                 weights["text"] * s_text + 
                 weights["context"] * s_context)
                 
        scores = {
            "dom": weights["dom"] * s_dom,
            "visual": weights["visual"] * s_visual,
            "text": weights["text"] * s_text,
            "context": weights["context"] * s_context
        }
        winning_signal = max(scores, key=scores.get)
        
    return score, winning_signal, raw_scores

def calculate_success_confidence(current_confidence: float, score: float) -> float:
    # Fold live score into current confidence using an EMA (0.7 current + 0.3 score)
    return float(max(0.0, min(1.0, 0.7 * current_confidence + 0.3 * score)))

def calculate_failure_confidence(current_confidence: float) -> float:
    # failure: score = max(0.0, score * 0.85 - 0.05)
    return max(0.0, current_confidence * 0.85 - 0.05)
