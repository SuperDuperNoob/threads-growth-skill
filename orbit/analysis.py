from __future__ import annotations
from typing import Any


def extract_top_patterns(posts: list[dict[str, Any]], top_n: int = 10) -> list[dict[str, Any]]:
    scored = []
    for p in posts:
        views = p.get("views", 0) or 0
        likes = p.get("likes", 0) or 0
        scored.append({
            **p,
            "like_rate": round(likes / views * 100, 2) if views else 0.0,
        })
    return sorted(scored, key=lambda x: x["views"], reverse=True)[:top_n]


def build_pattern_prompt(
    top_posts: list[dict[str, Any]],
    bookmarks: list[dict[str, Any]],
    recent_topics: list[str] | None = None,
    recent_performance: dict[str, Any] | None = None,
    *,
    count: int = 3,
) -> str:
    examples = "\n\n---\n\n".join(
        f"[{p['views']:,} views, {p['like_rate']}% like rate]\n{p['content']}"
        for p in top_posts[:5]
    )
    # Show enough sources to cover the requested draft count plus headroom
    # for the prompt's "pick the strongest source" judgment.
    source_limit = max(10, count + 4)
    sources = "\n\n---\n\n".join(
        f"Author: {b['author']}\nURL: {b['url']}\n{b['text']}"
        for b in bookmarks[:source_limit]
    )
    recent_section = "\n".join(f"- {t}" for t in (recent_topics or [])[:5]) or "(none — first post in this batch)"
    performance_section = _format_recent_performance(recent_performance)
    diversity_plan = _format_threads_diversity_plan(count)
    return f"""You are a Threads content writer. Your job is to write {count} Threads posts for Keith.

Keith's writing style — learned from his TOP PERFORMING posts:

{examples}

HARD CONSTRAINTS — every one of his top-10 posts follows these. Drafts that miss these underperform 10-50x.

OPENING HOOK — pick from these templates, weighted by LIKE RATE (refreshed 2026-06-19 after a like-rate collapse; views ≠ engagement):
  (a) "有人 [verb-ed] + named product" / "Someone just [verb-ed]"  — TIER 1 AND THE STRONGEST SIGNAL IN THE ACCOUNT. Refreshed 2026-08-02 (n=217): 有人-hook posts have a MEDIAN 5,807 views vs 2,916 for Brand-verb — nearly 2x. Of the TOP 20 posts, 60% open with 有人; of the BOTTOM 20, 0% do. The new all-time #1 (202k, Codex cyber-girlfriend) opens 有人. DEFAULT to this hook. But ONLY when paired with a distinctive named tool AND a payoff. Winners: "有人剛剛開源了整個排程平台 (Cal.com fork)" 1.48%, "有人開源了完全跑在瀏覽器的 AI 圖片工具 (Removerized)" 1.81%. The verb alone is not enough — see PAYOFF GATE below.
  (b) "[BrandName] [verb-ed]" — TIER 1 for VIEWS, but the #1 cause of the 2026-06-19 like-rate collapse. Bare "[Brand] 剛推出/開源了 [Y]" announcements scored 0–0.06% like rate (Stripe, Codex, MiMo, AMD, NotebookLM, Copilot, DiffusionGemma — all dead). Use (b) ONLY if it clears the PAYOFF GATE. A brand name + a feature is NOT a post.
  (c) "一個 [thing] [milestone]" — TIER 2. Use only for genuine GitHub-trending / leaderboard moments (LiteParse 1.47%).
  (d) "你[有沒有/為什麼] [pain]?" — DEPRECATED. Diagnosed 2026-06-03 slump. Default: skip (d) entirely.

Prefer (a) with a named tool + payoff. Use (b) ONLY through the PAYOFF GATE. Use (c) for milestones. Skip (d).

PAYOFF GATE (added 2026-06-19 — the core slump-recovery rule):
Last 30 days proved a brutal split. Posts that ONLY announce ("Brand X launched feature Y") got 0–0.06% like rate even at 16k–30k views — seen but ignored. Posts that PAIRED a tool with one of these cleared 1.4%+:
  - a sharp "so you can…" outcome ("去背、放大，免費" / "不用再付月費" / "掃瞄可疑流量")
  - a distinctive named product that sounds worth trying (Removerized, Bumblebee, Cal.diy, SkillOpt)
  - Keith's own stake/POV ("我丟進 Hermes 跑 SEO audit", "我花一年寫的 code 一個下午被蓋掉" 0.41%)
Before finalizing EACH draft, apply the gate: "Stripped of the brand name, is there still a reason for a stranger to tap like?" If the only content is "company shipped a thing," REJECT the draft and rewrite it around the payoff — or pick a different source.

AUDIENCE WIDTH (slump-recovery rule, added 2026-06-03):
The tool/insight in your draft must be relevant to a GENERAL AI builder — not a sub-niche.
Recent losers (all <1k views) were too narrow:
  - "Google Antigravity Science Skills" → only researchers care
  - "Agent Cookie" → only headless browser bot devs care
  - "Search as Code" → only Perplexity API users care
Recent winners (all >25k views) were universal:
  - Gemini Spark, Cal.com fork, Hivemind, Anthropic Frontend Design — every AI builder cares
If a source's audience is narrower than "anyone building with AI", SKIP that source. Pick a different one.

PRIORITY TOPIC — if a source involves an AI skill / agent skill / open-source skill system (Anthropic skills, Microsoft SkillOpt, Hivemind, etc.), prioritize it — 6 of top-20 are skill-launches. But the #1 and #2 absolute winners (115k Gemini Spark, 112k Google AI Pro perks) are NOT skills — they are agent-launches and money-saving hacks. Don't over-rotate on skills.

BODY MUST INCLUDE (HARD rules):
- At least ONE concrete number (GitHub stars / dollars raised / downloads / day-N counter). Vague "many/a lot" = REJECT.
- PREFER A DOLLAR FIGURE when the source has one (refreshed 2026-08-02): a $ / 美元 amount appears in 20% of TOP-20 posts and 0% of BOTTOM-20. Money framing amplifies — "賺了 $25,000" (capybara, 190k), "拒付 HubSpot $80k/年", "$13 做了一個網站". If the source involves earnings, cost saved, funding, or a price, put the dollar figure in the hook or first two lines.
- Open-source / free / MIT signal when applicable ("開源", "免費", "MIT", "fork", "open-sourced").
- LAST LINE = direct reader BENEFIT, NOT an observation.
    ✓ "不用再付月費了" / "你可以省下 2 小時/天" / "下個月開始花 30% 時間在 X 上" / "10 分鐘設定完"
    ✗ "這是新的預設" / "AI 已經變了" / "未來就長這樣" / "這不是實驗了"
  Strategic/observational endings KILL share rate. The last line is what drives the forward.

LIKE-RATE QUALITY BAR (added 2026-06-03):
Baseline like rate is 1.17%. Of last 7 posts, 5 were below baseline. Before finalizing each draft, ask:
"If I saw this from someone I don't follow, would I tap like?" If no, REWRITE or reject the source.
Reach can be lucky; like rate is whether the content actually landed.

RECENT PERFORMANCE SIGNAL:
{performance_section}
If recent posts are below baseline, switch into RECOVERY MODE: choose broader sources, stronger utility, and sharper last-line benefit. Do not copy the same structure as recent weak posts.

TOPIC FATIGUE GUARD (added 2026-06-03):
Keith's most-recent posted topics (do NOT pick a source covering the same brand/cluster):
{recent_section}
If your draft would cover the same BRAND or same SEMANTIC CLUSTER as any item above, pick a different source. Algorithm suppresses consecutive-topic clustering (SKILL.md S5/S14).

STYLE:
- Short punchy sentences. Single line breaks between thoughts.
- Mix of Traditional Chinese and English (brand names + technical terms stay English).
- No hashtags. No emojis unless very sparingly.
- 150-300 characters total.

DO NOT WRITE:
- BARE PRODUCT ANNOUNCEMENTS — "[Brand] 剛推出/開源了 [feature]" with no payoff, no named distinctive product worth trying, and no Keith POV. This is the single biggest killer (2026-06-19: 7+ such posts at 0–0.06% like rate despite 2k–30k views). Every announcement MUST clear the PAYOFF GATE.
- "用 Hermes Agent 第 X 天" diary posts. Confirmed dead format (4 data points, all <12k, all <1% like rate).
- Anniversary/milestone-stat posts WITHOUT a tool to use. "X reached N users, this is the new normal" reads as commentary, not actionable. If the source IS an anniversary, you must reframe it as "what builders should do now" with a specific action.
- Niche dev tool posts: cookie managers for headless bots, niche API rewrites, researcher-only skills, anything for a sub-audience smaller than "general AI builders".
- Meta/reflective posts about your own building.
- Posts that start with "I" or "我以為".
- Posts whose last line is observational ("這是新的預設" / "AI 已經變了") rather than actionable.
- Source covers same brand/topic as anything in TOPIC FATIGUE GUARD above.

SOURCE MATERIAL from Keith's X bookmarks (use 1-3 of these as inspiration):

{sources}

VARIATION PLAN:
{diversity_plan}

Write exactly {count} Threads posts. Number them [1] through [{count}]. Each must use different source material. Across the batch, vary angle, first line, structure, emotional frame, and final reader benefit. Hook mix: prefer (a) and (b); use (c) only if a source genuinely is a milestone; SKIP (d). It is OK to reuse hook families when writing more drafts than allowed hook templates, but do not reuse the same opening rhythm or body structure. Apply the TOPIC FATIGUE GUARD before finalizing each. Output only the posts, no explanations."""


