"""Rozkładanie plików ze skrzynki (inbox) do drzewa pamięci + dziennik JSONL i cofanie."""
from __future__ import annotations

import json
import os
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from .classifier import Decision, classify

LOG_NAME = ".tars_memory_log.jsonl"
SKIP_NAMES = {"desktop.ini", "thumbs.db", ".ds_store", LOG_NAME}
SKIP_SUFFIXES = (".part", ".crdownload", ".partial", ".tmp", ".download", ".!ut", "~")


@dataclass
class Result:
    """Wynik obsługi jednego pliku ze skrzynki."""
    original: Path
    destination: Path | None
    decision: Decision | None
    moved: bool = False
    error: str = ""
    extra: dict = field(default_factory=dict)


def is_skippable(path: Path) -> bool:
    """Pliki ukryte, tymczasowe, niedokończone pobrania i systemowe śmieci."""
    name = path.name.lower()
    return (name.startswith((".", "~$")) or name in SKIP_NAMES or name.endswith(SKIP_SUFFIXES))


def list_folders(root: Path, max_depth: int = 3) -> list[str]:
    """Względne ścieżki folderów drzewa (separator "/"), bez ukrytych."""
    root = Path(root)
    out: list[str] = []
    for dirpath, dirnames, _ in os.walk(root):
        rel = Path(dirpath).relative_to(root)
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        if len(rel.parts) >= max_depth:
            dirnames[:] = []
        out.extend((rel / d).as_posix() for d in dirnames)
    return out


def unique_path(dest: Path) -> Path:
    """Nie nadpisuje: plik.txt → plik (2).txt → plik (3).txt …"""
    if not dest.exists():
        return dest
    n = 2
    while True:
        cand = dest.with_name(f"{dest.stem} ({n}){dest.suffix}")
        if not cand.exists():
            return cand
        n += 1


def _within(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _move(src: Path, dest: Path) -> None:
    """shutil.move bez zostawiania kopii: gdy źródła nie da się usunąć (np. plik otwarty
    w innym programie na Windows), kopia w miejscu docelowym jest kasowana."""
    try:
        shutil.move(str(src), str(dest))
    except BaseException:
        if src.exists() and dest.exists() and not dest.is_dir():
            try:
                dest.unlink()
            except OSError:
                pass
        raise


def _append_log(root: Path, entry: dict) -> None:
    with open(root / LOG_NAME, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_log(root: Path) -> list[dict]:
    """Wpisy dziennika (uszkodzone linie są pomijane)."""
    path = Path(root) / LOG_NAME
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            entries.append(json.loads(line))
        except ValueError:
            continue
    return [e for e in entries if isinstance(e, dict)]


def _mkdirs(folder: Path) -> list[str]:
    """Tworzy folder z rodzicami; zwraca listę faktycznie utworzonych (od najpłytszego)."""
    missing = []
    p = folder
    while not p.exists():
        missing.append(p)
        p = p.parent
    folder.mkdir(parents=True, exist_ok=True)
    return [str(m) for m in reversed(missing)]


def sort_inbox(inbox, root, ai_fn: Callable[[str], str] | None = None, dry_run: bool = False) -> list[Result]:
    """Klasyfikuje i przenosi każdy plik ze skrzynki do drzewa `root`."""
    inbox, root = Path(inbox), Path(root)
    root.mkdir(parents=True, exist_ok=True)
    existing = list_folders(root)
    results: list[Result] = []
    files = sorted((p for p in inbox.iterdir() if p.is_file() and not is_skippable(p)), key=lambda p: p.name.lower())
    for src in files:
        try:
            dec = classify(src, existing, ai_fn=ai_fn)
            folder = root.joinpath(*dec.folder.split("/"))
            if not _within(folder, root):
                raise ValueError("folder poza drzewem pamięci")
            dest = folder / dec.filename
            if dest.resolve() == src.resolve():
                results.append(Result(src, dest, dec, error="plik jest już na miejscu"))
                continue
            dest = unique_path(dest)
            if dry_run:
                results.append(Result(src, dest, dec))
            else:
                created = _mkdirs(folder)
                _move(src, dest)
                _append_log(root, {
                    "id": uuid.uuid4().hex, "action": "move",
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                    "original": str(src.resolve()), "destination": str(dest.resolve()),
                    "folder": dec.folder, "reason": dec.reason, "source": dec.source,
                    "confidence": dec.confidence, "created_dirs": created,
                })
                results.append(Result(src, dest, dec, moved=True))
            if dec.folder not in existing:
                existing.append(dec.folder)
        except Exception as exc:  # noqa: BLE001 - jeden zły plik nie zatrzymuje reszty
            results.append(Result(src, None, None, error=f"{type(exc).__name__}: {exc}"))
    return results


def undo_last(root, n: int = 1) -> list[tuple[Path, Path]]:
    """Cofa `n` ostatnich przeniesień z dziennika; zwraca pary (skąd, dokąd)."""
    root = Path(root)
    entries = read_log(root)
    undone = {e.get("id") for e in entries if e.get("action") == "undo"}
    todo = [e for e in reversed(entries) if e.get("action") == "move" and e.get("id") not in undone][:max(0, n)]
    restored: list[tuple[Path, Path]] = []
    for e in todo:
        src, orig = Path(e["destination"]), Path(e["original"])
        ok = src.exists()
        if ok:
            orig.parent.mkdir(parents=True, exist_ok=True)
            target = unique_path(orig)
            _move(src, target)
            restored.append((src, target))
            for d in reversed(e.get("created_dirs") or []):
                try:
                    Path(d).rmdir()  # tylko puste
                except OSError:
                    break
        _append_log(root, {"id": e.get("id"), "action": "undo",
                           "timestamp": datetime.now().isoformat(timespec="seconds"),
                           "restored": ok})
    return restored
