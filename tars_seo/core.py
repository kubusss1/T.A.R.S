"""Audyt SEO: pobranie → analiza → sprawdzenia → wynik. Plus porównanie z konkurencją."""
from __future__ import annotations

from datetime import datetime, timezone

from .checks import CATEGORIES, local_business_entities, run_checks
from .fetch import DEFAULT_TIMEOUT, Fetcher, fetch_site, normalize_url
from .keywords import extract_keywords, keyword_presence
from .parse import parse_html
from .score import summarize

VERSION = "1.0"


def _page_summary(page: dict) -> dict:
    """Najważniejsze dane o stronie (bez pełnego tekstu) — do raportów i historii."""
    links = page.get("links") or []
    return {
        "title": page.get("title"), "meta_description": page.get("meta_description"),
        "canonical": page.get("canonical"), "robots_meta": page.get("robots_meta"),
        "lang": page.get("lang"), "viewport": page.get("viewport"),
        "h1": page.get("h1"), "h2": (page.get("h2") or [])[:20], "h3": (page.get("h3") or [])[:20],
        "word_count": page.get("word_count", 0), "images": len(page.get("images") or []),
        "links_internal": sum(1 for l in links if l["kind"] == "internal"),
        "links_external": sum(1 for l in links if l["kind"] == "external"),
        "og": page.get("og"), "twitter": page.get("twitter"),
        "jsonld_types": (page.get("jsonld") or {}).get("types", []),
        "hreflang": page.get("hreflang"), "favicon": page.get("favicon"),
        "mixed_content": len(page.get("mixed_content") or []),
        "tel_links": list(dict.fromkeys(page.get("tel_links") or []))[:5],
        "local_business": (local_business_entities(page) or [None])[0],
        "excerpt": (page.get("text") or "")[:800],
    }


def _build(url: str, final_url: str, html: str, resp: dict | None, site: dict | None,
           now: datetime | None = None) -> dict:
    page = parse_html(html, final_url)
    kws = extract_keywords(page.get("text", ""), top=10)
    presence = keyword_presence(kws[0]["phrase"], page.get("title"), page.get("h1"),
                                page.get("meta_description")) if kws else None
    ctx = {"url": url, "final_url": final_url, "page": page, "resp": resp, "html": html,
           "robots": (site or {}).get("robots"), "sitemap": (site or {}).get("sitemap"),
           "http_redirect": (site or {}).get("http_redirect"),
           "favicon_ico": (site or {}).get("favicon_ico"), "keywords": kws}
    checks = run_checks(ctx)
    result = {
        "version": VERSION, "url": url, "final_url": final_url,
        "audited_at": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
        **summarize(checks),
        "checks": checks,
        "keywords": [{k: v for k, v in kw.items() if k != "key"} for kw in kws],
        "keyword_presence": presence,
        "page": _page_summary(page),
        "fetch": None if resp is None else {
            "status": resp.get("status"), "elapsed_ms": resp.get("elapsed_ms"),
            "ttfb_ms": resp.get("ttfb_ms"), "size": resp.get("size"),
            "redirects": resp.get("redirects"), "error": resp.get("error")},
        "error": (resp or {}).get("error") if resp and not resp.get("status") else None,
    }
    if site:
        result["site"] = {"robots": {k: site["robots"].get(k) for k in
                                     ("url", "found", "status", "disallow_all", "sitemaps")},
                          "sitemap": site["sitemap"], "http_redirect": site["http_redirect"],
                          "favicon_ico": site["favicon_ico"]}
    return result


def audit(url: str, fetcher: Fetcher | None = None, timeout: float = DEFAULT_TIMEOUT,
          now: datetime | None = None) -> dict:
    """Pełny audyt adresu URL. ``fetcher`` — patrz :mod:`tars_seo.fetch`."""
    url = normalize_url(url)
    site = fetch_site(url, fetcher=fetcher, timeout=timeout)
    resp = site["page"]
    if resp.get("error") and not resp.get("status"):
        # strona w ogóle nie odpowiada — nie ma czego oceniać poza tym faktem
        from .checks import check_status
        checks = [check_status({"resp": resp})]
        return {"version": VERSION, "url": url, "final_url": resp.get("final_url") or url,
                "audited_at": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
                **summarize(checks), "checks": checks, "keywords": [], "keyword_presence": None,
                "page": {}, "fetch": {"status": 0, "error": resp.get("error"),
                                      "redirects": resp.get("redirects")},
                "error": resp.get("error")}
    return _build(url, resp.get("final_url") or url, resp.get("text") or "", resp, site, now)


def audit_html(html: str, url: str = "https://example.com/", site: dict | None = None,
               resp: dict | None = None, now: datetime | None = None) -> dict:
    """Audyt gotowego HTML-a (bez sieci). Sprawdzenia serwera są pomijane."""
    url = normalize_url(url)
    final = (resp or {}).get("final_url") or url
    return _build(url, final, html, resp, site, now)


# --------------------------------------------------------------------------
# Porównanie z konkurencją
# --------------------------------------------------------------------------

def compare_results(a: dict, b: dict) -> dict:
    """Porównuje dwa wyniki audytu kategoria po kategorii."""
    rows = []
    wins = {"a": 0, "b": 0}
    for cat in CATEGORIES:
        sa = (a.get("categories") or {}).get(cat)
        sb = (b.get("categories") or {}).get(cat)
        if sa is None and sb is None:
            winner = None
        elif sb is None or (sa is not None and sa > sb):
            winner = "a"
        elif sa is None or sb > sa:
            winner = "b"
        else:
            winner = "remis"
        if winner in wins:
            wins[winner] += 1
        rows.append({"category": cat, "a": sa, "b": sb, "winner": winner})
    if a.get("score", 0) > b.get("score", 0):
        overall = "a"
    elif b.get("score", 0) > a.get("score", 0):
        overall = "b"
    else:
        overall = "remis"
    # czego konkurent ma dobrze, a my nie — gotowa lista „do nadrobienia”
    a_levels = {c["id"]: c for c in a.get("checks") or []}
    catch_up = [a_levels[c["id"]] for c in b.get("checks") or []
                if c["level"] == "ok" and c["id"] in a_levels
                and a_levels[c["id"]]["level"] in ("warning", "critical")]
    return {"a": {"url": a.get("url"), "score": a.get("score"), "grade": a.get("grade")},
            "b": {"url": b.get("url"), "score": b.get("score"), "grade": b.get("grade")},
            "categories": rows, "wins": wins, "overall_winner": overall,
            "catch_up": catch_up}


def compare(url_a: str, url_b: str, fetcher: Fetcher | None = None,
            timeout: float = DEFAULT_TIMEOUT) -> dict:
    """Audytuje dwie strony (np. swoją i konkurenta) i porównuje je."""
    ra = audit(url_a, fetcher=fetcher, timeout=timeout)
    rb = audit(url_b, fetcher=fetcher, timeout=timeout)
    out = compare_results(ra, rb)
    out["results"] = {"a": ra, "b": rb}
    return out
