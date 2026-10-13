"""Login with CabalSpy ID: OpenID Connect helpers for servers, sync and async.

    from cabalspy_id import CabalSpyIDAuth

    auth = CabalSpyIDAuth(client_id="csid_...", client_secret="csid_sk_...",
                          redirect_uri="https://your.app/callback")

    # GET /login
    req = auth.create_authorization_url(scope=["openid", "profile", "wallets"])
    session["csid"] = req.to_dict()          # state, nonce, code_verifier
    return redirect(req.url)

    # GET /callback
    result = auth.handle_callback(request.url, **session.pop("csid"))
    result.claims["sub"]

Authorization code flow with PKCE S256 (required for every client), state and
nonce. ID tokens are ES256 JWTs, verified against the provider's JWKS.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any, Literal
from urllib.parse import parse_qs, quote, urlencode, urlsplit

import httpx
import jwt

from ._constants import DEFAULT_ISSUER, USER_AGENT
from ._errors import (
    APIConnectionError,
    CabalSpyIDError,
    InvalidResponseError,
    OAuthError,
    TokenVerificationError,
)

TokenEndpointAuthMethod = Literal["client_secret_basic", "client_secret_post", "none"]

__all__ = [
    "CabalSpyIDAuth",
    "AsyncCabalSpyIDAuth",
    "AuthorizationRequest",
    "LoginResult",
    "PkcePair",
    "generate_pkce",
    "is_limited",
]


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


@dataclass(frozen=True)
class PkcePair:
    code_verifier: str
    code_challenge: str


def generate_pkce() -> PkcePair:
    """A fresh PKCE verifier (64 chars) and its S256 challenge."""
    verifier = _b64url(secrets.token_bytes(48))
    return PkcePair(verifier, _b64url(hashlib.sha256(verifier.encode()).digest()))


@dataclass(frozen=True)
class AuthorizationRequest:
    """What to keep (server session or signed cookie) until the callback."""

    url: str
    state: str
    nonce: str
    code_verifier: str
    redirect_uri: str

    def to_dict(self) -> dict[str, str]:
        """``state``, ``nonce``, ``code_verifier`` and ``redirect_uri`` for ``handle_callback(**d)``."""
        d = asdict(self)
        d.pop("url")
        return d


@dataclass(frozen=True)
class LoginResult:
    #: The token response: access_token, id_token, expires_in, scope, refresh_token?
    tokens: dict[str, Any]
    #: Verified ID token claims. Check ``is_limited(claims)`` before using profile data.
    claims: dict[str, Any]


def is_limited(claims: Mapping[str, Any]) -> bool:
    """True when the platform is over its plan's user limit: anonymous sub, no profile data."""
    return claims.get("limited") is True or str(claims.get("sub", "")).startswith("anon_")


def _query(callback: str | Mapping[str, Any]) -> dict[str, str]:
    if isinstance(callback, Mapping):
        return {k: (v[0] if isinstance(v, (list, tuple)) else str(v)) for k, v in callback.items()}
    text = str(callback)
    if "://" in text or text.startswith("/"):
        text = urlsplit(text).query
    elif text.startswith("?"):
        text = text[1:]
    return {k: v[0] for k, v in parse_qs(text, keep_blank_values=True).items()}


def _oauth_error(response: httpx.Response, body: Any) -> OAuthError:
    if isinstance(body, dict) and isinstance(body.get("error"), str):
        return OAuthError(body["error"], body.get("error_description"), status=response.status_code, body=body)
    return OAuthError(
        f"http_{response.status_code}",
        f"HTTP {response.status_code} from {response.request.url if response.request else 'the identity provider'}",
        status=response.status_code,
        body=body,
    )


_JWT_ERRORS: list[tuple[type[Exception], str]] = [
    (jwt.ExpiredSignatureError, "token_expired"),
    (jwt.ImmatureSignatureError, "token_not_yet_valid"),
    (jwt.InvalidAudienceError, "invalid_audience"),
    (jwt.InvalidIssuerError, "invalid_issuer"),
    (jwt.InvalidIssuedAtError, "invalid_iat"),
    (jwt.MissingRequiredClaimError, "missing_claim"),
    (jwt.InvalidSignatureError, "invalid_signature"),
    (jwt.InvalidAlgorithmError, "invalid_alg"),
    (jwt.DecodeError, "malformed_token"),
]


def _map_jwt_error(exc: jwt.PyJWTError) -> TokenVerificationError:
    for cls, code in _JWT_ERRORS:
        if isinstance(exc, cls):
            return TokenVerificationError(str(exc) or code, code=code)
    return TokenVerificationError(str(exc) or "invalid token", code="invalid_token")


