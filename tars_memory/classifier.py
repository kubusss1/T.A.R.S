"""Decyzja, do którego folderu pamięci trafia plik: AI z walidacją, a w razie problemów reguły."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable

from .extract import extract_text
from .filetypes import GROUP_ALIASES, GROUP_LABELS, fold, group_of, human_size, norm_key

MAX_DEPTH = 3
MAX_NAME = 64
FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
RESERVED = {"con", "prn", "aux", "nul", "conin$", "conout$",
            *(f"{d}{i}" for d in ("com", "lpt") for i in (*range(10), "¹", "²", "³"))}

# (rdzenie słów po normalizacji, folder docelowy)
KEYWORD_RULES: list[tuple[tuple[str, ...], str]] = [
    (("faktur", "invoice", "fv"), "Finanse/Faktury"),
    (("rachun",), "Finanse/Rachunki"),
    (("paragon", "receipt"), "Finanse/Paragony"),
    (("wyciag", "przelew", "bank"), "Finanse/Bank"),
    (("pit", "podat", "zus"), "Finanse/Podatki"),
    (("umow", "aneks", "contract"), "Dokumenty/Umowy"),
    (("cv", "zyciorys", "resume"), "Dokumenty/CV"),
    (("certyfikat", "dyplom", "swiadectw"), "Dokumenty/Certyfikaty"),
    (("skan", "scan"), "Dokumenty/Skany"),
    (("notatk", "notes", "note"), "Notatki"),
    (("przepis", "recipe"), "Przepisy"),
    (("bilet", "rezerwacj", "ticket", "booking"), "Podróże"),
    (("screenshot", "zrzut"), "Obrazy/Zrzuty ekranu"),
]
SHORT_STEMS = {"fv", "cv", "pit", "zus"}  # krótkie rdzenie muszą pasować do całego słowa

PROMPT = """Jesteś asystentem porządkującym pamięć (drzewo folderów) użytkownika.
Wybierz folder dla nowego pliku. Preferuj istniejący folder; nowy utwórz tylko gdy żaden nie pasuje.
Folder podaj jako ścieżkę względną (separator "/", maks. {depth} poziomy, bez "..").

Istniejące foldery:
{folders}

Plik: {name}
Rozszerzenie: {ext}
Rozmiar: {size}
Fragment treści:
{snippet}

