# CloudLens: An AI-Powered AWS CloudWatch Diagnostic Tool

> Stop staring at CloudWatch logs. Let AI tell you exactly what went wrong and how to fix it.

CloudLens is a CLI tool that queries any AWS CloudWatch log group — Lambda, ECS, EC2, API Gateway, RDS, or a custom log source — sends the filtered logs to **Amazon Nova** via Amazon Bedrock for analysis, and gives you a structured diagnostic report identifying error locations, root causes, and actionable fixes.

Originally built as LambdaLens (Lambda-only), generalized in v2 to work with any CloudWatch log group.

---

## Demo

```
$ cloudlens diagnose --log-group /ecs/my-service --last 1h

CloudLens — AI-Powered CloudWatch Diagnostics
Analyzing log group: /ecs/my-service in us-east-2

Fetching CloudWatch logs and metadata...
✓ Log group metadata fetched successfully
✓ Fetched 142 log events successfully

Analyzing logs with Amazon Nova (ecs)...
✓ Analysis complete

╭─────────────────────────────────────────────╮
│ CloudLens Diagnostic Report                 │
│ Log Group: /ecs/my-service                  │
│ Service: ecs                                │
│ Overall Health: CRITICAL                    │
╰─────────────────────────────────────────────╯

🔴 OutOfMemoryError
  What happened: The container was killed due to running out of memory.
  Root cause: The application exceeded the task's memory limit.
  ✅ Fix: Increase the memoryReservation/memory values in the ECS task definition.
```

By default, results print directly in the terminal. Pass `--output web` to get the same diagnosis rendered as a clean, minimalist dashboard at `http://localhost:8000/report`, opened automatically in your browser.

---

## Features

- **One command debugging**: point it at any CloudWatch log group and get instant AI-powered diagnosis
- **Works with any AWS service**: auto-detects Lambda, ECS, RDS, API Gateway, or EC2 from the log group name, or you can hint it with `--service`
- **Powered by Amazon Nova via Bedrock**: advanced reasoning model identifies root causes, not just error names
- **Two output modes**: a Rich terminal report by default, or a beautiful local web dashboard with `--output web`
- **Context-aware prompts**: each service type gets a prompt tuned to its own failure patterns (cold starts and timeouts for Lambda, OOM kills for ECS, slow queries for RDS, etc.)
- **Specific actionable fixes**: not generic advice, but exact steps tailored to your logs — corrected code, IAM policy JSON, or config changes
- **Zero extra setup**: uses your existing AWS credentials, no API keys or logins needed
- **Privacy first**: your logs never leave your AWS account except to Bedrock, which you already use

---

## Architecture

```
cloudlens CLI (Click)
        ↓
cloudlens/detector.py
  → Infers service type (lambda/ecs/rds/apigateway/ec2/generic) from the log group name, or uses --service
        ↓
cloudlens/fetcher.py
  → boto3 fetches log group metadata
  → CloudWatch Logs Insights query (start_query/get_query_results) for the given --last/--since window
  → Optional --error-only filter applied at query time
        ↓
cloudlens/prompts.py + cloudlens/bedrock.py
  → Builds a service-specific prompt with log context
  → Calls Amazon Nova via Amazon Bedrock (converse API)
  → Returns structured JSON diagnosis, with retry/backoff on throttling
        ↓
cloudlens/reporter.py
  → render_terminal(): Rich panels/tables printed directly in the CLI
  → render_web(): hands off to the local FastAPI report
        ↓
cloudlens/webserver.py + cloudlens/templates/report.html
  → FastAPI serves the report at localhost:8000
  → Jinja2 renders the diagnosis into a light, minimalist dashboard
  → Browser opens automatically
```

---

## Prerequisites

- Python 3.10+
- **AWS credentials configured**: CloudLens uses your AWS credentials to call CloudWatch Logs and Bedrock. Configure them via the AWS CLI:
  ```bash
  aws configure
  ```
  You'll need an AWS account with access to:
  - Amazon CloudWatch Logs
  - Amazon Bedrock (Nova model)

---

## Installation

**1. Clone the repository**

```bash
git clone https://github.com/prithishsamanta/cloudlens.git
cd cloudlens
```

**2. Create and activate a virtual environment**

```bash
python -m venv venv

# Mac/Linux
source venv/bin/activate

# Windows
venv\Scripts\activate
```

**3. Install the package**

```bash
pip install -e .
```

This installs all dependencies and registers the `cloudlens` command globally in your terminal.

**4. Configure AWS credentials (required for the tool to work)**

CloudLens needs your AWS credentials to query CloudWatch Logs and to call Bedrock. If you haven't already:

```bash
aws configure
```

Provide:
- AWS Access Key ID
- AWS Secret Access Key
- Default region (e.g. `us-east-2`)

---

## Usage

### Basic usage

```bash
cloudlens diagnose --log-group /ecs/my-service
```

### Examples

```bash
# Analyze an ECS service, only the last 30 minutes
cloudlens diagnose --log-group /ecs/my-service --last 30m

# Analyze RDS logs, filtering to error-shaped lines only
cloudlens diagnose --log-group /aws/rds/my-db --error-only

# Hint the service type explicitly instead of relying on auto-detection
cloudlens diagnose --log-group /aws/apigateway/my-api --service apigateway

# Open the beautified local web report instead of terminal output
cloudlens diagnose --log-group /aws/ec2/my-instance --output web

# Use an absolute start time instead of a relative window
cloudlens diagnose --log-group /ecs/my-service --since 2026-07-01T00:00:00

# Also works with Lambda function log groups
cloudlens diagnose --log-group /aws/lambda/my-api-handler --last 1h
```

