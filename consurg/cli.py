from pathlib import Path
from typing import Annotated

import typer
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from consurg.scope import Scope, load_scope

app = typer.Typer(name="consurg", help="Context Surgeon - temporarily restrict AI coding agents to a declared subset of files.")
console = Console()

SCOPE_FILE = ".consurg.yaml"


def _scope_path() -> Path:
    return Path.cwd() / SCOPE_FILE


def _read_yaml() -> dict | None:
    p = _scope_path()
    if not p.exists():
        return None
    with open(p) as f:
        return yaml.safe_load(f) or {}


def _write_yaml(data: dict):
    with open(_scope_path(), "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


@app.command()
def init(name: str = typer.Argument(None, help="Scope name (defaults to directory name)")):
    """Initialize a new .consurg.yaml scope file."""
    scope_name = name or Path.cwd().name
    data = {
        "version": 1,
        "scope": scope_name,
        "active": True,
        "reason": "",
        "working_set": [],
        "reference": [],
        "signatures": [],
        "visible": [],
        "dynamic_deps": [],
    }
    _write_yaml(data)
    console.print(f"[green]Scope '{scope_name}' initialized in {SCOPE_FILE}[/green]")


@app.command()
def add(
    files: list[str] = typer.Argument(..., help="File patterns to add"),
    read: bool = typer.Option(False, "--read", help="Add to reference (read-only) tier"),
    sig: bool = typer.Option(False, "--sig", help="Add to signatures tier"),
):
    """Add file patterns to a tier list."""
    data = _read_yaml()
    if data is None:
        console.print("[red]No scope defined. Run consurg init[/red]")
        raise typer.Exit(1)

    if sig:
        key = "signatures"
    elif read:
        key = "reference"
    else:
        key = "working_set"

    existing = data.get(key, [])
    for f in files:
        if f not in existing:
            existing.append(f)
    data[key] = existing

    # Drift detection
    metadata = data.get("metadata", {})
    if metadata and "original_count" in metadata:
        total = sum(len(data.get(k, [])) for k in ("working_set", "reference", "signatures", "visible"))
        original = metadata["original_count"]
        if original > 0 and total >= 2 * original:
            console.print(Panel(
                f"[yellow]Scope drift detected![/yellow]\n"
                f"Original file count: {original}\n"
                f"Current file count: {total}\n"
                f"Expansion ratio: {total / original:.1f}x",
                title="Drift Warning",
                border_style="yellow",
            ))

    _write_yaml(data)
    console.print(f"[green]Added {len(files)} pattern(s) to {key}[/green]")


@app.command()
def remove(files: list[str] = typer.Argument(..., help="File patterns to remove")):
    """Remove file patterns from all tier lists."""
    data = _read_yaml()
    if data is None:
        console.print("[red]No scope defined. Run consurg init[/red]")
        raise typer.Exit(1)

    tier_keys = ["working_set", "reference", "signatures", "visible"]
    for pattern in files:
        found = False
        for key in tier_keys:
            lst = data.get(key, [])
            if pattern in lst:
                lst.remove(pattern)
                data[key] = lst
                found = True
        if not found:
            console.print(f"[yellow]Warning: '{pattern}' not found in any tier[/yellow]")

    _write_yaml(data)
    console.print("[green]Remove complete[/green]")


@app.command()
def on():
    """Activate the current scope."""
    data = _read_yaml()
    if data is None:
        console.print("[red]No scope defined. Run consurg init[/red]")
        raise typer.Exit(1)
    data["active"] = True
    _write_yaml(data)
    console.print("[green]Scope activated[/green]")


@app.command()
def off():
    """Deactivate the current scope."""
    data = _read_yaml()
    if data is None:
        console.print("[red]No scope defined. Run consurg init[/red]")
        raise typer.Exit(1)
    data["active"] = False
    _write_yaml(data)
    console.print("[yellow]Scope deactivated[/yellow]")


@app.command()
def status():
    """Show current scope status."""
    data = _read_yaml()
    if data is None:
        console.print("No scope defined. Run consurg init")
        return

    scope_name = data.get("scope", "unnamed")
    active = data.get("active", False)
    active_str = "[green]ACTIVE[/green]" if active else "[red]INACTIVE[/red]"

    table = Table(title=f"Scope: {scope_name} ({active_str})")
    table.add_column("Tier", style="bold")
    table.add_column("Count", justify="right")
    table.add_column("Patterns")

    tiers = [
        ("4 READ-WRITE", "working_set"),
        ("3 READ-ONLY", "reference"),
        ("2 SIGNATURE", "signatures"),
        ("1 EXISTENCE", "visible"),
    ]
    for label, key in tiers:
        patterns = data.get(key, [])
        table.add_row(label, str(len(patterns)), ", ".join(patterns) if patterns else "-")

    console.print(table)


@app.command(name="map")
def map_cmd():
    """Visualize file tiers as a tree."""
    from rich.text import Text
    from rich.tree import Tree

    from consurg.enforce import resolve_tier

    scope = load_scope(_scope_path())
    if scope is None:
        console.print("No scope defined. Run consurg init")
        return

    tree = Tree(f"[bold]{scope.scope_name}[/bold]")
    cwd = Path.cwd()

    tier_styles = {
        4: ("[RW]", "green", "block"),
        3: ("[RO]", "yellow", "block"),
        2: ("[SIG]", "blue", "block"),
        1: ("[--]", "dim", "dash"),
        0: ("[--]", "dim", "dash"),
    }

    files = sorted(p.relative_to(cwd) for p in cwd.rglob("*") if p.is_file()
                   and ".git" not in p.parts and "__pycache__" not in p.parts
                   and ".pytest_cache" not in p.parts)

    for fp in files:
        tier_num, _ = resolve_tier(str(fp), scope)
        label, style, block_type = tier_styles.get(tier_num, ("[--]", "dim", "dash"))
        bar = "\u2588" * min(tier_num, 4) if block_type == "block" else "-" * 2
        text = Text()
        text.append(f"{label} ", style=style)
        text.append(bar + " ", style=style)
        text.append(str(fp))
        tree.add(text)

    console.print(tree)


@app.command()
def pin():
    """Pin the current scope to .consurg.yaml."""
    p = _scope_path()
    if p.exists():
        console.print("[red]Scope file already exists. Use 'consurg off' first or pass --force.[/red]")
        raise typer.Exit(1)
    # If we had in-memory state we'd write it here; for now init covers creation
    console.print("[yellow]No in-memory scope to pin. Use 'consurg init' to create a scope.[/yellow]")


@app.command()
def unpin():
    """Remove .consurg.yaml from the project root."""
    p = _scope_path()
    if not p.exists():
        console.print("[yellow]No scope file to remove.[/yellow]")
        return
    p.unlink()
    console.print("[green]Scope file removed[/green]")


if __name__ == "__main__":
    app()
