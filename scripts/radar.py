"""Company radar: companies that keep showing up in the news but aren't on the watchlist yet.

A "mention" is a headline whose subject is a company doing something newsworthy
("Fay raises...", "Function Health launches...") or a funding/M&A story naming it.
Big incumbents and agencies are ignored (edit `radar_ignore` in watchlist.yaml to mute more).
"""
import re
from collections import defaultdict

from common import load_yaml

# "<Name> <newsworthy verb>" at the start of a headline.
SUBJECT_RE = re.compile(
    r"^(?:[\w+]+:\s+)?(?:(?:health|healthcare|health-tech|healthtech|digital health|wellness|AI|biotech|telehealth|"
    r"wearable|longevity|nutrition|beauty|food|supplement|startup)\s+)*(?:startup|company|brand|platform|app)?\s*"
    r"(?P<name>(?:[A-Z][\w&'.\-]*|[A-Z]{2,})(?:\s+(?:[A-Z][\w&'.\-]*|&|of|for)){0,3})\s+"
    r"(?:raises|raised|lands|secures|closes|launches|debuts|unveils|introduces|rolls out|expands|enters|partners|"
    r"teams up|acquires|buys|to acquire|merges|hires|names|appoints|taps|adds|opens|sues|files|cuts|lays off|"
    r"announces|releases|partners|gets|wins|nabs|bags|snags|scores|reaches|hits|plans|bets)\b")

ALWAYS_IGNORE = {
    # agencies, governments, people
    "FDA", "FTC", "CMS", "HHS", "CDC", "NIH", "WHO", "Medicare", "Medicaid", "Congress", "Senate", "House", "Trump",
    "White House", "RFK", "RFK Jr", "Kennedy", "Biden", "Texas", "California", "UK", "US", "U.S", "EU", "India", "China",
    # mega-caps and incumbents (covered everywhere already)
    "Apple", "Google", "Alphabet", "Amazon", "Microsoft", "Meta", "Samsung", "OpenAI", "Anthropic", "Nvidia", "IBM",
    "Walmart", "Target", "CVS", "CVS Health", "Walgreens", "Costco", "Kroger", "UnitedHealth", "UnitedHealth Group",
    "Optum", "Humana", "Cigna", "Aetna", "Elevance", "Novo Nordisk", "Novo", "Eli Lilly", "Lilly", "Pfizer", "Merck",
    "Johnson & Johnson", "J&J", "AstraZeneca", "Sanofi", "GSK", "Roche", "Abbott", "Medtronic", "Epic", "Oracle",
    "Fitbit", "Pixel", "Galaxy", "Mayo Clinic", "Kaiser", "Kaiser Permanente", "Cleveland Clinic", "Nestle", "Nestlé",
    "PepsiCo", "Coca-Cola", "Unilever", "Procter & Gamble", "P&G", "Kraft Heinz", "General Mills", "Mars", "Danone",
    "Sephora", "Ulta", "Ulta Beauty", "L'Oreal", "L'Oréal", "Estee Lauder", "Estée Lauder",
    # generic words that look like names at the start of headlines
    "New", "Study", "Report", "Research", "Researchers", "Scientists", "Experts", "Survey", "Startup", "Startups",
    "Exclusive", "Breaking", "Watch", "Why", "How", "What", "The", "This", "These", "Here", "Opinion", "AI", "GLP",
    "Doctors", "Patients", "Consumers", "Retailers", "Investors", "Analysts", "Industry", "Big Tech", "Health", "Medicare Advantage", "NVIDIA", "Mass General Brigham",
}


def company_radar(items, min_mentions=2, limit=15):
    wl = load_yaml("watchlist.yaml")
    known = set()
    for w in wl.get("companies", []) or []:
        known |= {w["name"].lower()} | {a.lower() for a in (w.get("aliases") or [])}
    ignore = {x.lower() for x in ALWAYS_IGNORE} | {x.lower() for x in (wl.get("radar_ignore") or [])}

    mentions = defaultdict(dict)  # name -> {item id: item}
    for i in items:
        names = set()
        if (m := SUBJECT_RE.match(i["title"])):
            names.add(m.group("name").strip(" .'’"))
        d = i.get("deal") or {}
        names |= {n for n in (d.get("company"), d.get("target")) if n}
        for n in names:
            n = re.sub(r"(?:'s|’s)$", "", n)
            low = n.lower()
            if len(n) < 3 or low in ignore or low in known or any(low.startswith(k + " ") for k in known):
                continue
            mentions[n][i["id"]] = i

    rows = []
    for name, by_id in mentions.items():
        lst = sorted(by_id.values(), key=lambda i: i["published"], reverse=True)
        outlets = len(lst) + sum(len(i.get("also", [])) for i in lst)
        stories = len(lst)
        if stories >= min_mentions or outlets >= 2:
            cats = sorted({i["category"] for i in lst})
            rows.append({"company": name, "stories": stories, "outlets": outlets, "categories": cats,
                         "latest": lst[0], "best_score": max(i["score"] for i in lst)})
    rows.sort(key=lambda r: (-r["stories"], -r["outlets"], -r["best_score"]))
    return rows[:limit]
