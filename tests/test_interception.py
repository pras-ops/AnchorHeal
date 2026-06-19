import pytest
import tempfile
import os
import datetime
from anchorheal.decorator import heal, HealingProxy, HealContext
from anchorheal.store import AnchorStore
from anchorheal.models import Anchor

# Mock Selenium classes for testing
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
    def __init__(self, elements):
        self.elements = elements
        for el in self.elements.values():
            el.parent = self

    def find_element(self, by, value):
        if value in self.elements:
            return self.elements[value]
        if value == "//span":
            for el in self.elements.values():
                if el.tag_name == "span":
                    return el
        raise Exception("NoSuchElementException")

    def find_elements(self, by, value):
        if value == "//*":
            return list(self.elements.values())
        return [self.elements[value]] if value in self.elements else []

    def execute_script(self, script, *args):
        # Mock simple JS executions
        if "getAbsoluteXPath" in script:
            el = args[0]
            tag = getattr(el, "tag_name", "span")
            return f"//{tag}"
        if "parentNode" in script:
            return []
        if "window.innerWidth" in script:
            return {"w": 1920, "h": 1080}
        return None

# Mock Playwright classes for testing
class DummyPlaywrightLocator:
    def __init__(self, page, selector):
        self.page = page
        self.selector = selector
        self._count = 1 if selector in page.elements or selector == "*" else 0

    @property
    def tag_name(self):
        el = self.page.elements.get(self.selector)
        return el.tag_name if el else "span"

    @property
    def classes(self):
        el = self.page.elements.get(self.selector)
        return el.classes if el else []

    @property
    def rect(self):
        el = self.page.elements.get(self.selector)
        return el.rect if el else {"x": 0, "y": 0, "width": 0, "height": 0}

    @property
    def text(self):
        el = self.page.elements.get(self.selector)
        return el.text if el else ""

    @property
    def xpath(self):
        el = self.page.elements.get(self.selector)
        tag = el.tag_name if el else "span"
        return f"//{tag}"

    def get_attribute(self, name):
        el = self.page.elements.get(self.selector)
        return el.get_attribute(name) if el else None

    def count(self):
        return self._count

    @property
    def first(self):
        return self

    def all(self):
        if self.selector == "*":
            return [DummyPlaywrightLocator(self.page, k) for k in self.page.elements.keys()]
        if self.selector in self.page.elements:
            return [self]
        return []

    def evaluate(self, script, *args):
        el = self.page.elements.get(self.selector)
        if not el:
            raise Exception("TimeoutError")
        if "tagName" in script:
            return el.tag_name
        if "getAbsoluteXPath" in script or "getPos" in script:
            return f"//{el.tag_name}"
        if "classList" in script:
            return el.classes
        if "parentNode" in script or "parents" in script:
            return []
        if "sibling" in script or "firstChild" in script:
            return []
        return ""

    def evaluate_all(self, script, *args):
        return None

    def inner_text(self):
        el = self.page.elements.get(self.selector)
        if not el:
            raise Exception("TimeoutError")
        return el.text

    def click(self):
        el = self.page.elements.get(self.selector)
        if not el:
            raise Exception("TimeoutError")

class DummyPlaywrightPage:
    def __init__(self, elements):
        self.elements = elements

    def locator(self, selector):
        return DummyPlaywrightLocator(self, selector)

@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp()
    yield path
    os.close(fd)
    if os.path.exists(path):
        os.remove(path)

def test_selenium_tier2_healing(temp_db):
    store = AnchorStore(db_path=temp_db)

    # 1. Run 1: Element '.price' is present. This registers the anchor dynamically!
    initial_elements = {
        ".price": DummyWebElement("span", "$100", ["price-text"], {"x": 960, "y": 540, "width": 50, "height": 20})
    }
    driver_initial = DummyWebDriver(initial_elements)

    @heal(driver_type="selenium", db_path=temp_db)
    def scrape_test(drv):
        el = drv.find_element("css selector", ".price")
        return el

    # Run pass 1
    el_initial = scrape_test(driver_initial)
    assert el_initial is not None
    assert el_initial.text == "$100"

    # Find the caller_id that was registered dynamically
    with store._get_conn() as conn:
        row = conn.execute("SELECT caller_id FROM anchors").fetchone()
        assert row is not None
        registered_cid = row["caller_id"]
        assert registered_cid == "test_interception.py:.price"

    # 2. Run 2: Element '.price' is missing, now is '.new-price' at similar position
    drifted_elements = {
        ".new-price": DummyWebElement("span", "$100", ["price-text"], {"x": 962, "y": 542, "width": 50, "height": 20})
    }
    driver_drifted = DummyWebDriver(drifted_elements)

    # Run pass 2 (the decorator will automatically heal)
    el_drifted = scrape_test(driver_drifted)
    assert el_drifted is not None
    assert el_drifted.text == "$100"
    
    # Check that heal event is logged in DB
    events = store.get_heal_events(registered_cid)
    assert len(events) == 1
    assert events[0].old_selector == ".price"
    assert events[0].new_selector == "//span"

def test_playwright_tier2_healing(temp_db):
    store = AnchorStore(db_path=temp_db)

    # 1. Run 1: Element '.price' is present.
    initial_elements = {
        ".price": DummyWebElement("span", "$100", ["price-text"], {"x": 960, "y": 540, "width": 50, "height": 20})
    }
    page_initial = DummyPlaywrightPage(initial_elements)

    @heal(driver_type="playwright", db_path=temp_db)
    def scrape_test(page):
        loc = page.locator(".price")
        return loc.inner_text()

    # Run pass 1
    val_initial = scrape_test(page_initial)
    assert val_initial == "$100"

    # Find caller_id
    with store._get_conn() as conn:
        row = conn.execute("SELECT caller_id FROM anchors").fetchone()
        assert row is not None
        registered_cid = row["caller_id"]
        assert registered_cid == "test_interception.py:.price"

    # 2. Run 2: Element '.price' is missing, now is '.new-price'
    drifted_elements = {
        ".new-price": DummyWebElement("span", "$100", ["price-text"], {"x": 962, "y": 542, "width": 50, "height": 20})
    }
    page_drifted = DummyPlaywrightPage(drifted_elements)

    # Run pass 2 (heals from cached anchor)
    val_drifted = scrape_test(page_drifted)
    assert val_drifted == "$100"

    # Check heal logs
    events = store.get_heal_events(registered_cid)
    assert len(events) == 1
    assert events[0].old_selector == ".price"
    assert events[0].new_selector == "//span"
