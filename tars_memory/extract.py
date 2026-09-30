"""Wyciąganie tekstu z plików (tylko stdlib, best-effort)."""
from __future__ import annotations

import html
import re
import zipfile
import zlib
from pathlib import Path

TEXT_EXT = {".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".py", ".log", ".ini", ".cfg", ".toml",
            ".yaml", ".yml", ".xml", ".js", ".ts", ".css", ".sql", ".bat", ".ps1", ".sh", ".rst", ".tex",
            ".c", ".cpp", ".h", ".java", ".cs", ".go", ".rs", ".php", ".rb", ".srt", ".vtt"}
HTML_EXT = {".html", ".htm", ".xhtml"}
ZIP_XML = {  # dokumenty biurowe: zip z XML-em
    ".docx": r"word/document\.xml",
    ".odt": r"content\.xml", ".ods": r"content\.xml", ".odp": r"content\.xml",
    ".pptx": r"ppt/slides/slide\d+\.xml",
    ".xlsx": r"xl/sharedStrings\.xml",
}
MAX_READ = 2 * 1024 * 1024
MAX_PDF = 20 * 1024 * 1024


def _clean(text: str, limit: int) -> str:
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()[:limit]


def _strip_xml(xml: str) -> str:
    xml = re.sub(r"</(w:p|text:p|a:p|p|div|li|tr|h\d|si)>|<br\s*/?>|<w:tab/>", "\n", xml, flags=re.I)
    return html.unescape(re.sub(r"<[^>]+>", " ", xml))


def _strip_html(text: str) -> str:
    text = re.sub(r"<(script|style|head)\b.*?</\1\s*>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    return _strip_xml(text)


def _zip_xml_text(path: Path, pattern: str) -> str:
    with zipfile.ZipFile(path) as zf:
        names = sorted((n for n in zf.namelist() if re.fullmatch(pattern, n)),
                       key=lambda n: [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", n)])
        parts, budget = [], MAX_READ
        for n in names:  # czytamy strumieniowo i z limitem — odporne na „bomby zip”
            if budget <= 0:
                break
            with zf.open(n) as f:
                raw = f.read(budget)
            budget -= len(raw)
            parts.append(_strip_xml(raw.decode("utf-8", "replace")))
        return "\n".join(parts)


def _pdf_literal(raw: bytes) -> str:
    out, i = bytearray(), 0
    esc = {ord("n"): 10, ord("r"): 13, ord("t"): 9, ord("b"): 8, ord("f"): 12}
    while i < len(raw):
        c = raw[i]
        if c == 0x5C and i + 1 < len(raw):  # backslash
            nxt = raw[i + 1]
            m = re.match(rb"[0-7]{1,3}", raw[i + 1:i + 4])
            if m:
                out.append(int(m.group(), 8) & 0xFF)
                i += 1 + len(m.group())
                continue
            out.append(esc.get(nxt, nxt))
            i += 2
            continue
        out.append(c)
        i += 1
    return out.decode("latin-1")


def _pdf_text(path: Path) -> str:
    """Best-effort: literały z operatorów Tj/TJ w (ew. skompresowanych Flate) strumieniach."""
    data = path.read_bytes()[:MAX_PDF]
    parts: list[str] = []
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\n?endstream", data, re.S):
        raw = m.group(1)
        try:
            raw = zlib.decompressobj().decompress(raw, MAX_READ)  # limit — odporne na „bomby”
        except zlib.error:
            pass
        for bt in re.findall(rb"BT(.*?)ET", raw, re.S):
            for s in re.findall(rb"\(((?:\\.|[^\\)])*)\)", bt, re.S):
                parts.append(_pdf_literal(s))
            parts.append("\n")
    text = "".join(parts)
    printable = sum(ch.isprintable() or ch.isspace() for ch in text)
    return text if text and printable / len(text) > 0.9 else ""


def extract_text(path, limit: int = 4000) -> str:
    """Zwraca do `limit` znaków tekstu z pliku; "" dla binariów lub gdy się nie da."""
    p = Path(path)
    ext = p.suffix.lower()
    try:
        if ext in TEXT_EXT:
            with open(p, "rb") as f:
                text = f.read(MAX_READ).decode("utf-8", "replace").lstrip("﻿")
        elif ext in HTML_EXT:
            with open(p, "rb") as f:
                text = _strip_html(f.read(MAX_READ).decode("utf-8", "replace"))
        elif ext in ZIP_XML:
            text = _zip_xml_text(p, ZIP_XML[ext])
        elif ext == ".pdf":
            text = _pdf_text(p)
        else:
            return ""
    except (OSError, zipfile.BadZipFile, KeyError, ValueError, RuntimeError):
        return ""
    return _clean(text, limit)
