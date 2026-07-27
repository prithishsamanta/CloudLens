from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError, EndpointConnectionError, NoCredentialsError

from cloudlens.credentials import check_aws_credentials


def test_check_aws_credentials_returns_true_when_valid():
    with patch("cloudlens.credentials.boto3.client") as mock_boto_client:
        mock_sts = MagicMock()
        mock_sts.get_caller_identity.return_value = {"Account": "123456789012"}
        mock_boto_client.return_value = mock_sts

        result = check_aws_credentials("us-east-2")

    assert result is True


def test_check_aws_credentials_returns_false_when_missing():
    with patch("cloudlens.credentials.boto3.client") as mock_boto_client:
        mock_sts = MagicMock()
        mock_sts.get_caller_identity.side_effect = NoCredentialsError()
        mock_boto_client.return_value = mock_sts

        result = check_aws_credentials("us-east-2")

    assert result is False


def test_check_aws_credentials_returns_false_when_rejected():
    with patch("cloudlens.credentials.boto3.client") as mock_boto_client:
        mock_sts = MagicMock()
        mock_sts.get_caller_identity.side_effect = ClientError(
            {"Error": {"Code": "InvalidClientTokenId", "Message": "bad token"}}, "GetCallerIdentity"
        )
        mock_boto_client.return_value = mock_sts

        result = check_aws_credentials("us-east-2")

    assert result is False


def test_check_aws_credentials_returns_false_when_region_unreachable():
    with patch("cloudlens.credentials.boto3.client") as mock_boto_client:
        mock_sts = MagicMock()
        mock_sts.get_caller_identity.side_effect = EndpointConnectionError(
            endpoint_url="https://sts.us-fake-region-99.amazonaws.com/"
        )
        mock_boto_client.return_value = mock_sts

        result = check_aws_credentials("us-fake-region-99")

    assert result is False


def test_check_aws_credentials_uses_sts_in_the_given_region():
    with patch("cloudlens.credentials.boto3.client") as mock_boto_client:
        mock_sts = MagicMock()
        mock_boto_client.return_value = mock_sts

        check_aws_credentials("eu-west-1")

    mock_boto_client.assert_called_once_with("sts", region_name="eu-west-1")
