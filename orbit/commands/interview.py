"""orbit interview — turn Keith's experiments and teaching into Threads drafts.

Static prompts derived from his top-performing posts pull original content out
of him. Claude then drafts in his voice using the same pattern-match prompt
structure as `orbit draft`.
"""
from __future__ import annotations
import os
import random
import sys
from datetime import datetime, timezone

import anthropic
import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from orbit.analysis import build_pattern_prompt, extract_top_patterns
from orbit.config import Config
from orbit.db import DB
from orbit.interview_prompts import CATEGORY_LABELS, all_categories, prompts_for

app = typer.Typer(help="Generate original Threads drafts from your experiments + teaching")
console = Console()


@app.callback(invoke_without_command=True)
def interview(
    category: str = typer.Option(
        None, "--category", "-c",
        help="Skip the category picker — go straight to prompts in this category",
    ),
) -> None:
    """Ask you a sharp question, turn your answer into 3 Threads drafts."""
    cfg = Config()
    db = DB()

    api_key = os.environ.get("ANTHROPIC_API_KEY") or cfg.get("anthropic.api_key")
    if not api_key:
        console.print("\n[red]✗ ANTHROPIC_API_KEY not set.[/red]")
        console.print("  Run: [cyan]orbit setup --platform anthropic[/cyan]\n")
        raise typer.Exit(1)

    # Step 1: pick category
    chosen = category or _pick_category()
    if chosen not in CATEGORY_LABELS:
        console.print(f"\n[red]Unknown category '{chosen}'.[/red] "
                      f"Options: {', '.join(all_categories())}\n")
        raise typer.Exit(1)

    # Step 2: show 3 prompts from that category, let user reshuffle or pick
    prompt_text = _pick_prompt(chosen)
    if not prompt_text:
        console.print("\n[dim]Cancelled.[/dim]\n")
        return

    # Step 3: collect the answer (multi-line until empty line or `.`)
    console.print()
    console.print(Panel(prompt_text, title="[bold cyan]Question[/bold cyan]", border_style="cyan"))
    console.print()
    console.print("[dim]Type your answer. Multi-line OK. Submit with a single[/dim] [cyan].[/cyan] "
                  "[dim]on its own line.[/dim]")
    answer = _collect_multiline()
    if not answer.strip():
        console.print("\n[dim]Empty answer. Discarded.[/dim]\n")
        return

    # Step 4: generate drafts using same pattern-match as orbit draft
    rows = db.conn.execute("""
        SELECT d.content, m.views, m.likes
        FROM posts p
        JOIN drafts d ON d.id = p.draft_id
        JOIN metrics m ON m.post_id = p.id
        WHERE p.platform = 'threads'
        ORDER BY m.views DESC
        LIMIT 10
    """).fetchall()
    if not rows:
        console.print("\n[yellow]No Threads engagement data yet.[/yellow] "
                      "Run [cyan]orbit sync --platform threads[/cyan] first so I can match your voice.\n")
        raise typer.Exit(1)

    top_posts = [{"content": r[0], "views": r[1], "likes": r[2]} for r in rows]
    top_patterns = extract_top_patterns(top_posts, top_n=5)
    full_prompt = _build_interview_prompt(top_patterns, prompt_text, answer)

    console.print("\n[dim]Generating drafts from your answer with Claude...[/dim]\n")
    ai = anthropic.Anthropic(api_key=api_key)
    msg = ai.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": full_prompt}],
    )
    raw = msg.content[0].text

    # Reuse existing draft display + save loop from orbit.commands.draft
    from orbit.commands.draft import _parse_drafts, _select_loop, _post_save_action
    drafts = _parse_drafts(raw)
    if not drafts:
        console.print("[red]✗ Could not parse drafts from Claude response.[/red]")
        console.print(raw)
        raise typer.Exit(1)

    picks = _select_loop(drafts, ai, full_prompt)
    if not picks:
        console.print("\n[dim]Discarded. Run again for fresh drafts.[/dim]\n")
        return

    saved_ids: list[int] = []
    now = datetime.now(timezone.utc).isoformat()
    for idx in picks:
        idea_id = db.conn["ideas"].insert({
            "title": drafts[idx][:80],
            "source": f"interview:{chosen}",
            "status": "draft",
            "created_at": now,
        }).last_pk
        draft_id = db.conn["drafts"].insert({
            "idea_id": idea_id,
            "platform": "threads",
            "content": drafts[idx],
            "status": "draft",
            "created_at": now,
        }).last_pk
        saved_ids.append(draft_id)

    saved_label = ", ".join(str(i + 1) for i in picks)
    console.print(f"\n[green]✓ Saved draft(s) {saved_label}.[/green]\n")

    _post_save_action(db, saved_ids, [drafts[i] for i in picks], cfg)


