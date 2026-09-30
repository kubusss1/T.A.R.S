"""Najczęstsze słowa i frazy (1–3 wyrazy) z widocznego tekstu strony.

Liczenie jest odporne na polskie znaki: „usługi”, „USŁUGI” i „uslugi” to to
samo słowo. Pomijamy popularne polskie (i kilka angielskich) słów-wypełniaczy.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter

_TOKEN_RE = re.compile(r"[^\W\d_]+", re.UNICODE)

_STOP_RAW = """
a aby ach acz aczkolwiek aj albo ale alez ani az bardziej bardzo beda bedzie bez
bo bowiem by byc byl byla byli bylo byly bym bys ci cie ciebie co cos czy czyli
czesto daleko dla dlaczego dlatego do dobrze dokad dosc duzo dwa dwaj dwie dwoje
dzis dzisiaj gdy gdyby gdyz gdzie gdziekolwiek go i ich ile im inna inne inny
innych iz ja jak jakas jakie jakis jakiz jakkolwiek jako jakos je jeden jedna
jedno jednak jednakze jego jej jemu jesli jest jestem jeszcze jezeli juz kazdy
kiedy kilka kims kto ktokolwiek ktora ktore ktorego ktorej ktory ktorych ktorym
ktorzy ku lat lecz lub ma maja mam mamy mi miedzy mimo mna mnie moga moi moim moj
moja moje moze mozliwe mozna mu musi my na nad nam nami nas nasi nasz nasza nasze
naszego naszej naszych natomiast nawet nia nic nich nie niech niego niej niemu
nigdy nim nimi niz no o obok od okolo on ona one oni ono oraz oto pan pana pani
po pod podczas pomimo ponad poniewaz powinien powinna powinni powinno poza prawie
przeciez przed przede przez przy roku rowniez sa sam sama sie skad sobie soba
sposob swoje ta tak taka taki takie takze tam te tego tej temu ten teraz tez to
toba tobie totez trzeba tu tutaj twoi twoj twoja twoje ty tych tylko tym u w wam
wami was wasz wasza wasze we wedlug wiec wiecej wiele wielu wlasnie wszyscy
wszystkich wszystkie wszystkim wszystko wtedy wy z za zaden zadna zadne zadnych
zapewne zawsze ze zeby zl znow znowu zostal czym tez sa oraz jako kazda kazde
the and for with you your our are this that from was were will can not all but
have has more about www http https com pl
"""


def fold(text: str) -> str:
    """Małe litery bez polskich znaków: „Łódź” → „lodz”."""
    text = (text or "").lower().replace("ł", "l")
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c))


STOPWORDS = frozenset(_STOP_RAW.split())


def tokenize(text: str) -> list[tuple[str, str]]:
    """Lista par (forma_złożona, oryginał_małymi)."""
    return [(fold(t), t.lower()) for t in _TOKEN_RE.findall(text or "")]


def _usable(folded: str) -> bool:
    return len(folded) >= 3 and folded not in STOPWORDS


def extract_keywords(text: str, top: int = 10, min_count: int = 2) -> list[dict]:
    """Najczęstsze słowa/frazy: ``[{"phrase", "count", "n"}]`` od najczęstszych.

    Frazy 2–3 wyrazowe nie mogą zaczynać się ani kończyć słowem-wypełniaczem.
    Fraza, która w całości zawiera się w częstszej/równie częstej dłuższej
    frazie, nie jest dublowana w wynikach.
    """
    tokens = tokenize(text)
    counts: Counter = Counter()
    display: dict[str, Counter] = {}
    for n in (1, 2, 3):
        for i in range(len(tokens) - n + 1):
            gram = tokens[i:i + n]
            if not (_usable(gram[0][0]) and _usable(gram[-1][0])):
                continue
            if n == 3 and not (len(gram[1][0]) >= 2):
                continue
            key = " ".join(g[0] for g in gram)
            counts[key] += 1
            display.setdefault(key, Counter())[" ".join(g[1] for g in gram)] += 1

    def score(item):
        key, c = item
        n = key.count(" ") + 1
        return (c * (1 + 0.5 * (n - 1)), n, key)

    ranked = [kv for kv in counts.items() if kv[1] >= min_count]
    ranked.sort(key=score, reverse=True)
    out: list[dict] = []
    chosen: list[tuple[str, int]] = []
    for key, c in ranked:
        # pomiń krótszą frazę, jeśli wybrana dłuższa już ją pokrywa tą samą liczbą
        if any(f" {key} " in f" {k} " and ck >= c for k, ck in chosen):
            continue
        chosen.append((key, c))
        out.append({"phrase": display[key].most_common(1)[0][0], "key": key,
                    "count": c, "n": key.count(" ") + 1})
        if len(out) >= top:
            break
    return out


def _stem(word: str) -> str:
    return word[:-2] if len(word) >= 6 else word


def contains_phrase(haystack: str, phrase: str) -> bool:
    """Czy fraza występuje w tekście (bez polskich znaków, z prostą odmianą)."""
    words = [fold(w) for w in _TOKEN_RE.findall(haystack or "")]
    target = [_stem(fold(w)) for w in _TOKEN_RE.findall(phrase or "")]
    if not target:
        return False
    n = len(target)
    for i in range(len(words) - n + 1):
        if all(words[i + j].startswith(target[j]) for j in range(n)):
            return True
    return False


def keyword_presence(keyword: str, title: str | None, h1: list[str] | None,
                     meta: str | None) -> dict:
    """Gdzie pojawia się słowo kluczowe: ``{"title", "h1", "meta"}`` → bool."""
    return {"title": contains_phrase(title or "", keyword),
            "h1": any(contains_phrase(h, keyword) for h in (h1 or [])),
            "meta": contains_phrase(meta or "", keyword)}
