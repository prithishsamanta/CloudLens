from core.fetcher import fetch_all_data
import boto3
from dotenv import load_dotenv
import os
from rich.console import Console
import json

# load environment variables first before anything else
load_dotenv()

# define the constant id for nova 2 lite
MODEL_ID = "us.amazon.nova-2-lite-v1:0"

# create a bedrock client which will be used to call the AWS Nova 2 Lite API via Bedrock SDK
bedrock_client = boto3.client(
    service_name='bedrock-runtime',
    region_name=os.getenv('AWS_REGION', 'us-east-2')
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


# create a prompt which will then be sent to analyze logs to call AWS Nova Lite API with the log
def build_prompt(metadata: dict, log_text: str) -> str:
    """
    Builds a prompt for Nova 2 Lite to analyze Lambda logs.
    """
    prompt = f"""
    You are an AWS Lambda debugging expert. Your role is to analyze CloudWatch logs 
    and identify exactly what went wrong and how to fix it.

    Function Metadata:
    - Name: {metadata.get('function_name')}
    - Runtime: {metadata.get('runtime')}
    - Memory: {metadata.get('memory')}MB
    - Timeout: {metadata.get('timeout')}s
    - Region: {metadata.get('region')}
    - Handler: {metadata.get('handler')}

    CloudWatch Logs:
    {log_text}

    Analyze these logs carefully and identify all errors, warnings, and issues.
    For each issue found, explain what happened, why it happened, and provide 
    specific actionable steps to fix it.

    Return your response ONLY as a valid JSON object with this exact structure, 
    no extra text, no markdown, no code blocks:
    {{
        "summary": "one sentence overall diagnosis of the Lambda function health",
        "overall_health": "critical or degraded or healthy",
        "errors": [
            {{
                "error_type": "short name of the error",
                "what_happened": "plain english explanation of what went wrong",
                "why_it_happened": "root cause explanation",
                "fix": {{
                    "explanation": "specific actionable steps to fix this in plain english",
                    "generated": "ready to use fix — corrected code pattern in the function runtime language based on the stack trace, exact IAM policy JSON, or specific configuration values depending on error type"
                }},
                "severity": "critical or warning or info",
                "relevant_log_lines": ["exact log line 1", "exact log line 2"]
            }}
        ]
    }}
    """
    return prompt

# create a function which will call the AWS Nova 2 Lite API via Bedrock SDK with the prompt
def analyze_logs(metadata: dict, log_text: str) -> dict:
    """
    Sends logs to Nova 2 Lite via Bedrock and returns structured diagnosis.
    """
    try:
        console.print("[cyan]Sending logs to Amazon Nova 2 Lite for analysis...[/cyan]")

        # build the prompt
        prompt = build_prompt(metadata, log_text)

        # call Nova 2 Lite via Bedrock
        response = bedrock_client.invoke_model(
            modelId=MODEL_ID,
            body=json.dumps({
                "messages": [
                    {"role": "user", "content": [{"text": prompt}]}
                ]
            })
        )

        # parse the response body
        response_body = json.loads(response['body'].read())

        # extract Nova's text response
        nova_response_text = response_body['output']['message']['content'][0]['text'].strip()

        # strip markdown code block if present (Nova sometimes wraps JSON in ```json ... ```)
        if nova_response_text.startswith("```"):
            lines = nova_response_text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            nova_response_text = "\n".join(lines)

        # Nova sometimes puts literal newlines inside string values; JSON requires \n. Sanitize first.
        nova_response_text = _sanitize_json_string(nova_response_text)

        # parse the JSON response from Nova
        diagnosis = json.loads(nova_response_text)

        console.print("[green]✓ Analysis complete[/green]")
        return diagnosis

    except json.JSONDecodeError as e:
        console.print(f"[red]✗ Failed to parse Nova response as JSON: {str(e)}[/red]")
        console.print(f"[yellow]Raw response: {nova_response_text}[/yellow]")
        raise

    except Exception as e:
        console.print(f"[red]✗ Failed to analyze logs: {str(e)}[/red]")
        raise