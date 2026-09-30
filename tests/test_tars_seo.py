"""Testy modułu tars_seo (bez internetu i bez Ollamy)."""

import contextlib
import gzip
import io
import json
import os
import re
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tars_seo import (  # noqa: E402
    audit, audit_html, compare, compare_results, extract_keywords, keyword_presence,
    parse_html, render_html, render_telegram, render_text, save_audit, sort_checks,
    suggest, top_fixes, trend, weighted_score, grade,
)
from tars_seo import checks as C  # noqa: E402
from tars_seo.ai import FALLBACK_MESSAGE, validate_variants  # noqa: E402
from tars_seo.fetch import fetch_page, fetch_sitemap, parse_robots, urllib_fetcher  # noqa: E402

# --------------------------------------------------------------------------
# Dane testowe
# --------------------------------------------------------------------------

PARAGRAPH = (
    "Tworzymy nowoczesne strony internetowe dla firm z Łodzi i okolic. Każda strona "
    "internetowa jest szybka, bezpieczna i dopasowana do telefonów. Pomagamy klientom "
    "zdobywać zapytania, projektujemy sklepy, prowadzimy kampanie reklamowe i dbamy "
    "o pozycjonowanie w wyszukiwarce, aby lokalni klienci łatwo znaleźli Twoją ofertę. "
)

LOCAL_JSONLD = {
    "@context": "https://schema.org", "@type": "LocalBusiness", "name": "Dobra Firma",
    "address": {"@type": "PostalAddress", "streetAddress": "Piotrkowska 1",
                "addressLocality": "Łódź", "postalCode": "90-001"},
    "telephone": "+48 600 100 200", "openingHours": "Mo-Fr 09:00-17:00",
}

GOOD_HTML = f"""<!doctype html><html lang="pl"><head>
<meta charset="utf-8"><title>Strony internetowe Łódź – Dobra Firma</title>
<meta name="description" content="Projektujemy szybkie strony internetowe dla firm z Łodzi. Bezpłatna wycena w 24 godziny — zadzwoń i zamów stronę.">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="canonical" href="https://dobra.pl/">
<link rel="icon" href="/favicon.png">
<meta property="og:title" content="Dobra Firma"><meta property="og:description" content="Strony www">
<meta property="og:image" content="https://dobra.pl/og.jpg"><meta name="twitter:card" content="summary_large_image">
<script type="application/ld+json">{json.dumps(LOCAL_JSONLD)}</script>
</head><body>
<h1>Strony internetowe dla firm w Łodzi</h1>
<h2>Oferta</h2><h3>Sklepy</h3><h2>Kontakt</h2>
<p>{PARAGRAPH * 7}</p>
<img src="/a.jpg" alt="Zespół" width="10" height="10" loading="lazy">
<img src="/b.jpg" alt="Biuro" width="10" height="10" loading="lazy">
<img src="/c.jpg" alt="Projekt" width="10" height="10" loading="lazy">
<img src="/d.jpg" alt="Sklep" width="10" height="10" loading="lazy">
<a href="/oferta">Oferta</a> <a href="https://facebook.com/x" rel="nofollow">Facebook</a>
<a href="tel:+48600100200">Zadzwoń: 600 100 200</a>
</body></html>"""

BAD_HTML = """<html><head><meta name="robots" content="noindex, nofollow">
<script src="http://cdn.example.org/lib.js"></script></head><body>
<h3>Witaj</h3><h1>Jeden</h1><h1>Dwa</h1>
<p>Krótki tekst.</p>
<img src="http://obrazki.example.org/x.jpg"><img src="/y.jpg" alt="">
<a href="#">kliknij</a><a href="javascript:void(0)">x</a><a href="/pusty"></a>
</body></html>"""

ROBOTS_OK = "User-agent: *\nDisallow: /wp-admin/\nSitemap: https://dobra.pl/sitemap_index.xml\n"
SITEMAP_INDEX = """<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<sitemap><loc>https://dobra.pl/page-sitemap.xml</loc></sitemap>
<sitemap><loc>https://dobra.pl/post-sitemap.xml</loc></sitemap></sitemapindex>"""
SITEMAP_A = ("<?xml version='1.0'?><urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9' "
             "xmlns:image='http://www.google.com/schemas/sitemap-image/1.1'>"
             + "".join(f"<url><loc>https://dobra.pl/{i}</loc><image:image><image:loc>x</image:loc>"
                       f"</image:image></url>" for i in range(3)) + "</urlset>")
