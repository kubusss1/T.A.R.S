"""Testy modułu tars_zrobsite (klient TARS Bridge, dashboard, widoki).

Bez internetu: lokalny fake serwer HTTP emuluje endpointy wtyczki WordPress.
"""
from __future__ import annotations

import io
import json
import os
import re
import socket
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlparse

from tars_zrobsite import client, dashboard, render, sites
from tars_zrobsite.__main__ import main as cli_main
from tars_zrobsite.dashboard import build_dashboard, pct_change, sort_rows, summarize_site
from tars_zrobsite.render import render_html, render_telegram

TODAY = date(2026, 9, 30)


def make_analytics(visitors: list[int], consent_rows: list[dict] | None = None, to: date = TODAY) -> dict:
    """Odpowiedź /analytics jak z wtyczki: `visitors` od najstarszego dnia do `to`."""
    n = len(visitors)
    daily = [
        {"date": (to - timedelta(days=n - 1 - i)).isoformat(), "views": v * 2, "visitors": v}
        for i, v in enumerate(visitors)
    ]
    consent_rows = consent_rows or []
    totals = {"accepted_all": 0, "rejected": 0, "custom": 0}
    for row in consent_rows:
        for k in totals:
            totals[k] += row.get(k, 0)
    totals["total"] = sum(totals.values())
    return {
        "days": n,
        "from": daily[0]["date"] if daily else None,
        "to": to.isoformat(),
        "daily": daily,
        "totals": {"views": sum(d["views"] for d in daily), "visitors": sum(visitors)},
        "top_pages": [{"path": "/", "views": 10}],
        "referrers": [{"domain": "google.com", "visits": 4}],
        "devices": {"mobile": 5, "desktop": 3},
        "consent": {"daily": consent_rows, "totals": totals, "acceptance_rate": None},
    }


def make_status(health: str = "ok", reasons: list[str] | None = None, plugins: int = 0, core: bool = False,
                themes: int = 0, ssl_days: int | None = 90, name: str = "Strona") -> dict:
    return {
        "site": {"name": name, "url": "https://example.test/"},
        "wp_version": "6.8.2",
        "php_version": "8.3.4",
        "core_update": {"available": core, "version": "6.8.3" if core else None},
        "plugin_updates": [{"name": f"Wtyczka {i}", "current": "1.0", "new": "1.1"} for i in range(plugins)],
        "theme_updates": [{"name": f"Motyw {i}", "current": "1.0", "new": "2.0"} for i in range(themes)],
        "active_plugins": 12,
        "ssl_days": ssl_days,
        "debug_mode": False,
        "health": health,
        "reasons": reasons or [],
    }


# Standardowa seria 60 dni: poprzednie 30 dni po 2 wizyty, potem 23 dni po 3 i ostatnie 7 dni po 4.
SERIES_60 = [2] * 30 + [3] * 23 + [4] * 7
CONSENT_ROWS = [
    {"date": (TODAY - timedelta(days=1)).isoformat(), "accepted_all": 4, "rejected": 2, "custom": 1},
    {"date": TODAY.isoformat(), "accepted_all": 2, "rejected": 1, "custom": 0},
    # poza oknem 30 dni — nie może wpływać na wynik
    {"date": (TODAY - timedelta(days=45)).isoformat(), "accepted_all": 100, "rejected": 0, "custom": 0},
]


