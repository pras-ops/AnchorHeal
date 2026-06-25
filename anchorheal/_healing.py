"""Shared healing primitives used by every framework path in :mod:`anchorheal.decorator`.

The Selenium, Playwright, BS4, and ``HealContext`` interception paths all repeat the exact same
"score the live element / detect a decoy / relocate the moved element / record the heal" logic. That
logic lives here once so there is a single source of truth; the decorator keeps only the
framework-specific glue (which object is the candidate context, and how to wrap the result).

All helpers are behaviour-preserving extractions of what the decorator used to inline.
"""

import datetime
import math
from typing import Any, Dict, Optional, Tuple

from .models import Anchor, HealEvent
from .ranker import (
    calculate_failure_confidence,
    calculate_success_confidence,
    score_candidate,
)
from .store import AnchorStore

# Threshold score above which we accept a healed candidate / consider a decoy "real".
HEAL_THRESHOLD = 0.60

# Candidates further than this (in normalized viewport distance) from the stored anchor are pruned.
_MAX_POSITION_DIST = 0.40
# Hard cap on the number of nearest candidates scored during a heal.
_MAX_CANDIDATES = 300


def _position_distance(anchor: Anchor, features: Dict[str, Any]) -> Optional[float]:
    """Normalized viewport distance between an anchor and a candidate, or ``None`` if either lacks
    coordinates (e.g. BS4, which has no layout)."""
    if anchor.rel_position and features.get("rel_position"):
        dx = anchor.rel_position["x_pct"] - features["rel_position"]["x_pct"]
        dy = anchor.rel_position["y_pct"] - features["rel_position"]["y_pct"]
        return math.sqrt(dx * dx + dy * dy)
    return None


def find_best_candidate(
    adapter: Any, ctx: Any, anchor: Anchor
) -> Tuple[Optional[Any], float, str, Dict[str, Any]]:
    """Relocate the moved element: enumerate candidates, position-prune, score, return the best.

    Returns ``(best_candidate, best_score, winning_signal, best_features)``. ``best_candidate`` is the
    raw framework element/locator (never wrapped) so the caller decides how to surface it.
    """
    tag = anchor.tag or "*"
    candidates = adapter.query_candidates(ctx, tag)
    if not candidates:
        candidates = adapter.query_candidates(ctx, "*")

    features_list = adapter.extract_features_bulk(ctx, candidates)

    # Prune by proximity to the stored anchor (no-op for layout-less adapters), nearest first.
    pruned = []
    for i, f in enumerate(features_list):
        if not f:
            continue
        dist = _position_distance(anchor, f)
        if dist is not None and dist > _MAX_POSITION_DIST:
            continue
        pruned.append((candidates[i], f, dist if dist is not None else 0.0))

    pruned.sort(key=lambda x: x[2])
    pruned = pruned[:_MAX_CANDIDATES]

    best_cand: Optional[Any] = None
    best_score = -1.0
    best_signal = "dom"
    best_features: Dict[str, Any] = {}
    for cand_el, f, _dist in pruned:
        score, signal, _ = score_candidate(f, anchor)
        if score > best_score:
            best_score = score
            best_cand = cand_el
            best_signal = signal
            best_features = f

    return best_cand, best_score, best_signal, best_features


def best_decoy_score(adapter: Any, ctx: Any, anchor: Anchor) -> float:
    """Highest candidate score on the page, used on the success path to detect a decoy that has
    stolen the original selector. Same scoring/pruning as :func:`find_best_candidate`, score only."""
    tag = anchor.tag or "*"
    candidates = adapter.query_candidates(ctx, tag)
    if not candidates:
        candidates = adapter.query_candidates(ctx, "*")

    features_list = adapter.extract_features_bulk(ctx, candidates)

    best = -1.0
    for f in features_list:
        if not f:
            continue
        dist = _position_distance(anchor, f)
        if dist is not None and dist > _MAX_POSITION_DIST:
            continue
        cand_score, _, _ = score_candidate(f, anchor)
        if cand_score > best:
            best = cand_score
    return best


def record_heal(
    store: AnchorStore,
    cid: str,
    selector: str,
    anchor: Anchor,
    best_score: float,
    best_features: Dict[str, Any],
    best_signal: str,
) -> float:
    """Refresh the baseline anchor to the healed element, log the heal event and new confidence.
    Returns the post-heal confidence."""
    before_conf = anchor.confidence
    after_conf = calculate_success_confidence(before_conf, best_score)

    healed_anchor = Anchor(
        caller_id=cid,
        primary_selector=selector,
        confidence=after_conf,
        **best_features,
    )
    store.save_anchor(healed_anchor)

    event = HealEvent(
        caller_id=cid,
        timestamp=datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None),
        old_selector=selector,
        new_selector=best_features.get("xpath") or selector,
        healed_features=best_features,
        confidence_before=before_conf,
        confidence_after=after_conf,
        primary_winning_signal=best_signal,
    )
    store.log_heal_event(event)
    store.log_confidence(cid, after_conf)
    return after_conf


def update_confidence_on_success(
    store: AnchorStore,
    adapter: Any,
    ctx: Any,
    cid: str,
    selector: str,
    features: Dict[str, Any],
) -> None:
    """Handle a successful primary-selector resolution.

    First time: freeze the baseline anchor and log confidence ``1.0``. Subsequent times: fold the
    live match score into a continuous confidence curve (without overwriting the baseline). If the
    live score drops below the heal threshold *and* a significantly better candidate exists on the
    page, raise to signal a decoy so the caller's heal path takes over.
    """
    anchor = store.get_anchor(cid)
    if anchor is None:
        anchor = Anchor(caller_id=cid, primary_selector=selector, confidence=1.0, **features)
        store.save_anchor(anchor)
        store.log_confidence(cid, 1.0)
        return

    score, _, _ = score_candidate(features, anchor)
    new_conf = calculate_success_confidence(anchor.confidence, score)
    store.log_confidence(cid, new_conf)

    if score < HEAL_THRESHOLD:
        best_cand_score = best_decoy_score(adapter, ctx, anchor)
        if best_cand_score > score + 0.15 and best_cand_score >= HEAL_THRESHOLD:
            raise Exception(
                f"Decoy element detected (score {score:.2f} < threshold {HEAL_THRESHOLD} "
                f"and better candidate score {best_cand_score:.2f} exists)"
            )


def attempt_heal(
    store: AnchorStore,
    adapter: Any,
    ctx: Any,
    cid: str,
    selector: str,
    anchor: Anchor,
) -> Optional[Tuple[Any, Dict[str, Any]]]:
    """Try to relocate a broken selector. On success (best score >= threshold) record the heal and
    return ``(best_candidate, best_features)``. On failure, decay confidence and return ``None``."""
    best_cand, best_score, best_signal, best_features = find_best_candidate(adapter, ctx, anchor)
    if best_score >= HEAL_THRESHOLD and best_cand is not None:
        record_heal(store, cid, selector, anchor, best_score, best_features, best_signal)
        return best_cand, best_features
    store.log_confidence(cid, calculate_failure_confidence(anchor.confidence))
    return None
