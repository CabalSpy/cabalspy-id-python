"""Trade Feed in a user's name, then the live Trade Feed stream.

    CABALSPY_API_KEY=... CSID_USER=<sub> python examples/trade_feed.py alice

The user must have signed in to your app with the scope "trade_feed".
"""

from __future__ import annotations

import asyncio
import os
import sys

from cabalspy_id import AsyncCabalSpyID, CabalSpyID


def main() -> None:
    user = os.environ["CSID_USER"]
    trader = sys.argv[1] if len(sys.argv) > 1 else "alice"
    with CabalSpyID() as csid:  # CABALSPY_API_KEY from the environment
        added = csid.add_to_trade_feed(user, trader, notify_theses=True, min_sol=0.1)
        print("added" if added["created"] else "updated", added["trader"]["username"], added["settings"])

        for entry in csid.trade_feed_traders(user):
            print("in the Trade Feed:", entry["trader"]["username"], "" if entry["trading_public"] else "(private)")

        for n, item in enumerate(csid.iter_trade_feed(user, filter="all")):
            if item["type"] == "trade":
                t = item["trade"]
                print(
                    item["timestamp"],
                    item["trader"]["username"],
                    t["side"],
                    t["symbol"],
                    t["amount_native"],
                    t["label"],
                )
            else:
                print(item["timestamp"], item["trader"]["username"], "thesis", item["thesis"]["body"][:60])
            if n >= 19:
                break


async def live() -> None:
    # Every user of your instance (the same events as the webhooks); needs cabalspy-id[stream].
    async with AsyncCabalSpyID() as csid:
        tf = csid.trade_feed_stream()
        tf.on(
            "trade_feed.trade",
            lambda d: print("tell", d["recipients"], "->", d["trader"]["username"], d["trade"]["label"]),
        )
        tf.on("error", lambda e: print("error", getattr(e, "code", e)))
        await tf.connect()
        await tf.run_forever()


if __name__ == "__main__":
    main()
    asyncio.run(live())
