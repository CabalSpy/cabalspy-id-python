# Changelog

All notable changes to this package are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.7.0] - 2026-10-31

Callouts: your users call tokens, and every call is stamped with the token's price and market
cap and tracked (every minute for the first 24 hours, then scored on candles; every 5 minutes
after that while the token is active, until 24 hours in a row below a $10k market cap). Callouts
are an extra that CabalSpy switches on per instance on request. Sync and async.

### Added

- Callouts (`/v1/callouts*`) on `CabalSpyID` and `AsyncCabalSpyID`: `create_callout`
  (`external_id` positionally or `csid_id=`; `chain`, `mint`, `note`), `remove_callout`,
  `callouts` / `iter_callouts` (filters `chain`, `mint`, `external_id` / `csid_id`, `since`,
  `until`; datetimes are sent as ISO 8601 UTC), `callout`, `callout_stats` (`hit_x`),
  `callout_leaderboard` / `iter_callout_leaderboard` (`period`, `chain`, `sort`, `min_callouts`,
  `hit_x`), `callout_settings`, `update_callout_settings` (`who`, `require_holding`,
  `cooldown_minutes`).
- `CalloutsStream` for `wss://api-id.cabalspy.xyz/v1/callouts/stream` via
  `client.callouts_stream(chain=, mint=)`: events `callout.created`, `callout.update`,
  `callout.milestone`, `callout.scored`, `callout.final`, `callout.removed` (handlers or
  `async for`), heartbeats, reconnects with backoff; `feature_not_enabled` and `invalid_api_key`
  are fatal, `too_many_connections` reconnects. New client option `callouts_stream_url`.
- Callout competitions: `create_competition(kind="callouts", ...)` with the metrics
  `avg_peak_x`, `best_peak_x`, `sum_peak_x`, `hit_rate`, `callouts`, `min_callouts`, `hit_x` and
  `chain="all"`; `update_competition` takes `min_callouts`, `hit_x` and `chain="all"`. The kind
  decides which chains, metrics and minimums are accepted locally.
- Types: `Callout` (`at_call`, `now`, `peak`, `score_x`, `tracking` with `below_10k_since`,
  `first_day`, ...), `CalloutStats`, `CalloutPeriodStats`, `CalloutLeaderboardEntry`,
  `CalloutLeaderboardResponse`, `CalloutSettings`, `CalloutBestCall`, `CalloutUser`, the stream
  events `CalloutUpdate`, `CalloutMilestone`, `CalloutRemovedEvent`, `CalloutsStreamReady`, and
  `CalloutWebhookData`. `MeResponse.features` (the extras switched on, e.g. `["callouts"]`).
  `Competition` has `kind`, `min_callouts` and `hit_x`; `CompetitionStanding` the callout stats
  and `best_call`.
- Constants: `CALLOUT_WEBHOOK_EVENTS` (`callout.created`, `callout.milestone`, `callout.scored`,
  `callout.final`, also in `WEBHOOK_EVENTS`), `CALLOUT_COMPETITION_METRICS`, `COMPETITION_KINDS`,
  `CALLOUT_SORTS`, `CALLOUT_WHO`, `CALLOUT_MAX_NOTE`, `CALLOUT_DEFAULT_HIT_X`,
  `CALLOUT_MILESTONES`, `CALLOUT_ACTIVE_MCAP_USD`, `MAX_CALLOUT_STREAMS_PER_KEY`,
  `DEFAULT_CALLOUTS_STREAM_URL`, `FEATURE_CALLOUTS`, `CALLOUT_EVENTS`, `CALLOUTS_STREAM_EVENTS`;
  Literal types `CompetitionKind`, `CompetitionChain`, `TradingCompetitionMetric`,
  `CalloutCompetitionMetric`, `CalloutSort`, `CalloutWho`, `CalloutStatus`, `CalloutPhase`,
  `CalloutFirstDayKind`.
- New error codes on the existing classes: `feature_not_enabled`, `kol_only`, `not_a_holder`,
  `invalid_account`, `posting_paused`, `consent_required`, `sandbox_user` (`PermissionError`),
  `callout_not_found` (`NotFoundError`), `already_called` (`ConflictError`), `callout_cooldown`
  (`RateLimitError` with `retry_after`), `no_price` (`BadRequestError`, HTTP 422).
