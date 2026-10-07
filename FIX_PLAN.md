# AnchorHeal — Fix Plan (v3)

> [!NOTE]
> **COMPLETED & ARCHIVED**
> This fix plan has been fully implemented. For details of subsequent bug fixes and changes, see the [CHANGELOG.md](CHANGELOG.md). For genuine remaining/future work, see the [ROADMAP.md](ROADMAP.md).

*Turns the working week-4 prototype into something defensible and testable. Closes the four gaps
found in the evaluation, and adds a local **test website** so every fix can be run and seen, not
just asserted.*

Browser scope for demos/adapters: **all three** — BS4 (zero-dependency), Selenium, Playwright.

---

## 0. The four problems this plan closes

| # | Problem (from evaluation) | Where it lives today | Severity |
|---|---|---|---|
| 1 | **Confidence is binary** — every success logs `1.0`, so drift is invisible until after the break. The "predict before it breaks" product can't work. | `decorator.py:67`, `decorator.py:286` (log `1.0`); `ranker.py:122` (`calculate_success_confidence` ignores its `score` arg) | **Highest** |
| 2 | **Benchmark is self-deceiving** — claims "+12.5% visual lift" while attributing 0% of wins to visual; synthetic, internally contradictory. | `benchmark/benchmark.py`; `ranker.py:118` (winning-signal = argmax of *weighted* terms) | High |
| 3 | **Tier-2 healing won't survive a real page** — enumerates `//*` and does ~6 WebDriver round-trips per node (minutes per heal); Playwright action path crashes on invalid JS; BS4 candidate enumeration silently returns nothing. | `decorator.py:80`, `decorator.py:144`, `decorator.py:292`; `adapters/*` per-element extraction | High |
| 4 | **Positioning ignores the real market** — risk register worries about incumbents copying visual; the actual threat is LLM-extraction (Firecrawl/ScrapeGraphAI/AgentQL) and Scrapling's existing adaptive match. | `README.md`, plan §11 | Strategic (docs only) |

A fifth, cross-cutting deliverable: **a local test website** so 1–3 are demonstrable end-to-end.

---

## 1. The test website (build first — everything else is verified against it)

A small Flask app that serves the *same product page* and can deliberately drift, so you scrape it,
break it, and watch AnchorHeal recover.

### 1.1 Files
```
testsite/
  app.py                 # Flask app
  templates/
    index.html           # landing page: links to every scenario + one-line explanation
    product.html         # single product template; renders differently per drift
    dashboard.html       # observability health report rendered from anchorheal.db
  static/
    style.css
  README.md              # how to run
```

### 1.2 The page
Every rendered page exposes the **same five logical fields**, so a scraper can target them across all
drift states:

| field | baseline selector | baseline text |
|---|---|---|
| title | `h1.product-title` | "AnchorHeal Test Widget" |
| price | `.price-tag` | "$19.99" |
| add-to-cart | `#add-to-cart` | "Add to Cart" |
| stock | `.stock-badge` | "In Stock (5)" |
| description | `p.description` | "Product description goes here…" |

### 1.3 Two ways to drift

**A. Discrete scenarios — `/product?v=N`** (each mirrors a real failure mode):

| v | Name | What changes | Exercises |
|---|---|---|---|
| 1 | Baseline | clean markup | anchor capture |
| 2 | Class rename | `.price-tag` → `.product-amount`; same position + text | DOM rename + visual rescue |
| 3 | Layout shift | inject a promo banner; everything moves down ~15%; selectors unchanged | position tolerance |
| 4 | Drastic re-tree | tags + classes all change, wrapped in new `<div>`s; only text + approx position stable | the hard case — does the blend survive severe churn? |
| 5 | Decoy / ad hijack | a fake element steals the old `.price-tag` (wrong text, wrong place); real price renamed + moved | does the ranker resist being fooled? |

**B. Continuous erosion — `/product?drift=0..100`** (the early-warning demo):
As the number climbs, the price element **slides down the page** and its class **slowly mutates**
(`price-tag` → `price-tag-v2` → `amount`), until around `drift≈80` the original `.price-tag`
selector finally fails. Running `0, 25, 50, 75, 90` in sequence produces a *declining confidence
curve before the break* — the proof that Fix 1 works.

### 1.4 Routes
- `GET /` — landing page, links to every scenario.
- `GET /product?v=N` / `GET /product?drift=K` — the drifting page.
- `GET /dashboard` — reads `anchorheal.db`, renders the observability health report (per-field
  confidence, slope, status) as an HTML table so drift/risk is *visible*.

