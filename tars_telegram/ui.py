"""Ładne wiadomości Telegrama dla TARS — niezależne od biblioteki bota.

Wszystko tutaj zwraca zwykłe napisy (``str``) w formacie HTML Telegrama
(``parse_mode="HTML"``) albo słowniki klawiatur w formacie Bot API, gotowe do
``json.dumps`` / przekazania jako ``reply_markup`` w dowolnej bibliotece
(python-telegram-bot, aiogram, pyTelegramBotAPI, surowe ``urllib``).

Zasada ucieczki (escaping): funkcje przyjmujące *tekst* zawsze go escapują.
Wyniki funkcji z tego modułu są typu :class:`Html` (podklasa ``str``) i przy
składaniu nie są escapowane drugi raz. Własny, już bezpieczny HTML można
oznaczyć ręcznie: ``Html("<b>ok</b>")``.
"""

from __future__ import annotations

import html as _html
import re
from typing import Any, Iterable, Sequence
from urllib.parse import urlencode, urlsplit

__all__ = [
    "Html", "esc", "tg_len",
    "header", "kv", "status_dot", "progress_bar", "section", "bullet_list",
    "code", "pre", "spoiler", "link", "safe_url", "divider", "footer", "card",
    "chunk_message", "strip_think", "md_to_tg_html",
    "CALLBACK_DATA_MAX", "check_callback_data", "button", "inline_keyboard",
    "merge_keyboards", "main_menu", "pager", "sort_menu", "parse_callback",
    "miniapp_url", "menu_button_web_app",
    "tpl_ai_answer", "tpl_error", "tpl_status", "tpl_memory_sorted", "plural",
]

TELEGRAM_LIMIT = 4096
CALLBACK_DATA_MAX = 64


# --------------------------------------------------------------------------
# Podstawy
# --------------------------------------------------------------------------

class Html(str):
    """Napis, który jest już bezpiecznym HTML-em Telegrama (nie escapujemy)."""

    __slots__ = ()


def esc(text: Any) -> str:
    """Escapuje ``&``, ``<`` i ``>`` (tyle wymaga HTML Telegrama)."""
    if text is None:
        return ""
    return _html.escape(str(text), quote=False)


def _h(value: Any) -> str:
    """Tekst → escapowany; :class:`Html` → bez zmian."""
    if value is None:
        return ""
    if isinstance(value, Html):
        return str(value)
    return esc(value)


def tg_len(text: str) -> int:
    """Długość tak, jak liczy ją Telegram (jednostki UTF-16)."""
    return len(str(text).encode("utf-16-le", "surrogatepass")) // 2


# --------------------------------------------------------------------------
# Klocki
# --------------------------------------------------------------------------

def header(title: Any, emoji: str | None = None) -> Html:
    """Nagłówek: ``📊 <b>Tytuł</b>``."""
    t = f"<b>{_h(title)}</b>"
    return Html(f"{esc(emoji)} {t}" if emoji else t)


_NBSP = " "


def kv(rows: Iterable[tuple[Any, Any]], max_key_width: int = 16) -> Html:
    """Wyrównane linie klucz/wartość.

    Klucze są w ``<code>`` (czcionka o stałej szerokości), dopełnione twardymi
    spacjami, więc wartości zaczynają się w jednej kolumnie.
    """
    rows = [(str(k), v) for k, v in rows]
    if not rows:
        return Html("")
    width = min(max(len(k) for k, _ in rows), max_key_width)
    lines = []
    for key, value in rows:
        if len(key) > width:
            key = key[: max(1, width - 1)] + "…"
        padded = esc(key) + _NBSP * (width - len(key))
        lines.append(f"<code>{padded}</code>{_NBSP}{_NBSP}{_h(value)}")
    return Html("\n".join(lines))


_DOTS = {"ok": "🟢", "warning": "🟡", "critical": "🔴", "unknown": "⚪"}
_LEVEL_ALIASES = {
    "ok": "ok", "up": "ok", "green": "ok", "good": "ok", "healthy": "ok",
    "online": "ok", "success": "ok", "running": "ok", "działa": "ok",
    "warning": "warning", "warn": "warning", "yellow": "warning",
    "degraded": "warning", "slow": "warning", "ostrzeżenie": "warning",
    "critical": "critical", "crit": "critical", "error": "critical",
    "err": "critical", "down": "critical", "fail": "critical",
    "failed": "critical", "red": "critical", "offline": "critical",
    "błąd": "critical",
    "unknown": "unknown", "none": "unknown", "?": "unknown",
}
_SEVERITY = {"critical": 0, "warning": 1, "unknown": 2, "ok": 3}


