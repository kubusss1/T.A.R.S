"""Testy modułu tars_telegram (wiadomości HTML, klawiatury, Mini App)."""

import http.client
import json
import re
import sys
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tars_telegram import ui  # noqa: E402
from tars_telegram.miniapp import server as srv  # noqa: E402

TOKEN = "123456:TEST-token_abcdef"
NOW = 1_800_000_000


def tags_balanced(s):
    stack = []
    for m in re.finditer(r"<(/?)([a-zA-Z][a-zA-Z0-9-]*)[^>]*>", s):
        if m.group(1):
            if not stack or stack.pop() != m.group(2):
                return False
        else:
            stack.append(m.group(2))
    return not stack


def all_buttons(markup):
    return [b for row in markup["inline_keyboard"] for b in row]


class TestBasics(unittest.TestCase):
    def test_escaping(self):
        self.assertEqual(ui.esc('a < b & c > "d"'), 'a &lt; b &amp; c &gt; "d"')
        self.assertEqual(ui.esc(None), "")
        self.assertIn("&lt;script&gt;", ui.section("T", "<script>"))

    def test_html_marker_not_double_escaped(self):
        self.assertEqual(ui.section("A&B", ui.code("x<y")), "<b>A&amp;B</b>\n<code>x&lt;y</code>")
        self.assertEqual(ui.bullet_list(["a<b", ui.Html("<i>c</i>")]), "• a&lt;b\n• <i>c</i>")

    def test_link_scheme_filtering(self):
        self.assertEqual(ui.link("x", "https://a.pl/?q=1&r=2"), '<a href="https://a.pl/?q=1&amp;r=2">x</a>')
        self.assertIn("href", ui.link("tg", "tg://resolve?domain=tars"))
        for bad in ("javascript:alert(1)", "JaVaScRiPt:alert(1)", " javascript:x", "data:text/html,x",
                    "java\nscript:x", "https://", "/relative", "file:///c:/x"):
            out = ui.link("<klik>", bad)
            self.assertNotIn("<a", out, bad)
            self.assertEqual(out, "&lt;klik&gt;")
        self.assertIn("&quot;", ui.link("q", 'https://a.pl/"onmouseover="x'))

    def test_status_dot(self):
        self.assertEqual([ui.status_dot(x) for x in ("ok", "warning", "critical", "unknown")],
                         ["🟢", "🟡", "🔴", "⚪"])
        self.assertEqual(ui.status_dot("DOWN"), "🔴")
        self.assertEqual(ui.status_dot("???"), "⚪")
        self.assertEqual(ui.status_dot(True), "🟢")

    def test_progress_bar_edges(self):
        self.assertEqual(ui.progress_bar(0, 10), "▱" * 10 + " 0%")
        self.assertEqual(ui.progress_bar(15, 10), "▰" * 10 + " 100%")
        self.assertEqual(ui.progress_bar(5, 0), "▱" * 10 + " 0%")
        self.assertEqual(ui.progress_bar(-3, 10), "▱" * 10 + " 0%")
        self.assertEqual(ui.progress_bar(3, 10), "▰▰▰▱▱▱▱▱▱▱ 30%")
        self.assertEqual(ui.progress_bar(1, 5, width=5), "▰▱▱▱▱ 20%")
        # prawie pełny pasek nie może udawać 100%
        self.assertTrue(ui.progress_bar(999, 1000).endswith(" 99%"))
        self.assertIn("▱", ui.progress_bar(999, 1000))

    def test_kv_and_card(self):
        out = ui.kv([("CPU", "30%"), ("Dysk", "<1 GB")])
        lines = out.split("\n")
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0].index("</code>"), lines[1].index("</code>"))
        self.assertIn("&lt;1 GB", out)
        c = ui.card("Serwer", [("CPU", ui.progress_bar(3, 10))], status="critical", footer="12:00")
        self.assertTrue(c.startswith("🔴 <b>Serwer</b>"))
        self.assertIn("┈", c)
        self.assertTrue(c.endswith("<i>12:00</i>"))
        self.assertTrue(tags_balanced(c))

    def test_pre_and_spoiler(self):
        self.assertEqual(ui.pre("a<b", "py"), '<pre><code class="language-py">a&lt;b</code></pre>')
        self.assertEqual(ui.pre("x", 'py"><script>'), '<pre><code class="language-pyscript">x</code></pre>')
        self.assertEqual(ui.spoiler("tajne"), "<tg-spoiler>tajne</tg-spoiler>")


