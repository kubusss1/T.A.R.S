"""Deterministyczny wybór poziomu modelu (big/mid/small) dla zadania.

Tabela zadań (task, bez rozróżniania wielkości liter):

    big   : code, plan, analysis, seo_audit, reasoning, refactor, debug, review, long
    mid   : chat, summary, classify, seo, translate, email, rewrite, extract, general*
    small : title, label, yesno, tag, short, name, emoji

Nieznane zadanie (oraz "general"/puste) -> decyduje treść promptu:

    1. wygląda na kod (```, def, function, class, import, =>, {...;) -> big
    2. długość > 2000 znaków                                          -> big
    3. długość < 150 znaków                                           -> small
    4. w pozostałych przypadkach                                      -> mid
"""
from __future__ import annotations

import re

TASK_TIERS: dict[str, str] = {
    **dict.fromkeys(("code", "plan", "analysis", "seo_audit", "reasoning",
                     "refactor", "debug", "review", "long"), "big"),
    **dict.fromkeys(("chat", "summary", "classify", "seo", "translate",
                     "email", "rewrite", "extract"), "mid"),
    **dict.fromkeys(("title", "label", "yesno", "tag", "short", "name", "emoji"), "small"),
}

LONG_PROMPT = 2000
SHORT_PROMPT = 150

_CODE_RE = re.compile(
    r"```"
    r"|^\s*def\s+\w+\s*\(|^\s*class\s+\w+.*:\s*$"
    r"|^\s*import\s+[\w.]+\s*$|^\s*from\s+[\w.]+\s+import\s"
    r"|\bfunction\s*\w*\s*\(|\b(const|let|var)\s+\w+\s*=|=>"
    r"|#include\s*<|\bpublic\s+static\b|\bSELECT\s.+\sFROM\s",
    re.MULTILINE,
)


def looks_like_code(text: str) -> bool:
    """True, jeśli tekst zawiera fragmenty kodu."""
    return bool(_CODE_RE.search(text or ""))


def pick_tier(task: str | None, prompt: str | None = "") -> str:
    """Zwraca 'big' | 'mid' | 'small' według tabeli w docstringu modułu."""
    key = (task or "").strip().lower().replace("-", "_").replace(" ", "_")
    if key in TASK_TIERS:
        return TASK_TIERS[key]
    prompt = prompt or ""
    if looks_like_code(prompt) or len(prompt) > LONG_PROMPT:
        return "big"
    if len(prompt) < SHORT_PROMPT:
        return "small"
    return "mid"
