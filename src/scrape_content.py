#!/usr/bin/env python3
"""Step 3: fetch full article bodies for ranked items.

Extracts the main article text using trafilatura. On failure (network
error, paywall, weird HTML), falls back to the item's RSS summary so
the summarize step (step 4) always has *something* to work with.
"""
from __future__ import annotations

import json
import logging
import re
import sys
import time
from pathlib import Path

import httpx
import trafilatura
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
RANKED_FILE = ROOT / "ranked.json"
OUT_FILE = ROOT / "enriched.json"

HTTP_TIMEOUT = 20.0
PER_REQUEST_DELAY = 0.5  # seconds — polite pacing across all fetches
MAX_BODY_CHARS = 8000  # truncate long articles to bound token usage downstream
MIN_USEFUL_BODY = 200  # below this we treat scrape as failed and fall back

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)

log = logging.getLogger("scrape")


def strip_html(s: str) -> str:
    if not s:
        return ""
    txt = BeautifulSoup(s, "html.parser").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", txt).strip()


def scrape_one(client: httpx.Client, url: str) -> str | None:
    r = client.get(url, follow_redirects=True, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    body = trafilatura.extract(
        r.text,
        include_comments=False,
        include_tables=False,
        favor_precision=True,
    )
    return body


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    items = json.loads(RANKED_FILE.read_text())
    log.info("Scraping %d ranked items", len(items))

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,*/*",
        "Accept-Language": "en-US,en;q=0.9",
    }

    n_scraped = n_fallback = n_failed = 0
    enriched: list[dict] = []
    with httpx.Client(headers=headers) as client:
        for i, item in enumerate(items, 1):
            url = item["link"]
            time.sleep(PER_REQUEST_DELAY)
            body = None
            err = None
            try:
                body = scrape_one(client, url)
            except Exception as exc:
                err = str(exc)

            if body and len(body) >= MIN_USEFUL_BODY:
                source = "scraped"
                n_scraped += 1
            else:
                fallback = strip_html(item.get("summary", ""))
                if fallback:
                    body = fallback
                    source = "rss_summary_fallback"
                    n_fallback += 1
                    note = "thin/empty scrape" if not err else f"error: {err}"
                    log.info("[%2d/%d] FALLBACK (%s) — %s", i, len(items), note, item["title"][:60])
                else:
                    body = ""
                    source = "none"
                    n_failed += 1
                    log.warning("[%2d/%d] NO BODY %s — %s", i, len(items), err or "", item["title"][:60])

            if body and len(body) > MAX_BODY_CHARS:
                body = body[:MAX_BODY_CHARS] + "…"

            log.info("[%2d/%d] %-25s %5dB  %s",
                     i, len(items), source, len(body or ""), item["title"][:60])

            enriched.append({**item, "body": body, "body_source": source})

    log.info("---")
    log.info("Scraped successfully: %d", n_scraped)
    log.info("RSS-summary fallback: %d", n_fallback)
    log.info("No body at all:       %d", n_failed)

    OUT_FILE.write_text(json.dumps(enriched, indent=2, ensure_ascii=False))
    log.info("Wrote %s (%d items)", OUT_FILE.relative_to(ROOT), len(enriched))
    return 0


if __name__ == "__main__":
    sys.exit(main())
