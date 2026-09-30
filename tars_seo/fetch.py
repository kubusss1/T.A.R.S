"""Pobieranie strony, robots.txt i mapy strony (sitemap) — tylko urllib.

Całe pobieranie idzie przez *fetcher*: funkcję ``fetcher(url, timeout=..,
max_bytes=..) -> dict`` wykonującą JEDNO żądanie GET bez podążania za
przekierowaniami. Domyślny to :func:`urllib_fetcher`; testy podstawiają własny.

Słownik zwracany przez fetcher::

    {"url": str, "status": int, "headers": {nazwa_małymi: wartość},
     "body": bytes, "size": int, "ttfb_ms": float, "elapsed_ms": float,
     "truncated": bool, "error": str | None}
"""
from __future__ import annotations

import gzip
import os
import re
import time
import urllib.error
import urllib.request
import zlib
from typing import Any, Callable
from urllib.parse import urljoin, urlsplit, urlunsplit

USER_AGENT = "TARS-SEO/1.0"
MAX_BYTES = 3 * 1024 * 1024
DEFAULT_TIMEOUT = float(os.environ.get("TARS_SEO_TIMEOUT", "15") or 15)
MAX_REDIRECTS = 10
REDIRECT_CODES = (301, 302, 303, 307, 308)

Fetcher = Callable[..., dict]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Nie podążamy automatycznie — łańcuch przekierowań zapisujemy sami."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        return None


_OPENER = urllib.request.build_opener(_NoRedirect())


def normalize_url(url: str) -> str:
    """Dodaje ``https://`` gdy brak schematu i ``/`` gdy brak ścieżki."""
    url = (url or "").strip()
    if not url:
        raise ValueError("Podaj adres strony, np. https://zrobsite.pl")
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", url):
        url = "https://" + url
    parts = urlsplit(url)
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
        raise ValueError(f"Nieprawidłowy adres strony: {url}")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or "/",
                       parts.query, ""))


def site_root(url: str) -> str:
    p = urlsplit(url)
    return f"{p.scheme}://{p.netloc}/"


def _headers_dict(msg: Any) -> dict:
    out: dict = {}
    if msg is None:
        return out
    try:
        items = msg.items()
    except AttributeError:
        items = dict(msg).items()
    for k, v in items:
        k = str(k).lower()
        out[k] = f"{out[k]}, {v}" if k in out else str(v)
    return out


def _decompress(body: bytes, encoding: str) -> bytes:
    encoding = (encoding or "").lower()
    try:
        if "gzip" in encoding or body[:2] == b"\x1f\x8b":
            return gzip.decompress(body)
        if "deflate" in encoding:
            try:
                return zlib.decompress(body)
            except zlib.error:
                return zlib.decompress(body, -zlib.MAX_WBITS)
    except (OSError, EOFError, zlib.error):
        return body
    return body


