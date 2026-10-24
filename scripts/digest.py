"""Builds the "This Week" digest from the last 7 days of stories, using simple counting rules
(free mode, no AI): biggest theme, most-covered story, money moves, watchlist activity,
rising topics, plus companies worth researching."""
import re
from collections import Counter
from datetime import timedelta

from common import load_yaml, now_utc, parse_iso


def _in_range(item, start, end):
    d = parse_iso(item["published"])
    return start <= d < end


def _fmt_money(usd):
    return f"${usd / 1e9:.1f}B" if usd >= 1e9 else f"${usd / 1e6:.0f}M"


def build_digest(items, profile_terms):
    """items: enriched + clustered stories. profile_terms: compiled regex of high-interest terms."""
    end = now_utc()
    start = end - timedelta(days=7)
    prev_start = start - timedelta(days=7)
    week = [i for i in items if _in_range(i, start, end)]
    prev = [i for i in items if _in_range(i, prev_start, start)]
    cats = load_yaml("categories.yaml")
    watch_names = {w["name"] for g in ("companies", "topics") for w in (load_yaml("watchlist.yaml").get(g) or [])}
    bullets = []
    if not week:
        return {"start": start, "end": end, "bullets": ["No stories collected this week yet."],
                "research": [], "top": [], "count": 0}

    # 1. Biggest theme: category with the most relevant (score >= 5) coverage.
    strong = Counter(i["category"] for i in week if i["score"] >= 5) or Counter(i["category"] for i in week)
    cat, n = strong.most_common(1)[0]
    lead = max((i for i in week if i["category"] == cat), key=lambda i: (i["score"], len(i["also"])))
    names = Counter(w for i in week if i["category"] == cat for w in i["watch"]).most_common(3)
    who = f" Most active: {', '.join(w for w, _ in names)}." if names else ""
    bullets.append({"label": "Biggest theme", "text": f"{cats[cat]['label']} led the week with {n} relevant stories.{who}",
                    "link": lead["link"], "link_text": lead["title"]})

    # 2. Most-covered story (by number of outlets).
    top_cov = max(week, key=lambda i: (len(i["also"]), i["score"]))
    if top_cov["also"]:
        bullets.append({"label": "Most-covered story",
                        "text": f"Picked up by {len(top_cov['also']) + 1} outlets.",
                        "link": top_cov["link"], "link_text": top_cov["title"]})

    # 3. Money moves.
    deals = [i for i in week if i.get("deal")]
    kinds = Counter(i["deal"]["type"] for i in deals)
    if deals:
        nouns = {"Funding": "funding round", "M&A": "M&A deal", "IPO": "IPO", "Layoffs": "layoff report"}
        parts = [f"{kinds[k]} {nouns[k]}{'' if kinds[k] == 1 else 's'}" for k in nouns if kinds[k]]
        biggest = max((i for i in deals if i["deal"].get("amount_usd")), key=lambda i: i["deal"]["amount_usd"], default=None)
        text = "Detected " + ", ".join(parts) + "."
        b = {"label": "Money moves", "text": text}
        if biggest:
            d = biggest["deal"]
            b["text"] += f" Largest stated: {d.get('company') or 'see story'} at {_fmt_money(d['amount_usd'])}" + \
                         (f" ({d['round']})." if d.get("round") else ".")
            b["link"], b["link_text"] = biggest["link"], biggest["title"]
        bullets.append(b)

    # 4. Watchlist activity.
    wc = Counter(w for i in week for w in i["watch"])
    if wc:
        top = wc.most_common(4)
        leader = top[0][0]
        story = max((i for i in week if leader in i["watch"]), key=lambda i: (i["score"], len(i["also"])))
        bullets.append({"label": "Watchlist activity",
                        "text": "Most news: " + ", ".join(f"{w} ({c})" for w, c in top) + f". Top {leader} story:",
                        "link": story["link"], "link_text": story["title"]})

    # 5. Rising topics: high-interest terms mentioned more than last week.
    def term_counts(lst):
        c = Counter()
        for i in lst:
            for m in {m.group(1).lower() for m in profile_terms.finditer(f"{i['title']} {i.get('summary', '')}")}:
                c[re.sub(r"s$", "", m)] += 1
        return c
    now_c, prev_c = term_counts(week), term_counts(prev)
    if prev:
        rising = sorted(((t, c, prev_c.get(t, 0)) for t, c in now_c.items() if c >= 3 and c > prev_c.get(t, 0)),
                        key=lambda x: x[1] - x[2], reverse=True)[:4]
        if rising:
            bullets.append({"label": "Rising topics",
                            "text": "Mentioned more than last week: " +
                                    ", ".join(f"{t} ({c} vs {p})" for t, c, p in rising) + "."})
    if len(bullets) < 5 and now_c:
        bullets.append({"label": "Most-mentioned interests",
                        "text": ", ".join(f"{t} ({c})" for t, c in now_c.most_common(5)) + "."})
    if len(bullets) < 5:
        pol = [i for i in week if i["category"] == "policy"]
        if pol:
            p = max(pol, key=lambda i: i["score"])
            bullets.append({"label": "Policy watch", "text": "Top policy story:", "link": p["link"], "link_text": p["title"]})

    # Companies worth researching: from funding/M&A stories this week, not already on the watchlist,
    # ranked by how relevant the story is to the profile.
    research, seen = [], set()
    for i in sorted(deals, key=lambda i: (-i["score"], -(i["deal"].get("amount_usd") or 0))):
        co = i["deal"].get("target") if i["deal"]["type"] == "M&A" else i["deal"].get("company")
        if not co or co in seen or co in watch_names or i["deal"]["type"] == "Layoffs":
            continue
        seen.add(co)
        d = i["deal"]
        detail = " · ".join(x for x in (d["type"], d.get("amount"), d.get("round"), cats[i["category"]]["short"]) if x)
        research.append({"company": co, "detail": detail, "link": i["link"], "title": i["title"]})
        if len(research) == 3:
            break

    top = sorted(week, key=lambda i: (-i["score"], -len(i["also"])))[:10]
    return {"start": start, "end": end, "bullets": bullets[:5], "research": research, "top": top, "count": len(week)}