def _level(level: Any) -> str:
    if level is True:
        return "ok"
    if level is False:
        return "critical"
    if level is None:
        return "unknown"
    return _LEVEL_ALIASES.get(str(level).strip().lower(), "unknown")


def status_dot(level: Any) -> str:
    """🟢 ok · 🟡 warning · 🔴 critical · ⚪ unknown (plus popularne aliasy)."""
    return _DOTS[_level(level)]


def progress_bar(value: Any, total: Any, width: int = 10) -> Html:
    """``▰▰▰▱▱▱▱▱▱▱ 30%`` — odporny na total=0, ujemne i > total."""
    width = max(1, int(width))
    try:
        v, t = float(value), float(total)
    except (TypeError, ValueError):
        v, t = 0.0, 0.0
    if t <= 0 or v != v or t != t:  # zero / NaN
        ratio = 0.0
    else:
        ratio = min(max(v / t, 0.0), 1.0)
    filled = int(round(ratio * width))
    if 0 < ratio < 1:
        filled = min(max(filled, 1), width - 1) if width > 1 else filled
    pct = int(round(ratio * 100))
    if ratio < 1 and pct == 100:
        pct = 99
    return Html(f"{'▰' * filled}{'▱' * (width - filled)} {pct}%")


def section(title: Any, body: Any) -> Html:
    """Pogrubiony tytuł i treść pod spodem."""
    return Html(f"<b>{_h(title)}</b>\n{_h(body)}")


def bullet_list(items: Iterable[Any], bullet: str = "•") -> Html:
    """Lista punktowana; zagnieżdżona lista/krotka → wcięte ``◦``."""
    lines = []
    for item in items:
        if isinstance(item, (list, tuple)):
            lines.extend(f"{_NBSP * 3}◦ {_h(sub)}" for sub in item)
        else:
            lines.append(f"{bullet} {_h(item)}")
    return Html("\n".join(lines))


def code(text: Any) -> Html:
    return Html(f"<code>{esc(text)}</code>")


def pre(text: Any, lang: str | None = None) -> Html:
    lang = re.sub(r"[^A-Za-z0-9_+#.-]", "", lang or "")[:32]
    if lang:
        return Html(f'<pre><code class="language-{lang}">{esc(text)}</code></pre>')
    return Html(f"<pre>{esc(text)}</pre>")


def spoiler(text: Any) -> Html:
    return Html(f"<tg-spoiler>{_h(text)}</tg-spoiler>")


_ALLOWED_SCHEMES = {"http", "https", "tg"}


def safe_url(url: Any) -> str | None:
    """Zwraca URL, jeśli to http/https/tg; w przeciwnym razie ``None``."""
    if not isinstance(url, str):
        return None
    u = url.strip()
    if not u or any(ord(c) < 33 or ord(c) == 127 for c in u):
        return None
    m = re.match(r"([A-Za-z][A-Za-z0-9+.-]*):", u)
    if not m or m.group(1).lower() not in _ALLOWED_SCHEMES:
        return None
    if m.group(1).lower() in ("http", "https"):
        try:
            if not urlsplit(u).netloc:
                return None
        except ValueError:
            return None
    return u


def link(text: Any, url: Any) -> Html:
    """Link ``<a>``; niedozwolony schemat (np. ``javascript:``) → sam tekst."""
    label = _h(text) if text not in (None, "") else esc(url)
    u = safe_url(url)
    if u is None:
        return Html(label)
    return Html(f'<a href="{_html.escape(u, quote=True)}">{label}</a>')


def divider(width: int = 16) -> Html:
    return Html("┈" * max(1, int(width)))


def footer(text: Any) -> Html:
    return Html(f"<i>{_h(text)}</i>")


_footer = footer


