import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from cloudlens.fetcher import (
    FetchError,
    _filter_log_events,
    _insights_query,
    describe_log_group,
    fetch_all_data,
    parse_time_window,
    query_log_events,
)


def _client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "boom"}}, "DescribeLogGroups")


# --- parse_time_window: pure logic, no AWS involved ---

def test_parse_time_window_defaults_to_1h():
    before = int(time.time()) - 3600
    result = parse_time_window()
    assert abs(result - before) < 5


@pytest.mark.parametrize("last,seconds", [("15m", 900), ("30m", 1800), ("1h", 3600), ("6h", 21600), ("24h", 86400)])
def test_parse_time_window_relative(last, seconds):
    expected = int(time.time()) - seconds
    result = parse_time_window(last=last)
    assert abs(result - expected) < 5


def test_parse_time_window_since_overrides_last():
    since = "2026-01-01T00:00:00"
    result = parse_time_window(last="24h", since=since)
    expected = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp())
    assert result == expected


def test_parse_time_window_invalid_last_raises():
    with pytest.raises(ValueError):
        parse_time_window(last="not-a-window")


# --- describe_log_group: moto-backed ---

@mock_aws
def test_describe_log_group_found():
    logs_client = boto3.client("logs", region_name="us-east-2")
    logs_client.create_log_group(logGroupName="/aws/lambda/my-fn")

    metadata = describe_log_group("/aws/lambda/my-fn", "us-east-2")

    assert metadata["log_group"] == "/aws/lambda/my-fn"
    assert metadata["region"] == "us-east-2"
    assert "retention_in_days" in metadata


@mock_aws
def test_describe_log_group_not_found_returns_exists_false():
    metadata = describe_log_group("/aws/lambda/does-not-exist", "us-east-2")

    assert metadata == {"log_group": "/aws/lambda/does-not-exist", "region": "us-east-2", "exists": False}


def test_describe_log_group_raises_fetch_error_on_client_error():
    with patch("cloudlens.fetcher.boto3.client") as mock_boto_client:
        mock_client = MagicMock()
        mock_client.describe_log_groups.side_effect = _client_error("AccessDeniedException")
        mock_boto_client.return_value = mock_client

        with pytest.raises(FetchError):
            describe_log_group("/aws/lambda/my-fn", "us-east-2")


# --- _filter_log_events: moto-backed, exercises real pagination shape ---

@mock_aws
def test_filter_log_events_returns_real_events():
    logs_client = boto3.client("logs", region_name="us-east-2")
    logs_client.create_log_group(logGroupName="/aws/ec2/my-instance")
    logs_client.create_log_stream(logGroupName="/aws/ec2/my-instance", logStreamName="stream-1")

    now_ms = int(time.time() * 1000)
    logs_client.put_log_events(
        logGroupName="/aws/ec2/my-instance",
        logStreamName="stream-1",
        logEvents=[
            {"timestamp": now_ms, "message": "INFO: started"},
            {"timestamp": now_ms + 1000, "message": "ERROR: disk full"},
        ],
    )

    start_time = int(time.time()) - 3600
    end_time = int(time.time()) + 60
    events = _filter_log_events(logs_client, "/aws/ec2/my-instance", start_time, end_time, error_only=False)

    assert len(events) == 2
    messages = [e["message"] for e in events]
    assert "INFO: started" in messages
    assert "ERROR: disk full" in messages


# --- query_log_events: verifies the Insights -> FilterLogEvents fallback wiring ---

def test_query_log_events_falls_back_when_insights_returns_nothing():
    fake_events = [{"timestamp": 1, "timestamp_readable": "x", "message": "ERROR: boom", "streamName": "s"}]

    with patch("cloudlens.fetcher._insights_query", return_value=[]) as mock_insights, \
         patch("cloudlens.fetcher._filter_log_events", return_value=fake_events) as mock_filter, \
         patch("cloudlens.fetcher.boto3.client"):
        events = query_log_events("/aws/lambda/my-fn", "us-east-2", last="1h")

    mock_insights.assert_called_once()
    mock_filter.assert_called_once()
    assert events == fake_events


def test_query_log_events_skips_fallback_when_insights_has_results():
    fake_events = [{"timestamp": 1, "timestamp_readable": "x", "message": "ERROR: boom", "streamName": "s"}]

    with patch("cloudlens.fetcher._insights_query", return_value=fake_events) as mock_insights, \
         patch("cloudlens.fetcher._filter_log_events") as mock_filter, \
         patch("cloudlens.fetcher.boto3.client"):
        events = query_log_events("/aws/lambda/my-fn", "us-east-2", last="1h")

    mock_insights.assert_called_once()
    mock_filter.assert_not_called()
    assert events == fake_events


def test_query_log_events_raises_fetch_error_on_client_error():
    with patch("cloudlens.fetcher._insights_query", side_effect=_client_error("AccessDeniedException")), \
         patch("cloudlens.fetcher.boto3.client"):
        with pytest.raises(FetchError):
            query_log_events("/aws/lambda/my-fn", "us-east-2", last="1h")


def test_query_log_events_propagates_invalid_last_uncaught():
    with pytest.raises(ValueError):
        query_log_events("/aws/lambda/my-fn", "us-east-2", last="not-a-window")


# --- error_only filter pattern construction ---

def test_filter_log_events_builds_error_pattern_when_error_only():
    mock_client = MagicMock()
    mock_client.filter_log_events.return_value = {"events": []}

    _filter_log_events(mock_client, "/aws/lambda/my-fn", 0, 100, error_only=True)

    call_kwargs = mock_client.filter_log_events.call_args.kwargs
    assert "filterPattern" in call_kwargs
    assert '"ERROR"' in call_kwargs["filterPattern"]
    assert '"FATAL"' in call_kwargs["filterPattern"]


def test_filter_log_events_no_pattern_when_not_error_only():
    mock_client = MagicMock()
    mock_client.filter_log_events.return_value = {"events": []}

    _filter_log_events(mock_client, "/aws/lambda/my-fn", 0, 100, error_only=False)

    call_kwargs = mock_client.filter_log_events.call_args.kwargs
    assert "filterPattern" not in call_kwargs


# --- fetch_all_data: end-to-end wiring with mocked pieces ---

def test_fetch_all_data_combines_metadata_and_log_text():
    fake_events = [
        {"timestamp": 1, "timestamp_readable": "2026-01-01 00:00:00", "message": "ERROR: boom", "streamName": "s"},
        {"timestamp": 2, "timestamp_readable": "2026-01-01 00:00:01", "message": "  ", "streamName": "s"},
    ]

    with patch("cloudlens.fetcher.describe_log_group", return_value={"log_group": "/aws/lambda/my-fn", "region": "us-east-2"}), \
         patch("cloudlens.fetcher.query_log_events", return_value=fake_events):
        result = fetch_all_data("/aws/lambda/my-fn", "us-east-2", last="1h")

    assert result["total_events"] == 2
    assert "ERROR: boom" in result["log_text"]
    # blank-message events are dropped from the assembled log text
    assert result["log_text"].count("\n") == 0
    assert result["metadata"]["log_group"] == "/aws/lambda/my-fn"