def _format_recent_performance(recent_performance: dict[str, Any] | None) -> str:
    if not recent_performance:
        return "(no recent performance data available)"

    sample_size = int(recent_performance.get("sample_size") or 0)
    if sample_size <= 0:
        return "(no recent performance data available)"

    baseline = float(recent_performance.get("baseline_like_rate") or 1.17)
    median = recent_performance.get("median_like_rate")
    below = int(recent_performance.get("below_baseline_count") or 0)
    weak = bool(recent_performance.get("weak_recent_performance"))
    lines = [
        f"Last {sample_size} Threads posts median like rate: {median:.2f}% vs {baseline:.2f}% baseline."
        if isinstance(median, (int, float))
        else f"Last {sample_size} Threads posts checked against {baseline:.2f}% baseline.",
        f"{below}/{sample_size} were below baseline.",
    ]
    if weak:
        lines.append("RECOVERY MODE is active: recent posts are underperforming.")

    examples = recent_performance.get("examples") or []
    if examples:
        lines.append("Recent weak-post openings to avoid mimicking:")
        for ex in examples[:3]:
            opening = (ex.get("opening") or "").strip()
            like_rate = ex.get("like_rate")
            if not opening:
                continue
            if isinstance(like_rate, (int, float)):
                lines.append(f"- {opening} ({like_rate:.2f}% like rate)")
            else:
                lines.append(f"- {opening}")
    return "\n".join(lines)


