import pytest
import tempfile
import os
import datetime
from anchorheal.models import Anchor
from anchorheal.store import AnchorStore
from anchorheal.ranker import score_candidate, calculate_success_confidence
from anchorheal.observability import ObservabilityManager
from anchorheal.decorator import heal

# Mock Selenium class for test
class DummyWebElement:
    def __init__(self, tag_name, text, classes, rect=None):
        self.tag_name = tag_name
        self.text = text
        self.classes = classes
        self._rect = rect or {"x": 0, "y": 0, "width": 0, "height": 0}
        self.parent = None

    @property
    def rect(self):
        return self._rect

    def get_attribute(self, name):
        if name == "class":
            return " ".join(self.classes)
        return None

class DummyWebDriver:
    def __init__(self, element):
        self.element = element
        element.parent = self

    def find_element(self, by, value):
        return self.element

    def execute_script(self, script, *args):
        # Mock simple JS executions
        if "window.innerWidth" in script:
            return {"w": 1920, "h": 1080}
        return None

@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp()
    yield path
    os.close(fd)
    if os.path.exists(path):
        os.remove(path)

def test_continuous_confidence_erosion(temp_db):
    store = AnchorStore(db_path=temp_db)
    obs = ObservabilityManager(db_path=temp_db)
    
    # Define our decorated scraper
    @heal(driver_type="selenium", db_path=temp_db)
    def scrape_item(drv):
        return drv.find_element("css selector", ".item")

    # Run 1: clean baseline element
    el1 = DummyWebElement("div", "Hello", ["item-class"], {"x": 100, "y": 100, "width": 50, "height": 20})
    drv1 = DummyWebDriver(el1)
    scrape_item(drv1)

    # Verify initial confidence is 1.0
    with store._get_conn() as conn:
        row = conn.execute("SELECT caller_id, confidence FROM anchors").fetchone()
        assert row is not None
        cid = row["caller_id"]
        assert row["confidence"] == pytest.approx(1.0)

    # Run 2: slight drift (class changed slightly, position shifted slightly)
    el2 = DummyWebElement("div", "Hello", ["item-class-drifted"], {"x": 105, "y": 105, "width": 50, "height": 20})
    drv2 = DummyWebDriver(el2)
    
    # We update t2 to simulate passage of time or event sequence
    t2 = datetime.datetime.now(datetime.timezone.utc)
    # Perform success scrape, which should trigger continuous confidence scoring against baseline
    scrape_item(drv2)
    
    # Get current confidence, it must have eroded below 1.0 because of class/position drift!
    conf2 = store.get_anchor(cid).confidence
    assert conf2 < 1.0
    
    # Run 3: severe drift (approaching failure)
    el3 = DummyWebElement("div", "Hello", ["item-bad"], {"x": 200, "y": 200, "width": 50, "height": 20})
    drv3 = DummyWebDriver(el3)
    scrape_item(drv3)
    
    conf3 = store.get_anchor(cid).confidence
    assert conf3 < conf2

    # Check drift status and failure predictions
    drift = obs.get_selector_drift(cid)
    assert drift["slope"] < 0
    
    # Trigger log with very low confidence manually to verify risk prediction
    store.log_confidence(cid, 0.30, timestamp=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=1))
    predictions = obs.predict_failures()
    assert len(predictions) == 1
    assert predictions[0]["status"] == "critical_risk"
