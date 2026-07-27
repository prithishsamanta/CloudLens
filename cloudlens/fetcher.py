import re
import time
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError, EndpointConnectionError, NoRegionError
from rich.console import Console

console = Console()

_ERROR_FILTER = 'ERROR|Exception|WARN|FATAL'
_ERROR_TERMS = ["ERROR", "Exception", "WARN", "FATAL"]
_LAST_PATTERN = re.compile(r"^(\d+)([mh])$")


class FetchError(Exception):
    """
    Raised when fetching from CloudWatch fails for a real reason, such as a
    bad region or a permissions problem, as opposed to a query that ran
    successfully and simply found no events. Keeping these separate means a
    real failure can never get misreported as a clean "healthy" result.
    """
    pass


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
    Fetches basic metadata about any CloudWatch log group. Raises FetchError
    if CloudWatch itself couldn't be reached (bad region, no permissions,
    no connectivity). A log group that genuinely doesn't exist is not an
    error, that's reported via the "exists" key instead.
    """
    console.print(f"[cyan]Fetching log group metadata for: {log_group}[/cyan]")

    try:
        logs_client = boto3.client("logs", region_name=region)
        response = logs_client.describe_log_groups(logGroupNamePrefix=log_group)
    except (ClientError, EndpointConnectionError, NoRegionError) as e:
        raise FetchError(f"Could not reach CloudWatch Logs in region '{region}': {str(e)}") from e

    matches = [g for g in response.get("logGroups", []) if g.get("logGroupName") == log_group]
    if not matches:
        console.print(f"[yellow]⚠ Log group not found: {log_group}[/yellow]")
        return {"log_group": log_group, "region": region, "exists": False}

    group = matches[0]
    metadata = {
        "log_group": log_group,
        "region": region,
        "exists": True,
        "stored_bytes": group.get("storedBytes"),
        "retention_in_days": group.get("retentionInDays"),
        "creation_time": group.get("creationTime"),
    }

    console.print("[green]✓ Log group metadata fetched successfully[/green]")
    return metadata


def _insights_query(
    logs_client,
    log_group: str,
    start_time: int,
    end_time: int,
    error_only: bool,
    poll_interval: float,
    timeout_seconds: float,
) -> list:
    """
    Runs a CloudWatch Logs Insights query and returns matching events.
    Insights has its own indexing pipeline that can lag well behind raw
    ingestion, especially for log groups with very little data — so an
    empty result here doesn't necessarily mean there's nothing to find.
    """
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
            console.print(f"[yellow]⚠ Logs Insights query {status.lower()}[/yellow]")
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

    return events


def _filter_log_events(
    logs_client,
    log_group: str,
    start_time: int,
    end_time: int,
    error_only: bool,
) -> list:
    """
    Falls back to the FilterLogEvents API, which reads raw ingested events
    directly with no separate indexing step — slower to paginate for large
    volumes than Logs Insights, but always sees data the moment it lands.
    """
    filter_pattern = " ".join(f'?"{term}"' for term in _ERROR_TERMS) if error_only else ""

    events = []
    kwargs = {
        "logGroupName": log_group,
        "startTime": start_time * 1000,
        "endTime": end_time * 1000,
    }
    if filter_pattern:
        kwargs["filterPattern"] = filter_pattern

    while True:
        response = logs_client.filter_log_events(**kwargs)
        for event in response.get("events", []):
            timestamp_ms = event.get("timestamp", 0)
            events.append({
                "timestamp": timestamp_ms,
                "timestamp_readable": datetime.fromtimestamp(
                    timestamp_ms / 1000, tz=timezone.utc
                ).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                "message": event.get("message", ""),
                "streamName": event.get("logStreamName", ""),
            })

        next_token = response.get("nextToken")
        if not next_token or len(events) >= 10000:
            break
        kwargs["nextToken"] = next_token

    return events


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
    Fetches log events for the resolved time window, optionally filtering
    to error-shaped lines. Tries CloudWatch Logs Insights first (rich query
    syntax, fast for high-volume log groups); if that comes back empty,
    falls back to FilterLogEvents in case Insights just hasn't indexed the
    data yet — which reliably happens on low-volume/freshly created groups.

    Raises ValueError if --last/--since is malformed, and FetchError if
    CloudWatch itself couldn't be reached. Both propagate uncaught, so a
    real problem can never get silently reported as "0 events, healthy."
    """
    start_time = parse_time_window(last, since)
    end_time = int(time.time())

    console.print(f"[cyan]Querying log events in {log_group}...[/cyan]")

    try:
        logs_client = boto3.client("logs", region_name=region)
        events = _insights_query(
            logs_client, log_group, start_time, end_time, error_only, poll_interval, timeout_seconds
        )

        if not events:
            console.print("[yellow]⚠ No results from Logs Insights, falling back to raw log events...[/yellow]")
            events = _filter_log_events(logs_client, log_group, start_time, end_time, error_only)

    except (ClientError, EndpointConnectionError, NoRegionError) as e:
        raise FetchError(f"Failed to query CloudWatch Logs: {str(e)}") from e

    events.sort(key=lambda e: e["timestamp"])

    console.print(f"[green]✓ Fetched {len(events)} log events successfully[/green]")
    return events


def fetch_all_data(
    log_group: str,
    region: str,
    last: str = None,
    since: str = None,
    error_only: bool = False,
) -> dict:
    """
    Master function that fetches all data needed for analysis: log group
    metadata + filtered log events, combined into one clean object. Lets
    ValueError (bad --last/--since) and FetchError (CloudWatch unreachable)
    propagate uncaught, so the caller can distinguish a real failure from a
    genuinely empty result.
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
