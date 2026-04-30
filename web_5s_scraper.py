"""Basic web scraper using requests + BeautifulSoup across 5 sources."""

import json
import time
import warnings
import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from datetime import datetime

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

SOURCES = [
    {
        "name": "PyPI New Packages",
        "url": "https://pypi.org/rss/packages.xml",
        "content_selector": "title",
    },
    {
        "name": "PyPI Latest Updates",
        "url": "https://pypi.org/rss/updates.xml",
        "content_selector": "title",
    },
    {
        "name": "GitHub Trending",
        "url": "https://github.com/trending",
        "content_selector": "h2.h3 a",
    },
    {
        "name": "GitHub Search ML",
        "url": "https://github.com/search?q=machine+learning&type=repositories",
        "content_selector": "h3 a",
    },
    {
        "name": "npm RSS",
        "url": "https://registry.npmjs.org/-/rss",
        "content_selector": "title",
    },
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}


def scrape_source(source: dict) -> dict:
    result = {"name": source["name"], "url": source["url"], "items": [], "error": None}
    try:
        resp = requests.get(source["url"], headers=HEADERS, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        elements = soup.select(source["content_selector"])
        result["items"] = [el.get_text(strip=True) for el in elements[:20] if el.get_text(strip=True)]
        print(f"  [{source['name']}] {len(result['items'])} items")
    except Exception as e:
        result["error"] = str(e)
        print(f"  [{source['name']}] ERROR: {e}")
    return result


def main():
    print(f"=== web_5s_scraper.py  ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')}) ===")
    results = []
    t0 = time.time()
    for source in SOURCES:
        results.append(scrape_source(source))
    elapsed = time.time() - t0

    output = {
        "scraped_at": datetime.now().isoformat(),
        "elapsed_seconds": round(elapsed, 2),
        "results": results,
    }

    out_path = "web_5s_output.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    total_items = sum(len(r["items"]) for r in results)
    print(f"\nDone: {total_items} items from {len(SOURCES)} sources in {elapsed:.1f}s -> {out_path}")


if __name__ == "__main__":
    main()
