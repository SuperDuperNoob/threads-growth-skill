---
name: threads-growth
description: Systematically improve your Threads content over time — log into your account, pull real Insights data, learn what works, draft better posts using your own performance history, and run algorithm + AI-tone checks before every post.
version: 2.0.0
author: Keith Rumjahn (@krumjahn)
platforms: [linux, macos]
metadata:
  hermes:
    tags: [social-media, threads, growth, analytics, content]
---

# 📈 Threads Growth Skill

Turn your Threads account into a compounding content machine.
This skill learns from your real performance data and gets smarter every post.

## What it does

1. **Logs into your Threads account** using browser cookies (one-time setup)
2. **Pulls your Insights** — views, likes, replies for every post
3. **Identifies winning patterns** — hook types, formats, artifact presence
4. **Drafts posts** using your winning patterns + algorithm alignment + AI-tone removal
5. **Runs pre-post checks** — algorithm red lines, AI-tone detection, engagement prediction
6. **Schedules via Postiz** when you say "go"
7. **Runs a bi-weekly cron** to update your personal performance database automatically

---

## One-Time Setup

### Step 1: Export your Threads cookies

1. Install the browser extension **"Cookie-Editor"** (Chrome/Firefox)
2. Go to **www.threads.com** while logged in
3. Open Cookie-Editor → Export → "Netscape" format
4. Save the file, then paste contents to Hermes: "here are my threads cookies: [paste]"

Hermes will extract your `sessionid`, `ds_user_id`, `csrftoken`, and `mid` values and store them securely.

### Step 2: Find your Postiz integration ID (optional — for auto-scheduling)

If you use Postiz for scheduling, run:
```
postiz integrations:list
```
Copy your Threads integration ID and tell Hermes: "my threads postiz ID is [id]"

### Step 3: Confirm setup

Tell Hermes: "set up my threads growth skill"

Hermes will:
- Test the cookie login
- Scrape your current Insights
- Create your personal `winning-formats.md`
- Schedule a bi-weekly performance tracker cron

---

## Workflow

### Draft a new post

Just describe your idea:
> "Draft a Threads post about [topic]"

Hermes will:
- Apply your personal winning patterns
- Run algorithm red-line check
- Run AI-tone detection + fix
- Score the draft (predicted engagement range)
- Suggest improvements if the score is low
- Schedule it when you say "go"

### Check your performance

> "How are my recent posts doing?"

Hermes logs in, pulls your Insights, and gives you a breakdown.

### Update your patterns

The bi-weekly cron does this automatically. Or trigger manually:
> "Update my threads patterns"

---

## Hook Framework

| Hook Type | When to use | Avg. multiplier |
|-----------|-------------|-----------------|
| Anti-Demo | You hit a specific failure → found the fix | 1.5x |
| Secret Knowledge | Something most people don't know + steps | 1.4x |
| Truth/Comparison | Same task, two tools, clear winner | 1.2x |
| Builder Journey | Workflow switch with concrete before/after | 1.1x |
| Link Drop | Just a link | 0.2x — avoid |

**Key rules:**
- Lead with friction, not the win
- Specific metrics over adjectives ("saves 2 hours" not "super fast")
- Artifact in-post (GitHub link, install command) = 1.5x engagement multiplier
- Never put the link in comments if you want shares
- Vary paragraph and bullet length — uniform lists are the #1 AI tell

---

## Algorithm Red-Line Check

Run this before finalising every draft. These cause suppression or demotion on Meta.

**Hard Red Lines — avoid completely:**
- **R1 Engagement Bait**: "like if you agree", "tag a friend", "comment X to get Y" — any explicit engagement solicitation
- **R2 Clickbait**: Hook promises something the body doesn't deliver
- **R3 Hook/Body Mismatch**: Hook sets up tension that the post never resolves
- **R5 Consecutive Same-Topic**: Posting same semantic cluster repeatedly causes topic fatigue
- **R9 Topic Mixing**: Single post covering 2+ unrelated topics dilutes semantic signal
- **R12 Soft Demotion Stack**: 2+ weak signals together can trigger soft suppression

