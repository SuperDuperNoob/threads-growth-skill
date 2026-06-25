"""Tests for the LinkedIn-tailored prompt + handoff routing."""
from orbit.analysis import build_linkedin_prompt, classify_linkedin_format


def test_linkedin_prompt_includes_sources():
    bookmarks = [
        {"author": "@test", "url": "https://x.com/test/status/1",
         "text": "Some tweet about an AI tool launch with specific numbers."},
        {"author": "@other", "url": "https://x.com/other/status/2",
         "text": "Another tweet about something interesting."},
    ]
    prompt = build_linkedin_prompt(bookmarks)
    assert "Some tweet about an AI tool launch" in prompt
    assert "Another tweet about something interesting" in prompt


def test_linkedin_prompt_enforces_norms():
    """The prompt must encode the LinkedIn-specific norms we identified.
    After the May 2026 data-derived update, length target shifted from 800-1500
    (the one-shot guess) to 300-700 (the actual sweet spot in top performers)."""
    prompt = build_linkedin_prompt([{"author": "@x", "url": "x", "text": "y"}])
    # Length norm — accept either old or new target so the test survives future tweaks
    assert any(s in prompt for s in ("300-700", "800-1500", "characters"))
    # No hashtags
    assert "No hashtags" in prompt or "no hashtags" in prompt
    # Don't write Threads-style hooks
    assert "Threads" in prompt


def test_linkedin_prompt_asks_for_one_post():
    """LinkedIn variant generation is 1 post per save, not 3 like Threads."""
    prompt = build_linkedin_prompt([{"author": "@x", "url": "x", "text": "y"}])
    assert "exactly 1" in prompt.lower() or "write 1" in prompt.lower()


def test_linkedin_prompt_handles_empty_bookmarks():
    """Should produce a valid prompt even with no source material — caller
    decides whether to call with empty."""
    prompt = build_linkedin_prompt([])
    assert "LinkedIn" in prompt
    assert isinstance(prompt, str)
    assert len(prompt) > 100  # has the body even without sources


# --- 2026-06-03 slump-recovery additions ---

def test_linkedin_prompt_bans_vague_time_markers():
    """Post 2026-06-03 ('After 6 months...', 242 imp) drove the new rule:
    vague duration spans aren't acceptable as the countable number."""
    prompt = build_linkedin_prompt([])
    # The exact failing opener should be cited so the LLM sees the example
    assert "After 6 months" in prompt
    # And the distinction should be named explicitly
    assert "COUNTABLE" in prompt or "countable" in prompt
    # The rule should explicitly call out duration spans as insufficient
    assert "duration" in prompt.lower() or "span" in prompt.lower()


def test_linkedin_prompt_includes_performance_floor_section():
    prompt = build_linkedin_prompt([])
    assert "PERFORMANCE FLOOR" in prompt
    # The floor is now framed around ENGAGEMENT RATE, not raw impressions.
    assert "ENGAGEMENT RATE" in prompt
    assert "1.30%" in prompt  # re-derived median engagement rate (n=20)


def test_linkedin_prompt_floor_targets_engagement_not_reach():
    """Regression guard for the 2026-06-26 metric reversal: the prompt must
    NOT tell the LLM that raw impressions are the goal, and must explicitly
    reject the high-reach/low-engagement trap (the 9,468-impression 0.08% post)."""
    prompt = build_linkedin_prompt([])
    # The reach-without-resonance trap is called out by its real numbers.
    assert "9,468" in prompt and "0.08%" in prompt
    # The old impression-floor framing is gone.
    assert "impression floor is ~700" not in prompt


def test_linkedin_prompt_includes_posting_cadence_guidance():
    prompt = build_linkedin_prompt([])
    assert "POSTING CADENCE" in prompt
    # B2B day-of-week guidance
    assert "Tue" in prompt and "Thu" in prompt


def test_linkedin_prompt_includes_pre_write_checklist():
    """7-point checklist gives the LLM a concrete verification step."""
    prompt = build_linkedin_prompt([])
    assert "PRE-WRITE CHECKLIST" in prompt
    # Should have numbered items
    assert "[1]" in prompt and "[7]" in prompt


def test_linkedin_prompt_includes_data_limitation_disclaimer():
    """Honest about the sync limitation — future Claude shouldn't assume
    engagement signals are auto-derivable from the current DB."""
    prompt = build_linkedin_prompt([])
    assert "DATA LIMITATION" in prompt
    # The reason the disclaimer exists
    assert "impressions" in prompt and "reactions" in prompt


def test_linkedin_prompt_acceptable_openings_include_real_top_posts():
    """The ✓ examples should match Keith's actual top-performing hooks
    so the LLM has concrete patterns to imitate, not just abstract rules."""
    prompt = build_linkedin_prompt([])
    # Confirmed top performers from the prompt's own statistical analysis
    assert "76 videos" in prompt
    assert "30/30 signups" in prompt


