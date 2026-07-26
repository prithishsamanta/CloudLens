# Manual smoke test — hits real AWS CloudWatch Logs. Requires live AWS
# credentials and an existing log group; not run by pytest/CI.
from cloudlens.fetcher import fetch_all_data

# Replace with your actual log group and region
result = fetch_all_data(
    log_group="/aws/lambda/nova-debugger-test",
    region="us-east-2",
    last="24h",
)

print("\n--- METADATA ---")
for key, value in result["metadata"].items():
    print(f"{key}: {value}")

print("\n--- LOG SAMPLE (first 500 chars) ---")
print(result["log_text"][:500])