class FakeBridgeServer(ThreadingHTTPServer):
    """Emulacja wtyczki TARS Bridge. Każda „strona” to prefiks ścieżki, np. /alfa."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), FakeBridgeHandler)
        self.sites: dict[str, dict] = {}
        self.requests: list[dict] = []
        self.lock = threading.Lock()

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"

    def add_site(self, prefix: str, key: str, status: dict | None = None, analytics: dict | None = None,
                 mode: str = "ok") -> dict:
        self.sites[prefix] = {"key": key, "status": status, "analytics": analytics, "mode": mode}
        return {"name": prefix.strip("/").title(), "url": self.base + prefix, "key": key}


class FakeBridgeHandler(BaseHTTPRequestHandler):
    server: FakeBridgeServer

    def log_message(self, *args):  # cisza w testach
        pass

    def _json(self, code: int, payload: object) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):  # klient zrezygnował (test timeoutu)
            pass

    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        with self.server.lock:
            self.server.requests.append(
                {
                    "path": parsed.path,
                    "query": parse_qs(parsed.query),
                    "headers": {k.lower(): v for k, v in self.headers.items()},  # nagłówki bez wielkości liter
                }
            )
        match = re.match(r"^(/[^/]+)/wp-json/tars/v1/(status|analytics)$", parsed.path)
        if not match or match.group(1) not in self.server.sites:
            return self._json(404, {"code": "rest_no_route", "message": "Nie znaleziono"})
        site = self.server.sites[match.group(1)]
        if self.headers.get("X-TARS-Key") != site["key"]:
            return self._json(401, {"code": "tars_unauthorized", "message": "Nieprawidłowy klucz"})
        if site["mode"] == "slow":
            time.sleep(1.5)
        if site["mode"] == "html":
            body = b"<html>Fatal error</html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if site["mode"] == "error500":
            return self._json(500, {"message": "boom"})
        if site["mode"].startswith("redirect:"):
            self.send_response(302)
            self.send_header("Location", site["mode"][len("redirect:"):] + parsed.path[len(match.group(1)):])
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        payload = site["status"] if match.group(2) == "status" else site["analytics"]
        return self._json(200, payload)


def closed_port_url() -> str:
    """Adres na porcie, na którym nic nie nasłuchuje (strona offline)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return f"http://127.0.0.1:{port}/offline"


class ServerTestCase(unittest.TestCase):
    def setUp(self):
        self.server = FakeBridgeServer()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