class TestChunking(unittest.TestCase):
    def test_short_message_single_chunk(self):
        self.assertEqual(ui.chunk_message("<b>hej</b>"), ["<b>hej</b>"])
        self.assertEqual(ui.chunk_message("   "), [])

    def test_chunks_within_limit_and_balanced(self):
        para = "<b>Ważne:</b> " + " ".join(["słowo"] * 30) + " <i>kursywa <b>obie</b> " + "x " * 40 + "</i>"
        text = "<b>" + "\n\n".join([para] * 25) + "</b>"
        for limit in (64, 200, 1000):
            chunks = ui.chunk_message(text, limit)
            self.assertGreater(len(chunks), 1)
            for c in chunks:
                self.assertLessEqual(ui.tg_len(c), limit)
                self.assertTrue(tags_balanced(c), c)
                self.assertTrue(c.startswith("<b>"))  # zewnętrzny tag otwarty ponownie
            plain = lambda s: re.sub(r"<[^>]*>|\s", "", s)  # noqa: E731
            self.assertEqual(plain("".join(chunks)), plain(text))

    def test_chunk_never_splits_entities_or_tags(self):
        text = ('<a href="https://example.com/?a=1&amp;b=2">link</a> &amp; ' * 200)
        for c in ui.chunk_message(text, 100):
            self.assertLessEqual(ui.tg_len(c), 100)
            self.assertIsNone(re.search(r"&[a-z]*$", c))
            self.assertIsNone(re.search(r"<[^>]*$", c))
            self.assertTrue(tags_balanced(c))

    def test_chunk_prefers_paragraph_boundaries(self):
        paras = [f"Akapit {i}. " + "tekst " * 60 for i in range(10)]
        chunks = ui.chunk_message("\n\n".join(paras), 1000)
        for c in chunks:
            self.assertTrue(c.startswith("Akapit"), c[:20])

    def test_emoji_counted_as_utf16(self):
        text = "😀" * 100  # 200 jednostek UTF-16
        chunks = ui.chunk_message(text, 64)
        self.assertTrue(all(ui.tg_len(c) <= 64 for c in chunks))
        self.assertEqual("".join(chunks), text)


class TestMarkdown(unittest.TestCase):
    def test_bold_italic(self):
        self.assertEqual(ui.md_to_tg_html("To **ważne** i *tak* i _też_"),
                         "To <b>ważne</b> i <i>tak</i> i <i>też</i>")
        self.assertEqual(ui.md_to_tg_html("snake_case_name i 2 * 3 * 4"), "snake_case_name i 2 * 3 * 4")

    def test_code_block_with_lt(self):
        out = ui.md_to_tg_html("Kod:\n```python\nif a < b and c > d:\n    print('**x**')\n```\nKoniec")
        self.assertIn('<pre><code class="language-python">if a &lt; b and c &gt; d:\n    print(\'**x**\')</code></pre>', out)
        self.assertNotIn("<b>x</b>", out)
        self.assertTrue(tags_balanced(out))

    def test_inline_code_and_escape(self):
        self.assertEqual(ui.md_to_tg_html("Użyj `a<b>` & <tag>"),
                         "Użyj <code>a&lt;b&gt;</code> &amp; &lt;tag&gt;")

    def test_link_and_list_and_heading(self):
        out = ui.md_to_tg_html("# Plan **dnia**\n- [Strona](https://zrobsite.pl)\n- zły [x](javascript:alert(1))\n* trzeci")
        lines = out.split("\n")
        self.assertEqual(lines[0], "<b>Plan dnia</b>")
        self.assertEqual(lines[1], '• <a href="https://zrobsite.pl">Strona</a>')
        self.assertEqual(lines[2], "• zły x")
        self.assertEqual(lines[3], "• trzeci")
        self.assertNotIn("javascript", out)

    def test_unbalanced_markdown_falls_back_safely(self):
        out = ui.md_to_tg_html("**a *b** c*")
        self.assertTrue(tags_balanced(out))

    def test_table_and_quote(self):
        out = ui.md_to_tg_html("| Model | Czas |\n|---|---|\n| qwen | 2 s |\n\n> cytat")
        self.assertIn("<pre>Model", out)
        self.assertIn("<blockquote>cytat</blockquote>", out)

    def test_strip_think(self):
        self.assertEqual(ui.strip_think("<think>\nhmm <b>\n</think>\n\nOdpowiedź"), "Odpowiedź")
        self.assertEqual(ui.strip_think("A<think>x</think>B<THINK>y</THINK>C"), "ABC")
        self.assertEqual(ui.strip_think("rozważania...</think>Wynik"), "Wynik")
        self.assertEqual(ui.strip_think("Wynik <think>urwane"), "Wynik")
        self.assertEqual(ui.strip_think(None), "")


