import pytest
import os
import tempfile
import datetime
from anchorheal.models import Anchor, HealEvent
from anchorheal.store import AnchorStore

@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp()
    yield path
    os.close(fd)
    if os.path.exists(path):
        os.remove(path)

def test_anchor_lifecycle(temp_db):
    store = AnchorStore(db_path=temp_db)
    
    anchor = Anchor(
        caller_id="test_file.py:10:.btn-submit",
        primary_selector=".btn-submit",
        confidence=1.0,
        tag="button",
        classes=["btn", "btn-primary"],
        id_attr="submit-id",
        text_pattern="Submit.*",
        parent_chain=["div.container", "form"],
        sibling_text=["Cancel"],
        xpath="//button[@id='submit-id']",
        rel_position={"x_pct": 0.5, "y_pct": 0.8},
        bbox={"x": 500, "y": 800, "w": 100, "h": 40},
        viewport={"w": 1000, "h": 1000},
        crop_32=b"fake_crop_32_data",
        crop_64=None
    )

    # Save
    store.save_anchor(anchor)

    # Get and Verify
    retrieved = store.get_anchor("test_file.py:10:.btn-submit")
    assert retrieved is not None
    assert retrieved.caller_id == anchor.caller_id
    assert retrieved.primary_selector == anchor.primary_selector
    assert retrieved.confidence == anchor.confidence
    assert retrieved.tag == anchor.tag
    assert retrieved.classes == anchor.classes
    assert retrieved.id_attr == anchor.id_attr
    assert retrieved.text_pattern == anchor.text_pattern
    assert retrieved.parent_chain == anchor.parent_chain
    assert retrieved.sibling_text == anchor.sibling_text
    assert retrieved.xpath == anchor.xpath
    assert retrieved.rel_position == anchor.rel_position
    assert retrieved.bbox == anchor.bbox
    assert retrieved.viewport == anchor.viewport
    assert retrieved.crop_32 == anchor.crop_32
    assert retrieved.crop_64 == anchor.crop_64

def test_confidence_history(temp_db):
    store = AnchorStore(db_path=temp_db)
    
    anchor = Anchor(
        caller_id="test.py:12:.item",
        primary_selector=".item",
        tag="div",
        classes=[],
        text_pattern="",
        parent_chain=[],
        sibling_text=[],
        xpath=""
    )
    store.save_anchor(anchor)

    t1 = datetime.datetime(2026, 6, 17, 10, 0, 0)
    t2 = datetime.datetime(2026, 6, 17, 10, 5, 0)

    store.log_confidence("test.py:12:.item", 0.95, timestamp=t1)
    store.log_confidence("test.py:12:.item", 0.90, timestamp=t2)

    history = store.get_confidence_history("test.py:12:.item")
    assert len(history) == 2
    assert history[0] == (t1, 0.95)
    assert history[1] == (t2, 0.90)

    # Check that main anchor's confidence is updated to the latest logged value
    updated_anchor = store.get_anchor("test.py:12:.item")
    assert updated_anchor.confidence == 0.90

def test_heal_events(temp_db):
    store = AnchorStore(db_path=temp_db)
    
    t = datetime.datetime(2026, 6, 17, 10, 15, 0)
    event = HealEvent(
        caller_id="test.py:15:.btn",
        timestamp=t,
        old_selector=".btn",
        new_selector=".btn-new",
        healed_features={"tag": "button", "classes": ["btn-new"]},
        confidence_before=0.8,
        confidence_after=0.86,
        primary_winning_signal="dom"
    )

    store.log_heal_event(event)

    events = store.get_heal_events("test.py:15:.btn")
    assert len(events) == 1
    assert events[0].caller_id == event.caller_id
    assert events[0].timestamp == event.timestamp
    assert events[0].old_selector == event.old_selector
    assert events[0].new_selector == event.new_selector
    assert events[0].healed_features == event.healed_features
    assert events[0].confidence_before == event.confidence_before
    assert events[0].confidence_after == event.confidence_after
    assert events[0].primary_winning_signal == event.primary_winning_signal