### Options

| Option | Description | Default |
|--------|-------------|---------|
| `--log-group` | CloudWatch log group to analyze (required) | — |
| `--last` | Relative time window: `15m`, `30m`, `1h`, `6h`, `24h` | `1h` |
| `--since` | Absolute start time (ISO 8601), overrides `--last` | — |
| `--error-only` | Filter to ERROR, Exception, WARN, FATAL lines before sending to Bedrock | `False` |
| `--service` | Service hint: `lambda`, `ecs`, `rds`, `apigateway`, `ec2`, `auto` | `auto` |
| `--region` | AWS region | `us-east-2` |
| `--output` | Output format: `terminal` or `web` | `terminal` |

---

## What the Report Shows

Both the terminal and web report include:

**Header**
- Log group, region, and detected/hinted service type
- Overall health status (Healthy / Degraded / Critical)

**AI Diagnosis Summary**
- One sentence overall assessment from Nova
- Total issues found, critical count, warning count

**Error Cards** (one per detected issue)
- Error type with severity badge (Critical / Warning / Info)
- **What happened**: plain English explanation
- **Root cause**: why it happened
- **How to fix**: ready-to-use fixes — corrected code patterns, exact IAM policy JSON, or specific configuration changes depending on the error type
- **Relevant log lines**: the exact log lines that triggered the error

---

## What CloudLens Can Detect

Detection targets are tuned per service type:

- **Lambda**: cold starts, timeouts, memory limit issues, IAM permission errors, VPC connectivity failures, runtime exceptions
- **ECS**: OOM kills, container exit codes, health check failures, deployment rollbacks
- **API Gateway**: 4xx/5xx spikes, latency outliers, integration timeouts, throttling patterns
- **RDS**: slow queries, connection limit warnings, replication lag, deadlocks
- **EC2**: application errors, disk space warnings, CPU/memory pressure, systemd service failures
- **Generic**: ERROR/WARN frequency, exception patterns, anomalous timing, repeated failure signatures

---

## Tech Stack

| Component | Technology |
|-----------|------------|
| CLI | Python + Click |
| AWS Integration | boto3, CloudWatch Logs Insights |
| AI Model | Amazon Nova |
| AI Platform | Amazon Bedrock (Converse API) |
| Terminal Output | Rich |
| Web Report Server | FastAPI + Uvicorn |
| Templating | Jinja2 |
| Frontend | Tailwind CSS + Alpine.js |
| Packaging | pyproject.toml (PyPI) |

---

## Project Structure

```
cloudlens/                      # or your clone directory
├── cloudlens/
│   ├── __init__.py
│   ├── cli.py                 # CLI entry point (cloudlens command)
│   ├── detector.py            # Service type auto-detection from log group name
│   ├── fetcher.py             # CloudWatch Logs Insights queries via boto3
│   ├── prompts.py             # Per-service-type prompt templates
│   ├── bedrock.py             # Bedrock Converse API calls and response parsing
│   ├── reporter.py            # Terminal (Rich) rendering and web report wiring
│   ├── webserver.py           # Local FastAPI report server
│   └── templates/
│       └── report.html        # Visual diagnostic report
├── pyproject.toml             # Package configuration
├── requirements.txt           # Dependencies
├── .env                       # Environment variables (not committed)
└── README.md
```

---

## What's Next

- **Multi-log-group fleet analysis**: analyze every log group in your account at once and get a health dashboard ranked by severity.
- **CI/CD integration**: run CloudLens in your deployment pipeline to catch issues before they reach users.
- **IDE plugin**: bring the same debugging intelligence into VS Code so you never leave your editor.
- **PyPI publish**: ship `pip install cloudlens` as a standalone install, no clone required.

---

## Privacy & Security

- **No data storage**: logs are fetched, analyzed, and displayed in memory only
- **No external transmission**: your logs only go to AWS APIs (CloudWatch, Bedrock) that you already use, within your own AWS account
- **Uses existing credentials**: no new API keys or accounts needed
- **Local report**: the web report is served locally on your machine only, never hosted externally
- **Credentials never touched**: CloudLens uses boto3's standard credential chain, never reads or stores your AWS keys directly

---

## Contributing

Contributions are welcome. Please open an issue first to discuss what you'd like to change.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## License

This project is licensed under the MIT License, see the [LICENSE](LICENSE) file for details.

---

## Author

**Prithish Samanta**

Originally built as LambdaLens, generalized into CloudLens.

---

## Acknowledgements

- [Amazon Nova](https://aws.amazon.com/ai/nova/), for the powerful reasoning model
- [Amazon Bedrock](https://aws.amazon.com/bedrock/), for the managed AI infrastructure
- [boto3](https://boto3.amazonaws.com/v1/documentation/api/latest/index.html), for the excellent AWS SDK
- [FastAPI](https://fastapi.tiangolo.com/), for the lightweight local server
- [Rich](https://rich.readthedocs.io/), for the beautiful terminal output