SITEMAP_B = ("<urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>"
             "<url><loc>https://dobra.pl/p1</loc></url><url><loc>https://dobra.pl/p2</loc></url></urlset>")


class FakeWeb:
    """Udawany internet: słownik url → (status, nagłówki, treść)."""

    def __init__(self, pages, elapsed_ms=200.0):
        self.pages = pages
        self.calls = []
        self.elapsed_ms = elapsed_ms

    def __call__(self, url, timeout=None, max_bytes=None):
        self.calls.append(url)
        if url not in self.pages:
            return {"url": url, "status": 404, "headers": {}, "body": b"not found",
                    "elapsed_ms": 5.0, "ttfb_ms": 4.0}
        status, headers, body = self.pages[url]
        if isinstance(body, str):
            body = body.encode("utf-8")
        return {"url": url, "status": status, "headers": headers, "body": body,
                "elapsed_ms": self.elapsed_ms, "ttfb_ms": self.elapsed_ms / 2}


HTML_HDR = {"Content-Type": "text/html; charset=utf-8", "Content-Encoding": "gzip"}


def good_site(html=GOOD_HTML, host="dobra.pl"):
    return FakeWeb({
        f"https://{host}/": (200, HTML_HDR, html),
        f"https://{host}/robots.txt": (200, {}, ROBOTS_OK.replace("dobra.pl", host)),
        f"https://{host}/sitemap_index.xml": (200, {}, SITEMAP_INDEX.replace("dobra.pl", host)),
        f"https://{host}/page-sitemap.xml": (200, {}, SITEMAP_A),
        f"https://{host}/post-sitemap.xml": (200, {}, SITEMAP_B),
        f"http://{host}/": (301, {"Location": f"https://{host}/"}, ""),
        f"https://{host}/favicon.ico": (200, {}, b"\x00\x00\x01\x00"),
    })


def bad_site():
    return FakeWeb({
        "https://zla.pl/": (200, {"Content-Type": "text/html"}, BAD_HTML),
        "https://zla.pl/robots.txt": (200, {}, "User-agent: *\nDisallow: /\n"),
    }, elapsed_ms=2500.0)


def by_id(result):
    return {c["id"]: c for c in result["checks"]}


def ctx_for(html, url="https://dobra.pl/", **extra):
    page = parse_html(html, url)
    ctx = {"url": url, "final_url": url, "page": page, "resp": None, "html": html,
           "keywords": extract_keywords(page["text"])}
    ctx.update(extra)
    return ctx


def html_with(title="", desc="", body=""):
    return (f"<html lang='pl'><head><title>{title}</title>"
            f"<meta name='description' content='{desc}'></head><body>{body}</body></html>")


# --------------------------------------------------------------------------
# Testy
# --------------------------------------------------------------------------

