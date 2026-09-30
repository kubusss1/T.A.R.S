"""Opcjonalne podpowiedzi AI (lokalna Ollama przez ``tars_ai``).

* 3 lepsze tytuły (30–60 znaków) i 3 opisy meta (70–160 znaków) po polsku,
* szkic JSON-LD LocalBusiness wypełniony tym, co znaleźliśmy na stronie.

AI jest opcjonalne: gdy Ollama nie działa, dostajesz czytelny komunikat po
polsku, a szkic LocalBusiness i tak powstaje (nie wymaga AI).
"""
from __future__ import annotations

import json
import re
from typing import Callable

TITLE_RANGE = (30, 60)
DESC_RANGE = (70, 160)
PLACEHOLDER = "UZUPEŁNIJ"
FALLBACK_MESSAGE = ("Podpowiedzi AI są niedostępne — lokalne AI (Ollama) nie odpowiada. "
                    "Uruchom Ollamę (`ollama serve`) i spróbuj ponownie z opcją --ai.")

AiFn = Callable[..., str]


def _default_ai_fn() -> AiFn:
    from tars_ai import chat  # leniwy import — moduł działa też bez AI
    return chat


def _clean_text(value) -> str:
    if isinstance(value, dict):
        value = value.get("text") or value.get("tekst") or ""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = text.strip("\"'„”“«»`").strip()
    return re.sub(r"^\d+[.)]\s*", "", text)


def validate_variants(items, min_len: int, max_len: int, limit: int = 3) -> tuple[list[dict], int]:
    """Zostawia tylko propozycje o poprawnej długości (bez dubli, bez HTML-a).

    Zwraca (lista ``{"text", "length"}``, liczba odrzuconych).
    """
    out: list[dict] = []
    seen = set()
    rejected = 0
    for raw in items or []:
        text = _clean_text(raw)
        key = text.lower()
        if not text or key in seen:
            continue
        if not (min_len <= len(text) <= max_len) or "<" in text or ">" in text:
            rejected += 1
            continue
        seen.add(key)
        out.append({"text": text, "length": len(text)})
        if len(out) >= limit:
            break
    return out, rejected


def _parse_reply(reply: str) -> dict:
    reply = re.sub(r"<think>.*?</think>", "", reply or "", flags=re.S | re.I).strip()
    for candidate in (reply, *re.findall(r"\{.*\}", reply, flags=re.S)):
        try:
            data = json.loads(candidate)
        except (ValueError, TypeError):
            continue
        if isinstance(data, dict):
            return data
    return {}


def _pick(data: dict, *keys) -> list:
    for k in keys:
        v = data.get(k)
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            return [v]
    return []


def build_prompt(result: dict, feedback: str = "") -> str:
    page = result.get("page") or {}
    kws = ", ".join(k["phrase"] for k in (result.get("keywords") or [])[:6]) or "brak"
    lines = [
        "Jesteś specjalistą SEO polskiej agencji stron internetowych.",
        "Na podstawie danych strony zaproponuj po polsku:",
        f"- 3 tytuły SEO, każdy {TITLE_RANGE[0]}–{TITLE_RANGE[1]} znaków (usługa + miasto/wyróżnik + marka),",
        f"- 3 opisy meta, każdy {DESC_RANGE[0]}–{DESC_RANGE[1]} znaków, z zachętą do działania.",
        "Odpowiedz WYŁĄCZNIE JSON-em: {\"titles\": [\"...\"], \"descriptions\": [\"...\"]}",
        "",
        f"Adres: {result.get('final_url') or result.get('url')}",
        f"Obecny tytuł: {page.get('title') or 'brak'}",
        f"Obecny opis: {page.get('meta_description') or 'brak'}",
        f"H1: {'; '.join(page.get('h1') or []) or 'brak'}",
        f"H2: {'; '.join((page.get('h2') or [])[:6]) or 'brak'}",
        f"Najczęstsze frazy: {kws}",
        f"Fragment treści: {(page.get('excerpt') or '')[:600]}",
    ]
    if feedback:
        lines += ["", feedback]
    return "\n".join(lines)


