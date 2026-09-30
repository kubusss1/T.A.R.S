"""Testy tars_ai na lokalnym, fałszywym serwerze Ollamy (bez sieci)."""
import asyncio
import io
import json
import os
import socket
import sys
import threading
import unittest
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tars_ai  # noqa: E402
from tars_ai import Anthropic, AsyncAnthropic, OllamaError, chat, health, pick_tier  # noqa: E402
from tars_ai.__main__ import main as cli_main  # noqa: E402
from tars_ai.anthropic_compat import map_model  # noqa: E402


class FakeOllama:
    """Minimalna Ollama: /api/tags i /api/chat, zapisuje żądania."""

    def __init__(self):
        self.installed = ["qwen3.5:9b", "qwen3.5:4b", "qwen3.5:2b"]
        self.reply = "Cześć!"
        self.requests = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, obj):
                body = json.dumps(obj).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path == "/api/tags":
                    self._send(200, {"models": [{"name": n} for n in fake.installed]})
                else:
                    self._send(404, {"error": "404 page not found"})

            def do_POST(self):
                data = json.loads(self.rfile.read(int(self.headers["Content-Length"])).decode("utf-8"))
                fake.requests.append(data)
                if data["model"] not in fake.installed:
                    return self._send(404, {"error": f"model '{data['model']}' not found"})
                self._send(200, {"model": data["model"], "done": True, "done_reason": "stop",
                                 "message": {"role": "assistant", "content": fake.reply},
                                 "prompt_eval_count": 11, "eval_count": 7})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, args=(0.05,), daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def free_port_url():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return f"http://127.0.0.1:{s.getsockname()[1]}"


class Base(unittest.TestCase):
    def setUp(self):
        self.fake = FakeOllama()
        env = {k: v for k, v in os.environ.items()
               if k not in ("TARS_MODEL_BIG", "TARS_MODEL_MID", "TARS_MODEL_SMALL")}
        env["OLLAMA_URL"] = self.fake.url
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.fake.close)

    @property
    def last(self):
        return self.fake.requests[-1]


class TestChat(Base):
    def test_basic_chat(self):
        self.assertEqual(chat("Jak się masz?", task="chat", system="Jesteś TARS"), "Cześć!")
        req = self.last
        self.assertFalse(req["stream"])
        self.assertEqual(req["model"], "qwen3.5:4b")
        self.assertEqual(req["messages"][0], {"role": "system", "content": "Jesteś TARS"})
        self.assertEqual(req["messages"][-1], {"role": "user", "content": "Jak się masz?"})
        self.assertEqual(req["options"]["temperature"], 0.3)
        self.assertNotIn("format", req)

    def test_history_is_sent_before_prompt(self):
        hist = [{"role": "user", "content": "A"}, {"role": "assistant", "content": "B"}]
        chat("C", tier="small", history=hist)
        self.assertEqual([m["content"] for m in self.last["messages"]], ["A", "B", "C"])
        self.assertEqual(self.last["model"], "qwen3.5:2b")

    def test_think_tags_stripped(self):
        self.fake.reply = "<think>\nrozważam...\n</think>\n\nOdpowiedź: 42"
        self.assertEqual(chat("pytanie", tier="mid"), "Odpowiedź: 42")
        self.fake.reply = "resztki myśli</think>Tak"
        self.assertEqual(chat("pytanie", tier="mid"), "Tak")

    def test_json_mode_sets_format(self):
        self.fake.reply = '{"ok": true}'
        out = chat("daj json", task="classify", json_mode=True)
        self.assertEqual(self.last["format"], "json")
        self.assertEqual(json.loads(out), {"ok": True})

    def test_env_override_applies_at_call_time(self):
        self.fake.installed.append("llama3:8b")
        os.environ["TARS_MODEL_BIG"] = "llama3:8b"
        chat("napisz funkcję", task="code")
        self.assertEqual(self.last["model"], "llama3:8b")

    def test_fallback_to_smaller_tier_when_model_missing(self):
        self.fake.installed = ["qwen3.5:2b"]
        self.assertEqual(chat("plan dnia", task="plan"), "Cześć!")
        self.assertEqual([r["model"] for r in self.fake.requests],
                         ["qwen3.5:9b", "qwen3.5:4b", "qwen3.5:2b"])

    def test_fallback_to_any_installed_model(self):
        self.fake.installed = ["gemma3:4b"]
        chat("tytuł", task="title")
        self.assertEqual(self.last["model"], "gemma3:4b")

    def test_no_model_at_all_raises(self):
        self.fake.installed = []
        with self.assertRaises(OllamaError) as cm:
            chat("x", tier="small")
        self.assertIn("ollama pull", str(cm.exception))

    def test_unreachable_server_polish_message(self):
        url = free_port_url()
        os.environ["OLLAMA_URL"] = url
        with self.assertRaises(OllamaError) as cm:
            chat("hej", timeout=2)
        self.assertIn("Ollama nie odpowiada na " + url, str(cm.exception))
        self.assertIn("uruchom Ollamę", str(cm.exception))
        self.assertIsInstance(cm.exception, RuntimeError)

    def test_bad_url_or_non_http_server_raises_ollama_error(self):
        # Zły port w OLLAMA_URL (InvalidURL) i serwer, który nie mówi HTTP (BadStatusLine),
        # też muszą dawać OllamaError, a health() — słownik z "error".
        os.environ["OLLAMA_URL"] = "http://localhost:abc"
        with self.assertRaises(OllamaError):
            chat("hej", timeout=2)
        self.assertFalse(health(timeout=2)["ok"])
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(5)
        self.addCleanup(srv.close)

        def garbage():
            for _ in range(2):
                try:
                    conn, _ = srv.accept()
                except OSError:
                    return
                with conn:
                    conn.recv(65536)
                    conn.sendall(b"SSH-2.0-OpenSSH_9.6\r\n")

        threading.Thread(target=garbage, daemon=True).start()
        os.environ["OLLAMA_URL"] = f"http://127.0.0.1:{srv.getsockname()[1]}"
        with self.assertRaises(OllamaError):
            chat("hej", timeout=2)
        self.assertIn("error", health(timeout=2))


