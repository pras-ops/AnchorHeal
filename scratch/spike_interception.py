import inspect
import sys
import time

# --- Mock Classes to simulate Selenium and Playwright ---

class MockNoSuchElementException(Exception):
    pass

class MockTimeoutError(Exception):
    pass

# Mock Selenium
class MockWebElement:
    def __init__(self, tag_name, text, classes, rect):
        self.tag_name = tag_name
        self.text = text
        self.classes = classes
        self.rect = rect # {x, y, width, height}

    def click(self):
        print(f"MockWebElement: Clicked on {self.tag_name}.{'.'.join(self.classes)}")

    def find_element(self, by, selector):
        # Nested find mock
        if selector == ".nested-active":
            return MockWebElement("span", "Nested text", ["nested-active"], {"x": 100, "y": 150, "width": 50, "height": 20})
        raise MockNoSuchElementException(f"Cannot find element with selector: {selector}")

class MockWebDriver:
    def __init__(self, elements):
        self.elements = elements # dict mapping selector -> MockWebElement

    def find_element(self, by, selector):
        if selector in self.elements:
            return self.elements[selector]
        raise MockNoSuchElementException(f"Cannot find element with selector: {selector}")

# Mock Playwright
class MockLocator:
    def __init__(self, page, selector):
        self.page = page
        self.selector = selector

    def click(self):
        print(f"MockLocator: Performing click on selector: {self.selector}")
        # Actually perform the query to check if it exists
        el = self.page._query_selector_internal(self.selector)
        if not el:
            raise MockTimeoutError(f"Timeout waiting for locator: {self.selector}")
        el.click()

    def inner_text(self):
        print(f"MockLocator: Fetching inner_text for selector: {self.selector}")
        el = self.page._query_selector_internal(self.selector)
        if not el:
            raise MockTimeoutError(f"Timeout waiting for locator: {self.selector}")
        return el.text

class MockPlaywrightPage:
    def __init__(self, elements):
        self.elements = elements # dict mapping selector -> MockWebElement

    def _query_selector_internal(self, selector):
        return self.elements.get(selector, None)

    def query_selector(self, selector):
        el = self._query_selector_internal(selector)
        if el:
            return el
        return None

    def locator(self, selector):
        return MockLocator(self, selector)


# --- AnchorHeal Core Interception Logic ---

# In-memory anchor DB for spike verification
SPIKE_ANCHOR_DB = {}

def get_caller_id(selector):
    frame = inspect.currentframe()
    try:
        while frame:
            filename = frame.f_code.co_filename
            if "spike_interception" in filename and frame.f_code.co_name == "scrape_test":
                # Find the call site inside the user's scrape function
                lineno = frame.f_lineno
                return f"{filename}:{lineno}:{selector}"
            frame = frame.f_back
    finally:
        del frame
    return selector

class HealingProxy:
    def __init__(self, obj, driver_type):
        # Avoid infinite recursion by setting attributes directly in __dict__
        self.__dict__["_obj"] = obj
        self.__dict__["_driver_type"] = driver_type

    def __getattr__(self, name):
        obj = self.__dict__["_obj"]
        driver_type = self.__dict__["_driver_type"]
        attr = getattr(obj, name)

        if callable(attr):
            def wrapper(*args, **kwargs):
                # Intercept element queries
                if driver_type == "selenium" and name in ("find_element",):
                    selector = args[1] if len(args) > 1 else kwargs.get("value", args[0])
                    caller_id = get_caller_id(selector)
                    print(f"[Intercept] Selenium find_element: selector={selector}, caller_id={caller_id}")
                    try:
                        res = attr(*args, **kwargs)
                        # Store/Update anchor configuration for success
                        print(f"  [Store] Successfully located {selector}. Saving anchor features.")
                        SPIKE_ANCHOR_DB[caller_id] = {
                            "selector": selector,
                            "tag": res.tag_name,
                            "classes": res.classes,
                            "text": res.text,
                            "rect": res.rect
                        }
                        return HealingProxy(res, "selenium_element")
                    except MockNoSuchElementException as e:
                        print(f"  [Heal Triggered] Selenium find_element failed for selector: {selector}")
                        # Look up original anchor using caller_id
                        anchor = SPIKE_ANCHOR_DB.get(caller_id)
                        if anchor:
                            # Run healing (simulated ranker finding the new selector/element)
                            print(f"  [Heal Lookup] Found saved anchor info: {anchor}")
                            # Let's say we search the new DOM and find a match
                            healed_selector = ".new-price-button"
                            print(f"  [Heal Action] Healed selector to '{healed_selector}'")
                            # Call the method again with the healed selector
                            # Note: in selenium, the first arg is By.CSS_SELECTOR, the second is value
                            new_args = list(args)
                            if len(new_args) > 1:
                                new_args[1] = healed_selector
                            else:
                                if "value" in kwargs:
                                    kwargs["value"] = healed_selector
                                else:
                                    new_args[0] = healed_selector
                            healed_el = attr(*new_args, **kwargs)
                            return HealingProxy(healed_el, "selenium_element")
                        else:
                            raise e

                elif driver_type == "playwright" and name == "locator":
                    selector = args[0]
                    caller_id = get_caller_id(selector)
                    print(f"[Intercept] Playwright locator call: selector={selector}, caller_id={caller_id}")
                    # In Playwright, creation is lazy, so we always return a wrapped locator
                    res = attr(*args, **kwargs)
                    return HealingProxy(res, "playwright_locator")

                elif driver_type == "playwright_locator" and name in ("click", "inner_text"):
                    # We wrap the lazy action calls
                    selector = obj.selector
                    caller_id = get_caller_id(selector)
                    print(f"[Intercept] Playwright Locator Action '{name}': selector={selector}, caller_id={caller_id}")
                    try:
                        # Record anchor features if it works
                        res = attr(*args, **kwargs)
                        print(f"  [Store] Successfully executed action on Playwright locator '{selector}'.")
                        # (Normally we would capture DOM details from page context here)
                        SPIKE_ANCHOR_DB[caller_id] = {
                            "selector": selector,
                        }
                        return res
                    except MockTimeoutError as e:
                        print(f"  [Heal Triggered] Playwright locator action failed for selector: {selector}")
                        anchor = SPIKE_ANCHOR_DB.get(caller_id)
                        if anchor:
                            healed_selector = ".new-btn"
                            print(f"  [Heal Action] Healed selector to '{healed_selector}'")
                            # Resolve dynamic action by querying the page with the healed selector
                            new_locator = obj.page.locator(healed_selector)
                            # Invoke the action on the healed locator
                            action_method = getattr(new_locator, name)
                            return action_method(*args, **kwargs)
                        else:
                            raise e

                # Normal forwarding
                res = attr(*args, **kwargs)
                return res
            return wrapper
        return attr

    def __setattr__(self, name, value):
        obj = self.__dict__["_obj"]
        setattr(obj, name, value)