class TestAuditEndToEnd(unittest.TestCase):
    def test_good_page_scores_high(self):
        r = audit("dobra.pl", fetcher=good_site())
        bad = [(c["id"], c["level"], c["detail"]) for c in r["checks"]
               if c["level"] in ("warning", "critical")]
        self.assertEqual(bad, [])
        self.assertGreaterEqual(r["score"], 95)
        self.assertEqual(r["grade"], "A")
        self.assertEqual(r["top3"], [])
        for c in r["checks"]:
            for key in ("id", "category", "level", "title", "why", "fix", "weight"):
                self.assertIn(key, c)
            self.assertIn(c["category"], C.CATEGORIES)
        self.assertGreaterEqual(len(r["checks"]), 25)

    def test_bad_page_flags_critical_problems(self):
        r = audit("https://zla.pl/", fetcher=bad_site())
        ids = by_id(r)
        for cid in ("title", "meta_description", "viewport", "indexable", "robots_txt",
                    "mixed_content", "response_time", "word_count"):
            self.assertEqual(ids[cid]["level"], "critical", cid)
        self.assertEqual(ids["h1"]["level"], "warning")
        self.assertEqual(ids["heading_order"]["level"], "warning")
        self.assertEqual(ids["sitemap"]["level"], "warning")
        self.assertEqual(ids["links"]["level"], "warning")
        self.assertIn("bez adresu: 2", ids["links"]["detail"])
        self.assertIn("bez tekstu: 1", ids["links"]["detail"])
        self.assertTrue(r["blocked"])  # noindex + robots.txt → wynik ograniczony
        self.assertLessEqual(r["score"], 39)
        self.assertEqual(r["grade"], "F")
        self.assertEqual(len(r["top3"]), 3)
        self.assertTrue(all(t["level"] == "critical" for t in r["top3"]))

    def test_unreachable_site(self):
        def broken(url, **kw):
            raise OSError("brak sieci")
        r = audit("https://nie-ma.pl", fetcher=broken)
        self.assertEqual(r["score"], 0)
        self.assertEqual(r["grade"], "F")
        self.assertIn("brak sieci", r["error"])
        self.assertEqual(r["checks"][0]["title"], "Strona nie odpowiada")


