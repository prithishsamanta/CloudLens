VALID_SERVICES = {"lambda", "ecs", "rds", "apigateway", "ec2", "generic"}


def detect_service(log_group: str) -> str:
    """
    Infers the AWS service type from a CloudWatch log group name pattern.
    """
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


def resolve_service(log_group: str, service_hint: str = "auto") -> str:
    """
    Resolves the service type to use: an explicit --service hint wins,
    otherwise falls back to auto-detection from the log group name.
    """
    if service_hint and service_hint != "auto":
        return service_hint
    return detect_service(log_group)
