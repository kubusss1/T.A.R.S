"""Sprawdzenia SEO napisane „po ludzku”.

Każde sprawdzenie zwraca słownik::

    {"id", "category", "level", "title", "why", "fix", "weight", "detail"}

* ``level`` — ``ok`` | ``warning`` | ``critical`` | ``info`` (info nie liczy się do wyniku),
* ``title`` — krótko, co wyszło,
* ``why`` — jedno proste zdanie, dlaczego to ważne,
* ``fix`` — jedna konkretna instrukcja, co kliknąć / wpisać,
* ``detail`` — co dokładnie znaleźliśmy.
"""
from __future__ import annotations

from typing import Callable
from urllib.parse import urlsplit

from .keywords import keyword_presence

CATEGORIES = ("Podstawy", "Treść", "Techniczne", "Social", "Lokalne SEO", "Szybkość")
LEVELS = ("critical", "warning", "info", "ok")

LOCAL_TYPES = {
    "LocalBusiness", "ProfessionalService", "Store", "Restaurant", "FoodEstablishment",
    "CafeOrCoffeeShop", "Bakery", "BarOrPub", "Dentist", "MedicalBusiness", "MedicalClinic",
    "Physician", "Pharmacy", "Optician", "HealthAndBeautyBusiness", "BeautySalon",
    "HairSalon", "DaySpa", "NailSalon", "HomeAndConstructionBusiness", "Plumber",
    "Electrician", "HVACBusiness", "GeneralContractor", "RoofingContractor", "Locksmith",
    "HousePainter", "MovingCompany", "AutomotiveBusiness", "AutoRepair", "AutoDealer",
    "AutoBodyShop", "AutoWash", "LegalService", "Attorney", "Notary", "AccountingService",
    "FinancialService", "InsuranceAgency", "RealEstateAgent", "LodgingBusiness", "Hotel",
    "SportsActivityLocation", "ExerciseGym", "EntertainmentBusiness", "TravelAgency",
    "ChildCare", "Library", "AnimalShelter", "VeterinaryCare", "EmploymentAgency",
    "EducationalOrganization", "GardenStore", "FurnitureStore", "ClothingStore",
    "ElectronicsStore", "HardwareStore", "Florist", "PetStore",
}
LOCAL_REQUIRED = {
    "name": "nazwa",
    "address": "adres",
    "telephone": "telefon",
    "openingHours": "godziny otwarcia",
}


def _check(cid: str, category: str, level: str, title: str, why: str, fix: str,
           weight: int, detail: str = "") -> dict:
    return {"id": cid, "category": category, "level": level, "title": title,
            "why": why, "fix": fix, "weight": int(weight), "detail": detail}


def _norm_url(u: str | None) -> str:
    if not u:
        return ""
    p = urlsplit(u)
    host = (p.hostname or "").lower()
    path = p.path or "/"
    if len(path) > 1:
        path = path.rstrip("/")
    return f"{host}{path}{'?' + p.query if p.query else ''}"


def _short(text: str | None, n: int = 70) -> str:
    text = text or ""
    return text if len(text) <= n else text[: n - 1] + "…"


# ==========================================================================
# PODSTAWY
# ==========================================================================

def check_status(ctx: dict) -> dict | None:
    resp = ctx.get("resp")
    if resp is None:
        return None
    why = "Jeśli strona nie odpowiada poprawnie, Google i klienci jej po prostu nie zobaczą."
    fix = "Sprawdź w panelu hostingu, czy strona działa, i napraw błąd (albo napisz do ZrobSite)."
    if resp.get("error") and not resp.get("status"):
        return _check("status", "Podstawy", "critical", "Strona nie odpowiada", why, fix, 15,
                      resp["error"])
    status = resp.get("status") or 0
    if status == 200:
        return _check("status", "Podstawy", "ok", "Strona działa (kod 200)", why, fix, 15,
                      f"Kod odpowiedzi: {status}")
    if 200 < status < 300:
        return _check("status", "Podstawy", "warning", f"Nietypowa odpowiedź serwera ({status})",
                      why, fix, 15, f"Kod odpowiedzi: {status}")
    return _check("status", "Podstawy", "critical", f"Strona zwraca błąd {status}", why, fix, 15,
                  resp.get("error") or f"Kod odpowiedzi: {status}")


def check_title(ctx: dict) -> dict:
    title = ctx["page"].get("title") or ""
    n = len(title)
    why = "Tytuł to niebieski napis w Google — od niego zależy, czy ktoś kliknie."
    fix = ("W WordPress: Yoast SEO → „Tytuł SEO”, wpisz 30–60 znaków: "
           "usługa + miasto + nazwa firmy.")
    if not title:
        return _check("title", "Podstawy", "critical", "Brak tytułu strony", why, fix, 10,
                      "Strona nie ma znacznika <title>.")
    detail = f"„{_short(title)}” — {n} znaków"
    if n < 30:
        return _check("title", "Podstawy", "warning", "Tytuł jest za krótki", why, fix, 10, detail)
    if n > 60:
        return _check("title", "Podstawy", "warning", "Tytuł jest za długi (Google go utnie)",
                      why, fix, 10, detail)
    return _check("title", "Podstawy", "ok", "Tytuł ma dobrą długość", why, fix, 10, detail)


