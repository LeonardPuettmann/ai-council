"""Loads council member profiles from disk and builds the compact roster Alfred uses."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

COUNCIL_DIR = Path(__file__).resolve().parent.parent / "council"
PROTOCOL_PATH = Path(__file__).resolve().parent.parent / "council-protocol.md"
CONTEXT_PATH = Path(__file__).resolve().parent.parent / "context.md"

# Stable color assignments for terminal rendering (rich color names).
COLORS = {
    "alfred":          "gold1",
    "gabe-newell":     "deep_sky_blue1",
    "warren-buffett":  "green3",
    "david-ogilvy":    "magenta",
    "andrew-grove":    "orange1",
    "pewdiepie":       "hot_pink",
    "marcus-aurelius": "cyan",
    "sun-tzu":         "red3",
    "harvey-specter":  "red1",
    "michael-stevens": "yellow",
    "alan-turing":     "blue_violet",
}

EMOJI = {
    "alfred":          "🎩",
    "gabe-newell":     "🎮",
    "warren-buffett":  "📈",
    "david-ogilvy":    "✍️",
    "andrew-grove":    "⚙️",
    "pewdiepie":       "📺",
    "marcus-aurelius": "🏛️",
    "sun-tzu":         "♟️",
    "harvey-specter":  "⚖️",
    "michael-stevens": "🧠",
    "alan-turing":     "💻",
}


@dataclass
class Member:
    slug: str          # folder name, e.g. "warren-buffett"
    name: str          # display name, e.g. "Warren Buffett"
    domain: str        # one-line domain, from H1 italic line
    summary: str       # one-paragraph summary for Alfred's selection
    personality: str   # full personality.md content
    color: str
    emoji: str

    @property
    def env_key(self) -> str:
        return "COUNCIL_MODEL_" + self.slug.upper().replace("-", "_")

    def model_spec(self) -> str:
        return os.getenv(self.env_key) or os.getenv(
            "COUNCIL_DEFAULT_MODEL", "anthropic:claude-sonnet-4-6"
        )


def _parse_personality(slug: str, text: str) -> tuple[str, str, str]:
    """Return (display_name, domain, summary)."""
    lines = text.splitlines()
    name = slug.replace("-", " ").title()
    domain = ""
    for line in lines:
        if line.startswith("# "):
            name = line[2:].strip()
            break
    for line in lines:
        m = re.match(r"\*([^*]+)\*", line)
        if m:
            domain = m.group(1).strip().split("—")[0].strip()
            break

    # Summary = first non-empty paragraph under "## Identity"
    summary = ""
    in_identity = False
    buf: list[str] = []
    for line in lines:
        if line.strip().startswith("## Identity"):
            in_identity = True
            continue
        if in_identity:
            if line.strip().startswith("##"):
                break
            if line.strip() == "" and buf:
                break
            if line.strip():
                buf.append(line.strip())
    summary = " ".join(buf).strip()
    return name, domain, summary


def load_members() -> dict[str, Member]:
    """Load every member except Alfred."""
    out: dict[str, Member] = {}
    for path in sorted(COUNCIL_DIR.iterdir()):
        if not path.is_dir() or path.name == "alfred":
            continue
        pfile = path / "personality.md"
        if not pfile.exists():
            continue
        text = pfile.read_text(encoding="utf-8")
        name, domain, summary = _parse_personality(path.name, text)
        out[path.name] = Member(
            slug=path.name,
            name=name,
            domain=domain,
            summary=summary,
            personality=text,
            color=COLORS.get(path.name, "white"),
            emoji=EMOJI.get(path.name, "•"),
        )
    return out


def load_alfred() -> Member:
    path = COUNCIL_DIR / "alfred" / "personality.md"
    text = path.read_text(encoding="utf-8")
    name, domain, summary = _parse_personality("alfred", text)
    return Member(
        slug="alfred",
        name=name,
        domain=domain,
        summary=summary,
        personality=text,
        color=COLORS["alfred"],
        emoji=EMOJI["alfred"],
    )


def load_protocol() -> str:
    return PROTOCOL_PATH.read_text(encoding="utf-8")


def load_context() -> str | None:
    """Read context.md if present. Returns None if missing or empty."""
    if not CONTEXT_PATH.exists():
        return None
    text = CONTEXT_PATH.read_text(encoding="utf-8").strip()
    return text or None


def compact_roster(members: dict[str, Member]) -> str:
    """The roster Alfred sees when selecting."""
    lines = []
    for m in members.values():
        lines.append(f"- **{m.name}** (slug: `{m.slug}`) — {m.domain}")
        lines.append(f"  {m.summary}")
    return "\n".join(lines)
