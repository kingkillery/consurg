import os
import subprocess
import sys
import time
import uuid
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from consurg.adapters import (
    generate_aider_args,
    generate_claude_scope,
    generate_cursor_rules,
    generate_generic_prompt,
)
from consurg.audit import audit_storage_stats, load_audit_config, persist_trace, should_audit_tool
from consurg.pk_agents import scaffold_pk_agents
from consurg.scope import Scope, load_scope
from consurg.trace import DependencyGraph, resolve_python_imports, resolve_ts_imports

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
    added_patterns = []
    skipped_patterns = []

    for f in files:
        pattern = f.replace("\\", "/")
        if pattern not in existing:
            existing.append(pattern)
            added_patterns.append(pattern)
        else:
            skipped_patterns.append(pattern)

    data[key] = existing

    # UX: Warn about non-glob files that don't exist
    for pat in added_patterns:
        # Simple heuristic: if it contains *, ?, or [, treat as glob
        is_glob = any(c in pat for c in "*?[")
        if not is_glob and not Path(pat).exists():
            console.print(f"[yellow]Warning: File '{pat}' not found locally.[/yellow]")

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

    if added_patterns:
        console.print(f"[green]Added {len(added_patterns)} pattern(s) to {key}[/green]")
    if skipped_patterns:
        console.print(f"[yellow]Skipped {len(skipped_patterns)} duplicate(s)[/yellow]")
    if not added_patterns and not skipped_patterns:
        # Should technically not happen due to required arg, but safe fallback
        console.print("[yellow]No patterns provided.[/yellow]")


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
    console.print("[dim]Hint: Run consurg clean to also unwire tools and remove .consurg.yaml[/dim]")


@app.command()
def clean(
    keep_scope: bool = typer.Option(False, "--keep-scope", help="Skip removing .consurg.yaml"),
):
    """Deactivate scope, unwire all tools, and optionally remove .consurg.yaml."""
    from consurg.wire import WIRERS

    actions = []

    # 1. Off
    data = _read_yaml()
    if data:
        if data.get("active"):
            data["active"] = False
            _write_yaml(data)
            actions.append("Scope deactivated")

    # 2. Unwire all
    for tool_id, wirer_cls in WIRERS.items():
        wirer = wirer_cls()
        if wirer.status() != "not wired":
            result = wirer.unwire()
            if result.success:
                actions.append(f"Unwired {wirer.name}")
            else:
                actions.append(f"[red]Failed to unwire {wirer.name}: {result.message}[/red]")

    # 3. Unpin
    if not keep_scope:
        p = _scope_path()
        if p.exists():
            p.unlink()
            actions.append("Scope file (.consurg.yaml) removed")

    if actions:
        console.print("[green]Clean complete:[/green]")
        for action in actions:
            console.print(f" - {action}")
    else:
        console.print("[yellow]Nothing to clean.[/yellow]")


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
        patterns_display = [p.replace("\\", "/") for p in patterns]
        table.add_row(label, str(len(patterns)), ", ".join(patterns_display) if patterns_display else "-")

    console.print(table)


@app.command(name="map")
def map_cmd(
    depth: Annotated[int | None, typer.Option("--depth", "-d", help="Maximum directory depth to traverse.")] = None,
    scoped_only: Annotated[bool, typer.Option("--scoped-only", help="Only show files with tier >= 1.")] = False,
):
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

    # Use git ls-files for .gitignore-aware file discovery; fallback to rglob
    try:
        result = subprocess.run(
            ["git", "ls-files"],
            capture_output=True, text=True, cwd=str(cwd),
        )
        if result.returncode == 0:
            files = sorted(
                Path(f) for f in result.stdout.strip().splitlines() if f.strip()
            )
        else:
            raise FileNotFoundError
    except FileNotFoundError:
        files = sorted(
            p.relative_to(cwd) for p in cwd.rglob("*") if p.is_file()
            and ".git" not in p.parts and "__pycache__" not in p.parts
            and ".pytest_cache" not in p.parts and "node_modules" not in p.parts
            and ".next" not in p.parts and "dist" not in p.parts
            and "venv" not in p.parts and ".venv" not in p.parts
        )

    # Filter by depth if specified
    if depth is not None:
        files = [f for f in files if len(f.parts) <= depth]

    # Warn on large file counts
    if len(files) > 5000:
        console.print(f"[yellow]Warning: {len(files)} files found. Consider using --scoped-only to limit output.[/yellow]")

    for fp in files:
        fp_str = str(fp).replace("\\", "/")
        tier_num, _ = resolve_tier(fp_str, scope)
        if scoped_only and tier_num == 0:
            continue
        label, style, block_type = tier_styles.get(tier_num, ("[--]", "dim", "dash"))
        bar = "\u2588" * min(tier_num, 4) if block_type == "block" else "-" * 2
        text = Text()
        text.append(f"{label} ", style=style)
        text.append(bar + " ", style=style)
        text.append(fp_str)
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


