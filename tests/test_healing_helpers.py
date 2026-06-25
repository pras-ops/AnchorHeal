"""Unit tests for the shared healing primitives in ``anchorheal._healing``.

These lock in the behavior that ``decorator.py`` used to inline four times: candidate relocation,
position pruning, decoy scoring, and heal recording — independent of any browser proxy.
"""

import os
import tempfile

import pytest

from anchorheal._healing import (
    HEAL_THRESHOLD,
    attempt_heal,
    best_decoy_score,
    find_best_candidate,
)
from anchorheal.models import Anchor
from anchorheal.store import AnchorStore


class FakeAdapter:
    """In-memory adapter: candidates are ``(obj, feature_dict)`` pairs, looked up by identity."""

    def __init__(self, candidates):
        self._candidates = candidates  # list[(obj, features)]

    def query_candidates(self, ctx, tag_name):
        if tag_name == "*":
            return [obj for obj, _f in self._candidates]
        return [obj for obj, f in self._candidates if f.get("tag") == tag_name]

    def extract_features_bulk(self, ctx, candidates):
        lookup = {id(obj): f for obj, f in self._candidates}
        return [lookup.get(id(c)) for c in candidates]


# Mirrors the benchmark "Class Rename / Position Preserved" scenario.
RENAME_ANCHOR = Anchor(
    caller_id="t", primary_selector=".price", tag="span", classes=["price"],
    text_pattern=r"\$19.99", xpath="//div/span[1]",
    rel_position={"x_pct": 0.75, "y_pct": 0.35},
)
DECOY = ("decoy_obj", {
    "tag": "span", "classes": ["price"], "id_attr": None, "text": "Cart Items",
    "xpath": "//header/span", "rel_position": {"x_pct": 0.10, "y_pct": 0.05},
    "parent_chain": ["header"], "sibling_text": [],
})
TARGET = ("target_obj", {
    "tag": "span", "classes": ["amt"], "id_attr": None, "text": "$19.99",
    "xpath": "//div/span[1]", "rel_position": {"x_pct": 0.76, "y_pct": 0.36},
    "parent_chain": ["div"], "sibling_text": ["Product details"],
})


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp()
    yield path
    os.close(fd)
    if os.path.exists(path):
        os.remove(path)


def test_find_best_candidate_picks_renamed_target_over_decoy():
    adapter = FakeAdapter([DECOY, TARGET])
    best_cand, best_score, _signal, best_features = find_best_candidate(adapter, None, RENAME_ANCHOR)
    assert best_cand == "target_obj"
    assert best_score >= HEAL_THRESHOLD
    assert best_features["text"] == "$19.99"


def test_position_pruning_drops_far_candidates():
    # The decoy sits >0.40 viewport-distance away from the anchor and must be pruned out entirely,
    # so even as the only candidate it cannot win.
    adapter = FakeAdapter([DECOY])
    best_cand, best_score, _signal, _features = find_best_candidate(adapter, None, RENAME_ANCHOR)
    assert best_cand is None
    assert best_score < HEAL_THRESHOLD


def test_best_decoy_score_high_when_strong_match_present():
    # Anchor without coordinates -> no pruning; an identical candidate should score near-perfect.
    anchor = Anchor(caller_id="t", primary_selector="#x", tag="span", classes=["badge"],
                    id_attr="x", text_pattern="hello", xpath="//span")
    twin = ("twin", {"tag": "span", "classes": ["badge"], "id_attr": "x", "text": "hello",
                     "xpath": "//span", "rel_position": None, "parent_chain": [], "sibling_text": []})
    adapter = FakeAdapter([twin])
    assert best_decoy_score(adapter, None, anchor) >= HEAL_THRESHOLD


def test_attempt_heal_records_event_on_success(temp_db):
    store = AnchorStore(db_path=temp_db)
    store.save_anchor(RENAME_ANCHOR)
    adapter = FakeAdapter([DECOY, TARGET])

    healed = attempt_heal(store, adapter, None, RENAME_ANCHOR.caller_id, ".price", RENAME_ANCHOR)
    assert healed is not None
    best_cand, _features = healed
    assert best_cand == "target_obj"

    events = store.get_heal_events(RENAME_ANCHOR.caller_id)
    assert len(events) == 1
    assert events[0].old_selector == ".price"
    assert events[0].new_selector == "//div/span[1]"


def test_attempt_heal_returns_none_and_decays_when_no_match(temp_db):
    store = AnchorStore(db_path=temp_db)
    store.save_anchor(RENAME_ANCHOR)
    # Only the far-away decoy is present -> pruned -> no heal.
    adapter = FakeAdapter([DECOY])

    healed = attempt_heal(store, adapter, None, RENAME_ANCHOR.caller_id, ".price", RENAME_ANCHOR)
    assert healed is None
    assert store.get_heal_events(RENAME_ANCHOR.caller_id) == []
    # Failure path decays confidence below the frozen baseline (1.0).
    history = store.get_confidence_history(RENAME_ANCHOR.caller_id)
    assert history and history[-1][1] < 1.0
