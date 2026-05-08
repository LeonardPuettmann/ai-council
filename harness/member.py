"""CouncilMember — wraps a personality + LLM call."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterator

from harness.llm import stream
from harness.roster import Member


@dataclass
class MemberResponse:
    speaker_slug: str
    text: str
    body: str                      # text with <question> tags stripped
    questions: list[tuple[str, str]]   # (target_slug_or_name, question)


QUESTION_RE = re.compile(
    r"<question\s+to\s*=\s*['\"]([^'\"]+)['\"]\s*>(.*?)</question>",
    re.DOTALL | re.IGNORECASE,
)


def parse_response(slug: str, text: str) -> MemberResponse:
    questions = [
        (m.group(1).strip().lower(), m.group(2).strip())
        for m in QUESTION_RE.finditer(text)
    ]
    body = QUESTION_RE.sub("", text).strip()
    return MemberResponse(speaker_slug=slug, text=text, body=body, questions=questions)


def build_system(member: Member, protocol: str, context: str | None = None) -> str:
    context_block = ""
    if context:
        context_block = (
            f"---\n\n"
            f"## Background context (about the user and their work)\n\n"
            f"{context}\n\n"
            f"Use this as background. Refer to it naturally when relevant. "
            f"Push back on it where the framing is the problem. Do not parrot it.\n\n"
        )

    last_name = member.name.split()[-1]

    return (
        f"# CRITICAL IDENTITY RULES — read first, follow always\n\n"
        f"You ARE **{member.name}**. You are not playing {member.name}; you are him.\n\n"
        f"- **Never address yourself by name.** Never write \"{last_name}, you're right about…\" "
        f"or \"{member.name}, your point is…\" — that would be talking to yourself.\n"
        f"- **Never start your response with your own name in brackets.** Do NOT write "
        f"`[{member.name}]` or `**{member.name}:**` or any similar header. Just write the response.\n"
        f"- **The transcript convention `[{member.name}]` marks YOUR OWN previous turns.** "
        f"When you see it, that was you. Do not respond to it as if it were someone else.\n"
        f"- Speak in the first person about yourself (\"I think…\", \"my view is…\"). "
        f"Address other members in the second person, by name.\n\n"
        f"---\n\n"
        f"{protocol}\n\n"
        f"---\n\n"
        f"## Your character\n\n"
        f"{member.personality}\n\n"
        f"{context_block}"
        f"---\n\n"
        f"## Formatting & engagement rules — every turn\n\n"
        f"**Voice & character**\n"
        f"- Stay strictly in character. Never mention you are an AI or a model.\n"
        f"- Speak in your own vocabulary, sentence rhythm, and rhetorical moves.\n\n"
        f"**Length & shape**\n"
        f"- Keep it tight. Two or three short paragraphs is plenty. One can be enough.\n"
        f"- Use short paragraphs (2–4 sentences) separated by blank lines.\n"
        f"- Use **bold AT MOST ONCE** in your entire response — for the single most important "
        f"phrase. Overusing bold makes it meaningless.\n"
        f"- Vary your sentence openings. If you've already opened a turn with "
        f"\"X, you're right about A but wrong about B\" earlier in this debate, find a "
        f"different shape this time. Repetition makes you sound like a template.\n"
        f"- Lists are fine when they genuinely fit your voice (Ogilvy and Grove especially). "
        f"Otherwise prose.\n"
        f"- Do not produce executive summaries unless asked. The disagreement is the output.\n\n"
        f"**Engaging the council**\n"
        f"- Address OTHER members by name when responding to them. Never yourself.\n"
        f"- If you genuinely agree with a previous speaker, say so plainly and add only what "
        f"extends or qualifies their point. Do not restate your own opening.\n"
        f"- If you have nothing new to add this round, say that in one sentence and yield. "
        f"Silence is acceptable; repetition is not.\n\n"
        f"**Asking questions**\n"
        f"- If you want a specific question answered by another member, end your turn with:\n"
        f'  <question to="slug-or-name">your question</question>\n'
        f"- At most ONE question per turn. Skip if no genuine question.\n"
        f"- If you have been asked direct questions, answer EVERY ONE of them by name. "
        f"Do not duck a question."
    )


def speak(
    *,
    member: Member,
    protocol: str,
    transcript: list[dict],
    max_tokens: int,
    context: str | None = None,
) -> Iterator[str]:
    """Stream a response from this member given the running transcript."""
    system = build_system(member, protocol, context)
    yield from stream(
        model_spec=member.model_spec(),
        system=system,
        messages=transcript,
        max_tokens=max_tokens,
    )
