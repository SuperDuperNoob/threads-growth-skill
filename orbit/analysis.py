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


def build_pattern_prompt(top_posts: list[dict[str, Any]], bookmarks: list[dict[str, Any]]) -> str:
    examples = "\n\n---\n\n".join(
        f"[{p['views']:,} views, {p['like_rate']}% like rate]\n{p['content']}"
        for p in top_posts[:5]
    )
    sources = "\n\n---\n\n".join(
        f"Author: {b['author']}\nURL: {b['url']}\n{b['text']}"
        for b in bookmarks[:10]
    )
    return f"""You are a Threads content writer. Your job is to write 3 Threads posts for Keith.

Keith's writing style — learned from his TOP PERFORMING posts:

{examples}

KEY PATTERNS in his best posts:
- Opens with a hook: "Someone just did X", "有人剛剛...", a provocative fact, or a personal day-N diary entry
- Short punchy sentences. Line breaks between each thought.
- Ends with why it matters or what changed
- Mix of Traditional Chinese and English is fine (Keith posts in both)
- No hashtags. No emojis unless very sparingly.
- 150-300 characters per post

SOURCE MATERIAL from Keith's X bookmarks (use 1-3 of these as inspiration):

{sources}

Write exactly 3 Threads posts. Number them [1], [2], [3]. Each should use different source material and a different hook style. Output only the posts, no explanations."""