class TestIndividualChecks(unittest.TestCase):
    def test_title_length_boundaries(self):
        for n, level in ((0, "critical"), (29, "warning"), (30, "ok"), (60, "ok"), (61, "warning")):
            r = C.check_title(ctx_for(html_with(title="a" * n)))
            self.assertEqual(r["level"], level, n)

    def test_meta_description_boundaries(self):
        for n, level in ((0, "critical"), (69, "warning"), (70, "ok"), (160, "ok"), (161, "warning")):
            r = C.check_meta_description(ctx_for(html_with(desc="b" * n)))
            self.assertEqual(r["level"], level, n)

    def test_h1_and_heading_order(self):
        self.assertEqual(C.check_h1(ctx_for(html_with(body="<p>x</p>")))["level"], "critical")
        self.assertEqual(C.check_h1(ctx_for(html_with(body="<h1>a</h1><h1>b</h1>")))["level"], "warning")
        self.assertEqual(C.check_h1(ctx_for(html_with(body="<h1>a</h1>")))["level"], "ok")
        skip = C.check_heading_order(ctx_for(html_with(body="<h1>A</h1><h3>C</h3>")))
        self.assertEqual(skip["level"], "warning")
        self.assertIn("H1 → H3", skip["detail"])
        ok = C.check_heading_order(ctx_for(html_with(body="<h1>A</h1><h2>B</h2><h3>C</h3><h2>D</h2>")))
        self.assertEqual(ok["level"], "ok")

    def test_images_alt_dimensions_lazy(self):
        imgs = "".join(f"<img src='{i}.jpg'>" for i in range(3)) + \
            "<img src='z.jpg' alt='opis' width='1' height='1' loading='lazy'>"
        ctx = ctx_for(html_with(body=imgs))
        alt = C.check_img_alt(ctx)
        self.assertEqual(alt["level"], "critical")
        self.assertIn("3 z 4", alt["detail"])
        self.assertEqual(C.check_img_dimensions(ctx)["level"], "warning")
        self.assertEqual(C.check_lazy_loading(ctx)["level"], "ok")
        no_lazy = ctx_for(html_with(body="<img src='a' alt='x'>" * 5))
        self.assertEqual(C.check_lazy_loading(no_lazy)["level"], "warning")
        self.assertEqual(C.check_img_alt(no_lazy)["level"], "ok")

    def test_canonical_and_noindex(self):
        self_c = ctx_for("<head><link rel='canonical' href='https://dobra.pl'></head>")
        self.assertEqual(C.check_canonical(self_c)["level"], "ok")
        other = ctx_for("<head><link rel='canonical' href='https://inna.pl/x'></head>")
        self.assertEqual(C.check_canonical(other)["level"], "warning")
        self.assertEqual(C.check_canonical(ctx_for("<p>x</p>"))["level"], "warning")
        hdr = ctx_for("<p>x</p>", resp={"headers": {"x-robots-tag": "noindex"}})
        self.assertEqual(C.check_indexable(hdr)["level"], "critical")
        self.assertEqual(C.check_indexable(ctx_for("<p>x</p>"))["level"], "ok")

    def test_mixed_content_detection(self):
        html = ("<link rel='stylesheet' href='http://a.pl/s.css'><img src='http://a.pl/i.jpg'>"
                "<img src='https://a.pl/ok.jpg'><a href='http://a.pl/'>link to nie zasób</a>"
                "<iframe src='http://yt.pl/e'></iframe>")
        page = parse_html(html, "https://dobra.pl/")
        kinds = sorted((m["tag"], m["kind"]) for m in page["mixed_content"])
        self.assertEqual(kinds, [("iframe", "active"), ("img", "passive"), ("link", "active")])
        self.assertEqual(C.check_mixed_content(ctx_for(html))["level"], "critical")
        passive = ctx_for("<img src='http://a.pl/i.jpg'>")
        self.assertEqual(C.check_mixed_content(passive)["level"], "warning")
        http_page = ctx_for(html, url="http://dobra.pl/")
        self.assertEqual(parse_html(html, "http://dobra.pl/")["mixed_content"], [])
        self.assertIsNone(C.check_mixed_content(http_page))

    def test_robots_disallow_all(self):
        self.assertTrue(parse_robots("User-agent: *\nDisallow: /\n")["disallow_all"])
        self.assertTrue(parse_robots("User-agent: Googlebot\nUser-agent: *\nDisallow: / # all\n")["disallow_all"])
        self.assertFalse(parse_robots("User-agent: BadBot\nDisallow: /\n\nUser-agent: *\nDisallow:\n")["disallow_all"])
        self.assertFalse(parse_robots("User-agent: *\nDisallow: /wp-admin/\n")["disallow_all"])
        info = parse_robots("Sitemap: https://a.pl/s.xml\nUser-agent: *\nAllow: /\n")
        self.assertEqual(info["sitemaps"], ["https://a.pl/s.xml"])
        r = C.check_robots_txt({"robots": {"found": True, "disallow_all": True}})
        self.assertEqual(r["level"], "critical")

    def test_sitemap_index_counting(self):
        web = good_site()
        sm = fetch_sitemap("https://dobra.pl/", ["https://dobra.pl/sitemap_index.xml"], web)
        self.assertTrue(sm["found"])
        self.assertTrue(sm["is_index"])
        self.assertEqual(sm["url_count"], 5)  # 3 + 2, bez liczenia <image:loc>
        self.assertEqual(sm["sitemaps"], 2)
        # bez wpisu w robots.txt → szuka /sitemap.xml, potem /sitemap_index.xml
        fallback = fetch_sitemap("https://dobra.pl/", [], web)
        self.assertEqual(fallback["url"], "https://dobra.pl/sitemap_index.xml")
        none = fetch_sitemap("https://pusta.pl/", [], FakeWeb({}))
        self.assertFalse(none["found"])

    def test_redirect_chain_and_http_to_https(self):
        web = FakeWeb({
            "http://a.pl/": (301, {"Location": "https://a.pl/"}, ""),
            "https://a.pl/": (302, {"Location": "/start"}, ""),
            "https://a.pl/start": (301, {"Location": "https://www.a.pl/start"}, ""),
            "https://www.a.pl/start": (200, {}, "<title>x</title>"),
        })
        r = fetch_page("http://a.pl/", web)
        self.assertEqual(r["final_url"], "https://www.a.pl/start")
        self.assertEqual([x["status"] for x in r["redirects"]], [301, 302, 301])
        self.assertEqual(r["elapsed_ms"], 800.0)
        chk = C.check_redirects({"resp": r, "final_url": r["final_url"]})
        self.assertEqual(chk["level"], "warning")
        loop = FakeWeb({"https://l.pl/": (302, {"Location": "https://l.pl/"}, "")})
        self.assertIn("pętla", fetch_page("https://l.pl/", loop)["error"])
        hr = C.check_http_redirect({"final_url": "https://a.pl/",
                                    "http_redirect": {"checked": True, "to_https": False,
                                                      "final_url": "http://a.pl/"}})
        self.assertEqual(hr["level"], "warning")

    def test_local_business_completeness(self):
        full = f"<script type='application/ld+json'>{json.dumps(LOCAL_JSONLD)}</script>"
        self.assertEqual(C.check_local_business(ctx_for(full))["level"], "ok")
        partial = {"@context": "https://schema.org",
                   "@graph": [{"@type": "WebSite", "name": "x"},
                              {"@type": ["Dentist"], "name": "Ząbek",
                               "address": {"@type": "PostalAddress", "streetAddress": ""}}]}
        r = C.check_local_business(ctx_for(
            f"<script type='application/ld+json'>{json.dumps(partial)}</script>"))
        self.assertEqual(r["level"], "warning")
        for field in ("adres", "telefon", "godziny otwarcia"):
            self.assertIn(field, r["fix"])
        self.assertNotIn("nazwa", r["detail"].split("brakuje:")[1])
        spec = dict(LOCAL_JSONLD)
        spec.pop("openingHours")
        spec["openingHoursSpecification"] = [{"@type": "OpeningHoursSpecification", "opens": "09:00"}]
        ok2 = C.check_local_business(ctx_for(
            f"<script type='application/ld+json'>{json.dumps(spec)}</script>"))
        self.assertEqual(ok2["level"], "ok")
        self.assertEqual(C.check_local_business(ctx_for("<p>x</p>"))["level"], "warning")
        broken = ctx_for("<script type='application/ld+json'>{zepsute</script>")
        self.assertEqual(C.check_structured_data(broken)["level"], "critical")

    def test_parser_extracts_everything(self):
        p = parse_html(GOOD_HTML, "https://dobra.pl/")
        self.assertEqual(p["title"], "Strony internetowe Łódź – Dobra Firma")
        self.assertEqual(p["lang"], "pl")
        self.assertEqual(p["h1"], ["Strony internetowe dla firm w Łodzi"])
        self.assertEqual(p["h2"], ["Oferta", "Kontakt"])
        self.assertIn("LocalBusiness", p["jsonld"]["types"])
        self.assertEqual(p["favicon"], "https://dobra.pl/favicon.png")
        kinds = [l["kind"] for l in p["links"]]
        self.assertEqual(kinds, ["internal", "external", "contact"])
        self.assertTrue(p["links"][1]["nofollow"])
        self.assertGreater(p["word_count"], 300)
        self.assertNotIn("LocalBusiness", p["text"])  # JSON-LD to nie widoczny tekst
        self.assertEqual(p["og"]["og:image"], "https://dobra.pl/og.jpg")
        self.assertEqual(p["tel_links"], ["+48600100200"])


