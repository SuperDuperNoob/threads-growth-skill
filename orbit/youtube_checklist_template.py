"""Checklist template seeded into every new `orbit youtube new` checklist.

Structure derived from Jeff Sue's process (LLjpnubsOWc, ~44-52 min):
- Pre-production: ideation → title → thumbnail → hook → outline → script
  ("hook is more important than the script outline" — 48:53)
- Filming: ~1 hour
- Post-production: briefing editor + B-roll instructions (4-5 hrs with AI mockups)

Within each phase the leaf items are intentionally Keith-flavored — vibe-coding
audience, Claude/Hermes/OpenClaw workflow, Threads cross-promo. Customize freely;
this is a starting point not a rule.
"""
from dataclasses import dataclass


@dataclass
class TemplateItem:
    phase: str           # 'pre-production', 'scripting', 'filming', 'post-production'
    label: str           # short imperative ("Confirm thumbnail")
    detail: str = ""     # longer hint (rule of thumb, prompt to use)
    blocks_next: bool = False  # if True, downstream items can't be checked until this is


# Order matters — these are seeded in this exact sequence per checklist.
TEMPLATE: list[TemplateItem] = [
    # === PRE-PRODUCTION ===
    TemplateItem(
        phase="pre-production",
        label="Ideate: pick a topic from your bookmark queue or interview answers",
        detail="Use `orbit discover` or `orbit interview` if you're blank. Best topics: AI tool launches your audience hasn't seen, contrarian takes on Hermes/Codex/Claude.",
    ),
    TemplateItem(
        phase="pre-production",
        label="GBT articulate: clean up scattered thoughts",
        detail="Run the GBT_ARTICULATE prompt with your raw notes. Output: structured refinement + narrative synthesis. (Prompt stored in orbit.youtube_prompts.GBT_ARTICULATE)",
    ),
    TemplateItem(
        phase="pre-production",
        label="Draft a working title (for scripting only — final 3 come later)",
        detail=(
            "Just one title to keep scripting focused. Your three A/B titles get generated "
            "in post-production once you know the actual finished story. Format that works "
            "for your audience: 'Master <Tool> in <N> minutes', 'I used <Tool> for <N> days', "
            "'<Brand> just open-sourced <Thing>'."
        ),
    ),
    TemplateItem(
        phase="pre-production",
        label="Generate primary thumbnail (Ali Abdaal style via ChatGPT Images 2.0)",
        detail=(
            "Inputs: your face photo + the style anchor.\n"
            "Prompt template: 'Create a YouTube thumbnail in the style of Ali Abdaal: bright "
            "vibrant background, large expressive facial reaction (use the photo I provided), "
            "big bold text overlay reading [TEXT], single clear subject, high contrast, no "
            "clutter. Topic: [TOPIC].'\n"
            "Generate 2-3 options and pick the strongest. Save as thumbnail_v1.png."
        ),
    ),
    TemplateItem(
        phase="pre-production",
        label="Finalize working title + primary thumbnail — must be locked before scripting",
        detail="Jeff's rule: 'I cannot proceed' until both are confirmed. If you're not happy with the thumbnail, you're not ready to script.",
        blocks_next=True,
    ),

    # === SCRIPTING ===
    TemplateItem(
        phase="scripting",
        label="Write the hook (more important than the outline)",
        detail=(
            "Jeff's 3-part hook framework (LLjpnubsOWc @ 48:53):\n"
            "  1. Confirm to the viewer they clicked on the right video.\n"
            "  2. Provide info about the story AND about you, the creator. Make it personal.\n"
            "  3. Ask a new, unexpected question that they have to wait until the end to get answered."
        ),
        blocks_next=True,
    ),
    TemplateItem(
        phase="scripting",
        label="Outline the script (chapters / sections)",
        detail="3-5 chapters max. Each chapter = one tool/concept/result. Your 'Master X in N min' videos work because each minute teaches one concrete thing.",
    ),
    TemplateItem(
        phase="scripting",
        label="Write the full script (8-10 hrs is normal per Jeff)",
        detail="Voice-match your Threads tone: short punchy sentences, specific numbers, mix of Traditional Chinese + English where natural.",
    ),
    TemplateItem(
        phase="scripting",
        label="Mark B-roll cues + screenshot moments",
        detail="Anywhere you mention a specific tool/setting/result, mark [B-ROLL: ...] so editor knows. Jeff uses Canva mockups; Excalidraw works too.",
    ),

    # === FILMING ===
    TemplateItem(
        phase="filming",
        label="Set up: camera, mic check, screen recording app",
        detail="If you're demoing Hermes/Codex/OpenClaw, do a 30-sec recording test first — agent UIs change and your last setup may not match.",
    ),
    TemplateItem(
        phase="filming",
        label="Record hook + intro (~1 hr total for full video per Jeff)",
        detail="If the hook doesn't feel right after take 2, stop and rewrite — don't push through.",
    ),
    TemplateItem(
        phase="filming",
        label="Record main chapters",
        detail="One clean take per chapter is better than splicing 5 fragments. Pause + restart the chapter if you lose the thread.",
    ),
    TemplateItem(
        phase="filming",
        label="Record outro + CTA",
        detail="Single CTA only: subscribe, OR check Hermes link, OR watch related video. Don't stack.",
    ),

    # === POST-PRODUCTION ===
    TemplateItem(
        phase="post-production",
        label="Send footage + B-roll notes to editor (or self-edit)",
        detail="If editing yourself with AI assist: 4-5 hrs is the new norm (vs Jeff's old 8-10). Brief the editor with Canva/Excalidraw mockups for any motion-graphics moment.",
    ),
    TemplateItem(
        phase="post-production",
        label="Review first cut — check pacing on first 30 seconds especially",
        detail="The hook is where viewers bounce. If first 30 sec doesn't deliver on the 3-part framework, recut before anything else.",
    ),
    TemplateItem(
        phase="post-production",
        label="Approve final cut",
        detail="Don't ship if you'd skip it yourself watching as a viewer.",
        blocks_next=True,
    ),

    # --- Post-production: titles, thumbnails, description (Keith's process) ---
    TemplateItem(
        phase="post-production",
        label="Generate 3 A/B test titles (each different, each ≤55 chars)",
        detail=(
            "YouTube Studio's 'Test & compare' rotates these for 2-4 days and picks the CTR winner. "
            "RULES:\n"
            "  • Each title must be ≤55 chars (gets truncated in mobile + sidebar above that).\n"
            "  • Each must use a different HOOK ANGLE — not just word swaps. Mix from:\n"
            "      - Curiosity gap: 'I replaced Claude with $10. Here's what broke.'\n"
            "      - Specific result: 'Minimax M2.7 vs Claude: 90% the result, 5% the cost'\n"
            "      - How-to: 'Cheapest way to run OpenClaw + Hermes (tested)'\n"
            "      - Contrarian: 'Stop paying for Claude API. Try this instead.'\n"
            "Run them through orbit's `_run_draft_generation` style if you want them in your voice."
        ),
    ),
    TemplateItem(
        phase="post-production",
        label="Generate 2 alt thumbnails (Ali Abdaal style via ChatGPT Images 2.0)",
        detail=(
            "Same generator as the primary thumbnail. YouTube's A/B test needs 3 total thumbnail "
            "variants (you already made thumbnail_v1 in pre-prod) — generate v2 and v3 here with "
            "different facial expressions OR different background colors so the A/B test has signal.\n"
            "Prompt template: 'Create a YouTube thumbnail in the style of Ali Abdaal: bright "
            "vibrant background ([COLOR: yellow/blue/red]), large [EXPRESSION: surprised/skeptical/excited] "
            "facial reaction (use the photo I provided), big bold text overlay reading [TEXT], "
            "single clear subject, high contrast, no clutter. Topic: [TOPIC].'\n"
            "Save as thumbnail_v2.png + thumbnail_v3.png."
        ),
    ),
    TemplateItem(
        phase="post-production",
        label="Write YouTube description with chapter timestamps + tool links",
        detail=(
            "Structure:\n"
            "  Line 1: one-sentence hook (what they'll learn)\n"
            "  Line 2-3: who this is for + the main result/promise\n"
            "  Blank line\n"
            "  📌 LINKS section: every tool/repo mentioned, with GitHub URLs when applicable\n"
            "     (orbit auto-extracts these in `source_links` if you used `orbit discover/draft`)\n"
            "  📌 CHAPTERS section: timestamps in `MM:SS — Chapter title` format\n"
            "     (YouTube auto-creates chapters when ≥3 timestamps starting at 00:00)\n"
            "  📌 RELATED VIDEOS: 2-3 of your own videos on adjacent topics\n"
            "  Final line: newsletter / CTA"
        ),
    ),
    TemplateItem(
        phase="post-production",
        label="Upload to YouTube Studio + configure A/B test",
        detail=(
            "1. Upload final video.\n"
            "2. Set primary thumbnail (v1) + title (#1) as defaults.\n"
            "3. YouTube Studio → Content → click your video → 'Test & compare' (under Title or Thumbnail).\n"
            "4. Add v2 and v3 as alternates. YouTube auto-rotates for ~2-4 days and locks in the CTR winner.\n"
            "5. Schedule (don't publish immediately) so you can review one last time."
        ),
    ),
    TemplateItem(
        phase="post-production",
        label="Add end screen (subscribe + 1-2 related videos)",
        detail=(
            "YouTube Studio → your video → Editor → End screen.\n"
            "Standard layout: 1 'Subscribe' element + 1-2 related videos (use 'Best for viewer' so "
            "YouTube picks the highest-CTR option per viewer, or hand-pick from your own catalog).\n"
            "Place in the last 5-20 seconds. Don't talk over silence — record your outro to leave "
            "room for the end screen visuals."
        ),
    ),
    TemplateItem(
        phase="post-production",
        label="Turn on monetization",
        detail=(
            "YouTube Studio → your video → Monetization → On.\n"
            "Ad types: keep defaults (display, overlay, sponsored cards, skippable + non-skippable video).\n"
            "Ad positions: 'Before video' + 'During video' (auto). Tick 'After video' if the outro can absorb it.\n"
            "Self-certification: complete the questionnaire honestly (most AI/tool content qualifies for "
            "advertiser-friendly). Skipping this means YouTube guesses, often more conservatively."
        ),
    ),
    TemplateItem(
        phase="post-production",
        label="Cross-post: queue Threads + Facebook teaser via `orbit draft`",
        detail="Feed the video title + hook to `orbit interview` (category: tool_experiment) for a Threads draft that drives traffic to YouTube. Use the YouTube URL as the source so handoff auto-adds it as a comment.",
    ),
    TemplateItem(
        phase="post-production",
        label="Publish — set Tuesday upload time (or your usual slot)",
        detail="Jeff publishes Tuesdays. Your schedule: pick one consistent day so the algorithm + audience both learn when to expect you.",
    ),
]