class ClientTests(ServerTestCase):
    def test_fetch_status_sends_auth_header_and_parses_json(self):
        site = self.server.add_site("/alfa", "tajny-klucz-123", status=make_status(name="Alfa"))
        result = client.fetch_status(site)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["data"]["site"]["name"], "Alfa")
        req = self.server.requests[-1]
        self.assertEqual(req["path"], "/alfa/wp-json/tars/v1/status")
        self.assertEqual(req["headers"].get("x-tars-key"), "tajny-klucz-123")
        self.assertIn("TARS-ZrobSite", req["headers"].get("user-agent", ""))

    def test_fetch_analytics_passes_days_param(self):
        site = self.server.add_site("/beta", "k", analytics=make_analytics(SERIES_60))
        result = client.fetch_analytics(site, days=60)
        self.assertTrue(result["ok"])
        self.assertEqual(self.server.requests[-1]["query"], {"days": ["60"]})
        client.fetch_analytics(site, days=9999)  # przycinane do 365
        self.assertEqual(self.server.requests[-1]["query"], {"days": ["365"]})

    def test_wrong_key_returns_polish_401_error(self):
        site = self.server.add_site("/gamma", "dobry", status=make_status())
        site["key"] = "zly"
        result = client.fetch_status(site)
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], 401)
        self.assertIn("klucz", result["error"].lower())

    def test_missing_plugin_404_and_bad_json_and_500(self):
        missing = {"name": "X", "url": self.server.base + "/nie-ma", "key": "k"}
        self.assertIn("TARS Bridge", client.fetch_status(missing)["error"])
        broken = self.server.add_site("/php", "k", mode="html")
        self.assertIn("JSON", client.fetch_status(broken)["error"])
        err = self.server.add_site("/err", "k", mode="error500")
        res = client.fetch_status(err)
        self.assertFalse(res["ok"])
        self.assertIn("500", res["error"])

    def test_offline_site_does_not_raise(self):
        site = {"name": "Offline", "url": closed_port_url(), "key": "k"}
        result = client.fetch_status(site, timeout=2)
        self.assertFalse(result["ok"])
        self.assertIsInstance(result["error"], str)
        both = client.fetch_site(site, timeout=2)
        self.assertFalse(both["status"]["ok"])
        self.assertFalse(both["analytics"]["ok"])

    def test_timeout_is_reported(self):
        site = self.server.add_site("/wolna", "k", status=make_status(), mode="slow")
        result = client.fetch_status(site, timeout=0.3)
        self.assertFalse(result["ok"])
        self.assertIn("0.3 s", result["error"])

    def test_redirect_to_other_host_does_not_leak_key(self):
        port = self.server.server_address[1]
        self.server.add_site("/cel", "k", status=make_status())
        # 127.0.0.1 → localhost: inny host (np. przejęta domena / błędny redirect) — bez klucza.
        away = self.server.add_site("/stara", "tajny", mode=f"redirect:http://localhost:{port}/obca")
        client.fetch_status(away)
        self.assertEqual(self.server.requests[0]["headers"].get("x-tars-key"), "tajny")
        self.assertGreaterEqual(len(self.server.requests), 2)
        self.assertEqual(self.server.requests[-1]["path"], "/obca/wp-json/tars/v1/status")
        self.assertNotIn("x-tars-key", self.server.requests[-1]["headers"])
        # Ten sam host (np. /stara → /nowa) — klucz zostaje.
        self.server.requests.clear()
        self.server.add_site("/nowa", "k2", status=make_status())
        same = self.server.add_site("/przed", "k2", mode=f"redirect:{self.server.base}/nowa")
        same_result = client.fetch_status(same)
        self.assertEqual(self.server.requests[-1]["headers"].get("x-tars-key"), "k2")
        self.assertTrue(same_result["ok"], same_result)

    def test_missing_key_in_config(self):
        result = client.fetch_status({"name": "Bez klucza", "url": "https://example.test"})
        self.assertEqual(result, {"ok": False, "error": "Brak klucza API w konfiguracji strony."})

    def test_api_base_override_with_rest_route(self):
        site = {"url": "https://x.test", "key": "k", "api_base": "https://x.test/?rest_route=/tars/v1"}
        self.assertEqual(
            client.endpoint_url(site, "analytics", {"days": 30}),
            "https://x.test/?rest_route=/tars/v1/analytics&days=30",
        )
        self.assertEqual(client.endpoint_url({"url": "https://y.test/"}, "status"), "https://y.test/wp-json/tars/v1/status")


class DashboardEndToEndTests(ServerTestCase):
    def test_build_dashboard_with_default_fetcher_and_offline_site(self):
        ok_site = self.server.add_site(
            "/ok", "k1", status=make_status(), analytics=make_analytics(SERIES_60, CONSENT_ROWS)
        )
        warn_site = self.server.add_site(
            "/warn", "k2", status=make_status("warning", ["Wtyczki do aktualizacji: 2"], plugins=2),
            analytics=make_analytics([1] * 60),
        )
        offline = {"name": "Zzz Offline", "url": closed_port_url(), "key": "k3"}
        dash = build_dashboard([ok_site, warn_site, offline], sort="health")
        names = [r["name"] for r in dash["sites"]]
        self.assertEqual(names, ["Zzz Offline", "Warn", "Ok"])
        off = dash["sites"][0]
        self.assertFalse(off["online"])
        self.assertEqual(off["health"], "critical")
        self.assertTrue(off["reasons"][0].startswith("Strona niedostępna"))
        self.assertEqual(dash["totals"]["offline"], 1)
        self.assertEqual(dash["totals"]["updates"], 2)
        # dashboard prosi o 60 dni, żeby porównać z poprzednim okresem
        days = [r["query"].get("days") for r in self.server.requests if r["path"].endswith("/analytics")]
        self.assertTrue(days and all(d == ["60"] for d in days))

    def test_cli_prints_summary_and_writes_html(self):
        site = self.server.add_site("/cli", "k", status=make_status(), analytics=make_analytics(SERIES_60))
        with tempfile.TemporaryDirectory() as tmp:
            sites_file = Path(tmp) / "sites.json"
            sites_file.write_text(json.dumps([site]), encoding="utf-8")
            out = Path(tmp) / "out" / "panel.html"
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = cli_main(["--sites", str(sites_file), "--html", str(out)])
            self.assertEqual(code, 0)
            self.assertIn("Strony: 1", buf.getvalue())
            self.assertIn("Zapisano widok HTML", buf.getvalue())
            self.assertIn("<!doctype html>", out.read_text(encoding="utf-8"))
            err = io.StringIO()
            with redirect_stderr(err):
                self.assertEqual(cli_main(["--sites", str(Path(tmp) / "brak.json")]), 2)
            self.assertIn("Nie znaleziono pliku stron", err.getvalue())