class TestScoring(unittest.TestCase):
    def mk(self, cid, level, weight, category="Podstawy"):
        return {"id": cid, "category": category, "level": level, "weight": weight,
                "title": cid, "why": "", "fix": "", "detail": ""}

    def test_score_math_and_grade_boundaries(self):
        checks = [self.mk("a", "ok", 10), self.mk("b", "warning", 10), self.mk("c", "critical", 10),
                  self.mk("d", "info", 50)]
        self.assertEqual(weighted_score(checks), 50)
        self.assertEqual(weighted_score([self.mk("a", "ok", 3), self.mk("b", "critical", 1)]), 75)
        from tars_seo.score import summarize
        fine = [self.mk("a", "ok", 90), self.mk("status", "ok", 10)]
        self.assertEqual(summarize(fine)["score"], 100)
        hidden = [self.mk("a", "ok", 90), self.mk("indexable", "critical", 10)]
        self.assertEqual(weighted_score(hidden), 90)
        self.assertEqual(summarize(hidden)["score"], 39)  # noindex → maks. 39
        self.assertTrue(summarize(hidden)["blocked"])
        self.assertIsNone(weighted_score([self.mk("d", "info", 5)]))
        cases = {100: "A", 90: "A", 89: "B", 80: "B", 79: "C", 70: "C", 69: "D", 55: "D",
                 54: "E", 40: "E", 39: "F", 0: "F"}
        for score, letter in cases.items():
            self.assertEqual(grade(score)[0], letter, score)

    def test_top3_and_sorting(self):
        checks = [self.mk("w_big", "warning", 15), self.mk("c_small", "critical", 2),
                  self.mk("c_big", "critical", 12, "Treść"), self.mk("ok", "ok", 20),
                  self.mk("w_small", "warning", 1, "Szybkość"), self.mk("i", "info", 0)]
        self.assertEqual([c["id"] for c in top_fixes(checks)], ["c_big", "c_small", "w_big"])
        by_cat = [c["category"] for c in sort_checks(checks, "category")]
        self.assertEqual(by_cat, sorted(by_cat, key=C.CATEGORIES.index))
        levels = [c["level"] for c in sort_checks(checks, "level")]
        self.assertEqual(levels, ["critical", "critical", "warning", "warning", "info", "ok"])
        with self.assertRaises(ValueError):
            sort_checks(checks, "alfabet")


