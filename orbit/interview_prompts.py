"""Interview prompts that pull original content out of Keith.

Categories derived from his top-10 Threads post patterns:
- Hermes/agent diary entries (day-N posts consistently get 8k-11k views)
- Teaching insights ("教了 400 個學生之後..." hit 8.4k)
- Tool experiments (Cua Driver / DESIGN. / scrape-tools posts hit 10k+)
- Contrarian takes ("廣告代理商請了好幾個..." 8.6k views)
- Workflow / meta-insights about agents

Each prompt is designed to pull SPECIFIC details — not "tell me about X" but
"what surprised you about X today?" The specificity is the trick: it makes Keith
write things he wouldn't think to write unprompted.
"""

# Each category is a list of prompts. Pick one randomly per session.
PROMPTS: dict[str, list[str]] = {
    "agent_diary": [
        "用 Hermes/OpenClaw/任何 agent 今天，有什麼讓你意外的細節？哪一刻你覺得「啊，這個如果能解決就完美了」？",
        "你今天 agent 跑了什麼任務，結果跟你預期差最多的是哪個部分？",
        "如果今天的 agent 工作量要寫進日記，最值得記的「失敗 → 修正」是哪一個？",
        "Day N 寫到今天，你回頭看會發現什麼是當初想錯了的？",
        "今天哪個 prompt / workflow / tool combination 終於跑通了？之前卡在哪？",
    ],
    "teaching_insight": [
        "最近教學生，哪個概念你解釋了三次他們才懂？那個「斷層」在哪裡？",
        "學生問了什麼問題，讓你發現他們對 AI / agent 的根本誤解？",
        "你最近觀察到一群學生共同犯的錯——是什麼？根因是什麼？",
        "如果你只能教學生一件關於 vibe coding / agent 的事，那會是什麼？為什麼不是其他的？",
        "你最近改了一個教學示範或例子，因為原本的太誤導。換成什麼了？",
    ],
    "tool_experiment": [
        "你這週試了什麼新工具/library/MCP server？三句話內：它解決什麼、哪裡好、哪裡爛。",
        "有什麼工具你用了一週就放棄了？放棄的那一刻是什麼觸發的？",
        "你 setup 一個新工具最近一次卡住，是卡在哪個沒寫在 docs 上的細節？",
        "兩個做類似事情的工具——你最後選了哪一個？選的關鍵是什麼？",
        "哪個工具的「marketing 講的能力」跟「實際能力」差最遠？",
    ],
    "contrarian_take": [
        "最近大家在吹什麼 AI 趨勢，但你覺得他們漏看了什麼？",
        "你最近改變想法的是什麼？以前怎麼想，現在怎麼想，什麼讓你改的？",
        "什麼 vibe-coding 的常識其實是錯的？你的證據是？",
        "如果你要勸退別人不要做某件事（買某個工具、學某個東西、加某個 community），會是什麼？為什麼？",
        "你最近遇到什麼「業界都這樣做」的事，但你覺得這樣做反而會出事？",
    ],
    "workflow_insight": [
        "你今天的 agent workflow 比一個月前改進了什麼？具體哪一步換掉了？",
        "你最近發現你重複做某件事三次以上——那件事是什麼？怎麼自動化？",
        "你管理 N 個 agent / N 個 task，現在的瓶頸是什麼？是 orchestration、cost、還是 context？",
        "上週讓你最浪費時間的 workflow 是哪個？你會怎麼重新設計？",
        "你最近發現自己用某個工具的方式跟設計者預期的差很多——是什麼？怎麼用？",
    ],
}


def all_categories() -> list[str]:
    return list(PROMPTS.keys())


def prompts_for(category: str) -> list[str]:
    return PROMPTS.get(category, [])


# Friendly labels for the menu
CATEGORY_LABELS: dict[str, str] = {
    "agent_diary": "🤖 Agent / Hermes 日記 — what happened today",
    "teaching_insight": "🎓 Teaching insight — what your students taught you",
    "tool_experiment": "🔧 Tool experiment — what you tried this week",
    "contrarian_take": "🔥 Contrarian take — where you disagree with consensus",
    "workflow_insight": "⚡ Workflow insight — how your process changed",
}
