"""Stage 3: turn the saved JSON into the static website in _site/.

Run:  python scripts/build_site.py      then open _site/index.html in a browser.
"""
import json
import re
import shutil
import sys
from collections import Counter
from datetime import timedelta
from email.utils import format_datetime
from xml.sax.saxutils import escape

from jinja2 import Environment, FileSystemLoader, select_autoescape

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from common import (DATA_DIR, ITEMS_DIR, ROOT, SITE_DIR, load_config, load_yaml, now_utc, parse_iso,
                    read_json, tz)
from digest import build_digest
from enrich import CATEGORY_ORDER, enrich_all, load_rules
from radar import company_radar

NAV = [("index", "Brief"), ("stories", "Stories"), ("watchlist", "Watchlist"), ("week", "This Week"),
       ("funding", "Funding"), ("archive", "Archive"), ("saved", "Saved")]


def local(iso):
    return parse_iso(iso).astimezone(tz()) if isinstance(iso, str) else iso.astimezone(tz())


def fmt_date(value):
    return local(value).strftime("%b %-d")


def card_json(i):
    """Minimal item data stored in the browser when the user saves a story."""
    keep = ("id", "title", "link", "source", "published", "category", "score", "summary", "why")
    return json.dumps({k: i.get(k) for k in keep}, ensure_ascii=False).replace("'", "&#39;").replace("<", "\\u003c")


def pick_brief(items, n):
    """Top stories by score, keeping variety: max 1 per watchlist company, max 3 per category."""
    chosen, cos, cats = [], set(), Counter()
    # `items` arrive newest-first; the stable sort keeps newer stories ahead on ties.
    for i in sorted(items, key=lambda i: (-i["score"], -len(i["also"]))):
        if cats[i["category"]] >= 3 or (set(i["watch"]) & cos):
            continue
        chosen.append(i)
        cos |= set(i["watch"])
        cats[i["category"]] += 1
        if len(chosen) == n:
            break
    return chosen


