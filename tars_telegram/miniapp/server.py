"""Mały serwer Mini App TARS (tylko biblioteka standardowa).

Uruchomienie::

    python -m tars_telegram.miniapp.server --port 8765

Serwuje wyłącznie ``index.html`` (pod ``/`` i ``/index.html``), ``/health``
oraz ``POST /auth`` — weryfikację ``initData`` z Telegrama (HMAC-SHA256).

Zmienne środowiskowe:

* ``TARS_BOT_TOKEN`` (lub ``TELEGRAM_BOT_TOKEN``) — token bota, potrzebny do /auth,
* ``TARS_ALLOWED_USER_IDS`` — lista ID użytkowników Telegrama (po przecinku);
  gdy ustawiona, /auth wpuszcza tylko ich,
* ``TARS_MINIAPP_TARS_URL`` / ``TARS_MINIAPP_ZROBSITE_URL`` — domyślne adresy
  paneli (parametry ``?tars=`` / ``?zrobsite=`` w linku mają pierwszeństwo),
* ``TARS_MINIAPP_CORS`` — originy (po przecinku), którym wolno wołać /auth z przeglądarki,
* ``TARS_MINIAPP_HOST`` / ``TARS_MINIAPP_PORT`` — domyślnie 127.0.0.1:8765.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import ipaddress
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit

INDEX_PATH = Path(__file__).resolve().with_name("index.html")
CONFIG_PLACEHOLDER = "/*__TARS_CONFIG__*/null"
MAX_BODY = 16 * 1024
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765

CSP = ("default-src 'none'; script-src 'unsafe-inline' https://telegram.org; "
       "style-src 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; "
       "frame-src https: http:; base-uri 'none'; form-action 'none'")


# --------------------------------------------------------------------------
# initData (https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app)
# --------------------------------------------------------------------------

def _secret_key(bot_token: str) -> bytes:
    return hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()


def _data_check_string(pairs: Iterable[tuple[str, str]]) -> str:
    return "\n".join(f"{k}={v}" for k, v in sorted(pairs))


def _sign(pairs: Iterable[tuple[str, str]], bot_token: str) -> str:
    dcs = _data_check_string(pairs).encode("utf-8")
    return hmac.new(_secret_key(bot_token), dcs, hashlib.sha256).hexdigest()


def sign_init_data(fields: dict[str, Any], bot_token: str) -> str:
    """Tworzy podpisane ``initData`` (do testów i lokalnego developmentu)."""
    pairs = []
    for key, value in fields.items():
        if key == "hash":
            continue
        if not isinstance(value, str):
            value = json.dumps(value, separators=(",", ":"), ensure_ascii=False)
        pairs.append((key, value))
    return urlencode(pairs + [("hash", _sign(pairs, bot_token))])


def validate_init_data(init_data: str, bot_token: str, max_age: int | None = 86400,
                       *, now: float | None = None) -> dict | None:
    """Sprawdza podpis ``Telegram.WebApp.initData``.

    Zwraca słownik pól (``user``/``receiver``/``chat`` zdekodowane z JSON,
    ``auth_date`` jako ``int``) albo ``None``, gdy dane są podrobione,
    uszkodzone lub starsze niż ``max_age`` sekund (``None``/0 = bez limitu).
    """
    if not init_data or not bot_token or not isinstance(init_data, str):
        return None
    try:
        pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        return None
    keys = [k for k, _ in pairs]
    if len(keys) != len(set(keys)):
        return None
    data = dict(pairs)
    received = data.pop("hash", "")
    if not received:
        return None
    expected = _sign(data.items(), bot_token)
    if not hmac.compare_digest(expected.encode("ascii"),
                               received.lower().encode("utf-8", "replace")):
        return None
    try:
        auth_date = int(data["auth_date"])
    except (KeyError, ValueError):
        return None
    now = time.time() if now is None else now
    if auth_date > now + 300:  # z przyszłości (tolerancja zegara 5 min)
        return None
    if max_age and now - auth_date > max_age:
        return None
    result: dict[str, Any] = dict(data)
    result["auth_date"] = auth_date
    for key in ("user", "receiver", "chat"):
        if key in result:
            try:
                result[key] = json.loads(result[key])
            except ValueError:
                return None
    return result


# --------------------------------------------------------------------------
# Adresy paneli
# --------------------------------------------------------------------------

def _is_private_host(host: str) -> bool:
    host = (host or "").lower().strip("[]")
    if host == "localhost" or host.endswith((".localhost", ".local", ".lan")):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    if ip.is_loopback or ip.is_private:
        return True
    return ip.version == 4 and ip in ipaddress.ip_network("100.64.0.0/10")  # Tailscale


def validate_panel_url(url: Any) -> str | None:
    """Ta sama reguła co w index.html: https:// albo http:// tylko w sieci lokalnej."""
    if not isinstance(url, str) or not url.strip():
        return None
    url = url.strip()
    try:
        parts = urlsplit(url)
        host = parts.hostname
    except ValueError:
        return None
    if not host or parts.username or parts.password:
        return None
    if parts.scheme == "https":
        return url
    if parts.scheme == "http" and _is_private_host(host):
        return url
    return None