class _AuthBase:
    def __init__(
        self,
        client_id: str,
        *,
        client_secret: str | None = None,
        redirect_uri: str | None = None,
        issuer: str | None = None,
        token_endpoint_auth_method: TokenEndpointAuthMethod | None = None,
        clock_tolerance: int = 60,
        timeout: float = 15.0,
        jwks_cooldown: float = 60.0,
    ) -> None:
        if not client_id:
            raise CabalSpyIDError("client_id is required", code="missing_client_id")
        self.client_id = client_id
        self._client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.issuer = (issuer or os.environ.get("CABALSPY_ID_ISSUER") or DEFAULT_ISSUER).rstrip("/")
        self.auth_method: TokenEndpointAuthMethod = token_endpoint_auth_method or (
            "client_secret_basic" if client_secret else "none"
        )
        if self.auth_method != "none" and not client_secret:
            raise CabalSpyIDError(f"{self.auth_method} needs client_secret", code="missing_client_secret")
        self.clock_tolerance = clock_tolerance
        self.timeout = timeout
        self._jwks_cooldown = jwks_cooldown
        self._discovery: dict[str, Any] | None = None
        self._keys: dict[str, Any] = {}
        self._keys_loaded = 0.0

    def __repr__(self) -> str:
        return f"{type(self).__name__}(client_id={self.client_id!r}, issuer={self.issuer!r})"

    # ── pure helpers ─────────────────────────────────────────────────────

    def _check_discovery(self, doc: Any) -> dict[str, Any]:
        if not isinstance(doc, dict):
            raise InvalidResponseError("Discovery document is not JSON", code="invalid_response")
        if doc.get("issuer") != self.issuer:
            raise TokenVerificationError(
                f"Discovery issuer {doc.get('issuer')!r} does not match {self.issuer!r}", code="invalid_issuer"
            )
        return doc

    def _build_authorization(
        self,
        discovery: Mapping[str, Any],
        scope: Sequence[str] | str | None,
        redirect_uri: str | None,
        prompt: str | None,
        state: str | None,
        nonce: str | None,
        extra_params: Mapping[str, str] | None,
    ) -> AuthorizationRequest:
        redirect = redirect_uri or self.redirect_uri
        if not redirect:
            raise CabalSpyIDError("redirect_uri is required", code="missing_redirect_uri")
        scopes = scope.split() if isinstance(scope, str) else list(scope or ["openid", "profile"])
        if "openid" not in scopes:
            scopes.insert(0, "openid")
        pkce = generate_pkce()
        state = state or _b64url(secrets.token_bytes(24))
        nonce = nonce or _b64url(secrets.token_bytes(24))
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": redirect,
            "scope": " ".join(dict.fromkeys(scopes)),
            "state": state,
            "nonce": nonce,
            "code_challenge": pkce.code_challenge,
            "code_challenge_method": "S256",
        }
        if prompt:
            params["prompt"] = prompt
        params.update(extra_params or {})
        url = f"{discovery['authorization_endpoint']}?{urlencode(params, quote_via=quote)}"
        return AuthorizationRequest(url, state, nonce, pkce.code_verifier, redirect)

    def _check_callback(self, callback: str | Mapping[str, Any], state: str) -> str:
        params = _query(callback)
        if params.get("error"):
            raise OAuthError(params["error"], params.get("error_description"), status=400)
        if not state or not hmac.compare_digest(params.get("state", ""), state):
            raise OAuthError("invalid_state", "The state parameter does not match (possible CSRF).", status=400)
        iss = params.get("iss")
        if iss is not None and iss != self.issuer:
            raise OAuthError("invalid_issuer", f"Unexpected iss {iss!r} in the authorization response.", status=400)
        code = params.get("code")
        if not code:
            raise OAuthError("invalid_request", "The callback has no code.", status=400)
        return code

    def _token_request(self, params: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
        """(form, headers) with client authentication applied."""
        form = dict(params)
        headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
        if self.auth_method == "client_secret_basic":
            # RFC 6749 2.3.1: form-encode id and secret before base64.
            raw = f"{quote(self.client_id, safe='')}:{quote(self._client_secret or '', safe='')}"
            headers["Authorization"] = "Basic " + base64.b64encode(raw.encode()).decode()
        else:
            form["client_id"] = self.client_id
            if self.auth_method == "client_secret_post":
                form["client_secret"] = self._client_secret or ""
        return form, headers

    def _json(self, response: httpx.Response) -> Any:
        try:
            body = response.json() if response.content else None
        except ValueError:
            body = None
        if response.status_code >= 400:
            raise _oauth_error(response, body)
        if not isinstance(body, dict):
            raise InvalidResponseError("Expected a JSON object", status=response.status_code, code="invalid_response")
        return body

    def _load_keys(self, jwks: Any) -> None:
        keys: dict[str, Any] = {}
        for jwk in (jwks or {}).get("keys", []) if isinstance(jwks, dict) else []:
            if jwk.get("kty") != "EC" or jwk.get("crv") != "P-256" or jwk.get("alg", "ES256") != "ES256":
                continue
            try:
                keys[jwk.get("kid", "")] = jwt.PyJWK(jwk, algorithm="ES256").key
            except jwt.PyJWTError:
                continue
        self._keys = keys
        self._keys_loaded = time.monotonic()

    def _pick_key(self, kid: str | None) -> Any:
        key = self._keys.get(kid or "")
        if key is None and kid is None and len(self._keys) == 1:
            key = next(iter(self._keys.values()))
        return key

    def _needs_refetch(self, kid: str | None) -> bool:
        if not self._keys_loaded:
            return True
        return self._pick_key(kid) is None and time.monotonic() - self._keys_loaded >= self._jwks_cooldown

    @staticmethod
    def _header(token: str) -> dict[str, Any]:
        try:
            return jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise TokenVerificationError("Malformed JWT", code="malformed_token") from exc

    def _decode(
        self, token: str, header: Mapping[str, Any], *, typ: str | None, reject_typ: str | None
    ) -> dict[str, Any]:
        if header.get("alg") != "ES256":
            raise TokenVerificationError(f"Unexpected alg {header.get('alg')!r}, expected ES256", code="invalid_alg")
        if typ and header.get("typ") != typ:
            raise TokenVerificationError(
                f"Unexpected token type {header.get('typ')!r}, expected {typ!r}", code="invalid_typ"
            )
        if reject_typ and header.get("typ") == reject_typ:
            raise TokenVerificationError(f"A {reject_typ!r} token is not accepted here", code="invalid_typ")
        kid = header.get("kid")
        key = self._pick_key(kid)
        if key is None:
            raise TokenVerificationError(f"No signing key with kid {kid!r} in the JWKS", code="unknown_kid")
        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                key,
                algorithms=["ES256"],
                audience=self.client_id,
                issuer=self.issuer,
                leeway=self.clock_tolerance,
                # iat is checked below with a clearer error than PyJWT's
                options={"require": ["exp", "iat", "iss", "aud", "sub"], "verify_iat": False},
            )
        except jwt.PyJWTError as exc:
            raise _map_jwt_error(exc) from exc
        iat = claims.get("iat")
        if isinstance(iat, (int, float)) and iat - self.clock_tolerance > time.time():
            raise TokenVerificationError("Token was issued in the future (iat)", code="invalid_iat")
        return claims

    def _check_id_claims(self, claims: dict[str, Any], nonce: str | None, max_age: int | None) -> dict[str, Any]:
        if not isinstance(claims.get("sub"), str) or not claims["sub"]:
            raise TokenVerificationError("ID token has no sub", code="missing_sub")
        if "azp" in claims and claims["azp"] != self.client_id:
            raise TokenVerificationError("ID token azp does not match the client", code="invalid_azp")
        if nonce is not None:
            got = claims.get("nonce")
            if not isinstance(got, str) or not hmac.compare_digest(got, nonce):
                raise TokenVerificationError("ID token nonce does not match", code="invalid_nonce")
        if max_age is not None:
            auth_time = claims.get("auth_time")
            if not isinstance(auth_time, (int, float)) or auth_time + max_age + self.clock_tolerance < time.time():
                raise TokenVerificationError("The user authenticated too long ago (max_age)", code="auth_time_too_old")
        return claims

    def _check_access_claims(self, claims: dict[str, Any]) -> dict[str, Any]:
        if claims.get("client_id") != self.client_id:
            raise TokenVerificationError("Access token was issued to another client", code="invalid_audience")
        return claims