def check_meta_description(ctx: dict) -> dict:
    desc = ctx["page"].get("meta_description") or ""
    n = len(desc)
    why = "Opis pod tytułem w Google to Twoja reklama — dobry opis daje więcej kliknięć."
    fix = ("W WordPress: Yoast SEO → „Opis meta”, napisz 70–160 znaków: co oferujesz, "
           "gdzie i zachęta typu „Zadzwoń”.")
    if not desc:
        return _check("meta_description", "Podstawy", "critical", "Brak opisu strony (meta description)",
                      why, fix, 8, "Google sam wybierze przypadkowy fragment tekstu.")
    detail = f"„{_short(desc, 90)}” — {n} znaków"
    if n < 70:
        return _check("meta_description", "Podstawy", "warning", "Opis strony jest za krótki",
                      why, fix, 8, detail)
    if n > 160:
        return _check("meta_description", "Podstawy", "warning", "Opis strony jest za długi",
                      why, fix, 8, detail)
    return _check("meta_description", "Podstawy", "ok", "Opis strony ma dobrą długość",
                  why, fix, 8, detail)


def check_h1(ctx: dict) -> dict:
    h1 = ctx["page"].get("h1") or []
    why = "Nagłówek H1 mówi Google i czytelnikowi, o czym jest ta strona."
    if not h1:
        return _check("h1", "Podstawy", "critical", "Brak głównego nagłówka H1", why,
                      "Dodaj na górze strony jeden nagłówek H1 z główną usługą "
                      "(w edytorze: blok Nagłówek → poziom H1).", 8, "Nie znaleziono H1.")
    if len(h1) > 1:
        return _check("h1", "Podstawy", "warning", f"Za dużo nagłówków H1 ({len(h1)})", why,
                      "Zostaw jeden H1, pozostałe zmień na H2 (zaznacz nagłówek → poziom H2).", 8,
                      "; ".join(f"„{_short(h, 40)}”" for h in h1[:5]))
    return _check("h1", "Podstawy", "ok", "Jest dokładnie jeden nagłówek H1", why,
                  "Dodaj na górze strony jeden nagłówek H1 z główną usługą.", 8,
                  f"„{_short(h1[0])}”")


def check_indexable(ctx: dict) -> dict:
    page = ctx["page"]
    resp = ctx.get("resp") or {}
    meta = (page.get("robots_meta") or "").lower()
    header = (resp.get("headers") or {}).get("x-robots-tag", "").lower()
    why = "Znacznik „noindex” każe Google ukryć stronę — nikt jej nie znajdzie w wyszukiwarce."
    fix = ("W WordPress: Ustawienia → Czytanie → odznacz „Proś wyszukiwarki o nieindeksowanie "
           "witryny”; w Yoast: Zaawansowane → „Pokazuj w wynikach” = Tak.")
    if "noindex" in meta or "noindex" in header or "none" in [m.strip() for m in meta.split(",")]:
        where = "znacznik meta robots" if "noindex" in meta or "none" in meta else "nagłówek X-Robots-Tag"
        return _check("indexable", "Podstawy", "critical", "Strona jest ukryta przed Google (noindex)",
                      why, fix, 15, f"Blokada: {where}.")
    return _check("indexable", "Podstawy", "ok", "Google może pokazywać tę stronę", why, fix, 15,
                  "Brak blokady noindex.")


def check_robots_txt(ctx: dict) -> dict | None:
    robots = ctx.get("robots")
    why = "Plik robots.txt mówi Google, czego nie czytać — zła linijka może ukryć całą stronę."
    fix = "Otwórz robots.txt (Yoast → Narzędzia → Edytor plików) i usuń „Disallow: /” pod „User-agent: *”."
    if robots is None:
        return None
    if robots.get("disallow_all"):
        return _check("robots_txt", "Podstawy", "critical", "robots.txt blokuje całą stronę",
                      why, fix, 12, "W robots.txt jest „Disallow: /” dla wszystkich robotów.")
    if not robots.get("found"):
        return _check("robots_txt", "Podstawy", "info", "Brak pliku robots.txt (nie jest wymagany)",
                      why, "Możesz dodać prosty robots.txt z linią „Sitemap: adres-mapy-strony”.", 0,
                      f"Kod odpowiedzi: {robots.get('status') or 'brak'}")
    return _check("robots_txt", "Podstawy", "ok", "robots.txt nie blokuje strony", why, fix, 12,
                  f"Reguł dla wszystkich robotów: {len(robots.get('rules') or [])}")