- README section "Callouts (on request)" and `examples/callouts.py`.

### Changed

- `callout_cooldown` (429) is never retried automatically, on any route: its `Retry-After` can be
  hours. `RateLimitError.retry_after` falls back to the error body's `retry_after` when the header
  is missing.
- HTTP 422 responses raise `BadRequestError` (with `status` 422) instead of the base
  `CabalSpyIDError`.
- `CompetitionMetric` now covers the trading and the callout metrics; the trading ones alone are
  `TradingCompetitionMetric` (`COMPETITION_METRICS` is unchanged). `Competition.min_trades` and
  `min_volume_usd` are only present on trading competitions.

## [0.6.0] - 2026-10-28

White-label: a platform keeps its own login, imports its users (by its own user id,
`external_id`) with the wallets they already have, and uses their trades, PnL, leaderboards
and trading competitions through the Data API. Sync and async.

### Added

- Platform users (`/v1/platform-users/*`) on `CabalSpyID` and `AsyncCabalSpyID`:
  `upsert_platform_user`, `import_platform_users`, `platform_user`, `update_platform_user`,
  `platform_users` / `iter_platform_users`, `delete_platform_user`, `add_platform_user_wallets`,
  `delete_platform_user_wallet`, `start_wallet_verification`, `wallet_verification`,
  `wallet_verification_qr` (SVG), `cancel_wallet_verification`, `platform_user_profile`,
  `platform_leaderboard` / `iter_platform_leaderboard`, `platform_settings`,
  `update_platform_settings`, `platform_inbound`, `enable_platform_inbound`,
  `disable_platform_inbound`, `platform_user_session`, `platform_user_claim_link`,
  `connect_platform_user_x`, `disconnect_platform_user_x`, `link_platform_user_telegram`,
  `platform_user_telegram`, `unlink_platform_user_telegram`, `platform_user_kol`,
  `request_platform_user_volume_check`, `apply_platform_user_kol`. Methods that take a user
  accept `external_id` or `csid_id=`.
- `bulk_import_platform_users(users)`: any number of users in chunks of at most 1,000 and under
  the 1 MB body limit, aggregated results in input order. Retries a chunk refused with 429
  (`Retry-After` wins) and re-sends only the users rejected with `rate_limited` once the
  minute is over; a chunk that succeeded is never sent again. Other failures raise
  `PlatformImportError` with `result` and `remaining` (to resume).
- Trading competitions (`/v1/competitions*`): `create_competition`, `competitions` /
  `iter_competitions`, `competition`, `update_competition`, `cancel_competition`,
  `join_competition`, `leave_competition`, `competition_participants` /
  `iter_competition_participants`, `competition_standings` / `iter_competition_standings`.
  The offset-paginated routes are walked with the new `offset_items()`.
- `get_text()` for non-JSON answers (the verification QR code).
- `ConflictError` (409): `account_claimed`, `last_wallet`, `too_many_wallets`,
  `wallet_already_verified`, `kol_badge`, `x_required`, `kol_not_eligible`, `competition_limit`,
  `competition_closed`, `competition_full`, `late_join_closed`. It subclasses
  `CabalSpyIDError`, which 409 responses raised before.
- New codes on the existing classes: `wallet_required`, `invalid_address`, `invalid_return_url`
  (`BadRequestError`), `claim_disabled` (`PermissionError`), `plan_user_limit` on creating a
  user (`PlanUserLimitError`, `body` has `user_limit`), `platform_user_not_found`,
  `verification_not_found`, `competition_not_found` (`NotFoundError`), `rate_limited` and
  `too_many_open_verifications` (`RateLimitError`).
- Webhook events `platform_user.created`, `platform_user.claimed`, `platform_user.x_connected`,
  `wallet.added`, `verification.expired`, `competition.started`, `competition.updated`,
  `competition.standings`, `competition.ended` in `WEBHOOK_EVENTS`, plus
  `PLATFORM_WEBHOOK_EVENTS` and `COMPETITION_WEBHOOK_EVENTS`.
