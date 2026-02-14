"""Rich-based TUI for the interactive guard.

Three panels:
  - Header: scope name, status, tier counts, port, uptime
  - Access log: scrolling table of recent events
  - Approval prompt: shown when a T0 access needs user decision

Keyboard input is platform-aware (msvcrt on Windows, tty on Unix).
"""

from __future__ import annotations

import os
import sys
import threading
import time
from typing import TYPE_CHECKING

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

if TYPE_CHECKING:
    from consurg.guard.state import GuardState


def _format_uptime(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h{m:02d}m"
    return f"{m}m{s:02d}s"


def _format_time(ts: float) -> str:
    return time.strftime("%H:%M:%S", time.localtime(ts))


def _build_header(state: GuardState) -> Panel:
    counts = state.tier_counts()
    scope_name = state.scope.scope_name or "unnamed"
    status = "[green]ACTIVE[/green]" if state.running else "[red]STOPPED[/red]"
    mode = "[cyan]INTERACTIVE[/cyan]" if state.interactive else "[dim]HEADLESS[/dim]"

    header_text = (
        f"  Scope: [bold]{scope_name}[/bold]  {status}  {mode}\n"
        f"  Port: {state.port}  "
        f"T4:{counts.get(4, 0)} T3:{counts.get(3, 0)} "
        f"T2:{counts.get(2, 0)} T1:{counts.get(1, 0)}  "
        f"Uptime: {_format_uptime(state.uptime())}"
    )
    return Panel(header_text, title="GUARD", border_style="blue")


def _build_log_table(state: GuardState) -> Panel:
    table = Table(expand=True, show_header=True, header_style="bold")
    table.add_column("Time", width=10, no_wrap=True)
    table.add_column("Tool", width=6, no_wrap=True)
    table.add_column("File", ratio=3)
    table.add_column("Tier", width=4, justify="center")
    table.add_column("", width=2, justify="center")

    events = list(state.access_log)[-20:]  # Show last 20
    for event in events:
        ts = _format_time(event.timestamp)
        tier_str = f"T{event.tier}"

        if event.decision == "allow":
            icon = "[green]\u2713[/green]"
            style = ""
        else:
            icon = "[red]\u2717[/red]"
            style = "dim"

        if event.promoted:
            icon = "[yellow]\u2191[/yellow]"

        table.add_row(ts, event.tool_name, event.file_path, tier_str, icon, style=style)

    return Panel(table, title="ACCESS LOG", border_style="green")


def _build_approval(state: GuardState) -> Panel | None:
    pending = state.get_pending()
    if pending is None:
        return None

    text = Text()
    text.append(f"  {pending.tool_name} ", style="bold")
    text.append(pending.file_path, style="yellow")
    text.append(f"  (T{pending.tier} {pending.label})\n\n", style="dim")
    text.append("  [W]", style="bold green")
    text.append("orking set  ")
    text.append("[R]", style="bold yellow")
    text.append("ead-only  ")
    text.append("[S]", style="bold blue")
    text.append("ignature  ")
    text.append("[D]", style="bold red")
    text.append("eny")

    return Panel(text, title="\u26a1 APPROVAL REQUIRED", border_style="yellow")


def _build_footer(state: GuardState) -> Panel:
    text = Text()
    text.append("  Press ", style="dim")
    text.append("Q", style="bold white")
    text.append(" to quit", style="dim")
    return Panel(text, border_style="none", padding=(0, 0))


def _build_layout(state: GuardState) -> Layout:
    layout = Layout()
    approval = _build_approval(state)

    splits = [
        Layout(_build_header(state), name="header", size=5),
        Layout(_build_log_table(state), name="log"),
    ]

    if approval:
        splits.append(Layout(approval, name="approval", size=6))

    splits.append(Layout(_build_footer(state), name="footer", size=1))

    layout.split_column(*splits)

    return layout


def _keyboard_listener(state: GuardState) -> None:
    """Listen for keyboard input in a separate thread."""
    if os.name == "nt":
        import msvcrt
        while state.running:
            if msvcrt.kbhit():
                ch = msvcrt.getwch().lower()
                _handle_key(state, ch)
            else:
                time.sleep(0.05)
    else:
        import select
        import termios
        import tty
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            while state.running:
                if select.select([sys.stdin], [], [], 0.05)[0]:
                    ch = sys.stdin.read(1).lower()
                    _handle_key(state, ch)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def _handle_key(state: GuardState, ch: str) -> None:
    if ch == "q":
        state.running = False
        return

    # Handle approval responses
    pending = state.get_pending()
    if pending and ch in ("w", "r", "s", "d"):
        pending.response = ch
        if ch != "d":
            tier_map = {"w": 4, "r": 3, "s": 2}
            pending.promoted_tier = tier_map[ch]
        pending.event.set()


def run_tui(state: GuardState) -> None:
    """Run the interactive TUI with Rich Live display."""
    console = Console()

    kb_thread = threading.Thread(target=_keyboard_listener, args=(state,), daemon=True)
    kb_thread.start()

    try:
        with Live(
            _build_layout(state),
            console=console,
            refresh_per_second=4,
            screen=True,
        ) as live:
            while state.running:
                live.update(_build_layout(state))
                time.sleep(0.25)
    except KeyboardInterrupt:
        state.running = False
    finally:
        console.clear()
        console.print("[yellow]Guard stopped.[/yellow]")
