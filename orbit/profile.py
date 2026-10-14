"""Personal profile for the Threads growth engine — the ONLY place our identity lives.

Everything downstream (analysis.py prompts, critic.py, scheduling.py) reads
from here, so the fork's Keith-specific DNA is replaced in one place instead of
scattered. This is the file you edit to change who "we" are.

LANGUAGE POLICY — HARD: we publish in **Malaysian Malay** and **English** on
Threads, nothing else. No Chinese, no Indonesian, no other languages. Code-switch
Malay + English the way a real MY creator does (everyday Malay, English for
product/brand/technical terms). This is non-negotiable and overrides any of the
fork's Chinese-native templates.
"""
from __future__ import annotations

# Public identity / voice
CREATOR = "the Malaysian creator"        # used only in invisible prompt narration
VOICE_NAME = "Malay-English (MY)"        # label in reports
MARKET = "Malaysia (MYT)"
LANGUAGES = ("Malay", "English")         # THE ONLY languages we publish in

# Posting slots — KL time (UTC+8, no DST). Tune to real MY engagement data.
SLOT_LABEL = "MYT"
SLOT_HOURS = (9, 16, 21)                 # 9am / 4pm / 9pm Malaysia time

# Baseline like-rate for the recovery-mode guard. Derived from real data when
# available (see _format_recent_performance); this is the fallback floor.
BASELINE_LIKE_RATE = 1.17

# Hook language mix: our lane ships Malay hooks with English product/brand names
# (code-switch), NOT Chinese. The four hook archetypes stay structurally the
# same as the fork's proven set, but rendered in MY voice.
