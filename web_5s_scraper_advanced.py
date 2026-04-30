"""Advanced web scraper using Playwright (Chromium) for JS-rendered pages."""

import json
import time
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

SOURCES = [
    {
        "name": "PyPI New Packages",
        "url": "https://pypi.org/rss/packages.xml",
        "wait_for": "channel",
        "content_selector": "title",
    },
    {
        "name": "PyPI Latest Updates",
        "url": "https://pypi.org/rss/updates.xml",
        "wait_for": "channel",
        "content_selector": "title",
    },
    {
        "name": "GitHub Trending",
        "url": "https://github.com/trending",
        "wait_for": "article.Box-row",
        "content_selector": "h2.h3 a",
    },
    {
        "name": "GitHub Search ML",
        "url": "https://github.com/search?q=machine+learning&type=repositories",
        "wait_for": "h3",
        "content_selector": "h3 a",
    },
    {
        "name": "GitHub Explore",
        "url": "https://github.com/explore",
        "wait_for": "article",
        "content_selector": "article h1 a, h2.h4 a, h3 a",
    },
]


def scrape_source(page, source: dict) -> dict:
    result = {"name": source["name"], "url": source["url"], "items": [], "error": None}
    try:
        page.goto(source["url"], timeout=15000, wait_until="domcontentloaded")
        try:
            page.wait_for_selector(source["wait_for"], timeout=8000)
        except PWTimeout:
            pass  # proceed with whatever loaded
        elements = page.query_selector_all(source["content_selector"])
        items = []
        for el in elements[:20]:
            try:
                text = el.inner_text().strip()
            except Exception:
                text = (el.text_content() or "").strip()
            if text:
                items.append(text)
        result["items"] = items
        print(f"  [{source['name']}] {len(result['items'])} items")
    except Exception as e:
        result["error"] = str(e)
        print(f"  [{source['name']}] ERROR: {e}")
    return result


def main():
    print(f"=== web_5s_scraper_advanced.py  ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')}) ===")
    results = []
    t0 = time.time()

    chrome_path = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            executable_path=chrome_path,
            args=["--ignore-certificate-errors"],
        )
        context = browser.new_context(
            ignore_https_errors=True,
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        )
        page = context.new_page()
        for source in SOURCES:
            results.append(scrape_source(page, source))
        browser.close()

    elapsed = time.time() - t0
    output = {
        "scraped_at": datetime.now().isoformat(),
        "elapsed_seconds": round(elapsed, 2),
        "results": results,
    }

    out_path = "web_5s_advanced_output.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    total_items = sum(len(r["items"]) for r in results)
    print(f"\nDone: {total_items} items from {len(SOURCES)} sources in {elapsed:.1f}s -> {out_path}")


if __name__ == "__main__":
    main()
