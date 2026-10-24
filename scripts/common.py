"""Shared helpers: file paths, config loading, dates, text cleanup."""
import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
ITEMS_DIR = DATA_DIR / "items"
SITE_DIR = ROOT / "_site"


def load_yaml(name):
    with open(ROOT / name, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_config():
    return load_yaml("config.yaml")


def tz():
    return ZoneInfo(load_config().get("timezone", "America/New_York"))


def now_utc():
    return datetime.now(timezone.utc)


def local_today():
    return now_utc().astimezone(tz()).date()


def parse_iso(s):
    return datetime.fromisoformat(s)


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_INVISIBLE_RE = re.compile("[\u200b-\u200f\u2060\ufeff\u00ad]")


def clean_text(s):
    """Strip HTML tags/entities and collapse whitespace."""
    if not s:
        return ""
    s = _TAG_RE.sub(" ", s)
    s = _INVISIBLE_RE.sub("", html.unescape(s))
    return _WS_RE.sub(" ", s).strip()


def truncate(s, limit=280):
    """Cut text to roughly `limit` chars, preferring a sentence or word boundary."""
    if len(s) <= limit:
        return s
    cut = s[:limit]
    period = cut.rfind(". ")
    if period > limit * 0.5:
        return cut[: period + 1]
    return cut.rsplit(" ", 1)[0].rstrip(",;:") + "…"


def norm_title(t):
    t = t.lower()
    t = re.sub(r"[^a-z0-9$ ]+", " ", t)
    return _WS_RE.sub(" ", t).strip()


def load_all_items(days=None):
    """Load items from the daily archive files, newest file first."""
    files = sorted(ITEMS_DIR.glob("*.json"), reverse=True)
    if days is not None:
        files = files[:days]
    items = []
    for f in files:
        items.extend(read_json(f, []))
    return items
