"""Live trade stream: wss://api-id.cabalspy.xyz/v1/stream (Pro plan and up).

    from cabalspy_id import AsyncCabalSpyID

    async with AsyncCabalSpyID() as csid:
        stream = csid.stream(blockchain="solana")

        @stream.on("trade")
        def _(trade):
            print(trade["trader"]["username"], trade["transaction_type"], trade["value_usd"])

        await stream.connect()        # returns once the server confirmed the subscription
        await stream.run_forever()

    # or iterate:
    async for trade in csid.stream():
        ...

The server sends a heartbeat every 30 s. The client reconnects with
exponential backoff after a dropped connection or when nothing arrives for
``heartbeat_timeout`` seconds. Configuration errors from the server (invalid
key, plan without the stream, ...) are fatal and stop reconnecting.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import random
from collections.abc import AsyncIterator, Callable, Sequence
from typing import Any, TypeVar, overload
from urllib.parse import urlencode

from ._constants import CHAINS, STREAM_TOPICS
from ._errors import (
    APIConnectionError,
    BadRequestError,
    CabalSpyIDError,
    PermissionError_,
    RateLimitError,
)

try:
    import websockets
except ImportError:  # pragma: no cover
    websockets = None  # type: ignore[assignment]

Handler = Callable[[Any], Any]
H = TypeVar("H", bound=Callable[[Any], Any])

#: Events: trade, subscribed, heartbeat, pong, open, close, reconnecting, error, message.
#: Thesis events (open the stream with ``events=["theses"]``).
THESIS_EVENTS = ("thesis", "thesis.reply", "thesis.reaction", "thesis.removed")
STREAM_EVENTS = (
    "trade",
    *THESIS_EVENTS,
    "subscribed",
    "heartbeat",
    "pong",
    "open",
    "close",
    "reconnecting",
    "error",
    "message",
)

#: Server error codes that will not go away by reconnecting.
FATAL_CODES = frozenset(
    {
        "invalid_api_key",
        "plan_required",
        "invalid_parameter",
        "missing_parameter",
        "scope_not_allowed",
        "product_not_enabled",
    }
)


def _stream_error(code: str, message: str) -> CabalSpyIDError:
    if code in ("invalid_parameter", "missing_parameter"):
        return BadRequestError(message, code=code, status=400)
    if code == "too_many_connections":
        return RateLimitError(message, code=code, status=429)
    if code in FATAL_CODES:
        return PermissionError_(message, code=code, status=403)
    return CabalSpyIDError(message, code=code)


class CabalSpyIDStream:
    """Async WebSocket client. Obtain one via ``client.stream()``."""

    def __init__(
        self,
        url: str,
        api_key: str,
        *,
        events: Sequence[str] | None = None,
        blockchain: str | None = None,
        mint: str | None = None,
        scope: str | None = None,
        instance: str | None = None,
        reconnect: bool = True,
        reconnect_delay: float = 1.0,
        max_reconnect_delay: float = 30.0,
        heartbeat_timeout: float | None = 75.0,
        open_timeout: float = 20.0,
    ) -> None:
        if websockets is None:  # pragma: no cover
            raise ImportError('The stream needs the websockets package: pip install "cabalspy-id[stream]"')
        if blockchain is not None and blockchain not in CHAINS:
            raise BadRequestError(
                f"Unknown blockchain {blockchain!r}",
                code="invalid_parameter",
                parameter="blockchain",
                allowed=list(CHAINS),
            )
        topics = list(dict.fromkeys(events)) if events is not None else None
        if topics is not None and (not topics or any(t not in STREAM_TOPICS for t in topics)):
            raise BadRequestError(
                "events must contain 'trades' and/or 'theses'",
                code="invalid_parameter",
                parameter="events",
                allowed=list(STREAM_TOPICS),
            )
        if mint and not blockchain:
            raise BadRequestError("mint needs blockchain", code="missing_parameter", parameter="blockchain")
        query = {
            "events": ",".join(topics) if topics else None,
            "blockchain": blockchain,
            "mint": mint,
            "scope": scope,
            "instance": instance,
        }
        extra = {k: v for k, v in query.items() if v}
        self._url = f"{url}?{urlencode({'api_key': api_key, **extra})}"
        #: The URL with the key masked, safe to log.
        self.safe_url = f"{url}?{urlencode({'api_key': '***', **extra}, safe='*')}"
        self.reconnect = reconnect
        self.reconnect_delay = reconnect_delay
        self.max_reconnect_delay = max_reconnect_delay
        self.heartbeat_timeout = heartbeat_timeout
        self.open_timeout = open_timeout

        self._ws: Any = None
        self._handlers: dict[str, list[Handler]] = {}
        self._attempt = 0
        self._closed = False
        self._fatal: CabalSpyIDError | None = None
        self._reader: asyncio.Task[None] | None = None
        self._subscribed: asyncio.Future[dict[str, Any]] | None = None
        self._done = asyncio.Event()
        self._backlog: list[Any] | None = None

    # ── handlers ─────────────────────────────────────────────────────────

    @overload
    def on(self, event: str) -> Callable[[H], H]: ...

    @overload
    def on(self, event: str, handler: H) -> H: ...

    def on(self, event: str, handler: Handler | None = None) -> Any:
        """Registers a handler (sync or async). Usable directly or as a decorator."""
        if event not in STREAM_EVENTS:
            raise ValueError(f"unknown event {event!r}; one of {', '.join(STREAM_EVENTS)}")

        def register(fn: Handler) -> Handler:
            self._handlers.setdefault(event, []).append(fn)
            return fn

        return register if handler is None else register(handler)

    def off(self, event: str, handler: Handler) -> None:
        if handler in self._handlers.get(event, []):
            self._handlers[event].remove(handler)

    async def _emit(self, event: str, payload: Any) -> None:
        for handler in list(self._handlers.get(event, [])):
            try:
                result = handler(payload)
                if inspect.isawaitable(result):
                    await result
            except Exception as exc:  # a throwing handler must not kill the socket
                if event != "error":
                    await self._emit("error", exc)

    # ── connection ───────────────────────────────────────────────────────

    @property
    def connected(self) -> bool:
        return self._ws is not None

    @property
    def fatal_error(self) -> CabalSpyIDError | None:
        """The configuration error that stopped the stream, if any."""
        return self._fatal

    async def connect(self) -> dict[str, Any]:
        """Opens the socket. Returns the ``subscribed`` data once the server confirmed."""
        self._closed = False
        self._fatal = None
        self._done.clear()
        loop = asyncio.get_running_loop()
        self._subscribed = loop.create_future()
        try:
            self._ws = await websockets.connect(self._url, open_timeout=self.open_timeout)
        except Exception as exc:
            raise APIConnectionError(f"Could not connect to {self.safe_url}: {exc}", code="ws_error") from exc
        await self._emit("open", None)
        self._reader = asyncio.create_task(self._read_loop(self._ws, self._subscribed))
        return await self._subscribed

    async def _read_loop(self, ws: Any, subscribed: asyncio.Future[dict[str, Any]]) -> None:
        close_info: dict[str, Any] = {}
        try:
            while True:
                try:
                    if self.heartbeat_timeout:
                        raw = await asyncio.wait_for(ws.recv(), timeout=self.heartbeat_timeout)
                    else:
                        raw = await ws.recv()
                except asyncio.TimeoutError:
                    await self._emit(
                        "error",
                        APIConnectionError("No heartbeat from the stream; reconnecting", code="heartbeat_timeout"),
                    )
                    with contextlib.suppress(Exception):
                        await ws.close(code=4000, reason="heartbeat timeout")
                    break
                try:
                    message = json.loads(raw)
                except (ValueError, TypeError):
                    continue
                if isinstance(message, dict):
                    await self._dispatch(message, subscribed)
        except websockets.ConnectionClosed as exc:
            rcvd = getattr(exc, "rcvd", None)
            close_info = {"code": getattr(rcvd, "code", None), "reason": getattr(rcvd, "reason", "")}
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._emit("error", exc)
        finally:
            if self._ws is ws:
                self._ws = None
        await self._emit("close", close_info)
        if not subscribed.done():
            subscribed.set_exception(
                self._fatal
                or APIConnectionError(
                    f"Stream closed before it was ready (code {close_info.get('code')})", code="ws_closed_early"
                )
            )
        if not self._closed and not self._fatal and self.reconnect:
            await self._reconnect()
        else:
            self._done.set()

    async def _dispatch(self, message: dict[str, Any], subscribed: asyncio.Future[dict[str, Any]]) -> None:
        await self._emit("message", message)
        event = message.get("event")
        if event == "trade":
            await self._emit("trade", message.get("data"))
        elif event == "subscribed":
            self._attempt = 0
            data = message.get("data") or {}
            await self._emit("subscribed", data)
            if not subscribed.done():
                subscribed.set_result(data)
        elif event in THESIS_EVENTS:
            await self._emit(str(event), message.get("data"))
        elif event == "heartbeat":
            await self._emit("heartbeat", {"ts": message.get("ts")})
        elif event == "pong":
            await self._emit("pong", {})
        elif event == "error":
            err = message.get("error") or {}
            exc = _stream_error(str(err.get("code") or "stream_error"), str(err.get("message") or "Stream error"))
            if exc.code in FATAL_CODES:
                self._fatal = exc
            await self._emit("error", exc)
            if not subscribed.done():
                subscribed.set_exception(exc)

    async def _reconnect(self) -> None:
        while not self._closed:
            delay = min(self.reconnect_delay * (2**self._attempt), self.max_reconnect_delay) + random.random() * 0.25
            self._attempt += 1
            await self._emit("reconnecting", {"attempt": self._attempt, "delay": delay})
            await asyncio.sleep(delay)
            if self._closed:
                break
            try:
                await self.connect()
                return
            except CabalSpyIDError as exc:
                await self._emit("error", exc)
                if self._fatal:
                    break
                # connect() failed after the socket opened: its read loop retries.
                if self._ws is not None or (self._reader and not self._reader.done()):
                    return
        self._done.set()

    async def ping(self) -> None:
        """Sends a ping; the server answers with ``pong``.

        Not needed to keep the connection alive (the server sends heartbeats),
        and pinging more often than every 30 s suppresses those heartbeats.
        """
        if self._ws is not None:
            await self._ws.send("ping")

    async def run_forever(self) -> None:
        """Blocks until :meth:`close` is called or a fatal error stops the stream.

        Raises the fatal error, if there was one.
        """
        await self._done.wait()
        if self._fatal:
            raise self._fatal

    async def close(self) -> None:
        """Closes the socket and stops reconnecting."""
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

    async def __aenter__(self) -> CabalSpyIDStream:
        # Events that arrive between connecting and the first loop are kept for it.
        self._backlog = []
        for name in ("trade", *THESIS_EVENTS):
            self.on(name, self._backlog_handler(name))
        try:
            await self.connect()
        except BaseException:
            self._drop_backlog()
            raise
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    def _backlog_handler(self, name: str) -> Handler:
        def keep(data: Any) -> None:
            if self._backlog is not None:
                self._backlog.append((name, data))

        keep.__csid_backlog__ = True  # type: ignore[attr-defined]
        return keep

    def _drop_backlog(self) -> list[Any]:
        backlog, self._backlog = self._backlog or [], None
        for name in ("trade", *THESIS_EVENTS):
            self._handlers[name] = [
                h for h in self._handlers.get(name, []) if not getattr(h, "__csid_backlog__", False)
            ]
        return backlog

    def __aiter__(self) -> AsyncIterator[dict[str, Any]]:
        """Iterates over trades; connects if needed.

        Ends when :meth:`close` is called, or raises the fatal error that
        stopped the stream. ``break`` does not close the socket by itself: use
        ``async with csid.stream() as stream: async for trade in stream: ...``
        or call :meth:`close`.
        """
        return self._iterate(("trade",), lambda _name, data: data)

    def theses(self) -> AsyncIterator[dict[str, Any]]:
        """Iterates over thesis events as ``{"event": ..., "data": ...}``.

        Events: ``thesis``, ``thesis.reply``, ``thesis.reaction``,
        ``thesis.removed``. Open the stream with ``events=["theses"]``.
        """
        return self._iterate(THESIS_EVENTS, lambda name, data: {"event": name, "data": data})

    async def _iterate(self, names: tuple[str, ...], wrap: Callable[[str, Any], Any]) -> AsyncIterator[Any]:
        queue: asyncio.Queue[Any] = asyncio.Queue()
        stop = object()
        for name, data in self._drop_backlog():
            if name in names:
                queue.put_nowait(wrap(name, data))

        def listener(name: str) -> Handler:
            return lambda data: queue.put_nowait(wrap(name, data))

        listeners = [(name, listener(name)) for name in names]

        def on_error(_exc: Any) -> None:
            if self._fatal:
                queue.put_nowait(stop)

        def on_close(_info: Any) -> None:
            if self._closed or not self.reconnect:
                queue.put_nowait(stop)

        for name, fn in listeners:
            self.on(name, fn)
        self.on("error", on_error)
        self.on("close", on_close)
        owns = self._ws is None
        try:
            if owns:
                await self.connect()
            while True:
                item = await queue.get()
                if item is stop:
                    if self._fatal:
                        raise self._fatal
                    return
                yield item
        finally:
            for name, fn in listeners:
                self.off(name, fn)
            self.off("error", on_error)
            self.off("close", on_close)
            if owns and not self._closed:
                await self.close()