### 1.5 Why local, not live Amazon
Deterministic, no anti-bot/captcha flakiness, and you control exactly what drifts — so a passing heal
proves the logic, not luck. (The plan's §7 live-site benchmark stays a later, separate exercise.)

---

## 2. Fix 1 — Continuous confidence (highest value)

**Goal:** confidence erodes *while the selector still resolves*, so failure is predictable.

### 2.1 Behaviour change
- On a successful primary-selector find:
  - **First time** (no stored anchor): capture & freeze the baseline signals; log confidence `1.0`.
  - **Subsequent successes**: compute `live = score_candidate(found_features, baseline_anchor)` and
    log **that** to `confidence_history` — *do not* overwrite baseline signals.
  - **After a heal**: refresh the baseline to the healed element's signals (new golden snapshot).
- This makes `confidence_history` a real erosion curve (e.g. `1.0 → 0.91 → 0.78 → break+heal`).

### 2.2 Code touch points
- `decorator.py` — Tier-2 success branch (`~:57–67`), Tier-1 `HealContext.find` success branch
  (`~:277–286`): replace the hardcoded `log_confidence(cid, 1.0)` with the baseline-compare logic
  above; only `save_anchor` (baseline) on first capture / post-heal, not every run.
- `ranker.py` — `calculate_success_confidence(current, score)` currently ignores `score`
  (`:122–127`). Make it actually fold the live score in (EMA, e.g.
  `new = clamp(0.7*current + 0.3*score)`), or log the raw live score for a cleaner slope. Pick raw
  live score for the history series; keep the smoothed value as the stored `anchor.confidence`.

### 2.3 Note on false erosion
Frozen baseline + a field whose *text legitimately changes daily* would erode text similarity.
Mitigation already present: `text_pattern` is a regex, and position uses exponential tolerance. v1
documents this; a later EMA-refresh of baseline can smooth legitimate slow change.

---

## 3. Fix 2 — Honest benchmark + real attribution

**Goal:** stop reporting a number we can't defend; measure what *actually* changes the decision.

### 3.1 Per-signal scores
- `ranker.py` — have `score_candidate` also return the per-signal **raw** sub-scores
  (`{dom, visual, text, context}`), not just the argmax label. (Add a return field / small struct;
  keep the existing 2-tuple working for current callers or update them.)

### 3.2 Ablation attribution (replaces the misleading "winning signal")
- `benchmark/benchmark.py` — current "winning signal" is argmax of *weighted* terms, so DOM (weight
  0.45) almost always "wins" regardless of what mattered. Replace with **ablation**: from the full
  ranker, drop each signal one at a time; whichever signal, when removed, **breaks the correct
  pick**, is the one that was decisive. Report those counts. This is honest and will show whether
  visual ever truly decides.

### 3.3 Live mode
- Add `python3 benchmark/benchmark.py --live`: drive the **test site** through `v1→v5` with a real
  browser (Selenium and Playwright), record DOM-only vs full-ranker success on *real drift*, print
  the honest lift + ablation. The synthetic 8 stay as a fast unit-level sanity check (no headline
  number from them).

### 3.4 Expectation to document
The synthetic "Drastic DOM churn" case *fails even with the full ranker* — the flagship
"renamed-class-same-position" pitch only holds for mild drift. The README must not over-claim; the
live benchmark decides the story (plan §7 decision gate: >15% headline / 5–15% supporting / <5%
tiebreaker).

---

## 4. Fix 3 — Tier-2 viability + correctness (all three adapters)

**Goal:** a heal completes in well under a second on a real page, and the Playwright + BS4 paths
actually work.

### 4.1 Batch feature extraction (the big perf win)
Per-candidate extraction today is ~6 round-trips × thousands of nodes.
- `adapters/selenium.py` — one `execute_script` that walks a passed-in list of elements and returns
  an **array of feature dicts** (tag, classes, id, text, xpath, rect, parent_chain, sibling_text) in
  a single round-trip.
- `adapters/playwright.py` — same via one `page.evaluate` over `document.querySelectorAll(...)` (or
  `page.eval_on_selector_all`), returning the feature array in one call.
- `adapters/bs4.py` — pure Python, already in-process; just iterate `find_all(True)`.
- Add an adapter method like `extract_features_bulk(ctx, candidates) -> list[dict]` to the `Adapter`
  protocol in `adapters/base.py`.

### 4.2 Candidate pruning
Before scoring, shrink the candidate set:
- filter by **tag == anchor.tag** first (broaden only if zero matches);
- filter to candidates whose `rel_position` is within a **viewport region** around the stored bbox;
- cap at a max count (e.g. 300).
This keeps healing fast and reduces false matches.

### 4.3 Adapter-specific candidate enumeration
- `decorator.py` currently calls `query_all(ctx, "//*")` for every framework. BS4's `.select("//*")`
  is CSS, not XPath → silently returns `[]` (Tier-1 BS4 healing is dead today). Route enumeration
  through each adapter: Selenium/Playwright = all elements via the bulk JS; BS4 = `find_all(True)`.

### 4.4 Correctness fixes in `decorator.py`
- **Delete the broken Playwright line** (`obj.evaluate("el => el.getAttribute('class') or ''")`,
  `~:144`) — `or` is Python, invalid JS, crashes the path; the result is unused anyway.
- **Return the winning candidate directly** instead of re-querying by fragile absolute XPath
  (`~:118–127`, `~:207–210`). We already hold `best_cand`.
- **`caller_id` robustness** (`get_caller_id`, `~:15–28`): drop the line-number component (or make it
  optional) so editing the scraper file doesn't orphan every anchor below the edit. Trade-off:
  two identical selectors in one file would collide — document it; Tier-1 already uses a stable
  field name, which is preferable.

### 4.5 Add the missing Playwright test
There is **no** Playwright Tier-2 test today, which is exactly why the crashing line slipped through.
Add one (§6).

---

## 5. Fix 4 — Repositioning (docs only, no code)

- `README.md`:
  - Remove the unverified "+12.5%".
  - Frame the niche honestly: AnchorHeal is for **deterministic, high-volume, cost-/latency-sensitive
    scraping** where an LLM-per-page (Firecrawl / ScrapeGraphAI / AgentQL) is too slow/expensive, and
    where you want **drift early-warning** that selector-relocation libraries (e.g. Scrapling's
    adaptive match) don't give you.
  - Lead with **observability / "which scrapers are about to break"** as the headline, healing as the
    floor.
  - Add the test-site + demo run instructions.

---

## 6. Demos + tests

### 6.1 Runnable demos (`examples/`)
- `demo_bs4.py` — zero browser deps: `requests` → `/product?v=1` then `?v=2`, heal, print results +
  heal log. Instant.
- `demo_selenium.py` — headless Chrome (Selenium Manager auto-fetches driver), scrapes across
  versions, shows the **visual** signal contributing.
- `demo_playwright.py` — headless Chromium (`playwright install chromium`), same, proves the fixed
  Playwright path.
- `demo_drift.py` — runs the `?drift=` ramp (0→90) and prints the eroding confidence curve with a
  `⚠ PREDICTED BREAK` line *before* it actually fails. (The Fix-1 showcase.)

### 6.2 Tests (`tests/`)
- `test_continuous_confidence.py` *(new)* — simulate erosion across runs → `confidence_history`
  declines monotonically-ish; `predict_failures()` fires **before** the hard break.
- `test_interception.py` — add a **Playwright Tier-2** mock test; assert heal returns `best_cand`
  without a re-query; keep the existing Selenium test green.
- `test_ranker.py` — add an **ablation/attribution** test and an assertion that visual actually
  rescues the class-rename case; update for the new `score_candidate` return shape.
- Existing `test_store.py`, `test_observability.py` stay green.

---

## 7. Dependencies (`pyproject.toml`)
Add a richer dev/extras group:
```toml
[project.optional-dependencies]
dev = ["pytest>=7.0.0"]
testsite = ["flask>=3.0", "requests>=2.31"]
browsers = ["selenium>=4.15", "playwright>=1.40", "pillow>=10.0"]
```
Keep the core install lean (no browser deps forced on library users).

---

## 8. How you'll run it (acceptance)
```bash
pip install -e ".[dev,testsite,browsers]"
python3 testsite/app.py                 # http://localhost:5000  (browse the scenarios)

# second terminal:
python3 examples/demo_bs4.py            # instant, no browser
python3 examples/demo_drift.py          # watch confidence erode + early warning
playwright install chromium
python3 examples/demo_playwright.py     # visual signal, fixed PW path
python3 examples/demo_selenium.py       # visual signal, Selenium
python3 benchmark/benchmark.py --live   # honest lift + ablation on real drift
python3 -m pytest -q                    # all tests green
# open http://localhost:5000/dashboard  # see drift/risk visually
```

**Done = :** all demos run; `?drift=` shows confidence dropping *before* the break; benchmark prints
honest ablation (not the fake "winning signal"); a heal on the test site completes in <1s; Playwright
+ BS4 paths work; `pytest` green.

---

## 9. Build order
1. **Test website** (§1) — the substrate everything is verified against.
2. **Fix 1: continuous confidence** (§2) — highest value; demo via `?drift=`.
3. **Fix 3: Tier-2 viability** (§4) — batch extraction, pruning, Playwright/BS4 correctness.
4. **Fix 2: honest benchmark** (§3) — per-signal scores, ablation, `--live`.
5. **Demos + tests** (§6).
6. **Fix 4: README/repositioning** (§5).

## 10. Explicitly out of scope
- Crops / phash / OCR / CLIP (schema already supports; not needed for these fixes).
- GitHub Action auto-PR (plan §Phase 5 — later).
- Locator-chain (Tier-3) recursion.
- The 6–8 week live-site benchmark (separate exercise; this plan makes it *runnable*, not run).
- Business-model repositioning beyond doc copy (your call, not code).

## 11. File manifest
**New:** `testsite/` (app + 3 templates + css + README), `examples/{demo_bs4,demo_selenium,demo_playwright,demo_drift}.py`, `tests/test_continuous_confidence.py`, this `FIX_PLAN.md`.
**Edited:** `anchorheal/decorator.py`, `anchorheal/ranker.py`, `anchorheal/adapters/{base,selenium,playwright,bs4}.py`, `benchmark/benchmark.py`, `tests/{test_interception,test_ranker}.py`, `README.md`, `pyproject.toml`.
