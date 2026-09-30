"""Testy modułu tars_memory (bez sieci i bez Ollamy — AI podmienione)."""
import io
import json
import os
import sys
import tempfile
import time
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tars_memory import (LOG_NAME, classify, extract_text, list_items, natural_key, read_log,  # noqa: E402
                         safe_folder, sort_inbox, undo_last)
from tars_memory.__main__ import main  # noqa: E402


def fake_ai(reply):
    """ai_fn zwracające stałą odpowiedź (dict → JSON) i zapamiętujące prompty."""
    def fn(prompt):
        fn.prompts.append(prompt)
        if isinstance(reply, Exception):
            raise reply
        return reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False)
    fn.prompts = []
    return fn


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.inbox = self.tmp / "inbox"
        self.root = self.tmp / "pamiec"
        self.inbox.mkdir()
        self.root.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def put(self, rel, content="x", base=None):
        p = (base or self.inbox) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            p.write_bytes(content)
        else:
            p.write_text(content, encoding="utf-8")
        return p


class TestClassifier(Base):
    def test_ai_decision_honored(self):
        (self.root / "Projekty" / "TARS").mkdir(parents=True)
        f = self.put("plan.md", "Plan rozwoju asystenta TARS")
        ai = fake_ai({"folder": "Projekty/TARS", "new_folder": False, "filename": "plan_tars.md",
                      "reason": "Dotyczy projektu TARS", "confidence": 0.9})
        d = classify(f, ["Projekty", "Projekty/TARS"], ai_fn=ai)
        self.assertEqual((d.folder, d.new_folder, d.filename, d.source), ("Projekty/TARS", False, "plan_tars.md", "ai"))
        prompt = ai.prompts[0]
        self.assertIn("Projekty/TARS", prompt)
        self.assertIn("plan.md", prompt)
        self.assertIn("Plan rozwoju", prompt)

    def test_ai_new_folder_and_extension_kept(self):
        f = self.put("przepis.txt", "Mąka, jajka, cukier")
        ai = fake_ai({"folder": "Kuchnia/Ciasta", "new_folder": True, "filename": "sernik.exe",
                      "reason": "Przepis", "confidence": 0.8})
        d = classify(f, ["Dokumenty"], ai_fn=ai)
        self.assertEqual((d.folder, d.new_folder, d.filename), ("Kuchnia/Ciasta", True, "sernik.txt"))

    def test_path_traversal_rejected(self):
        f = self.put("faktura_03.pdf", b"%PDF-1.4")
        for bad in ("../../Windows", "C:\\Windows\\System32", "/etc", "a/../../b", "A/B/C/D"):
            d = classify(f, [], ai_fn=fake_ai({"folder": bad, "confidence": 0.99}))
            self.assertEqual(d.source, "rules", bad)
            self.assertEqual(d.folder, "Finanse/Faktury")
        self.assertIsNone(safe_folder(".."))
        self.assertEqual(safe_folder('Zdj<ę>cia/2024:wakacje?'), "Zdjęcia/2024wakacje")
        self.assertEqual(safe_folder("con/x"), "_con/x")

    def test_windows_reserved_names_variants(self):
        from tars_memory.classifier import sanitize_name
        # Windows traktuje „NUL .txt”, „COM0”, „CONIN$” itp. jak urządzenia — muszą dostać „_”.
        for bad in ("NUL .txt", "con  .log", "COM0", "lpt0.txt", "CONIN$", "conout$.txt", "COM¹"):
            self.assertTrue(sanitize_name(bad).startswith("_"), bad)
        self.assertEqual(safe_folder("nul .x/abc"), "_nul .x/abc")
        self.assertEqual(sanitize_name("console.txt"), "console.txt")
        self.assertEqual(sanitize_name("com10"), "com10")

    def test_invalid_json_falls_back_to_rules(self):
        f = self.put("umowa_najmu.docx", b"not a zip")
        d = classify(f, [], ai_fn=fake_ai("Jasne! Wrzuć to do folderu Umowy :)"))
        self.assertEqual((d.source, d.folder, d.new_folder), ("rules", "Dokumenty/Umowy", True))
        self.assertIn("JSON", d.reason)

    def test_ai_exception_falls_back(self):
        f = self.put("wakacje.jpg", b"\xff\xd8\xff")
        d = classify(f, [], ai_fn=fake_ai(RuntimeError("Ollama nie działa")))
        self.assertEqual((d.source, d.folder), ("rules", "Obrazy"))

    def test_low_confidence_falls_back(self):
        f = self.put("utwor.mp3", b"ID3")
        d = classify(f, [], ai_fn=fake_ai({"folder": "Coś", "confidence": 0.2}))
        self.assertEqual((d.source, d.folder), ("rules", "Audio"))

    def test_json_in_code_fence_accepted(self):
        f = self.put("a.txt", "abc")
        d = classify(f, [], ai_fn=fake_ai('```json\n{"folder": "Notatki", "confidence": 0.7}\n```'))
        self.assertEqual((d.source, d.folder, d.filename), ("ai", "Notatki", "a.txt"))

    def test_existing_folder_preferred_fuzzy(self):
        bad_ai = fake_ai("???")
        img = self.put("IMG_0001.JPG", b"\xff\xd8")
        self.assertEqual(classify(img, ["Moje/zdjęcia", "Praca"], ai_fn=bad_ai).folder, "Moje/zdjęcia")
        fv = self.put("Faktura-VAT-12.pdf", b"%PDF")
        d = classify(fv, ["Finanse", "Archiwum/FAKTURY"], ai_fn=bad_ai)
        self.assertEqual((d.folder, d.new_folder), ("Archiwum/FAKTURY", False))
        doc = self.put("raport.txt", "tekst")
        ai = fake_ai({"folder": "dokumenty", "new_folder": True, "confidence": 0.9})
        d = classify(doc, ["Dokumęnty"], ai_fn=ai)
        self.assertEqual((d.folder, d.new_folder), ("Dokumęnty", False))

    def test_keyword_from_content(self):
        f = self.put("skan_0012.txt", "Rachunek za prąd, kwota 120 zł")
        d = classify(f, [], ai_fn=fake_ai("x"))
        self.assertEqual(d.folder, "Dokumenty/Skany")  # nazwa ma pierwszeństwo przed treścią
        g = self.put("dokument.txt", "Rachunek za prąd, kwota 120 zł")
        self.assertEqual(classify(g, [], ai_fn=fake_ai("x")).folder, "Finanse/Rachunki")


