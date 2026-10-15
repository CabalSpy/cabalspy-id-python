"""Live checks against the public CabalSpy ID endpoints. No API key needed.

Run with: pytest -m live
"""

from __future__ import annotations

import base64
import json

import pytest

from cabalspy_id import (
    AsyncCabalSpyID,
    AuthenticationError,
    CabalSpyID,
    CabalSpyIDAuth,
    CabalSpyIDError,
    PermissionError,
    TokenVerificationError,
)

pytestmark = pytest.mark.live


def test_health() -> None:
    with CabalSpyID("") as csid:
        health = csid.health()
    assert health["status"] in ("ok", "degraded")
    assert "trade_sync_age_seconds" in health


def test_missing_key_maps_to_authentication_error() -> None:
    with CabalSpyID("") as csid, pytest.raises(AuthenticationError) as e:
        csid.get_raw("/me", auth=False)
    assert e.value.status == 401 and e.value.code == "missing_api_key"
    assert e.value.docs == "https://docs.cabalspy.xyz/cabalspy-id/errors#missing_api_key"
    assert (e.value.request_id or "").startswith("req_")


def test_invalid_key_maps_to_permission_error() -> None:
    with CabalSpyID("csid_api_not_a_real_key", max_retries=0) as csid, pytest.raises(PermissionError) as e:
        csid.me()
    assert e.value.code == "invalid_api_key"


async def test_stream_refuses_an_invalid_key() -> None:
    async with AsyncCabalSpyID("csid_api_not_a_real_key") as csid:
        stream = csid.stream(reconnect=False)
        with pytest.raises(PermissionError) as e:
            await stream.connect()
        await stream.close()
    assert e.value.code == "invalid_api_key"


def test_discovery_and_jwks() -> None:
    with CabalSpyIDAuth("csid_live_test", redirect_uri="https://example.com/cb") as auth:
        d = auth.discover()
        assert d["issuer"] == "https://id.cabalspy.xyz"
        assert "ES256" in d["id_token_signing_alg_values_supported"]
        assert "S256" in d["code_challenge_methods_supported"]
        assert {"openid", "profile", "wallets", "onchain", "offline_access"} <= set(d["scopes_supported"])

        jwks = auth.get_jwks()
        assert jwks["keys"]
        for k in jwks["keys"]:
            assert (k["kty"], k["crv"], k["alg"]) == ("EC", "P-256", "ES256")

        # A token with a real kid and a zero signature fails on the signature:
        # proves the published key imported and verification runs.
        def enc(o: object) -> str:
            return base64.urlsafe_b64encode(json.dumps(o).encode()).rstrip(b"=").decode()

        fake = ".".join(
            [
                enc({"alg": "ES256", "kid": jwks["keys"][0]["kid"], "typ": "JWT"}),
                enc(
                    {"sub": "x", "iss": "https://id.cabalspy.xyz", "aud": "csid_live_test", "iat": 1, "exp": 9999999999}
                ),
                base64.urlsafe_b64encode(bytes(64)).rstrip(b"=").decode(),
            ]
        )
        with pytest.raises(TokenVerificationError) as e:
            auth.verify_id_token(fake)
        assert e.value.code == "invalid_signature"

        req = auth.create_authorization_url()
        assert req.url.startswith("https://id.cabalspy.xyz/oauth/authorize?")


WSOL = "So11111111111111111111111111111111111111112"
#: Public client_id of the CabalSpy ID playground instance (not a secret).
PLAYGROUND_CLIENT_ID = "csid_a97b0c26eccf6f41d5e3a99b"


def test_public_theses() -> None:
    from cabalspy_id import BadRequestError, ThesisClient

    with ThesisClient(client_id=PLAYGROUND_CLIENT_ID) as tc:
        page = tc.list("solana", WSOL, limit=2)
        assert isinstance(page.items, list)
        assert page.token["mint"] == WSOL
        assert isinstance(page.summary["theses"], int)
        assert tc.summary("solana", WSOL)["token"]["mint"] == WSOL
        with pytest.raises(BadRequestError):
            tc.summary("solana", "not-a-mint")
    with ThesisClient("not-a-token", client_id=PLAYGROUND_CLIENT_ID) as tc, pytest.raises(AuthenticationError):
        tc.me("solana", WSOL)


def test_data_api_theses_needs_a_key() -> None:
    with CabalSpyID("") as csid, pytest.raises(AuthenticationError):
        csid.get_raw("/theses", {"blockchain": "solana", "mint": WSOL}, auth=False)


async def test_public_live_socket_opens() -> None:
    from cabalspy_id import AsyncThesisClient

    async with AsyncThesisClient(client_id=PLAYGROUND_CLIENT_ID) as tc:
        live = tc.live("solana", WSOL, reconnect=False)
        await live.connect()
        assert live.connected
        await live.close()


async def test_theses_stream_refuses_an_invalid_key() -> None:
    async with AsyncCabalSpyID("csid_api_not_a_real_key") as csid:
        ts = csid.theses_stream(reconnect=False)
        with pytest.raises(CabalSpyIDError) as e:
            await ts.connect()
        await ts.close()
    # Refused in the stream (invalid_api_key) or, while the proxy does not upgrade
    # this path, already at the HTTP handshake (ws_error).
    assert e.value.code in ("invalid_api_key", "ws_error", "ws_closed_early")


def test_public_scope_global() -> None:
    from cabalspy_id import ThesisClient

    with ThesisClient(client_id=PLAYGROUND_CLIENT_ID, scope="global") as tc:
        assert isinstance(tc.summary("solana", WSOL)["theses"], int)


def test_notifications_need_a_valid_token() -> None:
    from cabalspy_id import ThesisClient

    with ThesisClient("not-a-token", client_id=PLAYGROUND_CLIENT_ID) as tc, pytest.raises(AuthenticationError):
        tc.notifications()
