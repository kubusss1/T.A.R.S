"""Raporty: terminal (tekst), Telegram (krótko) i samodzielna strona HTML."""
from __future__ import annotations

import html as _html
import json
import math
from urllib.parse import urlsplit

from .checks import CATEGORIES
from .score import LEVEL_LABEL, sort_checks

ICONS = {"ok": "✔", "warning": "!", "critical": "✖", "info": "i"}
TELEGRAM_LIMIT = 4096


def _host(url: str | None) -> str:
    try:
        return urlsplit(url or "").netloc or (url or "")
    except ValueError:
        return url or ""


def _level_for_score(score) -> str:
    if score is None:
        return "info"
    return "ok" if score >= 80 else "warning" if score >= 55 else "critical"


def _bar(score, width: int = 20) -> str:
    if score is None:
        return "·" * width
    filled = int(round(max(0, min(100, score)) / 100 * width))
    return "█" * filled + "░" * (width - filled)


# ==========================================================================
# Tekst (terminal)
# ==========================================================================

def render_text(result: dict, sort: str = "impact", show_ok: bool = True) -> str:
    r = result
    lines = [f"AUDYT SEO  {r.get('final_url') or r.get('url')}", "=" * 64]
    if r.get("error"):
        lines += [f"Błąd: {r['error']}", ""]
    if r.get("blocked") and not r.get("error"):
        lines += ["!!! STRONA JEST NIEWIDOCZNA DLA GOOGLE — napraw to najpierw (wynik ograniczony do 39).", ""]
    lines.append(f"Wynik: {r.get('score', 0)}/100   Ocena: {r.get('grade')} – {r.get('grade_label')}")
    lines.append(f"[{_bar(r.get('score'), 40)}]")
    c = r.get("counts") or {}
    lines.append(f"Krytyczne: {c.get('critical', 0)}   Do poprawy: {c.get('warning', 0)}   "
                 f"OK: {c.get('ok', 0)}")
    lines += ["", "KATEGORIE"]
    for cat in CATEGORIES:
        s = (r.get("categories") or {}).get(cat)
        lines.append(f"  {cat:<12} {_bar(s, 20)} {'–' if s is None else s:>3}")
    top = r.get("top3") or []
    lines += ["", "TOP 3 RZECZY DO POPRAWY"]
    if not top:
        lines.append("  Nic pilnego — gratulacje!")
    for i, t in enumerate(top, 1):
        lines.append(f"  {i}. [{LEVEL_LABEL[t['level']]}] {t['title']}")
        if t.get("detail"):
            lines.append(f"     Znaleziono: {t['detail']}")
        lines.append(f"     Dlaczego:   {t['why']}")
        lines.append(f"     Jak:        {t['fix']}")
    kws = r.get("keywords") or []
    if kws:
        lines += ["", "NAJCZĘSTSZE FRAZY"]
        lines.append("  " + ", ".join(f"{k['phrase']} ({k['count']}×)" for k in kws[:8]))
    sort_label = {"impact": "wg wpływu", "category": "wg kategorii", "level": "wg poziomu"}[sort]
    lines += ["", f"WSZYSTKIE SPRAWDZENIA ({sort_label})"]
    last_cat = None
    for ch in sort_checks(r.get("checks") or [], sort):
        if not show_ok and ch["level"] == "ok":
            continue
        if sort == "category" and ch["category"] != last_cat:
            last_cat = ch["category"]
            lines.append(f"  -- {last_cat} --")
        detail = f" — {ch['detail']}" if ch.get("detail") else ""
        lines.append(f"  {ICONS.get(ch['level'], '?')} {ch['title']}{detail}")
        if ch["level"] in ("warning", "critical"):
            lines.append(f"      → {ch['fix']}")
    ai = r.get("ai")
    if ai:
        lines += ["", "PODPOWIEDZI AI", f"  {ai.get('message', '')}"]
        for t in ai.get("titles") or []:
            lines.append(f"  Tytuł ({t['length']} zn.): {t['text']}")
        for d in ai.get("descriptions") or []:
            lines.append(f"  Opis  ({d['length']} zn.): {d['text']}")
        if ai.get("local_business_json"):
            lines += ["  Szkic LocalBusiness (JSON-LD, uzupełnij pola UZUPEŁNIJ):"]
            lines += ["    " + l for l in ai["local_business_json"].splitlines()]
    tr = r.get("trend")
    if tr:
        lines += ["", "TREND", "  " + render_trend_text(tr).replace("\n", "\n  ")]
    return "\n".join(lines)


