# Health Brief

A personal news site for consumer & digital health. Every morning it collects stories from about 45 news feeds
and 30 Google News searches, throws out junk and duplicates, ranks what's left against my interests,
and publishes a clean, phone-friendly site. **Free to run:** no AI, no API keys, no paid services.

**Pages:** Today's Brief (home) · one page per industry · All Stories (search) · Watchlist · This Week digest ·
Funding Tracker · Archive · Saved (bookmarks stored in your browser) · Status (feed health).

---

## How it works

```
6:17 am ET, every day (GitHub Actions)
  1. scripts/ingest.py      fetch sources.yaml + watchlist.yaml searches
                            drop junk, old (>7 days) and duplicate stories
                            save new stories → data/items/YYYY-MM-DD.json
  2. scripts/build_site.py  sort into categories, score 1-10 vs profile.md,
                            group duplicate coverage, build the website
  3. publish to GitHub Pages
```

Scoring is keyword-based (see `scripts/enrich.py`). It's recomputed on every run, so when you edit
`profile.md`, `watchlist.yaml` or `categories.yaml`, the whole archive is re-ranked.

---

## Editing (all from the GitHub website, no software needed)

On your repo page, click a file → the **pencil icon** (Edit) → make the change → **Commit changes**.
Saving any of these files automatically rebuilds the site within ~2 minutes.

### Add or remove a news source → `sources.yaml`
Add a block like:
```yaml
  - name: Some Newsletter
    url: https://example.substack.com/feed
```
- Substack newsletters: the feed is `https://NAME.substack.com/feed`.
- Most WordPress sites: `https://site.com/feed/`.
- If a site blocks feed readers, use a Google News search instead:
  ```yaml
  - name: Some Site
    google_news: "site:somesite.com"
  ```
- To remove a source: delete its block, or add `enabled: false` to pause it.

### Add a company to track → `watchlist.yaml`
Usually just one line under `companies:`:
```yaml
  - name: Levels
```
If the name is a common word, add a `query` (what to search), `aliases` (other spellings), and
`context` (words that must also appear, so "Nourish Our Community food drive" doesn't count as Nourish).
There are examples at the top of the file. Topics (like "GLP-1 telehealth") go under `topics:`.

### Change what ranks highly → `profile.md`
Three bullet lists: **High interest** (big boost), **Medium interest** (small boost),
**Push down** (ranked lower). One phrase per bullet, or several separated by commas.

### Fix how stories are sorted into categories → `categories.yaml`
Each category has a keyword list. Add words if stories land in the wrong category.

### Other settings → `config.yaml`
Number of stories in the Brief, how many days to keep on the site, the minimum score to show, etc.

---

## Rerun manually

GitHub repo → **Actions** tab → **Daily update** (left side) → **Run workflow** → green **Run workflow** button.
It takes about 1–2 minutes. Refresh the site afterward (on a phone you may need to pull down to refresh).

---

## Troubleshooting

| Problem | What to do |
|---|---|
| Site didn't update today | **Actions** tab → look for a red ✗ on "Daily update". Click it, then the red step, to read the error. Then click **Re-run jobs**. |
| One source shows ✗ on the Status page | Nothing else is affected. If it stays broken for several days, the feed address probably changed: find the new one, or switch it to a `google_news: "site:..."` search. |
| Error after editing a `.yaml` file | Almost always indentation or a missing quote. Compare your edit to the lines around it: same number of spaces, same `- name:` pattern. Undo via the file's **History** if needed. |
| A company shows no news | Check its spelling, try a more specific `query`, or remove a `context` rule that's too strict. |
| Wrong stories match a company | Add a `context` list to that company in `watchlist.yaml`. |
| Junk stories appear | Add a phrase to **Push down** in `profile.md`, or a pattern to `JUNK_PATTERNS` in `scripts/ingest.py`. |
| The daily run stopped completely | GitHub pauses scheduled jobs after 60 days with no repo activity (the daily data commit normally prevents this). Actions tab → Daily update → **Enable workflow**. |

The **Status** page on the site lists every source and whether it worked in the last run.

---

## Run it on your own computer (optional)

```bash
pip install -r requirements.txt
python scripts/check_sources.py --all   # test every feed and search
python scripts/ingest.py                # fetch today's news
python scripts/build_site.py            # build the site into _site/
cd _site && python -m http.server       # open http://localhost:8000
```

## Copyright & etiquette
The site only uses official RSS feeds and Google News RSS. It stores and shows headlines plus the short
teaser each publisher includes in its own feed, and always links to the original article. No full articles
are copied and nothing is scraped from web pages.

## Files
| Path | What it is |
|---|---|
| `sources.yaml`, `watchlist.yaml`, `profile.md`, `categories.yaml`, `config.yaml` | Your settings |
| `data/items/` | Daily archive, one JSON file per day |
| `data/last_run.json` | Health of the latest run (drives the Status page) |
| `scripts/` | The code: `ingest.py` (fetch), `enrich.py` (score/sort), `digest.py` (This Week), `build_site.py` (website), `check_sources.py` (feed test) |
| `templates/`, `static/` | Website layout, styles and browser code |
| `.github/workflows/daily.yml` | The daily schedule |
