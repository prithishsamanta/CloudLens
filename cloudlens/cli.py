import click
from rich.console import Console
from core.fetcher import fetch_all_data
from core.analyzer import analyze_logs
from server.app import start_server

console = Console()

@click.command()
@click.option('--function', required=True)
@click.option('--region', default='us-east-2')
@click.option('--hours', default=24)
def debug(function, region, hours):
    console.print("\n[bold cyan] LambdaLens — AI-Powered Lambda Debugger[/bold cyan]")
    console.print(f"[dim]Analyzing function: {function} in {region}[/dim]\n")

    # fetch all data
    console.print("[cyan] Fetching Lambda logs and metadata...[/cyan]")
    data = fetch_all_data(function, region, hours)

    # analyze the data
    console.print("[cyan] Analyzing logs with Amazon Nova 2 Lite...[/cyan]")
    result = analyze_logs(data['metadata'], data['log_text'])

    # start the server
    console.print("[cyan] Opening report in browser...[/cyan]")
    start_server(result, data['metadata'])