"""tars_ai – jedyne miejsce, w którym TARS rozmawia z AI (lokalna Ollama, modele qwen3.5)."""
from .anthropic_compat import Anthropic, AsyncAnthropic
from .client import OllamaError, chat, health, list_models
from .router import pick_tier

__all__ = ["chat", "pick_tier", "health", "list_models", "OllamaError", "Anthropic", "AsyncAnthropic"]