class CabalSpyIDAuth(_AuthBase):
    """Synchronous OpenID Connect client for "Login with CabalSpy ID"."""

    def __init__(self, client_id: str, *, http_client: httpx.Client | None = None, **kwargs: Any) -> None:
        super().__init__(client_id, **kwargs)
        self._http = http_client or httpx.Client(timeout=self.timeout)
        self._owns_http = http_client is None

    def __enter__(self) -> CabalSpyIDAuth:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def _send(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        kwargs.setdefault("headers", {"Accept": "application/json", "User-Agent": USER_AGENT})
        try:
            return self._http.request(method, url, **kwargs)
        except httpx.TimeoutException as exc:
            raise APIConnectionError(f"Request timed out: {url}", code="timeout") from exc
        except httpx.HTTPError as exc:
            raise APIConnectionError(f"Network error: {exc}", code="connection_error") from exc

    def discover(self) -> dict[str, Any]:
        """The discovery document (cached)."""
        if self._discovery is None:
            response = self._send("GET", f"{self.issuer}/.well-known/openid-configuration")
            self._discovery = self._check_discovery(self._json(response))
        return self._discovery

    def get_jwks(self) -> dict[str, Any]:
        """The provider's public signing keys."""
        result: dict[str, Any] = self._json(self._send("GET", self.discover()["jwks_uri"]))
        return result

    def create_authorization_url(
        self,
        *,
        scope: Sequence[str] | str | None = None,
        redirect_uri: str | None = None,
        prompt: Literal["none", "consent"] | None = None,
        state: str | None = None,
        nonce: str | None = None,
        extra_params: Mapping[str, str] | None = None,
    ) -> AuthorizationRequest:
        """Authorization URL with PKCE (S256), state and nonce.

        Keep ``state``, ``nonce`` and ``code_verifier`` (``req.to_dict()``) until the callback.
        """
        return self._build_authorization(self.discover(), scope, redirect_uri, prompt, state, nonce, extra_params)

    def handle_callback(
        self,
        callback: str | Mapping[str, Any],
        *,
        state: str,
        nonce: str,
        code_verifier: str,
        redirect_uri: str | None = None,
    ) -> LoginResult:
        """Completes the login on your redirect URI.

        Checks ``error``, ``state`` and ``iss``, exchanges the code and verifies
        the ID token (signature, iss, aud, exp, nonce). ``callback`` is the full
        callback URL, its query string or a mapping of its parameters.
        """
        code = self._check_callback(callback, state)
        tokens = self.exchange_code(code=code, code_verifier=code_verifier, redirect_uri=redirect_uri)
        claims = self.verify_id_token(tokens["id_token"], nonce=nonce)
        return LoginResult(tokens, claims)

    def _post(self, url: str, params: dict[str, str]) -> dict[str, Any]:
        form, headers = self._token_request(params)
        result: dict[str, Any] = self._json(self._send("POST", url, data=form, headers=headers))
        return result

    def exchange_code(self, *, code: str, code_verifier: str, redirect_uri: str | None = None) -> dict[str, Any]:
        """POST /oauth/token with grant_type=authorization_code. Returns :class:`TokenResponse`."""
        redirect = redirect_uri or self.redirect_uri
        if not redirect:
            raise CabalSpyIDError("redirect_uri is required", code="missing_redirect_uri")
        return self._post(
            self.discover()["token_endpoint"],
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect,
                "code_verifier": code_verifier,
            },
        )

    def refresh(self, refresh_token: str) -> dict[str, Any]:
        """POST /oauth/token with grant_type=refresh_token.

        Refresh tokens rotate: store the new one. Reusing an old one revokes the whole chain.
        """
        return self._post(
            self.discover()["token_endpoint"], {"grant_type": "refresh_token", "refresh_token": refresh_token}
        )

    def revoke(self, token: str) -> None:
        """POST /oauth/revoke (RFC 7009). Revoking a refresh token ends its chain."""
        self._post(self.discover()["revocation_endpoint"], {"token": token})

    def userinfo(self, access_token: str) -> dict[str, Any]:
        """GET /oauth/userinfo — claims for the token's scopes (x, wallets, onchain ...)."""
        headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json", "User-Agent": USER_AGENT}
        result: dict[str, Any] = self._json(self._send("GET", self.discover()["userinfo_endpoint"], headers=headers))
        return result

    def _ensure_key(self, kid: str | None) -> None:
        if self._needs_refetch(kid):
            self._load_keys(self.get_jwks())

    def verify_id_token(self, id_token: str, *, nonce: str | None = None, max_age: int | None = None) -> dict[str, Any]:
        """Verifies an ID token: ES256 signature (JWKS), iss, aud, azp, exp, iat, nonce.

        Use it for tokens from your own callback and for ``idToken`` sent from
        the browser widget. Limited users (over the plan's user limit) have an
        ``anon_...`` sub and ``limited: True``; see :func:`is_limited`.
        """
        header = self._header(id_token)
        self._ensure_key(header.get("kid"))
        claims = self._decode(id_token, header, typ=None, reject_typ="at+jwt")
        return self._check_id_claims(claims, nonce, max_age)

    def verify_access_token(self, access_token: str) -> dict[str, Any]:
        """Verifies a CabalSpy ID access token (typ at+jwt) issued to this client."""
        header = self._header(access_token)
        self._ensure_key(header.get("kid"))
        return self._check_access_claims(self._decode(access_token, header, typ="at+jwt", reject_typ=None))


