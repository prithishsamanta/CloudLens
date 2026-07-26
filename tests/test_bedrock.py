import json
from unittest.mock import patch

import pytest
from botocore.exceptions import ClientError

from cloudlens import bedrock


def _converse_response(text: str, input_tokens: int = 100, output_tokens: int = 50) -> dict:
    return {
        "output": {"message": {"content": [{"text": text}]}},
        "usage": {"inputTokens": input_tokens, "outputTokens": output_tokens},
    }


def _client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "boom"}}, "Converse")


VALID_DIAGNOSIS_JSON = json.dumps({
    "summary": "All good",
    "overall_health": "healthy",
    "errors": [],
})


# --- _sanitize_json_string ---

def test_sanitize_json_string_escapes_literal_newlines_inside_strings():
    raw = '{"a": "line one\nline two"}'
    sanitized = bedrock._sanitize_json_string(raw)
    assert json.loads(sanitized) == {"a": "line one\nline two"}


def test_sanitize_json_string_leaves_structure_whitespace_alone():
    raw = '{\n  "a": "b"\n}'
    sanitized = bedrock._sanitize_json_string(raw)
    assert json.loads(sanitized) == {"a": "b"}


# --- _extract_text ---

def test_extract_text_strips_markdown_fence():
    response = _converse_response("```json\n" + VALID_DIAGNOSIS_JSON + "\n```")
    text = bedrock._extract_text(response)
    assert json.loads(text) == json.loads(VALID_DIAGNOSIS_JSON)


def test_extract_text_passes_through_plain_json():
    response = _converse_response(VALID_DIAGNOSIS_JSON)
    text = bedrock._extract_text(response)
    assert json.loads(text) == json.loads(VALID_DIAGNOSIS_JSON)


# --- analyze_logs ---

def test_analyze_logs_happy_path():
    with patch.object(bedrock, "bedrock_client") as mock_client:
        mock_client.converse.return_value = _converse_response(VALID_DIAGNOSIS_JSON)
        result = bedrock.analyze_logs("lambda", {"log_group": "/aws/lambda/fn"}, "some logs")

    assert result["overall_health"] == "healthy"
    mock_client.converse.assert_called_once()


def test_analyze_logs_retries_on_throttling_then_succeeds():
    with patch.object(bedrock, "bedrock_client") as mock_client, patch("cloudlens.bedrock.time.sleep"):
        mock_client.converse.side_effect = [
            _client_error("ThrottlingException"),
            _converse_response(VALID_DIAGNOSIS_JSON),
        ]
        result = bedrock.analyze_logs("lambda", {"log_group": "/aws/lambda/fn"}, "some logs")

    assert result["overall_health"] == "healthy"
    assert mock_client.converse.call_count == 2


def test_analyze_logs_truncates_and_retries_on_validation_error_for_long_logs():
    long_log_text = "x" * (bedrock.MAX_LOG_CHARS + 1000)

    with patch.object(bedrock, "bedrock_client") as mock_client:
        mock_client.converse.side_effect = [
            _client_error("ValidationException"),
            _converse_response(VALID_DIAGNOSIS_JSON),
        ]
        result = bedrock.analyze_logs("lambda", {"log_group": "/aws/lambda/fn"}, long_log_text)

    assert result["overall_health"] == "healthy"
    assert mock_client.converse.call_count == 2
    # second call's prompt should be built from the truncated log text
    second_call_prompt = mock_client.converse.call_args.kwargs["messages"][0]["content"][0]["text"]
    assert len(second_call_prompt) < len(long_log_text) + 2000


def test_analyze_logs_raises_validation_error_when_logs_not_actually_long():
    with patch.object(bedrock, "bedrock_client") as mock_client:
        mock_client.converse.side_effect = _client_error("ValidationException")

        with pytest.raises(ClientError):
            bedrock.analyze_logs("lambda", {"log_group": "/aws/lambda/fn"}, "short logs")


