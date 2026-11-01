"""Trade Feed tour: manage one user's Trade Feed, read it, and get new trades live.

    pip install "cabalspy-id[stream]"            # the stream part only
    CABALSPY_API_KEY=... python examples/trade_feed.py

Every call acts in the name of one of your users: someone who signed in to your app with
the scope trade_feed, or one of your platform users. The user and the trader below are
placeholders.
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
    RateLimitError,
)

USER = "user_1"  # your platform's user id (external_id)
TRADER = "MazeCCC"  # a CabalSpy ID handle or csid_id


def line(item: Any) -> str:
    who = item["trader"]["username"] or item["trader"]["name"]
    if item["type"] == "thesis":
        th = item["thesis"]
        return f"{who} posted a {th['stance'] or 'neutral'} thesis on {th['symbol']}: {th['body'][:60]}"
    t = item["trade"]
    size = f"${t['amount_usd']:.0f}" if t["amount_usd"] else f"{t['amount_native']} {t['currency']}"
    return f"{who} {'bought' if t['side'] == 'buy' else 'sold'} {t['symbol']} for {size} ({t['label']})"


def tour() -> None:
    with CabalSpyID() as csid:  # reads CABALSPY_ID_API_KEY or CABALSPY_API_KEY
        # 1. Add the trader: alerts for buys from 0.5 SOL, no sells
        try:
            r = csid.add_trade_feed_trader(USER, trader=TRADER, min_sol=0.5, notify_sells=False)
            print("added" if r["created"] else "already there:", r["trader"]["username"], r["settings"])
        except PermissionError as err:  # consent_required (no trade_feed scope), trading_private
            print("not allowed:", err.code)
            return
        except NotFoundError as err:  # trader_not_found, platform_user_not_found
            print("not found:", err.code)
            return
        except ConflictError as err:  # trade_feed_full: 300 traders
            print("full:", err.message)
        except RateLimitError as err:  # rate_limited: more than 120 changes in an hour
            print("slow down:", err.message)

        # 2. Everyone in the Trade Feed, with alert and copy settings
        page = csid.get_raw("/trade-feed/traders", {"external_id": USER})
        print(f"{(page.pagination or {}).get('total')} of {(page.pagination or {}).get('max')} traders")
        for entry in csid.iter_trade_feed_traders(USER):
            s, name = entry["settings"], entry["trader"]["username"]
            print(f"  {name}: muted={s['muted']} min={s['min_native']} copy={s['copy']['enabled']}")

        # 3. The feed, newest first (first 20 items)
        for n, item in enumerate(csid.iter_trade_feed(USER), 1):
            print(" ", line(item))
            if n == 20:
                break

        # 4. Alerts that passed the user's filters
        for alert in csid.trade_feed_notifications(USER, limit=5):
            print("  alert:", alert["created_at"], alert["text"])

        # 5. Mute the trader (updates the settings, the trader stays), then remove them
        csid.add_trade_feed_trader(USER, trader=TRADER, muted=True)
        print("removed:", csid.remove_trade_feed_trader(USER, trader=TRADER)["removed"])


async def live() -> None:
    """New trades and theses as they happen (the webhooks trade_feed.trade / .thesis carry the same)."""
    async with AsyncCabalSpyID() as csid:
        tf = csid.trade_feed_stream()

        @tf.on("trade_feed.trade")
        @tf.on("trade_feed.thesis")
        def on_item(item: Any) -> None:
            print(line(item), "-> tell", item["recipients_external"] or item["recipients"])

        tf.on("error", lambda err: print("stream error:", err))
        print("ready:", await tf.connect())
        try:
            await asyncio.wait_for(tf.run_forever(), timeout=60)
        except asyncio.TimeoutError:
            pass
        finally:
            await tf.close()


if __name__ == "__main__":
    tour()
    asyncio.run(live())
