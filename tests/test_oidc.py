from __future__ import annotations

import base64
import hashlib
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from cabalspy_id import (
    AsyncCabalSpyIDAuth,
    CabalSpyIDAuth,
    CabalSpyIDError,
    OAuthError,
    TokenVerificationError,
    generate_pkce,
    is_limited,
)

from .conftest import CLIENT_ID, ISSUER, REDIRECT, SECRET, Recorder, SigningKey, discovery, id_claims


def provider(id_token: str | None = None, keys=None, token_error: tuple[int, dict] | None = None) -> Recorder:
    def handler(r: httpx.Request) -> httpx.Response:
        path = r.url.path
        if path == "/.well-known/openid-configuration":
            return httpx.Response(200, json=discovery())
        if path == "/oauth/jwks":
            return httpx.Response(200, json={"keys": [k.jwk for k in keys()]})
        if path == "/oauth/token":
            if token_error:
                return httpx.Response(token_error[0], json=token_error[1])
            return httpx.Response(
                200,
                json={
                    "access_token": "at",
                    "token_type": "Bearer",
                    "expires_in": 900,
                    "id_token": id_token,
                    "scope": "openid",
                },
            )
        if path == "/oauth/userinfo":
            return httpx.Response(200, json={"sub": "user-1", "preferred_username": "alice", "wallets": []})
        if path == "/oauth/revoke":
            return httpx.Response(200, json={})
        return httpx.Response(404, json={"error": "not_found"})

    return Recorder(handler)


def form(r: httpx.Request) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(r.content.decode()).items()}


def test_authorization_url(key: SigningKey) -> None:
    rec = provider(keys=lambda: [key])
    auth = CabalSpyIDAuth(CLIENT_ID, client_secret=SECRET, redirect_uri=REDIRECT, http_client=rec.client())
    req = auth.create_authorization_url(scope=["profile", "wallets"], prompt="consent")
    parts = urlsplit(req.url)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == f"{ISSUER}/oauth/authorize"
    q = {k: v[0] for k, v in parse_qs(parts.query).items()}
    assert q["scope"] == "openid profile wallets"
    assert q["response_type"] == "code" and q["client_id"] == CLIENT_ID and q["redirect_uri"] == REDIRECT
    assert q["state"] == req.state and q["nonce"] == req.nonce and q["prompt"] == "consent"
    assert q["code_challenge_method"] == "S256"
    expected = base64.urlsafe_b64encode(hashlib.sha256(req.code_verifier.encode()).digest()).rstrip(b"=").decode()
    assert q["code_challenge"] == expected
    assert set(req.to_dict()) == {"state", "nonce", "code_verifier", "redirect_uri"}


def test_generate_pkce() -> None:
    pair = generate_pkce()
    assert len(pair.code_verifier) == 64 and len(pair.code_challenge) == 43


def test_callback_flow_with_basic_auth(key: SigningKey) -> None:
    rec = provider(id_token=key.sign(id_claims()), keys=lambda: [key])
    auth = CabalSpyIDAuth(CLIENT_ID, client_secret=SECRET, redirect_uri=REDIRECT, http_client=rec.client())
    result = auth.handle_callback(
        f"{REDIRECT}?code=abc&state=s-1&iss=https%3A%2F%2Fid.cabalspy.xyz",
        state="s-1",
        nonce="n-1",
        code_verifier="v" * 64,
    )
    assert result.claims["sub"] == "user-1"
    assert result.tokens["access_token"] == "at"
    token = next(r for r in rec.requests if r.url.path == "/oauth/token")
    assert token.headers["authorization"] == "Basic " + base64.b64encode(f"{CLIENT_ID}:{SECRET}".encode()).decode()
    assert form(token) == {
        "grant_type": "authorization_code",
        "code": "abc",
        "redirect_uri": REDIRECT,
        "code_verifier": "v" * 64,
    }