def card(title: Any, rows: Any = None, status: Any = None,
         footer: Any = None) -> Html:
    """Kompletna „karta”: nagłówek (+ kropka statusu), linia, treść, stopka.

    ``rows`` — lista par (klucz, wartość) → :func:`kv`; albo gotowa treść.
    """
    parts = [header(title, status_dot(status) if status is not None else None)]
    parts.append(divider())
    if rows:
        if isinstance(rows, str):
            parts.append(_h(rows))
        else:
            rows = list(rows)
            if all(isinstance(r, (tuple, list)) and len(r) == 2 for r in rows):
                parts.append(kv(rows))
            else:
                parts.append("\n".join(_h(r) for r in rows))
    out = "\n".join(parts)
    if footer:
        out += "\n\n" + _footer(footer)
    return Html(out)


# --------------------------------------------------------------------------
# Dzielenie długich wiadomości
# --------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"<[^<>]*>|&(?:#\d+|#[xX][0-9a-fA-F]+|[a-zA-Z]+);")
_TAG_RE = re.compile(r"<\s*(/)?\s*([a-zA-Z][a-zA-Z0-9-]*)[^>]*?(/)?\s*>$", re.S)
_PRE_TAGS = ("pre", "code")


def _atoms(s: str) -> list[tuple[str, str, str | None]]:
    """Rozbija HTML na niepodzielne kawałki: tagi, encje, pojedyncze znaki."""
    out: list[tuple[str, str, str | None]] = []
    pos = 0
    for m in _TOKEN_RE.finditer(s):
        out.extend(("t", ch, None) for ch in s[pos:m.start()])
        tok = m.group(0)
        tm = _TAG_RE.match(tok) if tok.startswith("<") else None
        if tm is None or tm.group(3):
            out.append(("t", tok, None))
        elif tm.group(1):
            out.append(("c", tok, tm.group(2).lower()))
        else:
            out.append(("o", tok, tm.group(2).lower()))
        pos = m.end()
    out.extend(("t", ch, None) for ch in s[pos:])
    return out


def _open_str(stack: tuple) -> str:
    return "".join(raw for _, raw in stack)


def _close_str(stack: tuple) -> str:
    return "".join(f"</{name}>" for name, _ in reversed(stack))


def _closers_len(stack: tuple) -> int:
    return sum(len(name) + 3 for name, _ in stack)


def chunk_message(html_text: Any, limit: int = TELEGRAM_LIMIT) -> list[str]:
    """Dzieli HTML na części ≤ ``limit`` (liczone jak w Telegramie).

    Tnie najchętniej na pustej linii, potem na końcu linii, potem na spacji;
    nigdy w środku tagu ani encji. Otwarte tagi są zamykane na końcu części
    i otwierane ponownie na początku następnej.
    """
    if limit < 32:
        raise ValueError("limit musi wynosić co najmniej 32 znaki")
    text = str(html_text or "")
    if not text.strip():
        return []
    if tg_len(text) <= limit:
        return [text]

    atoms = _atoms(text)
    chunks: list[str] = []
    start_stack: tuple = ()
    stack: tuple = ()
    plen = 0
    parts: list[str] = []
    gidx: list[int] = []
    blen = 0
    cands: list[tuple[int, int, int, tuple]] = []

    def flush(kparts: list[str], end_stack: tuple) -> None:
        kparts = list(kparts)
        while kparts and kparts[-1] in (" ", "\n"):
            kparts.pop()
        chunk = _open_str(start_stack) + "".join(kparts) + _close_str(end_stack)
        if re.sub(r"<[^<>]*>", "", chunk).strip():
            chunks.append(chunk)

    i, n = 0, len(atoms)
    while i < n:
        kind, tok, name = atoms[i]
        if not parts and kind == "t":
            in_pre = any(nm in _PRE_TAGS for nm, _ in stack)
            if tok == "\n" or (tok == " " and not in_pre):
                i += 1
                continue
        new_stack = stack
        if kind == "o":
            new_stack = stack + ((name, tok),)
        elif kind == "c":
            names = [nm for nm, _ in stack]
            if name not in names:
                i += 1  # zabłąkany tag zamykający — pomijamy
                continue
            j = len(names) - 1 - names[::-1].index(name)
            new_stack = stack[:j]
        size = tg_len(tok)
        if plen + blen + size + _closers_len(new_stack) <= limit:
            parts.append(tok)
            gidx.append(i)
            blen += size
            stack = new_stack
            if kind == "t" and tok in ("\n", " "):
                if tok == "\n":
                    prio = 3 if len(parts) >= 2 and parts[-2] == "\n" else 2
                else:
                    prio = 1
                cands.append((prio, len(parts), blen, stack))
            i += 1
            continue

        # Nie mieści się — trzeba ciąć.
        if not parts:
            if start_stack:
                start_stack, stack, plen = (), (), 0
                continue
            raise ValueError("pojedynczy element HTML jest dłuższy niż limit")
        half = (limit - plen) * 0.5
        good = [c for c in cands if c[2] >= half]
        if good:
            best = max(good, key=lambda c: (c[0], c[1]))
        elif cands:
            best = max(cands, key=lambda c: c[1])
        else:
            best = (0, len(parts), blen, stack)
        _, k, _, cut_stack = best
        flush(parts[:k], cut_stack)
        if k < len(gidx):
            i = gidx[k]
        start_stack = stack = cut_stack
        plen = tg_len(_open_str(cut_stack))
        parts, gidx, blen, cands = [], [], 0, []

    if parts:
        flush(parts, stack)
    return chunks


