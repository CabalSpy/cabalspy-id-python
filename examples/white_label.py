"""White-label tour: your own login, your users' wallets, leaderboards and competitions.

    CABALSPY_API_KEY=... python examples/white_label.py

The key is your CabalSpy API key with "CabalSpy ID" enabled on the API keys page.
The users and wallets below are placeholders: replace them with your own.
"""

from __future__ import annotations

from typing import Any

from cabalspy_id import CabalSpyID, ConflictError, PlanUserLimitError, PlatformImportError

# Your platform's users, e.g. from your database and your wallet provider (Privy, Dynamic, ...)
MY_USERS: list[dict[str, Any]] = [
    {"id": "user_1", "name": "Alice", "wallets": ["7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU"]},
    {"id": "user_2", "name": "Bob", "wallets": ["0x52908400098527886E0F7030069857D2E4169EE7"]},
]

with CabalSpyID() as csid:  # reads CABALSPY_ID_API_KEY or CABALSPY_API_KEY
    # Settings: count imported wallets, keep your users to yourself
    settings = csid.update_platform_settings(wallet_trust="all", data_scope="platform")
    print("settings:", settings["wallet_trust"], settings["data_scope"])

    # 1. Import every user with the wallets they already have (chunks of 1,000, retries on 429)
    try:
        result = csid.bulk_import_platform_users(
            {"external_id": u["id"], "display_name": u["name"], "wallets": u["wallets"]} for u in MY_USERS
        )
    except PlatformImportError as err:
        print("import stopped:", err, "- resume with err.remaining")
        raise
    print("import:", result["summary"], "in", result["requests"], "call(s)")
    for item in result["results"]:
        if item["status"] == "rejected":
            print("  rejected", item["external_id"], item["error"]["code"])

    # 2. A new sign-up later: one call (creates, or updates an existing user)
    try:
        user = csid.upsert_platform_user(
            "user_3", wallets=[{"address": "So11111111111111111111111111111111111111112", "source": "privy"}]
        )
        print("user_3 created" if user["created"] else "user_3 updated", user["csid_id"])
    except PlanUserLimitError as err:
        print("plan user limit reached:", err.body)

    # 3. A profile page in one call
    profile = csid.platform_user_profile("user_1", period="7d")
    for chain in profile["trading"]:
        pnl, win_rate = chain["realized_pnl_usd"], chain["win_rate_percentage"]
        print(f"{chain['blockchain']}: PnL {pnl:.2f} USD, win rate {win_rate}%")
    print("wallets:", [(w["address"], w["status"]) for w in profile["wallets"]])

    # 4. Your own leaderboard (follows the cursor for you)
    for entry in csid.iter_platform_leaderboard(blockchain="solana", period="7d", sort="pnl_usd", limit=100):
        print(entry["rank"], entry["external_id"], entry["period_stats"]["realized_pnl_usd"])

    # 5. Optional: a verified badge through the on-chain payment verification
    v = csid.start_wallet_verification("user_1", chain="solana", address=MY_USERS[0]["wallets"][0])
    print(v["instructions"])
    svg = csid.wallet_verification_qr(v["verification_id"])  # an SVG QR code to show the user
    print(len(svg), "bytes of SVG")
    csid.cancel_wallet_verification(v["verification_id"])

    # 6. A trading competition between your users
    try:
        comp = csid.create_competition(
            name="Weekly PnL",
            chain="solana",
            metric="pnl_usd",
            duration_hours=168,
            min_participants=2,
            min_trades=3,
            prizes=[{"rank": 1, "prize": "100 USDC"}],
        )
    except ConflictError as err:  # competition_limit: 5 scheduled + running at a time
        print("cannot create:", err.code)
    else:
        for u in MY_USERS:
            csid.join_competition(comp["id"], u["id"])
        csid.update_competition(comp["id"], min_trades=1, note="Lower entry bar")
        standings = csid.competition_standings(comp["id"])
        print(comp["name"], standings["status"], [(s["rank"], s["external_id"]) for s in standings["standings"]])
        csid.cancel_competition(comp["id"])  # this is only a demo

    # 7. Clean up the demo user
    csid.delete_platform_user("user_3")
