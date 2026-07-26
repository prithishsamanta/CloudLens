# CloudLens: An AI-Powered AWS CloudWatch Diagnostic Tool

> Stop staring at CloudWatch logs. Let AI tell you exactly what went wrong and how to fix it.

CloudLens is a CLI tool that queries any AWS CloudWatch log group. This includes Lambda, ECS, EC2, API Gateway, RDS, or a custom log source. It sends the filtered logs to **Amazon Nova** via Amazon Bedrock for analysis and gives you a structured diagnostic report identifying error locations, root causes, and actionable fixes.

Originally built as LambdaLens (Lambda-only), generalized in v2 to work with any CloudWatch log group.

---

## Quick Install

CloudLens is published on PyPI. You need Python 3.10 or newer to use it. The steps are slightly different depending on your operating system, mostly because of how each system handles a fresh Python virtual environment.

### macOS

Check your Python version first.

```bash
python3 --version
```

If it says 3.10 or higher, you are set. If it is older, or you use Homebrew's Python, install into a dedicated virtual environment. This avoids the "externally managed environment" error that Homebrew's Python now shows when you try to install packages directly.

```bash
python3 -m venv ~/cloudlens-env
source ~/cloudlens-env/bin/activate
pip install cloudlens
```

### Windows

Install Python 3.10 or newer from [python.org](https://www.python.org/downloads/) if you do not already have it. During setup, check the box that says "Add Python to PATH."

Open PowerShell or Command Prompt, then run:

```powershell
python -m venv cloudlens-env
cloudlens-env\Scripts\activate
pip install cloudlens
```

### Linux

Most modern distributions (Ubuntu, Debian, Fedora) also block direct global installs, similar to macOS. Use a virtual environment the same way.

```bash
python3 -m venv ~/cloudlens-env
source ~/cloudlens-env/bin/activate
pip install cloudlens
```

### Confirm it installed correctly

With your virtual environment still active, run:

```bash
cloudlens diagnose --help
```

You should see the list of available options. If you do, the install worked.

### Configure your AWS credentials

CloudLens uses your own AWS credentials to read CloudWatch Logs and call Amazon Bedrock. If you have not set this up yet, run:

```bash
aws configure
```

and provide your AWS Access Key ID, Secret Access Key, and a default region.

If you skip this step, CloudLens checks for valid credentials before doing anything else. It prints clear setup instructions in the terminal instead of failing partway through.

### Using it later

Your virtual environment only stays active for the current terminal session. Any time you open a new terminal and want to use CloudLens, activate it again first.

```bash
# macOS/Linux
source ~/cloudlens-env/bin/activate

# Windows
cloudlens-env\Scripts\activate
```

Then run any `cloudlens diagnose` command as usual.

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
- **Specific actionable fixes**: not generic advice, but exact steps tailored to your logs, such as corrected code, IAM policy JSON, or config changes
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

## AWS Account Requirements

Your AWS account needs access to these two services for CloudLens to work.

- Amazon CloudWatch Logs
- Amazon Bedrock (Nova model)

See [Quick Install](#quick-install) above for how to install the tool itself and configure your credentials.

---

## Development Setup

The steps above install CloudLens as a regular package for using it. If you want to work on CloudLens itself, contribute a change, or run it directly from source, use this setup instead.

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

**3. Install in editable mode**

```bash
pip install -e .
```

This installs all dependencies and registers the `cloudlens` command, but points it at your local source files, so any changes you make take effect immediately without reinstalling.

**4. Configure AWS credentials**

```bash
aws configure
```

Provide your AWS Access Key ID, Secret Access Key, and a default region (for example `us-east-2`).

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
| `--log-group` | CloudWatch log group to analyze (required) | None |
| `--last` | Relative time window: `15m`, `30m`, `1h`, `6h`, `24h` | `1h` |
| `--since` | Absolute start time (ISO 8601), overrides `--last` | None |
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
- **How to fix**: ready-to-use fixes, such as corrected code patterns, exact IAM policy JSON, or specific configuration changes depending on the error type
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
├── pyproject.toml             # Package configuration and dependencies
├── .env                       # Environment variables (not committed)
└── README.md
```

---

## Testing

```bash
pip install -e ".[test]"
pytest
```

Runs the full unit test suite (`tests/`) with AWS and Bedrock calls mocked via `moto` and `unittest.mock`. There are no real credentials, no cost, and no network calls.

The `manual/` directory has separate smoke-test scripts (`smoke_test_fetcher.py`, `smoke_test_analyzer.py`, `smoke_test_web.py`) that hit real AWS CloudWatch Logs and Amazon Bedrock. They're not run by `pytest`, need live AWS credentials and an existing log group, and calling Bedrock costs real money. Run them directly with `python manual/smoke_test_fetcher.py` when you want to sanity-check against real infrastructure.

---

## What's Next

- **Multi-log-group fleet analysis**: analyze every log group in your account at once and get a health dashboard ranked by severity.
- **CI/CD integration**: run CloudLens in your deployment pipeline to catch issues before they reach users.
- **IDE plugin**: bring the same debugging intelligence into VS Code so you never leave your editor.

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