def local_business_draft(result: dict) -> dict:
    """Szkic JSON-LD LocalBusiness z tego, co jest na stronie (brakujące → UZUPEŁNIJ)."""
    page = result.get("page") or {}
    og = page.get("og") or {}
    existing = page.get("local_business") or {}
    title = page.get("title") or ""
    name = existing.get("name") or og.get("og:site_name") or \
        (re.split(r"\s[|–—-]\s", title)[-1].strip() if title else "") or PLACEHOLDER
    tels = page.get("tel_links") or []
    phone = existing.get("telephone") or (tels[0].strip() if tels else PLACEHOLDER)
    address = existing.get("address")
    if not address:
        address = {"@type": "PostalAddress", "streetAddress": PLACEHOLDER,
                   "postalCode": PLACEHOLDER, "addressLocality": PLACEHOLDER,
                   "addressCountry": "PL"}
    hours = existing.get("openingHoursSpecification") or existing.get("openingHours")
    draft = {
        "@context": "https://schema.org",
        "@type": existing.get("@type") or "LocalBusiness",
        "name": name,
        "url": result.get("final_url") or result.get("url"),
        "telephone": phone,
        "address": address,
    }
    if isinstance(hours, str) or (isinstance(hours, list) and hours and isinstance(hours[0], str)):
        draft["openingHours"] = hours
    else:
        draft["openingHoursSpecification"] = hours or [{
            "@type": "OpeningHoursSpecification",
            "dayOfWeek": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
            "opens": "09:00", "closes": "17:00"}]
    desc = existing.get("description") or page.get("meta_description")
    if desc:
        draft["description"] = desc
    image = existing.get("image") or og.get("og:image")
    if image:
        draft["image"] = image
    for key in ("geo", "priceRange", "sameAs", "email"):
        if existing.get(key):
            draft[key] = existing[key]
    return draft


def suggest(result: dict, ai_fn: AiFn | None = None, retries: int = 1) -> dict:
    """Podpowiedzi tytułów/opisów (AI) + szkic LocalBusiness (bez AI).

    Zwraca ``{"ok", "titles", "descriptions", "local_business", "message", "rejected"}``.
    ``ai_fn(prompt, task=..., json_mode=...)`` — domyślnie ``tars_ai.chat``.
    """
    draft = local_business_draft(result)
    out = {"ok": False, "titles": [], "descriptions": [], "local_business": draft,
           "local_business_json": json.dumps(draft, ensure_ascii=False, indent=2),
           "message": "", "rejected": 0}
    try:
        fn = ai_fn or _default_ai_fn()
    except Exception:  # noqa: BLE001 — brak modułu tars_ai
        out["message"] = FALLBACK_MESSAGE
        return out
    titles: list = []
    descs: list = []
    feedback = ""
    for _ in range(max(0, retries) + 1):
        try:
            reply = fn(build_prompt(result, feedback), task="seo", json_mode=True)
        except Exception:  # noqa: BLE001 — OllamaError, timeout, cokolwiek
            if not titles and not descs:
                out["message"] = FALLBACK_MESSAGE
                return out
            break
        data = _parse_reply(reply)
        titles += _pick(data, "titles", "tytuly", "tytuły", "title")
        descs += _pick(data, "descriptions", "opisy", "description", "meta")
        vt, rt = validate_variants(titles, *TITLE_RANGE)
        vd, rd = validate_variants(descs, *DESC_RANGE)
        if len(vt) >= 3 and len(vd) >= 3:
            break
        feedback = (f"Poprzednia odpowiedź miała propozycje o złej długości. Pilnuj limitów: "
                    f"tytuł {TITLE_RANGE[0]}–{TITLE_RANGE[1]} znaków, opis "
                    f"{DESC_RANGE[0]}–{DESC_RANGE[1]} znaków. Policz znaki.")
    vt, rt = validate_variants(titles, *TITLE_RANGE)
    vd, rd = validate_variants(descs, *DESC_RANGE)
    out.update({"titles": vt, "descriptions": vd, "rejected": rt + rd})
    if vt or vd:
        out["ok"] = True
        out["message"] = "Propozycje AI (sprawdź przed wklejeniem)."
    else:
        out["message"] = ("AI nie podało propozycji o poprawnej długości "
                          f"(tytuł {TITLE_RANGE[0]}–{TITLE_RANGE[1]}, opis "
                          f"{DESC_RANGE[0]}–{DESC_RANGE[1]} znaków). Spróbuj ponownie.")
    return out