Odpowiedz WYŁĄCZNIE obiektem JSON:
{{"folder": "Ścieżka/Folderu", "new_folder": false, "filename": "nazwa{ext}", "reason": "krótkie uzasadnienie po polsku", "confidence": 0.0-1.0}}"""


@dataclass
class Decision:
    """Wynik klasyfikacji pliku."""
    folder: str
    new_folder: bool
    filename: str
    reason: str
    confidence: float
    source: str  # "ai" | "rules"

    def to_dict(self) -> dict:
        return asdict(self)


def sanitize_name(name: str) -> str:
    """Nazwa pliku/folderu bezpieczna na Windows (bez znaków zakazanych i nazw zarezerwowanych)."""
    name = FORBIDDEN.sub("", str(name)).strip().rstrip(". ").strip()
    name = re.sub(r"\s+", " ", name)[:MAX_NAME].rstrip(". ")
    if name.split(".")[0].rstrip(" ").lower() in RESERVED:  # Windows: „CON .txt” to też urządzenie
        name = "_" + name
    return name


def safe_folder(raw) -> str | None:
    """Waliduje względną ścieżkę folderu; zwraca "A/B" albo None, gdy niebezpieczna/pusta."""
    if not isinstance(raw, str):
        return None
    raw = raw.strip()
    if not raw or raw[0] in "/\\" or re.match(r"^[A-Za-z]:", raw) or "\x00" in raw:
        return None
    parts = [p.strip() for p in re.split(r"[\\/]+", raw) if p.strip() not in ("", ".")]
    if not parts or len(parts) > MAX_DEPTH or any(p == ".." or p.startswith("..") for p in parts):
        return None
    clean = [sanitize_name(p) for p in parts]
    if any(not c or c.startswith(".") for c in clean):
        return None
    return "/".join(clean)


def safe_filename(raw, original: str) -> str:
    """Nazwa pliku od AI z wymuszonym oryginalnym rozszerzeniem; w razie problemu oryginał."""
    orig = Path(original)
    fallback = sanitize_name(orig.name) or "plik" + orig.suffix
    if not isinstance(raw, str) or not raw.strip():
        return fallback
    stem = sanitize_name(Path(raw.replace("\\", "/").split("/")[-1]).stem)
    if not stem or stem.startswith("."):
        return fallback
    return stem + orig.suffix


def _norm_folders(existing) -> list[str]:
    out = []
    for f in existing or []:
        f = str(f).replace("\\", "/").strip("/")
        if f and f not in out:
            out.append(f)
    return out


def _path_key(folder: str) -> str:
    return "/".join(norm_key(p) for p in folder.split("/"))


def match_existing(target: str, existing: list[str], aliases: set[str] | None = None,
                   leaf: bool = True) -> str | None:
    """Szuka istniejącego folderu o tej samej nazwie (bez wielkości liter i diakrytyków).

    Kolejność: pełna ścieżka → ostatni człon, najpłycej (gdy `leaf`) → aliasy kategorii.
    """
    full = _path_key(target)
    for f in existing:
        if _path_key(f) == full:
            return f
    if not leaf:
        return None
    leaf_key = norm_key(target.split("/")[-1])
    by_depth = sorted(existing, key=lambda f: (f.count("/"), len(f)))
    for f in by_depth:
        if norm_key(f.split("/")[-1]) == leaf_key:
            return f
    if aliases:
        for f in by_depth:
            if norm_key(f.split("/")[-1]) in aliases:
                return f
    return None


def _tokens(text: str) -> list[str]:
    return [t for t in re.split(r"[^0-9a-z]+", fold(text)) if t]


def _keyword_folder(text: str) -> tuple[str, str] | None:
    toks = _tokens(text)
    for stems, folder in KEYWORD_RULES:
        for s in stems:
            if any(t == s if s in SHORT_STEMS else t.startswith(s) for t in toks):
                return folder, s
    return None


def classify_rules(path, existing_folders, text: str | None = None) -> Decision:
    """Klasyfikacja regułowa: słowa kluczowe w nazwie/treści, potem rozszerzenie."""
    p = Path(path)
    existing = _norm_folders(existing_folders)
    filename = safe_filename(p.name, p.name)
    group = group_of(p.name)
    hit = _keyword_folder(p.stem) or (_keyword_folder(text[:1500]) if text else None)
    if hit:
        target, stem = hit
        found = match_existing(target, existing)
        folder = found or target
        return Decision(folder, found is None, filename,
                        f"Reguła: słowo kluczowe „{stem}” → {folder}", 0.6, "rules")
    target = GROUP_LABELS[group]
    found = match_existing(target, existing, GROUP_ALIASES[group])
    folder = found or target
    conf = 0.2 if group == "other" else 0.5
    ext = p.suffix.lower() or "brak rozszerzenia"
    return Decision(folder, found is None, filename,
                    f"Reguła: typ pliku ({ext}) → {folder}", conf, "rules")


def build_prompt(path, existing_folders, text: str) -> str:
    """Zwięzły polski prompt dla modelu."""
    p = Path(path)
    existing = _norm_folders(existing_folders)
    try:
        size = human_size(p.stat().st_size)
    except OSError:
        size = "nieznany"
    folders = "\n".join(f"- {f}" for f in existing[:200]) or "(brak — drzewo jest puste)"
    snippet = text[:1500] if text else "(brak tekstu — oceń po nazwie i rozszerzeniu)"
    return PROMPT.format(depth=MAX_DEPTH, folders=folders, name=p.name, ext=p.suffix.lower() or "(brak)",
                         size=size, snippet=snippet)


def parse_json(reply) -> dict | None:
    """Wyciąga obiekt JSON z odpowiedzi modelu (także z bloku ```json)."""
    if not isinstance(reply, str):
        return None
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", reply.strip())
    for cand in (s, s[s.find("{"): s.rfind("}") + 1] if "{" in s else ""):
        try:
            data = json.loads(cand)
        except (ValueError, TypeError):
            continue
        if isinstance(data, dict):
            return data
    return None


def _default_ai(prompt: str) -> str:
    from tars_ai import chat  # leniwy import
    return chat(prompt, task="classify", json_mode=True)


def min_confidence() -> float:
    try:
        return float(os.environ.get("TARS_MEMORY_MIN_CONFIDENCE", "0.4"))
    except ValueError:
        return 0.4


def classify(path, existing_folders: list[str], ai_fn: Callable[[str], str] | None = None) -> Decision:
    """Klasyfikuje plik: najpierw AI (walidacja), przy błędzie/niskiej pewności — reguły."""
    p = Path(path)
    existing = _norm_folders(existing_folders)
    text = extract_text(p)
    fn = ai_fn or _default_ai
    why = ""
    try:
        data = parse_json(fn(build_prompt(p, existing, text)))
    except Exception as exc:  # noqa: BLE001 - AI może zawieść na wiele sposobów
        data, why = None, f"AI niedostępne ({type(exc).__name__})"
    if data is not None:
        folder = safe_folder(data.get("folder"))
        try:
            conf = max(0.0, min(1.0, float(data.get("confidence", 0.5))))
        except (TypeError, ValueError):
            conf = 0.0
        if folder is None:
            why = "AI podało niebezpieczny folder"
        elif conf < min_confidence():
            why = f"AI niepewne ({conf:.2f})"
        else:
            found = match_existing(folder, existing, leaf="/" not in folder)
            reason = str(data.get("reason") or "Decyzja AI").strip()[:300]
            return Decision(found or folder, found is None, safe_filename(data.get("filename"), p.name),
                            reason, conf, "ai")
    elif not why:
        why = "AI zwróciło niepoprawny JSON"
    d = classify_rules(p, existing, text)
    d.reason = f"{why}; {d.reason}"
    return d
