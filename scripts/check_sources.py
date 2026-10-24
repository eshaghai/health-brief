"""Health check for every source in sources.yaml (and, with --all, every watchlist search).

Run:  python scripts/check_sources.py          (sources.yaml only)
      python scripts/check_sources.py --all    (feeds + watchlist searches)
"""
import sys
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from common import load_config
from ingest import build_source_list, entry_date, fetch


def main():
    cfg = load_config()
    sources = build_source_list(cfg)
    if "--all" not in sys.argv:
        sources = [s for s in sources if not s.get("watch_name")]

    def check(src):
        feed, err = fetch(src["url"], cfg.get("request_timeout_seconds", 20))
        if err:
            return src, "BROKEN", err
        dates = [d for d in (entry_date(e) for e in feed.entries) if d]
        newest = max(dates).strftime("%Y-%m-%d") if dates else "no dates"
        return src, "OK", f"{len(feed.entries)} items, newest {newest}"

    bad = 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        for src, status, detail in pool.map(check, sources):
            bad += status != "OK"
            print(f"{'✓' if status == 'OK' else '✗'} {status:<6} {src['name']:<40} {detail}")
    print(f"\n{len(sources) - bad}/{len(sources)} working.")


if __name__ == "__main__":
    t = time.time()
    main()
    print(f"({time.time() - t:.0f}s)")
