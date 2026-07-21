import boto3
from datetime import datetime, timedelta
from rich.console import Console

console = Console()

# create get lambda metadata which via boto3 which pulls the lambda metadata from the lambda function
def get_lambda_metadata(function_name: str, region: str) -> dict:
    """
    Fetches Lambda function metadata like runtime, memory, timeout etc.
    """

    try:
        console.print(f"[cyan]Fetching Lambda metadata for: {function_name}[/cyan]")

        lambda_client = boto3.client('lambda', region_name=region)
        response = lambda_client.get_function_configuration(
            FunctionName=function_name
        )

        metadata = {
            "function_name": response.get("FunctionName"),
            "runtime": response.get("Runtime"),
            "memory": response.get("MemorySize"),
            "timeout": response.get("Timeout"),
            "last_modified": response.get("LastModified"),
            "handler": response.get("Handler"),
            "role": response.get("Role"),
            "region": region
        }
        
        console.print(f"[green]✓ Lambda metadata fetched successfully[/green]")
        return metadata

    except Exception as e:
        console.print(f"[red]✗ Failed to fetch Lambda metadata: {str(e)}[/red]")
        return None

# create get log streams which pulls the most recent log stream from cloud watch logs
def get_log_streams(function_name: str, region: str, hours: int = 24) -> list:
    """
    Fetches the most recent CloudWatch log streams for a Lambda function.
    """

    try:
        console.print(f"[cyan]Fetching log streams for: {function_name}[/cyan]")

        logs_client = boto3.client('logs', region_name=region)
        log_group_name = f"/aws/lambda/{function_name}"
        
        # Calculate start time
        start_time = datetime.utcnow() - timedelta(hours=hours)
        start_time_ms = int(start_time.timestamp() * 1000)
        
        response = logs_client.describe_log_streams(
            logGroupName=log_group_name,
            orderBy='LastEventTime',
            descending=True,
            limit=10  # Get 10 most recent streams
        )
        
        streams = response.get('logStreams', [])
        
        # Filter streams that have events within our time window
        recent_streams = [
            stream for stream in streams
            if stream.get('lastEventTimestamp', 0) >= start_time_ms
        ]
        
        console.print(f"[green]✓ Found {len(recent_streams)} log streams in the last {hours} hours[/green]")
        return recent_streams
    
    except Exception as e:
        console.print(f"[red]✗ Failed to fetch log streams: {str(e)}[/red]")
        return None

# create get log events pulls the actual log events from the log which got printed
def get_log_events(function_name: str, region: str, hours: int = 24) -> list:
    """
    Fetches all log events from recent streams for a Lambda function.
    """
    try:
        console.print(f"[cyan]Fetching log events...[/cyan]")
        
        logs_client = boto3.client('logs', region_name=region)
        log_group_name = f"/aws/lambda/{function_name}"
        
        # First get the streams
        streams = get_log_streams(function_name, region, hours)
        
        if not streams:
            console.print(f"[yellow]⚠ No log streams found in the last {hours} hours[/yellow]")
            return []
        
        all_events = []
        
        # Fetch events from each stream
        for stream in streams:
            stream_name = stream['logStreamName']
            
            try:
                response = logs_client.get_log_events(
                    logGroupName=log_group_name,
                    logStreamName=stream_name,
                    startFromHead=True
                )
                
                events = response.get('events', [])
                
                # Add stream name to each event for context
                for event in events:
                    event['streamName'] = stream_name
                    # Convert timestamp to readable format
                    event['timestamp_readable'] = datetime.fromtimestamp(
                        event['timestamp'] / 1000
                    ).strftime('%Y-%m-%d %H:%M:%S')
                
                all_events.extend(events)
                
            except Exception as e:
                console.print(f"[yellow]⚠ Could not fetch events from stream {stream_name}: {str(e)}[/yellow]")
                continue
        
        # Sort all events by timestamp
        all_events.sort(key=lambda x: x['timestamp'])
        
        console.print(f"[green]✓ Fetched {len(all_events)} log events successfully[/green]")
        return all_events
    
    except Exception as e:
        console.print(f"[red]✗ Failed to fetch log events: {str(e)}[/red]")
        return None

# create fetch all data which calls the above fuctions and will be accessed by the rest of the application
def fetch_all_data(function_name: str, region: str, hours: int = 24) -> dict:
    """
    Master function that fetches all data needed for analysis.
    Combines metadata + log streams + log events into one clean object.
    """
    console.print(f"\n[bold cyan]Starting data fetch for Lambda: {function_name}[/bold cyan]\n")
    
    # Fetch everything
    metadata = get_lambda_metadata(function_name, region)
    streams = get_log_streams(function_name, region, hours)
    events = get_log_events(function_name, region, hours)

    # Use safe defaults when API calls fail (e.g. invalid credentials)
    streams = streams if streams is not None else []
    events = events if events is not None else []

    # Format log events as clean text for Nova
    log_text = "\n".join([
        f"[{event['timestamp_readable']}] {event['message'].strip()}"
        for event in events
        if event.get('message', '').strip()
    ])

    result = {
        "metadata": metadata,
        "streams": streams,
        "events": events,
        "log_text": log_text,
        "total_events": len(events),
        "total_streams": len(streams),
        "hours_analyzed": hours
    }

    console.print(f"\n[bold green]✓ Data fetch complete![/bold green]")
    console.print(f"[green]  → {len(streams)} streams analyzed[/green]")
    console.print(f"[green]  → {len(events)} log events fetched[/green]\n")
    
    return result