FORMAT_CHOICES = ["claude", "cursor", "aider", "generic"]


@app.command()
def export(
    fmt: str = typer.Option(..., "--format", help="Output format: claude, cursor, aider, generic"),
):
    """Export scope in a tool-specific format."""
    if fmt not in FORMAT_CHOICES:
        console.print(f"[red]Unknown format '{fmt}'. Choose from: {', '.join(FORMAT_CHOICES)}[/red]")
        raise typer.Exit(1)

    scope = load_scope(_scope_path())
    if scope is None:
        console.print("[red]No scope defined. Run consurg init[/red]")
        raise typer.Exit(1)

    generators = {
        "claude": generate_claude_scope,
        "cursor": generate_cursor_rules,
        "aider": generate_aider_args,
        "generic": generate_generic_prompt,
    }

    result = generators[fmt](scope)
    if isinstance(result, list):
        console.print(" ".join(result))
    else:
        console.print(result, highlight=False)


@app.command(name="apply-proposal")
def apply_proposal(
    proposal_file: str = typer.Option(
        ".consurg/recommendations/scope-proposal.yaml",
        "--proposal-file",
        help="Path to scope proposal YAML file",
    ),
    apply: bool = typer.Option(False, "--apply", help="Write mapped values to .consurg.yaml"),
):
    """Map scope proposal output into Consurg scope tiers."""
    proposal_path = Path(proposal_file)
    if not proposal_path.exists():
        console.print(f"[red]Proposal file not found: {proposal_path}[/red]")
        raise typer.Exit(1)

    with open(proposal_path, encoding="utf-8") as f:
        proposal = yaml.safe_load(f) or {}

    required_keys = ("include_context", "read_only", "exclude")
    missing = [k for k in required_keys if k not in proposal]
    if missing:
        console.print(f"[red]Invalid proposal: missing keys: {', '.join(missing)}[/red]")
        raise typer.Exit(1)

    for key in required_keys:
        if not isinstance(proposal.get(key), list) or not all(isinstance(x, str) for x in proposal[key]):
            console.print(f"[red]Invalid proposal: '{key}' must be a list of strings[/red]")
            raise typer.Exit(1)

    include_context = proposal.get("include_context", [])
    read_only = proposal.get("read_only", [])
    exclude = proposal.get("exclude", [])

    table = Table(title="Scope Proposal Mapping")
    table.add_column("Proposal Key", style="bold")
    table.add_column("Consurg Tier")
    table.add_column("Count", justify="right")
    table.add_row("include_context", "working_set (T4)", str(len(include_context)))
    table.add_row("read_only", "reference (T3)", str(len(read_only)))
    table.add_row("exclude", "implicit blocked (T0)", str(len(exclude)))
    console.print(table)

    if not apply:
        console.print("[yellow]Preview only. Re-run with --apply to write .consurg.yaml[/yellow]")
        return

    data = _read_yaml() or {
        "version": 1,
        "scope": Path.cwd().name,
        "active": True,
        "reason": "",
    }
    data["working_set"] = include_context
    data["reference"] = read_only
    data.setdefault("signatures", [])
    data.setdefault("visible", [])
    data["reason"] = str(proposal.get("task", data.get("reason", "")))
    _write_yaml(data)
    console.print(f"[green]Scope written to {SCOPE_FILE} from proposal[/green]")