def test_client_secret_post_and_public(key: SigningKey) -> None:
    rec = provider(id_token="x", keys=lambda: [key])
    post = CabalSpyIDAuth(
        CLIENT_ID,
        client_secret=SECRET,
        token_endpoint_auth_method="client_secret_post",
        redirect_uri=REDIRECT,
        http_client=rec.client(),
    )
    post.exchange_code(code="c", code_verifier="v" * 43)
    public = CabalSpyIDAuth(CLIENT_ID, redirect_uri=REDIRECT, http_client=rec.client())
    public.exchange_code(code="c", code_verifier="v" * 43)
    a, b = [r for r in rec.requests if r.url.path == "/oauth/token"]
    assert form(a)["client_secret"] == SECRET and form(a)["client_id"] == CLIENT_ID
    assert "authorization" not in a.headers
    assert form(b)["client_id"] == CLIENT_ID and "client_secret" not in form(b)


def test_callback_checks(key: SigningKey) -> None:
    rec = provider(keys=lambda: [key])
    auth = CabalSpyIDAuth(CLIENT_ID, redirect_uri=REDIRECT, http_client=rec.client())
    with pytest.raises(OAuthError) as e:
        auth.handle_callback("?code=a&state=evil", state="s-1", nonce="n", code_verifier="v")
    assert e.value.code == "invalid_state"
    with pytest.raises(OAuthError) as e:
        auth.handle_callback(
            {"error": "access_denied", "error_description": "nope"}, state="s-1", nonce="n", code_verifier="v"
        )
    assert (e.value.error, e.value.error_description) == ("access_denied", "nope")
    with pytest.raises(OAuthError) as e:
        auth.handle_callback("?code=a&state=s-1&iss=https://evil.example", state="s-1", nonce="n", code_verifier="v")
    assert e.value.code == "invalid_issuer"
    assert not any(r.url.path == "/oauth/token" for r in rec.requests)


def test_token_endpoint_error(key: SigningKey) -> None:
    rec = provider(keys=lambda: [key], token_error=(400, {"error": "invalid_grant", "error_description": "used"}))
    auth = CabalSpyIDAuth(CLIENT_ID, client_secret=SECRET, redirect_uri=REDIRECT, http_client=rec.client())
    with pytest.raises(OAuthError) as e:
        auth.exchange_code(code="x", code_verifier="v")
    assert (e.value.status, e.value.error) == (400, "invalid_grant")


def verifier(key: SigningKey, keys=None) -> CabalSpyIDAuth:
    rec = provider(keys=keys or (lambda: [key]))
    return CabalSpyIDAuth(CLIENT_ID, http_client=rec.client())


def test_verify_valid(key: SigningKey) -> None:
    assert verifier(key).verify_id_token(key.sign(id_claims()), nonce="n-1")["preferred_username"] == "alice"


@pytest.mark.parametrize(
    ("claims", "nonce", "code"),
    [
        (id_claims(), "other", "invalid_nonce"),
        (id_claims(exp=int(time.time()) - 3600), None, "token_expired"),
        (id_claims(aud="csid_other"), None, "invalid_audience"),
        (id_claims(azp="csid_other"), None, "invalid_azp"),
        (id_claims(iss="https://evil.example"), None, "invalid_issuer"),
        (id_claims(iat=int(time.time()) + 3600), None, "invalid_iat"),
    ],
)
def test_verify_rejects(key: SigningKey, claims: dict, nonce: str | None, code: str) -> None:
    with pytest.raises(TokenVerificationError) as e:
        verifier(key).verify_id_token(key.sign(claims), nonce=nonce)
    assert e.value.code == code


def test_verify_rejects_forged_and_unknown_keys(key: SigningKey, other_key: SigningKey) -> None:
    forged = other_key.sign(id_claims(), kid="k1")
    with pytest.raises(TokenVerificationError) as e:
        verifier(key).verify_id_token(forged)
    assert e.value.code == "invalid_signature"
    with pytest.raises(TokenVerificationError) as e:
        verifier(key).verify_id_token(other_key.sign(id_claims()))
    assert e.value.code == "unknown_kid"


