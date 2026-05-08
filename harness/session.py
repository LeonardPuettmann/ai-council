"""Session state machine: convene → opening → debate → proposal → vote → close."""
from __future__ import annotations

import datetime as dt
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from harness import orchestrator, ui
from harness.member import build_system, parse_response, speak
from harness.roster import Member, load_alfred, load_context, load_members, load_protocol

TRANSCRIPTS_DIR = Path(__file__).resolve().parent.parent / "transcripts"


@dataclass
class TurnRecord:
    speaker: str           # display name
    speaker_slug: str
    role: str              # "alfred" | "member" | "user" | "system"
    text: str
    kind: str = "speech"   # speech | opening | proposal | vote | summary | followup


@dataclass
class Session:
    question: str
    members: dict[str, Member]
    alfred: Member
    protocol: str
    panel: list[Member] = field(default_factory=list)
    turns: list[TurnRecord] = field(default_factory=list)
    max_rounds: int = 3
    max_tokens_per_turn: int = 600
    context: str | None = None

    def alfred_model(self) -> str:
        return os.getenv("ALFRED_MODEL", "anthropic:claude-sonnet-4-6")

    # Each member sees the running debate as a sequence of user-role messages
    # tagged with the speaker's name. We build that view fresh for each call so
    # all members see the full shared context.
    def transcript_for_llm(self) -> list[dict]:
        msgs: list[dict] = []
        msgs.append({"role": "user", "content": f"The user's question:\n\n{self.question}"})
        for t in self.turns:
            if t.kind in ("opening", "speech", "followup"):
                msgs.append(
                    {"role": "user", "content": f"[{t.speaker}]\n{t.text}"}
                )
        return msgs

    def record(self, **kwargs) -> None:
        self.turns.append(TurnRecord(**kwargs))

    def save(self) -> Path:
        TRANSCRIPTS_DIR.mkdir(exist_ok=True)
        slug = re.sub(r"[^a-z0-9]+", "-", self.question.lower())[:40].strip("-")
        ts = dt.datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
        base = TRANSCRIPTS_DIR / f"{ts}_{slug or 'session'}"
        json_path = base.with_suffix(".json")
        md_path = base.with_suffix(".md")

        json_path.write_text(
            json.dumps(
                {
                    "question": self.question,
                    "panel": [m.slug for m in self.panel],
                    "turns": [t.__dict__ for t in self.turns],
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        md = [f"# Council session\n\n**Question:** {self.question}\n"]
        md.append(f"**Panel:** {', '.join(m.name for m in self.panel)}\n\n---\n")
        for t in self.turns:
            md.append(f"## {t.speaker} _{t.kind}_\n\n{t.text}\n")
        md_path.write_text("\n".join(md), encoding="utf-8")
        return md_path


def run_session(
    *,
    question: str,
    forced_picks: Optional[list[str]] = None,
    max_rounds: int = 3,
    max_tokens: int = 600,
) -> Session:
    members = load_members()
    alfred = load_alfred()
    protocol = load_protocol()
    context = load_context()

    sess = Session(
        question=question,
        members=members,
        alfred=alfred,
        protocol=protocol,
        max_rounds=max_rounds,
        max_tokens_per_turn=max_tokens,
        context=context,
    )

    # 1. Convene
    if forced_picks:
        slugs = [s for s in forced_picks if s in members][:3]
        if len(slugs) < 3:
            ui.warn(f"Only matched {len(slugs)} of 3 picks. Filling.")
            for s in members:
                if s not in slugs:
                    slugs.append(s)
                if len(slugs) == 3:
                    break
        sess.panel = [members[s] for s in slugs]
        roster_lines = ", ".join(m.name for m in sess.panel)
        alfred_text = f"As you wish, sir. I have called {roster_lines}."
        ui.static_panel(
            title=f"{alfred.emoji} {alfred.name}",
            body=alfred_text,
            color=alfred.color,
        )
        sess.record(
            speaker=alfred.name,
            speaker_slug=alfred.slug,
            role="alfred",
            text=alfred_text,
            kind="speech",
        )
    else:
        with ui.thinking("Alfred is selecting council…"):
            selection = orchestrator.select_members(
                alfred_model=sess.alfred_model(),
                question=question,
                members=members,
                context=sess.context,
            )
        sess.panel = [members[s] for s in selection.slugs]
        roster_lines = " · ".join(m.name for m in sess.panel)
        body = f"Selected: {roster_lines}\n\n{selection.reasoning}"
        ui.static_panel(
            title=f"{alfred.emoji} {alfred.name}",
            body=body,
            color=alfred.color,
        )
        sess.record(
            speaker=alfred.name,
            speaker_slug=alfred.slug,
            role="alfred",
            text=body,
            kind="speech",
        )

    # 2. Opening statements
    ui.rule("Opening statements")
    for m in sess.panel:
        _stream_member_turn(sess, m, prompt_kind="opening")

    # 3. Debate rounds
    # pending_questions: target_slug -> list[(asker_name, question_text)]
    pending_questions: dict[str, list[tuple[str, str]]] = {}

    for round_no in range(1, sess.max_rounds + 1):
        ui.rule(f"Round {round_no} of {sess.max_rounds}")

        # Members with pending questions speak first, in panel order.
        targets = [m for m in sess.panel if m.slug in pending_questions]
        others = [m for m in sess.panel if m.slug not in pending_questions]
        speakers = targets + others

        new_questions: dict[str, list[tuple[str, str]]] = {}
        for m in speakers:
            extra = _round_directive(m, pending_questions.get(m.slug, []))
            resp = _stream_member_turn(sess, m, prompt_kind="speech", extra=extra)
            for tgt, q in resp.questions:
                tgt_slug = _resolve_slug(tgt, sess.panel)
                if tgt_slug and tgt_slug != m.slug:
                    new_questions.setdefault(tgt_slug, []).append((m.name, q))

        # Alfred's between-rounds choice
        if round_no >= sess.max_rounds:
            ui.info(
                f"Alfred: We have reached the maximum of {sess.max_rounds} rounds. "
                f"Closing the debate."
            )
            break
        if not new_questions and not _disagreement_present(sess):
            ui.info(
                "Alfred: I believe we have heard the strongest version of the argument. "
                "Closing the debate."
            )
            break

        pending_questions = new_questions

        # Show a clear Alfred status + ask the user what to do.
        status = [f"**End of round {round_no} of {sess.max_rounds}.**", ""]
        if pending_questions:
            status.append("Pending questions I shall route next round:")
            status.append("")
            for tgt_slug, qs in pending_questions.items():
                target = next((m for m in sess.panel if m.slug == tgt_slug), None)
                tname = target.name if target else tgt_slug
                for asker, q in qs:
                    short = q if len(q) <= 100 else q[:97] + "…"
                    status.append(f"- **{asker} → {tname}:** {short}")
            status.append("")
        else:
            status.append("No outstanding questions between members.")
            status.append("")
        status.append("**How shall I proceed, sir?**")
        status.append("")
        status.append("- `c` (or Enter) — continue to next round")
        status.append("- `a` — you ask a follow-up of the council before continuing")
        status.append("- `w` — wrap up: go straight to proposal and vote")
        status.append("- `q` — quit the session")

        ui.static_panel(
            title=f"{alfred.emoji} {alfred.name}",
            body="\n".join(status),
            color=alfred.color,
        )

        choice = ui.console.input("[bold gold1]❯[/bold gold1] ").strip().lower()

        if choice in ("q", "quit"):
            ui.info("Session aborted.")
            return sess
        if choice in ("w", "wrap"):
            break
        if choice in ("a", "ask"):
            followup = ui.console.input(
                "[bold]Your follow-up to the council:[/bold] "
            ).strip()
            if followup:
                ui.static_panel(title="You", body=followup, color="white")
                sess.record(
                    speaker="User",
                    speaker_slug="user",
                    role="user",
                    text=followup,
                    kind="followup",
                )
        # Anything else (including empty input or 'c') → continue to next round.

    # 4. Proposal
    ui.rule("Proposal")
    with ui.thinking("Alfred is drafting a proposal…"):
        proposal = orchestrator.draft_proposal(
            alfred_model=sess.alfred_model(),
            transcript=sess.transcript_for_llm(),
            context=sess.context,
        )
    ui.static_panel(
        title=f"{alfred.emoji} {alfred.name} — proposal",
        body=proposal,
        color=alfred.color,
    )
    sess.record(
        speaker=alfred.name,
        speaker_slug=alfred.slug,
        role="alfred",
        text=proposal,
        kind="proposal",
    )

    # 5. Vote
    ui.rule("Vote")
    votes: list[tuple[str, str, str]] = []
    for m in sess.panel:
        with ui.thinking(f"{m.name} is voting…"):
            vote, reason = orchestrator.cast_vote(
                member=m,
                proposal=proposal,
                transcript=sess.transcript_for_llm(),
                context=sess.context,
            )
        votes.append((m.name, vote, reason))
        marker = {"YES": "✓", "NO": "✗", "ABSTAIN": "—"}.get(vote, "?")
        ui.static_panel(
            title=f"{m.emoji} {m.name} — {marker} {vote}",
            body=reason,
            color=m.color,
        )
        sess.record(
            speaker=m.name,
            speaker_slug=m.slug,
            role="member",
            text=f"{vote}: {reason}",
            kind="vote",
        )

    # Tally line
    yes = sum(1 for _, v, _ in votes if v == "YES")
    no = sum(1 for _, v, _ in votes if v == "NO")
    ab = sum(1 for _, v, _ in votes if v == "ABSTAIN")
    tally = f"YES: {yes}  ·  NO: {no}  ·  ABSTAIN: {ab}"
    ui.info(f"Tally — {tally}")

    # 6. Closing summary
    with ui.thinking("Alfred is closing the session…"):
        summary = orchestrator.closing_summary(
            alfred_model=sess.alfred_model(),
            proposal=proposal,
            votes=votes,
            transcript=sess.transcript_for_llm(),
        )
    ui.static_panel(
        title=f"{alfred.emoji} {alfred.name} — closing",
        body=summary,
        color=alfred.color,
    )
    sess.record(
        speaker=alfred.name,
        speaker_slug=alfred.slug,
        role="alfred",
        text=summary,
        kind="summary",
    )

    path = sess.save()
    ui.info(f"Transcript saved → {path}")
    return sess


def _stream_member_turn(
    sess: Session,
    member: Member,
    *,
    prompt_kind: str,
    extra: str = "",
):
    transcript = sess.transcript_for_llm()
    if extra:
        transcript = transcript + [{"role": "user", "content": extra}]
    if prompt_kind == "opening":
        transcript = transcript + [
            {
                "role": "user",
                "content": (
                    f"[Alfred: opening statements, {member.name}. "
                    f"Two short paragraphs. Stake out your position; do not yet respond to others.]"
                ),
            }
        ]

    title = f"{member.emoji} {member.name}"
    chunks = speak(
        member=member,
        protocol=sess.protocol,
        transcript=transcript,
        max_tokens=sess.max_tokens_per_turn,
        context=sess.context,
    )
    full = ui.stream_panel(title=title, color=member.color, chunks=chunks)
    resp = parse_response(member.slug, full)
    sess.record(
        speaker=member.name,
        speaker_slug=member.slug,
        role="member",
        text=resp.body,
        kind=prompt_kind,
    )
    return resp


def _round_directive(
    member: Member, questions: list[tuple[str, str]]
) -> str:
    """Per-turn instruction that forces engagement with what just happened."""
    if questions:
        q_lines = "\n".join(f'  • {asker}: "{q}"' for asker, q in questions)
        return (
            "[Alfred: this is a debate round. Direct questions have been put to you. "
            "Address EACH ONE of them by name, in turn. Do not duck any of them. "
            "After answering, you may add a brief observation or push back, but the "
            "questions come first.]\n\n"
            f"Questions for you, {member.name}:\n{q_lines}"
        )
    return (
        "[Alfred: this is a debate round. Respond specifically to what the other "
        "members just said — name them, quote them if useful, agree or disagree on "
        "concrete points. Do NOT restate your opening statement.\n\n"
        "If you genuinely have nothing new to add this round, say so in one or two "
        "sentences (\"On this I'm with X — I'd only add Y.\" or \"I have nothing to "
        "add to that.\") and yield. Silence beats repetition.]"
    )


def _resolve_slug(target: str, panel: list[Member]) -> Optional[str]:
    """Match a question target against a panel member's slug or name."""
    t = target.strip().lower().replace(" ", "-")
    for m in panel:
        if m.slug == t or m.name.lower() == target.strip().lower():
            return m.slug
        last = m.name.split()[-1].lower()
        if t == last or target.strip().lower() == last:
            return m.slug
    return None


def _disagreement_present(sess: Session) -> bool:
    """Heuristic: did the latest round contain disagreement words?"""
    cues = ("disagree", "wrong", "no,", "but", "however", "actually")
    recent = [t.text.lower() for t in sess.turns[-3:] if t.role == "member"]
    return any(any(c in r for c in cues) for r in recent)
