#!/usr/bin/env python3
"""Fetch RSS feeds listed in feeds.yaml and write raw_items.json.

Step 1 of the news-agent pipeline. No AI here — just RSS pull, basic
junk filtering (sports/entertainment/lifestyle), and dedupe by URL.
"""
from __future__ import annotations

import json
import logging
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import feedparser
import httpx
import yaml

ROOT = Path(__file__).resolve().parent.parent
FEEDS_FILE = ROOT / "feeds.yaml"
OUT_FILE = ROOT / "raw_items.json"
PUBLISHED_FILE = ROOT / "published_links.json"

MAX_AGE_HOURS = 30
HTTP_TIMEOUT = 15.0
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "news-agent/0.1 (+https://github.com/news-agent)"
)

JUNK_CATEGORY_TOKENS = {
    "sport", "sports", "entertainment", "lifestyle", "food", "recipe",
    "recipes", "travel", "fashion", "celebrity", "arts", "music",
    "movies", "movie", "television", "tv", "books", "style", "wellness",
    "horoscope", "puzzles", "crossword", "games",
}
JUNK_URL_PATHS = (
    "/sport", "/sports", "/entertainment", "/lifestyle", "/food",
    "/travel", "/fashion", "/recipes", "/style", "/arts/", "/movies/",
    "/television/", "/books/", "/games/", "/crosswords",
)
# Promo/coupon/buying-guide spam — clean up Wired's RSS noise.
JUNK_TITLE_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in (
        r"\bpromo codes?\b",
        r"\bcoupons?\b",
        r"\bdiscount codes?\b",
        r"\bbundle deals?\b.*\bsave\b",
        r"\b\d+%\s*off\b",
        r"\btested and reviewed\b",
        r"\bbest\b.*\(\d{4}\)",
    )
]

log = logging.getLogger("fetch_feeds")


def _parse_pub(entry: Any) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            return datetime(*t[:6], tzinfo=timezone.utc)
    return None


def _tokenize_categories(categories: list[str]) -> set[str]:
    # CNA packs all tags into one comma-joined string like "Women ,CNA Lifestyle ,Singapore".
    # Split on common separators so each tag is its own token.
    tokens: set[str] = set()
    for c in categories:
        for piece in c.replace(";", ",").replace("|", ",").split(","):
            piece = piece.strip().lower()
            if not piece:
                continue
            tokens.add(piece)
            tokens.update(piece.split())
    return tokens


def _is_junk(title: str, link: str, categories: list[str]) -> bool:
    if _tokenize_categories(categories) & JUNK_CATEGORY_TOKENS:
        return True
    link_lc = link.lower()
    if any(p in link_lc for p in JUNK_URL_PATHS):
        return True
    if any(p.search(title) for p in JUNK_TITLE_PATTERNS):
        return True
    return False


def normalize_link(link: str) -> str:
    """Stable key for cross-source / cross-day dedup."""
    return link.split("?")[0].rstrip("/")


def load_published() -> dict[str, str]:
    if not PUBLISHED_FILE.exists():
        return {}
    return json.loads(PUBLISHED_FILE.read_text())


def parse_feed(source: dict, raw_xml: str, cutoff: datetime) -> list[dict]:
    feed = feedparser.parse(raw_xml)
    items: list[dict] = []
    for entry in feed.entries:
        title = (entry.get("title") or "").strip()
        link = (entry.get("link") or "").strip()
        if not title or not link:
            continue
        pub = _parse_pub(entry)
        if pub and pub < cutoff:
            continue
        categories = [
            t.term for t in entry.get("tags", []) if getattr(t, "term", None)
        ]
        if _is_junk(title, link, categories):
            continue
        items.append({
            "source": source["name"],
            "bucket": source["bucket"],
            "title": title,
            "link": link,
            "published": pub.isoformat() if pub else None,
            "summary": (entry.get("summary") or "").strip(),
            "categories": categories,
        })
    return items


def fetch_one(client: httpx.Client, url: str) -> str:
    r = client.get(url, follow_redirects=True, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    return r.text


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    sources = yaml.safe_load(FEEDS_FILE.read_text())["sources"]
    cutoff = datetime.now(timezone.utc) - timedelta(hours=MAX_AGE_HOURS)

    all_items: list[dict] = []
    failures: list[tuple[str, str]] = []

    headers = {"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml, text/xml, */*"}
    with httpx.Client(headers=headers) as client:
        for src in sources:
            try:
                xml = fetch_one(client, src["url"])
                items = parse_feed(src, xml, cutoff)
                log.info("%-30s %3d items", src["name"], len(items))
                all_items.extend(items)
            except Exception as exc:
                log.warning("%-30s FAILED — %s", src["name"], exc)
                failures.append((src["name"], str(exc)))

    seen: set[str] = set()
    unique: list[dict] = []
    for item in all_items:
        key = normalize_link(item["link"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)

    # Cross-day dedup: drop anything that already appeared in a past digest.
    published = load_published()
    fresh = [i for i in unique if normalize_link(i["link"]) not in published]
    skipped_published = len(unique) - len(fresh)

    bucket_counts = Counter(i["bucket"] for i in fresh)
    log.info("---")
    log.info("Total raw items:       %d", len(all_items))
    log.info("Unique after dedupe:   %d", len(unique))
    log.info("Skipped (already published in past digest): %d", skipped_published)
    log.info("Eligible for today:    %d", len(fresh))
    log.info("By bucket (feed-tagged): world=%d singapore=%d tech=%d",
             bucket_counts.get("world", 0),
             bucket_counts.get("singapore", 0),
             bucket_counts.get("tech", 0))
    if failures:
        log.warning("Feed failures: %d", len(failures))
        for name, err in failures:
            log.warning("  - %s: %s", name, err)

    OUT_FILE.write_text(json.dumps(fresh, indent=2, ensure_ascii=False))
    log.info("Wrote %s (%d items)", OUT_FILE.relative_to(ROOT), len(fresh))
    return 0


if __name__ == "__main__":
    sys.exit(main())
