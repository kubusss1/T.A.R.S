"""Konfiguracja stron klientów ZrobSite (plik JSON z listą {name, url, key})."""
from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_SITES_FILE = "sites.json"
ENV_SITES_FILE = "TARS_SITES_FILE"


class SitesConfigError(ValueError):
    """Błąd pliku konfiguracji stron (komunikat po polsku)."""


def sites_file_path(path: str | os.PathLike | None = None) -> Path:
    """Ścieżka pliku stron: argument > zmienna TARS_SITES_FILE > sites.json."""
    if path:
        return Path(path)
    return Path(os.environ.get(ENV_SITES_FILE) or DEFAULT_SITES_FILE)


def normalize_site(raw: object, index: int = 0) -> dict:
    """Sprawdza i normalizuje jeden wpis strony."""
    if not isinstance(raw, dict):
        raise SitesConfigError(f"Wpis nr {index + 1} musi być obiektem JSON.")
    url = str(raw.get("url") or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise SitesConfigError(f"Wpis nr {index + 1}: nieprawidłowy adres URL „{url}”.")
    key = str(raw.get("key") or "").strip()
    if not key:
        raise SitesConfigError(f"Wpis nr {index + 1} ({url}): brak klucza API „key”.")
    name = str(raw.get("name") or "").strip() or parsed.netloc
    site = {"name": name, "url": url.rstrip("/"), "key": key}
    api_base = str(raw.get("api_base") or "").strip()
    if api_base:
        site["api_base"] = api_base.rstrip("/")
    if raw.get("verify_ssl") is False:
        site["verify_ssl"] = False
    return site


def parse_sites(data: object) -> list[dict]:
    """Lista stron z danych JSON (lista albo {"sites": [...]}); pomija "enabled": false."""
    if isinstance(data, dict):
        data = data.get("sites")
    if not isinstance(data, list):
        raise SitesConfigError("Plik stron musi zawierać listę lub obiekt z kluczem „sites”.")
    sites = []
    seen = set()
    for i, raw in enumerate(data):
        if isinstance(raw, dict) and raw.get("enabled") is False:
            continue
        site = normalize_site(raw, i)
        if site["url"] in seen:
            raise SitesConfigError(f"Zduplikowany adres strony: {site['url']}")
        seen.add(site["url"])
        sites.append(site)
    return sites


def load_sites(path: str | os.PathLike | None = None) -> list[dict]:
    """Wczytuje strony z pliku JSON (UTF-8, także z BOM z Notatnika)."""
    file = sites_file_path(path)
    if not file.is_file():
        raise SitesConfigError(
            f"Nie znaleziono pliku stron: {file}. Skopiuj tars_zrobsite/sites.example.json "
            f"lub ustaw zmienną {ENV_SITES_FILE}."
        )
    try:
        data = json.loads(file.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise SitesConfigError(f"Błąd składni JSON w {file} (linia {exc.lineno}): {exc.msg}") from exc
    except OSError as exc:
        raise SitesConfigError(f"Nie można odczytać pliku {file}: {exc}") from exc
    return parse_sites(data)