def ok_result(status: dict, analytics: dict | None) -> dict:
    return {
        "status": {"ok": True, "data": status},
        "analytics": {"ok": True, "data": analytics} if analytics is not None else {"ok": False, "error": "x"},
    }


class AggregationTests(unittest.TestCase):
    def test_pct_change_math(self):
        self.assertEqual(pct_change(150, 100), 50.0)
        self.assertEqual(pct_change(97, 60), 61.7)
        self.assertEqual(pct_change(50, 100), -50.0)
        self.assertEqual(pct_change(0, 0), 0.0)
        self.assertIsNone(pct_change(10, 0))
        self.assertIsNone(pct_change(10, None))
        self.assertEqual(dashboard.acceptance_rate(6, 10), 60.0)
        self.assertIsNone(dashboard.acceptance_rate(0, 0))

    def test_site_summary_visits_change_and_consent_rate(self):
        row = summarize_site(
            {"name": "A", "url": "https://a.test", "key": "k"},
            ok_result(make_status(plugins=2, core=True, themes=1, ssl_days=12), make_analytics(SERIES_60, CONSENT_ROWS)),
        )
        self.assertEqual(row["visits_7d"], 28)
        self.assertEqual(row["visits_prev_7d"], 21)
        self.assertEqual(row["visits_7d_change"], 33.3)
        self.assertEqual(row["visits_30d"], 97)
        self.assertEqual(row["visits_prev_30d"], 60)
        self.assertEqual(row["visits_30d_change"], 61.7)
        self.assertEqual(row["views_30d"], 194)
        self.assertEqual(row["consent_total"], 10)  # dzień sprzed 45 dni pominięty
        self.assertEqual(row["consent_rate"], 60.0)
        self.assertEqual(row["updates"], 4)  # core + 2 wtyczki + 1 motyw
        self.assertEqual(row["ssl_days"], 12)
        self.assertEqual(len(row["sparkline"]), 30)
        self.assertEqual(row["sparkline"][-1], 4)
        self.assertEqual(row["sparkline_end"], TODAY.isoformat())

    def test_short_history_has_no_previous_period(self):
        row = summarize_site({"name": "Nowa", "url": "https://n.test"}, ok_result(make_status(), make_analytics([5] * 30)))
        self.assertEqual(row["visits_30d"], 150)
        self.assertIsNone(row["visits_prev_30d"])
        self.assertIsNone(row["visits_30d_change"])
        self.assertEqual(row["visits_7d_change"], 0.0)

    def test_totals(self):
        rows = [
            summarize_site({"name": "A", "url": "https://a.test"}, ok_result(make_status(), make_analytics(SERIES_60, CONSENT_ROWS))),
            summarize_site({"name": "B", "url": "https://b.test"}, ok_result(make_status("warning", ssl_days=5), make_analytics([1] * 60))),
            summarize_site({"name": "C", "url": "https://c.test"}, {"status": {"ok": False, "error": "Połączenie odrzucone"}}),
        ]
        totals = dashboard.compute_totals(rows)
        self.assertEqual(totals["sites"], 3)
        self.assertEqual(totals["online"], 2)
        self.assertEqual(totals["by_health"], {"critical": 1, "warning": 1, "ok": 1})
        self.assertEqual(totals["visits_30d"], 97 + 30)
        self.assertEqual(totals["visits_30d_change"], pct_change(127, 90))
        self.assertEqual(totals["consent_rate"], 60.0)
        self.assertEqual(totals["ssl_expiring"], 1)

    def test_malformed_plugin_payload_does_not_break_dashboard(self):
        weird = [
            {"health": ["ok"], "reasons": 5, "plugin_updates": 3, "theme_updates": "abc"},
            {"health": {"x": 1}, "reasons": "tekst", "plugin_updates": {"a": 1}, "ssl_days": "7"},
        ]
        analytics = make_analytics([1] * 60)
        analytics["daily"][-1]["visitors"] = float("inf")
        sites = [{"name": f"S{i}", "url": f"https://s{i}.test"} for i in range(len(weird))]
        by_url = {s["url"]: w for s, w in zip(sites, weird)}
        dash = build_dashboard(sites, fetcher=lambda s: ok_result(by_url[s["url"]], analytics), today=TODAY)
        for row in dash["sites"]:
            self.assertEqual(row["health"], "warning")
            self.assertEqual(row["plugin_updates"], [])
            self.assertIn("Nieznany stan kondycji zwrócony przez wtyczkę", row["reasons"])
        self.assertIn("S0", render_html(dash))

    def test_fetcher_exception_and_bad_result_do_not_break_dashboard(self):
        def fetcher(site):
            if site["name"] == "Wybuch":
                raise RuntimeError("awaria")
            if site["name"] == "Dziwna":
                return "nie słownik"
            return ok_result(make_status(), make_analytics([1] * 60))

        dash = build_dashboard(
            [{"name": "Wybuch", "url": "https://w.test"}, {"name": "Dziwna", "url": "https://d.test"},
             {"name": "Dobra", "url": "https://g.test"}],
            fetcher=fetcher,
        )
        by_name = {r["name"]: r for r in dash["sites"]}
        self.assertIn("awaria", by_name["Wybuch"]["error"])
        self.assertFalse(by_name["Dziwna"]["online"])
        self.assertTrue(by_name["Dobra"]["online"])
        self.assertEqual(build_dashboard([], fetcher=fetcher)["totals"]["sites"], 0)


