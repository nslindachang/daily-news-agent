#!/usr/bin/env python3
"""Step 4: generate summary + key points for each enriched item.

Uses Claude (via `claude -p`) on the full batch in one call. Output:
digest.json — slimmed to the fields the HTML render needs.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from claude_client import call_and_parse_with_retry

ROOT = Path(__file__).resolve().parent.parent
ENRICHED_FILE = ROOT / "enriched.json"
PROMPT_FILE = ROOT / "prompts" / "summarize.md"
OUT_FILE = ROOT / "digest.json"

CLAUDE_MODEL = "sonnet"  # quality matters more here than speed
CALL_TIMEOUT = 360  # per-attempt seconds; Sonnet summarize normally ~2-3 min

log = logging.getLogger("summarize")


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    items = json.loads(ENRICHED_FILE.read_text())
    log.info("Summarizing %d items", len(items))

    prepped = [
        {"id": i, "title": item["title"], "source": item["source"], "body": item["body"]}
        for i, item in enumerate(items)
    ]
    items_json = json.dumps(prepped, ensure_ascii=False)

    prompt = PROMPT_FILE.read_text()
    parsed = call_and_parse_with_retry(
        prompt, items_json,
        model=CLAUDE_MODEL,
        label="summarize",
        timeout=CALL_TIMEOUT,
        logs_dir=ROOT / "logs",
    )
    summaries = parsed.get("items", [])
    log.info("Got %d summaries", len(summaries))

    by_id = {s["id"]: s for s in summaries}
    out: list[dict] = []
    missing: list[int] = []
    for i, item in enumerate(items):
        s = by_id.get(i)
        if not s:
            missing.append(i)
            continue
        out.append({
            "title": item["title"],
            "link": item["link"],
            "source": item["source"],
            "bucket": item["bucket"],
            "score": item.get("score"),
            "published": item.get("published"),
            "summary": s["summary"],
            "key_points": s["key_points"],
        })

    if missing:
        log.warning("No summary returned for %d items: ids=%s", len(missing), missing)

    OUT_FILE.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    log.info("Wrote %s (%d items)", OUT_FILE.relative_to(ROOT), len(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
