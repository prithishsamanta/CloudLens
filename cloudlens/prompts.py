# Every service prompt shares the same structured JSON response contract
# (summary/overall_health/errors[]) so bedrock.py, reporter.py, and
# webserver.py only need to handle one schema regardless of service type.

_RESPONSE_CONTRACT = """
Keep every field concise (1-3 sentences max, code snippets under 10 lines) so
the full response stays well under 3000 tokens. Report at most 5 errors,
picking the most significant ones if more are present.

Return your response ONLY as a valid JSON object with this exact structure,
no extra text, no markdown, no code blocks:
{{
    "summary": "one sentence overall diagnosis of the {service_label} health",
    "overall_health": "critical or degraded or healthy",
    "errors": [
        {{
            "error_type": "short name of the error",
            "what_happened": "plain english explanation of what went wrong",
            "why_it_happened": "root cause explanation",
            "fix": {{
                "explanation": "specific actionable steps to fix this in plain english",
                "generated": "ready to use fix: corrected code pattern, exact IAM policy JSON, or specific configuration values depending on error type"
            }},
            "severity": "critical or warning or info",
            "relevant_log_lines": ["exact log line 1", "exact log line 2"]
        }}
    ]
}}
"""

_SERVICE_FOCUS = {
    "lambda": (
        "AWS Lambda function",
        "Cold starts, timeouts (\"Task timed out after\"), memory limits "
        "(\"Runtime exited\"), and permission errors (AccessDeniedException).",
    ),
    "ecs": (
        "ECS service/task",
        "OOM kills (OutOfMemoryError), container exit codes, health check "
        "failures, and deployment rollbacks.",
    ),
    "apigateway": (
        "API Gateway API",
        "4xx/5xx spikes, latency outliers, integration timeouts, and "
        "throttling (429) patterns.",
    ),
    "rds": (
        "RDS database",
        "Slow queries exceeding threshold, connection limit warnings, "
        "replication lag, and deadlock events.",
    ),
    "ec2": (
        "EC2 instance",
        "Application errors, disk space warnings, CPU/memory pressure, and "
        "systemd service failures.",
    ),
    "generic": (
        "AWS service",
        "ERROR/WARN frequency, exception patterns, anomalous timing, and "
        "repeated failure signatures.",
    ),
}


def build_prompt(service: str, metadata: dict, log_text: str) -> str:
    """
    Builds a service-aware prompt for Nova to analyze CloudWatch logs,
    targeting the failure patterns specific to the detected service type.
    """
    service_label, focus = _SERVICE_FOCUS.get(service, _SERVICE_FOCUS["generic"])

    prompt = f"""
    You are an AWS {service_label} debugging expert. Your role is to analyze
    CloudWatch logs and identify exactly what went wrong and how to fix it.

    Focus specifically on: {focus}

    Log Group: {metadata.get('log_group')}
    Region: {metadata.get('region')}
    Time Window: {metadata.get('time_window', 'unknown')}

    CloudWatch Logs:
    {log_text}

    Analyze these logs carefully and identify all errors, warnings, and issues.
    For each issue found, explain what happened, why it happened, and provide
    specific actionable steps to fix it.
    """
    prompt += _RESPONSE_CONTRACT.format(service_label=service_label)
    return prompt