- Types: `PlatformUser`, `PlatformUserUpsert`, `PlatformWallet`, `PlatformUserInput`,
  `PlatformWalletInput`, `PlatformImportResult`, `PlatformBulkImportResult`, `PlatformSettings`,
  `PlatformUserProfile`, `PlatformLeaderboardEntry`, `WalletVerification`, `Competition`,
  `CompetitionDetail`, `CompetitionStanding`, `CompetitionStandings` and more; constants
  `PLATFORM_IMPORT_MAX`, `PLATFORM_MAX_WALLETS_PER_REQUEST`, `MAX_REQUEST_BODY_BYTES`,
  `WALLET_TRUST`, `DATA_SCOPES`, `INBOUND_FORMATS`, `COMPETITION_METRICS`,
  `COMPETITION_STATUSES`, `COMPETITION_ENROLLMENTS`, `MAX_OPEN_COMPETITIONS`.
- README section "White-label (platform users)" and `examples/white_label.py`.

## [0.5.2] - 2026-10-15

The public thesis API (`https://id.cabalspy.xyz/thesis/v1/...`) and its live socket
(`wss://id.cabalspy.xyz/thesis/v1/ws/{chain}/{mint}`) now require your instance's public
client_id on every call. It is shown in the dashboard next to the API key; it is not a secret
and not the API key. The Data API (`CabalSpyID`, API key) is unchanged.

### Changed (breaking for the thesis client)

- `ThesisClient` / `AsyncThesisClient` require `client_id`:
  `ThesisClient(access_token=None, *, client_id="csid_...", scope=None, ...)`. Without it (or with
  an empty string) the constructor raises `AuthenticationError` with `code == "client_id_required"`.
- Every call sends the header `X-CSID-Client-Id: <client_id>`; `live()` adds `client_id=<client_id>`
  to the socket URL (`scope="instance"` keeps working with the same client_id). `post()` and
  `reply()` always send `client_id` in the body.

### Added

- New server error codes, mapped to the existing exception classes: `client_id_required` and
  `invalid_client` (401, `AuthenticationError`), `origin_not_allowed` (403, `PermissionError`),
  `rate_limited` (429, `RateLimitError`, `retry_after` from Retry-After, 60 s).
- `ThesisLive` treats the close codes 4401 (`client_id_required` / `invalid_client`) and 4403
  (`origin_not_allowed`) as final (no reconnect) and backs off 60 s after 4429 (`rate_limited`).
- `CLIENT_ID_HEADER` constant.

## [0.5.1] - 2026-10-15

### Changed

- People can sign in with X, Telegram or Google. Types match accounts without X: `x` is
  `None` in userinfo claims and Data API profiles, `twitter` is `None` in profiles, trading
  profile blocks and leaderboards, `telegram` is documented (`https://t.me/<name>` or `""`),
  handles may be `tg.<name>` or `id.<hex>`.

### Added

- `has_x()` and `handle_kind()` helpers and a README section "Users without X".

## [0.5.0] - 2026-10-14

### Added

- Modules `cabalspy_id.api` (Data API, trade stream, login, webhooks) and `cabalspy_id.thesis`
  (thesis methods, `ThesisClient`, `ThesesStream`), exposing the same objects as `cabalspy_id`.
- Packages table (socialfi-api, socialfi-thesis, socialfi-widget) in the README.

## [0.4.1] - 2026-10-14

### Changed

- Package description, keywords, classifiers and README: CabalSpy ID as a SocialFi API & SDK. No code changes.

## [0.4.0] - 2026-10-14

### Added

- `Thesis["reacted_by"]` (who reacted recently) and `Thesis["latest_replies"]` (reply preview).
- Moderation notifications: Data API `thesis_notifications(csid_id)` and
  `appeal_thesis_decision(csid_id, notification_id, message)`; public `ThesisClient.notifications()`,
  `mark_notifications_read()` and `appeal(notification_id, message)`. `TypedDict`s
  `ThesisNotification`, `ThesisNotifications`, `ThesisNotices`; `me()` returns `notices`.
- Webhook types `thesis.reply` (`data["reply"]`) and `thesis.reaction`
  (`thesis_id`, `chain`, `mint`, `emoji`, `on`, `reactions`).
- Error code `reporting_paused` (403, `PermissionError`) documented.

