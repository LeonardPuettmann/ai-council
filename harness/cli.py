"""REPL entry point. Loads .env, presents the prompt, dispatches commands."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory

from harness import ui
from harness.roster import CONTEXT_PATH, load_context, load_members
from harness.session import TRANSCRIPTS_DIR, run_session

ROOT = Path(__file__).resolve().parent.parent
HISTORY_FILE = ROOT / ".council_history"


def main() -> None:
    load_dotenv(dotenv_path=ROOT / ".env")
    if not (os.getenv("ANTHROPIC_API_KEY") or os.getenv("MISTRAL_API_KEY")):
        ui.error("No API key found. Set ANTHROPIC_API_KEY or MISTRAL_API_KEY in .env.")
        sys.exit(1)

    members = load_members()
    ui.banner(member_count=len(members), context_loaded=load_context() is not None)

    forced_picks: list[str] | None = None
    max_rounds = int(os.getenv("MAX_DEBATE_ROUNDS", "3"))
    max_tokens = int(os.getenv("MAX_TOKENS_PER_TURN", "600"))
    last_transcript: Path | None = None

    session = PromptSession(history=FileHistory(str(HISTORY_FILE)))

    while True:
        try:
            line = session.prompt(HTML("\n<ansiyellow><b>❯</b></ansiyellow> "))
        except (KeyboardInterrupt, EOFError):
            ui.info("Goodbye.")
            return

        line = line.strip()
        if not line:
            continue

        if line.startswith("/"):
            parts = line[1:].split(maxsplit=1)
            cmd = parts[0].lower()
            arg = parts[1] if len(parts) > 1 else ""

            if cmd in ("quit", "exit", "q"):
                ui.info("Goodbye.")
                return
            if cmd == "help":
                ui.slash_help()
                continue
            if cmd == "clear":
                ui.console.clear()
                ui.banner(member_count=len(members), context_loaded=load_context() is not None)
                continue
            if cmd == "context":
                ctx = load_context()
                if ctx:
                    n = len(ctx)
                    ui.info(f"context.md loaded ({n} chars) — {CONTEXT_PATH}")
                else:
                    ui.info(f"No context.md at {CONTEXT_PATH}")
                continue
            if cmd == "members":
                rows = [
                    f"  {m.emoji} [bold {m.color}]{m.name}[/bold {m.color}] "
                    f"([dim]{m.slug}[/dim]) — {m.domain}"
                    for m in members.values()
                ]
                ui.console.print("\n".join(rows))
                continue
            if cmd == "pick":
                if not arg:
                    ui.warn("Usage: /pick slug1,slug2,slug3  (or /auto to clear)")
                    continue
                slugs = [s.strip().lower().replace(" ", "-") for s in arg.split(",")]
                missing = [s for s in slugs if s not in members]
                if missing:
                    ui.warn(f"Unknown: {', '.join(missing)}")
                    continue
                forced_picks = slugs[:3]
                ui.info(f"Pick locked: {', '.join(forced_picks)}")
                continue
            if cmd == "auto":
                forced_picks = None
                ui.info("Selection returned to Alfred.")
                continue
            if cmd == "rounds":
                try:
                    max_rounds = max(1, int(arg))
                    ui.info(f"Max rounds: {max_rounds}")
                except ValueError:
                    ui.warn("Usage: /rounds N")
                continue
            if cmd == "last":
                if last_transcript:
                    ui.info(str(last_transcript))
                else:
                    ui.info("No session yet this run.")
                continue

            ui.warn(f"Unknown command: /{cmd}. Try /help.")
            continue

        ui.console.print()
        try:
            sess = run_session(
                question=line,
                forced_picks=forced_picks,
                max_rounds=max_rounds,
                max_tokens=max_tokens,
            )
            forced_picks = None
            # find latest transcript file
            mds = sorted(TRANSCRIPTS_DIR.glob("*.md"))
            if mds:
                last_transcript = mds[-1]
        except KeyboardInterrupt:
            ui.warn("Session interrupted.")
        except Exception as e:  # noqa: BLE001
            ui.error(f"{type(e).__name__}: {e}")