def write_feed(cfg, items, now):
    """_site/feed.xml: an RSS feed of my top stories, for any feed reader."""
    site = cfg.get("site_url", "").rstrip("/") + "/"
    cutoff = now - timedelta(days=7)
    top = [i for i in items if i["score"] >= cfg.get("feed_min_score", 6) and parse_iso(i["published"]) >= cutoff]
    entries = []
    for i in sorted(top, key=lambda i: i["published"], reverse=True)[:60]:
        desc = (i.get("summary") or "") + f"<p><b>Why it's here:</b> {i['why']} (score {i['score']}/10)</p>"
        entries.append(
            "<item>"
            f"<title>{escape(i['title'])}</title>"
            f"<link>{escape(i['link'])}</link>"
            f"<guid isPermaLink=\"false\">{i['id']}</guid>"
            f"<pubDate>{format_datetime(parse_iso(i['published']))}</pubDate>"
            f"<category>{escape(i['category'])}</category>"
            f"<source url=\"{escape(site)}feed.xml\">{escape(i['source'])}</source>"
            f"<description>{escape(desc)}</description>"
            "</item>")
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom"><channel>'
           f"<title>{escape(cfg['site_title'])}</title><link>{escape(site)}</link>"
           f"<atom:link href=\"{escape(site)}feed.xml\" rel=\"self\" type=\"application/rss+xml\"/>"
           f"<description>{escape(cfg.get('site_tagline', ''))}</description>"
           f"<lastBuildDate>{format_datetime(now)}</lastBuildDate>" + "".join(entries) + "</channel></rss>\n")
    (SITE_DIR / "feed.xml").write_text(xml, encoding="utf-8")


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def build():
    cfg = load_config()
    cats = {k: load_yaml("categories.yaml")[k] for k in CATEGORY_ORDER}
    now = now_utc()
    min_score = cfg.get("min_score_to_show", 3)

    files = sorted(ITEMS_DIR.glob("*.json"))
    window = files[-cfg.get("site_window_days", 60):]
    raw = [it for f in window for it in read_json(f, [])]
    items = enrich_all(raw)
    items.sort(key=lambda i: i["published"], reverse=True)
    visible = [i for i in items if i["score"] >= min_score]

    last_run = read_json(DATA_DIR / "last_run.json", None)
    updated = parse_iso(last_run["finished_at"]) if last_run else now
    week_ago = now - timedelta(days=7)
    this_week = [i for i in visible if parse_iso(i["published"]) >= week_ago]

    # Today's Brief: newest 2 days, widened if it's a slow news day.
    for days in (2, 4, 7):
        recent = [i for i in visible if parse_iso(i["published"]) >= now - timedelta(days=days)]
        if len(recent) >= cfg.get("brief_size", 7) * 2:
            break
    brief = pick_brief(recent, cfg.get("brief_size", 7))
    brief_window = "48 hours" if days == 2 else f"{days} days"

    env = Environment(loader=FileSystemLoader(ROOT / "templates"), autoescape=select_autoescape(["html"]))
    env.filters["fmt_date"] = fmt_date
    env.globals["card_json"] = card_json
    common = {"cfg": cfg, "cats": cats, "nav": NAV, "last_run": last_run, "build_id": now.strftime("%Y%m%d%H%M"),
              "updated_str": local(updated).strftime("%a %b %-d, %Y at %-I:%M %p %Z")}

    if SITE_DIR.exists():
        shutil.rmtree(SITE_DIR)
    (SITE_DIR / "category").mkdir(parents=True)
    (SITE_DIR / "archive").mkdir()
    shutil.copytree(ROOT / "static", SITE_DIR / "static")

    def render(template, out, page, root="", **ctx):
        html = env.get_template(template).render(page=page, root=root, title=ctx.pop("title", None), **common, **ctx)
        (SITE_DIR / out).write_text(html, encoding="utf-8")

    # Home
    tiles = {}
    for slug in CATEGORY_ORDER:
        lst = [i for i in this_week if i["category"] == slug]
        tiles[slug] = {"count": len(lst), "top": max(lst, key=lambda i: i["score"], default=None)}
    render("index.html", "index.html", "index", brief=brief, brief_window=brief_window, tiles=tiles,
           today_str=local(now).strftime("%A, %B %-d, %Y"))

    # Stories data for search / category pages
    slim = [{k: i.get(k) for k in ("id", "title", "link", "source", "published", "category", "secondary",
                                   "score", "summary", "why", "watch")} | {"also": i["also"][:8]} for i in visible]
    (SITE_DIR / "stories.json").write_text(json.dumps(slim, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    render("stories.html", "stories.html", "stories", title="All Stories")

    for slug, c in cats.items():
        in_cat = [i for i in visible if i["category"] == slug or slug in i["secondary"]]
        cos = Counter(w for i in in_cat for w in i["watch"]).most_common(3)
        week_n = sum(parse_iso(i["published"]) >= week_ago for i in in_cat)
        stats = {"week": week_n, "total": len(in_cat), "companies": [w for w, _ in cos]}
        render("category.html", f"category/{slug}.html", "category", root="../", title=c["label"],
               slug=slug, cat=c, stats=stats)

    # Watchlist
    wl = load_yaml("watchlist.yaml")
    def watch_rows(group):
        rows = []
        for w in wl.get(group, []) or []:
            if group == "companies":
                lst = [i for i in items if w["name"] in i["watch"] or w["name"] in i["watch_weak"]]
            else:
                lst = [i for i in items if i.get("watch_query") == w["name"]]
            lst.sort(key=lambda i: i["published"], reverse=True)
            rows.append({"name": w["name"], "anchor": slugify(w["name"]), "category": w.get("category"),
                         "items": lst, "week": sum(parse_iso(i["published"]) >= week_ago for i in lst)})
        return rows
    render("watchlist.html", "watchlist.html", "watchlist", title="Watchlist",
           companies=watch_rows("companies"), topics=watch_rows("topics"), radar=company_radar(visible))

    # This Week
    digest = build_digest(visible, load_rules()[2]["high"])
    render("week.html", "week.html", "week", title="This Week", digest=digest)

    # Funding tracker
    deals = [i for i in items if i.get("deal")]
    render("funding.html", "funding.html", "funding", title="Funding Tracker", deals=deals)

    # Archive: one page per daily file (all files, not just the window)
    days = []
    for f in reversed(files):
        day_items = enrich_all(read_json(f, []))
        day_items = [i for i in day_items if i["score"] >= min_score]
        from datetime import date
        d = date.fromisoformat(f.stem)
        label = d.strftime("%A, %B %-d, %Y")
        groups = []
        for slug in CATEGORY_ORDER:
            lst = sorted((i for i in day_items if i["category"] == slug), key=lambda i: -i["score"])
            if lst:
                groups.append((slug, lst))
        top = max(day_items, key=lambda i: i["score"], default=None)
        days.append({"date": f.stem, "label": label, "count": len(day_items), "top": top["title"] if top else ""})
        render("archive_day.html", f"archive/{f.stem}.html", "archive", root="../", title=label,
               day_label=label, groups=groups, count=len(day_items))
    render("archive.html", "archive.html", "archive", title="Archive", days=days)

    write_feed(cfg, visible, now)
    render("saved.html", "saved.html", "saved", title="Saved")
    render("status.html", "status.html", "status", title="Status")
    (SITE_DIR / ".nojekyll").write_text("")

    print(f"Built site: {len(visible)} stories shown ({len(items)} on-topic), brief of {len(brief)}, "
          f"{len(deals)} deals, {len(days)} archive days → {SITE_DIR.relative_to(ROOT)}/")


if __name__ == "__main__":
    build()
