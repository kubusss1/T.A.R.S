"""Wyciąganie danych SEO z HTML-a (``html.parser`` z biblioteki standardowej)."""
from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

WORD_RE = re.compile(r"[^\W\d_]+(?:['’-][^\W\d_]+)*", re.UNICODE)

_SKIP_TEXT = {"script", "style", "noscript", "template", "svg", "iframe", "object", "canvas"}
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
         "param", "source", "track", "wbr"}
_BLOCK = {"p", "div", "li", "br", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "td", "th",
          "section", "article", "header", "footer", "nav", "main", "aside", "ul", "ol",
          "table", "blockquote", "figcaption", "dd", "dt", "form", "label", "option"}
_ACTIVE_MIXED = {"script", "iframe", "embed", "object"}
_PASSIVE_MIXED = {"img", "audio", "video", "source", "track"}


def _host(url: str) -> str:
    try:
        h = (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""
    return h[4:] if h.startswith("www.") else h


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


class _SEOParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.page_https = base_url.lower().startswith("https://")
        self.d: dict = {
            "title": None, "title_count": 0, "meta_description": None, "canonical": None,
            "robots_meta": None, "lang": None, "viewport": None, "charset": None,
            "headings": [], "images": [], "links": [], "og": {}, "twitter": {},
            "jsonld_raw": [], "hreflang": [], "favicon": None, "mixed_content": [],
            "inline_script_bytes": 0, "inline_style_bytes": 0, "inline_scripts": 0,
            "inline_styles": 0, "external_scripts": 0, "external_styles": 0,
            "tel_links": [], "base_href": None,
        }
        self._stack_skip = 0
        self._in_title = False
        self._title_buf: list[str] = []
        self._in_svg = 0
        self._heading: list | None = None
        self._anchor: dict | None = None
        self._script: dict | None = None
        self._in_style = False
        self._text: list[str] = []

    # --- pomocnicze -------------------------------------------------------
    def _abs(self, url: str) -> str:
        return urljoin(self.d["base_href"] or self.base_url, (url or "").strip())

    def _mixed(self, tag: str, url: str | None) -> None:
        if self.page_https and url and url.strip().lower().startswith("http://"):
            kind = "active" if tag in _ACTIVE_MIXED or tag == "link" else "passive"
            self.d["mixed_content"].append({"tag": tag, "url": url.strip(), "kind": kind})

    def _finish_anchor(self) -> None:
        a = self._anchor
        if a is None:
            return
        self._anchor = None
        text = _clean("".join(a["text"]))
        href = a["href"]
        low = (href or "").strip().lower()
        if href is None or low in ("", "#") or low.startswith("javascript:"):
            kind = "empty"
        elif low.startswith(("mailto:", "tel:", "sms:")):
            kind = "contact"
            if low.startswith("tel:"):
                self.d["tel_links"].append(href.strip()[4:])
        elif low.startswith("#"):
            kind = "anchor"
        else:
            absu = self._abs(href)
            kind = "internal" if _host(absu) == _host(self.base_url) else "external"
            href = absu
        label = text or a["img_alt"] or a["aria"]
        self.d["links"].append({
            "href": href, "text": text, "kind": kind, "nofollow": a["nofollow"],
            "empty_text": not label,
        })

    # --- zdarzenia parsera ------------------------------------------------
    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        a = {k.lower(): (v if v is not None else "") for k, v in attrs}
        if tag in _BLOCK:
            self._text.append(" ")
            if self._anchor is not None:
                self._anchor["text"].append(" ")
        if tag == "svg":
            self._in_svg += 1
        if tag in _SKIP_TEXT and tag not in _VOID:
            self._stack_skip += 1
        if tag == "html" and a.get("lang"):
            self.d["lang"] = a["lang"].strip() or None
        elif tag == "base" and a.get("href") and not self.d["base_href"]:
            self.d["base_href"] = urljoin(self.base_url, a["href"])
        elif tag == "title" and not self._in_svg:
            self._in_title = True
            self._title_buf = []
            self.d["title_count"] += 1
        elif tag == "meta":
            self._meta(a)
        elif tag == "link":
            self._link(a)
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._heading = [int(tag[1]), []]
        elif tag == "img":
            src = a.get("src") or a.get("data-src") or a.get("data-lazy-src") or ""
            self.d["images"].append({
                "src": src,
                "alt": a.get("alt") if "alt" in a else None,
                "has_dimensions": bool(a.get("width")) and bool(a.get("height")),
                "lazy": a.get("loading", "").lower() == "lazy"
                        or "data-src" in a or "lazyload" in a.get("class", ""),
            })
            if self._anchor is not None and a.get("alt"):
                self._anchor["img_alt"] = a["alt"].strip()
            self._mixed("img", a.get("src"))
        elif tag == "a":
            self._finish_anchor()
            rel = a.get("rel", "").lower().split()
            self._anchor = {"href": a.get("href") if "href" in a else None, "text": [],
                            "img_alt": "", "aria": (a.get("aria-label") or a.get("title") or "").strip(),
                            "nofollow": "nofollow" in rel}
        elif tag == "script":
            typ = a.get("type", "").lower()
            if "src" in a:
                self.d["external_scripts"] += 1
                self._mixed("script", a.get("src"))
                self._script = None
            else:
                self._script = {"type": typ, "buf": []}
        elif tag == "style":
            self._in_style = True
            self.d["inline_styles"] += 1
        elif tag in ("iframe", "embed", "object", "audio", "video", "source", "track"):
            self._mixed(tag, a.get("src") or a.get("data"))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag.lower() not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in _BLOCK:
            self._text.append(" ")
        if tag in _SKIP_TEXT and tag not in _VOID and self._stack_skip > 0:
            self._stack_skip -= 1
        if tag == "svg" and self._in_svg:
            self._in_svg -= 1
        if tag == "title" and self._in_title:
            self._in_title = False
            if self.d["title"] is None:
                self.d["title"] = _clean("".join(self._title_buf))
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6") and self._heading:
            level, buf = self._heading
            self.d["headings"].append({"level": level, "text": _clean("".join(buf))})
            self._heading = None
        elif tag == "a":
            self._finish_anchor()
        elif tag == "script" and self._script is not None:
            content = "".join(self._script["buf"])
            if "ld+json" in self._script["type"]:
                self.d["jsonld_raw"].append(content)
            elif content.strip():
                self.d["inline_scripts"] += 1
                self.d["inline_script_bytes"] += len(content.encode("utf-8"))
            self._script = None
        elif tag == "style":
            self._in_style = False

    def handle_data(self, data):
        if self._in_title:
            self._title_buf.append(data)
            return
        if self._script is not None:
            self._script["buf"].append(data)
            return
        if self._in_style:
            self.d["inline_style_bytes"] += len(data.encode("utf-8"))
            return
        if self._stack_skip:
            return
        if self._heading is not None:
            self._heading[1].append(data)
        if self._anchor is not None:
            self._anchor["text"].append(data)
        self._text.append(data)

    def _meta(self, a: dict) -> None:
        name = (a.get("name") or "").strip().lower()
        prop = (a.get("property") or "").strip().lower()
        content = a.get("content", "")
        if a.get("charset"):
            self.d["charset"] = a["charset"]
        if name == "description" and self.d["meta_description"] is None:
            self.d["meta_description"] = _clean(content)
        elif name in ("robots", "googlebot") and content:
            prev = self.d["robots_meta"]
            self.d["robots_meta"] = f"{prev}, {content}" if prev else content.strip()
        elif name == "viewport":
            self.d["viewport"] = content.strip()
        if prop.startswith("og:"):
            self.d["og"].setdefault(prop, _clean(content))
        key = name if name.startswith("twitter:") else prop if prop.startswith("twitter:") else ""
        if key:
            self.d["twitter"].setdefault(key, _clean(content))

    def _link(self, a: dict) -> None:
        rel = (a.get("rel") or "").lower().split()
        href = a.get("href", "")
        if "canonical" in rel and self.d["canonical"] is None and href.strip():
            self.d["canonical"] = self._abs(href)
        if "alternate" in rel and a.get("hreflang"):
            self.d["hreflang"].append({"lang": a["hreflang"], "href": self._abs(href)})
        if "icon" in rel and href and not self.d["favicon"]:
            self.d["favicon"] = self._abs(href)
        if "stylesheet" in rel:
            self.d["external_styles"] += 1
            self._mixed("link", href)
        elif "icon" in rel:
            self._mixed("img", href)

    def result(self) -> dict:
        self._finish_anchor()
        if self._in_title and self.d["title"] is None:
            self.d["title"] = _clean("".join(self._title_buf))
        text = _clean("".join(self._text))
        self.d["text"] = text
        self.d["word_count"] = len(WORD_RE.findall(text))
        return self.d


# --------------------------------------------------------------------------
# JSON-LD
# --------------------------------------------------------------------------

def _types(value) -> list[str]:
    if isinstance(value, str):
        return [value.rsplit("/", 1)[-1]]
    if isinstance(value, list):
        return [t.rsplit("/", 1)[-1] for t in value if isinstance(t, str)]
    return []


def parse_jsonld(blocks: list[str]) -> dict:
    """Parsuje bloki JSON-LD → ``{"entities": [...], "types": [...], "errors": n}``."""
    entities: list[dict] = []
    errors = 0

    def walk(node, depth=0):
        if depth > 12:
            return
        if isinstance(node, list):
            for item in node:
                walk(item, depth + 1)
        elif isinstance(node, dict):
            if "@type" in node:
                entities.append(node)
            for k, v in node.items():
                if k != "@context" and isinstance(v, (dict, list)):
                    walk(v, depth + 1)

    for raw in blocks:
        raw = (raw or "").strip()
        if not raw:
            continue
        raw = re.sub(r"^\s*<!--|-->\s*$", "", raw)
        try:
            walk(json.loads(raw))
        except (ValueError, RecursionError):
            errors += 1
    types: list[str] = []
    for e in entities:
        for t in _types(e.get("@type")):
            if t not in types:
                types.append(t)
    return {"entities": entities, "types": types, "errors": errors}


def parse_html(html_text: str, url: str = "https://example.com/") -> dict:
    """Główna funkcja: HTML → słownik z danymi SEO."""
    p = _SEOParser(url)
    try:
        p.feed(html_text or "")
        p.close()
    except Exception:  # noqa: BLE001 — zepsuty HTML nie może przerwać audytu
        pass
    d = p.result()
    d["url"] = url
    d["h1"] = [h["text"] for h in d["headings"] if h["level"] == 1]
    d["h2"] = [h["text"] for h in d["headings"] if h["level"] == 2]
    d["h3"] = [h["text"] for h in d["headings"] if h["level"] == 3]
    d["jsonld"] = parse_jsonld(d.pop("jsonld_raw"))
    return d