def check_sitemap(ctx: dict) -> dict | None:
    sm = ctx.get("sitemap")
    if sm is None:
        return None
    why = "Mapa strony to spis treści dla Google — nowe podstrony szybciej trafiają do wyników."
    fix = "Włącz mapę strony: Yoast → Ustawienia → Mapy witryn XML, potem zgłoś ją w Google Search Console."
    if not sm.get("found"):
        return _check("sitemap", "Podstawy", "warning", "Brak mapy strony (sitemap.xml)", why, fix, 6,
                      "Nie znaleziono w robots.txt, /sitemap.xml ani /sitemap_index.xml.")
    kind = "indeks map" if sm.get("is_index") else "mapa"
    detail = f"{kind}: {sm.get('url')} — adresów: {sm.get('url_count', 0)}"
    if sm.get("url_count", 0) == 0:
        return _check("sitemap", "Podstawy", "warning", "Mapa strony jest pusta", why, fix, 6, detail)
    return _check("sitemap", "Podstawy", "ok", "Jest mapa strony", why, fix, 6, detail)


def check_canonical(ctx: dict) -> dict:
    page = ctx["page"]
    canonical = page.get("canonical")
    why = "Adres kanoniczny mówi Google, która wersja strony jest „ta właściwa” — bez dublowania."
    if not canonical:
        return _check("canonical", "Podstawy", "warning", "Brak adresu kanonicznego", why,
                      "Włącz Yoast lub Rank Math — dodadzą znacznik canonical automatycznie.", 6,
                      "Brak <link rel=\"canonical\">.")
    if _norm_url(canonical) != _norm_url(ctx.get("final_url")):
        return _check("canonical", "Podstawy", "warning", "Adres kanoniczny wskazuje inną stronę", why,
                      "W Yoast → Zaawansowane → „Kanoniczny URL” zostaw puste albo wpisz adres tej strony.",
                      6, f"canonical: {_short(canonical, 90)}")
    return _check("canonical", "Podstawy", "ok", "Adres kanoniczny wskazuje tę stronę", why,
                  "Nic nie trzeba zmieniać.", 6, _short(canonical, 90))


# ==========================================================================
# TREŚĆ
# ==========================================================================

def check_word_count(ctx: dict) -> dict:
    n = ctx["page"].get("word_count", 0)
    why = "Google chętniej pokazuje strony, które konkretnie odpowiadają na pytania klientów."
    fix = "Dopisz min. 300 słów konkretów: co robisz, dla kogo, gdzie, za ile, najczęstsze pytania (FAQ)."
    detail = f"Słów na stronie: {n}"
    if n < 100:
        return _check("word_count", "Treść", "critical", "Bardzo mało tekstu na stronie", why, fix, 8, detail)
    if n < 300:
        return _check("word_count", "Treść", "warning", "Za mało tekstu (poniżej 300 słów)", why, fix, 8, detail)
    return _check("word_count", "Treść", "ok", "Tekstu jest wystarczająco", why, fix, 8, detail)


def check_heading_order(ctx: dict) -> dict:
    heads = ctx["page"].get("headings") or []
    why = "Nagłówki po kolei (H1 → H2 → H3) to czytelny spis treści dla ludzi i Google."
    fix = "Nie przeskakuj poziomów: po H1 daj H2, a dopiero pod nim H3 (zmień poziom w edytorze)."
    if not heads:
        return _check("heading_order", "Treść", "warning", "Brak nagłówków na stronie", why, fix, 4,
                      "Strona nie ma żadnych nagłówków H1–H6.")
    problems = []
    prev = 0
    for h in heads:
        if prev and h["level"] > prev + 1:
            problems.append(f"H{prev} → H{h['level']} („{_short(h['text'], 30)}”)")
        prev = h["level"]
    if heads[0]["level"] != 1 and any(h["level"] == 1 for h in heads):
        problems.insert(0, f"pierwszy nagłówek to H{heads[0]['level']}, a nie H1")
    if problems:
        return _check("heading_order", "Treść", "warning", "Nagłówki nie są po kolei", why, fix, 4,
                      "; ".join(problems[:3]))
    return _check("heading_order", "Treść", "ok", "Nagłówki są ułożone po kolei", why, fix, 4,
                  f"Nagłówków: {len(heads)}")


