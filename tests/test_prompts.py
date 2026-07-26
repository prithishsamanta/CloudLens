import pytest

from cloudlens.prompts import _SERVICE_FOCUS, build_prompt


@pytest.mark.parametrize("service", ["lambda", "ecs", "apigateway", "rds", "ec2", "generic"])
def test_build_prompt_includes_service_specific_focus(service):
    metadata = {"log_group": "/aws/x/y", "region": "us-east-2", "time_window": "1h"}
    prompt = build_prompt(service, metadata, "some log text")

    _, focus = _SERVICE_FOCUS[service]
    assert focus in prompt


def test_build_prompt_unknown_service_falls_back_to_generic():
    metadata = {"log_group": "/custom/logs", "region": "us-east-2"}
    prompt = build_prompt("totally-unknown-service", metadata, "logs")

    _, generic_focus = _SERVICE_FOCUS["generic"]
    assert generic_focus in prompt


def test_build_prompt_includes_log_group_and_log_text():
    metadata = {"log_group": "/aws/lambda/my-fn", "region": "us-east-2", "time_window": "24h"}
    prompt = build_prompt("lambda", metadata, "ERROR: something broke")

    assert "/aws/lambda/my-fn" in prompt
    assert "us-east-2" in prompt
    assert "24h" in prompt
    assert "ERROR: something broke" in prompt


def test_build_prompt_includes_response_contract_json_shape():
    prompt = build_prompt("lambda", {"log_group": "x", "region": "y"}, "logs")

    for key in ["summary", "overall_health", "errors", "error_type", "severity", "relevant_log_lines"]:
        assert key in prompt


def test_build_prompt_missing_time_window_defaults_to_unknown():
    metadata = {"log_group": "/aws/lambda/my-fn", "region": "us-east-2"}
    prompt = build_prompt("lambda", metadata, "logs")

    assert "unknown" in prompt
