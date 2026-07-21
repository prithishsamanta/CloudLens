import json
import os
import time

import boto3
from botocore.exceptions import ClientError
from rich.console import Console

from cloudlens.prompts import build_prompt

# LambdaLens v1 used this exact model ID successfully via invoke_model; kept
# as-is for the converse API since it's the proven-working ID for this account.
MODEL_ID = "us.amazon.nova-2-lite-v1:0"

MAX_LOG_CHARS = 60_000
THROTTLE_RETRIES = 3

bedrock_client = boto3.client(
    service_name="bedrock-runtime",
    region_name=os.getenv("AWS_REGION", "us-east-2"),
)

console = Console()


def _sanitize_json_string(s: str) -> str:
    """
    Replace literal newlines and other control chars inside JSON string values
    with their escaped form. Nova sometimes returns these, which makes json.loads() fail.
    """
    result = []
    i = 0
    in_string = False
    escape_next = False
    while i < len(s):
        c = s[i]
        if escape_next:
            result.append(c)
            escape_next = False
            i += 1
            continue
        if in_string and c == "\\":
            result.append(c)
            escape_next = True
            i += 1
            continue
        if c == '"' and not escape_next:
            in_string = not in_string
            result.append(c)
            i += 1
            continue
        if in_string and c == "\n":
            result.append("\\n")
            i += 1
            continue
        if in_string and c == "\r":
            result.append("\\r")
            i += 1
            continue
        if in_string and ord(c) < 32:
            result.append(f"\\u{ord(c):04x}")
            i += 1
            continue
        result.append(c)
        i += 1
    return "".join(result)


def _extract_text(response: dict) -> str:
    text = response["output"]["message"]["content"][0]["text"].strip()

    # strip markdown code block if present (Nova sometimes wraps JSON in ```json ... ```)
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)

    return _sanitize_json_string(text)


def _converse(prompt: str) -> dict:
    return bedrock_client.converse(
        modelId=MODEL_ID,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
    )


def analyze_logs(service: str, metadata: dict, log_text: str) -> dict:
    """
    Sends logs to Nova via Bedrock and returns structured diagnosis.
    Retries on throttling and truncates the prompt once if it's too long.
    """
    prompt = build_prompt(service, metadata, log_text)

    for attempt in range(THROTTLE_RETRIES):
        try:
            console.print("[cyan]Sending logs to Amazon Nova for analysis...[/cyan]")
            response = _converse(prompt)

            nova_response_text = _extract_text(response)
            diagnosis = json.loads(nova_response_text)

            console.print("[green]✓ Analysis complete[/green]")
            return diagnosis

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")

            if error_code == "ThrottlingException" and attempt < THROTTLE_RETRIES - 1:
                backoff = 2 ** attempt
                console.print(f"[yellow]⚠ Throttled by Bedrock, retrying in {backoff}s...[/yellow]")
                time.sleep(backoff)
                continue

            if error_code == "ValidationException" and len(log_text) > MAX_LOG_CHARS:
                console.print("[yellow]⚠ Prompt too long, truncating logs and retrying...[/yellow]")
                log_text = log_text[-MAX_LOG_CHARS:]
                prompt = build_prompt(service, metadata, log_text)
                continue

            console.print(f"[red]✗ Bedrock call failed ({error_code}): {str(e)}[/red]")
            raise

        except json.JSONDecodeError as e:
            console.print(f"[red]✗ Failed to parse Nova response as JSON: {str(e)}[/red]")
            raise

    raise RuntimeError("Bedrock analysis failed after retries")
