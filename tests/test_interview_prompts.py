"""Tests for the interview prompt library."""
from orbit.interview_prompts import (
    CATEGORY_LABELS,
    PROMPTS,
    all_categories,
    prompts_for,
)


def test_all_categories_present():
    cats = all_categories()
    assert len(cats) >= 5
    assert "agent_diary" in cats
    assert "teaching_insight" in cats
    assert "tool_experiment" in cats
    assert "contrarian_take" in cats
    assert "workflow_insight" in cats


def test_each_category_has_at_least_three_prompts():
    """Need at least 3 to display a triplet without repeats."""
    for cat in all_categories():
        prompts = prompts_for(cat)
        assert len(prompts) >= 3, f"{cat} has only {len(prompts)} prompts"


def test_every_category_has_a_label():
    for cat in all_categories():
        assert cat in CATEGORY_LABELS, f"Missing label for {cat}"


def test_unknown_category_returns_empty():
    assert prompts_for("nonexistent") == []


def test_most_prompts_are_questions():
    """Most prompts should contain a question mark (? or ？) — they're meant to
    PULL content out of Keith. Allow a few compound prompts (question + format hint)."""
    total = 0
    questions = 0
    for cat in all_categories():
        for p in prompts_for(cat):
            total += 1
            if "？" in p or "?" in p:
                questions += 1
    assert questions / total >= 0.9, f"Only {questions}/{total} prompts contain a question mark"