class TestKeywords(unittest.TestCase):
    def test_polish_stopwords_and_diacritics(self):
        text = ("Oferujemy strony internetowe w Łodzi. Nasze strony internetowe są szybkie, "
                "a strony internetowe sklepów też. W ŁODZI i w lodzi robimy to się i jest dobrze. "
                "Łódź to miasto, łódź to łódź.")
        kws = extract_keywords(text, top=5)
        phrases = [k["phrase"] for k in kws]
        self.assertEqual(phrases[0], "strony internetowe")
        self.assertEqual(kws[0]["count"], 3)
        joined = " ".join(k["key"] for k in kws)
        for stop in (" się ", " jest ", " oraz "):
            self.assertNotIn(stop.strip(), joined.split())
        lodzi = next(k for k in kws if k["key"] == "lodzi")
        self.assertEqual(lodzi["count"], 3)  # Łodzi / ŁODZI / lodzi to to samo słowo
        lodz = next(k for k in kws if k["key"] == "lodz")
        self.assertEqual(lodz["phrase"], "łódź")
        pres = keyword_presence("strony internetowe", "Tania STRONA internetowa – Łódź",
                                ["Sklepy online"], "Robimy strony internetowe.")
        self.assertEqual(pres, {"title": True, "h1": False, "meta": True})


class TestCompareAndHistory(unittest.TestCase):
    def test_compare_winner_logic(self):
        cats = {c: 50 for c in C.CATEGORIES}
        a = {"url": "https://a.pl/", "score": 70, "grade": "C",
             "categories": {**cats, "Podstawy": 90, "Szybkość": 20, "Social": None},
             "checks": [{"id": "og", "level": "warning", "title": "Brak OG", "fix": "Dodaj OG"}]}
        b = {"url": "https://b.pl/", "score": 60, "grade": "D",
             "categories": {**cats, "Podstawy": 80, "Szybkość": 90, "Social": None},
             "checks": [{"id": "og", "level": "ok", "title": "OG ok", "fix": ""}]}
        res = compare_results(a, b)
        winners = {r["category"]: r["winner"] for r in res["categories"]}
        self.assertEqual(winners["Podstawy"], "a")
        self.assertEqual(winners["Szybkość"], "b")
        self.assertEqual(winners["Treść"], "remis")
        self.assertIsNone(winners["Social"])
        self.assertEqual(res["wins"], {"a": 1, "b": 1})
        self.assertEqual(res["overall_winner"], "a")
        self.assertEqual([c["id"] for c in res["catch_up"]], ["og"])

    def test_compare_end_to_end(self):
        web = good_site()
        web.pages.update(bad_site().pages)
        res = compare("https://dobra.pl/", "https://zla.pl/", fetcher=web)
        self.assertEqual(res["overall_winner"], "a")
        self.assertGreater(res["wins"]["a"], res["wins"]["b"])

    def test_history_trend_fixed_broken(self):
        with tempfile.TemporaryDirectory() as tmp:
            t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
            old = audit_html(html_with(title="x" * 40, body="<h1>Tytuł</h1>"), "https://h.pl/")
            new = audit_html(html_with(title="", desc="d" * 100, body="<h1>Tytuł</h1>"), "https://h.pl/")
            save_audit(old, tmp, now=t0)
            with mock.patch.dict(os.environ, {"TARS_SEO_DIR": tmp}):
                save_audit(new, now=t0 + timedelta(days=7))
                tr = trend("h.pl")
            self.assertEqual(tr["count"], 2)
            self.assertEqual(tr["delta"], new["score"] - old["score"])
            self.assertIn("meta_description", [f["id"] for f in tr["fixed"]])
            self.assertIn("title", [b["id"] for b in tr["broken"]])
            files = list(Path(tmp).glob("*.json"))
            self.assertEqual(len(files), 2)
            self.assertTrue(all(re.match(r"^[a-z0-9._-]+__[0-9-]+\.json$", f.name) for f in files))
            self.assertIsNone(trend("https://inna.pl/", tmp)["delta"])


