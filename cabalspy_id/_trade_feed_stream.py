"""Trade Feed stream: wss://api-id.cabalspy.xyz/v1/trade-feed/stream (every plan).

Every Trade Feed event that concerns your users (those who allowed the scope
``trade_feed``): one ``trade_feed.trade`` or ``trade_feed.thesis`` per trade or
thesis of a trader in their Trade Feeds, with ``data["recipients"]`` = your
users whose filters it passed. The same events as the webhooks. At most 5
connections per API key.

    async with AsyncCabalSpyID() as csid:
        tf = csid.trade_feed_stream()

        @tf.on("trade_feed.trade")
        async def _(data):
            await notify(data["recipients"], data)

        await tf.connect()                       # returns on "ready"
        await tf.run_forever()

    # or iterate ({"event": ..., "id": ..., "data": ...}):
    async with csid.trade_feed_stream() as tf:
        async for ev in tf:
            ...
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import random
from collections.abc import AsyncIterator, Callable
from typing import Any, TypeVar, overload
from urllib.parse import urlencode

from ._constants import TRADE_FEED_EVENTS
from ._errors import APIConnectionError, CabalSpyIDError, PermissionError_, RateLimitError

try:
    import websockets
except ImportError:  # pragma: no cover
    websockets = None  # type: ignore[assignment]

Handler = Callable[[Any], Any]
H = TypeVar("H", bound=Callable[[Any], Any])

#: Events: ready, trade_feed.trade, trade_feed.thesis, heartbeat, pong, open, close, reconnecting, error.
TRADE_FEED_STREAM_EVENTS = (
    "ready",
    *TRADE_FEED_EVENTS,
    "heartbeat",
    "pong",
    "open",
    "close",
    "reconnecting",
    "error",
)


def _refused(code: str, message: str) -> CabalSpyIDError:
    if code == "too_many_connections":
        return RateLimitError(message, code=code, status=429)
    return PermissionError_(message, code=code, status=403)


class TradeFeedStream:
    """Async client for the Trade Feed stream. Obtain one via ``client.trade_feed_stream()``.

    Handlers of ``trade_feed.trade`` / ``trade_feed.thesis`` get the event's
    ``data`` (:class:`~cabalspy_id.TradeFeedTradeData` /
    :class:`~cabalspy_id.TradeFeedThesisData`); ``data["id"]`` is stable per
    trade or thesis, so dedupe on it.
    """

    def __init__(
        self,
        url: str,
        api_key: str,
        *,
        instance: str | None = None,
        reconnect: bool = True,
        reconnect_delay: float = 1.0,
        max_reconnect_delay: float = 30.0,
        heartbeat_timeout: float | None = 75.0,
        open_timeout: float = 20.0,
    ) -> None:
        if websockets is None:  # pragma: no cover
            raise ImportError('The Trade Feed stream needs the websockets package: pip install "cabalspy-id[stream]"')
        extra = {"instance": instance} if instance else {}
        self._url = f"{url}?{urlencode({'api_key': api_key, **extra})}"
        #: The URL with the key masked, safe to log.
        self.safe_url = f"{url}?{urlencode({'api_key': '***', **extra}, safe='*')}"
        self.reconnect = reconnect
        self.reconnect_delay = reconnect_delay
        self.max_reconnect_delay = max_reconnect_delay
        self.heartbeat_timeout = heartbeat_timeout
        self.open_timeout = open_timeout

        self._ws: Any = None
        self._ready = False
        self._handlers: dict[str, list[Handler]] = {}
        self._attempt = 0
        self._closed = False
        self._fatal: CabalSpyIDError | None = None
        self._reader: asyncio.Task[None] | None = None
        self._ready_future: asyncio.Future[dict[str, Any]] | None = None
        self._done = asyncio.Event()
        self._backlog: list[Any] | None = None
        self._keepers: list[tuple[str, Handler]] = []
        self._last_ids: dict[int, str] = {}

    # ── handlers ─────────────────────────────────────────────────────────

    @overload
    def on(self, event: str) -> Callable[[H], H]: ...

    @overload
    def on(self, event: str, handler: H) -> H: ...

    def on(self, event: str, handler: Handler | None = None) -> Any:
        """Registers a handler (sync or async). Usable directly or as a decorator."""
        if event not in TRADE_FEED_STREAM_EVENTS:
            raise ValueError(f"unknown event {event!r}; one of {', '.join(TRADE_FEED_STREAM_EVENTS)}")

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
            except Exception as exc:
                if event != "error":
                    await self._emit("error", exc)

    # ── connection ───────────────────────────────────────────────────────

    @property
    def connected(self) -> bool:
        return self._ws is not None and self._ready

    async def connect(self) -> dict[str, Any]:
        """Opens the socket. Returns the ``ready`` data (``{"events": [...]}``)."""
        self._closed = False
        self._fatal = None
        self._ready = False
        self._done.clear()
        self._ready_future = asyncio.get_running_loop().create_future()
        try:
            ws = await websockets.connect(self._url, open_timeout=self.open_timeout)
        except Exception as exc:
            raise APIConnectionError(f"Could not connect to {self.safe_url}: {exc}", code="ws_error") from exc
        self._ws = ws
        await self._emit("open", None)
        self._reader = asyncio.create_task(self._read(ws, self._ready_future))
        return await self._ready_future

    async def _read(self, ws: Any, ready: asyncio.Future[dict[str, Any]]) -> None:
        info: dict[str, Any] = {}
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
                        APIConnectionError(
                            "No heartbeat from the Trade Feed stream; reconnecting", code="heartbeat_timeout"
                        ),
                    )
                    with contextlib.suppress(Exception):
                        await ws.close(code=4000, reason="heartbeat timeout")
                    break
                try:
                    msg = json.loads(raw)
                except (ValueError, TypeError):
                    continue
                if isinstance(msg, dict):
                    await self._dispatch(msg, ready)
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
                self._ready = False
        await self._emit("close", info)
        if not ready.done():
            ready.set_exception(
                self._fatal
                or APIConnectionError(
                    f"Trade Feed stream closed before it was ready (code {info.get('code')})", code="ws_closed_early"
                )
            )
        if not self._closed and not self._fatal and self.reconnect:
            await self._reconnect()
        else:
            self._done.set()

    async def _dispatch(self, msg: dict[str, Any], ready: asyncio.Future[dict[str, Any]]) -> None:
        event = msg.get("event")
        if event == "ready":
            self._ready = True
            self._attempt = 0
            data = msg.get("data") or {"events": list(TRADE_FEED_EVENTS)}
            await self._emit("ready", data)
            if not ready.done():
                ready.set_result(data)
        elif event in TRADE_FEED_EVENTS:
            data = msg.get("data")
            if isinstance(data, dict) and msg.get("id"):
                self._last_ids[id(data)] = str(msg["id"])
            try:
                await self._emit(str(event), data)
            finally:
                self._last_ids.pop(id(data), None)
        elif event == "heartbeat":
            await self._emit("heartbeat", {"ts": msg.get("ts")})
        elif event == "pong":
            await self._emit("pong", {})
        elif event == "error":
            # Refused (the server closes the socket): a bad key is final, too_many_connections is retried.
            err = msg.get("error") or {}
            code, message = str(err.get("code") or "stream_error"), str(err.get("message") or "Stream error")
            exc = _refused(code, message)
            if code != "too_many_connections":
                self._fatal = exc
            await self._emit("error", exc)
            if not ready.done():
                ready.set_exception(exc)

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
                if self._ws is not None or (self._reader and not self._reader.done()):
                    return
        self._done.set()

    async def ping(self) -> None:
        """Sends a ping (answered with ``pong``)."""
        if self._ws is not None:
            await self._ws.send("ping")

    async def run_forever(self) -> None:
        """Blocks until :meth:`close` is called or a fatal error stops the stream (raised)."""
        await self._done.wait()
        if self._fatal:
            raise self._fatal

    async def close(self) -> None:
        """Closes the socket and stops reconnecting."""
        self._closed = True
        ws, self._ws = self._ws, None
        self._ready = False
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

    async def __aenter__(self) -> TradeFeedStream:
        # Events that arrive between connecting and the first loop are kept for it.
        self._backlog = []
        backlog = self._backlog
        keepers: list[tuple[str, Handler]] = [
            (name, self._listener(backlog.append, name)) for name in TRADE_FEED_EVENTS
        ]
        for name, fn in keepers:
            self.on(name, fn)
        self._keepers = keepers
        try:
            await self.connect()
        except BaseException:
            self._drop_backlog()
            raise
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    def _listener(self, put: Callable[[Any], Any], name: str) -> Handler:
        def fn(data: Any) -> None:
            put({"event": name, "id": self._last_ids.get(id(data), ""), "data": data})

        return fn

    def _drop_backlog(self) -> list[Any]:
        backlog, self._backlog = self._backlog or [], None
        for name, fn in self._keepers:
            self.off(name, fn)
        self._keepers = []
        return backlog

    async def __aiter__(self) -> AsyncIterator[dict[str, Any]]:
        """Iterates over Trade Feed events as ``{"event", "id", "data"}``; connects if needed.

        Ends when :meth:`close` is called, or raises the fatal error. ``break``
        does not close the socket by itself: use ``async with`` or call :meth:`close`.
        """
        queue: asyncio.Queue[Any] = asyncio.Queue()
        stop = object()
        for item in self._drop_backlog():
            queue.put_nowait(item)

        listeners = [(name, self._listener(queue.put_nowait, name)) for name in TRADE_FEED_EVENTS]

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
