"""Zamiennik SDK Anthropic działający na lokalnej Ollamie.

Wystarczy zmienić import:  ``from tars_ai.anthropic_compat import Anthropic``
Modele claude-*: "opus" -> big, "sonnet" -> mid, "haiku" -> small (inny claude-* -> mid).
Nazwy spoza rodziny claude są przekazywane do Ollamy bez zmian.
"""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any

from . import client


@dataclass
class TextBlock:
    text: str
    type: str = "text"


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class Message:
    content: list[TextBlock]
    model: str
    stop_reason: str = "end_turn"
    usage: Usage = field(default_factory=Usage)
    id: str = field(default_factory=lambda: "msg_" + uuid.uuid4().hex[:24])
    role: str = "assistant"
    type: str = "message"
    stop_sequence: str | None = None


def map_model(name: str | None) -> tuple[str | None, str]:
    """Zwraca (model_ollamy | None, poziom). None = użyj modelu poziomu."""
    low = (name or "").lower()
    if not low or low.startswith("claude"):
        tier = "big" if "opus" in low else "small" if "haiku" in low else "mid"
        return None, tier
    return name, "mid"


def flatten(content: Any) -> str:
    """Treść wiadomości (str lub lista bloków) -> tekst; bloki inne niż text są pomijane."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    parts = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
        elif getattr(block, "type", None) == "text":
            parts.append(getattr(block, "text", ""))
    return "\n".join(p for p in parts if p)


_STOP = {"stop": "end_turn", "length": "max_tokens"}


class Messages:
    def __init__(self, owner: "Anthropic"):
        self._owner = owner

    def create(self, *, model: str | None = None, max_tokens: int | None = None,
               messages: list[dict], system: Any = None, temperature: float | None = None,
               **_ignored: Any) -> Message:
        """Odpowiednik anthropic.messages.create (bez streamingu i narzędzi)."""
        ollama_model, tier = map_model(model)
        msgs = [{"role": "system", "content": flatten(system)}] if system else []
        msgs += [{"role": m.get("role", "user"), "content": flatten(m.get("content"))} for m in messages]
        res = client.complete(msgs, model=ollama_model, tier=tier,
                              temperature=0.3 if temperature is None else temperature,
                              timeout=self._owner.timeout, max_tokens=max_tokens)
        return Message(content=[TextBlock(res["text"])], model=res["model"],
                       stop_reason=_STOP.get(res["done_reason"], "end_turn"),
                       usage=Usage(res["input_tokens"], res["output_tokens"]))


class Anthropic:
    """Klient zgodny z anthropic.Anthropic (api_key i inne argumenty są ignorowane)."""

    def __init__(self, api_key: str | None = None, *, timeout: float = 120, **_ignored: Any):
        self.timeout = timeout if isinstance(timeout, (int, float)) else 120
        self.messages = Messages(self)


class AsyncMessages:
    def __init__(self, sync: Messages):
        self._sync = sync

    async def create(self, **kwargs: Any) -> Message:
        return await asyncio.to_thread(self._sync.create, **kwargs)


class AsyncAnthropic(Anthropic):
    """Asynchroniczna wersja: ``await client.messages.create(...)``."""

    def __init__(self, api_key: str | None = None, **kwargs: Any):
        super().__init__(api_key, **kwargs)
        self.messages = AsyncMessages(Messages(self))  # type: ignore[assignment]
