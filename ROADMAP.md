# AnchorHeal — Future Roadmap

This document outlines the genuine remaining work and strategic directions for AnchorHeal.

## 1. Interception Scope Expansion
Currently, the `HealingProxy` (in [decorator.py](anchorheal/decorator.py)) only intercepts `find_element` calls.
In real-world Selenium and Playwright test suites, elements are often queried in other ways:
- `find_elements` (plural) — iterating over lists of elements.
- `WebDriverWait` and `expected_conditions` (e.g. `visibility_of_element_located`, `presence_of_element_located`).
Expanding the proxy to intercept these calls is critical to make AnchorHeal transparently support production-grade test suites.

## 2. Real-Site Benchmark
Our current benchmarks (in [benchmark.py](benchmark/benchmark.py)) run against a local synthetic test site. To fully evaluate healing reliability, we need to run a multi-week benchmark tracking actual selector drift on dynamic external sites (e.g., e-commerce, SaaS dashboards).

## 3. Visual Embeddings (CLIP/phash)
The `Anchor` model has schema slots for `crop_32` and `crop_64` binary columns, but there is currently no runtime feature extracting or comparing visual crops using models like CLIP or perceptual hashes (phash). Adding this would complete the visual validation pillar.

## 4. Unused-Selector Decay
The `calculate_decay_confidence` math function was removed because the database schema did not track `last_used` timestamps, leaving the decay feature dead. Re-implementing decay will require:
1. Adding a `last_used` datetime column/field to the database and `Anchor` model.
2. A maintenance loop or trigger to regularly decay anchors that haven't been resolved or verified in a long time.
