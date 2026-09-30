"""CLI: python -m tars_zrobsite [--sites plik.json] [--sort health] [--html out.html] [--telegram]."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .dashboard import SORT_MODES, build_dashboard
from .render import render_html, render_telegram, render_text
from .sites import SitesConfigError, load_sites


def _configure_stdout() -> None:
    # Konsola Windows (cp1250) nie zawsze obsłuży polskie znaki / emoji.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    _configure_stdout()
    parser = argparse.ArgumentParser(
        prog="python -m tars_zrobsite",
        description="Statusy i analityka stron ZrobSite (wtyczka TARS Bridge).",
    )
    parser.add_argument("--sites", help="plik JSON ze stronami (domyślnie $TARS_SITES_FILE lub sites.json)")
    parser.add_argument("--sort", choices=SORT_MODES, default="health", help="kolejność stron (domyślnie: health)")
    parser.add_argument("--html", metavar="PLIK", help="zapisz widok HTML do pliku")
    parser.add_argument("--telegram", action="store_true", help="wypisz wiadomość w formacie Telegram HTML")
    parser.add_argument("--theme", choices=("light", "dark"), help="wymuś motyw HTML (domyślnie wg systemu)")
    args = parser.parse_args(argv)

    try:
        sites = load_sites(args.sites)
    except SitesConfigError as exc:
        print(f"Błąd konfiguracji: {exc}", file=sys.stderr)
        return 2

    dashboard = build_dashboard(sites, sort=args.sort)
    print(render_telegram(dashboard) if args.telegram else render_text(dashboard), end="" if not args.telegram else "\n")

    if args.html:
        out = Path(args.html)
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(render_html(dashboard, theme=args.theme), encoding="utf-8")
        except OSError as exc:
            print(f"Nie można zapisać pliku {out}: {exc}", file=sys.stderr)
            return 1
        print(f"Zapisano widok HTML: {out.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
