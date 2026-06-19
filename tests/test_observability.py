import pytest
import tempfile
import os
import datetime
from anchorheal.models import Anchor
from anchorheal.store import AnchorStore
from anchorheal.observability import ObservabilityManager

@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp()
    yield path
    os.close(fd)
    if os.path.exists(path):
        os.remove(path)

def test_drift_analysis(temp_db):
    store = AnchorStore(db_path=temp_db)
    obs = ObservabilityManager(db_path=temp_db)
    
    # 1. Test insufficient history
    cid = "test.py:10:.btn"
    anchor = Anchor(
        caller_id=cid, primary_selector=".btn", tag="button",
        classes=[], text_pattern="", parent_chain=[], sibling_text=[], xpath=""
    )
    store.save_anchor(anchor)
    
    drift = obs.get_selector_drift(cid)
    assert drift["status"] == "stable"
    assert "Insufficient" in drift["message"]

    # Log initial high confidence
    t1 = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=5)
    store.log_confidence(cid, 1.0, timestamp=t1)
    
    # Log decaying confidence
    t2 = datetime.datetime.now(datetime.timezone.utc)
    store.log_confidence(cid, 0.7, timestamp=t2)
    
    drift = obs.get_selector_drift(cid)
    assert drift["status"] == "decaying"
    assert drift["slope"] < 0
    
    # Log critical risk confidence
    store.log_confidence(cid, 0.35, timestamp=t2 + datetime.timedelta(seconds=1))
    drift = obs.get_selector_drift(cid)
    assert drift["status"] == "critical_risk"

def test_predict_failures(temp_db):
    store = AnchorStore(db_path=temp_db)
    obs = ObservabilityManager(db_path=temp_db)

    # Scraper 1: decaying
    c1 = "s1.py:10:.item"
    store.save_anchor(Anchor(caller_id=c1, primary_selector=".item", tag="div", classes=[], text_pattern="", parent_chain=[], sibling_text=[], xpath=""))
    store.log_confidence(c1, 1.0, timestamp=datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=2))
    store.log_confidence(c1, 0.8, timestamp=datetime.datetime.now(datetime.timezone.utc))

    # Scraper 2: stable
    c2 = "s2.py:10:.item"
    store.save_anchor(Anchor(caller_id=c2, primary_selector=".item", tag="div", classes=[], text_pattern="", parent_chain=[], sibling_text=[], xpath=""))
    store.log_confidence(c2, 1.0, timestamp=datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=2))
    store.log_confidence(c2, 1.0, timestamp=datetime.datetime.now(datetime.timezone.utc))

    failures = obs.predict_failures()
    assert len(failures) == 1
    assert failures[0]["caller_id"] == c1

def test_health_report(temp_db):
    store = AnchorStore(db_path=temp_db)
    obs = ObservabilityManager(db_path=temp_db)

    # Insert two anchors
    store.save_anchor(Anchor(caller_id="c1", primary_selector=".a", tag="div", classes=[], text_pattern="", parent_chain=[], sibling_text=[], xpath=""))
    store.save_anchor(Anchor(caller_id="c2", primary_selector=".b", tag="span", classes=[], text_pattern="", parent_chain=[], sibling_text=[], xpath=""))

    report = obs.get_health_report()
    assert report["total_anchors"] == 2
    assert report["average_confidence"] == pytest.approx(1.0)
    assert len(report["anchors"]) == 2