class TestKeyboards(unittest.TestCase):
    def test_callback_data_length(self):
        self.assertEqual(ui.check_callback_data("a" * 64), "a" * 64)
        with self.assertRaises(ValueError):
            ui.check_callback_data("a" * 65)
        with self.assertRaises(ValueError):
            ui.check_callback_data("ą" * 33)  # 66 bajtów UTF-8
        with self.assertRaises(ValueError):
            ui.inline_keyboard([[("Za długi", "x" * 70)]])
        with self.assertRaises(ValueError):
            ui.sort_menu("a", [("k" * 70, "K")], "sort")

    def test_inline_keyboard_json(self):
        kb = ui.inline_keyboard([[("A", "a:1"), {"text": "Strona", "url": "https://zrobsite.pl"}],
                                 {"text": "B", "callback_data": "b"}])
        self.assertEqual(len(kb["inline_keyboard"]), 2)
        json.dumps(kb)
        with self.assertRaises(ValueError):
            ui.inline_keyboard([[{"text": "zły", "url": "javascript:alert(1)"}]])
        with self.assertRaises(ValueError):
            ui.button("dwie akcje", "x", url="https://a.pl")

    def test_sort_menu_marks_active(self):
        kb = ui.sort_menu("date", [("name", "Nazwa"), ("date", "Data"), ("size", "Rozmiar")], "sort")
        texts = [b["text"] for b in all_buttons(kb)]
        self.assertEqual(sum(t.startswith("✓") for t in texts), 1)
        self.assertTrue(texts[1].startswith("✓ Data"))
        active = all_buttons(kb)[1]
        self.assertEqual(active["callback_data"], "sort:-date")  # kliknięcie odwraca kierunek
        kb_desc = ui.sort_menu("-date", {"name": "Nazwa", "date": "Data"}, "sort")
        self.assertEqual(all_buttons(kb_desc)[1]["text"], "✓ Data ↓")
        self.assertEqual(all_buttons(kb_desc)[1]["callback_data"], "sort:date")
        self.assertEqual(ui.parse_callback("sort:-date"), ("sort", "-date"))

    def test_pager(self):
        row = ui.pager(2, 5, "mem")["inline_keyboard"][0]
        self.assertEqual([b["text"] for b in row], ["◀", "2/5", "▶"])
        self.assertEqual([b["callback_data"] for b in row], ["mem:1", "mem:noop", "mem:3"])
        first = ui.pager(1, 3, "p")["inline_keyboard"][0]
        self.assertEqual(first[0]["callback_data"], "p:noop")
        self.assertEqual(ui.pager(1, 1, "p"), {"inline_keyboard": []})
        self.assertEqual(ui.pager(99, 3, "p")["inline_keyboard"][0][1]["text"], "3/3")

    def test_main_menu_web_app_only_with_urls(self):
        plain = ui.main_menu()
        self.assertFalse(any("web_app" in b for b in all_buttons(plain)))
        texts = " ".join(b["text"] for b in all_buttons(plain))
        for label in ("Status", "Pamięć", "ZrobSite", "Więcej"):
            self.assertIn(label, texts)
        full = ui.main_menu("https://app.example.com/?tab=tars", "https://app.example.com/?tab=zrobsite")
        webs = [b for b in all_buttons(full) if "web_app" in b]
        self.assertEqual(len(webs), 2)
        self.assertEqual(webs[0]["web_app"]["url"], "https://app.example.com/?tab=tars")
        one = ui.main_menu(zrobsite_url="https://z.example.com")
        self.assertEqual(len([b for b in all_buttons(one) if "web_app" in b]), 1)
        with self.assertRaises(ValueError):
            ui.main_menu("http://localhost:8765")  # Telegram wymaga HTTPS
        json.dumps(full)

    def test_miniapp_url(self):
        url = ui.miniapp_url("https://app.pl/", tars="https://t.pl/?a=1&b=2", tab="tars")
        self.assertEqual(url, "https://app.pl/?tars=https%3A%2F%2Ft.pl%2F%3Fa%3D1%26b%3D2&tab=tars")


