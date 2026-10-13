"""Live trades of your users (Pro plan and up).

pip install "cabalspy-id[stream]"
CABALSPY_API_KEY=... python examples/stream.py
"""

from __future__ import annotations

import asyncio
from typing import Any

from cabalspy_id import AsyncCabalSpyID


async def main() -> None:
    async with AsyncCabalSpyID() as csid:
        stream = csid.stream(blockchain="solana")  # omit blockchain for every chain

        @stream.on("trade")
        def on_trade(t: dict[str, Any]) -> None:
            who = t["trader"]["username"] if t["trader"] else t["wallet"]
            print(f"{who} {t['transaction_type']} {t['token_symbol']} for ${t['value_usd']:.2f}")

        @stream.on("reconnecting")
        def on_reconnect(r: dict[str, Any]) -> None:
            print(f"reconnecting (#{r['attempt']}) in {r['delay']:.1f}s")

        @stream.on("error")
        def on_error(e: Exception) -> None:
            print("error:", e)

        print("subscribed:", await stream.connect())
        await stream.run_forever()  # until stream.close() or a fatal error

        # or iterate:
        # async with csid.stream() as stream:
        #     async for trade in stream:
        #         print(trade)


if __name__ == "__main__":
    asyncio.run(main())
