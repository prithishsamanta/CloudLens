import click
from rich.console import Console

from cloudlens.bedrock import analyze_logs
from cloudlens.detector import resolve_service
from cloudlens.fetcher import fetch_all_data
from cloudlens.reporter import render_terminal, render_web

console = Console()


@click.group()
def main():
    pass


@main.command()
@click.option("--log-group", required=True, help="CloudWatch log group to analyze")
@click.option("--last", default="1h", help="Time window: 15m, 30m, 1h, 6h, 24h")
@click.option("--since", default=None, help="Absolute start time (ISO 8601)")
@click.option("--error-only", is_flag=True, default=False, help="Filter to ERROR/Exception/WARN/FATAL lines")
@click.option("--service", default="auto", help="Service hint: lambda, ecs, rds, apigateway, ec2, auto")
@click.option("--region", default="us-east-2", help="AWS region")
@click.option("--output", type=click.Choice(["terminal", "web"]), default="terminal", help="Output format")
def diagnose(log_group, last, since, error_only, service, region, output):
    console.print("\n[bold cyan]CloudLens — AI-Powered CloudWatch Diagnostics[/bold cyan]")
    console.print(f"[dim]Analyzing log group: {log_group} in {region}[/dim]\n")

    console.print("[cyan]Fetching CloudWatch logs and metadata...[/cyan]")
    data = fetch_all_data(log_group, region, last=last, since=since, error_only=error_only)

    resolved_service = resolve_service(log_group, service)
    data["metadata"]["service"] = resolved_service
    data["metadata"]["time_window"] = since or last

    if data["total_events"] == 0:
        console.print("[yellow]⚠ No log events found in this time window — skipping analysis[/yellow]")
        diagnosis = {
            "summary": "No log events were found in the selected time window.",
            "overall_health": "healthy",
            "errors": [],
        }
    else:
        console.print(f"[cyan]Analyzing logs with Amazon Nova ({resolved_service})...[/cyan]")
        diagnosis = analyze_logs(resolved_service, data["metadata"], data["log_text"])

    if output == "web":
        render_web(diagnosis, data["metadata"], data["log_text"], resolved_service)
    else:
        render_terminal(diagnosis, data["metadata"])
