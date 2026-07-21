from cloudlens.detector import detect_service, resolve_service


def test_detect_service():
    assert detect_service("/aws/lambda/my-fn") == "lambda"
    assert detect_service("/ecs/my-service") == "ecs"
    assert detect_service("/aws/ecs/my-service") == "ecs"
    assert detect_service("/aws/rds/my-db") == "rds"
    assert detect_service("/aws/apigateway/my-api") == "apigateway"
    assert detect_service("/aws/ec2/my-instance") == "ec2"
    assert detect_service("/custom/anything") == "generic"


def test_resolve_service_hint_overrides_detection():
    assert resolve_service("/aws/lambda/my-fn", "ecs") == "ecs"
    assert resolve_service("/aws/lambda/my-fn", "auto") == "lambda"
    assert resolve_service("/aws/lambda/my-fn") == "lambda"
