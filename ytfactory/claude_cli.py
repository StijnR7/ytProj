"""Thin wrapper around the Claude Code CLI in headless mode (`claude -p`).

Uses your Claude subscription login - no API key. We deliberately strip
ANTHROPIC_API_KEY from the environment so the CLI can never fall back to
pay-per-token API billing.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

from .config import load_config


SYSTEM_PROMPT = (
    "You are the head writer, researcher and producer of an educational YouTube documentary channel. "
    "You are not working on software. Follow the user's instructions exactly and answer with only the requested output."
)


class ClaudeError(RuntimeError):
    pass


def find_claude() -> str | None:
    cmd = load_config()["claude"]["command"]
    found = shutil.which(cmd)
    if found:
        return found
    # Common install locations (native installer / npm on Windows)
    home = Path.home()
    for cand in [
        home / ".local" / "bin" / "claude.exe",
        home / ".local" / "bin" / "claude",
        home / "AppData" / "Roaming" / "npm" / "claude.cmd",
    ]:
        if cand.exists():
            return str(cand)
    return None


def ask(
    prompt: str,
    *,
    allow_web: bool = False,
    workdir: Path | None = None,
    log: Callable[[str], None] = print,
) -> str:
    """Send a prompt to Claude Code and return the final text response."""
    cfg = load_config()["claude"]
    exe = find_claude()
    if not exe:
        raise ClaudeError(
            "Claude Code CLI not found. Install it (see README) and run `claude` once to log in."
        )
    args = [exe, "-p", "--output-format", "json", "--system-prompt", SYSTEM_PROMPT]
    if cfg.get("model"):
        args += ["--model", str(cfg["model"])]
    if allow_web:
        args += ["--tools", "WebSearch,WebFetch", "--allowedTools", "WebSearch", "WebFetch"]
    else:
        args += ["--tools", ""]

    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
    env.setdefault("PYTHONIOENCODING", "utf-8")

    tmp = None
    if workdir is None:
        tmp = tempfile.mkdtemp(prefix="ytf_claude_")
        workdir = Path(tmp)
    workdir.mkdir(parents=True, exist_ok=True)

    log(f"  -> asking Claude ({len(prompt):,} chars{', web research on' if allow_web else ''})...")
    try:
        proc = subprocess.run(
            args,
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(workdir),
            env=env,
            timeout=int(cfg.get("timeout_minutes", 20)) * 60,
        )
    except subprocess.TimeoutExpired as e:
        raise ClaudeError("Claude took too long to answer (timeout). Try again.") from e
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)

    out = (proc.stdout or "").strip()
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        raise ClaudeError(
            f"Unexpected output from Claude CLI (exit {proc.returncode}):\n{out[:800]}\n{(proc.stderr or '')[:800]}"
        )
    if data.get("is_error") or data.get("subtype") not in (None, "success"):
        raise ClaudeError(f"Claude reported an error: {data.get('result') or data}")
    result = data.get("result") or ""
    if not result.strip():
        raise ClaudeError("Claude returned an empty answer.")
    return result


# ---------------------------------------------------------------- JSON helpers

def extract_json(text: str) -> Any:
    """Pull a JSON object/array out of a model response."""
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    candidates = []
    if m:
        candidates.append(m.group(1))
    starts = [i for i in (text.find("{"), text.find("[")) if i >= 0]
    if starts:
        s = min(starts)
        e = max(text.rfind("}"), text.rfind("]"))
        if e > s:
            candidates.append(text[s : e + 1])
    candidates.append(text)
    last_err = None
    for c in candidates:
        for variant in (c, re.sub(r",\s*([}\]])", r"\1", c)):
            try:
                return json.loads(variant)
            except json.JSONDecodeError as err:
                last_err = err
    raise ValueError(f"Could not parse JSON from Claude: {last_err}")


def ask_json(
    prompt: str,
    *,
    allow_web: bool = False,
    validate: Callable[[Any], None] | None = None,
    log: Callable[[str], None] = print,
    retries: int = 1,
) -> Any:
    """Ask for JSON, parse + validate, and ask Claude to repair once on failure."""
    text = ask(prompt, allow_web=allow_web, log=log)
    for attempt in range(retries + 1):
        try:
            data = extract_json(text)
            if validate:
                validate(data)
            return data
        except Exception as err:  # noqa: BLE001
            if attempt >= retries:
                raise ClaudeError(f"Claude's answer was not valid: {err}") from err
            log(f"  !! answer invalid ({err}); asking Claude to fix it")
            text = ask(
                "The JSON below has a problem: "
                f"{err}\n\nReturn the corrected, complete JSON only, in a ```json block. "
                "Keep all content; just fix the problem.\n\n" + text,
                log=log,
            )
    raise ClaudeError("unreachable")
