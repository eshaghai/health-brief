"""Stage 1: fetch RSS feeds + Google News searches, clean and dedupe, save today's items.

Run:  python scripts/ingest.py
Output: data/items/YYYY-MM-DD.json (new items first seen today) and data/last_run.json (feed health).
A broken feed is logged and skipped; it never stops the run.
"""
import hashlib
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, quote_plus, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import feedparser
import requests

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from common import (DATA_DIR, ITEMS_DIR, clean_text, load_config, load_yaml, local_today,
                    norm_title, now_utc, read_json, truncate, write_json)

USER_AGENT = "Mozilla/5.0 (compatible; HealthBrief/1.0; personal news reader)"

# Headlines matching these are almost never useful news.
JUNK_PATTERNS = [
    r"\bbest\b.*\b(deals?|sales?)\b", r"\bdeals?\b.*\b(today|this week|black friday|prime day)\b",
    r"\b\d+% off\b", r"\bcoupon\b", r"\bpromo code\b", r"\bsponsored\b", r"\bwebinar\b",
    r"\bwordle\b", r"\bhoroscope\b", r"^\s*(watch|listen):", r"\bpodcast\b",
    r"\bjob (opening|posting)s?\b", r"\bpress release distribution\b",
    # law-firm shareholder spam
    r"securities (fraud|class action)", r"class action (lawsuit|filed)", r"\bshareholder alert\b",
    r"\binvestor alert\b", r"investors (have|who lost)", r"\blead plaintiff\b", r"\blaw firm\b",
    r"\b(rosen|pomerantz|bragar|faruqi|levi & korsinsky|bernstein liebhard|gross law|schall)\b",
    # shopping posts
    r"\bprice (cut|drop)\b", r"\blowest price\b", r"\bon sale\b", r"\bdeal alert\b",
    r"\bsave \$\d+", r"\bdiscount(ed)?\b.*\$\d",
]
JUNK_RE = re.compile("|".join(JUNK_PATTERNS), re.I)
TRACKING_PARAMS = re.compile(r"^(utm_|fbclid|gclid|mc_|ref$|cmpid|ncid|taid|sr_share|cid$)", re.I)


def normalize_url(url):
    parts = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query) if not TRACKING_PARAMS.match(k)]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(("https", parts.netloc.lower().removeprefix("www."), path, urlencode(query), ""))


def item_id(url):
    return hashlib.sha1(normalize_url(url).encode()).hexdigest()[:12]


def google_news_url(query, cfg):
    gn = cfg.get("google_news", {})
    lang = gn.get("language", "en-US")
    country = gn.get("country", "US")
    q = quote_plus(f"{query} when:{cfg.get('max_age_days', 7)}d")
    return f"https://news.google.com/rss/search?q={q}&hl={lang}&gl={country}&ceid={country}:{lang.split('-')[0]}"


def fetch(url, timeout):
    """Return (parsed_feed, error_message). Retries once on failure."""
    last_err = None
    for attempt in range(2):
        try:
            r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
            r.raise_for_status()
            feed = feedparser.parse(r.content)
            if not feed.entries and feed.bozo:
                raise ValueError(f"not a valid feed ({feed.bozo_exception})")
            return feed, None
        except Exception as e:  # any failure: network, HTTP error, bad XML
            last_err = f"{type(e).__name__}: {e}"[:200]
            time.sleep(2)
    return None, last_err