def check_img_alt(ctx: dict) -> dict:
    imgs = ctx["page"].get("images") or []
    why = "Opis obrazka (alt) czyta Google Grafika i osoby niewidome — bez niego obrazek jest „niemy”."
    fix = "W WordPress: Media → kliknij obrazek → wypełnij „Tekst alternatywny” krótkim opisem."
    if not imgs:
        return _check("img_alt", "Treść", "ok", "Brak obrazków do opisania", why, fix, 6,
                      "Na stronie nie ma obrazków.")
    missing = sum(1 for i in imgs if not (i.get("alt") or "").strip())
    ratio = missing / len(imgs)
    detail = f"Bez opisu: {missing} z {len(imgs)} ({round(ratio * 100)}%)"
    if missing == 0:
        return _check("img_alt", "Treść", "ok", "Wszystkie obrazki mają opis (alt)", why, fix, 6, detail)
    if ratio > 0.5:
        return _check("img_alt", "Treść", "critical", "Większość obrazków nie ma opisu (alt)",
                      why, fix, 6, detail)
    return _check("img_alt", "Treść", "warning", "Część obrazków nie ma opisu (alt)", why, fix, 6, detail)


def check_title_h1(ctx: dict) -> dict | None:
    page = ctx["page"]
    title = (page.get("title") or "").strip().lower()
    h1 = [h.strip().lower() for h in page.get("h1") or []]
    if not title or not h1:
        return None
    why = "Tytuł i H1 to dwie osobne szanse, żeby powiedzieć Google, o czym jest strona."
    fix = "Możesz to zostawić, ale lepiej, gdy H1 mówi to samo innymi słowami niż tytuł."
    if title in h1:
        return _check("title_h1", "Treść", "info", "Tytuł i H1 są identyczne", why, fix, 0,
                      f"„{_short(page.get('title'))}”")
    return _check("title_h1", "Treść", "ok", "Tytuł i H1 się uzupełniają", why, fix, 0, "")


def check_keyword_focus(ctx: dict) -> dict | None:
    kws = ctx.get("keywords") or []
    if not kws:
        return None
    page = ctx["page"]
    top = kws[0]["phrase"]
    pres = keyword_presence(top, page.get("title"), page.get("h1"), page.get("meta_description"))
    why = "Gdy najważniejsze słowo z treści jest też w tytule i H1, Google szybciej łapie temat strony."
    fix = f"Wpleć frazę „{top}” w tytuł SEO i nagłówek H1 (jeśli to Twoja główna usługa)."
    where = [n for k, n in (("title", "tytuł"), ("h1", "H1"), ("meta", "opis")) if pres[k]]
    detail = f"Najczęstsza fraza: „{top}” ({kws[0]['count']}×). " + (
        f"Jest w: {', '.join(where)}." if where else "Nie ma jej w tytule, H1 ani opisie.")
    if pres["title"] or pres["h1"]:
        return _check("keyword_focus", "Treść", "ok", "Główna fraza jest w tytule lub H1", why, fix, 4, detail)
    return _check("keyword_focus", "Treść", "warning", "Główna fraza nie występuje w tytule ani H1",
                  why, fix, 4, detail)


# ==========================================================================
# TECHNICZNE
# ==========================================================================

def check_https(ctx: dict) -> dict:
    url = ctx.get("final_url") or ""
    why = "Bez HTTPS przeglądarka pokazuje „Niezabezpieczona”, a Google obniża pozycję."
    fix = ("Włącz darmowy certyfikat SSL (Let's Encrypt w panelu hostingu), potem WordPress: "
           "Ustawienia → Ogólne → adresy na https://.")
    if url.startswith("https://"):
        return _check("https", "Techniczne", "ok", "Strona działa na HTTPS (kłódka)", why, fix, 12, url)
    return _check("https", "Techniczne", "critical", "Strona nie ma HTTPS (brak kłódki)", why, fix, 12, url)


def check_http_redirect(ctx: dict) -> dict | None:
    hr = ctx.get("http_redirect")
    if hr is None or not (ctx.get("final_url") or "").startswith("https://"):
        return None
    why = "Ktoś, kto wpisze adres bez https, powinien automatycznie trafić na bezpieczną wersję."
    fix = "Ustaw przekierowanie 301 z http na https: w hostingu („Wymuś HTTPS”) lub wtyczką Really Simple SSL."
    if not hr.get("checked"):
        return _check("http_redirect", "Techniczne", "info", "Nie udało się sprawdzić wersji http://",
                      why, fix, 0, "Wersja http:// nie odpowiedziała.")
    if hr.get("to_https"):
        return _check("http_redirect", "Techniczne", "ok", "http:// przekierowuje na https://", why, fix, 6,
                      f"→ {_short(hr.get('final_url'), 80)}")
    return _check("http_redirect", "Techniczne", "warning", "Wersja http:// nie przekierowuje na https://",
                  why, fix, 6, f"Kończy się na: {_short(hr.get('final_url'), 80)}")


