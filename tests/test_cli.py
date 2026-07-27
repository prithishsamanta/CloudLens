from unittest.mock import patch

from click.testing import CliRunner

from cloudlens.bedrock import BedrockError
from cloudlens.cli import main
from cloudlens.fetcher import FetchError


def _run(args):
    runner = CliRunner()
    return runner.invoke(main, ["diagnose"] + args)


def test_diagnose_exits_cleanly_when_no_credentials():
    with patch("cloudlens.cli.check_aws_credentials", return_value=False):
        result = _run(["--log-group", "/aws/lambda/my-fn"])

    assert result.exit_code == 1


def test_diagnose_exits_cleanly_on_invalid_last():
    with patch("cloudlens.cli.check_aws_credentials", return_value=True), \
         patch("cloudlens.cli.fetch_all_data", side_effect=ValueError("Invalid --last value")):
        result = _run(["--log-group", "/aws/lambda/my-fn", "--last", "not-a-window"])

    assert result.exit_code == 1
    assert "--last" in result.output or "Invalid" in result.output


def test_diagnose_exits_cleanly_on_fetch_error():
    with patch("cloudlens.cli.check_aws_credentials", return_value=True), \
         patch("cloudlens.cli.fetch_all_data", side_effect=FetchError("Could not reach CloudWatch Logs")):
        result = _run(["--log-group", "/aws/lambda/my-fn"])

    assert result.exit_code == 1
    assert "Could not reach CloudWatch Logs" in result.output


def test_diagnose_exits_cleanly_when_log_group_does_not_exist():
    fake_data = {
        "metadata": {"log_group": "/aws/lambda/my-fn", "region": "us-east-2", "exists": False},
        "log_text": "",
        "total_events": 0,
    }
    with patch("cloudlens.cli.check_aws_credentials", return_value=True), \
         patch("cloudlens.cli.fetch_all_data", return_value=fake_data):
        result = _run(["--log-group", "/aws/lambda/my-fn"])

    assert result.exit_code == 1
    assert "does not exist" in result.output


def test_diagnose_exits_cleanly_on_bedrock_access_denied():
    fake_data = {
        "metadata": {"log_group": "/aws/lambda/my-fn", "region": "us-east-2", "exists": True},
        "log_text": "some real log line",
        "total_events": 1,
    }
    with patch("cloudlens.cli.check_aws_credentials", return_value=True), \
         patch("cloudlens.cli.fetch_all_data", return_value=fake_data), \
         patch("cloudlens.cli.analyze_logs", side_effect=BedrockError("AWS rejected the request to Amazon Bedrock (AccessDeniedException).")):
        result = _run(["--log-group", "/aws/lambda/my-fn"])

    assert result.exit_code == 1
    assert "AccessDeniedException" in result.output
    assert "Model access" in result.output


def test_diagnose_exits_cleanly_when_report_port_in_use():
    fake_data = {
        "metadata": {"log_group": "/aws/lambda/my-fn", "region": "us-east-2", "exists": True},
        "log_text": "",
        "total_events": 0,
    }
    with patch("cloudlens.cli.check_aws_credentials", return_value=True), \
         patch("cloudlens.cli.fetch_all_data", return_value=fake_data), \
         patch("cloudlens.cli.render_web") as mock_render_web:
        from cloudlens.webserver import PortInUseError
        mock_render_web.side_effect = PortInUseError("Port 8000 is already in use by something else on this machine.")

        result = _run(["--log-group", "/aws/lambda/my-fn", "--output", "web"])

    assert result.exit_code == 1
    assert "already in use" in result.output


def test_diagnose_proceeds_normally_when_log_group_exists():
    fake_data = {
        "metadata": {"log_group": "/aws/lambda/my-fn", "region": "us-east-2", "exists": True},
        "log_text": "",
        "total_events": 0,
    }
    with patch("cloudlens.cli.check_aws_credentials", return_value=True), \
         patch("cloudlens.cli.fetch_all_data", return_value=fake_data), \
         patch("cloudlens.cli.render_terminal") as mock_render:
        result = _run(["--log-group", "/aws/lambda/my-fn"])

    assert result.exit_code == 0
    mock_render.assert_called_once()