# --- helpers ---

def _pick_category() -> str:
    """Show the category menu, return the chosen category key."""
    cats = all_categories()
    console.print("\n[bold]What kind of content do you want to write?[/bold]\n")
    for i, cat in enumerate(cats, 1):
        console.print(f"  [cyan]{i}[/cyan]  {CATEGORY_LABELS[cat]}")
    console.print(f"  [cyan]r[/cyan]  random category\n")
    raw = Prompt.ask("Choose", default="1").strip().lower()
    if raw == "r" or raw == "":
        return random.choice(cats)
    if raw.isdigit() and 1 <= int(raw) <= len(cats):
        return cats[int(raw) - 1]
    return cats[0]


def _pick_prompt(category: str) -> str | None:
    """Show 3 prompts from category, let user pick, reshuffle, or cancel."""
    pool = list(prompts_for(category))
    while True:
        if len(pool) >= 3:
            shown = random.sample(pool, 3)
        else:
            shown = pool[:]
        console.print(f"\n[bold]{CATEGORY_LABELS[category]}[/bold]\n")
        for i, p in enumerate(shown, 1):
            console.print(f"  [cyan]{i}[/cyan]  {p}\n")
        console.print("  [cyan]r[/cyan]  reshuffle  ·  [cyan]Enter[/cyan]  cancel")
        raw = Prompt.ask("Pick", default="").strip().lower()
        if raw == "":
            return None
        if raw == "r":
            continue
        if raw.isdigit() and 1 <= int(raw) <= len(shown):
            return shown[int(raw) - 1]
        # Invalid → reshuffle


def _collect_multiline() -> str:
    """Read multi-line stdin until a single '.' on a line or EOF."""
    lines: list[str] = []
    try:
        while True:
            line = input()
            if line.strip() == ".":
                break
            lines.append(line)
    except EOFError:
        pass
    return "\n".join(lines).strip()


def _build_interview_prompt(top_patterns, question: str, answer: str) -> str:
    """Construct a Claude prompt that turns Keith's freeform answer into 3 Threads drafts."""
    from orbit.analysis import build_pattern_prompt  # for consistency, but we customize

    examples = "\n\n---\n\n".join(
        f"[{p['views']:,} views, {p['like_rate']}% like rate]\n{p['content']}"
        for p in top_patterns[:5]
    )
    return f"""You are a Threads content writer for Keith.

Keith's writing style — learned from his TOP PERFORMING posts:

{examples}

KEY PATTERNS in his best posts:
- Opens with a hook: "Someone just did X", "有人剛剛...", a personal day-N diary entry, or a concrete number
- Short punchy sentences. Line breaks between each thought.
- Ends with why it matters, what changed, or a sharp observation
- Mix of Traditional Chinese and English is fine (Keith posts in both)
- No hashtags. Sparing emojis at most.
- 150-300 characters per post

Today Keith was asked this question:

> {question}

He answered:

\"\"\"
{answer}
\"\"\"

Write exactly 3 Threads posts based on his answer. Each should:
- Use a different hook style and pull out a different angle from his answer
- Sound like HIM (use his voice patterns from the examples above)
- Be concrete and specific — use exact numbers, tool names, and details he mentioned
- Be ORIGINAL — based on his lived experience, not generic AI commentary

Number them [1], [2], [3]. Output only the posts, no explanations."""
