"""Widoki zakładki „Statusy i analityka”: HTML (panel), Telegram (HTML parse mode) i tekst (CLI)."""
from __future__ import annotations

import html
from datetime import date, datetime, timedelta
from urllib.parse import urlparse

TELEGRAM_LIMIT = 4096

HEALTH_LABELS = {"ok": "OK", "warning": "Ostrzeżenie", "critical": "Krytyczny", "offline": "Offline"}
HEALTH_ICONS = {"ok": "✓", "warning": "!", "critical": "✕", "offline": "–"}
TELEGRAM_DOTS = {"ok": "🟢", "warning": "🟡", "critical": "🔴", "offline": "⚫"}
SORT_LABELS = {
    "health": "stan",
    "name": "nazwa",
    "visits": "wizyty",
    "consent": "zgody",
    "updates": "aktualizacje",
}


# ---------------------------------------------------------------- formatowanie


def fmt_int(value: int | float | None) -> str:
    """12345 -> '12 345' (spacja nierozdzielająca), None -> '—'."""
    if value is None:
        return "—"
    return f"{int(value):,}".replace(",", " ")


def fmt_pct(value: float | None, signed: bool = False) -> str:
    """61.5 -> '61,5%', ze znakiem: '+4,2%' / '−3%'."""
    if value is None:
        return "—"
    text = f"{abs(value):.1f}".rstrip("0").rstrip(".").replace(".", ",")
    if signed:
        sign = "+" if value > 0 else ("−" if value < 0 else "±")
        return f"{sign}{text}%"
    return f"{'−' if value < 0 else ''}{text}%"


def fmt_days(value: int | None) -> str:
    if value is None:
        return "—"
    word = "dzień" if abs(value) == 1 else "dni"
    return f"{value} {word}" if value >= 0 else f"wygasł {abs(value)} {word} temu"


def row_state(row: dict) -> str:
    """Stan do wyświetlenia: ok / warning / critical / offline."""
    return "offline" if not row.get("online") else str(row.get("health") or "critical")


def _tg_len(text: str) -> int:
    """Długość jak w Telegramie (jednostki UTF-16 — emoji liczą się podwójnie)."""
    return len(text.encode("utf-16-le", "surrogatepass")) // 2


