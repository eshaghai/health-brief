"""Stage 2 (free mode): sort each story into a category, score it 1-10 against profile.md,
explain why it's there, and pull out funding/M&A details. No AI or API key needed.

All of this is recomputed at every build, so editing profile.md, watchlist.yaml or
categories.yaml re-ranks the whole archive on the next run.
"""
import re
import sys
from functools import lru_cache

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from common import ROOT, load_yaml
from ingest import is_junk

CATEGORY_ORDER = ["wearables", "nutrition", "longevity", "retail", "ai", "funding", "policy"]

# Words that must appear for a story to be considered health-related at all
# (used to filter broad feeds like Axios or OpenAI).
HEALTH_GATE = re.compile(
    r"\b(health\w*|medic\w*|wellness|well-being|fitness|patient\w*|doctor\w*|clinic\w*|hospital\w*|"
    r"disease\w*|diabet\w*|obesity|weight|nutrition\w*|diet\w*|food|beverage|supplement\w*|vitamin\w*|"
    r"sleep|wearable\w*|watch|ring|glucose|GLP-1s?|drug\w*|pharm\w*|biotech\w*|FDA|longevity|aging|"
    r"skin\w*|beauty|telehealth|therap\w*|mental|cancer|heart|blood|biomarker\w*|lab|care)\b", re.I)


def _phrase_re(phrases):
    parts = sorted({p.strip() for p in phrases if p and p.strip()}, key=len, reverse=True)
    if not parts:
        return None
    # Word-boundary match; allow trailing "s" for plurals.
    alts = "|".join(re.escape(p) + r"s?" for p in parts)
    return re.compile(rf"(?<![\w-])({alts})(?![\w-])", re.I)


@lru_cache(maxsize=1)
def load_rules():
    cats = load_yaml("categories.yaml")
    cat_res = {k: _phrase_re(v.get("keywords", [])) for k, v in cats.items()}

    # profile.md: parse bullet lists under the three headings.
    sections = {"high": [], "medium": [], "down": []}
    current = None
    for line in (ROOT / "profile.md").read_text(encoding="utf-8").splitlines():
        h = line.strip().lower()
        if h.startswith("## "):
            current = "high" if "high" in h else "medium" if "medium" in h else "down" if "down" in h else None
        elif current and line.strip().startswith(("-", "*")):
            sections[current] += [p.strip() for p in line.strip()[1:].split(",")]
    prof_res = {k: _phrase_re(v) for k, v in sections.items()}

    wl = load_yaml("watchlist.yaml")
    watch = []
    for group in ("companies", "topics"):
        for w in wl.get(group, []) or []:
            names = [w["name"]] + list(w.get("aliases", []) or [])
            watch.append({
                "name": w["name"], "group": group, "category": w.get("category"),
                "re": _phrase_re(names) if group == "companies" else None,
                "context": _phrase_re(w.get("context", []) or []),
            })
    return cats, cat_res, prof_res, watch


# ---------- funding / M&A extraction ----------
AMOUNT_RE = re.compile(r"\$\s?(\d+(?:\.\d+)?)\s?(billion|million|bn|mn|[BM])\b", re.I)
ROUND_RE = re.compile(r"\b(pre-seed|seed(?: round| funding| extension)?|series [a-h]\d?(?:\+| extension)?|"
                      r"growth (?:round|equity)|debt financing|IPO|SPAC)\b", re.I)
RAISE_RE = re.compile(r"^(?P<co>.{2,60}?)\s+(?:raises|raised|lands|secures|closes|nabs|bags|snags|banks|"
                      r"gets|scores|announces|completes)\b.*?(?:\$|funding|round|series|seed)", re.I)
ACQ_RE = re.compile(r"^(?P<co>.{2,60}?)\s+(?:to acquire|acquires|acquired|buys|to buy|snaps up|scoops up|"
                    r"agrees to acquire|completes acquisition of|merges with|to merge with)\s+(?P<target>.{2,60}?)"
                    r"(?:\s+(?:for|in|from|to)\b|[,:;]|$)", re.I)
