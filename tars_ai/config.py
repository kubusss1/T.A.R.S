"""Konfiguracja tars_ai: adres Ollamy i modele dla poziomów big/mid/small.

Wartości czytane są przy każdym wywołaniu (nie przy imporcie), więc zmiana
zmiennych środowiskowych działa od razu.
"""
from __future__ import annotations

import os

DEFAULT_URL = "http://localhost:11434"
TIERS = ("big", "mid", "small")  # od największego do najmniejszego
DEFAULT_MODELS = {"big": "qwen3.5:9b", "mid": "qwen3.5:4b", "small": "qwen3.5:2b"}
ENV_VARS = {"big": "TARS_MODEL_BIG", "mid": "TARS_MODEL_MID", "small": "TARS_MODEL_SMALL"}


def ollama_url() -> str:
    """Bazowy URL Ollamy (env OLLAMA_URL), bez końcowego '/'."""
    url = (os.environ.get("OLLAMA_URL") or DEFAULT_URL).strip()
    if "://" not in url:
        url = "http://" + url
    return url.rstrip("/")


def model_for(tier: str) -> str:
    """Nazwa modelu dla poziomu ('big' | 'mid' | 'small')."""
    if tier not in DEFAULT_MODELS:
        raise ValueError(f"Nieznany poziom modelu: {tier!r} (dozwolone: {', '.join(TIERS)})")
    return (os.environ.get(ENV_VARS[tier]) or DEFAULT_MODELS[tier]).strip()


def models() -> dict[str, str]:
    """Aktualne mapowanie poziom -> model."""
    return {t: model_for(t) for t in TIERS}


def smaller_tiers(tier: str) -> list[str]:
    """Poziomy mniejsze od podanego, w kolejności malejącej."""
    return list(TIERS[TIERS.index(tier) + 1:]) if tier in TIERS else []