class TestTemplates(unittest.TestCase):
    def test_ai_answer(self):
        out = ui.tpl_ai_answer("<think>myślę</think>**Cześć** <x>", model="qwen3.5:9b", seconds=2.1)
        self.assertEqual(out, "<b>Cześć</b> &lt;x&gt;\n\n<i>qwen3.5:9b · 2.1 s</i>")
        self.assertIn("pusta", ui.tpl_ai_answer("<think>tylko myśli</think>"))

    def test_error_and_status(self):
        err = ui.tpl_error(RuntimeError("Ollama <nie działa>"), hint="Uruchom: ollama serve")
        self.assertIn("&lt;nie działa&gt;", err)
        self.assertIn("💡", err)
        st = ui.tpl_status([{"name": "Ollama", "level": "ok", "detail": "3 modele"},
                            {"name": "ZrobSite", "level": "critical", "detail": "timeout"},
                            {"name": "Dysk", "level": "warning"}])
        self.assertIn("1/3 OK", st)
        self.assertLess(st.index("ZrobSite"), st.index("Dysk"))
        self.assertLess(st.index("Dysk"), st.index("Ollama"))
        self.assertTrue(tags_balanced(st))

    def test_memory_sorted(self):
        out = ui.tpl_memory_sorted([
            {"file": "C:\\Users\\Kuba\\faktura.pdf", "folder": "Finanse/2026"},
            ("notatka <1>.md", "Projekty"),
            {"path": "umowa.pdf", "dest": "Finanse/2026"},
        ])
        self.assertIn("3 pliki → 2 foldery", out)
        self.assertIn("📁 <b>Finanse/2026</b>", out)
        self.assertIn("faktura.pdf", out)
        self.assertNotIn("Users", out)
        self.assertIn("notatka &lt;1&gt;.md", out)
        self.assertLess(out.index("Finanse"), out.index("Projekty"))
        self.assertIn("Nie było nic", ui.tpl_memory_sorted([]))
        self.assertEqual(ui.plural(5, "plik", "pliki", "plików"), "plików")
        self.assertEqual(ui.plural(22, "plik", "pliki", "plików"), "pliki")
        self.assertEqual(ui.plural(12, "plik", "pliki", "plików"), "plików")


class TestInitData(unittest.TestCase):
    def make(self, **over):
        fields = {"query_id": "AAH", "user": {"id": 42, "first_name": "Kuba"}, "auth_date": str(NOW)}
        fields.update(over)
        return srv.sign_init_data(fields, TOKEN)

    def test_valid(self):
        data = srv.validate_init_data(self.make(), TOKEN, now=NOW + 10)
        self.assertIsNotNone(data)
        self.assertEqual(data["user"]["id"], 42)
        self.assertEqual(data["auth_date"], NOW)

    def test_known_vector(self):
        # Wektor liczony niezależnie wg dokumentacji Telegrama.
        import hashlib
        import hmac
        dcs = "auth_date=%d\nuser={\"id\":1}" % NOW
        secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
        h = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
        init = "user=%7B%22id%22%3A1%7D&auth_date=" + str(NOW) + "&hash=" + h
        self.assertEqual(srv.validate_init_data(init, TOKEN, now=NOW)["user"], {"id": 1})

    def test_tampered(self):
        good = self.make()
        tampered = good.replace("Kuba", "Eve")
        self.assertIsNone(srv.validate_init_data(tampered, TOKEN, now=NOW))
        bad_hash = re.sub(r"hash=([0-9a-f])", lambda m: "hash=" + ("0" if m.group(1) != "0" else "1"), good)
        self.assertIsNone(srv.validate_init_data(bad_hash, TOKEN, now=NOW))
        self.assertIsNone(srv.validate_init_data(good, "999:other", now=NOW))
        self.assertIsNone(srv.validate_init_data(good + "&hash=abc", TOKEN, now=NOW))  # duplikat
        self.assertIsNone(srv.validate_init_data("", TOKEN))
        self.assertIsNone(srv.validate_init_data("garbage", TOKEN))

    def test_expired(self):
        init = self.make()
        self.assertIsNone(srv.validate_init_data(init, TOKEN, max_age=3600, now=NOW + 3601))
        self.assertIsNotNone(srv.validate_init_data(init, TOKEN, max_age=3600, now=NOW + 3599))
        self.assertIsNone(srv.validate_init_data(init, TOKEN, now=NOW - 3600))  # z przyszłości