# --------------------------------------------------------------------------
# Wyjście modeli: <think> i Markdown
# --------------------------------------------------------------------------

def strip_think(text: Any) -> str:
    """Usuwa bloki ``<think>…</think>`` (także niedomknięte / osierocone)."""
    if not text:
        return ""
    s = str(text)
    s = re.sub(r"<think(?:ing)?>.*?</think(?:ing)?>", "", s, flags=re.S | re.I)
    closes = list(re.finditer(r"</think(?:ing)?>", s, flags=re.I))
    if closes:  # szablon dał otwarcie w prompcie — tniemy wszystko przed
        s = s[closes[-1].end():]
    m = re.search(r"<think(?:ing)?>", s, flags=re.I)
    if m:  # myślenie urwane w połowie
        s = s[:m.start()]
    return s.strip()


_PH_RE = re.compile("(\\d+)")
_BALANCE_TAG_RE = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9-]*)[^>]*>")


def _balanced(s: str) -> bool:
    stack: list[str] = []
    for m in _BALANCE_TAG_RE.finditer(s):
        name = m.group(2).lower()
        if m.group(1):
            if not stack or stack.pop() != name:
                return False
        else:
            stack.append(name)
    return not stack


def _inline(s: str) -> str:
    """Formatowanie w linii: kod, linki, pogrubienie, kursywa, przekreślenie."""
    store: list[str] = []
    raw: list[str] = []

    def keep(h: str, original: str) -> str:
        store.append(h)
        raw.append(original)
        return f"{len(store) - 1}"

    def restore(t: str) -> str:
        return _PH_RE.sub(lambda m: store[int(m.group(1))], t)

    def restore_raw(t: str) -> str:
        return _PH_RE.sub(lambda m: raw[int(m.group(1))], t)

    s = s.replace("", "").replace("", "")
    s = re.sub(r"(?<!`)(`{1,2})(?!`)(.+?)(?<!`)\1(?!`)",
               lambda m: keep(code(m.group(2).strip() or m.group(2)), m.group(0)), s)
    s = re.sub(r"\[([^\]\n]+)\]\(\s*<?((?:[^()\s<>]|\([^()\s<>]*\))+)>?(?:\s+\"[^\"]*\")?\s*\)",
               lambda m: keep(link(Html(_inline(restore_raw(m.group(1)))),
                                   restore_raw(m.group(2))), m.group(0)), s)
    plain = s
    s = esc(s)
    s = re.sub(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"(?<!\w)__(?=\S)(.+?)(?<=\S)__(?!\w)", r"<b>\1</b>", s)
    s = re.sub(r"~~(?=\S)(.+?)(?<=\S)~~", r"<s>\1</s>", s)
    s = re.sub(r"\|\|(?=\S)(.+?)(?<=\S)\|\|", r"<tg-spoiler>\1</tg-spoiler>", s)
    s = re.sub(r"(?<![*\w])\*(?=[^\s*])(.+?)(?<=[^\s*])\*(?![*\w])", r"<i>\1</i>", s)
    s = re.sub(r"(?<!\w)_(?=[^\s_])(.+?)(?<=[^\s_])_(?!\w)", r"<i>\1</i>", s)
    if not _balanced(s):  # np. „**a *b** c*” — lepiej bez formatowania niż błąd API
        s = esc(plain)
    return restore(s)


