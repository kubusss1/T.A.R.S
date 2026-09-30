"""Klient Ollamy (POST /api/chat, stream=false) z łańcuchem awaryjnym modeli."""
from __future__ import annotations

import http.client
import json
import re
import socket
import urllib.error
import urllib.request
from typing import Any

from . import config
from .router import pick_tier


class OllamaError(RuntimeError):
    """Błąd komunikacji z Ollamą (komunikat po polsku)."""


class _ModelMissing(Exception):
    """Model nie jest zainstalowany (404 / 'not found')."""


_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def strip_think(text: str) -> str:
    """Usuwa bloki <think>...</think> (także niedomknięte/osierocone)."""
    text = _THINK_RE.sub("", text or "")
    low = text.lower()
    if "</think>" in low:  # początek bloku uciął się
        text = text[low.rindex("</think>") + len("</think>"):]
    elif "<think>" in low:  # blok nie został domknięty
        text = text[:low.index("<think>")]
    return text.strip()


def _unreachable(url: str, reason: Any) -> OllamaError:
    return OllamaError(f"Ollama nie odpowiada na {url} ({reason}), uruchom Ollamę "
                       f"(np. `ollama serve`) albo ustaw poprawny OLLAMA_URL.")


def _request(path: str, payload: dict | None, timeout: float) -> dict:
    """Wysyła żądanie JSON do Ollamy i zwraca zdekodowaną odpowiedź."""
    base = config.ollama_url()
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(base + path, data=data, method="GET" if data is None else "POST",
                                 headers={"Content-Type": "application/json; charset=utf-8"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        if e.code == 404 or "not found" in detail.lower():
            raise _ModelMissing(detail) from e
        raise OllamaError(f"Ollama zwróciła błąd HTTP {e.code}: {detail[:300]}") from e
    except (socket.timeout, TimeoutError) as e:
        raise OllamaError(f"Ollama ({base}) nie odpowiedziała w ciągu {timeout} s.") from e
    except (urllib.error.URLError, ConnectionError, OSError) as e:
        raise _unreachable(base, getattr(e, "reason", e)) from e
    except (http.client.HTTPException, ValueError) as e:  # np. zły port w OLLAMA_URL, to nie serwer HTTP
        raise _unreachable(base, f"{type(e).__name__}: {e}") from e
    try:
        out = json.loads(body) if body.strip() else {}
    except json.JSONDecodeError as e:
        raise OllamaError(f"Niepoprawna odpowiedź Ollamy: {body[:200]}") from e
    if not isinstance(out, dict):
        raise OllamaError(f"Niepoprawna odpowiedź Ollamy: {body[:200]}")
    if out.get("error"):
        err = str(out["error"])
        if "not found" in err.lower():
            raise _ModelMissing(err)
        raise OllamaError(f"Ollama zgłosiła błąd: {err}")
    return out


def list_models(timeout: float = 10) -> list[str]:
    """Nazwy modeli zainstalowanych w Ollamie (GET /api/tags)."""
    try:
        data = _request("/api/tags", None, timeout)
    except _ModelMissing as e:
        raise OllamaError("Ollama nie udostępnia /api/tags – sprawdź OLLAMA_URL.") from e
    return [m.get("name") or m.get("model", "") for m in data.get("models", [])]


def _installed(name: str, installed: list[str]) -> bool:
    return name in installed or (":" not in name and f"{name}:latest" in installed)


def health(timeout: float = 5) -> dict:
    """Stan Ollamy: {"ok", "url", "models", "missing"} (+ "error" gdy nie działa)."""
    url = config.ollama_url()
    wanted = list(dict.fromkeys(config.models().values()))
    try:
        installed = list_models(timeout)
    except OllamaError as e:
        return {"ok": False, "url": url, "models": [], "missing": wanted, "error": str(e)}
    missing = [m for m in wanted if not _installed(m, installed)]
    return {"ok": not missing, "url": url, "models": installed, "missing": missing}


def _candidates(model: str | None, tier: str) -> list[str]:
    """Kolejność prób: wybrany model, potem mniejsze poziomy."""
    tiers = config.models()
    if model and model not in tiers.values():
        chain = [model] + [tiers[t] for t in config.TIERS]
    else:
        start = next((t for t, m in tiers.items() if m == model), tier)
        chain = ([model] if model else []) + [tiers[start]] + [tiers[t] for t in config.smaller_tiers(start)]
    return list(dict.fromkeys(chain))


def complete(messages: list[dict], *, model: str | None = None, tier: str = "mid",
             temperature: float | None = 0.3, timeout: float = 120, json_mode: bool = False,
             max_tokens: int | None = None) -> dict:
    """Niskopoziomowe wywołanie /api/chat z fallbackiem.

    Zwraca {"text", "model", "input_tokens", "output_tokens", "done_reason"}.
    """
    options: dict[str, Any] = {}
    if temperature is not None:
        options["temperature"] = temperature
    if max_tokens:
        options["num_predict"] = int(max_tokens)
    tried: list[str] = []
    queue = _candidates(model, tier)
    fetched_tags = False
    while True:
        if not queue:
            if fetched_tags:
                break
            fetched_tags = True
            # modele embeddingowe (np. nomic-embed-text) nie obsługują czatu
            queue = [m for m in list_models(min(timeout, 10))
                     if m not in tried and "embed" not in m.lower()]
            continue
        name = queue.pop(0)
        if name in tried:
            continue
        tried.append(name)
        payload: dict[str, Any] = {"model": name, "messages": messages, "stream": False}
        if options:
            payload["options"] = options
        if json_mode:
            payload["format"] = "json"
        try:
            data = _request("/api/chat", payload, timeout)
        except _ModelMissing:
            continue
        msg = data.get("message") or {}
        return {
            "text": strip_think(msg.get("content", "")),
            "model": data.get("model") or name,
            "input_tokens": int(data.get("prompt_eval_count") or 0),
            "output_tokens": int(data.get("eval_count") or 0),
            "done_reason": data.get("done_reason") or "stop",
        }
    raise OllamaError("Brak dostępnego modelu w Ollamie (próbowano: "
                      f"{', '.join(tried) or 'żaden'}). Zainstaluj np. `ollama pull {config.model_for('mid')}`.")


def chat(prompt: str, *, task: str = "general", system: str | None = None, model: str | None = None,
         tier: str | None = None, temperature: float = 0.3, timeout: float = 120,
         json_mode: bool = False, history: list[dict] | None = None) -> str:
    """Wysyła prompt do lokalnego modelu i zwraca czysty tekst odpowiedzi.

    Poziom: `tier` > (gdy brak `model`) pick_tier(task, prompt). `history` to lista
    {"role": "user"|"assistant", "content": str} poprzedzająca bieżący prompt.
    """
    tier = tier or pick_tier(task, prompt)
    config.model_for(tier)  # walidacja nazwy poziomu
    messages: list[dict] = [{"role": "system", "content": system}] if system else []
    messages += [{"role": m["role"], "content": m["content"]} for m in (history or [])]
    messages.append({"role": "user", "content": prompt})
    return complete(messages, model=model, tier=tier, temperature=temperature,
                    timeout=timeout, json_mode=json_mode)["text"]