def test_analyze_logs_retries_with_higher_max_tokens_on_truncated_json():
    with patch.object(bedrock, "bedrock_client") as mock_client:
        mock_client.converse.side_effect = [
            _converse_response('{"summary": "cut off mid-strin'),  # truncated/invalid JSON
            _converse_response(VALID_DIAGNOSIS_JSON),
        ]
        result = bedrock.analyze_logs("lambda", {"log_group": "/aws/lambda/fn"}, "some logs")

    assert result["overall_health"] == "healthy"
    assert mock_client.converse.call_count == 2
    second_call_max_tokens = mock_client.converse.call_args.kwargs["inferenceConfig"]["maxTokens"]
    assert second_call_max_tokens > bedrock.DEFAULT_MAX_TOKENS


def test_analyze_logs_gives_up_after_repeated_truncation():
    # max_tokens doubles from DEFAULT_MAX_TOKENS to MAX_TOKENS_CAP after one
    # retry, so the "max_tokens < MAX_TOKENS_CAP" guard stops it after 2
    # calls rather than exhausting all THROTTLE_RETRIES attempts.
    with patch.object(bedrock, "bedrock_client") as mock_client:
        mock_client.converse.return_value = _converse_response('{"summary": "still cut off')

        with pytest.raises(json.JSONDecodeError):
            bedrock.analyze_logs("lambda", {"log_group": "/aws/lambda/fn"}, "some logs")

    assert mock_client.converse.call_count == 2


def test_analyze_logs_raises_non_retryable_client_error():
    with patch.object(bedrock, "bedrock_client") as mock_client:
        mock_client.converse.side_effect = _client_error("AccessDeniedException")

        with pytest.raises(ClientError):
            bedrock.analyze_logs("lambda", {"log_group": "/aws/lambda/fn"}, "some logs")


# --- chat_reply ---

def test_chat_reply_happy_path_no_warning():
    with patch.object(bedrock, "bedrock_client") as mock_client:
        mock_client.converse.return_value = _converse_response("Here's how to fix it.", 1000, 200)
        result = bedrock.chat_reply("lambda", {"log_group": "/aws/lambda/fn"}, "logs", {"summary": "ok"}, [], "how do I fix it?")

    assert result["reply"] == "Here's how to fix it."
    assert result["warning"] is None


def test_chat_reply_includes_history_in_messages():
    with patch.object(bedrock, "bedrock_client") as mock_client:
        mock_client.converse.return_value = _converse_response("follow-up answer")
        bedrock.chat_reply(
            "lambda", {"log_group": "/aws/lambda/fn"}, "logs", {"summary": "ok"},
            history=["first question", "first answer"],
            user_message="second question",
        )

    messages = mock_client.converse.call_args.kwargs["messages"]
    assert len(messages) == 3
    assert messages[0] == {"role": "user", "content": [{"text": "first question"}]}
    assert messages[1] == {"role": "assistant", "content": [{"text": "first answer"}]}
    assert messages[2] == {"role": "user", "content": [{"text": "second question"}]}


def test_chat_reply_warns_when_approaching_context_limit():
    near_limit = bedrock.CHAT_WARN_THRESHOLD + 100
    with patch.object(bedrock, "bedrock_client") as mock_client:
        mock_client.converse.return_value = _converse_response("answer", input_tokens=near_limit, output_tokens=0)
        result = bedrock.chat_reply("lambda", {"log_group": "/aws/lambda/fn"}, "logs", {}, [], "question")

    assert result["warning"] is not None
    assert "getting long" in result["warning"]


def test_chat_reply_blocked_on_validation_error():
    with patch.object(bedrock, "bedrock_client") as mock_client:
        mock_client.converse.side_effect = _client_error("ValidationException")
        result = bedrock.chat_reply("lambda", {"log_group": "/aws/lambda/fn"}, "logs", {}, [], "question")

    assert result["reply"] is None
    assert "run out of room" in result["warning"]


def test_chat_reply_retries_on_throttling():
    with patch.object(bedrock, "bedrock_client") as mock_client, patch("cloudlens.bedrock.time.sleep"):
        mock_client.converse.side_effect = [
            _client_error("ThrottlingException"),
            _converse_response("answer after retry"),
        ]
        result = bedrock.chat_reply("lambda", {"log_group": "/aws/lambda/fn"}, "logs", {}, [], "question")

    assert result["reply"] == "answer after retry"
    assert mock_client.converse.call_count == 2
