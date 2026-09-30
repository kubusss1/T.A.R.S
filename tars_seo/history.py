"""Historia audytów: zapis migawek JSON i trend („co się poprawiło, co zepsuło”).

Folder: zmienna ``TARS_SEO_DIR`` (domyślnie ``./seo_history``).
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from .fetch import normalize_url

BAD = ("warning", "critical")


def history_dir(directory: str | os.PathLike | None = None) -> Path:
    return Path(directory or os.environ.get("TARS_SEO_DIR") or "seo_history")


def url_slug(url: str) -> str:
    """Bezpieczna (także na Windows) nazwa pliku z adresu URL."""
    try:
        url = normalize_url(url)
    except ValueError:
        pass
    p = urlsplit(url)
    host = (p.hostname or "strona").lower()
    host = host[4:] if host.startswith("www.") else host
    path = p.path.strip("/")
    raw = host + ("_" + path if path else "") + ("_" + p.query if p.query else "")
    slug = re.sub(r"[^a-z0-9._-]+", "-", raw.lower()).strip("-._")
    return slug[:100] or "strona"


def save_audit(result: dict, directory: str | os.PathLike | None = None,
               now: datetime | None = None) -> Path:
    """Zapisuje wynik audytu jako ``<slug>__<czas>.json``; zwraca ścieżkę."""
    folder = history_dir(directory)
    folder.mkdir(parents=True, exist_ok=True)
    now = now or datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%d-%H%M%S-%f")
    data = dict(result)
    data["saved_at"] = now.isoformat()
    path = folder / f"{url_slug(result.get('url') or '')}__{stamp}.json"
    n = 1
    while path.exists():
        path = folder / f"{url_slug(result.get('url') or '')}__{stamp}-{n}.json"
        n += 1
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_history(url: str, directory: str | os.PathLike | None = None) -> list[dict]:
    """Wszystkie zapisane audyty danego adresu, od najstarszego."""
    folder = history_dir(directory)
    if not folder.is_dir():
        return []
    slug = url_slug(url)
    items = []
    for f in folder.glob(f"{slug}__*.json"):
        try:
            items.append(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    items.sort(key=lambda d: d.get("saved_at") or d.get("audited_at") or "")
    return items


def diff_checks(old: dict, new: dict) -> dict:
    """Co naprawiono (było źle → ok) i co się zepsuło (było ok → źle)."""
    old_c = {c["id"]: c for c in old.get("checks") or []}
    new_c = {c["id"]: c for c in new.get("checks") or []}
    fixed, broken, worse, better = [], [], [], []
    for cid, nc in new_c.items():
        oc = old_c.get(cid)
        if not oc:
            continue
        if oc["level"] in BAD and nc["level"] == "ok":
            fixed.append({"id": cid, "title": nc["title"], "was": oc["title"]})
        elif oc["level"] == "ok" and nc["level"] in BAD:
            broken.append({"id": cid, "title": nc["title"], "level": nc["level"]})
        elif oc["level"] == "warning" and nc["level"] == "critical":
            worse.append({"id": cid, "title": nc["title"]})
        elif oc["level"] == "critical" and nc["level"] == "warning":
            better.append({"id": cid, "title": nc["title"]})
    return {"fixed": fixed, "broken": broken, "worse": worse, "better": better}


def trend(url: str, directory: str | os.PathLike | None = None,
          current: dict | None = None) -> dict:
    """Zmiana wyniku od poprzedniego audytu.

    Bez ``current`` porównuje dwa ostatnie zapisane audyty; z ``current`` —
    ostatni zapisany z bieżącym (niezapisanym) wynikiem.
    """
    items = load_history(url, directory)
    if current is not None:
        if items and items[-1].get("audited_at") == current.get("audited_at") \
                and items[-1].get("score") == current.get("score"):
            items = items[:-1]  # bieżący już zapisany — porównaj z wcześniejszym
        items = items + [current]
    out = {"url": url, "count": len(items), "history": [
        {"date": (d.get("saved_at") or d.get("audited_at") or "")[:19], "score": d.get("score"),
         "grade": d.get("grade")} for d in items]}
    if len(items) < 2:
        out.update({"previous": None, "latest": items[-1] if items else None, "delta": None,
                    "fixed": [], "broken": [], "worse": [], "better": [],
                    "message": "Za mało audytów do porównania — zapisz kolejny (--save)."})
        if items:
            out["latest"] = out["history"][-1]
        return out
    prev, last = items[-2], items[-1]
    delta = (last.get("score") or 0) - (prev.get("score") or 0)
    out.update({"previous": out["history"][-2], "latest": out["history"][-1], "delta": delta,
                **diff_checks(prev, last)})
    if delta > 0:
        out["message"] = f"Wynik wzrósł o {delta} pkt."
    elif delta < 0:
        out["message"] = f"Wynik spadł o {-delta} pkt."
    else:
        out["message"] = "Wynik bez zmian."
    return out
