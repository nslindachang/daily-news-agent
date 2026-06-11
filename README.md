# news-agent

Self-hosted daily news digest. Each morning at 6am SGT, pulls ~17 RSS feeds across world, Singapore, and tech sources, uses Claude to filter for impact and write summaries, and publishes a Markdown digest to a repo for reading on mobile via the GitHub app.

## Today's digest

→ *Not available in this repo*

## Intent

A personal daily-reader replacement, not a general news tool. Assumes one reader (Singapore-based) who wants to be well-informed about:

- **World** — geopolitics, conflict, macroeconomics, public health, climate, major elections, sanctions, court rulings on national policy.
- **Singapore** — local policy, MAS, parliament, regional security with SG implications.
- **Tech** — security CVEs, AI industry moves, infrastructure shifts, supply-chain stories, foundational research.

It deliberately filters OUT sports, entertainment, lifestyle, opinion/commentary, product reviews, gadget launches, deal roundups, and human-interest oddities. The ranker is biased toward substance over hot takes.

## How it works

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

## Setup

Prerequisites are listed in [Assumptions](#assumptions) below. The flow:

1. **Clone the repo** into your workspace.

2. **Create and activate the Python virtualenv** (the name must match what's in `.python-version`):
   ```
   pyenv virtualenv 3.13.5 news-virtualenv-3.13
   pyenv activate news-virtualenv-3.13
   ```

3. **Install dependencies**:
   ```
   pip install -r requirements.txt
   ```

4. **Generate the dedicated deploy key** (no passphrase, used only by this project):
   ```
   ssh-keygen -t ed25519 -f ~/.ssh/news_agent_deploy -N ''
   ```

5. **Add the public key as a Deploy Key on GitHub**:
   - Open `https://github.com/<your-user>/news-agent/settings/keys/new`
   - Paste the contents of `~/.ssh/news_agent_deploy.pub` into the Key field
   - Tick **Allow write access** (required — without it the daily push will fail)
   - Click **Add key**

6. **Run the installer** (idempotent — safe to re-run):
   ```
   ./install.sh
   ```
   This renders the launchd plist from its template, installs it into `~/Library/LaunchAgents`, bootstraps the job, and configures `git core.sshCommand` to use the deploy key.

7. **Schedule the Mac to wake** before the 6am job (one-time, requires sudo):
   ```
   sudo pmset repeat wakeorpoweron MTWRFSU 05:55:00
   ```
   Verify with `pmset -g sched`.

Uninstall with `./install.sh uninstall`.

## Usage

**Daily automated run.** Nothing to do — `launchd` fires `com.newsagent.daily` at 6am SGT and the pipeline takes 3–5 minutes. The new digest lands at `digests/today.md` and on GitHub for mobile reading.

**Manual run.** From the project root:
```
./run_news_agent.sh
```
Same script `launchd` invokes — same allowlist git push, same logging. Useful for testing changes to prompts, feeds, or scripts.

**Test the launchd code path itself** (runs in the unattended context, not your shell):
```
launchctl kickstart -p gui/$(id -u)/com.newsagent.daily
tail -f logs/$(date +%Y-%m-%d).log
```

**Read the digest on mobile.** Open the GitHub iOS/Android app → `news-agent` repo → `digests/today.md`. Bookmark it once.

**Inspect a failure.**
- Per-day script log: `logs/YYYY-MM-DD.log`
- `claude` stderr+stdout dumped on retryable failures: `logs/{rank,summarize}_{stderr,response}_<ts>_a<n>.txt`
- launchd-level stdout/err: `logs/launchd.out`, `logs/launchd.err`

**Force a fresh pipeline** (discard intermediate state from a prior partial run):
```
rm -f raw_items.json ranked.json enriched.json digest.json
./run_news_agent.sh
```

## Configuration

No environment variables. Everything tunable lives in a small set of files:

| What to change | Where |
|---|---|
| RSS sources — add/remove/reorder feeds | `feeds.yaml` |
| Ranking criteria, bucket targets, junk rules | `prompts/rank.md` |
| Summary voice, length, key-points style | `prompts/summarize.md` |
| Rank model (Haiku default) and per-attempt timeout (180s) | `src/rank.py` — `CLAUDE_MODEL`, `CALL_TIMEOUT` |
| Summarize model (Sonnet default) and per-attempt timeout (360s) | `src/summarize.py` — `CLAUDE_MODEL`, `CALL_TIMEOUT` |
| RSS lookback window (30h default) | `src/fetch_feeds.py` — `MAX_AGE_HOURS` |
| Pre-rank junk filters — title patterns, URL paths, category tokens | `src/fetch_feeds.py` — `JUNK_*` constants |
| Number of claude retries (3 default) and backoff | `src/claude_client.py` |
| Daily schedule | `com.newsagent.plist.template` — `StartCalendarInterval` (re-run `./install.sh` after) |
| Mac wake schedule | `pmset` (run the command from Setup step 7 with new times) |
| Allowlist of paths that may be committed | `hooks/pre-commit` |

## Assumptions

The environmental contract — *what must be true* for the system to work. See [Setup](#setup) for the commands that satisfy each one.

- **macOS** with `launchd` (Apple Silicon Homebrew paths in the plist).
- **Python 3.13** available via `pyenv`, plus the `pyenv-virtualenv` plugin.
- **Claude Code CLI** installed at `~/.local/bin/claude`, with an active subscription that includes Haiku and Sonnet access.
- **A passphraseless SSH key** registered as a write-enabled Deploy Key on the repo, so the daily push runs without ssh-agent or keychain.
- **Mac stays plugged in and able to wake from sleep** at 5:55 am (lid closed is fine). `LaunchAgents` only fire while a user is logged in.
- **Mac timezone is SGT** — the plist uses local time, not UTC.

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

## AI Assistance Disclosure

Parts of this project were developed with assistance from generative AI tools.