class SortTests(unittest.TestCase):
    def setUp(self):
        data = {
            "Ok Mały": ok_result(make_status("ok"), make_analytics([1] * 60)),
            "bravo krytyczny": ok_result(make_status("critical", ["SSL"], plugins=6), make_analytics([5] * 60, [
                {"date": TODAY.isoformat(), "accepted_all": 1, "rejected": 3, "custom": 0}])),
            "Charlie ostrzeżenie": ok_result(make_status("warning", ["x"], plugins=1), make_analytics([9] * 60, [
                {"date": TODAY.isoformat(), "accepted_all": 9, "rejected": 1, "custom": 0}])),
            "Alfa offline": {"status": {"ok": False, "error": "timeout"}},
        }
        self.site_list = [{"name": n, "url": f"https://{i}.test", "key": "k"} for i, n in enumerate(data)]
        self.dash = {s["name"]: data[s["name"]] for s in self.site_list}
        self.fetcher = lambda site: self.dash[site["name"]]

    def names(self, sort):
        return [r["name"] for r in build_dashboard(self.site_list, fetcher=self.fetcher, sort=sort)["sites"]]

    def test_sort_health_critical_first(self):
        self.assertEqual(self.names("health"), ["Alfa offline", "bravo krytyczny", "Charlie ostrzeżenie", "Ok Mały"])

    def test_sort_name_case_insensitive(self):
        # "bravo" małą literą ląduje między "Alfa" i "Charlie" (bez rozróżniania wielkości liter)
        self.assertEqual(self.names("name"), ["Alfa offline", "bravo krytyczny", "Charlie ostrzeżenie", "Ok Mały"])

    def test_sort_visits_desc_none_last(self):
        self.assertEqual(self.names("visits"), ["Charlie ostrzeżenie", "bravo krytyczny", "Ok Mały", "Alfa offline"])

    def test_sort_consent_desc_none_last(self):
        self.assertEqual(self.names("consent"), ["Charlie ostrzeżenie", "bravo krytyczny", "Alfa offline", "Ok Mały"])

    def test_sort_updates_desc_none_last(self):
        self.assertEqual(self.names("updates"), ["bravo krytyczny", "Charlie ostrzeżenie", "Ok Mały", "Alfa offline"])

    def test_invalid_sort_raises(self):
        with self.assertRaises(ValueError):
            build_dashboard(self.site_list, fetcher=self.fetcher, sort="losowo")
        with self.assertRaises(ValueError):
            sort_rows([], "zle")