ACQ_PASSIVE_RE = re.compile(r"^(?P<target>.{2,60}?)\s+(?:acquired by|to be acquired by|sold to|agrees to sell to)\s+"
                            r"(?P<co>.{2,60}?)(?:\s+(?:for|in)\b|[,:;]|$)", re.I)
IPO_RE = re.compile(r"\b(IPO|goes public|files (?:to go|for) public|S-1|public debut|listing on (?:the )?(?:Nasdaq|NYSE))\b", re.I)
LAYOFF_RE = re.compile(r"\b(lay(?:s|ing)? off|layoffs?|job cuts|cuts (?:\d+ )?jobs|cuts staff|workforce reduction)\b", re.I)
INVESTORS_RE = re.compile(r"\b(?:led by|co-led by|backed by|from investors(?: including)?)\s+"
                          r"(?P<inv>[A-Z][\w&.'\- ]{2,80}?)(?=[,.;]|\s+(?:and|with|to|as|bringing|that|which|in)\s|$)")


def _clean_company(name):
    name = re.sub(r"^\s*[\[{(][^\]})]*[\]})]\s*", "", name)  # "{Funding Alert} Even" -> "Even"
    name = re.sub(r"^[^:]{1,20}:\s+", "", name.strip())  # "STAT+: Pathos" -> "Pathos"
    # "Healthcare AI Startup BioStack" / "AI drug firm Pathos" -> "BioStack" / "Pathos"
    name = re.sub(r"^.*\b(?:startup|start-up|firm|company|maker|provider|platform|developer|unicorn)\s+(?=[A-Z0-9])",
                  "", name, flags=re.I)
    name = re.sub(r"(?:'s|’s)\s.*$", "", name)  # "Lycia's $318M" -> "Lycia"
    return name.strip(" '\"‘’“”")


def _valid_name(name):
    words = (name or "").split()
    lowercase = [w for w in words if w[:1].islower() and w not in ("and", "of", "&", "the", "for")]
    return bool(words) and len(name) <= 45 and not lowercase and words[0][:1].isupper() and "," not in name


def extract_deal(title, text):
    """Return a dict describing a funding/M&A/IPO/layoff event, or None."""
    title = re.split(r";\s", title)[0]  # roundup headlines: "A raises $5M; B files IPO; ..."
    candidates = []
    m = RAISE_RE.search(title)
    if m and (AMOUNT_RE.search(title) or ROUND_RE.search(title)):
        candidates.append({"type": "Funding", "company": _clean_company(m.group("co"))})
    if (m := ACQ_RE.search(title)) or (m := ACQ_PASSIVE_RE.search(title)):
        candidates.append({"type": "M&A", "company": _clean_company(m.group("co")),
                           "target": _clean_company(m.group("target"))})
    deal = next((c for c in candidates if _valid_name(c["company"])), candidates[0] if candidates else None)
    if deal:
        pass
    elif IPO_RE.search(title):
        deal = {"type": "IPO", "company": _clean_company(re.split(r"\s+(?:files|plans|prices|sets|eyes|readies|to|goes|IPO)\b", title, maxsplit=1)[0])}
    elif LAYOFF_RE.search(title):
        deal = {"type": "Layoffs", "company": _clean_company(re.split(r"\s+(?:lays|cuts|to cut|announces|plans|begins|conducts|layoffs)\b", title, maxsplit=1)[0])}
    if not deal:
        return None
    if not _valid_name(deal["company"]):
        deal["company"] = ""  # extraction went wrong; keep the event but not a bogus name
    if deal.get("target") and not _valid_name(deal["target"]):
        deal["target"] = ""
    full = f"{title}. {text}"
    if deal["type"] != "Layoffs" and (a := AMOUNT_RE.search(full)):
        unit = a.group(2).lower()
        deal["amount"] = f"${a.group(1)}{'B' if unit.startswith('b') else 'M'}"
        deal["amount_usd"] = float(a.group(1)) * (1e9 if unit.startswith("b") else 1e6)
    if (r := ROUND_RE.search(full)):
        deal["round"] = r.group(1).title().replace("Ipo", "IPO").replace("Spac", "SPAC")
    if (i := INVESTORS_RE.search(text or "")):
        deal["investors"] = i.group("inv").strip()
    return deal


