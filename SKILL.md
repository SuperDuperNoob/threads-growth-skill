---
name: threads-growth
description: Systematically improve your Threads content over time — log into your account, pull real Insights data, learn what works, and draft better posts using your own performance history.
version: 1.0.0
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
4. **Scores new drafts** before you post them
5. **Runs a bi-weekly cron** to update your personal performance database automatically

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
- Apply your personal winning patterns (not generic advice)
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

## Hook Framework (built-in)

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
Running live on my own account. Star the repo if it's useful.