def test_access_token_is_not_an_id_token(key: SigningKey) -> None:
    with pytest.raises(TokenVerificationError) as e:
        verifier(key).verify_id_token(key.sign(id_claims(), typ="at+jwt"))
    assert e.value.code == "invalid_typ"


def test_limited_user(key: SigningKey) -> None:
    claims = verifier(key).verify_id_token(
        key.sign(id_claims(sub="anon_abc", preferred_username=None, limited=True, reason="plan_user_limit"))
    )
    assert claims["limited"] is True and is_limited(claims)
    assert not is_limited({"sub": "user-1"})


def test_jwks_refetch_cooldown(key: SigningKey, other_key: SigningKey) -> None:
    keys = [key]
    rec = provider(keys=lambda: keys)
    auth = CabalSpyIDAuth(CLIENT_ID, http_client=rec.client(), jwks_cooldown=0)
    auth.verify_id_token(key.sign(id_claims()))
    keys.append(other_key)  # rotation: a new kid appears
    assert auth.verify_id_token(other_key.sign(id_claims()))["sub"] == "user-1"
    assert sum(r.url.path == "/oauth/jwks" for r in rec.requests) == 2


def test_verify_access_token(key: SigningKey) -> None:
    now = int(time.time())
    at = key.sign(
        {
            "iss": ISSUER,
            "sub": "user-1",
            "aud": CLIENT_ID,
            "client_id": CLIENT_ID,
            "scope": "openid",
            "iat": now,
            "exp": now + 900,
            "jti": "j",
        },
        typ="at+jwt",
    )
    assert verifier(key).verify_access_token(at)["scope"] == "openid"
    with pytest.raises(TokenVerificationError):
        verifier(key).verify_access_token(key.sign(id_claims()))


def test_refresh_revoke_userinfo(key: SigningKey) -> None:
    rec = provider(id_token="x", keys=lambda: [key])
    auth = CabalSpyIDAuth(CLIENT_ID, client_secret=SECRET, http_client=rec.client())
    auth.refresh("csid_rt_1")
    auth.revoke("csid_rt_1")
    assert auth.userinfo("at-1")["preferred_username"] == "alice"
    refresh, revoke, userinfo = [r for r in rec.requests if "well-known" not in r.url.path]
    assert form(refresh) == {"grant_type": "refresh_token", "refresh_token": "csid_rt_1"}
    assert str(revoke.url) == f"{ISSUER}/oauth/revoke" and form(revoke) == {"token": "csid_rt_1"}
    assert userinfo.headers["authorization"] == "Bearer at-1"
    assert sum("well-known" in r.url.path for r in rec.requests) == 1  # discovery cached


def test_discovery_issuer_mismatch(key: SigningKey) -> None:
    rec = provider(keys=lambda: [key])
    with pytest.raises(TokenVerificationError):
        CabalSpyIDAuth(CLIENT_ID, issuer="https://other.example", http_client=rec.client()).discover()


def test_secret_required_for_confidential_methods() -> None:
    with pytest.raises(CabalSpyIDError):
        CabalSpyIDAuth(CLIENT_ID, token_endpoint_auth_method="client_secret_basic")


async def test_async_flow(key: SigningKey) -> None:
    rec = provider(id_token=key.sign(id_claims()), keys=lambda: [key])
    async with AsyncCabalSpyIDAuth(
        CLIENT_ID, client_secret=SECRET, redirect_uri=REDIRECT, http_client=rec.async_client()
    ) as auth:
        req = await auth.create_authorization_url()
        assert req.url.startswith(f"{ISSUER}/oauth/authorize?")
        result = await auth.handle_callback(
            f"?code=c&state={req.state}", state=req.state, nonce="n-1", code_verifier=req.code_verifier
        )
        assert result.claims["sub"] == "user-1"
        assert (await auth.userinfo("at"))["sub"] == "user-1"