class TestSorter(Base):
    def test_locked_source_leaves_no_duplicate(self):
        # Windows: plik otwarty w innym programie — rename się nie udaje, kopia się udaje,
        # a usunięcie źródła rzuca PermissionError. Nie może zostać kopia w pamięci.
        src = self.put("notatka.txt", "treść")
        real_unlink = os.unlink

        def locked_unlink(path, *a, **kw):
            if Path(path) == src:
                raise PermissionError(13, "Plik jest używany przez inny proces", str(path))
            return real_unlink(path, *a, **kw)

        ai = fake_ai({"folder": "Notatki", "confidence": 0.9})
        with mock.patch("os.rename", side_effect=OSError(18, "cross-device")), \
                mock.patch("os.unlink", side_effect=locked_unlink):
            res = sort_inbox(self.inbox, self.root, ai_fn=ai)
        self.assertFalse(res[0].moved)
        self.assertIn("PermissionError", res[0].error)
        self.assertTrue(src.exists())
        self.assertEqual([p for p in self.root.rglob("*") if p.is_file()], [])
        self.assertEqual(read_log(self.root), [])

    def test_sort_moves_and_collision_numbering(self):
        target = self.root / "Notatki"
        target.mkdir()
        (target / "lista.txt").write_text("stara", encoding="utf-8")
        (target / "lista (2).txt").write_text("stara2", encoding="utf-8")
        self.put("lista.txt", "nowa")
        ai = fake_ai({"folder": "Notatki", "confidence": 0.9, "reason": "notatka"})
        res = sort_inbox(self.inbox, self.root, ai_fn=ai)
        self.assertEqual(len(res), 1)
        self.assertTrue(res[0].moved)
        self.assertEqual(res[0].destination.name, "lista (3).txt")
        self.assertEqual((target / "lista (3).txt").read_text(encoding="utf-8"), "nowa")
        self.assertEqual((target / "lista.txt").read_text(encoding="utf-8"), "stara")
        self.assertFalse((self.inbox / "lista.txt").exists())

    def test_skip_temp_files(self):
        for n in ("~$raport.docx", "film.mp4.part", "plik.crdownload", "desktop.ini", "Thumbs.db", ".ukryty"):
            self.put(n, "x")
        self.put("ok.txt", "x")
        res = sort_inbox(self.inbox, self.root, ai_fn=fake_ai({"folder": "Inne", "confidence": 0.9}))
        self.assertEqual([r.original.name for r in res], ["ok.txt"])
        self.assertTrue((self.inbox / "desktop.ini").exists())

    def test_dry_run_moves_nothing(self):
        self.put("faktura.pdf", b"%PDF")
        res = sort_inbox(self.inbox, self.root, ai_fn=fake_ai("zły json"), dry_run=True)
        self.assertEqual(res[0].destination, self.root / "Finanse" / "Faktury" / "faktura.pdf")
        self.assertFalse(res[0].moved)
        self.assertTrue((self.inbox / "faktura.pdf").exists())
        self.assertFalse((self.root / "Finanse").exists())
        self.assertFalse((self.root / LOG_NAME).exists())

    def test_log_and_undo(self):
        self.put("a.txt", "A")
        self.put("b.txt", "B")
        ai = fake_ai({"folder": "Nowy/Folder", "new_folder": True, "confidence": 0.9, "reason": "test"})
        res = sort_inbox(self.inbox, self.root, ai_fn=ai)
        self.assertTrue(all(r.moved for r in res))
        log = read_log(self.root)
        self.assertEqual(len(log), 2)
        for key in ("timestamp", "original", "destination", "reason", "source"):
            self.assertIn(key, log[0])
        self.assertEqual(log[0]["source"], "ai")
        restored = undo_last(self.root)  # cofa b.txt (ostatni)
        self.assertEqual(len(restored), 1)
        self.assertTrue((self.inbox / "b.txt").exists())
        self.assertFalse((self.inbox / "a.txt").exists())
        self.assertEqual(len(undo_last(self.root, n=5)), 1)
        self.assertTrue((self.inbox / "a.txt").exists())
        self.assertFalse((self.root / "Nowy").exists())  # puste, utworzone foldery usunięte
        self.assertEqual(undo_last(self.root), [])

    def test_new_folder_reused_within_batch(self):
        self.put("faktura1.pdf", b"%PDF")
        self.put("faktura2.pdf", b"%PDF")
        res = sort_inbox(self.inbox, self.root, ai_fn=fake_ai("nie"))
        self.assertEqual([r.decision.new_folder for r in res], [True, False])
        self.assertEqual(len(list((self.root / "Finanse" / "Faktury").iterdir())), 2)

    def test_cli_sort_and_list(self):
        self.put("notatka.txt", "x")
        buf = io.StringIO()
        offline = mock.patch("tars_memory.classifier._default_ai", side_effect=RuntimeError("offline"))
        with redirect_stdout(buf), offline:
            main(["sort", str(self.inbox), str(self.root), "--dry-run"])
            main(["list", str(self.root)])
        out = buf.getvalue()
        self.assertIn("Tryb próbny", out)
        self.assertIn("Brak plików", out)