def render_compare_text(cmp: dict) -> str:
    a, b = cmp["a"], cmp["b"]
    name = {"a": _host(a["url"]), "b": _host(b["url"]), "remis": "remis", None: "–"}
    lines = ["PORÓWNANIE SEO", "=" * 64,
             f"A: {a['url']}  →  {a['score']}/100 ({a['grade']})",
             f"B: {b['url']}  →  {b['score']}/100 ({b['grade']})", "",
             f"  {'Kategoria':<12} {'A':>4} {'B':>4}   Wygrywa"]
    for row in cmp["categories"]:
        sa = "–" if row["a"] is None else row["a"]
        sb = "–" if row["b"] is None else row["b"]
        lines.append(f"  {row['category']:<12} {sa:>4} {sb:>4}   {name[row['winner']]}")
    lines += ["", f"Wygrane kategorie: A {cmp['wins']['a']} : {cmp['wins']['b']} B",
              f"Ogólnie wygrywa: {name[cmp['overall_winner']]}"]
    if cmp.get("catch_up"):
        lines += ["", "Konkurent (B) ma to dobrze, a A nie:"]
        lines += [f"  • {c['title']} → {c['fix']}" for c in cmp["catch_up"][:8]]
    return "\n".join(lines)


def render_trend_text(tr: dict) -> str:
    lines = [f"{tr.get('url')}: audytów w historii {tr.get('count', 0)}"]
    if tr.get("previous"):
        p, l = tr["previous"], tr["latest"]
        sign = "+" if (tr.get("delta") or 0) > 0 else ""
        lines.append(f"{p['date']}: {p['score']} ({p['grade']})  →  {l['date']}: {l['score']} "
                     f"({l['grade']})   zmiana: {sign}{tr.get('delta')}")
    lines.append(tr.get("message", ""))
    for key, label in (("fixed", "Naprawione"), ("broken", "Zepsute"),
                       ("better", "Lepiej"), ("worse", "Gorzej")):
        items = tr.get(key) or []
        if items:
            lines.append(f"{label}: " + "; ".join(i["title"] for i in items))
    return "\n".join(lines)


# ==========================================================================
# Telegram
# ==========================================================================

def render_telegram(result: dict, include_categories: bool = True) -> str:
    """Krótka wiadomość HTML (parse_mode=HTML), zawsze ≤ 4096 znaków."""
    from tars_telegram.ui import Html, card, esc, footer, progress_bar, status_dot, tg_len

    r = result
    host = _host(r.get("final_url") or r.get("url"))[:60]
    score = r.get("score", 0)
    rows = [("Wynik", f"{score}/100 · {r.get('grade')} ({r.get('grade_label')})"),
            ("Postęp", progress_bar(score, 100))]
    if include_categories:
        for cat in CATEGORIES:
            s = (r.get("categories") or {}).get(cat)
            if s is not None:
                rows.append((cat, Html(f"{status_dot(_level_for_score(s))} {s}")))

    def build(with_fix: bool, fix_len: int = 160) -> str:
        top = r.get("top3") or []
        lines = []
        for i, t in enumerate(top, 1):
            lines.append(f"{i}. {status_dot(t['level'])} <b>{esc(t['title'][:120])}</b>")
            if with_fix:
                fix = t["fix"] if len(t["fix"]) <= fix_len else t["fix"][: fix_len - 1] + "…"
                lines.append(f"   ↳ {esc(fix)}")
        body = "\n".join(lines) if lines else "Nic pilnego — gratulacje! 🎉"
        msg = str(card(f"Audyt SEO · {host}", rows, status=_level_for_score(score)))
        if r.get("blocked") and not r.get("error"):
            msg += "\n\n⛔ <b>Strona jest niewidoczna dla Google — napraw to najpierw!</b>"
        return (msg + "\n\n<b>Top 3 do poprawy</b>\n" + body + "\n\n"
                + footer("Pełny raport: python -m tars_seo audit ADRES --html raport.html"))

    msg = build(True)
    if tg_len(msg) > TELEGRAM_LIMIT:
        msg = build(False)
    if tg_len(msg) > TELEGRAM_LIMIT:  # awaryjnie — nigdy nie przekraczaj limitu
        msg = f"<b>Audyt SEO</b>\nWynik: {score}/100 · {esc(r.get('grade'))}"
    return msg