def check_redirects(ctx: dict) -> dict | None:
    resp = ctx.get("resp")
    if resp is None:
        return None
    chain = resp.get("redirects") or []
    n = len(chain)
    why = "Każde przekierowanie to dodatkowe czekanie — długi łańcuch spowalnia i gubi „moc” linków."
    fix = "Linkuj od razu do adresu docelowego i ustaw jedno przekierowanie 301 zamiast kilku po kolei."
    detail = " → ".join([_short(r["url"], 50) for r in chain] + [_short(ctx.get("final_url"), 50)]) if chain \
        else "Bez przekierowań."
    if n == 0:
        return _check("redirects", "Techniczne", "ok", "Brak przekierowań", why, fix, 4, detail)
    if n == 1:
        return _check("redirects", "Techniczne", "ok", "Jedno przekierowanie (w porządku)", why, fix, 4, detail)
    level = "critical" if n > 3 else "warning"
    return _check("redirects", "Techniczne", level, f"Za dużo przekierowań po kolei ({n})", why, fix, 4, detail)


def check_viewport(ctx: dict) -> dict:
    vp = ctx["page"].get("viewport") or ""
    why = "Bez tego znacznika strona na telefonie wygląda jak pomniejszona wersja komputerowa."
    fix = ("Dodaj w <head>: <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"> "
           "(nowoczesne motywy WordPress mają to domyślnie).")
    if not vp:
        return _check("viewport", "Techniczne", "critical", "Strona nie jest dopasowana do telefonów",
                      why, fix, 8, "Brak znacznika meta viewport.")
    if "width=device-width" not in vp.replace(" ", "").lower():
        return _check("viewport", "Techniczne", "warning", "Nietypowe ustawienie widoku na telefonie",
                      why, fix, 8, f"viewport: {vp}")
    return _check("viewport", "Techniczne", "ok", "Strona jest przygotowana na telefony", why, fix, 8,
                  f"viewport: {_short(vp)}")


def check_lang(ctx: dict) -> dict:
    lang = ctx["page"].get("lang")
    why = "Język strony pomaga Google pokazać ją ludziom szukającym po polsku."
    fix = "WordPress: Ustawienia → Ogólne → Język witryny = Polski (motyw doda <html lang=\"pl-PL\">)."
    if not lang:
        return _check("lang", "Techniczne", "warning", "Nie ustawiono języka strony", why, fix, 4,
                      "Brak atrybutu lang w <html>.")
    return _check("lang", "Techniczne", "ok", "Język strony jest ustawiony", why, fix, 4, f"lang=\"{lang}\"")


def check_mixed_content(ctx: dict) -> dict | None:
    if not (ctx.get("final_url") or "").startswith("https://"):
        return None
    mixed = ctx["page"].get("mixed_content") or []
    why = "Pliki ładowane przez http:// na stronie https psują kłódkę i mogą się w ogóle nie wczytać."
    fix = "Zmień adresy zasobów z http:// na https:// (wtyczka Better Search Replace lub Really Simple SSL)."
    if not mixed:
        return _check("mixed_content", "Techniczne", "ok", "Wszystkie zasoby ładują się bezpiecznie",
                      why, fix, 6, "Brak zasobów http://.")
    active = [m for m in mixed if m["kind"] == "active"]
    detail = f"Zasobów http://: {len(mixed)} (skrypty/style/ramki: {len(active)}), np. {_short(mixed[0]['url'], 70)}"
    level = "critical" if active else "warning"
    return _check("mixed_content", "Techniczne", level, "Niezabezpieczone pliki na stronie (mixed content)",
                  why, fix, 6, detail)


def check_links(ctx: dict) -> dict:
    links = ctx["page"].get("links") or []
    empty_href = [l for l in links if l["kind"] == "empty"]
    no_text = [l for l in links if l["empty_text"] and l["kind"] != "empty"]
    internal = sum(1 for l in links if l["kind"] == "internal")
    external = sum(1 for l in links if l["kind"] == "external")
    why = "Link bez adresu albo bez opisu to ślepa uliczka dla klienta i dla Google."
    fix = "Każdy link powinien prowadzić pod konkretny adres i mówić dokąd, np. „Zobacz cennik” (nie samo „#”)."
    detail = (f"Linki: {len(links)} (wewnętrzne {internal}, zewnętrzne {external}); "
              f"bez adresu: {len(empty_href)}, bez tekstu: {len(no_text)}")
    bad = len(empty_href) + len(no_text)
    if bad == 0:
        return _check("links", "Techniczne", "ok", "Linki mają adresy i opisy", why, fix, 4, detail)
    level = "critical" if links and bad / len(links) > 0.3 and bad >= 5 else "warning"
    return _check("links", "Techniczne", level, f"Puste lub nieopisane linki ({bad})", why, fix, 4, detail)