def heal(driver_type):
    def decorator(func):
        def wrapper(*args, **kwargs):
            # Inspect first arg and wrap if matches driver_type
            new_args = list(args)
            if len(new_args) > 0:
                print(f"[Decorator] Wrapping first argument {type(new_args[0]).__name__} with HealingProxy")
                new_args[0] = HealingProxy(new_args[0], driver_type)
            return func(*new_args, **kwargs)
        return wrapper
    return decorator


# --- Tier-1 Explicit Finder fallback prototype ---

class HealContext:
    def __init__(self, driver, driver_type):
        self.driver = driver
        self.driver_type = driver_type

    def find(self, field_name, selector):
        caller_id = f"tier1:{field_name}"
        print(f"[Tier-1 context] find: field={field_name}, selector={selector}")
        try:
            if self.driver_type == "selenium":
                el = self.driver.find_element("css selector", selector)
                SPIKE_ANCHOR_DB[caller_id] = {"selector": selector}
                return el
        except MockNoSuchElementException as e:
            print(f"  [Heal Triggered] Tier-1 find failed for field: {field_name}")
            anchor = SPIKE_ANCHOR_DB.get(caller_id)
            if anchor:
                healed_selector = ".new-price-button"
                print(f"  [Heal Action] Healed to '{healed_selector}'")
                return self.driver.find_element("css selector", healed_selector)
            raise e


# --- Test Runner Functions ---

def run_selenium_tier2_test():
    print("\n--- RUNNING SELENIUM TIER-2 PROXY TEST ---")
    # Setup initial mock page elements
    initial_elements = {
        ".price-btn": MockWebElement("button", "$100", ["price-btn"], {"x": 10, "y": 20, "width": 80, "height": 30})
    }
    driver = MockWebDriver(initial_elements)

    @heal(driver_type="selenium")
    def scrape_test(drv):
        # 1. First run: elements exist. We save anchor details.
        el = drv.find_element("css selector", ".price-btn")
        print(f"Scraped value: {el.text}")
        el.click()

    scrape_test(driver)

    # 2. Second run: class changed from .price-btn to .new-price-button.
    print("\n--- Changing Page Layout (Simulating Drift) ---")
    drifted_elements = {
        ".new-price-button": MockWebElement("button", "$100", ["new-price-button"], {"x": 12, "y": 22, "width": 80, "height": 30})
    }
    driver_drifted = MockWebDriver(drifted_elements)
    
    # We call the exact same scraping code (original selector '.price-btn')
    scrape_test(driver_drifted)


def run_playwright_tier2_test():
    print("\n--- RUNNING PLAYWRIGHT TIER-2 PROXY TEST ---")
    initial_elements = {
        ".btn": MockWebElement("button", "Submit", ["btn"], {"x": 50, "y": 50, "width": 100, "height": 40})
    }
    page = MockPlaywrightPage(initial_elements)

    @heal(driver_type="playwright")
    def scrape_test(pg):
        # 1. First run: selector works
        locator = pg.locator(".btn")
        locator.click()

    scrape_test(page)

    # 2. Page drifts: selector is now .new-btn
    print("\n--- Changing Page Layout (Simulating Drift) ---")
    drifted_elements = {
        ".new-btn": MockWebElement("button", "Submit", ["new-btn"], {"x": 52, "y": 52, "width": 100, "height": 40})
    }
    page_drifted = MockPlaywrightPage(drifted_elements)

    # Call scraping code again using original selector
    scrape_test(page_drifted)


def run_tier1_fallback_test():
    print("\n--- RUNNING TIER-1 FALLBACK TEST ---")
    initial_elements = {
        ".price-btn": MockWebElement("button", "$100", ["price-btn"], {"x": 10, "y": 20, "width": 80, "height": 30})
    }
    driver = MockWebDriver(initial_elements)

    def scrape_test(drv):
        ctx = HealContext(drv, "selenium")
        el = ctx.find("price_button", ".price-btn")
        print(f"Scraped via Tier-1: {el.text}")

    scrape_test(driver)

    # Drift page
    print("\n--- Changing Page Layout (Simulating Drift) ---")
    drifted_elements = {
        ".new-price-button": MockWebElement("button", "$100", ["new-price-button"], {"x": 12, "y": 22, "width": 80, "height": 30})
    }
    driver_drifted = MockWebDriver(drifted_elements)
    scrape_test(driver_drifted)


if __name__ == "__main__":
    run_selenium_tier2_test()
    run_playwright_tier2_test()
    run_tier1_fallback_test()