@app.command(name="audit-status")
def audit_status():
    """Show effective audit persistence configuration and storage usage."""
    config = load_audit_config(Path.cwd())
    stats = audit_storage_stats(config.storage_path)

    table = Table(title="Audit Status")
    table.add_column("Setting", style="bold")
    table.add_column("Value")
    table.add_row("enabled", "true" if config.enabled else "false")
    table.add_row("storage_path", str(config.storage_path))
    table.add_row("max_runs", str(config.max_runs))
    table.add_row("max_age_days", str(config.max_age_days))
    table.add_row("max_bytes", str(config.max_bytes))
    table.add_row("redaction_profile", config.redaction_profile)
    table.add_row("run_dirs", str(stats["runs"]))
    table.add_row("storage_bytes", str(stats["bytes"]))
    console.print(table)


_PY_EXTENSIONS = {".py"}
_TS_EXTENSIONS = {".ts", ".tsx", ".js", ".jsx", ".mts", ".mjs"}


def _build_graph(entry_files: list[str], depth: int) -> DependencyGraph:
    graph = DependencyGraph()
    root = str(Path.cwd())
    visited: set[str] = set()
    queue: deque[tuple[str, int]] = deque()

    for ef in entry_files:
        normalized = str(Path(ef)).replace("\\", "/")
        queue.append((normalized, 0))

    while queue:
        current, d = queue.popleft()
        if current in visited or d > depth:
            continue
        visited.add(current)

        current_path = Path.cwd() / current
        if not current_path.exists():
            continue

        ext = current_path.suffix.lower()
        if ext in _PY_EXTENSIONS:
            deps = resolve_python_imports(str(current_path), root)
        elif ext in _TS_EXTENSIONS:
            deps = resolve_ts_imports(str(current_path), root)
        else:
            continue

        for dep_path, kind in deps:
            graph.add_edge(current, dep_path, kind)
            if d + 1 <= depth:
                queue.append((dep_path, d + 1))

    return graph


@app.command()
def trace(
    entry_files: list[str] = typer.Argument(..., help="Entry point files to trace from"),
    apply: bool = typer.Option(False, "--apply", help="Write scope to .consurg.yaml"),
    depth: int = typer.Option(3, "--depth", help="Max trace depth"),
):
    """Trace dependencies from entry files and classify into tiers."""
    # Validate entry files exist
    missing = [f for f in entry_files if not Path(f).exists()]
    if missing:
        console.print(f"[red]Files not found: {', '.join(missing)}[/red]")
        raise typer.Exit(1)

    graph = _build_graph(entry_files, depth)
    normalized_entries = [str(Path(f)).replace("\\", "/") for f in entry_files]
    tiers = graph.classify_tiers(normalized_entries)

    # Ensure entry files are always tier 4, even if they have no deps
    for ef in normalized_entries:
        if ef not in tiers:
            tiers[ef] = 4

    # Build tier buckets
    tier_buckets: dict[int, list[str]] = {4: [], 3: [], 2: [], 1: []}
    for file, tier in sorted(tiers.items(), key=lambda x: (-x[1], x[0])):
        if tier in tier_buckets:
            tier_buckets[tier].append(file)

    table = Table(title="Dependency Trace")
    table.add_column("Tier", style="bold")
    table.add_column("Files")

    tier_labels = {4: "T4 working_set", 3: "T3 reference", 2: "T2 signatures", 1: "T1 visible"}
    for t in (4, 3, 2, 1):
        files = tier_buckets[t]
        if files:
            table.add_row(tier_labels[t], ", ".join(files))

    console.print(table)

    if apply:
        data = _read_yaml() or {
            "version": 1,
            "scope": Path.cwd().name,
            "active": True,
            "reason": "auto-generated by trace",
        }
        data["working_set"] = tier_buckets[4]
        data["reference"] = tier_buckets[3]
        data["signatures"] = tier_buckets[2]
        data["visible"] = tier_buckets[1]
        _write_yaml(data)
        console.print(f"[green]Scope written to {SCOPE_FILE}[/green]")