def check_favicon(ctx: dict) -> dict:
    page = ctx["page"]
    why = "Ikonka strony pojawia się w Google i na kartach przeglądarki — buduje zaufanie i rozpoznawalność."
    fix = "WordPress: Wygląd → Dostosuj → Tożsamość witryny → Ikona witryny (kwadrat 512×512 px)."
    if page.get("favicon"):
        return _check("favicon", "Techniczne", "ok", "Strona ma ikonkę (favicon)", why, fix, 2,
                      _short(page["favicon"], 80))
    if ctx.get("favicon_ico"):
        return _check("favicon", "Techniczne", "ok", "Strona ma ikonkę (favicon.ico)", why, fix, 2,
                      "Znaleziono /favicon.ico.")
    return _check("favicon", "Techniczne", "warning", "Brak ikonki strony (favicon)", why, fix, 2,
                  "Brak <link rel=\"icon\"> i /favicon.ico.")


# ==========================================================================
# SOCIAL
# ==========================================================================

def check_open_graph(ctx: dict) -> dict:
    og = ctx["page"].get("og") or {}
    need = {"og:title": "tytuł", "og:description": "opis", "og:image": "obrazek"}
    missing = [v for k, v in need.items() if not og.get(k)]
    why = "Open Graph decyduje, jak wygląda link udostępniony na Facebooku czy Messengerze."
    fix = "Yoast → zakładka Social przy stronie → dodaj tytuł, opis i obrazek 1200×630 px."
    if not missing:
        return _check("open_graph", "Social", "ok", "Podgląd do social mediów jest gotowy", why, fix, 5,
                      "Są og:title, og:description i og:image.")
    level = "warning"
    title = "Brak podglądu dla social mediów" if len(missing) == 3 else "Niepełny podgląd dla social mediów"
    return _check("open_graph", "Social", level, title, why, fix, 5, "Brakuje: " + ", ".join(missing))


def check_twitter(ctx: dict) -> dict:
    tw = ctx["page"].get("twitter") or {}
    why = "Karta X (Twittera) sprawia, że link pokazuje się z dużym obrazkiem zamiast gołego adresu."
    fix = "Yoast → Social → X: włącz karty (wystarczy twitter:card = summary_large_image)."
    if tw.get("twitter:card"):
        return _check("twitter", "Social", "ok", "Jest karta X/Twitter", why, fix, 1,
                      f"twitter:card = {tw['twitter:card']}")
    return _check("twitter", "Social", "warning", "Brak karty X/Twitter", why, fix, 1,
                  "Brak twitter:card.")


# ==========================================================================
# LOKALNE SEO
# ==========================================================================

def check_structured_data(ctx: dict) -> dict:
    jl = ctx["page"].get("jsonld") or {}
    types = jl.get("types") or []
    why = "Dane strukturalne to „wizytówka dla robota” — dzięki nim Google może pokazać gwiazdki, adres, FAQ."
    fix = "Yoast/Rank Math → Schema (np. LocalBusiness dla firmy lokalnej); gotowy szkic: python -m tars_seo audit ADRES --ai."
    if jl.get("errors") and not types:
        return _check("structured_data", "Lokalne SEO", "critical", "Dane strukturalne są uszkodzone",
                      why, "Popraw błąd składni w bloku JSON-LD (sprawdź w validator.schema.org).", 6,
                      f"Błędnych bloków JSON-LD: {jl['errors']}")
    if not types:
        return _check("structured_data", "Lokalne SEO", "warning", "Brak danych strukturalnych (schema)",
                      why, fix, 6, "Nie znaleziono JSON-LD.")
    detail = "Typy: " + ", ".join(types[:8])
    if jl.get("errors"):
        return _check("structured_data", "Lokalne SEO", "warning", "Część danych strukturalnych jest uszkodzona",
                      why, "Popraw błąd składni w bloku JSON-LD (validator.schema.org).", 6,
                      detail + f"; błędnych bloków: {jl['errors']}")
    return _check("structured_data", "Lokalne SEO", "ok", "Są dane strukturalne", why, fix, 6, detail)


def local_business_entities(page: dict) -> list[dict]:
    ents = (page.get("jsonld") or {}).get("entities") or []
    out = []
    for e in ents:
        t = e.get("@type")
        types = [t] if isinstance(t, str) else [x for x in (t or []) if isinstance(x, str)]
        if any(x.rsplit("/", 1)[-1] in LOCAL_TYPES for x in types):
            out.append(e)
    return out


def local_business_missing(entity: dict) -> list[str]:
    """Nazwy pól (po polsku) brakujących w encji LocalBusiness."""
    missing = []
    for key, label in LOCAL_REQUIRED.items():
        val = entity.get(key)
        if key == "openingHours" and not val:
            val = entity.get("openingHoursSpecification")
        if key == "address" and isinstance(val, dict):
            val = val.get("streetAddress") or val.get("addressLocality")
        if isinstance(val, str):
            val = val.strip()
        if not val:
            missing.append(label)
    return missing