def _js_json(obj: Any) -> str:
    """JSON bezpieczny do wklejenia w ``<script>``."""
    s = json.dumps(obj, ensure_ascii=False)
    for ch, rep in (("<", "\\u003c"), (">", "\\u003e"), ("&", "\\u0026"),
                    (" ", "\\u2028"), (" ", "\\u2029")):
        s = s.replace(ch, rep)
    return s


# --------------------------------------------------------------------------
# Serwer HTTP
# --------------------------------------------------------------------------

class MiniAppServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], *, bot_token: str | None = None,
                 max_age: int = 86400, allowed_user_ids: Iterable[int] | None = None,
                 cors_origins: Iterable[str] | None = None,
                 panel_urls: dict[str, str | None] | None = None,
                 index_path: Path = INDEX_PATH, verbose: bool = False) -> None:
        self.bot_token = bot_token or None
        self.max_age = max_age
        self.allowed_user_ids = {int(x) for x in (allowed_user_ids or [])}
        self.cors_origins = {o.rstrip("/") for o in (cors_origins or []) if o}
        self.panel_urls = {k: validate_panel_url(v) for k, v in (panel_urls or {}).items()}
        self.index_path = Path(index_path)
        self.verbose = verbose
        super().__init__(address, MiniAppHandler)

    def render_index(self) -> bytes:
        page = self.index_path.read_text(encoding="utf-8")
        config = {k: v for k, v in self.panel_urls.items() if v}
        page = page.replace(CONFIG_PLACEHOLDER, _js_json(config), 1)
        return page.encode("utf-8")