## [0.3.0] - 2026-10-13

### Added

- `scope` (`global` | `instance`) on `list_theses`, `iter_theses`, `thesis_summary` and
  `latest_theses`.
- `ThesesStream` (`client.theses_stream()`, async) for `wss://api-id.cabalspy.xyz/v1/theses/stream`
  (every plan): `subscribe` / `unsubscribe` up to 200 tokens, `subscribe_all` / `unsubscribe_all`,
  subscriptions restored after reconnects, heartbeat watchdog, handlers and async iteration.
- `ThesisClient` / `AsyncThesisClient`: `scope` and `client_id` (reads, `live()`, post attribution).

## [0.2.0] - 2026-10-13

### Added

- Token theses in the Data API (sync and async): `list_theses` / `iter_theses`, `thesis_summary`,
  `thesis`, `thesis_replies` / `iter_thesis_replies`, `latest_theses`, `user_theses`,
  `thesis_eligibility`, and writes in a user's name: `post_thesis`, `reply_to_thesis`,
  `react_to_thesis`, `report_thesis`, `delete_thesis`. `TypedDict`s `Thesis`, `ThesisPosition`,
  `ThesisSummary`, `ThesisEligibility`, `ThesisReactions`.
- `post_raw`. Writes are only retried after the API's own rate limit (`rate_limit_exceeded`),
  never after a server or network error.
- Stream: `events=["trades", "theses"]` and `mint=`; events `thesis`, `thesis.reply`,
  `thesis.reaction`, `thesis.removed`; `stream.theses()` iterator.
- `ThesisClient` / `AsyncThesisClient` for the public thesis API
  (`https://id.cabalspy.xyz/thesis/v1`) with a user's access token, and `ThesisLive` (`.live()`)
  for the public per-token websocket.
- Webhook type `thesis.created`, OAuth scope `thesis`.

## [0.1.0] - 2026-10-13

First release.

### Added

- `CabalSpyID` and `AsyncCabalSpyID` Data API clients for `https://api-id.cabalspy.xyz/v1`:
  `health`, `me`, `users`, `profile`, `wallet_lookup`, `tracker`, `history`, `holdings`,
  `pnl_calendar`, `leaderboard`, `latest_transactions`, with `instance` support, retries with
  backoff, rate limit info, `get_raw` / `pages` and iterators (`iter_users`, `iter_history`,
  `iter_leaderboard`).
- `CabalSpyIDStream` (async, `[stream]` extra) for the live trade stream (`/v1/stream`):
  auto-reconnect, heartbeat watchdog, fatal configuration errors, async iteration.
- `CabalSpyIDAuth` and `AsyncCabalSpyIDAuth` OpenID Connect helpers: discovery,
  `create_authorization_url` (PKCE S256, state, nonce), `handle_callback`, `exchange_code`,
  `refresh`, `revoke`, `userinfo`, `verify_id_token` and `verify_access_token` (ES256 via JWKS,
  PyJWT), `is_limited`, `generate_pkce`.
- `verify_webhook` / `sign_webhook` for Standard Webhooks signatures.
- `TypedDict` response types and `py.typed`.
- Exceptions: `BadRequestError`, `AuthenticationError`, `PermissionError`, `PlanUserLimitError`,
  `NotFoundError`, `RateLimitError`, `ServerError`, `APIConnectionError`,
  `InvalidResponseError`, `OAuthError`, `TokenVerificationError`, `WebhookVerificationError`.

[0.7.0]: https://github.com/CabalSpy/cabalspy-id-python/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/CabalSpy/cabalspy-id-python/compare/v0.5.2...v0.6.0
[0.5.2]: https://github.com/CabalSpy/cabalspy-id-python/compare/v0.5.1...v0.5.2
[0.5.1]: https://github.com/CabalSpy/cabalspy-id-python/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/CabalSpy/cabalspy-id-python/compare/v0.4.1...v0.5.0
[0.4.1]: https://github.com/CabalSpy/cabalspy-id-python/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/CabalSpy/cabalspy-id-python/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/CabalSpy/cabalspy-id-python/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/CabalSpy/cabalspy-id-python/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/CabalSpy/cabalspy-id-python/releases/tag/v0.1.0