class TestRouter(unittest.TestCase):
    def test_known_tasks(self):
        for task in ("code", "plan", "analysis", "seo_audit"):
            self.assertEqual(pick_tier(task, "x"), "big", task)
        for task in ("chat", "summary", "classify", "seo"):
            self.assertEqual(pick_tier(task, "x" * 5000), "mid", task)
        for task in ("title", "label", "yesno", "tag", "YesNo", "seo-audit"):
            self.assertEqual(pick_tier(task, "x"), "small" if task != "seo-audit" else "big", task)

    def test_unknown_task_by_prompt(self):
        self.assertEqual(pick_tier("general", "Ile to 2+2?"), "small")
        self.assertEqual(pick_tier("general", "słowo " * 100), "mid")
        self.assertEqual(pick_tier("general", "a" * 2500), "big")
        self.assertEqual(pick_tier("cokolwiek", "Popraw:\n```py\nx=1\n```"), "big")
        self.assertEqual(pick_tier(None, "def foo(x):\n    return x"), "big")
        self.assertEqual(pick_tier("general", "Import towarów z Chin – co warto wiedzieć?"), "small")

    def test_invalid_tier_rejected(self):
        with self.assertRaises(ValueError):
            chat("x", tier="huge")


class TestHealth(Base):
    def test_health_all_ok(self):
        info = health()
        self.assertTrue(info["ok"])
        self.assertEqual(info["url"], self.fake.url)
        self.assertEqual(info["missing"], [])
        self.assertEqual(tars_ai.list_models(), self.fake.installed)

    def test_health_detects_missing(self):
        self.fake.installed = ["qwen3.5:4b"]
        info = health()
        self.assertFalse(info["ok"])
        self.assertEqual(info["missing"], ["qwen3.5:9b", "qwen3.5:2b"])
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli_main(["health"])
        self.assertEqual(code, 1)
        self.assertIn("ollama pull qwen3.5:9b", buf.getvalue())

    def test_health_unreachable(self):
        os.environ["OLLAMA_URL"] = free_port_url()
        info = health()
        self.assertFalse(info["ok"])
        self.assertIn("uruchom Ollamę", info["error"])

    def test_cli_ask(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli_main(["ask", "Jak", "leci?"])
        self.assertEqual(code, 0)
        self.assertEqual(buf.getvalue().strip(), "Cześć!")
        self.assertEqual(self.last["messages"][-1]["content"], "Jak leci?")


class TestAnthropicShim(Base):
    def test_response_shape(self):
        client = Anthropic(api_key="ignored")
        resp = client.messages.create(model="claude-3-5-sonnet-latest", max_tokens=100,
                                      system="Bądź zwięzły", temperature=0.1,
                                      messages=[{"role": "user", "content": "Hej"}])
        self.assertEqual(resp.content[0].type, "text")
        self.assertEqual(resp.content[0].text, "Cześć!")
        self.assertEqual(resp.stop_reason, "end_turn")
        self.assertEqual((resp.usage.input_tokens, resp.usage.output_tokens), (11, 7))
        self.assertEqual(resp.model, "qwen3.5:4b")
        self.assertEqual(self.last["options"], {"temperature": 0.1, "num_predict": 100})
        self.assertEqual(self.last["messages"][0], {"role": "system", "content": "Bądź zwięzły"})

    def test_claude_name_mapping(self):
        self.assertEqual(map_model("claude-opus-4-1"), (None, "big"))
        self.assertEqual(map_model("claude-sonnet-4-5"), (None, "mid"))
        self.assertEqual(map_model("claude-3-haiku-20240307"), (None, "small"))
        self.assertEqual(map_model("llama3:8b"), ("llama3:8b", "mid"))
        client = Anthropic()
        for name, expected in (("claude-opus-4", "qwen3.5:9b"), ("claude-haiku-4-5", "qwen3.5:2b")):
            client.messages.create(model=name, max_tokens=10, messages=[{"role": "user", "content": "x"}])
            self.assertEqual(self.last["model"], expected)
        self.fake.installed.append("mistral:7b")
        client.messages.create(model="mistral:7b", max_tokens=10, messages=[{"role": "user", "content": "x"}])
        self.assertEqual(self.last["model"], "mistral:7b")

    def test_block_list_content(self):
        content = [{"type": "text", "text": "Opisz"}, {"type": "image", "source": {}},
                   {"type": "text", "text": "to zdjęcie"}]
        Anthropic().messages.create(model="claude-sonnet-4", max_tokens=50,
                                    system=[{"type": "text", "text": "SYS"}],
                                    messages=[{"role": "user", "content": content}])
        self.assertEqual(self.last["messages"], [{"role": "system", "content": "SYS"},
                                                 {"role": "user", "content": "Opisz\nto zdjęcie"}])

    def test_async_shim(self):
        async def run():
            return await AsyncAnthropic().messages.create(
                model="claude-haiku-4-5", max_tokens=20, messages=[{"role": "user", "content": "hej"}])
        resp = asyncio.run(run())
        self.assertEqual(resp.content[0].text, "Cześć!")
        self.assertEqual(resp.model, "qwen3.5:2b")


if __name__ == "__main__":
    unittest.main()
