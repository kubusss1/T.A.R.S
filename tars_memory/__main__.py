"""CLI: python -m tars_memory sort|undo|list …"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from .filetypes import human_size
from .listing import SORT_LABELS, SORT_MODES, list_items
from .sorter import sort_inbox, undo_last


def _rel(p: Path, root: Path) -> str:
    try:
        return Path(p).relative_to(root).as_posix()
    except ValueError:
        return str(p)


def cmd_sort(a) -> int:
    root = Path(a.root)
    results = sort_inbox(Path(a.inbox), root, dry_run=a.dry_run)
    if not results:
        print("Skrzynka jest pusta — nie ma nic do posortowania.")
        return 0
    if a.dry_run:
        print("Tryb próbny — nic nie zostało przeniesione.\n")
    ok = 0
    for r in results:
        if r.error:
            print(f"  ✗ {r.original.name}: {r.error}")
            continue
        ok += 1
        d = r.decision
        new = " [nowy folder]" if d.new_folder else ""
        src = "AI" if d.source == "ai" else "reguły"
        print(f"  ✓ {r.original.name} → {_rel(r.destination, root)}{new}")
        print(f"      {src}, pewność {d.confidence:.0%}: {d.reason}")
    verb = "Do przeniesienia" if a.dry_run else "Przeniesiono"
    print(f"\n{verb}: {ok} z {len(results)} plików.")
    return 0 if ok == len(results) else 1


def cmd_undo(a) -> int:
    restored = undo_last(Path(a.root), a.n)
    if not restored:
        print("Nie ma czego cofnąć.")
        return 0
    for src, dst in restored:
        print(f"  ↩ {src.name} → {dst}")
    print(f"\nCofnięto przeniesień: {len(restored)}.")
    return 0


def cmd_list(a) -> int:
    root = Path(a.root)
    items = list_items(root, sort=a.sort, query=a.q, types=a.type or None)
    if not items:
        print("Brak plików pasujących do kryteriów.")
        return 0
    print(f"Pamięć: {root} — {len(items)} plików, sortowanie: {SORT_LABELS[a.sort]}\n")
    for i in items:
        when = datetime.fromtimestamp(i.mtime).strftime("%Y-%m-%d %H:%M")
        folder = i.folder or "."
        print(f"  {i.name:<40} {folder:<28} {human_size(i.size):>10}  {when}  {i.group_label}")
    return 0


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # konsola Windows
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(prog="python -m tars_memory", description="TARS — zakładka Pamięć")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sort", help="rozłóż pliki ze skrzynki do drzewa pamięci")
    s.add_argument("inbox", help="folder skrzynki (inbox)")
    s.add_argument("root", help="katalog główny pamięci")
    s.add_argument("--dry-run", action="store_true", help="tylko pokaż, nic nie przenoś")
    s.set_defaults(func=cmd_sort)
    u = sub.add_parser("undo", help="cofnij ostatnie przeniesienia")
    u.add_argument("root", help="katalog główny pamięci")
    u.add_argument("-n", type=int, default=1, help="ile przeniesień cofnąć (domyślnie 1)")
    u.set_defaults(func=cmd_undo)
    ls = sub.add_parser("list", help="pokaż pliki pamięci")
    ls.add_argument("root", help="katalog główny pamięci")
    ls.add_argument("--sort", choices=SORT_MODES, default="recent", help="tryb sortowania")
    ls.add_argument("--q", default=None, help="szukaj w nazwie/folderze")
    ls.add_argument("--type", action="append", help="filtr typu, np. obrazy, dokumenty (można powtarzać)")
    ls.set_defaults(func=cmd_list)
    a = ap.parse_args(argv)
    try:
        return a.func(a)
    except (OSError, ValueError) as exc:
        print(f"Błąd: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
