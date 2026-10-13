"""Public thesis API: https://id.cabalspy.xyz/thesis/v1 (no API key).

Reading needs nothing. Writing uses the signed-in user's CabalSpy ID access
token with the scope "thesis" (``result.tokens["access_token"]`` after login).

    from cabalspy_id import ThesisClient

    theses = ThesisClient(access_token=tokens["access_token"])
    page = theses.list("solana", mint, sort="top")
    if theses.me("solana", mint)["can_post"]:
        theses.post("solana", mint, body="Strong community, still early.", stance="bull")

Live updates for one token (async, needs the ``stream`` extra):

    live = AsyncThesisClient().live("solana", mint)
    live.on("thesis", print)
    await live.connect()
    await live.run_forever()
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import random
from collections.abc import AsyncIterator, Callable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlencode

import httpx

from ._constants import (
    CHAINS,
    DEFAULT_THESIS_URL,
    DEFAULT_THESIS_WS_URL,
    THESIS_EMOJIS,
    THESIS_REPORT_REASONS,
    USER_AGENT,
    Chain,
    ThesisEmoji,
    ThesisReportReason,
    ThesisScope,
    ThesisSort,
    ThesisStance,
)
from ._errors import (
    APIConnectionError,
    AuthenticationError,
    BadRequestError,
    CabalSpyIDError,
    InvalidResponseError,
    PermissionError_,
    RateLimit,
    error_from_status,
)

__all__ = ["ThesisClient", "AsyncThesisClient", "ThesisLive", "TokenThesesPage", "ThesisPage", "LIVE_EVENTS"]

#: Events of the public live socket.
LIVE_EVENTS = ("thesis", "reply", "reaction", "removed", "heartbeat", "open", "close", "error")


@dataclass(frozen=True)
class ThesisPage:
    items: list[dict[str, Any]]
    pagination: dict[str, Any]


@dataclass(frozen=True)
class TokenThesesPage:
    items: list[dict[str, Any]]
    pagination: dict[str, Any]
    #: Token info: chain, mint, name, symbol, logo, price_usd.
    token: dict[str, Any]
    #: Counts: theses, bull, bear, authors.
    summary: dict[str, Any]


def _q(value: str) -> str:
    return quote(value, safe="")


def _token_path(chain: str, mint: str) -> str:
    if chain not in CHAINS:
        raise BadRequestError(
            f"Unknown blockchain {chain!r}", code="invalid_parameter", parameter="chain", allowed=list(CHAINS)
        )
    if not mint:
        raise BadRequestError("Parameter 'mint' is required", code="missing_parameter", parameter="mint")
    return f"/tokens/{_q(chain)}/{_q(mint)}"


def _scope_query(scope: str | None, client_id: str | None) -> dict[str, str]:
    """Query parameters for a scope; instance scope needs the client_id."""
    if scope is None or scope == "global":
        return {"scope": scope} if scope else {}
    if scope != "instance":
        raise BadRequestError(
            f"Invalid value for 'scope': {scope!r}",
            code="invalid_parameter",
            parameter="scope",
            allowed=["global", "instance"],
        )
    if not client_id:
        raise BadRequestError("scope=instance needs client_id", code="missing_parameter", parameter="client_id")
    return {"scope": scope, "client_id": client_id}


class _ThesisBase:
    def __init__(
        self,
        access_token: str | None = None,
        *,
        scope: ThesisScope | None = None,
        client_id: str | None = None,
        base_url: str = DEFAULT_THESIS_URL,
        ws_url: str = DEFAULT_THESIS_WS_URL,
        timeout: float = 15.0,
    ) -> None:
        _scope_query(scope, client_id)
        #: global (default) or instance: only theses written on ``client_id``'s instance.
        self.scope = scope
        #: Your instance's client_id: needed for scope="instance"; also credits posts to your app.
        self.client_id = client_id
        self._access_token = access_token
        self.base_url = base_url.rstrip("/")
        self.ws_url = ws_url.rstrip("/")
        self.timeout = timeout

    def set_access_token(self, token: str | None) -> None:
        """Sets (or with None clears) the user's access token."""
        self._access_token = token

    def _request_args(self, auth: str | None) -> dict[str, str]:
        if auth == "required" and not self._access_token:
            raise AuthenticationError(
                'Sign in with CabalSpy ID to write (an access token with the scope "thesis").',
                status=401,
                code="sign_in_required",
            )
        headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
        if auth and self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"
        return headers

    @staticmethod
    def _parse(response: httpx.Response, label: str) -> dict[str, Any]:
        try:
            parsed: Any = response.json() if response.content else None
        except ValueError:
            parsed = None
        if response.status_code >= 400 or (isinstance(parsed, dict) and parsed.get("success") is False):
            err = parsed.get("error") if isinstance(parsed, dict) else None
            raise error_from_status(
                response.status_code,
                err if isinstance(err, dict) else None,
                RateLimit(),
                None,
                f"HTTP {response.status_code} on {label}",
            )
        if not isinstance(parsed, dict) or "data" not in parsed:
            raise InvalidResponseError(f"Unexpected response shape on {label}", status=response.status_code)
        return parsed

    @staticmethod
    def _check_emoji(emoji: str) -> None:
        if emoji not in THESIS_EMOJIS:
            raise BadRequestError(
                "Unknown reaction", code="invalid_parameter", parameter="emoji", allowed=list(THESIS_EMOJIS)
            )

    @staticmethod
    def _check_reason(reason: str) -> None:
        if reason not in THESIS_REPORT_REASONS:
            raise BadRequestError(
                "Choose a reason", code="invalid_parameter", parameter="reason", allowed=list(THESIS_REPORT_REASONS)
            )

    @staticmethod
    def _check_stance(stance: str | None) -> None:
        if stance not in (None, "bull", "bear"):
            raise BadRequestError(
                "stance must be bull or bear", code="invalid_parameter", parameter="stance", allowed=["bull", "bear"]
            )

    @staticmethod
    def _clean(params: Mapping[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in params.items() if v is not None and v != ""}

    def _token_page(self, parsed: dict[str, Any]) -> TokenThesesPage:
        return TokenThesesPage(
            parsed["data"], parsed.get("pagination") or {}, parsed.get("token") or {}, parsed.get("summary") or {}
        )

    def _scope(self, scope: str | None, client_id: str | None) -> dict[str, str]:
        return _scope_query(scope or self.scope, client_id or self.client_id)

    def _attributed(self, body: dict[str, Any]) -> dict[str, Any]:
        return {**body, "client_id": self.client_id} if self.client_id else body

    def live(
        self,
        chain: Chain,
        mint: str,
        *,
        scope: ThesisScope | None = None,
        client_id: str | None = None,
        **kwargs: Any,
    ) -> ThesisLive:
        """Live updates for one token over the public websocket (async): thesis, reply, reaction, removed.

        With ``scope="instance"`` (and ``client_id``) only theses written on that instance.
        """
        path = _token_path(chain, mint).removeprefix("/tokens")
        query = urlencode(self._scope(scope, client_id))
        return ThesisLive(f"{self.ws_url}{path}" + (f"?{query}" if query else ""), **kwargs)


class ThesisClient(_ThesisBase):
    """Synchronous client for the public thesis API."""

    def __init__(
        self, access_token: str | None = None, *, http_client: httpx.Client | None = None, **kwargs: Any
    ) -> None:
        super().__init__(access_token, **kwargs)
        self._http = http_client or httpx.Client(timeout=self.timeout)
        self._owns_http = http_client is None

    def __enter__(self) -> ThesisClient:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def _call(
        self,
        method: str,
        path: str,
        *,
        auth: str | None = None,
        params: Mapping[str, Any] | None = None,
        body: Any = None,
    ) -> dict[str, Any]:
        headers = self._request_args(auth)
        try:
            response = self._http.request(
                method, f"{self.base_url}{path}", params=self._clean(params or {}), json=body, headers=headers
            )
        except httpx.TimeoutException as exc:
            raise APIConnectionError(f"Request timed out: {method} {path}", code="timeout") from exc
        except httpx.HTTPError as exc:
            raise APIConnectionError(f"Network error: {exc}", code="connection_error") from exc
        return self._parse(response, f"{method} {path}")

    # reading
    def list(
        self,
        chain: Chain,
        mint: str,
        *,
        sort: ThesisSort | None = None,
        stance: ThesisStance | None = None,
        limit: int | None = None,
        cursor: str | None = None,
        scope: ThesisScope | None = None,
        client_id: str | None = None,
    ) -> TokenThesesPage:
        """Theses on a token, with token info and counts."""
        parsed = self._call(
            "GET",
            _token_path(chain, mint),
            auth="optional",
            params={"sort": sort, "stance": stance, "limit": limit, "cursor": cursor, **self._scope(scope, client_id)},
        )
        return self._token_page(parsed)

    def iterate(self, chain: Chain, mint: str, **kwargs: Any) -> Iterator[dict[str, Any]]:
        """Every thesis on a token, following ``next_cursor``."""
        cursor = kwargs.pop("cursor", None)
        while True:
            page = self.list(chain, mint, cursor=cursor, **kwargs)
            yield from page.items
            cursor = page.pagination.get("next_cursor")
            if not page.pagination.get("has_more") or not cursor:
                return

    def summary(
        self, chain: Chain, mint: str, *, scope: ThesisScope | None = None, client_id: str | None = None
    ) -> dict[str, Any]:
        """Counts (theses, bull, bear, authors) and token info."""
        result: dict[str, Any] = self._call(
            "GET", f"{_token_path(chain, mint)}/summary", params=self._scope(scope, client_id)
        )["data"]
        return result

    def get(self, thesis_id: str) -> dict[str, Any]:
        """One thesis or reply."""
        result: dict[str, Any] = self._call("GET", f"/items/{_q(thesis_id)}", auth="optional")["data"]
        return result

    def replies(self, thesis_id: str, *, limit: int | None = None, cursor: str | None = None) -> ThesisPage:
        parsed = self._call(
            "GET", f"/items/{_q(thesis_id)}/replies", auth="optional", params={"limit": limit, "cursor": cursor}
        )
        return ThesisPage(parsed["data"], parsed.get("pagination") or {})

    def by_user(self, csid_id: str, *, limit: int | None = None, cursor: str | None = None) -> ThesisPage:
        parsed = self._call("GET", f"/users/{_q(csid_id)}", auth="optional", params={"limit": limit, "cursor": cursor})
        return ThesisPage(parsed["data"], parsed.get("pagination") or {})

    # the signed-in user
    def me(self, chain: Chain, mint: str) -> dict[str, Any]:
        """Eligibility of the signed-in user (can_post, can_reply, holder, paused) and who they are."""
        result: dict[str, Any] = self._call("GET", f"{_token_path(chain, mint)}/me", auth="required")["data"]
        return result

    def post(self, chain: Chain, mint: str, *, body: str, stance: ThesisStance | None = None) -> dict[str, Any]:
        """Posts a thesis. Holders only (``not_a_holder`` otherwise)."""
        self._check_stance(stance)
        result: dict[str, Any] = self._call(
            "POST",
            _token_path(chain, mint),
            auth="required",
            body=self._attributed(self._clean({"body": body, "stance": stance})),
        )["data"]
        return result

    def reply(self, thesis_id: str, body: str) -> dict[str, Any]:
        result: dict[str, Any] = self._call(
            "POST", f"/items/{_q(thesis_id)}/replies", auth="required", body=self._attributed({"body": body})
        )["data"]
        return result

    def react(self, thesis_id: str, emoji: ThesisEmoji, on: bool = True) -> dict[str, Any]:
        self._check_emoji(emoji)
        result: dict[str, Any] = self._call(
            "POST", f"/items/{_q(thesis_id)}/reactions", auth="required", body={"emoji": emoji, "on": on}
        )["data"]
        return result

    def report(self, thesis_id: str, reason: ThesisReportReason, note: str | None = None) -> dict[str, Any]:
        self._check_reason(reason)
        result: dict[str, Any] = self._call(
            "POST",
            f"/items/{_q(thesis_id)}/report",
            auth="required",
            body=self._clean({"reason": reason, "note": note}),
        )["data"]
        return result

    def delete(self, thesis_id: str) -> dict[str, Any]:
        result: dict[str, Any] = self._call("DELETE", f"/items/{_q(thesis_id)}", auth="required")["data"]
        return result


class AsyncThesisClient(_ThesisBase):
    """Asynchronous client for the public thesis API; same methods as :class:`ThesisClient`."""

    def __init__(
        self, access_token: str | None = None, *, http_client: httpx.AsyncClient | None = None, **kwargs: Any
    ) -> None:
        super().__init__(access_token, **kwargs)
        self._http = http_client or httpx.AsyncClient(timeout=self.timeout)
        self._owns_http = http_client is None

    async def __aenter__(self) -> AsyncThesisClient:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def _call(
        self,
        method: str,
        path: str,
        *,
        auth: str | None = None,
        params: Mapping[str, Any] | None = None,
        body: Any = None,
    ) -> dict[str, Any]:
        headers = self._request_args(auth)
        try:
            response = await self._http.request(
                method, f"{self.base_url}{path}", params=self._clean(params or {}), json=body, headers=headers
            )
        except httpx.TimeoutException as exc:
            raise APIConnectionError(f"Request timed out: {method} {path}", code="timeout") from exc
        except httpx.HTTPError as exc:
            raise APIConnectionError(f"Network error: {exc}", code="connection_error") from exc
        return self._parse(response, f"{method} {path}")

    async def list(
        self,
        chain: Chain,
        mint: str,
        *,
        sort: ThesisSort | None = None,
        stance: ThesisStance | None = None,
        limit: int | None = None,
        cursor: str | None = None,
        scope: ThesisScope | None = None,
        client_id: str | None = None,
    ) -> TokenThesesPage:
        parsed = await self._call(
            "GET",
            _token_path(chain, mint),
            auth="optional",
            params={"sort": sort, "stance": stance, "limit": limit, "cursor": cursor, **self._scope(scope, client_id)},
        )
        return self._token_page(parsed)

    async def iterate(self, chain: Chain, mint: str, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        cursor = kwargs.pop("cursor", None)
        while True:
            page = await self.list(chain, mint, cursor=cursor, **kwargs)
            for item in page.items:
                yield item
            cursor = page.pagination.get("next_cursor")
            if not page.pagination.get("has_more") or not cursor:
                return

    async def summary(
        self, chain: Chain, mint: str, *, scope: ThesisScope | None = None, client_id: str | None = None
    ) -> dict[str, Any]:
        result: dict[str, Any] = (
            await self._call("GET", f"{_token_path(chain, mint)}/summary", params=self._scope(scope, client_id))
        )["data"]
        return result

    async def get(self, thesis_id: str) -> dict[str, Any]:
        result: dict[str, Any] = (await self._call("GET", f"/items/{_q(thesis_id)}", auth="optional"))["data"]
        return result

    async def replies(self, thesis_id: str, *, limit: int | None = None, cursor: str | None = None) -> ThesisPage:
        parsed = await self._call(
            "GET", f"/items/{_q(thesis_id)}/replies", auth="optional", params={"limit": limit, "cursor": cursor}
        )
        return ThesisPage(parsed["data"], parsed.get("pagination") or {})

    async def by_user(self, csid_id: str, *, limit: int | None = None, cursor: str | None = None) -> ThesisPage:
        parsed = await self._call(
            "GET", f"/users/{_q(csid_id)}", auth="optional", params={"limit": limit, "cursor": cursor}
        )
        return ThesisPage(parsed["data"], parsed.get("pagination") or {})

    async def me(self, chain: Chain, mint: str) -> dict[str, Any]:
        result: dict[str, Any] = (await self._call("GET", f"{_token_path(chain, mint)}/me", auth="required"))["data"]
        return result

    async def post(self, chain: Chain, mint: str, *, body: str, stance: ThesisStance | None = None) -> dict[str, Any]:
        self._check_stance(stance)
        result: dict[str, Any] = (
            await self._call(
                "POST",
                _token_path(chain, mint),
                auth="required",
                body=self._attributed(self._clean({"body": body, "stance": stance})),
            )
        )["data"]
        return result

    async def reply(self, thesis_id: str, body: str) -> dict[str, Any]:
        result: dict[str, Any] = (
            await self._call(
                "POST", f"/items/{_q(thesis_id)}/replies", auth="required", body=self._attributed({"body": body})
            )
        )["data"]
        return result

    async def react(self, thesis_id: str, emoji: ThesisEmoji, on: bool = True) -> dict[str, Any]:
        self._check_emoji(emoji)
        result: dict[str, Any] = (
            await self._call(
                "POST", f"/items/{_q(thesis_id)}/reactions", auth="required", body={"emoji": emoji, "on": on}
            )
        )["data"]
        return result

    async def report(self, thesis_id: str, reason: ThesisReportReason, note: str | None = None) -> dict[str, Any]:
        self._check_reason(reason)
        result: dict[str, Any] = (
            await self._call(
                "POST",
                f"/items/{_q(thesis_id)}/report",
                auth="required",
                body=self._clean({"reason": reason, "note": note}),
            )
        )["data"]
        return result

    async def delete(self, thesis_id: str) -> dict[str, Any]:
        result: dict[str, Any] = (await self._call("DELETE", f"/items/{_q(thesis_id)}", auth="required"))["data"]
        return result


# ── live websocket ──────────────────────────────────────────────────────────


class ThesisLive:
    """Public live socket for one token (async). Events: thesis, reply, reaction,
    removed, heartbeat, open, close, error. Reconnects after drops or missed
    heartbeats; close code 1008 (invalid token, too many sockets) is final."""

    def __init__(
        self,
        url: str,
        *,
        reconnect: bool = True,
        reconnect_delay: float = 1.0,
        max_reconnect_delay: float = 30.0,
        heartbeat_timeout: float | None = 75.0,
        open_timeout: float = 20.0,
    ) -> None:
        self.url = url
        self.reconnect = reconnect
        self.reconnect_delay = reconnect_delay
        self.max_reconnect_delay = max_reconnect_delay
        self.heartbeat_timeout = heartbeat_timeout
        self.open_timeout = open_timeout
        self._ws: Any = None
        self._handlers: dict[str, list[Callable[[Any], Any]]] = {}
        self._closed = False
        self._final: CabalSpyIDError | None = None
        self._attempt = 0
        self._reader: asyncio.Task[None] | None = None
        self._done = asyncio.Event()

    @property
    def connected(self) -> bool:
        return self._ws is not None

    def on(self, event: str, handler: Callable[[Any], Any] | None = None) -> Any:
        """Registers a handler (sync or async). Usable directly or as a decorator."""
        if event not in LIVE_EVENTS:
            raise ValueError(f"unknown event {event!r}; one of {', '.join(LIVE_EVENTS)}")

        def register(fn: Callable[[Any], Any]) -> Callable[[Any], Any]:
            self._handlers.setdefault(event, []).append(fn)
            return fn

        return register if handler is None else register(handler)

    def off(self, event: str, handler: Callable[[Any], Any]) -> None:
        if handler in self._handlers.get(event, []):
            self._handlers[event].remove(handler)

    async def _emit(self, event: str, payload: Any) -> None:
        for handler in list(self._handlers.get(event, [])):
            try:
                result = handler(payload)
                if inspect.isawaitable(result):
                    await result
            except Exception as exc:
                if event != "error":
                    await self._emit("error", exc)

    async def connect(self) -> None:
        """Opens the socket; returns once it is open."""
        try:
            import websockets
        except ImportError as exc:  # pragma: no cover
            raise ImportError('Live updates need the websockets package: pip install "cabalspy-id[stream]"') from exc
        self._closed = False
        self._final = None
        self._done.clear()
        try:
            ws = await websockets.connect(self.url, open_timeout=self.open_timeout)
        except Exception as exc:
            raise APIConnectionError(f"Could not connect to {self.url}: {exc}", code="ws_error") from exc
        self._ws = ws
        self._attempt = 0
        await self._emit("open", None)
        self._reader = asyncio.create_task(self._read(ws))

    async def _read(self, ws: Any) -> None:
        import websockets

        info: dict[str, Any] = {}
        try:
            while True:
                try:
                    raw = await (
                        asyncio.wait_for(ws.recv(), self.heartbeat_timeout) if self.heartbeat_timeout else ws.recv()
                    )
                except asyncio.TimeoutError:
                    await self._emit(
                        "error",
                        APIConnectionError("No heartbeat from the live socket; reconnecting", code="heartbeat_timeout"),
                    )
                    with contextlib.suppress(Exception):
                        await ws.close(code=4000, reason="heartbeat timeout")
                    break
                try:
                    msg = json.loads(raw)
                except (ValueError, TypeError):
                    continue
                kind = msg.get("type") if isinstance(msg, dict) else None
                if kind in ("thesis", "reply", "reaction", "removed"):
                    await self._emit(kind, msg.get("data"))
                elif kind == "heartbeat":
                    await self._emit("heartbeat", {})
        except websockets.ConnectionClosed as exc:
            rcvd = getattr(exc, "rcvd", None)
            info = {"code": getattr(rcvd, "code", None), "reason": getattr(rcvd, "reason", "")}
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._emit("error", exc)
        finally:
            if self._ws is ws:
                self._ws = None
        await self._emit("close", info)
        if info.get("code") == 1008:
            self._final = PermissionError_(
                "The live socket was refused (1008): invalid token address or too many sockets from this IP",
                code="ws_refused",
                status=403,
            )
            await self._emit("error", self._final)
        if self._closed or self._final or not self.reconnect:
            self._done.set()
            return
        while not self._closed:
            delay = min(self.reconnect_delay * (2**self._attempt), self.max_reconnect_delay) + random.random() * 0.25
            self._attempt += 1
            await asyncio.sleep(delay)
            if self._closed:
                break
            try:
                await self.connect()
                return
            except CabalSpyIDError as exc:
                await self._emit("error", exc)
        self._done.set()

    async def run_forever(self) -> None:
        """Blocks until :meth:`close` is called or the socket is refused (raised)."""
        await self._done.wait()
        if self._final:
            raise self._final

    async def close(self) -> None:
        self._closed = True
        ws, self._ws = self._ws, None
        if ws is not None:
            with contextlib.suppress(Exception):
                await ws.close()
        task = self._reader
        if task and not task.done() and task is not asyncio.current_task():
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=2)
            except (asyncio.TimeoutError, Exception):
                task.cancel()
        self._done.set()

    async def __aenter__(self) -> ThesisLive:
        await self.connect()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()