def check_local_business(ctx: dict) -> dict:
    ents = local_business_entities(ctx["page"])
    why = "Dla firmy lokalnej schemat LocalBusiness (nazwa, adres, telefon, godziny) pomaga wejść do mapki Google."
    fix = ("Dodaj schemat LocalBusiness z nazwą, adresem, telefonem i godzinami otwarcia "
           "(Rank Math → Local SEO albo szkic z: python -m tars_seo audit ADRES --ai).")
    if not ents:
        return _check("local_business", "Lokalne SEO", "warning", "Brak wizytówki firmy (LocalBusiness)",
                      why, fix, 8, "Nie znaleziono schematu LocalBusiness ani jego odmian.")
    best = min(ents, key=lambda e: len(local_business_missing(e)))
    missing = local_business_missing(best)
    t = best.get("@type")
    tname = t if isinstance(t, str) else ", ".join(x for x in t if isinstance(x, str))
    if missing:
        return _check("local_business", "Lokalne SEO", "warning", "Wizytówka firmy jest niepełna", why,
                      "Uzupełnij w schemacie LocalBusiness: " + ", ".join(missing) + ".", 8,
                      f"Typ: {tname}; brakuje: {', '.join(missing)}")
    return _check("local_business", "Lokalne SEO", "ok", "Wizytówka firmy (LocalBusiness) jest kompletna",
                  why, fix, 8, f"Typ: {tname}; są nazwa, adres, telefon i godziny.")


def check_tel_link(ctx: dict) -> dict:
    tels = ctx["page"].get("tel_links") or []
    why = "Klikalny numer telefonu to jeden dotyk do rozmowy z klientem na komórce."
    fix = "Zaznacz numer w edytorze → Link → wpisz tel:+48123456789."
    if tels:
        return _check("tel_link", "Lokalne SEO", "ok", "Numer telefonu jest klikalny", why, fix, 3,
                      "tel: " + ", ".join(dict.fromkeys(tels[:3])))
    return _check("tel_link", "Lokalne SEO", "warning", "Brak klikalnego numeru telefonu", why, fix, 3,
                  "Nie znaleziono linku tel:.")


# ==========================================================================
# SZYBKOŚĆ
# ==========================================================================

def check_response_time(ctx: dict) -> dict:
    resp = ctx.get("resp") or {}
    ms = resp.get("elapsed_ms")
    ttfb = resp.get("ttfb_ms")
    why = "Co sekunda czekania część klientów rezygnuje, a Google woli szybkie strony."
    fix = "Włącz cache (np. LiteSpeed Cache lub WP Super Cache) i sprawdź hosting — celuj w mniej niż 0,8 s."
    if ms is None:
        return _check("response_time", "Szybkość", "info", "Czasu odpowiedzi nie zmierzono", why, fix, 0,
                      "Audyt z gotowego HTML-a.")
    detail = f"Pobranie: {ms / 1000:.2f} s" + (f", pierwszy bajt ok. {ttfb / 1000:.2f} s" if ttfb else "")
    if ms < 800:
        return _check("response_time", "Szybkość", "ok", "Serwer odpowiada szybko", why, fix, 8, detail)
    if ms < 2000:
        return _check("response_time", "Szybkość", "warning", "Serwer odpowiada wolno", why, fix, 8, detail)
    return _check("response_time", "Szybkość", "critical", "Serwer odpowiada bardzo wolno", why, fix, 8, detail)


def check_page_weight(ctx: dict) -> dict:
    resp = ctx.get("resp") or {}
    size = resp.get("size") or len((ctx.get("html") or "").encode("utf-8"))
    kb = size / 1024
    why = "Ciężki kod strony dłużej się ładuje, zwłaszcza na telefonie w słabym zasięgu."
    fix = "Odchudź stronę: usuń zbędne wtyczki i sekcje, włącz minifikację HTML we wtyczce cache."
    detail = f"Rozmiar HTML: {kb:.0f} KB" + (" (ucięto przy 3 MB)" if resp.get("truncated") else "")
    if kb < 500:
        return _check("page_weight", "Szybkość", "ok", "Kod strony jest lekki", why, fix, 6, detail)
    if kb < 1500:
        return _check("page_weight", "Szybkość", "warning", "Kod strony jest ciężki", why, fix, 6, detail)
    return _check("page_weight", "Szybkość", "critical", "Kod strony jest bardzo ciężki", why, fix, 6, detail)


