import re
import time
from datetime import datetime, timezone

import boto3
from rich.console import Console

console = Console()

_ERROR_FILTER = 'ERROR|Exception|WARN|FATAL'
_LAST_PATTERN = re.compile(r"^(\d+)([mh])$")


def parse_time_window(last: str = None, since: str = None) -> int:
    """
    Resolves a start time (epoch seconds) from either --last (relative, e.g.
    15m/30m/1h/6h/24h) or --since (absolute, ISO 8601). --since takes
    precedence if both are given.
    """
    if since:
        dt = datetime.fromisoformat(since)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())

    last = last or "1h"
    match = _LAST_PATTERN.match(last)
    if not match:
        raise ValueError(f"Invalid --last value: {last!r} (expected e.g. 15m, 30m, 1h, 6h, 24h)")

    amount, unit = int(match.group(1)), match.group(2)
    seconds = amount * 60 if unit == "m" else amount * 3600
    return int(time.time()) - seconds


def describe_log_group(log_group: str, region: str) -> dict:
    """
    Fetches basic metadata about any CloudWatch log group.
    """
    try:
        console.print(f"[cyan]Fetching log group metadata for: {log_group}[/cyan]")

        logs_client = boto3.client("logs", region_name=region)
        response = logs_client.describe_log_groups(logGroupNamePrefix=log_group)

        matches = [g for g in response.get("logGroups", []) if g.get("logGroupName") == log_group]
        if not matches:
            console.print(f"[yellow]⚠ Log group not found: {log_group}[/yellow]")
            return {"log_group": log_group, "region": region}

        group = matches[0]
        metadata = {
            "log_group": log_group,
            "region": region,
            "stored_bytes": group.get("storedBytes"),
            "retention_in_days": group.get("retentionInDays"),
            "creation_time": group.get("creationTime"),
        }

        console.print("[green]✓ Log group metadata fetched successfully[/green]")
        return metadata

    except Exception as e:
        console.print(f"[red]✗ Failed to fetch log group metadata: {str(e)}[/red]")
        return {"log_group": log_group, "region": region}


def query_log_events(
    log_group: str,
    region: str,
    last: str = None,
    since: str = None,
    error_only: bool = False,
    poll_interval: float = 1.0,
    timeout_seconds: float = 60.0,
) -> list:
    """
    Runs a CloudWatch Logs Insights query against the given log group for
    the resolved time window, optionally filtering to error-shaped lines,
    and returns the matching log events sorted by time.
    """
    try:
        console.print(f"[cyan]Querying log events in {log_group}...[/cyan]")

        logs_client = boto3.client("logs", region_name=region)

        start_time = parse_time_window(last, since)
        end_time = int(time.time())

        filter_clause = f"| filter @message like /{_ERROR_FILTER}/\n" if error_only else ""
        query_string = (
            "fields @timestamp, @message, @logStream\n"
            f"{filter_clause}"
            "| sort @timestamp asc\n"
            "| limit 10000"
        )

        start_response = logs_client.start_query(
            logGroupName=log_group,
            startTime=start_time,
            endTime=end_time,
            queryString=query_string,
        )
        query_id = start_response["queryId"]

        elapsed = 0.0
        results = []
        while elapsed < timeout_seconds:
            response = logs_client.get_query_results(queryId=query_id)
            status = response.get("status")

            if status == "Complete":
                results = response.get("results", [])
                break
            elif status in ("Failed", "Cancelled", "Timeout"):
                console.print(f"[red]✗ Logs Insights query {status.lower()}[/red]")
                return []

            time.sleep(poll_interval)
            elapsed += poll_interval

        events = []
        for row in results:
            fields = {f["field"]: f["value"] for f in row}
            timestamp_str = fields.get("@timestamp", "")
            timestamp_ms = 0
            if timestamp_str:
                dt = datetime.fromisoformat(timestamp_str.replace(" ", "T")).replace(tzinfo=timezone.utc)
                timestamp_ms = int(dt.timestamp() * 1000)
            events.append({
                "timestamp": timestamp_ms,
                "timestamp_readable": timestamp_str,
                "message": fields.get("@message", ""),
                "streamName": fields.get("@logStream", ""),
            })

        events.sort(key=lambda e: e["timestamp"])

        console.print(f"[green]✓ Fetched {len(events)} log events successfully[/green]")
        return events

    except Exception as e:
        console.print(f"[red]✗ Failed to query log events: {str(e)}[/red]")
        return []


def fetch_all_data(
    log_group: str,
    region: str,
    last: str = None,
    since: str = None,
    error_only: bool = False,
) -> dict:
    """
    Master function that fetches all data needed for analysis: log group
    metadata + filtered log events, combined into one clean object.
    """
    console.print(f"\n[bold cyan]Starting data fetch for log group: {log_group}[/bold cyan]\n")

    metadata = describe_log_group(log_group, region)
    events = query_log_events(log_group, region, last=last, since=since, error_only=error_only)

    log_text = "\n".join([
        f"[{event['timestamp_readable']}] {event['message'].strip()}"
        for event in events
        if event.get("message", "").strip()
    ])

    result = {
        "metadata": metadata,
        "events": events,
        "log_text": log_text,
        "total_events": len(events),
        "time_window": since or (last or "1h"),
        "error_only": error_only,
    }

    console.print("\n[bold green]✓ Data fetch complete![/bold green]")
    console.print(f"[green]  → {len(events)} log events fetched[/green]\n")

    return result
