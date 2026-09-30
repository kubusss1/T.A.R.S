"""Klient REST wtyczki TARS Bridge (namespace tars/v1).

Funkcje nigdy nie rzucają wyjątków sieciowych — zwracają
{"ok": True, "data": {...}} albo {"ok": False, "error": "<komunikat po polsku>"},
żeby jedna niedziałająca strona nie psuła panelu.
"""
from __future__ import annotations

import ipaddress
import json
import socket
import ssl
import urllib.error
import urllib.request
from urllib.parse import urlencode, urlparse

API_PATH = "/wp-json/tars/v1"
USER_AGENT = "TARS-ZrobSite/1.0 (+https://zrobsite.pl)"
MAX_RESPONSE_BYTES = 5 * 1024 * 1024


def api_base(site: dict) -> str:
    """Bazowy adres API strony (można nadpisać polem "api_base")."""
    return (site.get("api_base") or (str(site.get("url", "")).rstrip("/") + API_PATH)).rstrip("/")


def endpoint_url(site: dict, endpoint: str, params: dict | None = None) -> str:
    url = f"{api_base(site)}/{endpoint.lstrip('/')}"
    if params:
        url += ("&" if "?" in url else "?") + urlencode(params)
    return url


def _is_loopback(host: str | None) -> bool:
    if not host:
        return False
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


KEY_HEADER = "X-tars-key"  # tak urllib zapisuje nagłówek "X-TARS-Key" (str.capitalize)


class _KeySafeRedirect(urllib.request.HTTPRedirectHandler):
    """Przekierowanie na inny host lub z https na http nie dostaje klucza API.

    Domyślnie urllib kopiuje wszystkie nagłówki (także X-TARS-Key) do nowego adresu.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None:
            old_p, new_p = urlparse(req.full_url), urlparse(new.full_url)
            downgrade = old_p.scheme == "https" and new_p.scheme != "https"
            if downgrade or (old_p.hostname or "").lower() != (new_p.hostname or "").lower():
                new.remove_header(KEY_HEADER)
        return new


def _opener(url: str, verify_ssl: bool = True) -> urllib.request.OpenerDirector:
    handlers: list = [_KeySafeRedirect()]
    if _is_loopback(urlparse(url).hostname):
        handlers.append(urllib.request.ProxyHandler({}))  # localhost nigdy przez proxy
    if url.lower().startswith("https://"):
        context = ssl.create_default_context()
        if not verify_ssl:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        handlers.append(urllib.request.HTTPSHandler(context=context))
    return urllib.request.build_opener(*handlers)


def _error(message: str, **extra) -> dict:
    result = {"ok": False, "error": message}
    result.update(extra)
    return result


def _request_json(site: dict, endpoint: str, params: dict | None = None, timeout: float = 10) -> dict:
    if not site.get("url") and not site.get("api_base"):
        return _error("Brak adresu strony w konfiguracji.")
    if not site.get("key"):
        return _error("Brak klucza API w konfiguracji strony.")
    url = endpoint_url(site, endpoint, params)
    request = urllib.request.Request(
        url,
        headers={
            "X-TARS-Key": str(site["key"]),
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
            "Cache-Control": "no-cache",
        },
        method="GET",
    )
    try:
        opener = _opener(url, verify_ssl=site.get("verify_ssl", True) is not False)
        with opener.open(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            status = response.status
    except urllib.error.HTTPError as exc:
        code = exc.code
        try:
            exc.close()
        except Exception:  # pragma: no cover - zamknięcie best-effort
            pass
        if code == 401:
            return _error("Nieprawidłowy klucz API (401) — sprawdź klucz w sites.json.", status=code)
        if code == 403:
            return _error("Dostęp zablokowany (403) — firewall lub wtyczka bezpieczeństwa blokuje API.", status=code)
        if code == 404:
            return _error("Nie znaleziono API (404) — czy wtyczka TARS Bridge jest aktywna?", status=code)
        if code == 429:
            return _error("Za dużo zapytań (429) — spróbuj za chwilę.", status=code)
        if code >= 500:
            return _error(f"Błąd serwera strony ({code}).", status=code)
        return _error(f"Błąd HTTP {code}.", status=code)
    except urllib.error.URLError as exc:
        reason = exc.reason
        if isinstance(reason, (socket.timeout, TimeoutError)):
            return _error(f"Strona nie odpowiedziała w ciągu {timeout:g} s.")
        if isinstance(reason, ssl.SSLCertVerificationError):
            return _error("Błąd certyfikatu SSL strony (nieważny lub wygasły).")
        if isinstance(reason, socket.gaierror):
            return _error("Nie można odnaleźć domeny (DNS).")
        if isinstance(reason, ConnectionRefusedError):
            return _error("Połączenie odrzucone — serwer strony nie działa.")
        return _error(f"Strona nie odpowiada: {reason}")
    except (socket.timeout, TimeoutError):
        return _error(f"Strona nie odpowiedziała w ciągu {timeout:g} s.")
    except ssl.SSLError:
        return _error("Błąd połączenia SSL ze stroną.")
    except (OSError, ValueError) as exc:
        return _error(f"Błąd połączenia: {exc}")

    if len(raw) > MAX_RESPONSE_BYTES:
        return _error("Odpowiedź strony jest zbyt duża.")
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _error("Nieprawidłowa odpowiedź (to nie jest JSON) — sprawdź, czy strona nie zwraca błędu PHP.")
    if not isinstance(data, dict):
        return _error("Nieoczekiwany format odpowiedzi API.")
    return {"ok": True, "status": status, "data": data}


def fetch_status(site: dict, timeout: float = 10) -> dict:
    """GET /status — kondycja strony, aktualizacje, SSL."""
    return _request_json(site, "status", timeout=timeout)


def fetch_analytics(site: dict, days: int = 30, timeout: float = 10) -> dict:
    """GET /analytics?days=N — odsłony, odwiedzający, zgody cookie."""
    days = max(1, min(365, int(days)))
    return _request_json(site, "analytics", params={"days": days}, timeout=timeout)


def fetch_site(site: dict, days: int = 60, timeout: float = 10) -> dict:
    """Status + analityka jednej strony (domyślny fetcher dashboardu).

    60 dni pozwala policzyć zmianę 30 dni względem poprzednich 30 dni.
    """
    status = fetch_status(site, timeout=timeout)
    if not status["ok"] and "status" not in status:
        # Strona w ogóle nie odpowiada — nie czekamy drugi raz na timeout.
        analytics = _error(status["error"])
    else:
        analytics = fetch_analytics(site, days=days, timeout=timeout)
    return {"status": status, "analytics": analytics}