def _format_threads_diversity_plan(count: int) -> str:
    lanes = [
        "1. Tool utility: what this lets a general AI builder do faster today.",
        "2. Money/time saved: quantify the concrete cost, hours, or subscription avoided.",
        "3. Open-source/fork angle: emphasize free, MIT, self-hosted, or GitHub momentum.",
        "4. Big-company launch angle: explain why a known brand's move changes the default workflow.",
        "5. Workflow before/after: show the old painful way, then the new shortcut.",
        "6. Builder implication: turn the source into a specific action readers should take this week.",
    ]
    selected = lanes[: max(1, min(count, len(lanes)))]
    if count > len(lanes):
        selected.extend(
            f"{i}. Fresh source angle: use a new source and avoid any previous lane's opening rhythm."
            for i in range(len(lanes) + 1, count + 1)
        )
    return "\n".join(selected)


def build_linkedin_prompt(
    bookmarks: list[dict[str, Any]],
    *,
    recent_formats: list[str] | None = None,
) -> str:
    """Generate 1 LinkedIn-tailored draft per Threads draft generation.

    Constraints derived from analysis of Keith's actual LinkedIn data (May 2026,
    n=49 posts with engagement data, top vs bottom 10 by engagement rate):

    Statistically significant signals (top10 vs bottom10 from real data):
    - has_specific_number:        TOP 7/10  vs  BOT 4/10  (+3)
    - mentions_wife_family:       TOP 4/10  vs  BOT 1/10  (+3)
    - length_300_to_700:          TOP 3/10  vs  BOT 0/10  (+3)
    - length_over_700:            TOP 6/10  vs  BOT 9/10  (-3)  ← over-long bombs
    - starts_with_after:          TOP 2/10  vs  BOT 0/10  (+2)
    - starts_with_time_marker:    TOP 2/10  vs  BOT 0/10  (+2)
    - has_percentage:             TOP 2/10  vs  BOT 0/10  (+2)
    - mentions_years_of:          TOP 2/10  vs  BOT 0/10  (+2)
    - has_milestone_word:         TOP 3/10  vs  BOT 1/10  (+2)
    - has_question_in_first_line: TOP 0/10  vs  BOT 2/10  (-2)  ← questions bomb

    Top hook lines (engagement rates 1.7%-3.25%):
    - "After 76 videos and 1 year of effort, I finally have a breakout..."
    - "Rating for lesson 1 of my class: 4.12 out of 5."
    - "I had the 80/20 rule completely backwards."
    - "My AI course is now full! 30/30 signups."
    - "After 8 incredible years at OliveX, I'm stepping down as CEO."

    Bottom hook lines (0.13%-0.66%):
    - "A product manager in Hong Kong searched 'AI expert'..." (story about OTHERS)
    - "𝗦𝘁𝗲𝗮𝗹 𝗺𝘆 𝗯𝗲𝘀𝘁 𝗢𝗽𝗲𝗻𝗖𝗹𝗮𝘄 𝗽𝗿𝗼𝗺𝗽𝘁." (bold-unicode gimmick)
    - "Most people use AI like a junior employee." (generic AI commentary)
    - "What the heck is Shadow AI?" (question opener)
    - "My wife finally stopped asking what I do all day." (521 imp, May 29 2026 — family-as-whole-story, no number in hook)
    - "My son drew a picture of me." (202 imp, May 30 2026 — anecdote-as-whole-story, no number in hook, third-person stake)
    """
    sources = "\n\n---\n\n".join(
        f"Author: {b['author']}\nURL: {b['url']}\n{b['text']}"
        for b in bookmarks[:10]
    )
    fatigue_block = _format_fatigue_block(recent_formats or [])
    return f"""You are a LinkedIn content writer. Your job is to write 1 LinkedIn post for Keith.

Keith publishes on BOTH Threads (short, punchy, Traditional Chinese + English) AND LinkedIn (longer, English, personal). The Threads voice does NOT work on LinkedIn. Different audience, different norms, near-opposite engagement patterns. Don't copy Threads style.

FORMAT MENU — pick ONE format per draft (added 2026-06-07 after 6 consecutive sub-floor story-format posts):
Keith's LinkedIn was running only the STORY format ("After X, I [milestone]"). LinkedIn's algorithm suppresses repeated format from the same author. The 6 sub-floor posts on file are ALL stories. You MUST pick one of these 5 formats:

(A) STORY — personal milestone or backwards-insight (the historical default)
    Hook: "After [N countable], I [struggle/realization]" or "I [self-deprecating struggle]"
    Length: 300-700 chars
    Example: "After 100 YouTube videos averaging 100 views each, I almost gave up"
    Use when: source bookmark surfaces a struggle YOU experienced firsthand
    Warning: overused 2026-05 to 2026-06. Default ONLY if other formats clearly don't fit.

(B) TEARDOWN — analyze a public AI launch's wins/misses
    Hook: "[Company] shipped [thing] last week. Here's what they got right that [competitor] keeps missing:"
    Length: 400-800 chars, 3-4 specific points
    Example: "Anthropic shipped Skills last week. Here's what they got right that OpenAI keeps missing: [3 points with specifics]"
    Use when: source bookmark is a product/feature launch from a known player
    Why it works: positions Keith as analyst, not memoirist. No personal milestone required. Triggers debate.

(C) CONTRARIAN TAKE — flat assertion + evidence
    Hook: "Most [X] is wrong about [Y]. Here's [evidence]."
    Length: 250-500 chars (tight)
    Example: "Most AI agent demos lie about reliability. 30-day audit of mine: 71% completion rate, not 95%."
    Use when: source bookmark surfaces an industry-wide claim Keith can challenge with data
    Why it works: opens with claim, not autobiography. Number frames evidence, not trophy. Sparks comments.

(D) RESOURCE DROP — curated list with brief annotations
    Hook: "I tested [N] [things] this month. The [smaller N] worth using:"
    Length: 400-700 chars, numbered list, 1 line per item
    Example: "I tested 12 AI coding tools this month. The 4 worth using: [list]"
    Use when: source bookmark is one item in a category where Keith can cite alternatives
    Why it works: pure utility, zero personal-stake needed. Readers SAVE these — algo loves saves.

(E) QUESTION→DATA — pose specific question, answer with concrete numbers
    Hook: "Do/Does [specific question with concrete units]? I ran the experiment. Answer:"
    Length: 300-600 chars, lead with question, payoff = number
    Example: "Do Threads posts in Traditional Chinese reach more or fewer people than English? 30-day experiment. Answer: [number]"
    Use when: source bookmark raises a measurable question Keith has actual data on
    Why it works: question creates curiosity gap. Data closes it. Forces specificity.

{fatigue_block}HOW TO PICK: Match the SOURCE BOOKMARK to the best-fit format. A product launch → TEARDOWN. An industry claim → CONTRARIAN. A category survey → RESOURCE DROP. A measurable question → QUESTION→DATA. Personal struggle/realization → STORY (but only if format-fatigue allows). When in doubt between two formats, pick the one Keith has used LEAST RECENTLY (see FORMAT FATIGUE block).

HARD CONSTRAINTS — derived from analysis of Keith's 49 LinkedIn posts with engagement data. Top 10 vs bottom 10 patterns:

OPENING HOOK — depends on which FORMAT MENU option you picked:
  FORMAT (A) STORY: must be ONE of these three (top story performers all use one):
    (a) "After [N years/videos/etc.], I [milestone]"
    (b) "I [self-deprecating struggle or backwards insight]"
    (c) "[Specific personal milestone with a number]"
  FORMAT (B) TEARDOWN: "[Company] shipped [thing]. Here's what they got right/wrong:"
  FORMAT (C) CONTRARIAN: "Most [X] [does Y wrong]. Here's [evidence]."
  FORMAT (D) RESOURCE DROP: "I tested [N] [things]. The [smaller N] worth using:"
  FORMAT (E) QUESTION→DATA: "Do/Does [specific measurable question]?"

NUMBER-IN-HOOK RULE (HARD, applies to ALL formats): The OPENING — first 100 characters — MUST contain a concrete, COUNTABLE number, rating, count, or percentage. The number in the body is not enough — LinkedIn's algorithm decides reach from the first ~150 chars of dwell time. (Formats B/C/D/E naturally satisfy this via teardown specifics, percentages, list counts, or measurement units — but verify before submitting.)

  ✓ ACCEPTABLE openings (specific countable units):
    - "After 76 videos and 1 year of effort..." (76, 1)
    - "Rating for lesson 1 of my class: 4.12 out of 5" (4.12)
    - "My AI course is now full! 30/30 signups" (30/30)
    - "After 100 YouTube videos averaging 100 views..." (100, 100)

  ✗ REJECTED openings (vague time markers, no specific count — added 2026-06-03, hardened 2026-06-07 after 3 more sub-400-impression posts):
    - "After 6 months of evolving my AI workflow..." (6 months is a SPAN, not a COUNT — 242 imp)
    - "After 6 months of token-maxing — running Qwen locally..." (6 months SPAN — 123 imp, worst LinkedIn perf in recent memory, 2026-06-07)
    - "12 months ago I was begging Claude to fix..." (TIME-AGO span, no count — 222 imp, 2026-06-06)
    - "After a while of trying..." (no count at all)
    - "Recently I figured out..." (no count)
    - "Yesterday I tried X" (relative time, no count)
    - "My wife finally stopped asking..." (no count — 521 imp)
    - "My son drew a picture of me..." (no count — 202 imp)

BAN-LIST — these exact opener PATTERNS are auto-reject, no exceptions:
    - "After N months/years of [activity]" — duration span. Use "After N [countable]" instead.
    - "N months/years ago I [did X]" — TIME-AGO span. Doesn't satisfy NUMBER-IN-HOOK.
    - "After a while", "Recently", "Yesterday", "A while back" — no count.
    - "Over the last [duration]" — duration span.
    - "For [N] months/years I [did X]" — duration span, even though N is technically a number.

The distinction is COUNTABLE UNITS vs DURATION SPANS. "76 videos" counts; "6 months" doesn't. "30/30 signups" counts; "12 months ago" doesn't. If your opening can be rewritten with "many" or "some" without losing meaning, the number isn't concrete enough. If your number is a UNIT OF TIME (months/years/weeks/days) it is a SPAN, not a COUNT — reject.

BRAG-FLEX REJECTION (added 2026-06-07):
A countable number alone is not enough. If the opening reads as a BRAG without a struggle/setup hook, LinkedIn's algorithm treats it as low-engagement and suppresses reach.
    ✗ "After 149,000 views on an iPhone 15 Pro, I went out and bought a Sony anyway" (399 imp — number is a flex, no problem/insight framing)
    ✗ "After 10,000 followers, I bought a new camera" (number-as-trophy)
    ✓ "After 100 YouTube videos averaging 100 views each, I almost gave up" (number frames a STRUGGLE, not a trophy)
    ✓ "After 76 videos and 1 year of effort, I finally have a breakout" (number earns the milestone via effort)
Rule: if the opening number reads as "look what I accomplished" without immediately pairing it with a struggle, mistake, or counter-intuitive realization, REWRITE. The number must frame a PROBLEM the reader cares about, not a TROPHY the writer earned.

NEVER OPEN WITH:
- A vague time marker ("After 6 months", "Recently", "A while ago") — duration without a countable unit. See ✗ list above.
- A question ("What is X?" / "Have you ever?") — bottom posts use these.
- A story about ANOTHER person, including your own family as the SUBJECT — family as FOIL inside a numeric milestone is fine; family as the whole premise is not.
- Bold-unicode formatting (𝗯𝗼𝗹𝗱) — reads gimmicky.
- Generic AI commentary ("Most people use AI...") — scrolls right past.
- Thanks/shoutouts (saved for occasional, not the default).
- A first line with no number, count, or rating — algo suppression in first hour.

BODY MUST INCLUDE:
- At least ONE concrete number (year count, video count, $ amount, rating, percentage, signup count). No vague "many" or "a lot". This is THE single strongest signal.
- A personal stake — what YOU did, felt, struggled with. Stories about others bomb.
- A wife/family/student reference works well as a foil (4/10 top posts use this).
- A milestone or backwards-insight word ("finally", "breakthrough", "backwards", "doubled", "completely wrong") — top posts use these 3x more than bottom.

LENGTH:
- TARGET: 300-700 characters. 3 of 10 top posts hit this sweet spot, 0 of 10 bottom posts do.
- Acceptable: 700-1200 if the story genuinely needs it.
- DANGER ZONE: over 1200 chars. 9 of 10 bottom posts are over 700 chars without earning it.
- AVOID under 250 chars (LinkedIn algo treats as low-value).

STYLE:
- English-first. Drop in 中文 only for direct quotes or product names.
- Paragraph breaks between thoughts (LinkedIn renders them well).
- Sparing emoji — 🚀 at the start of "course is full" type announcements is OK, but never lead with a long emoji sequence.
- No hashtags (current LinkedIn algo deprioritizes hashtag-stuffed posts).

CLOSE:
- A reflection or earned insight, not a sales pitch.
- Optional: invite engagement with a specific question ("If you've done X, how did you handle Y?"). Top posts ask less than I'd expected — only 1/10 ends with a question. Don't force it.

PERFORMANCE FLOOR (re-derived 2026-06-26 against REAL reaction data, n=20 posts):
The metric that matters is ENGAGEMENT RATE — (reactions + comments) / impressions — NOT raw reach. Raw impressions are a vanity number on LinkedIn: a post the algorithm sprays to 9,468 feeds but that nobody reacts to (0.08%) builds no audience, while a post seen by 186 people where 2.15% react is a genuine connection. Optimize for the rate, not the reach.

Real engagement-rate distribution (n=20 posts with true reaction counts, May–Jun 2026):
- MEDIAN engagement rate: 1.30%
- MEAN: 1.56%   ·   RANGE: 0.12%–3.47%
- FLOOR to clear: ~1.0% engagement. Below ~0.5% is a confirmed underperformer.

Confirmed LOW-engagement posts (high reach, weak connection — the trap to avoid):
- 9,468 impressions but only 0.08% engagement, 2026-06-18 (massive reach, near-zero reaction — reach without resonance)
- 2,856 impressions at 0.42% engagement, 2026-06-13 (wide spray, thin engagement)
- 1,040 impressions at 0.48% engagement, 2026-06-23

Confirmed HIGH-engagement posts (the target — modest reach, strong reaction):
- 2.50% engagement, 2026-06-01 (681 imp, 17 reactions)
- 2.48% engagement (the "son drew a picture of me" post — only 202 impressions but one of the BEST engagement rates on file; the old prompt wrongly flagged this as a failure on impressions alone)
- 2.15% engagement, 2026-06-25 (186 imp)
- 2.11% engagement, 2026-06-17 (237 imp)
- 1.82% engagement, 2026-06-22 (549 imp)
- 1.34% engagement (the "my wife finally stopped asking" post — above the 1.30% median; also previously mis-flagged as a floor failure)

KEY REVERSAL: several posts the OLD prompt called "sub-floor failures" (son's picture 202 imp, wife 521 imp) are in fact ABOVE-median on engagement rate. Do NOT avoid their patterns. The lesson is not "small reach = bad" — it's "write for the people who actually see it." A high reaction RATE is the goal even at modest reach.

POSTING CADENCE (added 2026-06-03):
LinkedIn B2B engagement is measurably stronger Tue/Thu mornings (8-10am posting time) than Mon/Wed/Fri. Keith's audience per demographics: tech/software founders, CEOs, software engineers, 2-50 employee companies — exactly the segment that's most active those mornings. If the draft will be posted Mon/Wed/Fri, weight extra effort into the first 100 chars to compensate for the weaker algorithmic baseline.

PRE-WRITE CHECKLIST — verify each before finalizing:
[1] First 100 chars contain a specific COUNTABLE number — NOT a duration ("6 months", "12 months ago", "for 2 years"). Re-read the BAN-LIST and BRAG-FLEX sections.
[2] The number in [1] frames a STRUGGLE, BACKWARDS-INSIGHT, or COUNTER-INTUITIVE REALIZATION — not a trophy. "After 149,000 views, I bought a Sony" = trophy = REJECT. "After 100 videos averaging 100 views, I almost gave up" = struggle = OK.
[3] Within the first 100 chars, the reader can sense WHY THEY SHOULD CARE — what insight or lesson is coming. Lead with the takeaway-hint, not the autobiography. If your first 2 lines are pure personal history with the insight buried at line 5+, REWRITE so the insight is hinted at in line 1-2.
[4] Opening matches your chosen FORMAT MENU option. Specifically: NOT a generic-rhetorical question (FORMAT E uses a SPECIFIC measurable question — different), NOT a third-person/family-as-subject story, NOT vague "Most people use AI..." commentary (FORMAT C CONTRARIAN must cite SPECIFIC evidence, not vibes), NOT a brag-flex.
[5] Body has at least one more concrete number (not vague "many/a lot")
[6] For FORMAT A (STORY): personal stake is YOURS — what YOU did, felt, struggled with. For FORMATS B/C/D/E: replace with "Specifics are CITED — companies named, numbers measured, tools listed by name" (not vague references)
[7] Length matches your chosen format's target (STORY 300-700; TEARDOWN 400-800; CONTRARIAN 250-500; RESOURCE 400-700; QUESTION→DATA 300-600); never over 1200 without earning it
[8] Close is reflection/insight, not sales pitch
[9] No hashtags. No leading emoji sequences.
If any checkbox fails, REWRITE before submitting. A failing draft trades away engagement rate — the metric that actually compounds into an audience.

DATA LIMITATION DISCLAIMER:
The PERFORMANCE FLOOR engagement-rate numbers were re-derived 2026-06-26 from REAL reaction data (n=20 posts with true reaction/comment counts imported via `orbit linkedin single`). This corrected the prior framing, which optimized for raw impressions and mis-flagged several high-engagement posts as failures.

The hook/format signals (top10/bottom10 above — has_specific_number, mentions_wife_family, etc.) are STILL from the one-time May 2026 export of 49 posts and have NOT yet been re-derived against engagement rate, because the post BODIES for the real-reaction posts aren't in the DB. To re-derive content signals: export a LinkedIn Shares.csv, run `orbit linkedin shares <Shares.csv>` to backfill post text, then recompute which hooks correlate with high engagement rate. Until then, treat the content signals as directional, not confirmed. Don't assume any of this is auto-updated.

SOURCE MATERIAL from Keith's X bookmarks (use the ONE most interesting as the spine):

{sources}

STEP 1: Pick a FORMAT (A/B/C/D/E) by matching the source bookmark + the FORMAT FATIGUE constraint above. Announce your chosen format internally before writing.
STEP 2: Pick the source bookmark that best fits that format.
STEP 3: Write exactly 1 LinkedIn post following ALL rules above (NUMBER-IN-HOOK, BAN-LIST, BRAG-FLEX REJECTION, length for chosen format, PRE-WRITE CHECKLIST).
STEP 4: Self-check against PRE-WRITE CHECKLIST. If any item fails, rewrite.

For FORMAT A (STORY): write from Keith's first-person voice — frame it as something HE experienced.
For FORMATS B/C/D/E: Keith is the analyst/curator/experimenter, NOT the protagonist of the source's story. The "I" voice is still Keith, but he's commentating, comparing, testing — not memoirizing.

Output only the post body, no format label, no headers, no explanations."""