_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


def _table(lines: list[str]) -> str:
    rows = []
    for line in lines:
        cells = line.strip().strip("|").split("|")
        rows.append([re.sub(r"\*\*|__|`", "", c).strip() for c in cells])
    cols = max(len(r) for r in rows)
    rows = [r + [""] * (cols - len(r)) for r in rows]
    widths = [max(len(r[c]) for r in rows) for c in range(cols)]
    out = ["  ".join(r[c].ljust(widths[c]) for c in range(cols)).rstrip() for r in rows]
    if len(out) > 1:
        out.insert(1, "  ".join("─" * w for w in widths))
    return pre("\n".join(out))


def md_to_tg_html(text: Any) -> Html:
    """Zamienia typowy Markdown z LLM-a na bezpieczny HTML Telegrama.

    Obsługuje: ``**pogrubienie**``, ``*kursywę*``/``_kursywę_``, ``~~skreślenie~~``,
    ```` `kod` ````, bloki `````` ```lang``` ``````, nagłówki ``#`` → pogrubienie,
    listy ``-``/``*`` → ``•``, ``[tekst](url)``, cytaty ``>``, tabele ``|…|``,
    linie ``---``. Cała reszta jest escapowana.
    """
    if not text:
        return Html("")
    lines = str(text).replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        fm = re.match(r"^\s*(`{3,}|~{3,})\s*([\w+#.-]*)[^`]*$", line)
        if fm:
            fence = fm.group(1)
            close_re = re.compile(r"^\s*" + re.escape(fence[0]) + "{%d,}\\s*$" % len(fence))
            buf = []
            i += 1
            while i < len(lines) and not close_re.match(lines[i]):
                buf.append(lines[i])
                i += 1
            i += 1
            out.append(pre("\n".join(buf), fm.group(2) or None))
            continue
        if _TABLE_ROW.match(line) and i + 1 < len(lines) and _TABLE_SEP.match(lines[i + 1]):
            rows = [line]
            i += 2
            while i < len(lines) and _TABLE_ROW.match(lines[i]):
                rows.append(lines[i])
                i += 1
            out.append(_table(rows))
            continue
        if re.match(r"^\s{0,3}>", line):
            buf = []
            while i < len(lines) and re.match(r"^\s{0,3}>", lines[i]):
                buf.append(_inline(re.sub(r"^\s{0,3}>\s?", "", lines[i])))
                i += 1
            out.append("<blockquote>" + "\n".join(buf).strip() + "</blockquote>")
            continue
        i += 1
        hm = re.match(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$", line)
        if hm:
            title = re.sub(r"\*\*|__", "", hm.group(2))
            out.append(f"<b>{_inline(title)}</b>")
            continue
        if re.match(r"^\s{0,3}([-*_])(\s*\1){2,}\s*$", line):
            out.append(divider())
            continue
        lm = re.match(r"^(\s*)[-*+]\s+(.*)$", line)
        if lm:
            indent = len(lm.group(1).expandtabs(4))
            item = lm.group(2)
            tm = re.match(r"^\[([ xX])\]\s+(.*)$", item)
            if tm:
                bullet = "☑" if tm.group(1).lower() == "x" else "☐"
                item = tm.group(2)
            else:
                bullet = "•" if indent == 0 else "◦"
            pad = _NBSP * (0 if indent == 0 else (3 if indent <= 4 else 6))
            out.append(f"{pad}{bullet} {_inline(item)}")
            continue
        nm = re.match(r"^(\s*)(\d{1,3})[.)]\s+(.*)$", line)
        if nm:
            pad = _NBSP * (3 if nm.group(1) else 0)
            out.append(f"{pad}{nm.group(2)}. {_inline(nm.group(3))}")
            continue
        out.append(_inline(line.rstrip()))
    result = "\n".join(out)
    result = re.sub(r"\n{3,}", "\n\n", result).strip()
    return Html(result)


# --------------------------------------------------------------------------
# Klawiatury (format Bot API, zwykłe słowniki)
# --------------------------------------------------------------------------

_BUTTON_ACTIONS = ("callback_data", "url", "web_app", "switch_inline_query",
                   "switch_inline_query_current_chat", "copy_text", "pay",
                   "login_url", "callback_game", "switch_inline_query_chosen_chat")


def check_callback_data(data: Any) -> str:
    """Sprawdza, czy ``callback_data`` ma 1–64 bajty UTF-8 (limit Telegrama)."""
    if not isinstance(data, str) or not data:
        raise ValueError("callback_data musi być niepustym napisem")
    size = len(data.encode("utf-8"))
    if size > CALLBACK_DATA_MAX:
        raise ValueError(
            f"callback_data ma {size} bajtów (limit {CALLBACK_DATA_MAX}): {data[:40]!r}…")
    return data


def _check_web_app_url(url: Any) -> str:
    u = safe_url(url)
    if u is None or not u.lower().startswith("https://"):
        raise ValueError(f"Mini App wymaga adresu https://, podano: {url!r}")
    return u


def button(text: str, callback_data: str | None = None, *, url: str | None = None,
           web_app: str | None = None, **extra: Any) -> dict:
    """Jeden przycisk inline. Dokładnie jedna akcja: callback / url / web_app / …"""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("przycisk musi mieć tekst")
    btn: dict[str, Any] = {"text": text}
    if callback_data is not None:
        btn["callback_data"] = check_callback_data(callback_data)
    if url is not None:
        u = safe_url(url)
        if u is None:
            raise ValueError(f"niedozwolony URL przycisku: {url!r}")
        btn["url"] = u
    if web_app is not None:
        btn["web_app"] = {"url": _check_web_app_url(web_app)}
    for key, value in extra.items():
        if key not in _BUTTON_ACTIONS:
            raise ValueError(f"nieznane pole przycisku: {key}")
        btn[key] = value
    actions = [k for k in btn if k in _BUTTON_ACTIONS]
    if len(actions) != 1:
        raise ValueError("przycisk musi mieć dokładnie jedną akcję")
    return btn


def _norm_button(b: Any) -> dict:
    if isinstance(b, dict):
        b = dict(b)
        text = b.pop("text", None)
        web = b.pop("web_app", None)
        if isinstance(web, dict):
            web = web.get("url")
        return button(text, b.pop("callback_data", None), url=b.pop("url", None),
                      web_app=web, **b)
    if isinstance(b, (tuple, list)) and len(b) == 2:
        return button(str(b[0]), str(b[1]))
    raise ValueError(f"nieprawidłowy przycisk: {b!r}")


def inline_keyboard(rows: Iterable[Any]) -> dict:
    """``{"inline_keyboard": [[...], ...]}`` z walidacją.

    Wiersz to lista przycisków; przycisk to słownik Bot API albo krotka
    ``(tekst, callback_data)``. Pojedynczy słownik też może być wierszem.
    """
    out = []
    for row in rows:
        if isinstance(row, dict):
            row = [row]
        buttons = [_norm_button(b) for b in row]
        if buttons:
            out.append(buttons)
    return {"inline_keyboard": out}


def merge_keyboards(*markups: dict | None) -> dict:
    """Skleja kilka klawiatur inline w jedną (np. sortowanie + pager)."""
    rows: list = []
    for mk in markups:
        if mk:
            rows.extend(mk.get("inline_keyboard", []))
    return {"inline_keyboard": rows}


def parse_callback(data: str) -> tuple[str, str]:
    """``"sort:-date"`` → ``("sort", "-date")``."""
    prefix, _, value = (data or "").partition(":")
    return prefix, value


def miniapp_url(base_url: str, tars: str | None = None, zrobsite: str | None = None,
                tab: str | None = None) -> str:
    """Buduje adres Mini App z parametrami ``?tars=…&zrobsite=…&tab=…``."""
    params = [(k, v) for k, v in (("tars", tars), ("zrobsite", zrobsite), ("tab", tab)) if v]
    if not params:
        return base_url
    sep = "&" if "?" in base_url else "?"
    return base_url + sep + urlencode(params)


def menu_button_web_app(text: str, url: str) -> dict:
    """Obiekt ``MenuButtonWebApp`` do ``setChatMenuButton``."""
    return {"type": "web_app", "text": text, "web_app": {"url": _check_web_app_url(url)}}


def main_menu(panel_url: str | None = None, zrobsite_url: str | None = None,
              prefix: str = "menu") -> dict:
    """Główne menu TARS. Z adresami → dodatkowy wiersz przycisków Mini App."""
    rows: list[list[dict]] = [
        [button("📊 Status", f"{prefix}:status"), button("🧠 Pamięć", f"{prefix}:memory")],
        [button("🌐 ZrobSite", f"{prefix}:zrobsite"), button("⚙️ Więcej", f"{prefix}:more")],
    ]
    apps = []
    if panel_url:
        apps.append(button("🖥 Panel TARS", web_app=panel_url))
    if zrobsite_url:
        apps.append(button("🧩 Panel ZrobSite", web_app=zrobsite_url))
    if apps:
        rows.append(apps)
    return {"inline_keyboard": rows}


def pager(page: int, pages: int, prefix: str) -> dict:
    """``◀ 2/5 ▶`` — strony numerowane od 1. Jedna strona → pusta klawiatura."""
    pages = max(1, int(pages))
    page = min(max(1, int(page)), pages)
    if pages <= 1:
        return {"inline_keyboard": []}
    noop = f"{prefix}:noop"
    row = [
        button("◀", f"{prefix}:{page - 1}") if page > 1 else button("·", noop),
        button(f"{page}/{pages}", noop),
        button("▶", f"{prefix}:{page + 1}") if page < pages else button("·", noop),
    ]
    return {"inline_keyboard": [row]}


def _norm_options(options: Any) -> list[tuple[str, str]]:
    if isinstance(options, dict):
        return [(str(k), str(v)) for k, v in options.items()]
    out = []
    for opt in options:
        if isinstance(opt, (tuple, list)) and len(opt) == 2:
            out.append((str(opt[0]), str(opt[1])))
        else:
            out.append((str(opt), str(opt)))
    return out


def sort_menu(current: str | None, options: Any, prefix: str = "sort",
              columns: int = 3, directional: bool = True) -> dict:
    """Menu sortowania; aktywna opcja ma ``✓`` (i strzałkę kierunku).

    ``current`` może mieć minus na początku (``"-date"``) = malejąco. Kliknięcie
    aktywnej opcji odwraca kierunek; nieaktywnej — sortuje rosnąco.
    """
    cur = (current or "").strip()
    desc = cur.startswith("-")
    cur_key = cur.lstrip("-")
    buttons = []
    for key, label in _norm_options(options):
        if key == cur_key:
            arrow = (" ↓" if desc else " ↑") if directional else ""
            data = f"{prefix}:{'' if desc or not directional else '-'}{key}"
            buttons.append(button(f"✓ {label}{arrow}", data))
        else:
            buttons.append(button(label, f"{prefix}:{key}"))
    columns = max(1, int(columns))
    rows = [buttons[i:i + columns] for i in range(0, len(buttons), columns)]
    return {"inline_keyboard": rows}


# --------------------------------------------------------------------------
# Szablony odpowiedzi TARS
# --------------------------------------------------------------------------

def plural(n: int, one: str, few: str, many: str) -> str:
    """Polska odmiana: 1 plik, 2 pliki, 5 plików, 22 pliki, 112 plików."""
    n = abs(int(n))
    if n == 1:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def _fmt_seconds(seconds: float) -> str:
    s = float(seconds)
    if s < 10:
        return f"{s:.1f} s"
    if s < 60:
        return f"{s:.0f} s"
    m, s = divmod(int(round(s)), 60)
    return f"{m} min {s} s" if s else f"{m} min"


def tpl_ai_answer(text: Any, model: str | None = None,
                  seconds: float | None = None) -> Html:
    """Odpowiedź modelu: bez ``<think>``, Markdown → HTML, dyskretna stopka."""
    body = md_to_tg_html(strip_think(text))
    if not body.strip():
        body = Html("<i>(pusta odpowiedź modelu)</i>")
    meta = []
    if model:
        meta.append(esc(model))
    if seconds is not None:
        try:
            meta.append(_fmt_seconds(seconds))
        except (TypeError, ValueError):
            pass
    if meta:
        return Html(f"{body}\n\n<i>{' · '.join(meta)}</i>")
    return Html(body)


def tpl_error(msg: Any, hint: Any = None) -> Html:
    """Przyjazny komunikat błędu z opcjonalną podpowiedzią."""
    if isinstance(msg, BaseException):
        msg = str(msg) or type(msg).__name__
    msg = str(msg or "Nieznany błąd")
    if len(msg) > 1500:
        msg = msg[:1500] + "…"
    out = f"⚠️ <b>Coś poszło nie tak</b>\n{_h(msg)}"
    if hint:
        out += f"\n\n💡 <i>{_h(hint)}</i>"
    return Html(out)


_STATUS_SUMMARY = {
    "ok": "Wszystko działa",
    "warning": "Działa, ale są ostrzeżenia",
    "critical": "Są problemy",
    "unknown": "Brak pełnych danych",
}


def tpl_status(services: Sequence[dict], title: str = "Status TARS",
               updated: Any = None) -> Html:
    """Status usług: podsumowanie + lista (najpierw awarie, potem reszta)."""
    items = []
    for svc in services or []:
        lvl = _level(svc.get("level", svc.get("status")))
        items.append((lvl, str(svc.get("name", "?")), svc.get("detail")))
    parts = [header(title, "📊")]
    if not items:
        parts.append("<i>Brak usług do sprawdzenia.</i>")
        return Html("\n".join(parts))
    worst = min((lvl for lvl, _, _ in items), key=_SEVERITY.__getitem__)
    ok = sum(1 for lvl, _, _ in items if lvl == "ok")
    parts.append(f"{_DOTS[worst]} {_STATUS_SUMMARY[worst]} · {ok}/{len(items)} OK")
    parts.append(divider())
    for lvl, name, detail in sorted(items, key=lambda it: _SEVERITY[it[0]]):
        line = f"{_DOTS[lvl]} <b>{esc(name)}</b>"
        if detail not in (None, ""):
            line += f" — {_h(detail)}"
        parts.append(line)
    out = "\n".join(parts)
    if updated:
        stamp = updated.strftime("%H:%M") if hasattr(updated, "strftime") else str(updated)
        out += f"\n\n<i>Aktualizacja: {esc(stamp)}</i>"
    return Html(out)


_FILE_KEYS = ("file", "name", "path", "src", "source")
_FOLDER_KEYS = ("folder", "dest", "target", "category", "dir")


def _pick(d: dict, keys: Sequence[str]) -> Any:
    for k in keys:
        if d.get(k):
            return d[k]
    return None


def tpl_memory_sorted(results: Iterable[Any], max_items: int = 60) -> Html:
    """Wynik sortowania pamięci: pliki pogrupowane w folderach docelowych.

    Element wyniku: ``{"file": ..., "folder": ...}`` (też ``path``/``dest`` itp.)
    albo krotka ``(plik, folder)``.
    """
    groups: dict[str, list[str]] = {}
    for r in results or []:
        if isinstance(r, dict):
            f, d = _pick(r, _FILE_KEYS), _pick(r, _FOLDER_KEYS)
        elif isinstance(r, (tuple, list)) and len(r) >= 2:
            f, d = r[0], r[1]
        else:
            f, d = r, None
        if not f:
            continue
        name = re.split(r"[\\/]", str(f).rstrip("\\/"))[-1] or str(f)
        folder = str(d).replace("\\", "/").strip("/") if d else ""
        groups.setdefault(folder, []).append(name)
    if not groups:
        return Html(f"{header('Pamięć', '🧠')}\n<i>Nie było nic do posortowania.</i>")
    nfiles = sum(len(v) for v in groups.values())
    nfold = len([k for k in groups if k])
    lines = [header("Pamięć posortowana", "🧠"),
             f"{nfiles} {plural(nfiles, 'plik', 'pliki', 'plików')} → "
             f"{nfold} {plural(nfold, 'folder', 'foldery', 'folderów')}",
             divider()]
    shown = 0
    for folder in sorted(groups, key=lambda k: (k == "", k.lower())):
        files = sorted(groups[folder], key=str.lower)
        label = f"📁 <b>{esc(folder)}</b>" if folder else "❓ <b>Bez folderu</b>"
        lines.append(("\n" if shown else "") + label)
        for fname in files:
            if shown >= max_items:
                break
            lines.append(f"{_NBSP * 3}• {esc(fname)}")
            shown += 1
        if shown >= max_items:
            break
    if nfiles > shown:
        rest = nfiles - shown
        lines.append(f"\n<i>… i jeszcze {rest} {plural(rest, 'plik', 'pliki', 'plików')}</i>")
    return Html("\n".join(lines))