# ==========================================================================
# HTML
# ==========================================================================

def e(value) -> str:
    return _html.escape("" if value is None else str(value), quote=True)


_CSS = """
:root{--bg:#f6f7f9;--card:#fff;--fg:#16181d;--muted:#5f6673;--line:#e3e6eb;
--ok:#15803d;--warn:#b45309;--crit:#c81e1e;--info:#64748b;--track:#e9ecf1;--accent:#2f5bea;
--ok-bg:#e8f6ee;--warn-bg:#fdf3e4;--crit-bg:#fdecec;--info-bg:#eef1f5;
--radius:14px;--font:system-ui,-apple-system,"Segoe UI",Roboto,Ubuntu,sans-serif}
@media (prefers-color-scheme:dark){:root{--bg:#0f1115;--card:#171a21;--fg:#e8eaee;--muted:#9aa3b2;
--line:#2a2f3a;--ok:#4ade80;--warn:#fbbf24;--crit:#f87171;--info:#94a3b8;--track:#262b35;
--accent:#7aa2ff;--ok-bg:#12261a;--warn-bg:#2a2112;--crit-bg:#2c1515;--info-bg:#1e232c}}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.55 var(--font)}
main{max-width:880px;margin:0 auto;padding:28px 16px 48px}
h1{font-size:1.1rem;margin:0;color:var(--muted);font-weight:600;letter-spacing:.02em}
h2{font-size:1.15rem;margin:0 0 14px}
.url{font-size:1.35rem;font-weight:700;word-break:break-all;margin:4px 0 2px}
.meta{color:var(--muted);font-size:.9rem}
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);padding:20px;margin-top:18px}
.hero{display:flex;gap:24px;align-items:center;flex-wrap:wrap}
.ring{width:150px;height:150px;flex:none}
.ring text{font-family:var(--font);fill:var(--fg)}
.grade{font-size:2.2rem;font-weight:800;line-height:1}
.grade small{font-size:1rem;font-weight:600;color:var(--muted);margin-left:6px}
.counts{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}
.pill{display:inline-block;border-radius:999px;padding:2px 10px;font-size:.8rem;font-weight:600;white-space:nowrap}
.pill.ok{background:var(--ok-bg);color:var(--ok)}.pill.warning{background:var(--warn-bg);color:var(--warn)}
.pill.critical{background:var(--crit-bg);color:var(--crit)}.pill.info{background:var(--info-bg);color:var(--info)}
ol.top{margin:0;padding:0;list-style:none;counter-reset:t}
ol.top li{counter-increment:t;position:relative;padding:0 0 14px 44px;margin-bottom:14px;border-bottom:1px solid var(--line)}
ol.top li:last-child{border-bottom:0;margin-bottom:0;padding-bottom:0}
ol.top li::before{content:counter(t);position:absolute;left:0;top:0;width:30px;height:30px;border-radius:50%;
background:var(--accent);color:#fff;font-weight:700;display:grid;place-items:center}
.t{font-weight:700}.why{color:var(--muted);margin:4px 0}.fix{margin:4px 0}
.fix b,.why b{font-weight:600}
.bars{display:grid;gap:10px}
.bar{display:grid;grid-template-columns:120px 1fr 44px;gap:12px;align-items:center}
.track{height:10px;border-radius:99px;background:var(--track);overflow:hidden}
.fill{height:100%;border-radius:99px}
.fill.ok{background:var(--ok)}.fill.warning{background:var(--warn)}.fill.critical{background:var(--crit)}
.num{text-align:right;font-variant-numeric:tabular-nums;font-weight:600}
h3.cat{font-size:.95rem;margin:18px 0 6px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}
details{border-top:1px solid var(--line)}
details:first-of-type{border-top:0}
summary{cursor:pointer;list-style:none;display:flex;gap:10px;align-items:baseline;padding:10px 0}
summary::-webkit-details-marker{display:none}
summary .dot{width:10px;height:10px;border-radius:50%;flex:none;transform:translateY(1px)}
.dot.ok{background:var(--ok)}.dot.warning{background:var(--warn)}.dot.critical{background:var(--crit)}.dot.info{background:var(--info)}
summary .st{flex:1}
summary .d{display:block;color:var(--muted);font-size:.85rem;word-break:break-word}
details .body{padding:0 0 12px 20px}
.chips{display:flex;flex-wrap:wrap;gap:8px}
.chip{border:1px solid var(--line);border-radius:999px;padding:3px 12px;font-size:.9rem}
.chip b{color:var(--muted);font-weight:600;margin-left:4px}
pre{background:var(--bg);border:1px solid var(--line);border-radius:10px;padding:12px;overflow:auto;font-size:.85rem}
.sugg li{margin-bottom:6px}.len{color:var(--muted);font-size:.85rem}
footer{color:var(--muted);font-size:.85rem;text-align:center;margin-top:28px}
@media (max-width:560px){.bar{grid-template-columns:92px 1fr 36px;gap:8px}.ring{width:120px;height:120px}}
"""


