# Threads Growth Skill for Hermes Agent

> Systematically improve your Threads content over time using your own real data.

Built by [@krumjahn](https://www.threads.com/@krumjahn) — running live on my account since April 2026.

## What this does

- Logs into your Threads account (via browser cookies)
- Pulls your real Insights — views, likes, replies per post
- Identifies your personal winning patterns (not generic advice)
- Scores new post drafts before you publish
- Runs a bi-weekly cron to keep your performance database updated automatically

## Requirements

- [Hermes Agent](https://github.com/NousResearch/hermes-agent) installed
- A Threads account
- Cookie-Editor browser extension (for one-time setup)

## Install

```bash
# Clone into your Hermes skills directory
git clone https://github.com/krumjahn/threads-growth-skill ~/.hermes/skills/social-media/threads-growth
```

Then tell Hermes:
```
set up my threads growth skill
```

Hermes will walk you through cookie export and first Insights scrape (~5 min).

## How it works

1. **Setup**: Export your Threads cookies once → Hermes stores them → logs in via browser automation
2. **Draft**: Describe your post idea → Hermes drafts using your winning patterns → you approve
3. **Track**: Bi-weekly cron scrapes Insights → updates `winning-formats.md` → sends you a report
4. **Compound**: Every 2 weeks your patterns get sharper. Posts improve automatically.

## The compounding loop

```
Post → Track performance → Update patterns → Better drafts → Better posts → Repeat
```

Most people post by feel. This skill makes you post by data — your data, not generic best practices.

## Files

```
threads-growth/
├── SKILL.md                        # Main skill (loaded by Hermes)
├── README.md                       # This file
├── references/
│   └── winning-formats.md          # Your personal performance database
└── scripts/
    ├── setup.sh                    # One-time setup
    └── scrape_insights.sh          # Insights scraper (called by cron)
```

## Cookie expiry

Threads session cookies last ~60 days. When expired, the cron alerts you to paste fresh ones. 2-minute refresh.

## License

MIT — steal it freely.

---

*If this helped you, follow [@krumjahn](https://www.threads.com/@krumjahn) for more AI + solopreneur workflows.*
