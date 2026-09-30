"""Lista elementów pamięci z sortowaniem (naturalnym, z polskimi znakami), wyszukiwaniem i filtrem typów."""
from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from .filetypes import GROUP_LABELS, fold, group_of, resolve_group
from .sorter import LOG_NAME

SORT_MODES = ("recent", "oldest", "name", "name_desc", "size", "size_desc", "type", "folder")
SORT_LABELS = {
    "recent": "najnowsze", "oldest": "najstarsze", "name": "nazwa A→Ż", "name_desc": "nazwa Ż→A",
    "size": "najmniejsze", "size_desc": "największe", "type": "typ", "folder": "folder",
}
PL_ALPHABET = "aąbcćdeęfghijklłmnńoópqrsśtuvwxyzźż"
_RANK = {c: i for i, c in enumerate(PL_ALPHABET)}


@dataclass
class Item:
    """Plik w drzewie pamięci."""
    path: Path
    name: str
    folder: str  # względny, "/" — "" dla katalogu głównego
    size: int
    mtime: float
    ext: str
    group: str

    @property
    def group_label(self) -> str:
        return GROUP_LABELS[self.group]


def _collate_char(c: str) -> str:
    c = c.lower()
    if c in _RANK:
        return chr(0x100 + _RANK[c])
    base = unicodedata.normalize("NFKD", c)[:1]  # é → e, ü → u
    if base in _RANK:
        return chr(0x100 + _RANK[base])
    return c if ord(c) < 0x80 else chr(ord(c) + 0x1000)


def collate(text: str) -> str:
    """Klucz porządku alfabetu polskiego, bez wielkości liter (a < ą < b … < ż)."""
    return "".join(_collate_char(c) for c in text)


def natural_key(text: str) -> tuple:
    """Sortowanie naturalne: plik2 < plik10, z polską kolejnością liter."""
    parts = re.split(r"(\d+)", text)
    return tuple((0, int(p), "") if p.isdigit() else (1, 0, collate(p)) for p in parts if p)


def _scan(root: Path) -> list[Item]:
    items = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        rel = Path(dirpath).relative_to(root).as_posix()
        for fn in filenames:
            if fn.startswith(".") or fn == LOG_NAME:
                continue
            p = Path(dirpath) / fn
            try:
                st = p.stat()
            except OSError:
                continue
            items.append(Item(p, fn, "" if rel == "." else rel, st.st_size, st.st_mtime,
                              p.suffix.lower(), group_of(fn)))
    return items


def _matches(item: Item, terms: list[str]) -> bool:
    hay = fold(f"{item.folder}/{item.name}")
    return all(t in hay for t in terms)


def list_items(root, sort: str = "recent", query: str | None = None, types=None) -> list[Item]:
    """Pliki pamięci posortowane wg `sort`, przefiltrowane frazą `query` i grupami `types`."""
    if sort not in SORT_MODES:
        raise ValueError(f"Nieznany tryb sortowania: {sort!r}. Dostępne: {', '.join(SORT_MODES)}")
    root = Path(root)
    items = _scan(root) if root.is_dir() else []
    if query and query.strip():
        terms = fold(query).split()
        items = [i for i in items if _matches(i, terms)]
    if types:
        wanted = {resolve_group(t) for t in ([types] if isinstance(types, str) else types)} - {None}
        items = [i for i in items if i.group in wanted]
    by_name = lambda i: (natural_key(i.name), natural_key(i.folder))  # noqa: E731
    keys = {
        "recent": (lambda i: (-i.mtime, by_name(i)), False),
        "oldest": (lambda i: (i.mtime, by_name(i)), False),
        "name": (by_name, False),
        "name_desc": (by_name, True),
        "size": (lambda i: (i.size, by_name(i)), False),
        "size_desc": (lambda i: (-i.size, by_name(i)), False),
        "type": (lambda i: (collate(i.group_label), i.ext, by_name(i)), False),
        "folder": (lambda i: (natural_key(i.folder), natural_key(i.name)), False),
    }
    key, rev = keys[sort]
    return sorted(items, key=key, reverse=rev)
