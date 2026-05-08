"""Rich-based rendering: banners, panels, streaming output, spinners."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text

console = Console()

# Reading-width cap. Long lines kill readability.
PANEL_WIDTH = 96


def _panel_width() -> int:
    return min(console.width - 2, PANEL_WIDTH)


def banner(member_count: int, context_loaded: bool = False) -> None:
    title = Text("The AI Council", style="bold gold1")
    ctx_str = "context loaded" if context_loaded else "no context.md"
    sub = Text(
        f"  {member_count} advisors · alfred presiding · {ctx_str} · /help  ",
        style="dim",
    )
    console.print()
    console.print(Panel.fit(Text.assemble(title, "\n", sub), border_style="gold1"))
    console.print()


def rule(label: str, style: str = "dim") -> None:
    console.print(Rule(label, style=style, characters="─"))


def user_echo(text: str) -> None:
    console.print(f"[bold white]❯[/bold white] {text}")
    console.print()


def info(text: str) -> None:
    console.print(f"[dim]{text}[/dim]")


def warn(text: str) -> None:
    console.print(f"[yellow]! {text}[/yellow]")


def error(text: str) -> None:
    console.print(f"[bold red]✗ {text}[/bold red]")


@contextmanager
def thinking(label: str):
    with console.status(f"[dim]{label}[/dim]", spinner="dots"):
        yield


def _render_body(text: str, streaming: bool):
    """Body renderer. Markdown for finished output; plain text while streaming
    (incomplete markdown can render strangely mid-stream)."""
    if streaming:
        return Text(text)
    return Markdown(text or "")


def stream_panel(
    *,
    title: str,
    color: str,
    chunks: Iterator[str],
) -> str:
    """Stream chunks into a live-updating bordered panel.

    During the stream we render plain Text (incremental, fast). When the stream
    ends we re-render once with Markdown so paragraph breaks, bold, and lists
    look right. Returns the full text.
    """
    buffer: list[str] = []
    width = _panel_width()

    def render(streaming: bool) -> Panel:
        return Panel(
            _render_body("".join(buffer), streaming=streaming),
            title=Text(f" {title} ", style=f"bold {color}"),
            title_align="left",
            border_style=color,
            padding=(1, 2),
            width=width,
        )

    with Live(
        render(streaming=True),
        console=console,
        refresh_per_second=15,
        transient=False,
    ) as live:
        for chunk in chunks:
            buffer.append(chunk)
            live.update(render(streaming=True))
        # Final repaint with markdown formatting:
        live.update(render(streaming=False))
    console.print()
    return "".join(buffer)


def static_panel(*, title: str, body: str, color: str) -> None:
    console.print(
        Panel(
            Markdown(body or ""),
            title=Text(f" {title} ", style=f"bold {color}"),
            title_align="left",
            border_style=color,
            padding=(1, 2),
            width=_panel_width(),
        )
    )
    console.print()


def slash_help() -> None:
    body = (
        "[bold]/help[/bold]            show this help\n"
        "[bold]/members[/bold]         list all council members\n"
        "[bold]/pick a,b,c[/bold]      force these three for the next question\n"
        "[bold]/auto[/bold]            let Alfred pick (default)\n"
        "[bold]/rounds N[/bold]        set max debate rounds\n"
        "[bold]/context[/bold]         show whether context.md is loaded\n"
        "[bold]/last[/bold]            path to the last saved transcript\n"
        "[bold]/clear[/bold]           clear the screen\n"
        "[bold]/quit[/bold]            exit\n"
        "\n"
        "Anything else is treated as a question for the council."
    )
    static_panel(title="Commands", body=body, color="gold1")
