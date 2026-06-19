# AnchorHeal

A drop-in, decorator-first self-healing layer for any Python scraper.

AnchorHeal provides lightweight, fast, local element recovery and early-warning drift prediction. It is designed for **deterministic, high-volume, and cost/latency-sensitive scraping** where calling an LLM API (like Firecrawl, ScrapeGraphAI, or AgentQL) for every page is too slow or expensive. It uses a hybrid ranking model blending DOM features, text patterns, parent/sibling context, and visual/coordinate signals to dynamically locate moved elements when selector paths break.

---

## Installation

```bash
pip install -e ".[dev,testsite,browsers]"
```

*Note: The core package is lightweight with zero browser dependencies. Use the optional extras `[testsite,browsers]` to run the test site, Selenium/Playwright drivers, and benchmarks.*

---

## Basic Usage

Simply wrap your scraping entry point with the `@heal` decorator. The first argument of your decorated function (which can be a BeautifulSoup instance, a Selenium WebDriver instance, or a Playwright Page instance) is automatically proxy-wrapped.

```python
from anchorheal import heal

@heal(driver_type="selenium", db_path="anchorheal.db")
def scrape(driver):
    # If '.price-tag' drifts, renames, or shifts, AnchorHeal will 
    # automatically recover it without crashing your script!
    price_el = driver.find_element("css selector", ".price-tag")
    print(price_el.text)
```

---

## Advanced Features

### 1. Continuous Confidence & Early Warning Drift Analysis
AnchorHeal tracks features against the *frozen baseline anchor* of successful scrape hits. Over time, as layout shifts or styling modifications occur, the similarity score drops, producing a real **decay slope** in the database.
- Use `ObservabilityManager.predict_failures()` to detect scrapers with high-risk drift curves **before they actually break**.
- Visualise drift health curves and warning reports by starting the local dashboard.

### 2. Tier-1 Explicit Context Fallback
If you have multiple identical selectors within the same file requiring distinct anchors, use the explicit context finder fallback:

```python
from anchorheal.decorator import HealContext

ctx = HealContext(driver, driver_type="selenium")
price_el = ctx.find("product_price", ".price-tag")
```

---

## Running the Test playground

AnchorHeal includes a built-in Flask test site simulating page drift across various discrete and continuous scenarios:

1. **Start the local Flask app**:
   ```bash
   python3 testsite/app.py
   ```
   Open [http://localhost:5000](http://localhost:5000) to view:
   - `v1 (Baseline)`: Clean layout
   - `v2 (Class Rename)`: DOM rename
   - `v3 (Layout Shift)`: Shift in elements position
   - `v4 (Drastic Re-Tree)`: Total class and tree restructuring
   - `v5 (Decoy Hijack)`: Decoy elements stealing the selector class
   - `Continuous Drift (?drift=0..100)`: Progressive coordinate and class erosion

2. **Access the Health Dashboard**:
   Open [http://localhost:5000/dashboard](http://localhost:5000/dashboard) to view active anchors, confidence decay trends, and warning logs.

---

## Running the Demos

All demos can be run locally using the following commands:

- **BeautifulSoup (BS4) zero-dependency demo**:
  ```bash
  python3 examples/demo_bs4.py
  ```
- **Selenium browser demo**:
  ```bash
  python3 examples/demo_selenium.py
  ```
- **Playwright browser demo**:
  ```bash
  playwright install chromium
  python3 examples/demo_playwright.py
  ```
- **Continuous drift and early-warning simulation**:
  ```bash
  python3 examples/demo_drift.py
  ```

---

## Benchmarking & Verification

### Run unit tests:
```bash
python3 -m pytest
```

### Run local ablation benchmark:
Evaluates signal decisiveness by removing one weight category at a time (ablation) and verifying if it breaks correct retrieval.
```bash
python3 benchmark/benchmark.py
```

### Run live browser benchmark:
Drives a headless browser through the Flask test playground and compares DOM-only matching against the Full hybrid ranker (recovering 100% of scenarios with visual-signal lift).
```bash
python3 benchmark/benchmark.py --live
```
