"""Regression: text with regex metacharacters must score 1.0 against itself via capture path."""
import pytest
from anchorheal.models import Anchor
from anchorheal.ranker import text_similarity

METACHAR_TEXTS = ["$19.99", "In Stock (5)", "Buy Now! [50% off]", "item.name", "a+b=c"]

@pytest.mark.parametrize("txt", METACHAR_TEXTS)
def test_metachar_text_scores_perfectly(txt):
    # Anchor created via text→text_pattern auto-capture (the real runtime path)
    anchor = Anchor(caller_id="t", primary_selector=".x", tag="span", text=txt)
    cand = {"text": txt}
    assert text_similarity(cand, anchor) == pytest.approx(1.0)
