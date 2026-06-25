# AnchorHeal

[![CI](https://github.com/pras-ops/AnchorHeal/actions/workflows/ci.yml/badge.svg)](https://github.com/pras-ops/AnchorHeal/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)

> **Status: experimental (v0.1).** Validated against a local synthetic test playground; real-site
> validation is still pending — see [Validation status](#validation-status) before relying on it in
> production.

**A drop-in, decorator-first drift early-warning and self-healing layer for any Python scraper.**

AnchorHeal's headline job is **observability**: it tracks a per-selector confidence curve so you can
see *which scrapers are about to break* before they actually do (`ObservabilityManager.predict_failures()`).
The **self-healing** is the floor underneath that — when a selector path finally breaks, AnchorHeal
relocates the moved element locally instead of crashing your run.

It is designed for **deterministic, high-volume, and cost/latency-sensitive scraping** where calling
an LLM API (like Firecrawl, ScrapeGraphAI, or AgentQL) for every page is too slow or expensive, and
where you want drift early-warning that pure selector-relocation libraries don't surface. Recovery
uses a hybrid ranking model blending DOM features, text patterns, parent/sibling context, and
visual/coordinate signals to locate moved elements when selector paths break.

See [CHANGELOG.md](CHANGELOG.md) for release notes and [LICENSE](LICENSE) (MIT).

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
On the 8 synthetic scenarios this reports **75.0% DOM-only → 87.5% full ranker (+12.5% net)**. The
lift comes from the signal *blend* (text/context/visual together), not from a standalone visual
signal — the ablation attribution shows visual is rarely the single decisive signal on its own.

### Run live browser benchmark:
Drives a headless browser through the Flask test playground and compares DOM-only matching against
the full hybrid ranker on real rendered drift, printing per-scenario recovery plus ablation
attribution. (This path requires a local browser and has not been run as part of the published
results — see [Validation status](#validation-status).)
```bash
python3 benchmark/benchmark.py --live
```

---

## Validation status

Be aware of exactly what has and hasn't been verified before depending on AnchorHeal:

- **Synthetic only.** The headline numbers come from the 8-scenario synthetic ablation benchmark and
  the local Flask test playground. There is **no real-world site benchmark** yet.
- **Not every drift is recoverable.** The full ranker does **not** recover the "Drastic DOM churn"
  scenario (tags, classes, and tree all change at once, leaving only text + approximate position) —
  the "renamed-class-same-position" recovery story holds for mild-to-moderate drift, not arbitrary
  restructuring.
- **No standalone visual lift is claimed.** Visual/coordinate signals help disambiguate as part of
  the blend; they are not independently decisive in most scenarios (see the ablation output).
- **Concurrency.** The SQLite store uses WAL journaling so multiple scrapers can share a database
  file, but heavy concurrent throughput has not been load-tested.

Running a real-site benchmark is the main open item before a production-readiness claim.
