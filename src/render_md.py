#!/usr/bin/env python3
"""Step 5: render digest.json to Markdown.

Writes:
- digests/today.md            (latest, overwritten daily)
- digests/<YYYY-MM-DD>.md      (dated archive copy)

README.md is static — GitHub's folder listing of digests/ is the archive,
so no per-run README regeneration.

On success, appends today's published URLs to published_links.json so
they're excluded from future digests.
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parent.parent
DIGEST_FILE = ROOT / "digest.json"
TEMPLATES_DIR = ROOT / "templates"
DIGESTS_DIR = ROOT / "digests"
PUBLISHED_FILE = ROOT / "published_links.json"

log = logging.getLogger("render_md")


def long_date(d: date) -> str:
    return d.strftime("%A, %B %-d, %Y")


def update_published(items: list[dict], today_iso: str) -> None:
    if PUBLISHED_FILE.exists():
        published = json.loads(PUBLISHED_FILE.read_text())
    else:
        published = {}
    added = 0
    for item in items:
        key = item["link"].split("?")[0].rstrip("/")
        if key not in published:
            published[key] = today_iso
            added += 1
    PUBLISHED_FILE.write_text(json.dumps(published, indent=2, ensure_ascii=False))
    log.info("published_links.json: +%d new (total %d)", added, len(published))


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    items = json.loads(DIGEST_FILE.read_text())
    log.info("Rendering %d items", len(items))

    today = date.today()
    today_iso = today.isoformat()

    groups: dict[str, list[dict]] = {"world": [], "singapore": [], "tech": []}
    for item in items:
        groups.setdefault(item["bucket"], []).append(item)
    for b in groups:
        groups[b].sort(key=lambda x: x.get("score") or 0, reverse=True)

    DIGESTS_DIR.mkdir(exist_ok=True)

    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )

    digest_tmpl = env.get_template("digest.md.j2")
    digest_md = digest_tmpl.render(
        date_iso=today_iso,
        date_long=long_date(today),
        groups=groups,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    )

    (DIGESTS_DIR / "today.md").write_text(digest_md)
    (DIGESTS_DIR / f"{today_iso}.md").write_text(digest_md)
    log.info("Wrote digests/today.md and digests/%s.md", today_iso)

    update_published(items, today_iso)
    return 0


if __name__ == "__main__":
    sys.exit(main())
