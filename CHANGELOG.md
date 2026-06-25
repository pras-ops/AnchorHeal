# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Parametrized regression test `tests/test_text_metacharacter_scoring.py` checking correctness of scoring with regex metacharacters.
- Forward-looking `ROADMAP.md` documenting future work (interception scope expansion, real-site benchmark, CLIP/phash, unused-selector decay).

### Changed
- Unified text extraction to `textContent` via JS in `SeleniumElement.text` and `text_content()` in `PlaywrightElement.text` for consistency with bulk extraction.
- Escaped literal text using `re.escape()` when auto-capturing it as a pattern in `models.py` `map_text_to_pattern` validator.
- Added descriptive docstring to Playwright's `extract_features_bulk` explaining Page-level query constraints and fallback mechanics.
- Archived and retired stale `FIX_PLAN.md` documentation by adding an archive banner and removing stray XML tags.

### Removed
- Unused selector decay helper `calculate_decay_confidence` from `anchorheal/ranker.py` and its test assertions.
- Dead `get_crop` protocol slot and its adapter-level implementations from all elements and drivers.
- Unused PIL imports from `selenium.py` and `playwright.py`.

## [0.1.0] - 2026-06-22

Initial public release.

### Added
- Decorator-first `@heal` self-healing layer for BeautifulSoup, Selenium, and Playwright scrapers.
- Hybrid ranker blending DOM, visual/coordinate, text-pattern, and parent/sibling-context signals
  (`anchorheal/ranker.py`).
- Continuous-confidence drift tracking with early-warning failure prediction
  (`anchorheal/observability.py`, `ObservabilityManager.predict_failures`).
- SQLite-backed anchor store, confidence history, and heal-event log (`anchorheal/store.py`).
- Tier-1 explicit context finder fallback (`HealContext`).
- Local Flask test playground with discrete (`?v=N`) and continuous (`?drift=K`) drift scenarios,
  runnable demos, and a synthetic + live ablation benchmark.
- Packaging metadata, `LICENSE` (MIT), `py.typed` marker, and CI workflow.

### Changed
- Extracted the duplicated heal/decoy/record logic (previously copy-pasted across the Selenium,
  Playwright, BS4, and `HealContext` paths) into shared helpers in `anchorheal/_healing.py`;
  `decorator.py` now has a single source of truth for healing. Behavior is unchanged.
- Enabled SQLite WAL journaling and a busy-timeout so concurrent scrapers sharing a database file no
  longer fail on lock contention (`anchorheal/store.py`).

### Documentation
- Corrected the benchmark claim in the README: reported numbers are from the synthetic ablation
  benchmark (75% DOM-only → 87.5% full ranker) and the net lift comes from the signal *blend*, not
  from a standalone visual signal. Added a validation-status section noting synthetic-only coverage
  and the unrecovered "drastic DOM churn" case.

[Unreleased]: https://github.com/pras-ops/AnchorHeal/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/pras-ops/AnchorHeal/releases/tag/v0.1.0