def _ring(score: int, level: str) -> str:
    r = 52
    c = 2 * math.pi * r
    offset = c * (1 - max(0, min(100, score)) / 100)
    color = {"ok": "ok", "warning": "warn", "critical": "crit"}.get(level, "info")
    return (f'<svg class="ring" viewBox="0 0 120 120" role="img" aria-label="Wynik {score} na 100">'
            f'<circle cx="60" cy="60" r="{r}" fill="none" stroke="var(--track)" stroke-width="11"/>'
            f'<circle cx="60" cy="60" r="{r}" fill="none" stroke="var(--{color})" '
            f'stroke-width="11" stroke-linecap="round" stroke-dasharray="{c:.2f}" '
            f'stroke-dashoffset="{offset:.2f}" transform="rotate(-90 60 60)"/>'
            f'<text x="60" y="66" text-anchor="middle" font-size="30" font-weight="800">{score}</text>'
            f'<text x="60" y="86" text-anchor="middle" font-size="11" fill="var(--muted)" '
            f'style="fill:var(--muted)">na 100</text></svg>')


def _check_html(ch: dict) -> str:
    lvl = e(ch.get("level"))
    detail = f'<span class="d">{e(ch["detail"])}</span>' if ch.get("detail") else ""
    fix = f'<p class="fix"><b>Jak naprawić:</b> {e(ch["fix"])}</p>' if ch["level"] != "ok" else ""
    return (f'<details class="{lvl}"><summary><span class="dot {lvl}"></span>'
            f'<span class="st">{e(ch["title"])}{detail}</span>'
            f'<span class="pill {lvl}">{e(LEVEL_LABEL.get(ch["level"], ch["level"]))}</span></summary>'
            f'<div class="body"><p class="why"><b>Dlaczego to ważne:</b> {e(ch["why"])}</p>{fix}</div></details>')