_LINKEDIN_FORMATS = ("STORY", "TEARDOWN", "CONTRARIAN", "RESOURCE_DROP", "QUESTION_DATA")


def classify_linkedin_format(content: str) -> str:
    """Best-effort heuristic to classify a LinkedIn post's format.

    Used by the FORMAT FATIGUE GUARD to decide which formats Keith has
    used recently. Heuristic — not perfect, but good enough to detect
    "all 6 recent posts are STORY format" which is the failure mode we
    care about. Returns one of _LINKEDIN_FORMATS, defaulting to STORY
    when nothing else matches (since STORY is the historical default).
    """
    if not content:
        return "STORY"
    first_line = content.strip().split("\n", 1)[0].lower()
    head = content.strip()[:200].lower()

    # QUESTION→DATA: opens with do/does/which/why/can/should + has a question mark in first line
    if "?" in first_line and any(first_line.startswith(w) for w in ("do ", "does ", "which ", "why ", "can ", "should ", "is ", "are ", "what ")):
        return "QUESTION_DATA"
    # RESOURCE DROP: "I tested N" / "The N worth" / numbered list signals
    if "tested" in head or "i tried " in head or "worth using" in head or "best " in first_line:
        if any(marker in head for marker in ("1.", "2.", "•", "- ", "the 3 ", "the 4 ", "the 5 ", "the 6 ", "the 7 ")):
            return "RESOURCE_DROP"
    # CONTRARIAN: opens with "most", "everyone", "people think", flat assertion
    if any(first_line.startswith(w) for w in ("most ", "everyone ", "people think", "the truth ", "nobody ")):
        return "CONTRARIAN"
    # TEARDOWN: opens with a company/product name + verb like "shipped", "launched", "released"
    if any(verb in head for verb in ("shipped ", "launched ", "released ", "announced ", "got right", "got wrong")):
        # Must look like analysis, not personal: no "I [past-tense-verb]" in first line
        if not any(first_line.startswith(p) for p in ("i tested ", "i tried ", "i built ", "i made ", "i finally ", "after ")):
            return "TEARDOWN"
    # Default: STORY (historical pattern — "After N", "I [struggle]", milestone)
    return "STORY"


