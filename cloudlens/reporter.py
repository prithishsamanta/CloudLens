from rich.console import Console
from rich.panel import Panel

console = Console()

_SEVERITY_STYLE = {
    "critical": ("🔴", "bold red"),
    "warning": ("🟡", "bold yellow"),
    "info": ("🔵", "bold blue"),
}


def render_terminal(diagnosis: dict, metadata: dict) -> None:
    """
    Renders the diagnosis as Rich panels/tables in the terminal.
    """
    health = (diagnosis.get("overall_health") or "unknown").upper()
    header = (
        f"[bold]CloudLens Diagnostic Report[/bold]\n"
        f"Log Group: {metadata.get('log_group')}\n"
        f"Service: {metadata.get('service', 'generic')}\n"
        f"Time Window: {metadata.get('time_window', '1h')}\n"
        f"Overall Health: {health}"
    )
    console.print(Panel(header, expand=False))
    console.print()

    if diagnosis.get("summary"):
        console.print(f"[bold]SUMMARY[/bold]\n  {diagnosis['summary']}\n")

    errors = diagnosis.get("errors", [])
    if not errors:
        console.print("[green]✓ No issues found[/green]")
        return

    for error in errors:
        severity = (error.get("severity") or "info").lower()
        icon, style = _SEVERITY_STYLE.get(severity, _SEVERITY_STYLE["info"])

        console.print(f"{icon} [{style}]{error.get('error_type', 'ISSUE')}[/{style}]")
        console.print(f"  [bold]What happened:[/bold] {error.get('what_happened', '')}")
        console.print(f"  [bold]Root cause:[/bold] {error.get('why_it_happened', '')}")

        fix = error.get("fix", {})
        if fix.get("explanation"):
            console.print(f"  [bold green]✅ Fix:[/bold green] {fix['explanation']}")
        if fix.get("generated"):
            console.print(f"  [dim]{fix['generated']}[/dim]")

        log_lines = error.get("relevant_log_lines") or []
        if log_lines:
            console.print(f"  [dim]Relevant log lines ({len(log_lines)}):[/dim]")
            for line in log_lines:
                console.print(f"    [dim]{line}[/dim]")

        console.print()


def render_web(diagnosis: dict, metadata: dict) -> None:
    """
    Starts the local FastAPI web report and opens it in the browser.
    """
    from cloudlens.webserver import start_server

    console.print("[cyan]Opening report in browser...[/cyan]")
    start_server(diagnosis, metadata)