class TestAI(unittest.TestCase):
    def result(self):
        return audit("https://dobra.pl/", fetcher=good_site())

    def test_suggestion_validation(self):
        calls = []

        def fake_ai(prompt, task=None, json_mode=False):
            calls.append((task, json_mode))
            return json.dumps({
                "titles": ["Za krótki", "Strony internetowe Łódź – szybko i tanio | Dobra",
                           "„Strony WWW dla firm z Łodzi – bezpłatna wycena”",
                           "Strony internetowe Łódź – szybko i tanio | Dobra",  # dubel
                           "x" * 61, "Sklepy internetowe i strony WWW w Łodzi – Dobra Firma"],
                "descriptions": ["krótko", "d" * 161,
                                 "Tworzymy szybkie strony internetowe dla firm z Łodzi. Zadzwoń i odbierz darmową wycenę!",
                                 "Strona, sklep i SEO w jednym miejscu. Dobra Firma z Łodzi — sprawdź ofertę i zadzwoń."],
            })

        s = suggest(self.result(), ai_fn=fake_ai)
        self.assertTrue(s["ok"])
        self.assertEqual(len(s["titles"]), 3)
        self.assertEqual(len(s["descriptions"]), 2)
        for t in s["titles"]:
            self.assertTrue(30 <= t["length"] <= 60)
            self.assertEqual(t["length"], len(t["text"]))
            self.assertFalse(t["text"].startswith("„"))
        for d in s["descriptions"]:
            self.assertTrue(70 <= d["length"] <= 160)
        self.assertEqual(len(calls), 2)  # za mało opisów → jedna ponowna próba
        self.assertEqual(calls[0], ("seo", True))
        self.assertEqual(s["local_business"]["name"], "Dobra Firma")
        self.assertEqual(s["local_business"]["telephone"], "+48 600 100 200")
        valid, rejected = validate_variants(["<b>Tytuł z HTML-em, który jest dość długi</b>"], 30, 60)
        self.assertEqual((valid, rejected), ([], 1))

    def test_fallback_when_ai_fails(self):
        def boom(prompt, **kw):
            raise RuntimeError("Ollama nie odpowiada")

        r = audit_html("<html><head><title>Hydraulik 24h | Kowalski</title></head><body>"
                       "<a href='tel:+48 111 222 333'>Zadzwoń</a></body></html>", "https://k.pl/")
        s = suggest(r, ai_fn=boom)
        self.assertFalse(s["ok"])
        self.assertEqual(s["message"], FALLBACK_MESSAGE)
        self.assertEqual(s["titles"], [])
        lb = s["local_business"]
        self.assertEqual(lb["@type"], "LocalBusiness")
        self.assertEqual(lb["name"], "Kowalski")
        self.assertEqual(lb["telephone"], "+48 111 222 333")
        self.assertEqual(lb["address"]["streetAddress"], "UZUPEŁNIJ")
        json.loads(s["local_business_json"])
        garbage = suggest(r, ai_fn=lambda p, **k: "nie umiem w JSON")
        self.assertFalse(garbage["ok"])
        self.assertIn("poprawnej długości", garbage["message"])


