from __future__ import annotations
import json
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULTS: dict[str, Any] = {
    "sample_size": 0,
    "top_hooks": [],
    "optimal_length": {"min": 50, "max": 300, "unit": "words"},
    "best_posting_times": [],
    "top_topics": [],
    "weak_topics": [],
    "ai_tone_flags": [],
    "engagement_benchmarks": {"views_median": 0, "likes_median": 0, "comments_median": 0},
}


class PatternStore:
    def __init__(self, home: Path | None = None):
        self.home = home or Path.home() / ".orbit"
        self.patterns_dir = self.home / "patterns"
        self.patterns_dir.mkdir(parents=True, exist_ok=True)

    def load(self, platform: str) -> dict[str, Any]:
        path = self.patterns_dir / f"{platform}.json"
        if not path.exists():
            return {"platform": platform, "updated_at": None, **DEFAULTS}
        return json.loads(path.read_text())

    def save(self, platform: str, data: dict[str, Any]) -> None:
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        path = self.patterns_dir / f"{platform}.json"
        path.write_text(json.dumps(data, indent=2))

    def recalculate(self, platform: str, db: Any) -> dict[str, Any]:
        rows = db.conn.execute("""
            SELECT p.id, p.published_at, d.hook_type, d.content,
                   m.views, m.likes, m.comments, m.reposts
            FROM posts p
            JOIN drafts d ON d.id = p.draft_id
            LEFT JOIN metrics m ON m.post_id = p.id
            WHERE p.platform = ?
            ORDER BY m.pulled_at DESC
        """, [platform]).fetchall()

        if not rows:
            return self.load(platform)

        views = [r[4] or 0 for r in rows]
        likes = [r[5] or 0 for r in rows]
        comments = [r[6] or 0 for r in rows]

        hook_scores: dict[str, list[int]] = defaultdict(list)
        for r in rows:
            hook_scores[r[2] or "unknown"].append(r[4] or 0)

        median_views = statistics.median(views)
        top_hooks = sorted(
            [
                {
                    "type": ht,
                    "avg_multiplier": round(
                        (sum(scores) / len(scores)) / median_views, 2
                    ) if median_views else 1.0,
                    "sample": len(scores),
                }
                for ht, scores in hook_scores.items()
            ],
            key=lambda x: x["avg_multiplier"],
            reverse=True,
        )

        pattern = self.load(platform)
        pattern.update({
            "sample_size": len(rows),
            "top_hooks": top_hooks,
            "engagement_benchmarks": {
                "views_median": median_views,
                "likes_median": statistics.median(likes),
                "comments_median": statistics.median(comments),
            },
        })
        self.save(platform, pattern)
        return pattern