def _hits(regex, text):
    if not regex or not text:
        return []
    return [m.group(1) for m in regex.finditer(text)]


def enrich(item):
    """Add category, score, tags, why, watch, deal to an item. Returns None if off-topic."""
    cats, cat_res, prof_res, watch = load_rules()
    title, summary = item["title"], item.get("summary", "")
    text = f"{title} {summary}"

    # Watchlist matches (company names in the headline/summary, with optional context words).
    watch_hits = []
    for w in watch:
        if w["re"] and w["re"].search(text):
            if w["context"] and not w["context"].search(text):
                continue
            watch_hits.append(w["name"])
    # Came from a company's own Google News search but the name isn't in the headline
    # (usually mentioned in the article body): shown on the Watchlist page, no ranking boost.
    watch_weak = []
    src = next((w for w in watch if w["group"] == "companies" and w["name"] == item.get("watch_query")), None)
    if src and src["name"] not in watch_hits and (not src["context"] or src["context"].search(text)):
        watch_weak.append(src["name"])
    # Topic searches: the story came from that Google News query.
    topic = next((w for w in watch if w["group"] == "topics" and w["name"] == item.get("watch_query")), None)

    # Category: keyword hits, headline counts double; source hint breaks ties.
    scores = {}
    for c in CATEGORY_ORDER:
        r = cat_res.get(c)
        scores[c] = 2 * len(_hits(r, title)) + len(_hits(r, summary))
    hint = item.get("category_hint") or (topic or {}).get("category")
    if hint in scores:
        scores[hint] += 1.5
    for name in watch_hits:
        wc = next(w["category"] for w in watch if w["name"] == name)
        if wc in scores:
            scores[wc] += 1

    deal = extract_deal(title, summary)
    if deal:
        scores["funding"] += 3

    if is_junk(item):
        return None
    if max(scores.values()) == 0 and not watch_hits and not watch_weak:
        return None  # off-topic
    if not HEALTH_GATE.search(text) and not watch_hits and not watch_weak:
        return None  # e.g. general business/tech stories from broad feeds

    category = max(CATEGORY_ORDER, key=lambda c: (scores[c], -CATEGORY_ORDER.index(c)))
    secondary = [c for c in CATEGORY_ORDER if c != category and scores[c] >= 2][:2]

    # Relevance score 1-10.
    high = {h.lower() for h in _hits(prof_res["high"], text)}
    med = {h.lower() for h in _hits(prof_res["medium"], text)} - high
    down = {h.lower() for h in _hits(prof_res["down"], text)}
    s = 3.0
    s += 2.5 if any(w["re"] and w["re"].search(title) for w in watch if w["name"] in watch_hits) else (1.5 if watch_hits else 0)
    s += min(len(high), 3) * 1.0
    s += min(len(med), 3) * 0.4
    s -= min(len(down), 2) * 1.5
    s += 1.0 if deal and deal["type"] in ("Funding", "M&A", "IPO") else 0
    s += min(scores[category], 6) * 0.15
    if item.get("origin") == "google_news" and not watch_hits and not topic:
        s -= 0.5
    score = max(1, min(10, round(s)))

    why = []
    if watch_hits:
        why.append("Watchlist: " + ", ".join(watch_hits))
    elif watch_weak:
        why.append(f"From {watch_weak[0]} news search")
    elif topic:
        why.append(f"Tracked topic: {topic['name']}")
    if deal:
        bits = [deal["type"]]
        if deal.get("amount"):
            bits.append(deal["amount"])
        if deal.get("round"):
            bits.append(deal["round"])
        why.append(" ".join(bits) + " signal")
    matched = sorted(high, key=len, reverse=True)[:3] + sorted(med, key=len, reverse=True)[:max(0, 3 - len(high))]
    if matched:
        why.append("Matches: " + ", ".join(matched))
    if down:
        why.append("Pushed down: " + ", ".join(sorted(down)[:2]))

    out = dict(item)
    out.update({"category": category, "secondary": secondary, "score": score,
                "watch": watch_hits, "watch_weak": watch_weak, "why": " · ".join(why) or "Category keyword match",
                "deal": deal})
    return out


