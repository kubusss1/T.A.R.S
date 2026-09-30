"""Grupy typów plików, polskie etykiety i porównywanie nazw bez polskich znaków."""
from __future__ import annotations

import re
import unicodedata

GROUP_EXTENSIONS: dict[str, set[str]] = {
    "document": {".pdf", ".doc", ".docx", ".odt", ".rtf", ".txt", ".md", ".markdown", ".epub", ".pages"},
    "image": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tif", ".tiff", ".heic", ".svg", ".ico", ".raw"},
    "video": {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm", ".flv", ".m4v", ".mpg", ".mpeg"},
    "audio": {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".wma", ".opus"},
    "code": {".py", ".js", ".ts", ".html", ".htm", ".css", ".json", ".xml", ".yaml", ".yml", ".sh", ".bat",
             ".ps1", ".c", ".cpp", ".h", ".java", ".cs", ".go", ".rs", ".php", ".rb", ".sql", ".ipynb", ".toml", ".ini"},
    "spreadsheet": {".xls", ".xlsx", ".ods", ".csv", ".tsv", ".numbers"},
    "presentation": {".ppt", ".pptx", ".odp", ".key"},
    "archive": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".iso"},
}
EXT_TO_GROUP = {ext: g for g, exts in GROUP_EXTENSIONS.items() for ext in exts}

GROUP_LABELS = {
    "document": "Dokumenty", "image": "Obrazy", "video": "Wideo", "audio": "Audio", "code": "Kod",
    "spreadsheet": "Arkusze", "presentation": "Prezentacje", "archive": "Archiwa", "other": "Inne",
}
# Nazwy folderów uznawane za „ten sam” folder kategorii (klucze znormalizowane).
GROUP_ALIASES = {
    "document": {"dokumenty", "documents", "docs", "pisma"},
    "image": {"obrazy", "zdjecia", "grafiki", "obrazki", "images", "photos", "pictures", "foto"},
    "video": {"wideo", "filmy", "video", "videos", "nagrania"},
    "audio": {"audio", "muzyka", "dzwieki", "music", "nagraniaaudio"},
    "code": {"kod", "code", "skrypty", "programy", "src"},
    "spreadsheet": {"arkusze", "tabele", "spreadsheets", "excel"},
    "presentation": {"prezentacje", "slajdy", "presentations"},
    "archive": {"archiwa", "archiwum", "archives", "spakowane"},
    "other": {"inne", "rozne", "other", "misc"},
}


def group_of(ext_or_name: str) -> str:
    """Zwraca grupę typu (np. "image") dla rozszerzenia lub nazwy pliku."""
    s = ext_or_name.lower()
    ext = s if s.startswith(".") and s.count(".") == 1 else ("." + s.rsplit(".", 1)[-1] if "." in s else "")
    return EXT_TO_GROUP.get(ext, "other")


def resolve_group(name: str) -> str | None:
    """Zamienia klucz grupy lub polską etykietę („Obrazy”, „zdjęcia”) na klucz grupy."""
    k = norm_key(name)
    for g in GROUP_LABELS:
        if k == g or k == norm_key(GROUP_LABELS[g]) or k in GROUP_ALIASES[g]:
            return g
    return None


def fold(text: str) -> str:
    """Małe litery bez znaków diakrytycznych (ł→l)."""
    text = text.replace("ł", "l").replace("Ł", "L")
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c)).casefold()


def norm_key(text: str) -> str:
    """Klucz porównania nazw: bez diakrytyków, wielkości liter i znaków innych niż litery/cyfry."""
    return re.sub(r"[^0-9a-z]+", "", fold(text))


def human_size(n: int) -> str:
    """Rozmiar czytelny dla człowieka (B, KB, MB, GB)."""
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}".replace(".", ",")
        size /= 1024
    return f"{n} B"