def entry_date(entry):
    t = entry.get("published_parsed") or entry.get("updated_parsed")
    if t:
        return datetime(*t[:6], tzinfo=timezone.utc)
    # Some feeds (e.g. Fierce) use non-standard dates like "Jan 7, 2026 3:20pm" (US Eastern).
    raw = (entry.get("published") or entry.get("updated") or "").strip()
    for fmt in ("%b %d, %Y %I:%M%p", "%B %d, %Y %I:%M%p", "%b %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=ZoneInfo("America/New_York")).astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def entry_to_item(entry, source):
    link = entry.get("link") or ""
    title = clean_text(entry.get("title", ""))
    publisher = source["name"]
    if source["kind"] == "google_news":
        # Google News titles look like "Headline - Publisher"; split them.
        src = entry.get("source") or {}
        publisher = src.get("title") or publisher
        if " - " in title:
            head, tail = title.rsplit(" - ", 1)
            if not src.get("title") or tail.strip() == publisher:
                title, publisher = head.strip(), tail.strip()
    summary = clean_text(entry.get("summary", ""))
    # Drop teasers that just repeat the headline (common with Google News).
    if norm_title(summary).startswith(norm_title(title)[:40]) or len(summary) < 40:
        summary = ""
    published = entry_date(entry)
    return {
        "id": item_id(link),
        "title": title,
        "link": link,
        "source": publisher,
        "via": source["name"],
        "origin": source["kind"],
        "watch_query": source.get("watch_name"),
        "published": published.isoformat() if published else None,
        "summary": truncate(summary, 300),
    }


def is_junk(item):
    t = item["title"]
    # all-lowercase headlines come from SEO/content-farm sites
    return len(t) < 15 or t == t.lower() or bool(JUNK_RE.search(t))


def similar(a, b):
    """Near-duplicate check on normalized titles."""
    ta, tb = set(a.split()), set(b.split())
    if not ta or not tb:
        return False
    jaccard = len(ta & tb) / len(ta | tb)
    if jaccard < 0.45:
        return False
    return jaccard > 0.75 or SequenceMatcher(None, a, b).ratio() > 0.85


def dedupe(items, known_ids, known_titles):
    """Drop items already seen (by URL) or whose headline nearly matches one already kept.
    Direct publisher feeds are preferred over Google News copies of the same story."""
    items = sorted(items, key=lambda i: i["origin"] != "feed")
    kept, kept_titles = [], list(known_titles)
    seen_ids = set(known_ids)
    for it in items:
        if it["id"] in seen_ids:
            continue
        nt = norm_title(it["title"])
        if any(similar(nt, kt) for kt in kept_titles):
            continue
        seen_ids.add(it["id"])
        kept_titles.append(nt)
        kept.append(it)
    return kept


def build_source_list(cfg):
    sources = []
    for s in load_yaml("sources.yaml").get("sources", []) or []:
        if not s.get("enabled", True):
            continue
        if s.get("url"):
            sources.append({"name": s["name"], "url": s["url"], "kind": "feed",
                            "category": s.get("category")})
        elif s.get("google_news"):
            # Publisher without a usable feed: read its headlines via a Google News search.
            sources.append({"name": s["name"], "url": google_news_url(s["google_news"], cfg),
                            "kind": "google_news", "category": s.get("category")})
    if cfg.get("google_news", {}).get("enabled", True):
        wl = load_yaml("watchlist.yaml")
        for group in ("companies", "topics"):
            for w in wl.get(group, []) or []:
                query = w.get("query") or f'"{w["name"]}"'
                sources.append({"name": f"Google News: {w['name']}", "url": google_news_url(query, cfg),
                                "kind": "google_news", "watch_name": w["name"],
                                "category": w.get("category")})
    return sources


def run():
    cfg = load_config()
    timeout = cfg.get("request_timeout_seconds", 20)
    per_feed = cfg.get("max_items_per_feed", 40)
    cutoff = now_utc() - timedelta(days=cfg.get("max_age_days", 7))
    sources = build_source_list(cfg)
    print(f"Fetching {len(sources)} sources…")

    def work(src):
        feed, err = fetch(src["url"], timeout)
        return src, feed, err

    raw, health = [], []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for src, feed, err in pool.map(work, sources):
            if err:
                print(f"  ✗ {src['name']}: {err}")
                health.append({"name": src["name"], "kind": src["kind"], "ok": False, "error": err, "items": 0})
                continue
            recent = []
            for entry in feed.entries:
                it = entry_to_item(entry, src)
                if not it["link"] or not it["title"]:
                    continue
                pub = it["published"]
                if pub and datetime.fromisoformat(pub) < cutoff:
                    continue
                it["category_hint"] = src.get("category")
                recent.append(it)
            # Newest first, capped per feed (some feeds list hundreds of items in no particular order).
            recent.sort(key=lambda i: i["published"] or "", reverse=True)
            raw.extend(recent[:per_feed])
            got = min(len(recent), per_feed)
            health.append({"name": src["name"], "kind": src["kind"], "ok": True, "error": None, "items": got})
            print(f"  ✓ {src['name']}: {got} recent items")

    before = len(raw)
    raw = [i for i in raw if not is_junk(i)]
    junk = before - len(raw)

    # Compare against the last 14 days of saved items so the same story isn't added twice.
    today = local_today()
    known_ids, known_titles = set(), []
    for f in sorted(ITEMS_DIR.glob("*.json"), reverse=True)[:14]:
        for it in read_json(f, []):
            known_ids.add(it["id"])
            known_titles.append(norm_title(it["title"]))

    new = dedupe(raw, known_ids, known_titles)
    stamp = now_utc().isoformat()
    for it in new:
        it["first_seen"] = stamp
        if not it["published"]:
            it["published"] = stamp
            it["date_estimated"] = True

    out_path = ITEMS_DIR / f"{today.isoformat()}.json"
    existing = read_json(out_path, [])
    write_json(out_path, existing + new)

    ok = sum(1 for h in health if h["ok"])
    summary = {"finished_at": stamp, "sources_total": len(health), "sources_ok": ok,
               "fetched": before, "junk_dropped": junk, "duplicates_dropped": before - junk - len(new),
               "new_items": len(new), "sources": sorted(health, key=lambda h: (h["ok"], h["name"]))}
    write_json(DATA_DIR / "last_run.json", summary)
    print(f"\nSources OK: {ok}/{len(health)} | fetched {before} | junk {junk} | "
          f"dupes {summary['duplicates_dropped']} | NEW {len(new)} → {out_path.relative_to(DATA_DIR.parent)}")
    return summary


if __name__ == "__main__":
    run()