STOPWORDS = set("a an the and or of to in on for with at by from as is are be its it this that after over "
                "into amid new says said will can could may report reports why how what s".split())


def _key_tokens(title, ignore=()):
    """Distinctive words of a headline, crudely stemmed ("burns"/"burn", "reportedly"/"report")."""
    toks = {w.rstrip("s")[:6] for w in re.findall(r"[a-z0-9$]+", title.lower()) if w not in STOPWORDS and len(w) > 2}
    return toks - set(ignore)


def _name_tokens(names):
    _, _, _, watch = load_rules()
    words = set()
    for w in watch:
        if w["name"] in names and w["re"]:
            words |= {t.rstrip("s")[:6] for t in re.findall(r"[a-z0-9]+", w["re"].pattern.lower())}
    return words


def cluster(items):
    """Group stories about the same event from different outlets. The highest-scoring copy
    (direct feeds preferred) is kept as the lead; the others are attached as `also`."""
    items = sorted(items, key=lambda i: (-i["score"], i.get("origin") != "feed", i["published"]))
    leads = []
    for it in items:
        toks = _key_tokens(it["title"])
        for lead in leads:
            if abs((_dt(it) - _dt(lead)).days) > 3:
                continue
            # Ignore the company's own name: two different Oura stories both say "Oura".
            shared_cos = set(it["watch"]) & set(lead["watch"])
            ignore = _name_tokens(shared_cos) if shared_cos else set()
            a, b = toks - ignore, lead["_tokens"] - ignore
            if not a or not b:
                continue
            shared = len(a & b)
            overlap = shared / min(len(a), len(b))
            coverage = shared / max(len(a), len(b))
            same_deal = bool(it["deal"] and lead["deal"] and it["deal"].get("company") and
                             it["deal"].get("company") == lead["deal"].get("company"))
            if it["watch"] and lead["watch"] and not shared_cos:
                continue  # stories about different tracked companies are never the same story
            if (overlap >= 0.6 and coverage >= 0.4 and shared >= 3) or \
                    (shared_cos and overlap >= 0.3 and coverage >= 0.25 and shared >= 3) or \
                    (same_deal and overlap >= 0.25 and shared >= 2):
                lead["also"].append({"source": it["source"], "link": it["link"], "title": it["title"]})
                break
        else:
            it["_tokens"], it["also"] = toks, []
            leads.append(it)
    for lead in leads:
        lead.pop("_tokens", None)
    return leads


def _dt(item):
    from datetime import datetime
    return datetime.fromisoformat(item["published"])


def enrich_all(items):
    """Enrich every item, drop off-topic ones, and merge duplicate coverage."""
    out = []
    for it in items:
        e = enrich(it)
        if e:
            out.append(e)
    return cluster(out)


if __name__ == "__main__":
    import collections
    from common import load_all_items
    raw = load_all_items(days=1)
    items = enrich_all(raw)
    print(f"{len(raw)} stories → {len(items)} on-topic ({len(raw) - len(items)} dropped as off-topic)\n")
    print("By category:", dict(collections.Counter(i["category"] for i in items)))
    print("By score:   ", dict(sorted(collections.Counter(i["score"] for i in items).items())))
    print("\nTop 12:")
    for i in sorted(items, key=lambda i: (-i["score"], i["published"]), reverse=False)[:12]:
        print(f" [{i['score']:>2}] {i['category']:<9} {i['title'][:85]}\n        ({i['source']}) {i['why']}")
    deals = [i for i in items if i["deal"]]
    print(f"\nDeals detected: {len(deals)}")
    for i in deals[:12]:
        print("  ", {k: v for k, v in i["deal"].items() if k != "amount_usd"}, "|", i["title"][:70])
