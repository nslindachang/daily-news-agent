# news-agent

Self-hosted daily news digest. Each morning at 6am SGT, pulls ~17 RSS feeds across world, Singapore, and tech sources, uses Claude to filter for impact and write summaries, and publishes a Markdown digest to a repo for reading on mobile via the GitHub app.

## Today's digest

→ *Not available in this repos*

## Intent

A personal daily-reader replacement, not a general news tool. Assumes one reader (Singapore-based) who wants to be well-informed about:

- **World** — geopolitics, conflict, macroeconomics, public health, climate, major elections, sanctions, court rulings on national policy.
- **Singapore** — local policy, MAS, parliament, regional security with SG implications.
- **Tech** — security CVEs, AI industry moves, infrastructure shifts, supply-chain stories, foundational research.

It deliberately filters OUT sports, entertainment, lifestyle, opinion/commentary, product reviews, gadget launches, deal roundups, and human-interest oddities. The ranker is biased toward substance over hot takes.

## Mechanism

Six-stage pipeline, one script per stage in `src/`:

```
fetch_feeds.py     → raw_items.json    RSS pull, junk filter, cross-day dedup
rank.py            → ranked.json       Claude (Haiku) picks top ~30 by impact
scrape_content.py  → enriched.json     Fetch full article body for the ~30
summarize.py       → digest.json       Claude (Sonnet) writes summary + key points
render_md.py       → digests/, README  Render Markdown
git push           → GitHub            Publish for mobile reading
```

**Claude Code, not Anthropic API.** `rank.py` and `summarize.py` shell out to the `claude` CLI rather than calling the Anthropic API directly. This piggybacks on the existing Claude Code subscription — no separate API key, no per-call billing. Trade-off: less control over generation. The CLI exposes no `max_tokens` flag, no native JSON-output mode, and no separate system message — which is why the prompts include explicit "begin with `{`" priming and the scripts retry on bad JSON.

**Plain Markdown prompts, not Claude Code Skills.** `prompts/rank.md` and `prompts/summarize.md` are plain files passed via `claude -p`. Skills would add discovery and packaging machinery that pays off when the same prompt is reused across many contexts; these two prompts are single-purpose to this pipeline with no expected reuse elsewhere, so plain Markdown keeps iteration tight — edit, run, eyeball, edit.

**Bucket assignment**: each RSS item carries a *feed bucket* (`world` / `singapore` / `tech`), but the ranker re-buckets by *topic*. A chip-factory story from NYT-Business is re-tagged `tech`; a Singapore-relevant story from CNA-World is re-tagged `singapore`.

**Cross-day dedup**: `published_links.json` records every URL ever included in a digest. `fetch_feeds.py` skips matching items, so the same story doesn't appear two days running. The file is committed so dedup state survives a re-clone.

**Resilience**: rank/summarize calls retry up to 3× on (a) timeout, (b) non-zero claude exit, or (c) bad JSON. Every failure dumps `claude`'s stderr+stdout to `logs/{rank,summarize}_{stderr,response}_<ts>_a<n>.txt` for post-mortem.

**Schedule**: `launchd` runs `com.newsagent.daily` at 6am SGT (see `com.newsagent.plist.template` + `install.sh`). `pmset repeat wakeorpoweron MTWRFSU 05:55:00` wakes the Mac 5 min beforehand; `caffeinate -i` keeps it awake during the ~3–5 min run.

**Push auth**: uses a dedicated passphraseless deploy key (`~/.ssh/news_agent_deploy`) via `git config core.sshCommand` with `IdentityAgent=none` and `IdentitiesOnly=yes`. The unattended job does not depend on `ssh-agent` or macOS keychain — both proved unreliable across reboots for a 6am background job.

## Assumptions

Designed for a single specific setup:

- **macOS** with `launchd` (Apple Silicon Homebrew paths in the plist).
- **pyenv-virtualenv** venv named `news-virtualenv-3.13` (Python 3.13.5). Install `requirements.txt` into the venv directly (`~/.pyenv/versions/news-virtualenv-3.13/bin/pip`).
- **Claude Code CLI** at `~/.local/bin/claude`, with an active Claude subscription that has Haiku + Sonnet access.
- **GitHub deploy key**: `~/.ssh/news_agent_deploy.pub` added to the repo's Deploy Keys with **Allow write access** enabled. Generate with `ssh-keygen -t ed25519 -f ~/.ssh/news_agent_deploy -N ''`.
- **Mac stays plugged in and can wake from sleep** at 5:55am (lid closed is fine). `LaunchAgents` only fire while a user is logged in.
- **Mac timezone is SGT** — the plist uses local time, not UTC.

`install.sh` (idempotent) wires up the plist, the `core.sshCommand`, and verifies the deploy key is present.

## Limitations

- **RSS-only sources.** No API-based feeds (Reuters Connect), no podcasts, no newsletters, no Substack.
- **Paywall-aware, not paywall-bypassing.** NYT returns lead paragraphs (1–2 KB); summaries may be thinner than for fully-accessible sources.
- **InfoQ blocks automated scrapers** (AWS WAF captcha). Those items use the RSS-summary fallback — shorter but usable.
- **Claude reliability is the bottleneck**, especially the Sonnet summarize call. Roughly 1 in 3 mornings at 6am SGT has hit a timeout, non-zero exit, or hang (recovered manually or by retries). Likely culprits: Anthropic peak-hour load (6am SGT = US evening + EU late evening), Claude Code subscription rolling-window limits, or larger-than-usual payloads. Stderr is now captured for definitive diagnosis on the next failure.
- **No failure alerting.** A failed run is silent — discovered only by the digest looking stale on your phone. Opt-in alerting (macOS notification or ntfy push) is available but not enabled.
- **URL-based dedup misses republishes.** The same story under a different URL (CNA update of an earlier piece) will appear twice.
- **Cross-source dedup is best-effort, not guaranteed.** When CNA, BBC, and NYT all cover the same event, the ranker is *instructed* (in `prompts/rank.md`) to pick the most authoritative version and drop the rest — but it's a prompt-level instruction, not enforced code. On busy news days (e.g. major US–Iran or EU-policy events) two or three takes on the same story sometimes slip through.
- **Bucket distribution is suggested, not enforced.** The ranker targets ~10 world / ~5 SG / ~10 tech but skews when a day's feeds are unbalanced.
- **Single-host dependency.** If the Mac is fully off (not asleep) at 6am, or has no network, no digest that day. There is no cloud fallback.

## Repo layout

```
src/             pipeline scripts (fetch, rank, scrape, summarize, render)
prompts/         rank.md, summarize.md — Claude system prompts
templates/       digest.md.j2 — Jinja2 template for daily digests
feeds.yaml       RSS source list
hooks/           pre-commit allowlist (activated via core.hooksPath=hooks)
run_news_agent.sh    daily entrypoint, invoked by launchd
install.sh           idempotent setup: plist + git config + deploy-key check
com.newsagent.plist.template    launchd job (paths interpolated by install.sh)
digests/         generated Markdown (today.md + dated archive)
published_links.json  cross-day dedup state (tracked)
```