class TestMiniAppFiles(unittest.TestCase):
    def test_index_html_only_telegram_script(self):
        page = (ROOT / "tars_telegram" / "miniapp" / "index.html").read_text(encoding="utf-8")
        self.assertIn("https://telegram.org/js/telegram-web-app.js", page)
        srcs = re.findall(r"<script[^>]*\bsrc\s*=\s*[\"']?([^\"'\s>]+)", page, flags=re.I)
        self.assertEqual(srcs, ["https://telegram.org/js/telegram-web-app.js"])
        self.assertIsNone(re.search(r"<link[^>]+stylesheet", page, flags=re.I))
        self.assertIsNone(re.search(r"@import", page))
        for needle in ("--tg-theme-bg-color", "expand()", "ready()", "BackButton",
                       "HapticFeedback", "localStorage", "openLink", "Otwórz w przeglądarce",
                       srv.CONFIG_PLACEHOLDER):
            self.assertIn(needle, page)

    def test_index_html_tab_lookup_own_keys_only(self):
        # start_param z linku t.me/…?startapp=constructor nie może wywrócić Mini App.
        page = (ROOT / "tars_telegram" / "miniapp" / "index.html").read_text(encoding="utf-8")
        self.assertIn("Object.prototype.hasOwnProperty.call(TABS, t)", page)
        self.assertNotRegex(page, r"return t && TABS\[t\]|if \(!TABS\[tab\]")
        self.assertIn(".filter(isTab)", page)
        self.assertIn("if (!isTab(tab)", page)

    def test_validate_panel_url(self):
        for ok in ("https://tars.example.com", "http://localhost:8000/panel", "http://192.168.1.20:5000",
                   "http://10.0.0.5", "http://127.0.0.1:8080", "http://100.100.1.2"):
            self.assertIsNotNone(srv.validate_panel_url(ok), ok)
        for bad in ("http://example.com", "javascript:alert(1)", "ftp://x", "", None,
                    "https://user:pass@x.pl", "http://8.8.8.8"):
            self.assertIsNone(srv.validate_panel_url(bad), bad)

    def test_readme_exists(self):
        readme = (ROOT / "tars_telegram" / "miniapp" / "README.md").read_text(encoding="utf-8")
        for needle in ("BotFather", "HTTPS", "main_menu"):
            self.assertIn(needle, readme)


class TestMiniAppServer(unittest.TestCase):
    """Lokalny serwer na 127.0.0.1 (port losowy) — bez internetu."""

    @classmethod
    def setUpClass(cls):
        cls.server = srv.make_server("127.0.0.1", 0, bot_token=TOKEN, allowed_user_ids=[42],
                                     cors_origins=[], panel_urls={"tars": "https://t.example.com/<x>",
                                                                  "zrobsite": "http://evil.com"})
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            resp = conn.getresponse()
            return resp.status, dict(resp.getheaders()), resp.read()
        finally:
            conn.close()

    def test_health_and_index(self):
        status, _, body = self.request("GET", "/health")
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["ok"])
        status, headers, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        page = body.decode("utf-8")
        self.assertIn("telegram-web-app.js", page)
        self.assertNotIn(srv.CONFIG_PLACEHOLDER, page)
        self.assertIn("\\u003cx\\u003e", page)  # wstrzyknięty config jest bezpieczny w <script>
        self.assertNotIn("evil.com", page)  # http:// spoza LAN odrzucony
        self.assertIn("Content-Security-Policy", headers)

    def test_no_other_files(self):
        for path in ("/server.py", "/README.md", "/../ui.py", "/miniapp/", "/index.html/.."):
            status, _, _ = self.request("GET", path)
            self.assertEqual(status, 404, path)

    def test_auth_endpoint(self):
        good = srv.sign_init_data({"user": {"id": 42, "first_name": "Kuba"},
                                   "auth_date": str(int(__import__("time").time()))}, TOKEN)
        status, _, body = self.request("POST", "/auth", json.dumps({"initData": good}),
                                       {"Content-Type": "application/json"})
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)["user"]["first_name"], "Kuba")
        status, _, _ = self.request("POST", "/auth", good.replace("Kuba", "Eve"))
        self.assertEqual(status, 401)
        stranger = srv.sign_init_data({"user": {"id": 7}, "auth_date": str(int(__import__("time").time()))}, TOKEN)
        status, _, _ = self.request("POST", "/auth", stranger)
        self.assertEqual(status, 403)
        status, _, _ = self.request("GET", "/auth")
        self.assertEqual(status, 405)

    def test_slow_client_does_not_hold_thread_forever(self):
        import socket
        import time
        from unittest import mock
        self.assertIsNotNone(srv.MiniAppHandler.timeout)
        self.assertLessEqual(srv.MiniAppHandler.timeout, 60)
        with mock.patch.object(srv.MiniAppHandler, "timeout", 0.3):
            sock = socket.create_connection(("127.0.0.1", self.port), timeout=5)
            try:
                sock.sendall(b"POST /auth HTTP/1.1\r\nHost: x\r\nContent-Length: 100\r\n\r\nabc")
                start = time.monotonic()
                self.assertEqual(sock.recv(1024), b"")  # serwer zamyka połączenie po timeoucie
                self.assertLess(time.monotonic() - start, 4)
            finally:
                sock.close()


if __name__ == "__main__":
    unittest.main()