def check_compression(ctx: dict) -> dict | None:
    resp = ctx.get("resp")
    if resp is None or not resp.get("status"):
        return None
    enc = (resp.get("headers") or {}).get("content-encoding", "").lower()
    why = "Kompresja zmniejsza stronę kilka razy, więc szybciej dociera do klienta."
    fix = "Włącz kompresję GZIP/Brotli w panelu hostingu albo we wtyczce cache."
    if any(x in enc for x in ("gzip", "br", "deflate", "zstd")):
        return _check("compression", "Szybkość", "ok", "Kompresja jest włączona", why, fix, 3, f"Kodowanie: {enc}")
    if (resp.get("size") or 0) < 2048:
        return _check("compression", "Szybkość", "info", "Strona jest tak mała, że kompresja nie ma znaczenia",
                      why, fix, 0, "")
    return _check("compression", "Szybkość", "warning", "Brak kompresji (GZIP)", why, fix, 3,
                  "Serwer wysłał stronę bez kompresji.")


def check_img_dimensions(ctx: dict) -> dict:
    imgs = ctx["page"].get("images") or []
    why = "Obrazki bez wymiarów sprawiają, że strona „skacze” podczas ładowania — to irytuje i obniża ocenę Google."
    fix = "Dodaj obrazkom atrybuty width i height (sprawdź zwłaszcza obrazki wstawione przez page builder)."
    if not imgs:
        return _check("img_dimensions", "Szybkość", "ok", "Brak obrazków do sprawdzenia", why, fix, 4, "")
    missing = sum(1 for i in imgs if not i.get("has_dimensions"))
    detail = f"Bez wymiarów: {missing} z {len(imgs)}"
    if missing == 0:
        return _check("img_dimensions", "Szybkość", "ok", "Obrazki mają wymiary", why, fix, 4, detail)
    return _check("img_dimensions", "Szybkość", "warning", "Obrazki bez wymiarów (strona „skacze”)",
                  why, fix, 4, detail)


def check_lazy_loading(ctx: dict) -> dict:
    imgs = ctx["page"].get("images") or []
    why = "Leniwe ładowanie wczytuje obrazki dopiero przy przewijaniu, więc góra strony pojawia się szybciej."
    fix = "Włącz loading=\"lazy\" dla obrazków (WordPress 5.5+ robi to sam; LiteSpeed Cache → Obrazy → Lazy Load)."
    if len(imgs) <= 3:
        return _check("lazy_loading", "Szybkość", "ok", "Mało obrazków — leniwe ładowanie niepotrzebne",
                      why, fix, 3, f"Obrazków: {len(imgs)}")
    lazy = sum(1 for i in imgs if i.get("lazy"))
    detail = f"Leniwie ładowane: {lazy} z {len(imgs)}"
    if lazy == 0:
        return _check("lazy_loading", "Szybkość", "warning", "Obrazki nie ładują się leniwie", why, fix, 3, detail)
    return _check("lazy_loading", "Szybkość", "ok", "Obrazki ładują się leniwie", why, fix, 3, detail)


def check_inline_code(ctx: dict) -> dict:
    page = ctx["page"]
    total = page.get("inline_script_bytes", 0) + page.get("inline_style_bytes", 0)
    why = "Dużo kodu wklejonego w HTML spowalnia pierwsze wyświetlenie strony."
    fix = "Przenieś duże fragmenty JS/CSS do osobnych plików albo włącz ich łączenie we wtyczce cache."
    detail = (f"Skrypty w HTML: {page.get('inline_script_bytes', 0) / 1024:.0f} KB, "
              f"style w HTML: {page.get('inline_style_bytes', 0) / 1024:.0f} KB")
    if total > 150 * 1024:
        return _check("inline_code", "Szybkość", "warning", "Dużo kodu wklejonego w HTML", why, fix, 2, detail)
    return _check("inline_code", "Szybkość", "ok", "Niewiele kodu wklejonego w HTML", why, fix, 2, detail)


ALL_CHECKS: list[Callable[[dict], dict | None]] = [
    check_status, check_title, check_meta_description, check_h1, check_indexable,
    check_robots_txt, check_sitemap, check_canonical,
    check_word_count, check_heading_order, check_img_alt, check_title_h1, check_keyword_focus,
    check_https, check_http_redirect, check_redirects, check_viewport, check_lang,
    check_mixed_content, check_links, check_favicon,
    check_open_graph, check_twitter,
    check_structured_data, check_local_business, check_tel_link,
    check_response_time, check_page_weight, check_compression, check_img_dimensions,
    check_lazy_loading, check_inline_code,
]


def run_checks(ctx: dict) -> list[dict]:
    """Uruchamia wszystkie sprawdzenia (pomijając te, których nie da się wykonać)."""
    results = []
    for fn in ALL_CHECKS:
        try:
            r = fn(ctx)
        except Exception as e:  # noqa: BLE001 — jedno sprawdzenie nie psuje audytu
            r = _check(fn.__name__.replace("check_", ""), "Techniczne", "info",
                       "Nie udało się wykonać sprawdzenia", "—", "—", 0, str(e))
        if r:
            results.append(r)
    return results
