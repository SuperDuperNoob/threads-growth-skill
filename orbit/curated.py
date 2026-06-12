"""Curated X accounts whose tweets we mine for draft candidates.

Edit this file directly to add/remove accounts. Each handle is the X screen_name
without the @. Grouped only for readability — discovery treats them as one pool.

Selected from analysis of Keith's top 10 Threads posts: brand-name AI launches +
open-source AI infra + indie hacker tools dominated engagement.
"""

OFFICIAL_AI_COMPANIES = [
    "AnthropicAI",
    "OpenAI",
    "OpenAIDevs",
    "Google",
    "GoogleDeepMind",
    "MetaAI",
    "xai",
    "thinkymachines",
    "MistralAI",
]

AI_COMPANY_EMPLOYEES = [
    "sama",
    "karpathy",
    "miramurati",
    "AndrewYNg",
    "ylecun",
]

VIBE_CODING_VOICES = [
    "swyx",
    "simonw",
    "nutlope",
    "levelsio",
    "rauchg",
    "theo",
    "t3dotgg",
]

OPEN_SOURCE_INFRA = [
    "NousResearch",
    "Teknium1",
    "cline",
    "cursor_ai",
    "windsurf_ai",
    "ContinueDev",
    "langchainai",
]

ALL = OFFICIAL_AI_COMPANIES + AI_COMPANY_EMPLOYEES + VIBE_CODING_VOICES + OPEN_SOURCE_INFRA