**Key Distribution Signals — optimize for these:**
- **S1 DM/Private Shares**: 3–5x heavier than likes (Mosseri 2025). Ask: would someone forward this to a friend?
- **S2 Deep Comments**: 5+ word comments = ~30x the weight of a like. Design for comment-worthy conclusions.
- **S3 Dwell Time**: Multi-part threads increase dwell — favored by algorithm
- **S6 Image+Text Combo**: 60% higher median engagement (Buffer 2026) — add a screenshot where possible
- **S8 Trust Graph**: Meta's 2026 key signal. Consistent topic + authentic voice builds trust score over time
- **S14 Topic Freshness Budget**: Each semantic cluster has a fatigue budget. Check recent posts before same-topic draft

**Share Motive Split** (design for at least one):
- DM Forwardability: "I need to send this to someone" — strongest reach signal
- Public Repostability: "This reflects who I am"
- Identity Signal: "Sharing this = credibility boost for me"
- Utility: "I'll need this later / bookmark-worthy"

---

## AI-Tone Detection

Run on every draft before presenting. Flag and fix any hits.

**Sentence-level tells:**
- Fixed "liveliness" phrases: 說白了就是, 更離譜的是, 坦白說 — AI signatures
- Over-neat contrast: "以前是A，現在是B" with identical length both sides
- >40% of sentences work as standalone quotes
- Performative suspense then immediate self-answer
- Formal connectors stacked: 然而, 值得注意的是, 換言之
- Uniform bullet lists (each bullet ±5 chars)
- Philosophical ending: specific topic → suddenly jumps to life wisdom

**Structure-level tells:**
- Argument flows too smoothly — add one counterexample or hedge
- Every paragraph ends with a summary sentence
- Overly complete ending with conclusion + recommendation + CTA all together

**De-AI methods (apply at least 2 per draft):**
1. Add a case that nearly failed or was unexpected
2. Add a moment your judgment was wrong
3. Add an exception: "除了一個情況…"
4. Add uncertainty modifiers: "大概", "我猜", "左右"
5. Leave one sentence intentionally imperfect
6. Leave an incomplete judgment — not everything spelled out
7. End only by saying what you personally do next

---

## Pre-Post Checklist

Run before every scheduled post:

- [ ] No R1 engagement bait
- [ ] Hook promise matches body (R2/R3)
- [ ] Not same topic cluster as recent post (R5/S14)
- [ ] Single topic focus (R9)
- [ ] At least 2 de-AI methods applied
- [ ] Ending is not philosophical / not a full CTA paragraph
- [ ] DM-forwardable? (S1 — highest weight signal)
- [ ] Consider adding image/screenshot (S6 — +60% engagement)

---

## Post Length — Threads vs Facebook

- **Threads**: 500 char limit per part. Use multiple `-c` flags for multi-part threads — they appear as one seamless long post in the feed. This is how power users write "long" Threads posts.
- **Facebook**: Always one long continuous post. No threading needed.

---

## Files

| File | Purpose |
|------|---------|
| `SKILL.md` | This file — workflow and framework |
| `references/winning-formats.md` | Your personal performance database (auto-updated) |
| `scripts/scrape_insights.sh` | Cookie injection + Insights scrape script |
| `scripts/setup.sh` | One-time setup helper |

---

## Cookie Expiry

Threads session cookies last ~60 days. When your cron detects an expired session, it will message you to paste fresh cookies. Takes 2 minutes to refresh.

---

## Credits

Built by [@krumjahn](https://www.threads.com/@krumjahn) — solopreneur, AI builder.
Algorithm knowledge base adapted from [AK-Threads-Booster](https://github.com/akseolabs-seo/AK-Threads-booster) by @darkseoking.
Running live on my own account. Star the repo if it's useful.
