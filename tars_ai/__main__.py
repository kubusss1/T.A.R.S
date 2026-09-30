"""CLI: ``python -m tars_ai health`` | ``python -m tars_ai ask "pytanie"``."""
from __future__ import annotations

import argparse
import sys

from . import config
from .client import OllamaError, chat, health


def _utf8_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def cmd_health() -> int:
    info = health()
    print(f"Ollama: {info['url']}")
    if info.get("error"):
        print(f"[BŁĄD] {info['error']}")
        return 2
    print(f"Zainstalowane modele ({len(info['models'])}): {', '.join(info['models']) or 'brak'}")
    for tier, name in config.models().items():
        state = "BRAK" if name in info["missing"] else "OK"
        print(f"  {tier:<5} {name:<20} {state}")
    if info["missing"]:
        print("Brakujące modele – zainstaluj poleceniem:")
        for name in info["missing"]:
            print(f"  ollama pull {name}")
        return 1
    print("Wszystko gotowe.")
    return 0


def main(argv: list[str] | None = None) -> int:
    _utf8_stdout()
    p = argparse.ArgumentParser(prog="python -m tars_ai", description="Lokalne AI TARS (Ollama).")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("health", help="sprawdź Ollamę i modele")
    ask = sub.add_parser("ask", help="zadaj pytanie modelowi")
    ask.add_argument("prompt", nargs="+", help="treść pytania")
    ask.add_argument("--task", default="general", help="rodzaj zadania (np. code, chat, title)")
    ask.add_argument("--tier", choices=config.TIERS, help="wymuś poziom modelu")
    ask.add_argument("--model", help="wymuś konkretny model Ollamy")
    ask.add_argument("--system", help="prompt systemowy")
    args = p.parse_args(argv)
    if args.cmd == "health":
        return cmd_health()
    try:
        print(chat(" ".join(args.prompt), task=args.task, tier=args.tier,
                   model=args.model, system=args.system))
    except OllamaError as e:
        print(f"[BŁĄD] {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
