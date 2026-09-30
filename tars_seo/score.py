"""Wynik 0–100, ocena A–F, wyniki kategorii i „Top 3 rzeczy do poprawy”."""
from __future__ import annotations

from .checks import CATEGORIES

LEVEL_FACTOR = {"ok": 1.0, "warning": 0.5, "critical": 0.0}
LEVEL_RANK = {"critical": 0, "warning": 1, "info": 2, "ok": 3}
LEVEL_LABEL = {"critical": "KRYTYCZNE", "warning": "DO POPRAWY", "info": "INFO", "ok": "OK"}

# (minimalny wynik, ocena, opis) — od najlepszej
GRADES = [
    (90, "A", "Świetnie"),
    (80, "B", "Dobrze"),
    (70, "C", "Nieźle"),
    (55, "D", "Słabo"),
    (40, "E", "Źle"),
    (0, "F", "Bardzo źle"),
]

SORT_MODES = ("impact", "category", "level")

# Problemy, przy których strona jest praktycznie niewidoczna w Google — wtedy
# wynik nie może być wyższy niż BLOCKER_CAP (nawet jeśli reszta jest świetna).
BLOCKERS = ("status", "indexable", "robots_txt")
BLOCKER_CAP = 39


def weighted_score(checks: list[dict]) -> int | None:
    """Średnia ważona: ok = 100%, warning = 50%, critical = 0%; info się nie liczy."""
    total = earned = 0.0
    for c in checks:
        if c.get("level") not in LEVEL_FACTOR or c.get("weight", 0) <= 0:
            continue
        total += c["weight"]
        earned += c["weight"] * LEVEL_FACTOR[c["level"]]
    if total <= 0:
        return None
    return int(round(100 * earned / total))


def grade(score: int | None) -> tuple[str, str]:
    """Wynik → (litera, opis po polsku)."""
    if score is None:
        return "?", "Brak danych"
    for minimum, letter, label in GRADES:
        if score >= minimum:
            return letter, label
    return "F", "Bardzo źle"


def category_scores(checks: list[dict]) -> dict:
    """``{kategoria: wynik 0–100 | None}`` w stałej kolejności kategorii."""
    return {cat: weighted_score([c for c in checks if c.get("category") == cat])
            for cat in CATEGORIES}


def impact_key(check: dict) -> tuple:
    """Klucz sortowania „wg wpływu”: krytyczne → ostrzeżenia → info → ok, potem waga."""
    return (LEVEL_RANK.get(check.get("level"), 9), -int(check.get("weight", 0)), check.get("id", ""))


def sort_checks(checks: list[dict], by: str = "impact") -> list[dict]:
    """Sortuje listę sprawdzeń: ``impact`` (domyślnie), ``category`` lub ``level``."""
    if by not in SORT_MODES:
        raise ValueError(f"Nieznany sposób sortowania: {by} (dostępne: {', '.join(SORT_MODES)})")
    if by == "impact":
        return sorted(checks, key=impact_key)
    if by == "category":
        order = {c: i for i, c in enumerate(CATEGORIES)}
        return sorted(checks, key=lambda c: (order.get(c.get("category"), 99),) + impact_key(c))
    return sorted(checks, key=lambda c: (LEVEL_RANK.get(c.get("level"), 9), c.get("category", ""),
                                         c.get("title", "")))


def top_fixes(checks: list[dict], n: int = 3) -> list[dict]:
    """Najważniejsze rzeczy do poprawy (tylko critical/warning), wg wpływu."""
    bad = [c for c in checks if c.get("level") in ("critical", "warning")]
    return sort_checks(bad, "impact")[:n]


def blockers(checks: list[dict]) -> list[dict]:
    """Krytyczne problemy, które ukrywają stronę przed Google."""
    return [c for c in checks if c.get("id") in BLOCKERS and c.get("level") == "critical"]


def summarize(checks: list[dict]) -> dict:
    score = weighted_score(checks)
    blocked = blockers(checks)
    if blocked and score is not None:
        score = min(score, BLOCKER_CAP)
    letter, label = grade(score)
    counts = {lvl: sum(1 for c in checks if c.get("level") == lvl) for lvl in LEVEL_RANK}
    return {"score": score if score is not None else 0, "grade": letter, "grade_label": label,
            "categories": category_scores(checks), "top3": top_fixes(checks, 3), "counts": counts,
            "blocked": bool(blocked)}