class MiniAppHandler(BaseHTTPRequestHandler):
    server: MiniAppServer
    server_version = "TARS-MiniApp/1.0"
    sys_version = ""
    timeout = 15  # s — wolny/niedokończony klient nie blokuje wątku w nieskończoność

    # --- pomocnicze ---
    def _send(self, status: int, body: bytes, ctype: str, head: bool = False,
              headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if not head:
            self.wfile.write(body)

    def _json(self, status: int, obj: Any, head: bool = False,
              headers: dict[str, str] | None = None) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8", head, headers)

    def _cors(self) -> dict[str, str]:
        origin = (self.headers.get("Origin") or "").rstrip("/")
        if origin and origin in self.server.cors_origins:
            return {"Access-Control-Allow-Origin": origin, "Vary": "Origin",
                    "Access-Control-Allow-Methods": "POST, OPTIONS",
                    "Access-Control-Allow-Headers": "Content-Type"}
        return {}

    def _path(self) -> str:
        return urlsplit(self.path).path

    # --- metody ---
    def do_GET(self) -> None:  # noqa: N802
        self._route(head=False)

    def do_HEAD(self) -> None:  # noqa: N802
        self._route(head=True)

    def _route(self, head: bool) -> None:
        path = self._path()
        if path in ("/", "/index.html"):
            try:
                body = self.server.render_index()
            except OSError:
                self._json(500, {"ok": False, "error": "Brak pliku index.html"}, head)
                return
            self._send(200, body, "text/html; charset=utf-8", head,
                       {"Content-Security-Policy": CSP})
        elif path == "/health":
            self._json(200, {"ok": True, "service": "tars-miniapp",
                             "auth": bool(self.server.bot_token)}, head)
        elif path == "/auth":
            self._json(405, {"ok": False, "error": "Użyj POST"}, head, {"Allow": "POST"})
        else:
            self._json(404, {"ok": False, "error": "Nie znaleziono"}, head)

    def do_OPTIONS(self) -> None:  # noqa: N802
        if self._path() == "/auth":
            self._send(204, b"", "text/plain", headers=self._cors())
        else:
            self._json(404, {"ok": False, "error": "Nie znaleziono"})

    def do_POST(self) -> None:  # noqa: N802
        cors = self._cors()
        if self._path() != "/auth":
            self._json(404, {"ok": False, "error": "Nie znaleziono"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length < 0 or length > MAX_BODY:
            self._json(413, {"ok": False, "error": "Za duże zapytanie"}, headers=cors)
            return
        try:
            raw = self.rfile.read(length).decode("utf-8", "replace").strip()
        except OSError:  # m.in. TimeoutError — klient nie dosłał treści
            self.close_connection = True
            return
        init_data = raw
        if raw.startswith("{"):
            try:
                obj = json.loads(raw)
                init_data = str(obj.get("initData") or obj.get("init_data") or "")
            except (ValueError, AttributeError):
                init_data = ""
        if not self.server.bot_token:
            self._json(503, {"ok": False, "error": "Serwer nie ma ustawionego TARS_BOT_TOKEN"},
                       headers=cors)
            return
        data = validate_init_data(init_data, self.server.bot_token, self.server.max_age)
        if data is None:
            self._json(401, {"ok": False, "error": "Nieprawidłowe lub przeterminowane initData"},
                       headers=cors)
            return
        user = data.get("user") if isinstance(data.get("user"), dict) else {}
        allowed = self.server.allowed_user_ids
        if allowed and user.get("id") not in allowed:
            self._json(403, {"ok": False, "error": "Brak dostępu dla tego konta"}, headers=cors)
            return
        self._json(200, {"ok": True, "user": user, "auth_date": data["auth_date"],
                         "start_param": data.get("start_param")}, headers=cors)

    def log_message(self, fmt: str, *args: Any) -> None:
        if self.server.verbose:
            sys.stderr.write("[miniapp] " + (fmt % args) + "\n")


def _env_list(name: str) -> list[str]:
    return [x.strip() for x in os.environ.get(name, "").split(",") if x.strip()]


def make_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, **kwargs: Any) -> MiniAppServer:
    """Tworzy serwer; brakujące ustawienia bierze ze zmiennych środowiskowych."""
    if "bot_token" not in kwargs:
        kwargs["bot_token"] = os.environ.get("TARS_BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN")
    if "allowed_user_ids" not in kwargs:
        kwargs["allowed_user_ids"] = [int(x) for x in _env_list("TARS_ALLOWED_USER_IDS") if x.isdigit()]
    if "cors_origins" not in kwargs:
        kwargs["cors_origins"] = _env_list("TARS_MINIAPP_CORS")
    if "panel_urls" not in kwargs:
        kwargs["panel_urls"] = {"tars": os.environ.get("TARS_MINIAPP_TARS_URL"),
                                "zrobsite": os.environ.get("TARS_MINIAPP_ZROBSITE_URL")}
    return MiniAppServer((host, int(port)), **kwargs)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Serwer Mini App TARS")
    parser.add_argument("--host", default=os.environ.get("TARS_MINIAPP_HOST", DEFAULT_HOST))
    parser.add_argument("--port", type=int,
                        default=int(os.environ.get("TARS_MINIAPP_PORT", DEFAULT_PORT)))
    parser.add_argument("--verbose", action="store_true", help="loguj zapytania")
    args = parser.parse_args(argv)
    server = make_server(args.host, args.port, verbose=args.verbose)
    host, port = server.server_address[:2]
    print(f"Mini App TARS: http://{host}:{port}/  (Ctrl+C = stop)")
    if not server.bot_token:
        print("Uwaga: brak TARS_BOT_TOKEN - POST /auth zwróci 503.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