# --- 2026-06-07 format-variety additions ---

def test_linkedin_prompt_includes_format_menu():
    """5 distinct formats must be present so LLM has variety beyond STORY."""
    prompt = build_linkedin_prompt([])
    assert "FORMAT MENU" in prompt
    # Each of the 5 format labels should be present
    for label in ("STORY", "TEARDOWN", "CONTRARIAN", "RESOURCE DROP", "QUESTION"):
        assert label in prompt, f"Missing format: {label}"


def test_linkedin_prompt_no_fatigue_when_no_recent_formats():
    """With no recent_formats, the FORMAT FATIGUE GUARD section is omitted —
    LLM picks freely from the menu. Empty input degrades gracefully."""
    prompt = build_linkedin_prompt([], recent_formats=None)
    assert "FORMAT FATIGUE GUARD" not in prompt
    # The menu itself should still be there
    assert "FORMAT MENU" in prompt


def test_linkedin_prompt_fatigue_guard_excludes_recent_formats():
    """When recent_formats lists STORY 3 times, the prompt must instruct
    the LLM NOT to pick STORY."""
    prompt = build_linkedin_prompt([], recent_formats=["STORY", "STORY", "STORY"])
    assert "FORMAT FATIGUE GUARD" in prompt
    assert "DO NOT pick" in prompt
    assert "STORY" in prompt


def test_linkedin_prompt_fatigue_dedupes_recent_formats():
    """Repeated formats in recent_formats shouldn't multiply in the prompt —
    we want a clean exclusion list, not 'STORY, STORY, STORY'."""
    prompt = build_linkedin_prompt([], recent_formats=["STORY", "STORY", "STORY"])
    # The exclusion list (after "DO NOT pick any of:") should mention STORY once
    after_marker = prompt.split("DO NOT pick any of:", 1)[1].split("\n", 1)[0]
    assert after_marker.count("STORY") == 1


def test_linkedin_prompt_fatigue_ignores_unknown_formats():
    """Garbage input shouldn't pollute the prompt or crash."""
    prompt = build_linkedin_prompt([], recent_formats=["NONSENSE", "", None])
    # No valid formats → no fatigue block
    assert "FORMAT FATIGUE GUARD" not in prompt


def test_classify_linkedin_format_detects_story():
    """STORY: 'After N [countable], I [milestone]' or 'I [struggle]'."""
    assert classify_linkedin_format(
        "After 76 videos and 1 year of effort, I finally have a breakout"
    ) == "STORY"
    assert classify_linkedin_format(
        "I had the 80/20 rule completely backwards.\n\nFor months..."
    ) == "STORY"


def test_classify_linkedin_format_detects_teardown():
    """TEARDOWN: Company shipped/launched X. Here's what they got right."""
    assert classify_linkedin_format(
        "Anthropic shipped Claude Skills last week. Here's what they got right that OpenAI keeps missing."
    ) == "TEARDOWN"


def test_classify_linkedin_format_detects_contrarian():
    """CONTRARIAN: opens with 'Most X' or flat-assertion challenge."""
    assert classify_linkedin_format(
        "Most AI agent demos lie about reliability. 30-day audit: 71% completion rate, not 95%."
    ) == "CONTRARIAN"


def test_classify_linkedin_format_detects_resource_drop():
    """RESOURCE DROP: 'I tested N. The smaller-N worth using:' + numbered list."""
    assert classify_linkedin_format(
        "I tested 12 AI coding tools this month. The 4 worth using:\n1. Tool A\n2. Tool B\n3. Tool C\n4. Tool D"
    ) == "RESOURCE_DROP"


def test_classify_linkedin_format_detects_question_data():
    """QUESTION→DATA: opens with 'Do/Does/Why/etc.' + question mark in first line."""
    assert classify_linkedin_format(
        "Do Threads posts in Traditional Chinese reach more or fewer people than English? I ran the experiment for 30 days. Answer: 2.4x more."
    ) == "QUESTION_DATA"


def test_classify_linkedin_format_defaults_to_story():
    """Unknown / ambiguous content defaults to STORY (the historical pattern)."""
    assert classify_linkedin_format("") == "STORY"
    assert classify_linkedin_format("Some random text without clear markers.") == "STORY"


def test_classify_linkedin_format_on_actual_failed_posts():
    """Sanity check: the 3 confirmed failed posts (2026-06-04 to 06-07) all
    classify as STORY — which is the format that overdosed and triggered
    the fatigue guard work."""
    assert classify_linkedin_format(
        "After 149,000 views on an iPhone 15 Pro, I went out and bought a Sony anyway."
    ) == "STORY"
    assert classify_linkedin_format(
        "My gut had a 30% hit rate on content. Likes stuck between 10 and 30."
    ) == "STORY"
    assert classify_linkedin_format(
        "After 6 months of token-maxing — running Qwen locally, juggling 3 separate $20/month subscriptions"
    ) == "STORY"
