import click
from rich.console import Console

from cloudlens.bedrock import BedrockError, analyze_logs
from cloudlens.credentials import check_aws_credentials
from cloudlens.detector import resolve_service
from cloudlens.fetcher import FetchError, fetch_all_data
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

    if not check_aws_credentials(region):
        raise SystemExit(1)

    console.print("[cyan]Fetching CloudWatch logs and metadata...[/cyan]")

    try:
        data = fetch_all_data(log_group, region, last=last, since=since, error_only=error_only)
    except ValueError as e:
        console.print(f"[red]{str(e)}[/red]")
        console.print()
        console.print("Check your --last or --since value and try again.")
        raise SystemExit(1)
    except FetchError as e:
        console.print(f"[red]{str(e)}[/red]")
        console.print()
        console.print("Check that the log group name and region are correct, and that your")
        console.print("AWS credentials have permission to access CloudWatch Logs.")
        raise SystemExit(1)

    if not data["metadata"].get("exists", True):
        console.print(f"[red]The log group '{log_group}' does not exist in region '{region}'.[/red]")
        console.print()
        console.print("Double check the log group name and region, then try again.")
        console.print("You can list your log groups with this command.")
        console.print()
        console.print(f"[bold cyan]  aws logs describe-log-groups --region {region}[/bold cyan]")
        raise SystemExit(1)

    resolved_service = resolve_service(log_group, service)
    data["metadata"]["service"] = resolved_service
    data["metadata"]["time_window"] = since or last

    if data["total_events"] == 0:
        console.print("[yellow]⚠ No log events found in this time window. Skipping analysis[/yellow]")
        diagnosis = {
            "summary": "No log events were found in the selected time window.",
            "overall_health": "healthy",
            "errors": [],
        }
    else:
        console.print(f"[cyan]Analyzing logs with Amazon Nova ({resolved_service})...[/cyan]")
        try:
            diagnosis = analyze_logs(resolved_service, data["metadata"], data["log_text"])
        except BedrockError as e:
            console.print(f"[red]{str(e)}[/red]")
            console.print()
            console.print("This usually means one of two things.")
            console.print("1. Your AWS credentials do not have permission to call Bedrock.")
            console.print("2. You have not requested access to the Nova model yet.")
            console.print()
            console.print("Model access has to be requested once per AWS account and region,")
            console.print("in the Amazon Bedrock console under Model access. Also check your")
            console.print("internet connection if the problem is not related to permissions.")
            raise SystemExit(1)

    if output == "web":
        from cloudlens.webserver import PortInUseError

        try:
            render_web(diagnosis, data["metadata"], data["log_text"], resolved_service)
        except PortInUseError as e:
            console.print(f"[red]{str(e)}[/red]")
            console.print()
            console.print("Stop whatever else is using that port, or wait a moment and try again.")
            raise SystemExit(1)
    else:
        render_terminal(diagnosis, data["metadata"])