XSS_NAME = '<script>alert("x")</script> & "Kowalski"'


def xss_dashboard() -> dict:
    status = make_status("warning", ['<img src=x onerror="alert(1)">'], plugins=1)
    return build_dashboard(
        [
            {"name": XSS_NAME, "url": "https://kowalski.test", "key": "k"},
            {"name": "Zły link", "url": "javascript:alert(1)", "key": "k"},
        ],
        fetcher=lambda s: ok_result(status, make_analytics(SERIES_60, CONSENT_ROWS)),
    )


class RenderTests(unittest.TestCase):
    def test_html_escapes_site_names_and_reasons(self):
        page = render_html(xss_dashboard())
        self.assertNotIn("<script>alert", page)
        self.assertNotIn("<img src=x", page)
        self.assertIn("&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt; &amp; &quot;Kowalski&quot;", page)
        self.assertNotIn('href="javascript:', page)
        self.assertIn('href="https://kowalski.test"', page)

    def test_html_is_self_contained_with_sparkline_and_theme(self):
        page = render_html(xss_dashboard())
        self.assertTrue(page.startswith("<!doctype html>"))
        self.assertIn('<html lang="pl">', page)
        self.assertIn("Statusy i analityka", page)
        self.assertIn("<svg class=\"zs-spark\"", page)
        self.assertIn("<polyline points=", page)
        self.assertIn("prefers-color-scheme:dark", page)
        self.assertIn("--zs-surface", page)
        self.assertIsNone(re.search(r'(src|href)="(https?:)?//(?!kowalski\.test)', page))
        self.assertNotIn("<link", page)
        self.assertNotIn("<script", page)
        fragment = render_html(xss_dashboard(), full_page=False, theme="dark")
        self.assertTrue(fragment.startswith('<section class="tars-zs" data-theme="dark"'))
        self.assertIn("Brak stron", render_html(build_dashboard([], fetcher=lambda s: {})))

    def test_telegram_escapes_and_uses_status_dots(self):
        text = render_telegram(xss_dashboard())
        self.assertIn("&lt;script&gt;alert(\"x\")&lt;/script&gt; &amp; \"Kowalski\"", text)
        self.assertIn("&lt;img src=x onerror=\"alert(1)\"&gt;", text)
        tags = set(re.findall(r"</?([a-zA-Z]+)", text))
        self.assertEqual(tags, {"b"})  # tylko dozwolony tag
        self.assertIn("🟡", text)
        self.assertIn("61,7%", text)

    def test_telegram_limit(self):
        many = [{"name": f"Strona {i} " + "x" * 80, "url": f"https://s{i}.test", "key": "k"} for i in range(120)]
        dash = build_dashboard(many, fetcher=lambda s: {"status": {"ok": False, "error": "Połączenie odrzucone"}})
        text = render_telegram(dash)
        self.assertLessEqual(len(text), 4096)
        self.assertTrue(text.endswith("(lista skrócona)"))
        self.assertIn("⚫", text)

    def test_telegram_limit_counts_utf16_like_telegram(self):
        # Emoji (⚫, 🔴 …) to 2 jednostki UTF-16 — Telegram odrzuci wiadomość > 4096 jednostek.
        many = [{"name": "😀" * 30, "url": f"https://s{i}.test", "key": "k"} for i in range(120)]
        dash = build_dashboard(many, fetcher=lambda s: {"status": {"ok": False, "error": "x"}})
        text = render_telegram(dash)
        self.assertLessEqual(len(text.encode("utf-16-le")) // 2, 4096)
        self.assertTrue(text.endswith("(lista skrócona)"))

    def test_polish_number_formatting(self):
        self.assertEqual(render.fmt_int(12345), "12 345")
        self.assertEqual(render.fmt_pct(61.5), "61,5%")
        self.assertEqual(render.fmt_pct(-3.0, signed=True), "−3%")
        self.assertEqual(render.fmt_pct(4.25, signed=True), "+4,2%")
        self.assertEqual(render.fmt_days(1), "1 dzień")
        self.assertEqual(render.fmt_days(-2), "wygasł 2 dni temu")
        self.assertIn("Akceptacja cookies", render.render_text(xss_dashboard()))


class SitesConfigTests(unittest.TestCase):
    def test_load_from_env_path_with_bom(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "moje-strony.json"
            payload = {
                "sites": [
                    {"name": "Piekarnia", "url": "https://piekarnia.test/", "key": " abc "},
                    {"url": "https://bez-nazwy.test", "key": "def"},
                    {"name": "Wyłączona", "url": "https://off.test", "key": "x", "enabled": False},
                ]
            }
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8-sig")
            with mock.patch.dict(os.environ, {"TARS_SITES_FILE": str(path)}):
                loaded = sites.load_sites()
        self.assertEqual(
            loaded,
            [
                {"name": "Piekarnia", "url": "https://piekarnia.test", "key": "abc"},
                {"name": "bez-nazwy.test", "url": "https://bez-nazwy.test", "key": "def"},
            ],
        )

    def test_default_path_and_errors(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TARS_SITES_FILE", None)
            self.assertEqual(sites.sites_file_path(), Path("sites.json"))
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "zly.json"
            bad.write_text("{nie json", encoding="utf-8")
            with self.assertRaises(sites.SitesConfigError) as ctx:
                sites.load_sites(bad)
            self.assertIn("Błąd składni JSON", str(ctx.exception))
            with self.assertRaises(sites.SitesConfigError):
                sites.load_sites(Path(tmp) / "brak.json")
        with self.assertRaises(sites.SitesConfigError):
            sites.parse_sites([{"url": "https://a.test"}])  # brak klucza
        with self.assertRaises(sites.SitesConfigError):
            sites.parse_sites([{"url": "ftp://a.test", "key": "k"}])
        with self.assertRaises(sites.SitesConfigError):
            sites.parse_sites([{"url": "https://a.test", "key": "k"}, {"url": "https://a.test/", "key": "k"}])
        with self.assertRaises(sites.SitesConfigError):
            sites.parse_sites({"nie": "lista"})

    def test_example_file_is_valid(self):
        example = Path(__file__).resolve().parent.parent / "tars_zrobsite" / "sites.example.json"
        loaded = sites.load_sites(example)
        self.assertEqual(len(loaded), 2)  # trzecia strona ma "enabled": false
        self.assertTrue(all(s["url"].startswith("https://") for s in loaded))


if __name__ == "__main__":
    unittest.main()