class AsyncCabalSpyIDAuth(_AuthBase):
    """Asynchronous OpenID Connect client; same methods as :class:`CabalSpyIDAuth`."""

    def __init__(self, client_id: str, *, http_client: httpx.AsyncClient | None = None, **kwargs: Any) -> None:
        super().__init__(client_id, **kwargs)
        self._http = http_client or httpx.AsyncClient(timeout=self.timeout)
        self._owns_http = http_client is None

    async def __aenter__(self) -> AsyncCabalSpyIDAuth:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def _send(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        kwargs.setdefault("headers", {"Accept": "application/json", "User-Agent": USER_AGENT})
        try:
            return await self._http.request(method, url, **kwargs)
        except httpx.TimeoutException as exc:
            raise APIConnectionError(f"Request timed out: {url}", code="timeout") from exc
        except httpx.HTTPError as exc:
            raise APIConnectionError(f"Network error: {exc}", code="connection_error") from exc

    async def discover(self) -> dict[str, Any]:
        if self._discovery is None:
            response = await self._send("GET", f"{self.issuer}/.well-known/openid-configuration")
            self._discovery = self._check_discovery(self._json(response))
        return self._discovery

    async def get_jwks(self) -> dict[str, Any]:
        result: dict[str, Any] = self._json(await self._send("GET", (await self.discover())["jwks_uri"]))
        return result

    async def create_authorization_url(
        self,
        *,
        scope: Sequence[str] | str | None = None,
        redirect_uri: str | None = None,
        prompt: Literal["none", "consent"] | None = None,
        state: str | None = None,
        nonce: str | None = None,
        extra_params: Mapping[str, str] | None = None,
    ) -> AuthorizationRequest:
        return self._build_authorization(await self.discover(), scope, redirect_uri, prompt, state, nonce, extra_params)

    async def handle_callback(
        self,
        callback: str | Mapping[str, Any],
        *,
        state: str,
        nonce: str,
        code_verifier: str,
        redirect_uri: str | None = None,
    ) -> LoginResult:
        code = self._check_callback(callback, state)
        tokens = await self.exchange_code(code=code, code_verifier=code_verifier, redirect_uri=redirect_uri)
        claims = await self.verify_id_token(tokens["id_token"], nonce=nonce)
        return LoginResult(tokens, claims)

    async def _post(self, url: str, params: dict[str, str]) -> dict[str, Any]:
        form, headers = self._token_request(params)
        result: dict[str, Any] = self._json(await self._send("POST", url, data=form, headers=headers))
        return result

    async def exchange_code(self, *, code: str, code_verifier: str, redirect_uri: str | None = None) -> dict[str, Any]:
        redirect = redirect_uri or self.redirect_uri
        if not redirect:
            raise CabalSpyIDError("redirect_uri is required", code="missing_redirect_uri")
        return await self._post(
            (await self.discover())["token_endpoint"],
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect,
                "code_verifier": code_verifier,
            },
        )

    async def refresh(self, refresh_token: str) -> dict[str, Any]:
        return await self._post(
            (await self.discover())["token_endpoint"], {"grant_type": "refresh_token", "refresh_token": refresh_token}
        )

    async def revoke(self, token: str) -> None:
        await self._post((await self.discover())["revocation_endpoint"], {"token": token})

    async def userinfo(self, access_token: str) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json", "User-Agent": USER_AGENT}
        result: dict[str, Any] = self._json(
            await self._send("GET", (await self.discover())["userinfo_endpoint"], headers=headers)
        )
        return result

    async def _ensure_key(self, kid: str | None) -> None:
        if self._needs_refetch(kid):
            self._load_keys(await self.get_jwks())

    async def verify_id_token(
        self, id_token: str, *, nonce: str | None = None, max_age: int | None = None
    ) -> dict[str, Any]:
        header = self._header(id_token)
        await self._ensure_key(header.get("kid"))
        claims = self._decode(id_token, header, typ=None, reject_typ="at+jwt")
        return self._check_id_claims(claims, nonce, max_age)

    async def verify_access_token(self, access_token: str) -> dict[str, Any]:
        header = self._header(access_token)
        await self._ensure_key(header.get("kid"))
        return self._check_access_claims(self._decode(access_token, header, typ="at+jwt", reject_typ=None))