def render_html(result: dict, sort: str = "category") -> str:
    """Samodzielna strona HTML (bez zewnętrznych plików), jasny i ciemny motyw."""
    r = result
    score = int(r.get("score") or 0)
    level = _level_for_score(score)
    counts = r.get("counts") or {}
    url = r.get("final_url") or r.get("url") or ""
    parts = [
        "<!doctype html><html lang=\"pl\"><head><meta charset=\"utf-8\">",
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">",
        "<meta name=\"color-scheme\" content=\"light dark\">",
        f"<title>Audyt SEO – {e(_host(url))}</title><style>{_CSS}</style></head><body><main>",
        f'<h1>Audyt SEO · TARS</h1><div class="url">{e(url)}</div>',
        f'<div class="meta">{e(r.get("audited_at", ""))}'
        + (f" · strona: „{e((r.get('page') or {}).get('title') or 'bez tytułu')}”" if r.get("page") else "")
        + "</div>",
    ]
    if r.get("error"):
        parts.append(f'<div class="card"><span class="pill critical">Błąd</span> {e(r["error"])}</div>')
    if r.get("blocked") and not r.get("error"):
        parts.append('<div class="card"><span class="pill critical">Uwaga</span> Strona jest '
                     'niewidoczna dla Google — napraw najpierw problemy oznaczone jako krytyczne '
                     'w „Top 3” (wynik ograniczono do 39).</div>')
    parts.append(
        f'<section class="card hero">{_ring(score, level)}<div>'
        f'<div class="grade">{e(r.get("grade"))}<small>{e(r.get("grade_label"))}</small></div>'
        f'<div class="meta" style="margin-top:6px">Ocena od A (świetnie) do F (bardzo źle)</div>'
        f'<div class="counts"><span class="pill critical">Krytyczne: {counts.get("critical", 0)}</span>'
        f'<span class="pill warning">Do poprawy: {counts.get("warning", 0)}</span>'
        f'<span class="pill ok">OK: {counts.get("ok", 0)}</span></div></div></section>')

    top = r.get("top3") or []
    parts.append('<section class="card"><h2>Top 3 rzeczy do poprawy</h2>')
    if top:
        parts.append('<ol class="top">')
        for t in top:
            parts.append(
                f'<li><div class="t">{e(t["title"])} <span class="pill {e(t["level"])}">'
                f'{e(LEVEL_LABEL[t["level"]])}</span></div>'
                + (f'<div class="meta">{e(t["detail"])}</div>' if t.get("detail") else "")
                + f'<p class="why">{e(t["why"])}</p><p class="fix"><b>Zrób tak:</b> {e(t["fix"])}</p></li>')
        parts.append("</ol>")
    else:
        parts.append("<p>Nic pilnego — gratulacje!</p>")
    parts.append("</section>")

    parts.append('<section class="card"><h2>Kategorie</h2><div class="bars">')
    for cat in CATEGORIES:
        s = (r.get("categories") or {}).get(cat)
        if s is None:
            continue
        parts.append(f'<div class="bar"><span>{e(cat)}</span><div class="track">'
                     f'<div class="fill {_level_for_score(s)}" style="width:{int(s)}%"></div></div>'
                     f'<span class="num">{int(s)}</span></div>')
    parts.append("</div></section>")

    parts.append('<section class="card"><h2>Wszystkie sprawdzenia</h2>')
    checks = sort_checks(r.get("checks") or [], sort)
    if sort == "category":
        for cat in CATEGORIES:
            group = [c for c in checks if c.get("category") == cat]
            if group:
                parts.append(f'<h3 class="cat">{e(cat)}</h3>')
                parts.extend(_check_html(c) for c in group)
    else:
        parts.extend(_check_html(c) for c in checks)
    parts.append("</section>")

    kws = r.get("keywords") or []
    if kws:
        parts.append('<section class="card"><h2>Najczęstsze frazy na stronie</h2><div class="chips">')
        parts.extend(f'<span class="chip">{e(k["phrase"])}<b>{int(k["count"])}×</b></span>' for k in kws)
        parts.append("</div>")
        pres = r.get("keyword_presence")
        if pres:
            yes = lambda v: "✔" if v else "✖"  # noqa: E731
            parts.append(f'<p class="meta">„{e(kws[0]["phrase"])}” — tytuł {yes(pres["title"])} · '
                         f'H1 {yes(pres["h1"])} · opis {yes(pres["meta"])}</p>')
        parts.append("</section>")

    ai = r.get("ai")
    if ai:
        parts.append(f'<section class="card sugg"><h2>Podpowiedzi AI</h2><p class="meta">{e(ai.get("message"))}</p>')
        for key, label in (("titles", "Tytuły"), ("descriptions", "Opisy meta")):
            if ai.get(key):
                parts.append(f"<h3 class=\"cat\">{label}</h3><ul>")
                parts.extend(f'<li>{e(x["text"])} <span class="len">({int(x["length"])} zn.)</span></li>'
                             for x in ai[key])
                parts.append("</ul>")
        if ai.get("local_business"):
            parts.append('<h3 class="cat">Szkic LocalBusiness (JSON-LD)</h3>'
                         f'<pre>{e(json.dumps(ai["local_business"], ensure_ascii=False, indent=2))}</pre>')
        parts.append("</section>")

    tr = r.get("trend")
    if tr and tr.get("previous"):
        parts.append(f'<section class="card"><h2>Zmiana od ostatniego audytu</h2><p>{e(tr.get("message"))}</p>')
        for key, label in (("fixed", "Naprawione"), ("broken", "Zepsute")):
            if tr.get(key):
                parts.append(f"<p><b>{label}:</b> " + "; ".join(e(i["title"]) for i in tr[key]) + "</p>")
        parts.append("</section>")

    parts.append("<footer>Raport wygenerował TARS · ZrobSite</footer></main></body></html>")
    return "".join(parts)
