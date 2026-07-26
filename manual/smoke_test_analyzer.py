# Manual smoke test — hits real AWS CloudWatch Logs and Amazon Bedrock.
# Requires live AWS credentials and an existing log group; not run by
# pytest/CI, and calling Bedrock costs real money.
from cloudlens.bedrock import analyze_logs
from cloudlens.detector import resolve_service
from cloudlens.fetcher import fetch_all_data

log_group = "/aws/lambda/nova-debugger-test"
region = "us-east-2"

data = fetch_all_data(log_group=log_group, region=region, last="24h")

service = resolve_service(log_group)
data["metadata"]["service"] = service
data["metadata"]["time_window"] = "24h"

result = analyze_logs(service, data["metadata"], data["log_text"])

print("\n--- DIAGNOSIS ---")
print(f"Summary: {result['summary']}")
print(f"Health: {result['overall_health']}")
print(f"\nErrors found: {len(result['errors'])}")
for error in result["errors"]:
    print(f"\n→ {error['error_type']} [{error['severity']}]")
    print(f"  What: {error['what_happened']}")
    print(f"  Why: {error['why_it_happened']}")
    print(f"  Fix: {error['fix']['explanation']}")