def urllib_fetcher(url: str, timeout: float = DEFAULT_TIMEOUT,
                   max_bytes: int = MAX_BYTES) -> dict:
    """Jedno żądanie GET (bez przekierowań). Nigdy nie rzuca — błąd w ``error``."""
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pl,en;q=0.7",
        "Accept-Encoding": "gzip, deflate",
    })
    t0 = time.perf_counter()
    result = {"url": url, "status": 0, "headers": {}, "body": b"", "size": 0,
              "ttfb_ms": None, "elapsed_ms": None, "truncated": False, "error": None}
    try:
        resp = _OPENER.open(req, timeout=timeout)
    except urllib.error.HTTPError as e:  # 3xx/4xx/5xx — to też odpowiedź
        resp = e
    except (urllib.error.URLError, OSError, ValueError) as e:
        reason = getattr(e, "reason", e)
        result["error"] = f"Nie udało się połączyć: {reason}"
        result["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        return result
    result["ttfb_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    try:
        result["status"] = int(getattr(resp, "status", None) or resp.getcode() or 0)
        result["headers"] = _headers_dict(getattr(resp, "headers", None))
        try:
            raw = resp.read(max_bytes + 1) or b""
        except Exception:  # noqa: BLE001 — np. ucięte połączenie
            raw = b""
        if len(raw) > max_bytes:
            raw = raw[:max_bytes]
            result["truncated"] = True
        result["size"] = len(raw)
        result["body"] = _decompress(raw, result["headers"].get("content-encoding", ""))
    finally:
        try:
            resp.close()
        except Exception:  # noqa: BLE001
            pass
    result["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return result


def _call(fetcher: Fetcher, url: str, timeout: float, max_bytes: int) -> dict:
    try:
        r = dict(fetcher(url, timeout=timeout, max_bytes=max_bytes) or {})
    except Exception as e:  # noqa: BLE001 — fetcher nie może wywrócić audytu
        r = {"error": f"Nie udało się pobrać: {e}"}
    r.setdefault("url", url)
    r.setdefault("status", 0)
    r["headers"] = {str(k).lower(): str(v) for k, v in (r.get("headers") or {}).items()}
    body = r.get("body") or b""
    if isinstance(body, str):
        body = body.encode("utf-8")
    r["body"] = body
    r.setdefault("size", len(body))
    r.setdefault("ttfb_ms", None)
    r.setdefault("elapsed_ms", None)
    r.setdefault("truncated", False)
    r.setdefault("error", None)
    return r


_META_CHARSET = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?\s*([A-Za-z0-9_.:-]+)""", re.I)


def decode_body(body: bytes, content_type: str = "") -> str:
    """Zamienia bajty na tekst: charset z nagłówka → z <meta> → UTF-8."""
    candidates = []
    m = re.search(r"charset=([\w.:-]+)", content_type or "", re.I)
    if m:
        candidates.append(m.group(1))
    m = _META_CHARSET.search(body[:4096])
    if m:
        candidates.append(m.group(1).decode("ascii", "ignore"))
    candidates.append("utf-8")
    for enc in candidates:
        try:
            return body.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return body.decode("utf-8", errors="replace")


def fetch_page(url: str, fetcher: Fetcher | None = None, timeout: float = DEFAULT_TIMEOUT,
               max_bytes: int = MAX_BYTES, max_redirects: int = MAX_REDIRECTS) -> dict:
    """Pobiera stronę, podąża za przekierowaniami i zapisuje ich łańcuch.

    Zwraca: ``url, final_url, status, headers, body, text, size, redirects
    ([{url, status, location}]), elapsed_ms (suma), ttfb_ms (ostatni skok),
    truncated, error``.
    """
    fetcher = fetcher or urllib_fetcher
    current = url
    redirects: list[dict] = []
    total_ms = 0.0
    timed = False
    seen = set()
    while True:
        r = _call(fetcher, current, timeout, max_bytes)
        if r.get("elapsed_ms") is not None:
            total_ms += float(r["elapsed_ms"])
            timed = True
        status = int(r.get("status") or 0)
        location = r["headers"].get("location")
        if status in REDIRECT_CODES and location and not r.get("error"):
            nxt = urljoin(current, location.strip())
            redirects.append({"url": current, "status": status, "location": nxt})
            if len(redirects) > max_redirects or nxt in seen:
                r["error"] = "Za dużo przekierowań (pętla przekierowań)."
                break
            seen.add(current)
            current = nxt
            continue
        break
    text = ""
    if r["body"]:
        text = decode_body(r["body"], r["headers"].get("content-type", ""))
    return {
        "url": url, "final_url": current, "status": int(r.get("status") or 0),
        "headers": r["headers"], "body": r["body"], "text": text,
        "size": int(r.get("size") or len(r["body"])), "redirects": redirects,
        "elapsed_ms": round(total_ms, 1) if timed else None,
        "ttfb_ms": r.get("ttfb_ms"), "truncated": bool(r.get("truncated")),
        "error": r.get("error"),
    }


# --------------------------------------------------------------------------
# robots.txt
# --------------------------------------------------------------------------

def parse_robots(text: str) -> dict:
    """Wyciąga reguły dla ``User-agent: *`` i linie ``Sitemap:``."""
    sitemaps: list[str] = []
    groups: list[tuple[list[str], list[tuple[str, str]]]] = []
    agents: list[str] = []
    rules: list[tuple[str, str]] = []
    last_was_agent = False
    for raw in (text or "").splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key, value = key.strip().lower(), value.strip()
        if key == "sitemap":
            if value:
                sitemaps.append(value)
            continue
        if key == "user-agent":
            if not last_was_agent and (agents or rules):
                groups.append((agents, rules))
                agents, rules = [], []
            agents.append(value.lower())
            last_was_agent = True
            continue
        if key in ("allow", "disallow"):
            rules.append((key, value))
        last_was_agent = False
    if agents or rules:
        groups.append((agents, rules))
    star_rules = [r for a, rs in groups if "*" in a for r in rs]
    disallow_all = any(k == "disallow" and v in ("/", "/*") for k, v in star_rules)
    return {"sitemaps": sitemaps, "disallow_all": disallow_all,
            "rules": star_rules, "groups": len(groups)}


def fetch_robots(url: str, fetcher: Fetcher | None = None,
                 timeout: float = DEFAULT_TIMEOUT) -> dict:
    robots_url = urljoin(site_root(url), "/robots.txt")
    r = fetch_page(robots_url, fetcher, timeout=timeout, max_bytes=512 * 1024)
    found = r["status"] == 200 and not r["error"]
    info = parse_robots(r["text"]) if found else {"sitemaps": [], "disallow_all": False,
                                                  "rules": [], "groups": 0}
    return {"url": robots_url, "status": r["status"], "found": found,
            "error": r["error"], **info}


# --------------------------------------------------------------------------
# sitemap
# --------------------------------------------------------------------------

_LOC_RE = re.compile(r"<(?:[\w-]+:)?loc>\s*(.*?)\s*</(?:[\w-]+:)?loc>", re.I | re.S)
_URL_TAG_RE = re.compile(r"<(?:[\w-]+:)?url[\s>/]", re.I)


def parse_sitemap(xml_text: str) -> dict:
    """Rozpoznaje ``<urlset>`` / ``<sitemapindex>`` i liczy wpisy."""
    low = (xml_text or "")[:5000].lower()
    if "sitemapindex" in low:
        children = [l.replace("&amp;", "&") for l in _LOC_RE.findall(xml_text)]
        return {"kind": "index", "children": children, "url_count": 0}
    if "urlset" in low:
        return {"kind": "urlset", "children": [], "url_count": len(_URL_TAG_RE.findall(xml_text))}
    return {"kind": None, "children": [], "url_count": 0}


def fetch_sitemap(url: str, robots_sitemaps: list[str] | None = None,
                  fetcher: Fetcher | None = None, timeout: float = DEFAULT_TIMEOUT,
                  max_children: int = 20) -> dict:
    """Szuka mapy strony (z robots.txt, /sitemap.xml, /sitemap_index.xml)."""
    root = site_root(url)
    candidates = list(dict.fromkeys(
        list(robots_sitemaps or []) + [urljoin(root, "/sitemap.xml"),
                                       urljoin(root, "/sitemap_index.xml")]))
    for cand in candidates:
        r = fetch_page(cand, fetcher, timeout=timeout)
        if r["status"] != 200 or r["error"]:
            continue
        info = parse_sitemap(decode_body(_decompress(r["body"], ""), ""))
        if not info["kind"]:
            continue
        result = {"found": True, "url": cand, "is_index": info["kind"] == "index",
                  "url_count": info["url_count"], "sitemaps": 1, "children_checked": 0}
        if result["is_index"]:
            total = 0
            for child in info["children"][:max_children]:
                cr = fetch_page(child, fetcher, timeout=timeout)
                if cr["status"] != 200 or cr["error"]:
                    continue
                sub = parse_sitemap(decode_body(_decompress(cr["body"], ""), ""))
                total += sub["url_count"]
                result["children_checked"] += 1
            result["url_count"] = total
            result["sitemaps"] = len(info["children"])
        return result
    return {"found": False, "url": None, "is_index": False, "url_count": 0,
            "sitemaps": 0, "children_checked": 0}


# --------------------------------------------------------------------------
# Całość
# --------------------------------------------------------------------------

def fetch_site(url: str, fetcher: Fetcher | None = None,
               timeout: float = DEFAULT_TIMEOUT) -> dict:
    """Strona + robots.txt + sitemap + test http→https + /favicon.ico."""
    url = normalize_url(url)
    page = fetch_page(url, fetcher, timeout=timeout)
    base = page["final_url"] if page["status"] else url
    robots = fetch_robots(base, fetcher, timeout=timeout)
    sitemap = fetch_sitemap(base, robots.get("sitemaps"), fetcher, timeout=timeout)

    http_redirect: dict = {"checked": False, "to_https": None, "final_url": None}
    if urlsplit(base).scheme == "https":
        http_url = "http://" + urlsplit(base).netloc + "/"
        hr = fetch_page(http_url, fetcher, timeout=min(timeout, 10))
        if hr["status"] and not hr["error"]:
            http_redirect = {"checked": True, "final_url": hr["final_url"],
                             "to_https": hr["final_url"].startswith("https://")}

    fav = fetch_page(urljoin(site_root(base), "/favicon.ico"), fetcher,
                     timeout=min(timeout, 10), max_bytes=256 * 1024)
    favicon_ico = fav["status"] == 200 and not fav["error"] and bool(fav["body"])
    return {"page": page, "robots": robots, "sitemap": sitemap,
            "http_redirect": http_redirect, "favicon_ico": favicon_ico}
