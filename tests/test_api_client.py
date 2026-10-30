import pytest
from engine.config import config
from engine.api_client import api_client


def test_bearer_token_attachment():
    config.BOT_ACCESS_TOKEN = "test_secret_jwt_token_12345"
    headers = api_client._headers(require_auth=True)
    assert "Authorization" in headers
    assert headers["Authorization"] == "Bearer test_secret_jwt_token_12345"
    assert headers["Content-Type"] == "application/json"


def test_masked_token_does_not_expose_secret():
    config.BOT_ACCESS_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.super_confidential_secret"
    masked = config.masked_token
    assert "super_confidential_secret" not in masked
    assert masked.startswith("eyJhbG")
    assert masked.endswith("cret")


def test_rate_limiter():
    limiter = api_client.rate_limiter
    # Can acquire rapidly without blocking up to limit
    acquired = limiter.acquire()
    assert acquired is True

