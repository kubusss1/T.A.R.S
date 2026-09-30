# T.A.R.S — moduły offline (Ollama + Qwen)

Gotowe klocki do podpięcia pod TARS, który działa na Twoim komputerze.
Wszystko w czystym Pythonie (bez `pip install`), AI tylko lokalnie przez Ollamę.
Żaden moduł nie wymaga Claude ani klucza Anthropic.

| Moduł | Co robi |
|---|---|
| `tars_ai/` | Jedno miejsce rozmowy z AI: Ollama + Qwen, automatyczny dobór modelu do zadania, zamiennik biblioteki Anthropic |
| `tars_memory/` | Pamięć: wrzucasz dowolny plik → AI sama go segreguje do folderów (albo tworzy nowy), cofanie, lepsze sortowanie |
| `tars_zrobsite/` + `wordpress/tars-bridge/` | Zakładka **Statusy i analityka**: stan stron klientów (aktualizacje, SSL, błędy), wizyty bez cookies, zgody cookies |
| `tars_telegram/` | Ładniejsze wiadomości bota (karty, statusy, paski postępu, menu, sortowanie) + **Mini App** z panelem TARS i ZrobSite |
| `tars_seo/` | Prosty audyt SEO: ocena 0–100 i A–F, „Top 3 do poprawy” po ludzku, porównanie z konkurencją, historia zmian, propozycje tytułów/opisów od AI |
| `narzedzia/sprawdz-ollame.ps1` | Sprawdza Ollamę i dociąga brakujące modele Qwen na dysk F |

## Modele

| Poziom | Model | Kiedy |
|---|---|---|
| duży | `qwen3.5:9b` | kod, planowanie, analizy, długie teksty |
| średni | `qwen3.5:4b` | czat, streszczenia, segregowanie plików |
| mały | `qwen3.5:2b` | tytuły, etykiety, tak/nie |

Jeśli modelu brakuje, TARS sam przechodzi na mniejszy. Zmiana modeli: zmienne
`TARS_MODEL_BIG`, `TARS_MODEL_MID`, `TARS_MODEL_SMALL`, adres: `OLLAMA_URL`.

## Szybki start (Windows, PowerShell, w folderze repo)

```powershell
powershell -ExecutionPolicy Bypass -File narzedzia\sprawdz-ollame.ps1   # modele
python -m tars_ai health                     # czy AI działa
python -m tars_ai ask "Cześć, kim jesteś?"   # test odpowiedzi
python -m unittest discover -s tests         # wszystkie testy
```

## Podpięcie do istniejącego TARS

**1. Odpięcie Claude (najważniejsze).** W kodzie TARS znajdź `import anthropic`
/ `from anthropic import ...` i zamień na:

```python
from tars_ai import Anthropic          # zamiast: from anthropic import Anthropic
from tars_ai import AsyncAnthropic     # jeśli kod jest asynchroniczny
```

Reszta kodu (`client.messages.create(...)`, `resp.content[0].text`) działa bez zmian.
Nazwy `claude-opus-*` → duży model, `claude-sonnet-*` → średni, `claude-haiku-*` → mały.
W nowym kodzie najprościej: `from tars_ai import chat; chat("pytanie", task="summary")`.

**2. Pamięć.** Folder „do posegregowania” → posegregowana pamięć:

```powershell
python -m tars_memory sort C:\TARS\pamiec\_wrzuc C:\TARS\pamiec
python -m tars_memory list C:\TARS\pamiec --sort recent
python -m tars_memory undo C:\TARS\pamiec
```

W panelu: `sort_inbox(inbox, root)` po wrzuceniu pliku, `list_items(root, sort=..., query=...)` do listy.

**3. Statusy i analityka ZrobSite.**
1. Spakuj `wordpress/tars-bridge/` do ZIP → WordPress → Wtyczki → Dodaj → Wyślij → Aktywuj (na każdej stronie klienta).
2. Ustawienia → TARS Bridge → skopiuj gotowy wpis do `sites.json` (wzór: `tars_zrobsite/sites.example.json`). Plik `sites.json` zawiera klucze — jest w `.gitignore`.
3. Podgląd: `python -m tars_zrobsite --html statusy.html`. W panelu: `build_dashboard(...)` + `render_html(...)`, w Telegramie: `render_telegram(...)`.

**4. SEO.**

```powershell
python -m tars_seo audit https://strona-klienta.pl --html raport.html --save
python -m tars_seo audit https://strona-klienta.pl --ai          # + propozycje tytułów i opisów
python -m tars_seo compare https://strona-klienta.pl https://konkurencja.pl
python -m tars_seo trend https://strona-klienta.pl               # co się poprawiło od ostatniego razu
```

**5. Telegram.** Wiadomości wysyłaj z `parse_mode="HTML"` i klockami z `tars_telegram`
(`card`, `tpl_ai_answer`, `md_to_tg_html`, `chunk_message`, `main_menu`, `sort_menu`).
Mini App: instrukcja w `tars_telegram/miniapp/README.md`.

## Czego tu nie ma

- Zamiennik Anthropic nie obsługuje strumieniowania (`stream=True`, `messages.stream`) ani narzędzi (tool use).
  Jeśli kod TARS ich używa, te miejsca trzeba przepisać na zwykłe `messages.create` / `chat(...)`.
- Wtyczka WordPress ma przetestowaną logikę, ale nie była uruchomiona na prawdziwym WordPressie —
  najpierw zainstaluj ją na jednej stronie testowej.

Kod samego TARS (bot, panele) jest tylko na Twoim komputerze — nie ma go w tym repo.
Dlatego te moduły są gotowe i przetestowane, ale ich wpięcie w panel i bota
trzeba zrobić tam, gdzie leży kod TARS (kroki wyżej). Jeśli wrzucisz kod TARS do
repo, wpięcie da się zrobić automatycznie.
