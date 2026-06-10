"""Shared Claude CLI invocation with retries, stderr capture, and JSON parsing.

Used by rank.py and summarize.py. The two callers differ only in model,
per-attempt timeout, and label (for log messages and dump filenames).

Failure modes handled in the retry loop:
  - subprocess.TimeoutExpired  (claude hung)
  - non-zero exit              (claude errored)
  - json.JSONDecodeError       (preamble / truncation in the response)
On every failure, a stderr preview is logged and full stderr+stdout
dumped to disk for post-mortem.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path

log = logging.getLogger("claude_client")


def extract_json(text: str) -> dict:
    """Parse Claude's response; tolerant of code-fence wrapping or stray prose."""
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if m:
        text = m.group(1)
    else:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            text = m.group(0)
    return json.loads(text)


def _dump(logs_dir: Path, label: str, ts: str, attempt: int,
          stderr: str | None, stdout: str | None) -> None:
    logs_dir.mkdir(exist_ok=True)
    if stderr:
        (logs_dir / f"{label}_stderr_{ts}_a{attempt}.txt").write_text(stderr)
    if stdout:
        (logs_dir / f"{label}_response_{ts}_a{attempt}.txt").write_text(stdout)


def call_and_parse_with_retry(
    prompt: str,
    items_json: str,
    *,
    model: str,
    label: str,
    timeout: int,
    logs_dir: Path,
    attempts: int = 3,
) -> dict:
    """Call `claude -p` with retries; parse and return the response as JSON.

    Args:
        prompt: Instructions passed via `-p`.
        items_json: JSON string piped to claude's stdin.
        model: Model alias (e.g. 'haiku', 'sonnet').
        label: Tag used in log messages and dump filenames (e.g. 'rank',
            'summarize') so failures from different stages are distinguishable.
        timeout: Per-attempt wall-time limit in seconds.
        logs_dir: Where to write debug dumps on failure.
        attempts: How many tries before giving up.
    """
    cmd = ["claude", "-p", prompt, "--model", model]
    last_err: object = None

    for attempt in range(1, attempts + 1):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        log.info("[%s] Calling claude (model=%s, prompt=%dB, stdin=%dB, timeout=%ds) [%d/%d]",
                 label, model, len(prompt), len(items_json), timeout, attempt, attempts)

        try:
            result = subprocess.run(
                cmd, input=items_json, capture_output=True, text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            last_err = exc
            stderr = (exc.stderr.decode("utf-8", "replace") if isinstance(exc.stderr, bytes)
                      else (exc.stderr or ""))
            stdout = (exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes)
                      else (exc.stdout or ""))
            log.warning("[%s] claude TIMED OUT after %ds (attempt %d/%d)",
                        label, timeout, attempt, attempts)
            log.warning("[%s] stderr tail: %s", label, stderr[-500:] if stderr else "(empty)")
            _dump(logs_dir, label, ts, attempt, stderr, stdout)
        else:
            if result.returncode != 0:
                last_err = f"exit {result.returncode}"
                log.warning("[%s] claude EXITED %d (attempt %d/%d)",
                            label, result.returncode, attempt, attempts)
                log.warning("[%s] stderr tail: %s", label,
                            (result.stderr or "")[-500:] or "(empty)")
                log.warning("[%s] stdout tail: %s", label,
                            (result.stdout or "")[-300:] or "(empty)")
                _dump(logs_dir, label, ts, attempt, result.stderr, result.stdout)
            else:
                log.info("[%s] Claude responded (%dB) [attempt %d/%d]",
                         label, len(result.stdout), attempt, attempts)
                try:
                    return extract_json(result.stdout)
                except json.JSONDecodeError as exc:
                    last_err = exc
                    log.warning("[%s] PARSE FAILED (attempt %d/%d): %s",
                                label, attempt, attempts, exc)
                    log.warning("[%s] response tail: %s", label, result.stdout[:500])
                    if result.stderr:
                        log.warning("[%s] stderr tail: %s", label, result.stderr[-500:])
                    _dump(logs_dir, label, ts, attempt, result.stderr, result.stdout)

        if attempt < attempts:
            backoff = 30 * attempt
            log.warning("[%s] Retrying in %ds...", label, backoff)
            time.sleep(backoff)

    raise RuntimeError(f"All {attempts} {label} attempts failed; last error: {last_err}")