class TestExtract(Base):
    def test_docx_extraction(self):
        p = self.inbox / "umowa.docx"
        xml = ('<?xml version="1.0"?><w:document xmlns:w="x"><w:body><w:p><w:r><w:t>Umowa najmu</w:t></w:r></w:p>'
               '<w:p><w:r><w:t>Strona &amp; kwota: 2000 zł</w:t></w:r></w:p></w:body></w:document>')
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("word/document.xml", xml)
        text = extract_text(p)
        self.assertIn("Umowa najmu", text)
        self.assertIn("Strona & kwota: 2000 zł", text)
        self.assertNotIn("<w:", text)

    def test_zip_bomb_bounded(self):
        # 50 MB zer w document.xml (kompresja ~1000:1) — czytamy najwyżej MAX_READ.
        from tars_memory import extract as ex
        f = self.inbox / "bomba.docx"
        with zipfile.ZipFile(f, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("word/document.xml", b"<w:t>a</w:t>" + b" " * (50 * 1024 * 1024))
        real_read = zipfile.ZipFile.read
        with mock.patch.object(zipfile.ZipFile, "read", side_effect=AssertionError("pełny odczyt wpisu")):
            self.assertEqual(extract_text(f), "a")
        self.assertIs(zipfile.ZipFile.read, real_read)
        import zlib
        pdf = self.inbox / "bomba.pdf"
        pdf.write_bytes(b"%PDF-1.4\nstream\n" + zlib.compress(b" " * (40 * 1024 * 1024) + b"BT (Hej) Tj ET")
                        + b"\nendstream\n")
        # Strumień rozpakowany tylko do MAX_READ — tekst za 40 MB zer nie jest już osiągalny.
        self.assertEqual(extract_text(pdf), "")
        ok = self.inbox / "ok.pdf"
        ok.write_bytes(b"%PDF-1.4\nstream\n" + zlib.compress(b"BT (Hej) Tj ET") + b"\nendstream\n")
        with mock.patch.object(ex, "MAX_READ", 1024):
            self.assertEqual(extract_text(ok), "Hej")

    def test_text_html_binary_pdf(self):
        self.assertEqual(extract_text(self.put("a.md", "# Tytuł\nżółć" * 1000), limit=50)[:7], "# Tytuł")
        self.assertEqual(len(extract_text(self.put("b.txt", "x" * 9000))), 4000)
        html = self.put("c.html", "<html><head><style>p{}</style></head><body><p>Cześć&nbsp;<b>świecie</b></p>"
                                  "<script>alert(1)</script></body></html>")
        t = extract_text(html)
        self.assertIn("Cześć", t)
        self.assertIn("świecie", t)
        self.assertNotIn("alert", t)
        self.assertEqual(extract_text(self.put("d.jpg", b"\xff\xd8\xff\xe0")), "")
        self.assertEqual(extract_text(self.put("e.docx", b"zepsuty")), "")
        pdf = b"%PDF-1.4\n1 0 obj<<>>stream\nBT /F1 12 Tf (Faktura nr 7) Tj ET\nendstream\n%%EOF"
        self.assertIn("Faktura nr 7", extract_text(self.put("f.pdf", pdf)))
        self.assertEqual(extract_text(self.inbox / "brak.txt"), "")


class TestListing(Base):
    def setUp(self):
        super().setUp()
        now = time.time()
        spec = [("plik10.txt", "", 300, 1), ("plik2.txt", "", 100, 3), ("Ćma.jpg", "Obrazy", 5000, 2),
                ("zebra.pdf", "Dokumenty/Umowy", 50, 5), ("ananas.mp3", "Audio", 10, 4), ("Łódź.png", "Obrazy", 20, 6)]
        for name, folder, size, age in spec:
            p = self.put(name, b"x" * size, base=self.root / folder if folder else self.root)
            os.utime(p, (now - age * 100, now - age * 100))
        self.put(LOG_NAME, "{}", base=self.root)

    def names(self, **kw):
        return [i.name for i in list_items(self.root, **kw)]

    def test_natural_and_polish_name_sort(self):
        self.assertEqual(self.names(sort="name"), ["ananas.mp3", "Ćma.jpg", "Łódź.png", "plik2.txt", "plik10.txt", "zebra.pdf"])
        self.assertEqual(self.names(sort="name_desc"), list(reversed(self.names(sort="name"))))
        self.assertLess(natural_key("file2"), natural_key("file10"))
        self.assertLess(natural_key("ala"), natural_key("ąb"))
        self.assertLess(natural_key("ąb"), natural_key("b"))
        self.assertLess(natural_key("Zebra"), natural_key("żaba"))

    def test_each_sort_mode(self):
        self.assertEqual(self.names(sort="recent")[0], "plik10.txt")
        self.assertEqual(self.names(sort="oldest")[0], "Łódź.png")
        self.assertEqual(self.names(sort="size"), ["ananas.mp3", "Łódź.png", "zebra.pdf", "plik2.txt", "plik10.txt", "Ćma.jpg"])
        self.assertEqual(self.names(sort="size_desc")[0], "Ćma.jpg")
        self.assertEqual(self.names(sort="type"), ["ananas.mp3", "zebra.pdf", "plik2.txt", "plik10.txt", "Ćma.jpg", "Łódź.png"])
        self.assertEqual(self.names(sort="folder"), ["plik2.txt", "plik10.txt", "ananas.mp3", "zebra.pdf", "Ćma.jpg", "Łódź.png"])
        with self.assertRaises(ValueError):
            list_items(self.root, sort="losowo")

    def test_search_and_filter(self):
        self.assertEqual(self.names(sort="name", query="LODZ"), ["Łódź.png"])
        self.assertEqual(self.names(sort="name", query="umowy"), ["zebra.pdf"])
        self.assertEqual(self.names(sort="name", query="obrazy cma"), ["Ćma.jpg"])
        self.assertEqual(self.names(sort="name", types=["image"]), ["Ćma.jpg", "Łódź.png"])
        self.assertEqual(self.names(sort="name", types=["Zdjęcia", "audio"]), ["ananas.mp3", "Ćma.jpg", "Łódź.png"])
        self.assertNotIn(LOG_NAME, self.names())


if __name__ == "__main__":
    unittest.main()
