# Mini App TARS

Jedno okno w Telegramie z dwiema zakładkami: **TARS** i **ZrobSite**. Każda
pokazuje odpowiedni panel WWW w ramce (iframe). Adresy paneli podajesz w linku:

```
https://twoj-host/?tars=https://tars.example.com&zrobsite=https://panel.zrobsite.pl
```

Dozwolone są adresy `https://` oraz `http://` w sieci lokalnej (localhost,
192.168.x.x, 10.x.x.x, Tailscale 100.64.x.x) — te ostatnie działają tylko
poza Telegramem, bo Mini App jest po HTTPS.

## 1. Uruchom serwer

```
set TARS_BOT_TOKEN=123456:ABC...          (Windows; w Linuksie: export ...)
set TARS_ALLOWED_USER_IDS=111222333        (opcjonalnie: tylko Twoje konto)
python -m tars_telegram.miniapp.server --port 8765
```

Serwer udostępnia tylko `index.html`, `GET /health` i `POST /auth`.
Adresy paneli możesz też ustawić na stałe: `TARS_MINIAPP_TARS_URL`,
`TARS_MINIAPP_ZROBSITE_URL`.

## 2. Wystaw go przez HTTPS

Telegram otwiera Mini App **tylko przez HTTPS**. Najprościej:

- Cloudflare Tunnel: `cloudflared tunnel --url http://localhost:8765`
- ngrok: `ngrok http 8765`

Tak samo wystaw panel TARS i panel ZrobSite, jeśli działają lokalnie.
Jeśli panel wysyła `X-Frame-Options: DENY` albo `frame-ancestors`, nie
pokaże się w ramce — wtedy użyj przycisku „Otwórz w przeglądarce” albo
zezwól na `frame-ancestors https://twoj-host https://web.telegram.org`.

## 3. Zarejestruj w BotFather

- **Przycisk menu** (najwygodniej): `/mybots` → bot → *Bot Settings* →
  *Menu Button* → podaj adres `https://…` z parametrami.
- **Osobna Mini App** (link `t.me/twoj_bot/panel`): `/newapp` → wybierz
  bota, podaj tytuł, opis, obrazek 640×360 i adres `https://…`.
  Parametr `startapp=zrobsite` otworzy od razu zakładkę ZrobSite.

## 4. Dodaj przyciski do bota

```python
from tars_telegram import main_menu, miniapp_url, card, progress_bar

app = "https://tars-miniapp.trycloudflare.com/"
markup = main_menu(
    panel_url=miniapp_url(app, tars=TARS_URL, zrobsite=ZROBSITE_URL, tab="tars"),
    zrobsite_url=miniapp_url(app, tars=TARS_URL, zrobsite=ZROBSITE_URL, tab="zrobsite"),
)
text = card("Serwer", [("CPU", progress_bar(3, 10))], status="ok")
# dowolna biblioteka: parse_mode="HTML", reply_markup=markup (słownik Bot API)
```

Przyciski `web_app` działają w czatach prywatnych. Callbacki menu to
`menu:status`, `menu:memory`, `menu:zrobsite`, `menu:more`.

## 5. Weryfikacja użytkownika w panelu (opcjonalnie)

Po wczytaniu ramki Mini App wysyła do panelu (tylko do jego originu)
`postMessage({type: "tars:init", initData})`. Panel przekazuje `initData` do
`POST /auth` (JSON `{"initData": "..."}`) i dostaje `200 {"ok": true, "user": {...}}`
albo `401`/`403`. Wywołania z przeglądarki panelu wymagają dopisania jego
originu do `TARS_MINIAPP_CORS`. W Pythonie to samo robi
`validate_init_data(init_data, bot_token)`.
