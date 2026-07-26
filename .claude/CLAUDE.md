# CLAUDE.md: CloudLens Project Context

## What This Project Is

CloudLens is an AI-powered CLI diagnostic tool that queries any AWS CloudWatch log group, sends filtered logs to Amazon Bedrock for analysis, and generates a structured report identifying error locations, root causes, and actionable fixes.

This is **v2** of a project previously called **LambdaLens**. LambdaLens v1 only supported AWS Lambda. CloudLens generalizes it to work with any CloudWatch log source. This includes Lambda, ECS, EC2, API Gateway, RDS, or any custom log group.

The tool will be published to **PyPI** so anyone can install it with `pip install cloudlens`.

---

## Current State

LambdaLens v1 is already built and on GitHub. The existing README.md in the repo describes v1. Read it for context on the core flow: fetching logs via Boto3, sending to Bedrock, and parsing output. CloudLens v2 refactors and extends that codebase.

**Do not start from scratch. Refactor the existing v1 code.**

---

## Tech Stack

- Python 3.10+
- Boto3: AWS SDK for CloudWatch Logs and Bedrock
- Amazon Bedrock: Nova 2 Lite model for log analysis (model ID: `amazon.nova-lite-v1:0`)
- CloudWatch Logs Insights: for fetching log events
- Click: CLI argument parsing (preferred over argparse)
- Rich: terminal output formatting (colored, structured)
- pyproject.toml: packaging for PyPI

---

## Target Package Structure

```
cloudlens/
├── __init__.py
├── cli.py          # Entry point, Click argument parsing
├── fetcher.py      # CloudWatch Logs queries via Boto3
├── detector.py     # Service type auto-detection from log group name
├── prompts.py      # Prompt templates per service type
├── bedrock.py      # Bedrock API calls and response parsing
├── reporter.py     # Terminal (Rich) rendering and web report wiring
├── webserver.py    # Local FastAPI report server (generalized from LambdaLens v1's server/app.py)
└── templates/
    └── report.html # Jinja2 template for the web report
pyproject.toml
README.md
```

---

## CLI Interface

All commands follow this pattern:

```bash
cloudlens diagnose --log-group /aws/lambda/my-function
cloudlens diagnose --log-group /ecs/my-service --last 30m
cloudlens diagnose --log-group /aws/rds/my-db --error-only
cloudlens diagnose --log-group /aws/apigateway/my-api --service apigateway
```

### Flags

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--log-group` | Yes | None | CloudWatch log group to analyze |
| `--last` | No | `1h` | Time window: `15m`, `30m`, `1h`, `6h`, `24h` |
| `--since` | No | None | Absolute start time for log fetch |
| `--error-only` | No | False | Filter to ERROR, Exception, WARN, FATAL lines before sending to Bedrock |
| `--service` | No | `auto` | Hint service type: `lambda`, `ecs`, `rds`, `apigateway`, `ec2`, `auto` |
| `--output` | No | `terminal` | Output format: `terminal` or `web` |

---

## Core Flow

```
1. Developer runs: cloudlens diagnose --log-group /aws/lambda/my-fn --last 1h
2. Authenticate using developer's existing AWS credentials (boto3 default chain, no extra setup needed)
3. Fetch log events from CloudWatch Logs for the specified time window
4. If --error-only, filter lines containing: ERROR, Exception, WARN, FATAL
5. Auto-detect service type from log group name pattern (or use --service hint)
6. Select appropriate prompt template for the detected service type
7. Send filtered logs + prompt to Amazon Bedrock Nova 2 Lite
8. Parse LLM response into structured sections: errors found, root cause, fix recommendations
9. Render to terminal (Rich, colored) or open the local web report (FastAPI + browser)
```

---

## Service Auto-Detection Logic

Detect service from log group name before falling back to generic:

```python
def detect_service(log_group: str) -> str:
    if log_group.startswith("/aws/lambda/"):
        return "lambda"
    elif log_group.startswith("/ecs/") or log_group.startswith("/aws/ecs/"):
        return "ecs"
    elif log_group.startswith("/aws/rds/"):
        return "rds"
    elif log_group.startswith("/aws/apigateway/"):
        return "apigateway"
    elif log_group.startswith("/aws/ec2/"):
        return "ec2"
    else:
        return "generic"
```

---

## Context-Aware Prompt Templates

Each service type gets its own prompt that tells Bedrock what to look for specifically. This is the key feature that separates CloudLens from a generic log summarizer.

| Service | What the prompt targets |
|---------|------------------------|
| **lambda** | Cold starts, timeouts ("Task timed out after"), memory limits ("Runtime exited"), permission errors (AccessDeniedException) |
| **ecs** | OOM kills (OutOfMemoryError), container exit codes, health check failures, deployment rollbacks |
| **apigateway** | 4xx/5xx spikes, latency outliers, integration timeouts, throttling (429) patterns |
| **rds** | Slow queries exceeding threshold, connection limit warnings, replication lag, deadlock events |
| **ec2** | Application errors, disk space warnings, CPU/memory pressure, systemd service failures |
| **generic** | ERROR/WARN frequency, exception patterns, anomalous timing, repeated failure signatures |

Prompts should request structured JSON output from Bedrock with these sections:
- `errors_found`: list of specific errors with line references
- `root_cause`: plain-English explanation of what went wrong
- `recommendations`: numbered list of actionable fixes
- `severity`: LOW, MEDIUM, HIGH, or CRITICAL

---

## Bedrock Integration

Use the Bedrock Runtime client with the Converse API:

```python
import boto3

