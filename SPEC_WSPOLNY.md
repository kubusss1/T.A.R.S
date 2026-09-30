# Wspólne ustalenia modułów TARS (offline, Ollama)

Te moduły są niezależne od reszty kodu TARS (który jest na komputerze Kuby)
i mają dać się do niego podpiąć bez przeróbek.

## Zasady dla wszystkich modułów
- Python 3.10+, **tylko biblioteka standardowa** (urllib, json, pathlib, unittest…). Zero `pip install`.
- Działa na Windows (ścieżki przez `pathlib`, kodowanie UTF-8 jawnie).
- Testy: `unittest`, pliki `tests/test_<modul>.py`, uruchamiane z katalogu głównego repo:
  `python -m unittest discover -s tests -v`. Każdy moduł ma **co najmniej 10 testów**.
  Testy nie mogą wymagać działającej Ollamy ani internetu (mocki / lokalny fake serwer HTTP).
- Teksty widoczne dla użytkownika: po polsku. Nazwy w kodzie: po angielsku.
- Konfiguracja przez zmienne środowiskowe z sensownymi domyślnymi wartościami.

## Modele (Ollama na `http://localhost:11434`)
| Poziom | Domyślny model | Zmienna env | Do czego |
|---|---|---|---|
| `big`   | `qwen3.5:9b` | `TARS_MODEL_BIG`   | trudne zadania, kod, długie odpowiedzi |
| `mid`   | `qwen3.5:4b` | `TARS_MODEL_MID`   | zwykły czat, klasyfikacja, streszczenia |
| `small` | `qwen3.5:2b` | `TARS_MODEL_SMALL` | krótkie etykiety, tytuły, tak/nie |

Adres: `OLLAMA_URL` (domyślnie `http://localhost:11434`).

## Interfejs `tars_ai` (używany przez inne moduły)
```python
from tars_ai import chat, pick_tier, health

text: str = chat(prompt, *, task="general", system=None, model=None, tier=None,
                 temperature=0.3, timeout=120, json_mode=False)
tier: str = pick_tier(task: str, prompt: str)   # "big" | "mid" | "small"
info: dict = health()                           # {"ok": bool, "models": [...], "missing": [...]}
```
Błędy: `tars_ai.OllamaError` (podklasa `RuntimeError`).

Inne moduły **importują `tars_ai` leniwie** (wewnątrz funkcji) i przyjmują
wstrzykiwaną funkcję (`ai_fn=`), żeby testy mogły ją podmienić.
