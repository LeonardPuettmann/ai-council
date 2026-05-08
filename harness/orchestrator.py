"""Alfred — selects members, moderates, drafts proposals, tallies votes."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

from harness.llm import LLMError, collect, stream
from harness.roster import Member, compact_roster, load_protocol


@dataclass
class Selection:
    slugs: list[str]
    reasoning: str


SELECTION_SYSTEM = """You are Alfred Pennyworth, the orchestrator of an advisory council.
Your role here is purely to SELECT three council members for a given question.

Speak in your butler voice — dry, formal, faintly amused. Brief. One sentence
of reasoning per pick. Choose three members whose disagreements will be most
productive for the question, not three who will agree.

You MUST respond in this exact format:

<selection>
<member slug="..." />
<member slug="..." />
<member slug="..." />
</selection>

<reasoning>
A short paragraph (2-4 sentences) addressed to the user, in your butler voice,
explaining the choices. Do not list the names again — just explain the angles
they bring and why these three together.
</reasoning>
"""


PROPOSAL_SYSTEM = """You are Alfred Pennyworth, orchestrating a council debate.

Read the transcript and draft ONE concrete proposal that captures the most
actionable version of where the debate has landed. The proposal should be a
single specific recommendation the user could act on or vote against, not a
summary of views.

Format: a single paragraph, 1-2 sentences, written in your butler voice,
beginning with "I should propose, sir, that…" or similar.
"""


VOTE_SYSTEM_TEMPLATE = """You are {name}, a member of the council. Alfred has put a
proposal to a vote after the debate. Respond with your vote in this exact format:

<vote>YES</vote>  or  <vote>NO</vote>  or  <vote>ABSTAIN</vote>
<reason>One sentence in your voice. Sharp, no hedging.</reason>

Stay in character. Vote based on whether you actually agree, not to please anyone.
"""


SUMMARY_SYSTEM = """You are Alfred Pennyworth, closing a council debate.

Given the proposal, the votes, and a brief debate transcript, deliver a final
summary in your butler voice. Cover:
- the tally
- where the council was united
- where it was divided, and on what
- one final neutral observation, only if it adds something the user might miss

Keep it short. Five or six sentences at most. Do not add your own substantive
recommendation unless the council was clearly split and the user would benefit
from a tiebreak — and even then, with a polite qualifier.
"""


def select_members(
    *,
    alfred_model: str,
    question: str,
    members: dict[str, Member],
    context: str | None = None,
) -> Selection:
    roster = compact_roster(members)
    context_block = (
        f"\n\nBackground context about the user and their work:\n\n{context}\n\n"
        if context else ""
    )
    user_msg = (
        f"The user has put the following question to the council:\n\n"
        f"---\n{question}\n---\n"
        f"{context_block}\n"
        f"Here is the available roster:\n\n{roster}\n\n"
        f"Select three members whose disagreements will be most productive for this question."
    )
    text = collect(
        stream(
            model_spec=alfred_model,
            system=SELECTION_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
            max_tokens=500,
        )
    )
    slugs = re.findall(r'<member\s+slug\s*=\s*[\'"]([^\'"]+)[\'"]', text)
    slugs = [s.strip().lower() for s in slugs]
    valid = [s for s in slugs if s in members][:3]
    if len(valid) < 3:
        # Fallback: fill with first three available
        for s in members:
            if s not in valid:
                valid.append(s)
            if len(valid) == 3:
                break
    m = re.search(r"<reasoning>(.*?)</reasoning>", text, re.DOTALL)
    reasoning = m.group(1).strip() if m else text.strip()
    return Selection(slugs=valid, reasoning=reasoning)


def draft_proposal(
    *, alfred_model: str, transcript: list[dict], context: str | None = None
) -> str:
    context_block = (
        f"Background context about the user:\n\n{context}\n\n---\n\n" if context else ""
    )
    user_msg = (
        f"{context_block}"
        "Here is the debate transcript so far. Draft a single concrete proposal "
        "for the council to vote on:\n\n"
        + _render_transcript(transcript)
    )
    return collect(
        stream(
            model_spec=alfred_model,
            system=PROPOSAL_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
            max_tokens=300,
        )
    ).strip()


def cast_vote(
    *,
    member: Member,
    proposal: str,
    transcript: list[dict],
    context: str | None = None,
) -> tuple[str, str]:
    """Return (vote, reason). vote in {YES, NO, ABSTAIN}."""
    system = VOTE_SYSTEM_TEMPLATE.format(name=member.name) + "\n\n" + member.personality
    if context:
        system += f"\n\n---\n\nBackground context about the user:\n\n{context}"
    user_msg = (
        "The debate transcript:\n\n"
        + _render_transcript(transcript)
        + "\n\nAlfred's proposal:\n\n"
        + proposal
        + "\n\nCast your vote."
    )
    text = collect(
        stream(
            model_spec=member.model_spec(),
            system=system,
            messages=[{"role": "user", "content": user_msg}],
            max_tokens=200,
        )
    )
    vm = re.search(r"<vote>\s*(YES|NO|ABSTAIN)\s*</vote>", text, re.IGNORECASE)
    rm = re.search(r"<reason>(.*?)</reason>", text, re.DOTALL)
    vote = (vm.group(1).upper() if vm else "ABSTAIN")
    reason = (rm.group(1).strip() if rm else text.strip())
    return vote, reason


def closing_summary(
    *,
    alfred_model: str,
    proposal: str,
    votes: list[tuple[str, str, str]],   # (name, vote, reason)
    transcript: list[dict],
) -> str:
    vote_block = "\n".join(f"- {n}: {v} — {r}" for n, v, r in votes)
    user_msg = (
        f"Proposal:\n{proposal}\n\nVotes:\n{vote_block}\n\n"
        f"Brief transcript context:\n{_render_transcript(transcript[-6:])}\n\n"
        f"Deliver the closing."
    )
    return collect(
        stream(
            model_spec=alfred_model,
            system=SUMMARY_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
            max_tokens=400,
        )
    ).strip()


def _render_transcript(transcript: list[dict]) -> str:
    out = []
    for msg in transcript:
        role = msg.get("role", "?")
        content = msg.get("content", "")
        out.append(f"[{role}] {content}")
    return "\n\n".join(out)