def _e(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _tg(value: object) -> str:
    """Escape dla Telegram HTML parse mode (&, <, >)."""
    return html.escape("" if value is None else str(value), quote=False)


def _safe_href(url: str) -> str | None:
    parsed = urlparse(url or "")
    if parsed.scheme in ("http", "https") and parsed.netloc:
        return url
    return None


def _host(url: str) -> str:
    return urlparse(url or "").netloc or url or ""


def _generated_label(dashboard: dict) -> str:
    raw = dashboard.get("generated_at")
    try:
        return datetime.fromisoformat(str(raw)).strftime("%d.%m.%Y %H:%M")
    except (TypeError, ValueError):
        return ""


# ---------------------------------------------------------------- HTML

_CSS = """
.tars-zs{--zs-page:#f9f9f7;--zs-surface:#fcfcfb;--zs-ink:#0b0b0b;--zs-ink-2:#52514e;--zs-muted:#898781;
--zs-line:#e1e0d9;--zs-border:rgba(11,11,11,.10);--zs-accent:#2a78d6;--zs-good:#0ca30c;--zs-good-text:#006300;
--zs-warn:#fab219;--zs-crit:#d03b3b;--zs-off:#898781;--zs-radius:12px;
color:var(--zs-ink);background:var(--zs-page);font:14px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
padding:16px;box-sizing:border-box}
@media (prefers-color-scheme:dark){.tars-zs:not([data-theme=light]){--zs-page:#0d0d0d;--zs-surface:#1a1a19;
--zs-ink:#fff;--zs-ink-2:#c3c2b7;--zs-line:#2c2c2a;--zs-border:rgba(255,255,255,.10);--zs-accent:#3987e5;
--zs-good-text:#0ca30c;--zs-crit:#e05555}}
.tars-zs[data-theme=dark]{--zs-page:#0d0d0d;--zs-surface:#1a1a19;--zs-ink:#fff;--zs-ink-2:#c3c2b7;--zs-line:#2c2c2a;
--zs-border:rgba(255,255,255,.10);--zs-accent:#3987e5;--zs-good-text:#0ca30c;--zs-crit:#e05555}
.tars-zs *{box-sizing:border-box}
.tars-zs h2{font-size:18px;font-weight:600;margin:0}
.tars-zs .zs-head{display:flex;flex-wrap:wrap;align-items:baseline;justify-content:space-between;gap:4px 16px;margin-bottom:14px}
.tars-zs .zs-meta{color:var(--zs-muted);font-size:12px}
.tars-zs .zs-tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin-bottom:16px}
.tars-zs .zs-tile{background:var(--zs-surface);border:1px solid var(--zs-border);border-radius:var(--zs-radius);padding:10px 12px}
.tars-zs .zs-tile-label{color:var(--zs-ink-2);font-size:12px}
.tars-zs .zs-tile-value{font-size:22px;font-weight:600;margin-top:2px}
.tars-zs .zs-tile-sub{font-size:12px;color:var(--zs-muted)}
.tars-zs .zs-card{background:var(--zs-surface);border:1px solid var(--zs-border);border-radius:var(--zs-radius);overflow:hidden}
.tars-zs table{width:100%;border-collapse:collapse}
.tars-zs th{text-align:left;font-weight:500;font-size:12px;color:var(--zs-muted);padding:10px 12px;border-bottom:1px solid var(--zs-line);white-space:nowrap}
.tars-zs td{padding:10px 12px;border-bottom:1px solid var(--zs-line);vertical-align:top}
.tars-zs tr:last-child td{border-bottom:0}
.tars-zs .zs-num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.tars-zs .zs-site a{color:var(--zs-ink);font-weight:600;text-decoration:none}
.tars-zs .zs-site a:hover{text-decoration:underline}
.tars-zs .zs-host{color:var(--zs-muted);font-size:12px}
.tars-zs .zs-reasons{margin:4px 0 0;padding:0;list-style:none;color:var(--zs-ink-2);font-size:12px}
.tars-zs .zs-state{display:inline-flex;align-items:center;gap:6px;white-space:nowrap;font-size:13px}
.tars-zs .zs-dot{width:10px;height:10px;border-radius:50%;flex:none;background:var(--zs-off)}
.tars-zs .zs-ok .zs-dot{background:var(--zs-good)}.tars-zs .zs-warning .zs-dot{background:var(--zs-warn)}
.tars-zs .zs-critical .zs-dot{background:var(--zs-crit)}
.tars-zs .zs-delta{display:block;font-size:12px;color:var(--zs-muted)}
.tars-zs .zs-up{color:var(--zs-good-text)}.tars-zs .zs-down{color:var(--zs-crit)}
.tars-zs .zs-alert{color:var(--zs-crit);font-weight:600}
.tars-zs .zs-spark{display:block;width:120px;height:28px;overflow:visible}
.tars-zs .zs-spark polyline{fill:none;stroke:var(--zs-accent);stroke-width:1.5;stroke-linejoin:round;stroke-linecap:round}
.tars-zs .zs-spark .zs-last{fill:var(--zs-accent)}
.tars-zs .zs-spark .zs-hit{fill:transparent}
.tars-zs .zs-spark .zs-hit:hover{fill:var(--zs-accent);fill-opacity:.25}
.tars-zs .zs-empty{padding:24px;text-align:center;color:var(--zs-muted)}
@media (max-width:760px){
.tars-zs thead{display:none}
.tars-zs table,.tars-zs tbody,.tars-zs tr,.tars-zs td{display:block;width:100%}
.tars-zs tr{border-bottom:1px solid var(--zs-line);padding:6px 0}
.tars-zs tr:last-child{border-bottom:0}
.tars-zs td{border:0;padding:4px 12px;display:flex;justify-content:space-between;gap:12px;text-align:right}
.tars-zs td::before{content:attr(data-label);color:var(--zs-muted);font-size:12px;text-align:left}
.tars-zs td.zs-site{display:block;text-align:left}.tars-zs td.zs-site::before{content:none}
.tars-zs td .zs-delta{display:inline;margin-left:6px}
}
"""


def sparkline_svg(values: list[int], end: str | None = None, width: int = 120, height: int = 28) -> str:
    """Mała linia trendu (inline SVG) z natywnymi podpowiedziami dla każdego dnia."""
    values = [max(0, int(v)) for v in values or []]
    if not values:
        return '<span class="zs-host">brak danych</span>'
    end_date = None
    try:
        end_date = date.fromisoformat(end) if end else None
    except ValueError:
        end_date = None
    n = len(values)
    peak = max(values) or 1
    pad = 2
    step = (width - 2 * pad) / max(1, n - 1)

    def xy(i: int, v: int) -> tuple[float, float]:
        return pad + i * step, height - pad - (v / peak) * (height - 2 * pad)

    points = " ".join(f"{x:.1f},{y:.1f}" for x, y in (xy(i, v) for i, v in enumerate(values)))
    lx, ly = xy(n - 1, values[-1])
    total = sum(values)
    label = f"Wizyty dziennie, ostatnie {n} dni: razem {fmt_int(total)}, maks. {fmt_int(max(values))}"
    hits = []
    for i, v in enumerate(values):
        x, _ = xy(i, v)
        day = (end_date - timedelta(days=n - 1 - i)).strftime("%d.%m") if end_date else f"dzień {i + 1}"
        hits.append(
            f'<rect class="zs-hit" x="{x - step / 2:.1f}" y="0" width="{max(step, 1):.1f}" height="{height}">'
            f"<title>{_e(day)}: {fmt_int(v)}</title></rect>"
        )
    return (
        f'<svg class="zs-spark" viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'role="img" aria-label="{_e(label)}"><title>{_e(label)}</title>'
        f'<polyline points="{points}"/><circle class="zs-last" cx="{lx:.1f}" cy="{ly:.1f}" r="2.5"/>'
        f'{"".join(hits)}</svg>'
    )


def _delta_html(change: float | None, prefix: str = "") -> str:
    if change is None:
        return f'<span class="zs-delta">{_e(prefix)}brak porównania</span>' if prefix else ""
    cls = "zs-up" if change > 0 else ("zs-down" if change < 0 else "")
    arrow = "▲ " if change > 0 else ("▼ " if change < 0 else "")
    return f'<span class="zs-delta {cls}">{_e(prefix)}{arrow}{_e(fmt_pct(change, signed=True))}</span>'


def _state_html(state: str) -> str:
    return (
        f'<span class="zs-state zs-{_e(state)}"><span class="zs-dot" aria-hidden="true"></span>'
        f'{_e(HEALTH_ICONS.get(state, "?"))} {_e(HEALTH_LABELS.get(state, state))}</span>'
    )


def _tile(label: str, value: str, sub: str = "") -> str:
    return (
        f'<div class="zs-tile"><div class="zs-tile-label">{_e(label)}</div>'
        f'<div class="zs-tile-value">{value}</div>'
        f'{f"<div class=zs-tile-sub>{sub}</div>" if sub else ""}</div>'
    )


def _site_row(row: dict) -> str:
    state = row_state(row)
    href = _safe_href(row.get("url", ""))
    name = _e(row.get("name"))
    name_html = f'<a href="{_e(href)}" target="_blank" rel="noopener noreferrer">{name}</a>' if href else name
    reasons = list(row.get("reasons") or [])
    if row.get("analytics_error"):
        reasons.append(f"Analityka: {row['analytics_error']}")
    reasons_html = (
        '<ul class="zs-reasons">' + "".join(f"<li>{_e(r)}</li>" for r in reasons[:6]) + "</ul>" if reasons else ""
    )
    ssl_days = row.get("ssl_days")
    ssl_cls = ' class="zs-alert"' if ssl_days is not None and ssl_days <= 7 else ""
    updates = row.get("updates")
    upd_cls = ' class="zs-alert"' if updates and updates >= 5 else ""
    consent_sub = (
        f'<span class="zs-delta">{_e(fmt_int(row.get("consent_total")))} decyzji</span>'
        if row.get("consent_total")
        else ""
    )

    def num(label: str, inner: str) -> str:
        return f'<td class="zs-num" data-label="{_e(label)}"><span class="zs-val">{inner}</span></td>'

    return (
        f'<tr class="zs-row zs-{_e(state)}">'
        f'<td class="zs-site" data-label="Strona">{name_html}<div class="zs-host">{_e(_host(row.get("url", "")))}</div>'
        f"{reasons_html}</td>"
        f'<td data-label="Stan">{_state_html(state)}</td>'
        + num("Aktualizacje", f"<span{upd_cls}>{_e(fmt_int(updates))}</span>")
        + num("SSL", f"<span{ssl_cls}>{_e(fmt_days(ssl_days))}</span>")
        + num("Wizyty 7 dni", _e(fmt_int(row.get("visits_7d"))) + _delta_html(row.get("visits_7d_change")))
        + num("Wizyty 30 dni", _e(fmt_int(row.get("visits_30d"))) + _delta_html(row.get("visits_30d_change")))
        + num("Akceptacja cookies", _e(fmt_pct(row.get("consent_rate"))) + consent_sub)
        + f'<td data-label="Trend 30 dni">{sparkline_svg(row.get("sparkline") or [], row.get("sparkline_end"))}</td>'
        "</tr>"
    )


def render_html(dashboard: dict, full_page: bool = True, theme: str | None = None) -> str:
    """Samodzielny widok zakładki (bez zewnętrznych zasobów).

    full_page=False zwraca sam fragment <section> ze stylami do osadzenia w panelu.
    theme: None (wg systemu), "light" lub "dark".
    """
    totals = dashboard.get("totals") or {}
    rows = dashboard.get("sites") or []
    by_health = totals.get("by_health") or {}
    title = str(dashboard.get("title") or "Statusy i analityka")
    theme_attr = f' data-theme="{_e(theme)}"' if theme in ("light", "dark") else ""

    tiles = "".join(
        [
            _tile(
                "Strony online",
                f"{_e(totals.get('online', 0))}/{_e(totals.get('sites', 0))}",
                _e(f"offline: {totals.get('offline', 0)}"),
            ),
            _tile(
                "Stan",
                f"{_e(by_health.get('critical', 0))} / {_e(by_health.get('warning', 0))} / {_e(by_health.get('ok', 0))}",
                "krytyczne / ostrzeżenia / OK",
            ),
            _tile("Aktualizacje", _e(fmt_int(totals.get("updates", 0))), _e(f"SSL wygasa wkrótce: {totals.get('ssl_expiring', 0)}")),
            _tile("Wizyty 30 dni", _e(fmt_int(totals.get("visits_30d", 0))), _delta_html(totals.get("visits_30d_change"), "vs poprz. 30 dni: ")),
            _tile("Wizyty 7 dni", _e(fmt_int(totals.get("visits_7d", 0))), _delta_html(totals.get("visits_7d_change"), "vs poprz. 7 dni: ")),
            _tile(
                "Akceptacja cookies",
                _e(fmt_pct(totals.get("consent_rate"))),
                _e(f"{fmt_int(totals.get('consent_total', 0))} decyzji w 30 dni"),
            ),
        ]
    )

    if rows:
        body = (
            '<div class="zs-card"><table><thead><tr>'
            "<th>Strona</th><th>Stan</th><th class=zs-num>Aktualizacje</th><th class=zs-num>SSL</th>"
            "<th class=zs-num>Wizyty 7 dni</th><th class=zs-num>Wizyty 30 dni</th>"
            "<th class=zs-num>Akceptacja cookies</th><th>Trend 30 dni</th>"
            "</tr></thead><tbody>" + "".join(_site_row(r) for r in rows) + "</tbody></table></div>"
        )
    else:
        body = '<div class="zs-card zs-empty">Brak stron w konfiguracji (sites.json).</div>'

    sort_label = SORT_LABELS.get(str(dashboard.get("sort")), str(dashboard.get("sort") or ""))
    generated = _generated_label(dashboard)
    meta = " · ".join(p for p in (f"Aktualizacja: {generated}" if generated else "", f"Sortowanie: {sort_label}") if p)
    section = (
        f'<section class="tars-zs"{theme_attr} aria-label="{_e(title)}"><style>{_CSS}</style>'
        f'<div class="zs-head"><h2>{_e(title)}</h2><span class="zs-meta">{_e(meta)}</span></div>'
        f'<div class="zs-tiles">{tiles}</div>{body}'
        '<p class="zs-meta">Wizyty = suma dziennych unikalnych odwiedzających (bez cookies). '
        "Akceptacja = pełne „Akceptuj wszystkie” / wszystkie decyzje w banerze.</p></section>"
    )
    if not full_page:
        return section
    return (
        '<!doctype html><html lang="pl"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{_e(title)} · ZrobSite</title>"
        "<style>html,body{margin:0;background:#f9f9f7}"
        "@media (prefers-color-scheme:dark){html,body{background:#0d0d0d}}</style>"
        f"</head><body>{section}</body></html>"
    )


# ---------------------------------------------------------------- Telegram


def render_telegram(dashboard: dict, limit: int = TELEGRAM_LIMIT) -> str:
    """Zwięzła wiadomość Telegram (parse_mode=HTML)."""
    totals = dashboard.get("totals") or {}
    by_health = totals.get("by_health") or {}
    rows = dashboard.get("sites") or []
    lines = [
        f"<b>📊 {_tg(dashboard.get('title') or 'Statusy i analityka')}</b>",
        f"🔴 {by_health.get('critical', 0)}  🟡 {by_health.get('warning', 0)}  🟢 {by_health.get('ok', 0)}"
        f"  ·  offline: {totals.get('offline', 0)}  ·  aktualizacje: {totals.get('updates', 0)}",
        f"👥 Wizyty 30 dni: {_tg(fmt_int(totals.get('visits_30d', 0)))}"
        + (f" ({_tg(fmt_pct(totals.get('visits_30d_change'), signed=True))})" if totals.get("visits_30d_change") is not None else ""),
        f"🍪 Akceptacja cookies: {_tg(fmt_pct(totals.get('consent_rate')))}",
        "",
    ]
    for row in rows:
        state = row_state(row)
        parts = []
        if row.get("online"):
            if row.get("updates"):
                parts.append(f"🔄 {row['updates']}")
            if row.get("ssl_days") is not None and row["ssl_days"] <= 21:
                parts.append(f"🔒 {_tg(fmt_days(row['ssl_days']))}")
            visits = f"👥 {_tg(fmt_int(row.get('visits_30d')))}"
            if row.get("visits_30d_change") is not None:
                visits += f" ({_tg(fmt_pct(row['visits_30d_change'], signed=True))})"
            parts.append(visits)
            if row.get("consent_rate") is not None:
                parts.append(f"🍪 {_tg(fmt_pct(row['consent_rate']))}")
        line = f"{TELEGRAM_DOTS.get(state, '⚪')} <b>{_tg(row.get('name'))}</b>"
        if parts:
            line += " — " + " · ".join(parts)
        lines.append(line)
        if state != "ok":
            for reason in (row.get("reasons") or [])[:3]:
                lines.append(f"    • {_tg(reason)}")
    if not rows:
        lines.append("Brak stron w konfiguracji.")

    text = "\n".join(lines).rstrip()
    if _tg_len(text) <= limit:
        return text
    suffix = "\n… (lista skrócona)"
    out: list[str] = []
    size = 0
    for line in lines:
        if size + _tg_len(line) + 1 + _tg_len(suffix) > limit:
            break
        out.append(line)
        size += _tg_len(line) + 1
    return "\n".join(out).rstrip() + suffix


# ---------------------------------------------------------------- tekst (CLI)


def render_text(dashboard: dict) -> str:
    """Podsumowanie tekstowe po polsku (konsola)."""
    totals = dashboard.get("totals") or {}
    by_health = totals.get("by_health") or {}
    lines = [
        f"{dashboard.get('title') or 'Statusy i analityka'} — {_generated_label(dashboard)}".rstrip(" —"),
        f"Strony: {totals.get('sites', 0)} (online {totals.get('online', 0)}, offline {totals.get('offline', 0)})"
        f" | krytyczne {by_health.get('critical', 0)}, ostrzeżenia {by_health.get('warning', 0)}, OK {by_health.get('ok', 0)}",
        f"Aktualizacje do zrobienia: {totals.get('updates', 0)} | SSL wygasa wkrótce: {totals.get('ssl_expiring', 0)}",
        f"Wizyty 7 dni: {fmt_int(totals.get('visits_7d', 0))} ({fmt_pct(totals.get('visits_7d_change'), signed=True)})"
        f" | 30 dni: {fmt_int(totals.get('visits_30d', 0))} ({fmt_pct(totals.get('visits_30d_change'), signed=True)})",
        f"Akceptacja cookies: {fmt_pct(totals.get('consent_rate'))} ({fmt_int(totals.get('consent_total', 0))} decyzji)",
        "",
    ]
    for row in dashboard.get("sites") or []:
        state = row_state(row)
        lines.append(f"[{HEALTH_LABELS.get(state, state).upper()}] {row.get('name')} ({_host(row.get('url', ''))})")
        if row.get("online"):
            lines.append(
                f"    aktualizacje: {fmt_int(row.get('updates'))} | SSL: {fmt_days(row.get('ssl_days'))}"
                f" | wizyty 7d: {fmt_int(row.get('visits_7d'))} ({fmt_pct(row.get('visits_7d_change'), signed=True)})"
                f" | 30d: {fmt_int(row.get('visits_30d'))} ({fmt_pct(row.get('visits_30d_change'), signed=True)})"
                f" | zgody: {fmt_pct(row.get('consent_rate'))}"
            )
        for reason in row.get("reasons") or []:
            lines.append(f"    - {reason}")
        if row.get("analytics_error"):
            lines.append(f"    - Analityka: {row['analytics_error']}")
    return "\n".join(lines).rstrip() + "\n"
