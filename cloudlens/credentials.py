import boto3
from botocore.exceptions import NoCredentialsError, ClientError
from rich.console import Console

console = Console()


def check_aws_credentials(region: str) -> bool:
    """
    Verifies AWS credentials exist and are accepted by AWS, using a free,
    permission-agnostic STS call. Returns False and prints clear setup
    instructions if credentials are missing or rejected, so the CLI can
    stop early instead of silently falling through to a misleading
    empty report.
    """
    try:
        sts_client = boto3.client("sts", region_name=region)
        sts_client.get_caller_identity()
        return True

    except NoCredentialsError:
        console.print("[red]No AWS credentials were found on this machine.[/red]")
        console.print()
        console.print("CloudLens needs your AWS credentials to read CloudWatch Logs and call Bedrock.")
        console.print("Set them up by running this command and following the prompts.")
        console.print()
        console.print("[bold cyan]  aws configure[/bold cyan]")
        console.print()
        console.print("You will need an AWS Access Key ID, a Secret Access Key, and a default region.")
        console.print("You can create these in the AWS IAM console under your user's security credentials.")
        return False

    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        console.print(f"[red]AWS rejected your credentials ({error_code}).[/red]")
        console.print()
        console.print("This usually means your credentials are invalid, expired, or revoked.")
        console.print("Set up new credentials by running this command.")
        console.print()
        console.print("[bold cyan]  aws configure[/bold cyan]")
        console.print()
        console.print("You can check which identity your current credentials belong to with this command.")
        console.print()
        console.print("[bold cyan]  aws sts get-caller-identity[/bold cyan]")
        return False