@app.command(name="git-diff")
def git_diff_cmd(
    base: str = typer.Argument(None, help="Base branch (auto-detects main/master)"),
    apply: bool = typer.Option(False, "--apply", help="Write scope to .consurg.yaml"),
):
    """Build scope from git diff against a base branch."""
    if base is None:
        base = _detect_base_branch()
        if base is None:
            console.print("[red]Error: Could not detect base branch. Specify one explicitly.[/red]")
            raise typer.Exit(1)

    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", f"{base}...HEAD"],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        console.print("[red]Error: git is not installed or not in PATH[/red]")
        raise typer.Exit(1)

    if result.returncode != 0:
        stderr = result.stderr.strip()
        console.print(f"[red]Error: {stderr}[/red]")
        raise typer.Exit(1)

    changed_files = [f for f in result.stdout.strip().splitlines() if f.strip()]

    if not changed_files:
        console.print("[yellow]No changed files found[/yellow]")
        return

    # Build graph from changed files to find their deps
    graph = _build_graph(changed_files, depth=1)
    tiers = graph.classify_tiers(changed_files)

    # Ensure all changed files are at least tier 4
    for cf in changed_files:
        normalized = cf.replace("\\", "/")
        if normalized not in tiers:
            tiers[normalized] = 4

    working_set = sorted(f for f, t in tiers.items() if t == 4)
    reference = sorted(f for f, t in tiers.items() if t == 3)

    table = Table(title=f"Git Diff Scope (base: {base})")
    table.add_column("Tier", style="bold")
    table.add_column("Files")

    if working_set:
        table.add_row("T4 working_set", ", ".join(working_set))
    if reference:
        table.add_row("T3 reference", ", ".join(reference))

    console.print(table)

    if apply:
        data = _read_yaml() or {
            "version": 1,
            "scope": Path.cwd().name,
            "active": True,
            "reason": f"auto-generated from git diff {base}",
        }
        data["working_set"] = working_set
        data["reference"] = reference
        _write_yaml(data)
        console.print(f"[green]Scope written to {SCOPE_FILE}[/green]")


def _detect_base_branch() -> str | None:
    for branch in ("main", "master"):
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--verify", branch],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                return branch
        except FileNotFoundError:
            return None
    return None


# ---------------------------------------------------------------------------
# guard command
# ---------------------------------------------------------------------------

@app.command()
def guard(
    interactive: bool = typer.Option(True, "-i/--no-i", help="Enable interactive TUI mode"),
    port: int = typer.Option(9876, "--port", help="HTTP server port"),
    no_tui: bool = typer.Option(False, "--no-tui", help="Run headless (no TUI)"),
):
    """Start the interactive scope firewall guard."""
    from consurg.guard.lockfile import GuardLockfile
    from consurg.guard.server import GuardServer
    from consurg.guard.state import GuardState

    scope = load_scope(_scope_path())
    if scope is None:
        console.print("[red]No scope defined. Run consurg init[/red]")
        raise typer.Exit(1)

    if not scope.active:
        console.print("[yellow]Scope is inactive. Activating for guard session.[/yellow]")
        scope.active = True

    state = GuardState(scope=scope, interactive=interactive and not no_tui, port=port)

    # Write lockfile for hook discovery
    lockfile = GuardLockfile()
    lockfile.write(port=port, scope_name=scope.scope_name)

    # Start HTTP server
    server = GuardServer(state)
    try:
        server.start()
        console.print(f"[green]Guard started on port {port}[/green]")

        if no_tui:
            # Headless mode — just wait
            console.print("[dim]Running headless. Press Ctrl+C to stop.[/dim]")
            import time
            while state.running:
                time.sleep(0.5)
        else:
            # Interactive TUI mode
            from consurg.guard.tui import run_tui
            run_tui(state)
    except KeyboardInterrupt:
        state.running = False
    finally:
        server.stop()
        lockfile.remove()
        console.print("[yellow]Guard stopped.[/yellow]")


# ---------------------------------------------------------------------------
# wire command
# ---------------------------------------------------------------------------

WIRE_TOOLS = ["claude", "pk-agent", "droid", "gemini", "codex"]


