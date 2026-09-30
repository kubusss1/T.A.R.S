"""tars_seo — audyt SEO zrozumiały na pierwszy rzut oka.

    from tars_seo import audit, render_text
    wynik = audit("https://zrobsite.pl")
    print(render_text(wynik))

Główne funkcje:

* :func:`audit` / :func:`audit_html` — audyt adresu / gotowego HTML-a,
* :func:`compare` / :func:`compare_results` — porównanie z konkurencją,
* :func:`save_audit` / :func:`trend` — historia i zmiany w czasie,
* :func:`suggest` — podpowiedzi AI (tytuły, opisy, szkic LocalBusiness),
* :func:`extract_keywords` — najczęstsze frazy,
* :func:`render_text` / :func:`render_telegram` / :func:`render_html` — raporty.
"""
from .ai import suggest
from .checks import CATEGORIES, run_checks
from .core import audit, audit_html, compare, compare_results
from .fetch import fetch_page, fetch_site, urllib_fetcher
from .history import load_history, save_audit, trend
from .keywords import extract_keywords, keyword_presence
from .parse import parse_html
from .report import render_compare_text, render_html, render_telegram, render_text, render_trend_text
from .score import grade, sort_checks, top_fixes, weighted_score

__all__ = [
    "audit", "audit_html", "compare", "compare_results", "suggest", "save_audit", "trend",
    "load_history", "extract_keywords", "keyword_presence", "parse_html", "fetch_page",
    "fetch_site", "urllib_fetcher", "run_checks", "CATEGORIES", "grade", "sort_checks",
    "top_fixes", "weighted_score", "render_text", "render_telegram", "render_html",
    "render_compare_text", "render_trend_text",
]