class TestReports(unittest.TestCase):
    def test_html_escapes_malicious_title(self):
        evil = '<script>alert("x")</script>" onmouseover="alert(1)'
        html = f"<html><head><title>{evil.replace('<', '&lt;')}</title></head><body><h1>{evil}</h1></body></html>"
        r = audit_html(html, "https://zly.pl/")
        self.assertIn("<script>", r["page"]["title"])
        r["ai"] = {"message": "<img src=x onerror=alert(1)>", "titles": [{"text": "<b>", "length": 3}],
                   "descriptions": [], "local_business": {"name": "</pre><script>"}}
        out = render_html(r)
        self.assertNotIn("<script", out.lower())
        self.assertNotIn("<img", out.lower())
        self.assertNotIn('" onmouseover', out)
        self.assertIn("&lt;script&gt;", out)
        self.assertIn("prefers-color-scheme:dark", out)
        self.assertIn("<svg", out)
        self.assertIsNone(re.search(r"""(src|href)=["']?https?://""", out))
        self.assertEqual(out.count("<details"), len(r["checks"]))

    def test_telegram_output_short_and_safe(self):
        r = audit("https://zla.pl/", fetcher=bad_site())
        msg = render_telegram(r)
        self.assertLessEqual(len(msg), 4096)
        self.assertIn(f"{r['score']}/100", msg)
        self.assertIn("Top 3", msg)
        self.assertIn("🔴", msg)
        huge = dict(r)
        huge["top3"] = [dict(t, title="<b>" * 400, fix="Ż" * 5000) for t in r["top3"]]
        huge["final_url"] = "https://" + "a" * 3000 + ".pl/"
        msg2 = render_telegram(huge)
        self.assertLessEqual(len(msg2.encode("utf-16-le")) // 2, 4096)
        self.assertNotIn("<b><b>", msg2)

    def test_text_report(self):
        r = audit("https://zla.pl/", fetcher=bad_site())
        txt = render_text(r, sort="category")
        self.assertIn("TOP 3 RZECZY DO POPRAWY", txt)
        self.assertIn("-- Podstawy --", txt)
        self.assertIn(f"{r['score']}/100", txt)


class _Handler(BaseHTTPRequestHandler):
    seen_agents = []

    def log_message(self, *a):
        pass

    def do_GET(self):  # noqa: N802
        _Handler.seen_agents.append(self.headers.get("User-Agent"))
        if self.path == "/":
            self.send_response(302)
            self.send_header("Location", "/strona")
            self.end_headers()
            return
        if self.path == "/strona":
            body = gzip.compress(GOOD_HTML.encode("utf-8"))
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()


class TestRealFetcherLocalServer(unittest.TestCase):
    """Prawdziwy urllib na lokalnym serwerze (127.0.0.1) — bez internetu."""

    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        cls.thread = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def test_urllib_fetcher_redirect_gzip(self):
        with mock.patch.dict(os.environ, {"NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"}):
            r = fetch_page(self.base + "/", urllib_fetcher, timeout=5)
            raw = urllib_fetcher(self.base + "/strona", timeout=5, max_bytes=100)
        self.assertEqual(r["status"], 200)
        self.assertEqual(r["final_url"], self.base + "/strona")
        self.assertEqual(r["redirects"][0]["status"], 302)
        self.assertIn("Strony internetowe Łódź", r["text"])
        self.assertIsNotNone(r["ttfb_ms"])
        self.assertTrue(raw["truncated"])
        self.assertIn("TARS-SEO/1.0", _Handler.seen_agents)

    def test_cli_audit_writes_html_and_history(self):
        from tars_seo.__main__ import main
        with tempfile.TemporaryDirectory() as tmp:
            out_html = Path(tmp) / "raport.html"
            env = {"TARS_SEO_DIR": str(Path(tmp) / "hist"), "NO_PROXY": "127.0.0.1",
                   "no_proxy": "127.0.0.1"}
            buf, err = io.StringIO(), io.StringIO()
            with mock.patch.dict(os.environ, env), contextlib.redirect_stdout(buf), \
                    contextlib.redirect_stderr(err):
                code = main(["audit", self.base + "/", "--html", str(out_html), "--save"])
            self.assertEqual(code, 0)
            self.assertIn("AUDYT SEO", buf.getvalue())
            self.assertTrue(out_html.read_text(encoding="utf-8").startswith("<!doctype html>"))
            self.assertEqual(len(list((Path(tmp) / "hist").glob("*.json"))), 1)


if __name__ == "__main__":
    unittest.main()