@app.command()
def wire(
    tool: str = typer.Argument(..., help=f"Tool to wire: {', '.join(WIRE_TOOLS)}"),
    unwire_flag: bool = typer.Option(False, "--unwire", help="Remove hooks instead of installing"),
):
    """Auto-configure hooks for a supported AI tool."""
    from consurg.wire import WIRERS

    if tool not in WIRERS:
        console.print(f"[red]Unknown tool '{tool}'. Supported: {', '.join(WIRERS.keys())}[/red]")
        raise typer.Exit(1)

    wirer = WIRERS[tool]()

    if unwire_flag:
        result = wirer.unwire()
    else:
        result = wirer.wire()

    if result.success:
        console.print(f"[green]{result.message}[/green]")
        if result.config_path:
            console.print(f"[dim]Config: {result.config_path}[/dim]")
    else:
        console.print(f"[red]{result.message}[/red]")
        raise typer.Exit(1)

    # Show current status
    current = wirer.status()
    console.print(f"[dim]Status: {current}[/dim]")


# ---------------------------------------------------------------------------
# wrap command
# ---------------------------------------------------------------------------

@app.command(
    context_settings={"allow_extra_args": True, "allow_interspersed_args": False},
)
def wrap(ctx: typer.Context):
    """Wrap a command with scope enforcement (embedded headless guard).

    Usage: consurg wrap -- <command> [args...]
    """
    if not ctx.args:
        console.print("[red]No command provided. Usage: consurg wrap -- <command>[/red]")
        raise typer.Exit(1)

    from consurg.guard.lockfile import GuardLockfile
    from consurg.guard.server import GuardServer
    from consurg.guard.state import GuardState

    scope = load_scope(_scope_path())
    if scope is None:
        console.print("[red]No scope defined. Run consurg init[/red]")
        raise typer.Exit(1)

    # Find a free port
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    state = GuardState(scope=scope, interactive=False, port=port)
    lockfile = GuardLockfile()
    lockfile.write(port=port, scope_name=scope.scope_name)

    server = GuardServer(state)
    server.start()

    # Set env vars for child process
    env = os.environ.copy()
    env["CONSURG_GUARD_PORT"] = str(port)
    env["CONSURG_ACTIVE"] = "1"
    started_at = datetime.now(UTC)
    start_ms = int(started_at.timestamp() * 1000)
    t0 = time.perf_counter()
    tool_name = Path(ctx.args[0]).name
    audit_config = load_audit_config(Path.cwd(), env=env)
    should_persist = should_audit_tool(tool_name, audit_config)

    try:
        run_kwargs: dict = {"env": env}
        if should_persist:
            run_kwargs.update({"capture_output": True, "text": True, "errors": "replace"})
        result = subprocess.run(ctx.args, **run_kwargs)
        if should_persist:
            if result.stdout:
                sys.stdout.write(result.stdout)
            if result.stderr:
                sys.stderr.write(result.stderr)
            duration_ms = int((time.perf_counter() - t0) * 1000)
            trace_call = {
                "name": tool_name,
                "type": "tool",
                "start_time": start_ms,
                "duration_ms": duration_ms,
                "success": result.returncode == 0,
                "input": {"argv": ctx.args},
                "output": {
                    "returncode": result.returncode,
                    "stdout": result.stdout or "",
                    "stderr": result.stderr or "",
                },
            }
            try:
                persist_trace(
                    config=audit_config,
                    run_id=str(uuid.uuid4()),
                    started_at=started_at,
                    tool_calls=[trace_call],
                )
            except Exception:
                console.print("[yellow]Warning: failed to persist audit trace[/yellow]")
        raise typer.Exit(result.returncode)
    except FileNotFoundError:
        console.print(f"[red]Command not found: {ctx.args[0]}[/red]")
        raise typer.Exit(1)
    finally:
        server.stop()
        lockfile.remove()


@app.command(name="scaffold-pk-agents")
def scaffold_pk_agents_cmd(
    force: bool = typer.Option(False, "--force", help="Overwrite existing scaffold files"),
):
    """Scaffold pk-agent files for scope selection and excluded-context summarization."""
    written = scaffold_pk_agents(Path.cwd(), force=force)
    if written:
        console.print("[green]Scaffolded pk-agent files:[/green]")
        for p in written:
            console.print(f"[dim]- {p.relative_to(Path.cwd())}[/dim]")
    else:
        console.print("[yellow]Scaffold already exists. Use --force to overwrite.[/yellow]")


if __name__ == "__main__":
    app()
