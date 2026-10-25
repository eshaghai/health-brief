"""Write the "This Week" digest as Markdown for the weekly email.

The weekly GitHub Action posts this as a GitHub Issue in the repo; GitHub then emails it to
the repo owner automatically (no email service or account needed).

Run:  python scripts/weekly_email.py digest.md     (prints the email subject)
"""
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from build_site import fmt_date
from common import ITEMS_DIR, load_config, load_yaml, read_json
from digest import build_digest
from enrich import enrich_all, load_rules
from radar import company_radar


def main(out_path):
    cfg = load_config()
    cats = load_yaml("categories.yaml")
    site = cfg.get("site_url", "").rstrip("/") + "/"
    files = sorted(ITEMS_DIR.glob("*.json"))[-30:]
    items = [i for i in enrich_all([it for f in files for it in read_json(f, [])])
             if i["score"] >= cfg.get("min_score_to_show", 3)]
    d = build_digest(items, load_rules()[2]["high"])
    span = f"{fmt_date(d['start'])} – {fmt_date(d['end'])}"

    md = [f"## The week in five bullets ({span})", ""]
    for n, b in enumerate(d["bullets"], 1):
        line = f"{n}. **{b['label']}.** {b['text']}"
        if b.get("link"):
            line += f" [{b['link_text']}]({b['link']})"
        md.append(line)

    if d["research"]:
        md += ["", "## Worth researching", ""]
        md += [f"- **{r['company']}** ({r['detail']}): [{r['title']}]({r['link']})" for r in d["research"]]

    radar = company_radar(items, limit=5)
    if radar:
        md += ["", "## Company radar (not on my watchlist)", ""]
        md += [f"- **{r['company']}**: {r['stories']} {'story' if r['stories'] == 1 else 'stories'}, {r['outlets']} outlets. Latest: "
               f"[{r['latest']['title']}]({r['latest']['link']})" for r in radar]

    md += ["", "## Top 10 stories", ""]
    for i in d["top"]:
        md.append(f"- **[{i['title']}]({i['link']})** · {i['source']} · {cats[i['category']]['short']} · "
                  f"score {i['score']}  \n  _{i['why']}_")

    md += ["", "---", f"{d['count']} stories collected this week. "
           f"[Open the site]({site}) · [This Week page]({site}week.html) · [Funding tracker]({site}funding.html)",
           "", "_Sent automatically by the Health Brief weekly workflow. Close this issue whenever you like._"]

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")
    print(f"Health Brief weekly: {span}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "digest.md")
