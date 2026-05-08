# The AI Council

A virtual board of advisors. Ten distinct minds you can summon — individually or together — to pressure-test ideas, argue with each other, and tell you what you don't want to hear in a way you can actually use.

## The Members

| # | Advisor | Domain |
|---|---------|--------|
| 1 | [Gabe Newell](council/gabe-newell/personality.md) | Product, Platforms, Long-Game Building |
| 2 | [Warren Buffett](council/warren-buffett/personality.md) | Finance, Capital Allocation, M&A |
| 3 | [David Ogilvy](council/david-ogilvy/personality.md) | Media, Advertising, Persuasion |
| 4 | [Andrew Grove](council/andrew-grove/personality.md) | Management & Operations |
| 5 | [PewDiePie](council/pewdiepie/personality.md) | Creativity, Audience, Entertainment |
| 6 | [Marcus Aurelius](council/marcus-aurelius/personality.md) | Stoicism, Self-Discipline |
| 7 | [Sun Tzu](council/sun-tzu/personality.md) | Strategy & Special Situations |
| 8 | [Harvey Specter](council/harvey-specter/personality.md) | Negotiation & Leverage |
| 9 | [Michael Stevens / Vsauce](council/michael-stevens/personality.md) | Science, Curiosity, First Principles |
| 10 | [Alan Turing](council/alan-turing/personality.md) | Computation, Logic, AI |

## How to use it

Read [`council-protocol.md`](council-protocol.md) — it defines the rules of engagement (how they talk, when they push back, what "constructive brutal honesty" means here).

Three modes:

- **One-on-one.** Load a single `personality.md` as the system prompt and ask the question.
- **Panel.** Load the protocol + 2–4 personalities. Ask the question. Let them argue.
- **Full council.** Load the protocol + all 10. Use for big strategic decisions where you want maximum dissent.

Pair people who will fight. Buffett and Harvey Specter on a deal. Marcus Aurelius and PewDiePie on burnout. Turing and Sun Tzu on a strategy you think is "obvious."

## The terminal harness

A simple REPL where Alfred (the butler) picks three council members to debate your question, moderates the conversation, drafts a proposal, and tallies a vote.

### Setup

```bash
# 1. install (uv recommended; pip works too)
uv sync                # or: pip install -e .

# 2. configure keys + models
cp .env.example .env
# edit .env: set ANTHROPIC_API_KEY and/or MISTRAL_API_KEY
```

Models are addressed as `provider:model` strings in `.env`. Providers: `anthropic`, `mistral`.

```env
# Defaults — used by every member unless overridden
ALFRED_MODEL=anthropic:claude-opus-4-7
COUNCIL_DEFAULT_MODEL=anthropic:claude-opus-4-7

# Per-member override (key = COUNCIL_MODEL_<SLUG_UPPERCASED_WITH_UNDERSCORES>)
# Mix providers/tiers to balance views — heavyweight thinkers on Opus,
# lighter voices on a smaller model, etc.
COUNCIL_MODEL_MARCUS_AURELIUS=anthropic:claude-opus-4-7
COUNCIL_MODEL_WARREN_BUFFETT=anthropic:claude-sonnet-4-6
COUNCIL_MODEL_HARVEY_SPECTER=mistral:mistral-medium-3-5
COUNCIL_MODEL_PEWDIEPIE=mistral:mistral-small-latest
```

Sampling temperature is configurable per provider via `ANTHROPIC_TEMPERATURE` and `MISTRAL_TEMPERATURE`. Debate length is bounded by `MAX_DEBATE_ROUNDS` and `MAX_TOKENS_PER_TURN`.

### Run

```bash
council                # or: python -m harness
```

Then just type your question. Slash commands available:

| Command | What it does |
|---|---|
| `/help` | show all commands |
| `/members` | list every advisor and their domain |
| `/pick a,b,c` | force these three for the next question |
| `/auto` | hand selection back to Alfred (default) |
| `/rounds N` | set max debate rounds (default 3) |
| `/last` | path to the most recent transcript |
| `/clear` | clear the screen |
| `/quit` | exit |

### Flow of a session

1. **Convene.** Alfred picks three members and explains why.
2. **Opening.** Each member stakes out a position.
3. **Debate.** Up to N rounds. Members can ask each other direct questions (Alfred routes them). Between rounds you can `[c]ontinue / [a]sk a follow-up / [w]rap up / [q]uit`.
4. **Proposal.** Alfred drafts one concrete recommendation.
5. **Vote.** Each member votes YES/NO/ABSTAIN with a one-line reason.
6. **Closing.** Alfred summarises consensus, dissent, and tally.

Every session is saved as both JSON and Markdown in `transcripts/` (gitignored).

## Project layout

```
council/                 # one folder per advisor, each with personality.md
council-protocol.md      # rules of engagement (debate, dissent, voting)
harness/                 # the terminal REPL
  ├─ cli.py              # slash commands and input loop
  ├─ orchestrator.py     # convene → debate → propose → vote
  ├─ session.py          # transcript persistence
  ├─ member.py           # system prompt + response parsing
  ├─ roster.py           # loads personalities, resolves model per member
  ├─ llm.py              # unified Anthropic + Mistral streaming client
  └─ ui.py               # rich rendering
transcripts/             # saved sessions (JSON + Markdown)
```

## Adding a new advisor

1. Create `council/<slug>/personality.md`. Mirror the structure of an existing one — H1 with the name, an italic one-liner for the domain, then `## Identity`, voice, beliefs, etc.
2. Add an entry to `COLORS` and `EMOJI` in `harness/roster.py`.
3. Optionally pin a model with `COUNCIL_MODEL_<SLUG>=...` in `.env`.

That's it — Alfred will pick them up automatically.

## License

MIT.