def _format_fatigue_block(recent_formats: list[str]) -> str:
    """Render the FORMAT FATIGUE GUARD section for the prompt.

    Empty input → empty string (the prompt's HOW TO PICK section still
    works without it). Non-empty input → ban-list with explicit format
    exclusions and a guidance line.

    Mirrors how the Threads prompt handles TOPIC FATIGUE GUARD.
    """
    if not recent_formats:
        return ""
    # Dedup preserving order, filter to known formats
    seen: set[str] = set()
    cleaned: list[str] = []
    for f in recent_formats:
        f_norm = (f or "").strip().upper()
        if f_norm in _LINKEDIN_FORMATS and f_norm not in seen:
            seen.add(f_norm)
            cleaned.append(f_norm)
    if not cleaned:
        return ""
    excluded = ", ".join(cleaned)
    return (
        f"FORMAT FATIGUE GUARD (LinkedIn algo suppresses repeated format from same author):\n"
        f"Keith's last 3 LinkedIn posts used these formats: {excluded}.\n"
        f"DO NOT pick any of: {excluded}. Choose from the remaining formats in the menu.\n"
        f"If the source bookmark genuinely cannot fit any non-excluded format, prefer the LEAST-RECENTLY-USED excluded format and note this trade-off in your internal reasoning.\n\n"
    )


def build_facebook_variant_prompt(content: str) -> str:
    """Rewrite a Threads draft as a Facebook-native post.

    Facebook's 2026 feed distributes Page text posts almost entirely on
    comment/share velocity (reach without engagement: ~1-6% of followers,
    no discovery surface). A broadcast that works on Threads just dies there,
    so the cross-post gets reframed for discussion instead of cloned.
    """
    return f"""Rewrite this Threads post as a Facebook post by the same author.

Facebook in 2026 rewards posts that start conversations — comments and shares
are the only distribution currency for text posts. Rewrite it so it:

- Opens with the strongest concrete detail or claim (first line is the hook).
- Keeps every fact, number, and project name exactly as written — invent nothing.
- Reads as the same person: plain, direct, first person. No marketing voice.
- Has room to breathe: 2-4 short paragraphs (Facebook tolerates longer than Threads).
- Ends with ONE specific question readers can answer from their own experience.
  Not "what do you think?" — a question about THEIR setup, result, or choice.
- No hashtags. No emojis beyond any already in the original.

Original Threads post:
---
{content}
---

Output ONLY the Facebook post text — no preamble, no quotes, no explanation."""