client = boto3.client("bedrock-runtime", region_name="us-east-1")

response = client.converse(
    modelId="amazon.nova-lite-v1:0",
    messages=[
        {
            "role": "user",
            "content": [{"text": prompt}]
        }
    ]
)

output = response["output"]["message"]["content"][0]["text"]
```

Always wrap in try/except for:
- `ClientError`: IAM permission issues
- `ValidationException`: prompt too long, truncate logs if needed
- `ThrottlingException`: retry with exponential backoff

---

## Output Formatting

### Terminal Output (Rich)

Use Rich panels, tables, and colored text. Structure:

```
┌─────────────────────────────────────────┐
│  CloudLens Diagnostic Report            │
│  Log Group: /aws/lambda/my-function     │
│  Time Window: Last 1 hour               │
│  Severity: HIGH                         │
└─────────────────────────────────────────┘

🔴 ERRORS FOUND
  • Task timed out after 30.01 seconds (12 occurrences)
  • AccessDeniedException on s3:GetObject (3 occurrences)

🔍 ROOT CAUSE
  The function is attempting to read from an S3 bucket it does not
  have permission to access, causing retries that exhaust the timeout.

✅ RECOMMENDATIONS
  1. Add s3:GetObject permission to the Lambda execution role IAM policy
  2. Increase timeout from 30s to 60s as a temporary mitigation
  3. Add error handling to surface permission errors immediately
```

### Web Output

Start a local FastAPI server (generalized from LambdaLens v1's `server/app.py`) and open the report automatically in the developer's browser at `http://localhost:8000/report`. Rendered via a Jinja2 template (`cloudlens/templates/report.html`, generalized from v1's `report.html`) with the same structure as the terminal output. This includes a header with log group, time window, and severity, plus error cards, root cause, and recommendations. This is a first-class output mode, not a fallback. The tool intentionally offers both a terminal report and a beautified local web report.

---

## PyPI Publishing

### pyproject.toml Entry Point

```toml
[project.scripts]
cloudlens = "cloudlens.cli:main"
```

### Publishing Commands

```bash
pip install build twine
python -m build
twine upload dist/*
```

### Verify After Publishing

```bash
pip install cloudlens  # from a clean environment
cloudlens diagnose --help
```

---

## AWS Permissions Required

The developer's AWS credentials need:

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "logs:GetLogEvents",
                "logs:FilterLogEvents",
                "logs:StartQuery",
                "logs:GetQueryResults",
                "logs:DescribeLogGroups",
                "logs:DescribeLogStreams"
            ],
            "Resource": "*"
        },
        {
            "Effect": "Allow",
            "Action": [
                "bedrock:InvokeModel"
            ],
            "Resource": "*"
        }
    ]
}
```

---

## Security Design Principle

**Logs never leave the developer's AWS account.** The tool calls CloudWatch (their account) and Bedrock (their account). No data goes to any third-party service. This is a deliberate design decision to be stated clearly in the README and resume bullets.

---

## Resume Bullets (Target, after PyPI publish)

**Bullet 1:**
Developed a CLI diagnostic tool, published to PyPI, that queries any AWS CloudWatch log group using the developer's own credentials, sends filtered logs to Amazon Bedrock for AI-powered analysis, and generates a structured report identifying error locations, root causes, and actionable fixes. This reduces hours of manual log scanning to under 2 minutes.

**Bullet 2:**
Built context-aware prompt templates per AWS service type, including Lambda, ECS, API Gateway, and RDS, so the AI analysis targets failure patterns specific to each service rather than producing generic output. This includes parsing logic to handle variations in LLM response formatting and ensure every report is accurate and actionable.

**Bullet 3:**
Designed the tool to run entirely within the developer's own AWS account using their existing credentials, so logs and function metadata never leave their environment. This eliminates the security risk of piping production logs through a third-party service.

---

## What NOT To Do

- Do not add real-time log tailing. Fetch and analyze, do not stream
- Do not add multi-region support in v2. Use a single region per invocation
- Do not add log writing or mutations. Keep it read-only always
- Do not require any additional API keys or accounts beyond AWS credentials
- Do not import the full log group without filtering. Always apply the time window first to keep prompts manageable

---

## Build Order

Build modules in this order since each depends on the previous:

```
1. detector.py: no dependencies, pure string logic
2. fetcher.py: depends on boto3 and detector
3. prompts.py: no dependencies, pure string templates
4. bedrock.py: depends on boto3 and prompts
5. reporter.py: depends on Rich and parsed Bedrock output
6. cli.py: wires everything together via Click
```

---

## Reference

- Existing LambdaLens v1 code and README are in this repo. Read them before building
- CloudWatch Logs Insights docs: https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/CWL_QuerySyntax.html
- Bedrock Converse API docs: https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_Converse.html
- Rich docs: https://rich.readthedocs.io
- Click docs: https://click.palletsprojects.com
