from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from jwt.algorithms import ECAlgorithm

ISSUER = "https://id.cabalspy.xyz"
CLIENT_ID = "csid_testclient"
SECRET = "csid_sk_testsecret"
REDIRECT = "https://app.example.com/callback"

META = {
    "request_id": "req_test",
    "cached": False,
    "cache_age_seconds": 0,
    "version": "v1",
    "timestamp": "2026-10-13T00:00:00Z",
}
RATE = {"X-RateLimit-Limit": "10", "X-RateLimit-Remaining": "9", "X-RateLimit-Reset": "1"}


def ok(data: Any, **extra: Any) -> httpx.Response:
    return httpx.Response(200, json={"success": True, "data": data, **extra, "meta": META}, headers=RATE)


def api_error(
    status: int, code: str, message: str | None = None, headers: dict[str, str] | None = None, **extra: Any
) -> httpx.Response:
    body = {
        "success": False,
        "error": {
            "code": code,
            "message": message or code,
            "request_id": "req_err",
            "docs": f"https://docs.cabalspy.xyz/cabalspy-id/errors#{code}",
            **extra,
        },
    }
    return httpx.Response(status, json=body, headers=headers or {})


class Recorder:
    """httpx transport that records requests and answers through a handler."""

    def __init__(self, handler: Callable[[httpx.Request], httpx.Response]) -> None:
        self.handler = handler
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        request.read()
        self.requests.append(request)
        return self.handler(request)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))

    def async_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self))


class SigningKey:
    def __init__(self, kid: str) -> None:
        self.kid = kid
        self.private = ec.generate_private_key(ec.SECP256R1())
        jwk = json.loads(ECAlgorithm.to_jwk(self.private.public_key()))
        self.jwk = {**jwk, "kid": kid, "alg": "ES256", "use": "sig"}

    def sign(self, payload: dict[str, Any], **header: Any) -> str:
        headers = {"kid": self.kid, "typ": "JWT", **header}
        return jwt.encode(payload, self.private, algorithm="ES256", headers=headers)


@pytest.fixture(scope="session")
def key() -> SigningKey:
    return SigningKey("k1")


@pytest.fixture(scope="session")
def other_key() -> SigningKey:
    return SigningKey("k-other")


def discovery(issuer: str = ISSUER) -> dict[str, Any]:
    return {
        "issuer": issuer,
        "authorization_endpoint": f"{issuer}/oauth/authorize",
        "token_endpoint": f"{issuer}/oauth/token",
        "userinfo_endpoint": f"{issuer}/oauth/userinfo",
        "jwks_uri": f"{issuer}/oauth/jwks",
        "revocation_endpoint": f"{issuer}/oauth/revoke",
        "id_token_signing_alg_values_supported": ["ES256"],
        "code_challenge_methods_supported": ["S256"],
    }


def id_claims(**extra: Any) -> dict[str, Any]:
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "sub": "user-1",
        "aud": CLIENT_ID,
        "azp": CLIENT_ID,
        "iat": now,
        "exp": now + 900,
        "nonce": "n-1",
        "preferred_username": "alice",
    }
    claims.update(extra)
    return {k: v for k, v in claims.items() if v is not None}
