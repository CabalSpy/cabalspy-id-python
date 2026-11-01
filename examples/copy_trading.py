"""Copy trading tour: copy a trader for one of your users, execute the instructions, report back.

    pip install "cabalspy-id[stream]"            # the stream part only
    CABALSPY_API_KEY=... python examples/copy_trading.py

CabalSpy ID never holds keys and never executes: every trade of a copied trader
becomes an instruction for your app, which executes it with the user's wallet and
reports the result. The user needs to have allowed your app the scope trade_feed.
The user and the trader below are placeholders.
"""

from __future__ import annotations

import asyncio
from typing import Any

from cabalspy_id import (
    AsyncCabalSpyID,
    CabalSpyID,
    ConflictError,
    NotFoundError,
    PermissionError,
)

USER = "user_1"  # your platform's user id (external_id)
TRADER = "ctkol"  # a CabalSpy ID handle or csid_id


def execute(instruction: Any) -> str | None:
    """Your swap with the user's wallet. Returns the transaction signature, or None."""
    a = instruction["action"]
    if a["side"] == "buy":
        print(f"  buy ${a['amount_usd']} of {a['symbol']} on {a['blockchain']}, at most ${a['max_price_usd']}")
    else:
        print(f"  sell {a['sell_percent']} % of the copied {a['symbol']}, at least ${a['min_price_usd']}")
    return None  # placeholder: nothing is executed in this example


def report(csid: CabalSpyID, instruction: Any) -> None:
    sig = execute(instruction)
    if sig:
        csid.report_copy_instruction(
            instruction["id"],
            status="executed",
            tx_signature=sig,
            executed_amount_usd=instruction["action"]["amount_usd"],
        )
    else:
        csid.report_copy_instruction(instruction["id"], status="skipped", note="example: not executed")


def tour() -> None:
    with CabalSpyID() as csid:  # reads CABALSPY_ID_API_KEY or CABALSPY_API_KEY
        # 1. Copy the trader: $25 per buy, at most $20, buys and sells, 1.5 % price limit
        try:
            s = csid.update_copy_trading_settings(
                USER,
                trader=TRADER,
                enabled=True,
                mode="fixed_usd",
                amount_usd=25,
                max_usd=20,
                sides="both",
                slippage_bps=150,
            )
            print("copying", s["trader"]["username"], s["copy"])
        except ConflictError as err:  # copy_managed_elsewhere: another platform copies this trader
            print("managed elsewhere:", err.message)
        except PermissionError as err:  # consent_required: no trade_feed scope
            print("not allowed:", err.code)
            return
        except NotFoundError as err:  # trader_not_found
            print("no such trader:", err.code)
            return

        # 2. Everyone in the user's Trade Feed and how they are copied
        for s in csid.copy_trading_settings(USER):
            print(f"  {s['trader']['username']}: {s['copy']['enabled']} (elsewhere: {s['managed_by_other_platform']})")

        # 3. Pending instructions, newest first: execute and report each
        for i in csid.iter_copy_instructions(USER, status="pending"):
            report(csid, i)

        # 4. Percent mode, buys only, no cap
        csid.update_copy_trading_settings(USER, trader=TRADER, mode="percent", percent=10, sides="buys", max_usd=None)


async def live() -> None:
    """New instructions as they happen (the webhook copy_trade.instruction carries the same)."""
    async with AsyncCabalSpyID() as csid:
        cs = csid.copy_trading_stream()

        @cs.on("copy_trade.instruction")
        async def on_instruction(i: Any) -> None:
            print("instruction", i["id"], "for", i.get("external_id") or i["csid_id"], i["action"]["side"])
            await csid.report_copy_instruction(i["id"], status="skipped", note="example")

        cs.on("error", lambda err: print("stream error:", err))
        print("ready:", await cs.connect())
        try:
            await asyncio.wait_for(cs.run_forever(), timeout=60)
        except asyncio.TimeoutError:
            pass
        finally:
            await cs.close()


if __name__ == "__main__":
    tour()
    asyncio.run(live())
