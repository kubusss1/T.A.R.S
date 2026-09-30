"""Linia poleceń::

    python -m tars_seo audit <url> [--html raport.html] [--ai] [--save] [--sort impact|category|level] [--json]
    python -m tars_seo compare <url_a> <url_b>
    python -m tars_seo trend <url>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .ai import suggest
from .core import audit, compare
from .history import save_audit, trend
from .report import render_compare_text, render_html, render_text, render_trend_text
from .score import SORT_MODES


def _utf8_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    _utf8_stdout()
    ap = argparse.ArgumentParser(prog="python -m tars_seo",
                                 description="TARS SEO — prosty audyt SEO strony po polsku.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("audit", help="audyt jednej strony")
    a.add_argument("url")
    a.add_argument("--html", metavar="PLIK", help="zapisz raport HTML do pliku")
    a.add_argument("--ai", action="store_true", help="dodaj podpowiedzi AI (Ollama)")
    a.add_argument("--save", action="store_true", help="zapisz wynik w historii (TARS_SEO_DIR)")
    a.add_argument("--sort", choices=SORT_MODES, default="impact", help="kolejność listy sprawdzeń")
    a.add_argument("--json", action="store_true", help="wypisz wynik jako JSON")
    c = sub.add_parser("compare", help="porównaj stronę z konkurencją")
    c.add_argument("url_a")
    c.add_argument("url_b")
    t = sub.add_parser("trend", help="zmiany od poprzedniego audytu")
    t.add_argument("url")
    args = ap.parse_args(argv)

    try:
        if args.cmd == "audit":
            result = audit(args.url)
            if args.ai:
                result["ai"] = suggest(result)
            if args.save:
                path = save_audit(result)
                result["trend"] = trend(result["url"])
                print(f"Zapisano w historii: {path}", file=sys.stderr)
            if args.json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print(render_text(result, sort=args.sort))
            if args.html:
                out = Path(args.html)
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(render_html(result), encoding="utf-8")
                print(f"\nRaport HTML: {out.resolve()}")
            return 0 if not result.get("error") else 2
        if args.cmd == "compare":
            cmp = compare(args.url_a, args.url_b)
            print(render_compare_text(cmp))
            return 0
        if args.cmd == "trend":
            print(render_trend_text(trend(args.url)))
            return 0
    except ValueError as e:
        print(f"Błąd: {e}", file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    sys.exit(main())
