#!/usr/bin/env python3
"""Step 2: rank raw items by impact, picking ~30 for the digest.

Uses Claude (via `claude -p`) to score and select items. Input is
RSS-level metadata only (title, teaser, categories) — full article
bodies aren't fetched until step 3.
"""
from __future__ import annotations

import json
import logging
import re
import sys
from collections import Counter
from pathlib import Path

from bs4 import BeautifulSoup

from claude_client import call_and_parse_with_retry

ROOT = Path(__file__).resolve().parent.parent
RAW_FILE = ROOT / "raw_items.json"
PROMPT_FILE = ROOT / "prompts" / "rank.md"
OUT_FILE = ROOT / "ranked.json"

CLAUDE_MODEL = "haiku"
CALL_TIMEOUT = 180  # per-attempt seconds; Haiku rank normally ~20s
MAX_SUMMARY_CHARS = 400

log = logging.getLogger("rank")


def strip_html(s: str | None) -> str:
    if not s:
        return ""
    txt = BeautifulSoup(s, "html.parser").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", txt).strip()


def prepare_items_for_prompt(raw: list[dict]) -> list[dict]:
    out = []
    for i, item in enumerate(raw):
        out.append({
            "id": i,
            "source": item["source"],
            "bucket": item["bucket"],
            "title": item["title"],
            "summary": strip_html(item.get("summary"))[:MAX_SUMMARY_CHARS],
            "categories": item.get("categories", []),
            "link": item["link"],
        })
    return out


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    raw = json.loads(RAW_FILE.read_text())
    log.info("Loaded %d raw items", len(raw))

    prepped = prepare_items_for_prompt(raw)
    items_json = json.dumps(prepped, ensure_ascii=False)

    prompt = PROMPT_FILE.read_text()
    parsed = call_and_parse_with_retry(
        prompt, items_json,
        model=CLAUDE_MODEL,
        label="rank",
        timeout=CALL_TIMEOUT,
        logs_dir=ROOT / "logs",
    )
    selections = parsed.get("selections", [])
    log.info("Got %d selections", len(selections))

    by_id = dict(enumerate(raw))
    out_items: list[dict] = []
    for sel in selections:
        item = by_id.get(sel["id"])
        if not item:
            log.warning("Selection id=%s not found in raw items", sel["id"])
            continue
        # Use the ranker's reassigned bucket (topic-based), not the feed's.
        out_items.append({
            **item,
            "bucket": sel.get("bucket", item["bucket"]),
            "score": sel["score"],
            "rationale": sel["rationale"],
        })

    bucket_counts = Counter(i["bucket"] for i in out_items)
    log.info("Selection by bucket (reassigned): world=%d singapore=%d tech=%d",
             bucket_counts.get("world", 0),
             bucket_counts.get("singapore", 0),
             bucket_counts.get("tech", 0))

    OUT_FILE.write_text(json.dumps(out_items, indent=2, ensure_ascii=False))
    log.info("Wrote %s (%d items)", OUT_FILE.relative_to(ROOT), len(out_items))
    # Note: published_links.json is updated by the render step (step 5),
    # only after a digest actually goes out. That way re-running rank
    # during testing doesn't pollute the cross-day dedup state.
    return 0


if __name__ == "__main__":
    sys.exit(main())
