"""Agregacja statusów i analityki wszystkich stron do zakładki „Statusy i analityka”."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from typing import Callable

HEALTH_LEVELS = ("critical", "warning", "ok")
HEALTH_RANK = {"critical": 0, "warning": 1, "ok": 2}
SORT_MODES = ("health", "name", "visits", "consent", "updates")
SSL_WARNING_DAYS = 21
SPARKLINE_DAYS = 30
FETCH_DAYS = 60  # 30 dni + poprzednie 30 dni do porównania

Fetcher = Callable[[dict], dict]


def pct_change(current: int | float | None, previous: int | float | None) -> float | None:
    """Zmiana procentowa względem poprzedniego okresu (None, gdy brak bazy)."""
    if current is None or previous is None:
        return None
    if previous == 0:
        return 0.0 if current == 0 else None
    return round((current - previous) / previous * 100, 1)


def acceptance_rate(accepted: int, total: int) -> float | None:
    """Procent pełnych akceptacji cookies wśród wszystkich decyzji."""
    if not total:
        return None
    return round(accepted / total * 100, 1)


def _parse_date(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _as_int(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return 0


def _daily_map(items: object, field: str) -> dict[date, int]:
    out: dict[date, int] = {}
    if not isinstance(items, list):
        return out
    for item in items:
        if not isinstance(item, dict):
            continue
        d = _parse_date(item.get("date") or item.get("day"))
        if d is not None:
            out[d] = out.get(d, 0) + _as_int(item.get(field))
    return out


def window_sum(
    series: dict[date, int], end: date, days: int, offset: int = 0, require_full: bool = True
) -> int | None:
    """Suma z okna `days` dni kończącego się `offset` okresów przed `end`.

    Przy `require_full` zwraca None, gdy seria nie obejmuje całego okna
    (np. brak danych za poprzedni okres). Wtyczka zwraca serię uzupełnioną zerami.
    """
    last = end - timedelta(days=days * offset)
    first = last - timedelta(days=days - 1)
    if not series or (require_full and min(series) > first):
        return None
    return sum(v for d, v in series.items() if first <= d <= last)


def _reference_date(analytics: dict, series: dict[date, int], today: date | None) -> date:
    return _parse_date(analytics.get("to")) or (max(series) if series else None) or today or date.today()


def _count_updates(data: dict) -> int:
    core = data.get("core_update")
    count = 1 if isinstance(core, dict) and core.get("available") else 0
    plugins = data.get("plugin_updates")
    themes = data.get("theme_updates")
    if isinstance(plugins, list) or isinstance(themes, list):
        count += sum(len(x) for x in (plugins, themes) if isinstance(x, list))
        return count
    return _as_int(data.get("updates_count"))


def summarize_site(site: dict, result: dict | None, today: date | None = None) -> dict:
    """Wiersz podsumowania jednej strony z wyników fetchera."""
    result = result if isinstance(result, dict) else {}
    status = result.get("status") if isinstance(result.get("status"), dict) else {}
    analytics = result.get("analytics") if isinstance(result.get("analytics"), dict) else {}

    row: dict = {
        "name": str(site.get("name") or site.get("url") or "?"),
        "url": str(site.get("url") or ""),
        "online": False,
        "error": None,
        "health": "critical",
        "reasons": [],
        "updates": None,
        "plugin_updates": [],
        "ssl_days": None,
        "wp_version": None,
        "php_version": None,
        "visits_7d": None,
        "visits_prev_7d": None,
        "visits_7d_change": None,
        "visits_30d": None,
        "visits_prev_30d": None,
        "visits_30d_change": None,
        "views_30d": None,
        "consent_accepted": 0,
        "consent_total": 0,
        "consent_rate": None,
        "sparkline": [],
        "sparkline_end": None,
        "analytics_error": None,
    }

    if status.get("ok") and isinstance(status.get("data"), dict):
        data = status["data"]
        health = data.get("health")
        known = isinstance(health, str) and health in HEALTH_RANK
        reasons = data.get("reasons")
        plugin_updates = data.get("plugin_updates")
        row["online"] = True
        row["health"] = health if known else "warning"
        row["reasons"] = [str(r) for r in reasons if isinstance(r, (str, int, float))] if isinstance(reasons, list) else []
        if not known:
            row["reasons"].append("Nieznany stan kondycji zwrócony przez wtyczkę")
        row["updates"] = _count_updates(data)
        row["plugin_updates"] = [p for p in plugin_updates if isinstance(p, dict)] if isinstance(plugin_updates, list) else []
        ssl_days = data.get("ssl_days")
        row["ssl_days"] = ssl_days if isinstance(ssl_days, int) and not isinstance(ssl_days, bool) else None
        row["wp_version"] = data.get("wp_version")
        row["php_version"] = data.get("php_version")
    else:
        error = str(status.get("error") or "Brak odpowiedzi strony")
        row["error"] = error
        row["reasons"] = [f"Strona niedostępna: {error}"]

    if analytics.get("ok") and isinstance(analytics.get("data"), dict):
        adata = analytics["data"]
        visitors = _daily_map(adata.get("daily"), "visitors")
        views = _daily_map(adata.get("daily"), "views")
        ref = _reference_date(adata, visitors, today)
        row["visits_7d"] = window_sum(visitors, ref, 7) or 0
        row["visits_prev_7d"] = window_sum(visitors, ref, 7, offset=1)
        row["visits_7d_change"] = pct_change(row["visits_7d"], row["visits_prev_7d"])
        row["visits_30d"] = window_sum(visitors, ref, 30) or 0
        row["visits_prev_30d"] = window_sum(visitors, ref, 30, offset=1)
        row["visits_30d_change"] = pct_change(row["visits_30d"], row["visits_prev_30d"])
        row["views_30d"] = window_sum(views, ref, 30) or 0
        row["sparkline"] = [visitors.get(ref - timedelta(days=i), 0) for i in range(SPARKLINE_DAYS - 1, -1, -1)]
        row["sparkline_end"] = ref.isoformat()

        consent = adata.get("consent") if isinstance(adata.get("consent"), dict) else {}
        accepted_daily = _daily_map(consent.get("daily"), "accepted_all")
        if accepted_daily:
            rejected_daily = _daily_map(consent.get("daily"), "rejected")
            custom_daily = _daily_map(consent.get("daily"), "custom")
            accepted = window_sum(accepted_daily, ref, 30, require_full=False) or 0
            total = (
                accepted
                + (window_sum(rejected_daily, ref, 30, require_full=False) or 0)
                + (window_sum(custom_daily, ref, 30, require_full=False) or 0)
            )
        else:
            totals = consent.get("totals") if isinstance(consent.get("totals"), dict) else {}
            accepted = _as_int(totals.get("accepted_all"))
            total = _as_int(totals.get("total")) or (
                accepted + _as_int(totals.get("rejected")) + _as_int(totals.get("custom"))
            )
        row["consent_accepted"] = accepted
        row["consent_total"] = total
        row["consent_rate"] = acceptance_rate(accepted, total)
    elif row["online"]:
        row["analytics_error"] = str(analytics.get("error") or "Brak danych analitycznych")

    return row


def _sum_optional(values: list[int | None]) -> int | None:
    present = [v for v in values if v is not None]
    return sum(present) if present else None


def compute_totals(rows: list[dict]) -> dict:
    """Sumy dla wszystkich stron."""
    by_health = {level: 0 for level in HEALTH_LEVELS}
    for row in rows:
        by_health[row["health"]] = by_health.get(row["health"], 0) + 1
    visits_7d = sum(r["visits_7d"] or 0 for r in rows)
    visits_30d = sum(r["visits_30d"] or 0 for r in rows)
    # Porównanie tylko dla stron, które mają dane za oba okresy.
    cmp7 = [r for r in rows if r["visits_prev_7d"] is not None]
    cmp30 = [r for r in rows if r["visits_prev_30d"] is not None]
    accepted = sum(r["consent_accepted"] for r in rows)
    consent_total = sum(r["consent_total"] for r in rows)
    return {
        "sites": len(rows),
        "online": sum(1 for r in rows if r["online"]),
        "offline": sum(1 for r in rows if not r["online"]),
        "by_health": by_health,
        "updates": sum(r["updates"] or 0 for r in rows),
        "ssl_expiring": sum(1 for r in rows if r["ssl_days"] is not None and r["ssl_days"] <= SSL_WARNING_DAYS),
        "visits_7d": visits_7d,
        "visits_7d_change": pct_change(
            _sum_optional([r["visits_7d"] for r in cmp7]), _sum_optional([r["visits_prev_7d"] for r in cmp7])
        ),
        "visits_30d": visits_30d,
        "visits_30d_change": pct_change(
            _sum_optional([r["visits_30d"] for r in cmp30]), _sum_optional([r["visits_prev_30d"] for r in cmp30])
        ),
        "consent_accepted": accepted,
        "consent_total": consent_total,
        "consent_rate": acceptance_rate(accepted, consent_total),
    }


def _none_last_desc(value: float | int | None) -> tuple[int, float]:
    return (1, 0.0) if value is None else (0, -float(value))


def sort_rows(rows: list[dict], sort: str = "health") -> list[dict]:
    """Sortuje wiersze: health (krytyczne najpierw), name, visits, consent, updates (malejąco)."""
    if sort not in SORT_MODES:
        raise ValueError(f"Nieznany tryb sortowania: {sort!r}. Dostępne: {', '.join(SORT_MODES)}.")

    def name_key(r: dict) -> str:
        return r["name"].casefold()

    if sort == "health":
        key = lambda r: (HEALTH_RANK.get(r["health"], 0), r["online"], -len(r["reasons"]), name_key(r))  # noqa: E731
    elif sort == "name":
        key = lambda r: (name_key(r), r["url"])  # noqa: E731
    elif sort == "visits":
        key = lambda r: (_none_last_desc(r["visits_30d"]), name_key(r))  # noqa: E731
    elif sort == "consent":
        key = lambda r: (_none_last_desc(r["consent_rate"]), name_key(r))  # noqa: E731
    else:
        key = lambda r: (_none_last_desc(r["updates"]), name_key(r))  # noqa: E731
    return sorted(rows, key=key)


def _default_fetcher(site: dict) -> dict:
    from .client import fetch_site

    return fetch_site(site, days=FETCH_DAYS)


def _safe_fetch(fetcher: Fetcher, site: dict) -> dict:
    try:
        result = fetcher(site)
    except Exception as exc:  # fetcher nie może wywrócić całego panelu
        return {"status": {"ok": False, "error": f"Błąd pobierania danych: {exc}"}, "analytics": {"ok": False}}
    return result if isinstance(result, dict) else {"status": {"ok": False, "error": "Nieprawidłowy wynik pobierania"}}


def build_dashboard(
    sites: list[dict],
    fetcher: Fetcher | None = None,
    sort: str = "health",
    *,
    today: date | None = None,
    max_workers: int = 8,
) -> dict:
    """Pobiera równolegle dane wszystkich stron i buduje słownik dla panelu.

    `fetcher(site) -> {"status": <wynik fetch_status>, "analytics": <wynik fetch_analytics>}`.
    """
    if sort not in SORT_MODES:
        raise ValueError(f"Nieznany tryb sortowania: {sort!r}. Dostępne: {', '.join(SORT_MODES)}.")
    fetcher = fetcher or _default_fetcher
    sites = list(sites or [])
    if sites:
        with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(sites)))) as pool:
            results = list(pool.map(lambda s: _safe_fetch(fetcher, s), sites))
    else:
        results = []
    rows = [summarize_site(site, result, today=today) for site, result in zip(sites, results)]
    return {
        "title": "Statusy i analityka",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "sort": sort,
        "period_days": 30,
        "totals": compute_totals(rows),
        "sites": sort_rows(rows, sort),
    }
