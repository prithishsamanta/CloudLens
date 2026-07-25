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
DEFAULT_MAX_TOKENS = 4096
MAX_TOKENS_CAP = 8192

# Nova Lite's context window is ~300K tokens. The chat panel warns the user
# well before that so they get a heads-up instead of a hard failure mid-reply.
CHAT_MAX_TOKENS = 1024
CHAT_CONTEXT_LIMIT = 300_000
CHAT_WARN_THRESHOLD = int(CHAT_CONTEXT_LIMIT * 0.85)

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


def _converse(prompt: str, max_tokens: int) -> dict:
    return bedrock_client.converse(
        modelId=MODEL_ID,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": max_tokens},
    )


def analyze_logs(service: str, metadata: dict, log_text: str) -> dict:
    """
    Sends logs to Nova via Bedrock and returns structured diagnosis.
    Retries on throttling, truncates the prompt once if it's too long, and
    raises maxTokens if Nova's response gets cut off mid-JSON.
    """
    prompt = build_prompt(service, metadata, log_text)
    max_tokens = DEFAULT_MAX_TOKENS

    for attempt in range(THROTTLE_RETRIES):
        try:
            console.print("[cyan]Sending logs to Amazon Nova for analysis...[/cyan]")
            response = _converse(prompt, max_tokens)

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
            if max_tokens < MAX_TOKENS_CAP and attempt < THROTTLE_RETRIES - 1:
                max_tokens = min(max_tokens * 2, MAX_TOKENS_CAP)
                console.print(
                    f"[yellow]⚠ Nova response was cut off, retrying with maxTokens={max_tokens}...[/yellow]"
                )
                continue

            console.print(f"[red]✗ Failed to parse Nova response as JSON: {str(e)}[/red]")
            raise

    raise RuntimeError("Bedrock analysis failed after retries")


def _build_chat_system_prompt(service: str, metadata: dict, log_text: str, diagnosis: dict) -> str:
    return f"""
    You are an AWS {service} debugging expert helping a developer understand a
    diagnostic report CloudLens just generated for their CloudWatch logs.

    Log Group: {metadata.get('log_group')}
    Region: {metadata.get('region')}
    Time Window: {metadata.get('time_window', 'unknown')}

    Original CloudWatch Logs analyzed:
    {log_text}

    Diagnosis already generated for this report:
    {json.dumps(diagnosis)}

    Answer the developer's follow-up questions about this specific report only
    — the errors found, the root causes, or how to implement the suggested
    fixes. Give plain-text answers, no JSON, no markdown code fences. Keep
    answers focused and practical. If asked about something unrelated to this
    report, say so and redirect to the report's content.
    """


def chat_reply(
    service: str,
    metadata: dict,
    log_text: str,
    diagnosis: dict,
    history: list,
    user_message: str,
) -> dict:
    """
    Sends a follow-up chat message to Nova, scoped strictly to the log data
    and diagnosis from this report — no memory beyond what's passed in.
    Returns {"reply": str, "context_tokens": int, "warning": str | None}.
    """
    system_prompt = _build_chat_system_prompt(service, metadata, log_text, diagnosis)

    messages = [{"role": "user" if i % 2 == 0 else "assistant", "content": [{"text": m}]}
                for i, m in enumerate(history)]
    messages.append({"role": "user", "content": [{"text": user_message}]})

    for attempt in range(THROTTLE_RETRIES):
        try:
            response = bedrock_client.converse(
                modelId=MODEL_ID,
                system=[{"text": system_prompt}],
                messages=messages,
                inferenceConfig={"maxTokens": CHAT_MAX_TOKENS},
            )

            reply_text = response["output"]["message"]["content"][0]["text"].strip()
            usage = response.get("usage", {})
            context_tokens = usage.get("inputTokens", 0) + usage.get("outputTokens", 0)

            warning = None
            if context_tokens >= CHAT_CONTEXT_LIMIT:
                warning = (
                    "This conversation has run out of room for the model to keep track of. "
                    "Reload the report to start a fresh chat."
                )
            elif context_tokens >= CHAT_WARN_THRESHOLD:
                warning = (
                    "This conversation is getting long — the AI may start losing track of "
                    "earlier context soon. Consider reloading the report to start fresh."
                )

            return {"reply": reply_text, "context_tokens": context_tokens, "warning": warning}

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")

            if error_code == "ThrottlingException" and attempt < THROTTLE_RETRIES - 1:
                time.sleep(2 ** attempt)
                continue

            if error_code == "ValidationException":
                return {
                    "reply": None,
                    "context_tokens": CHAT_CONTEXT_LIMIT,
                    "warning": (
                        "This conversation has run out of room for the model to keep track of. "
                        "Reload the report to start a fresh chat."
                    ),
                }

            raise

    raise RuntimeError("Chat reply failed after retries")
