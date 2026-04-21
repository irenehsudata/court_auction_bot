# Court Auction API MVP

## Summary
- Build a `FastAPI + SQLite` API for 2 fixed courts with hourly slots from `07:00-19:00` in `Europe/London`.
- Support multiple future `play_date`s instead of one configured day.
- Maintain a rolling 14-day horizon of playable dates. For each `play_date`, generate 24 slots total: 12 hours for `Court 1` and 12 for `Court 2`.
- For each `play_date`, expose both:
  - `play_date`: the day the court is used
  - `bidding_date`: `play_date - 8 calendar days`
- All slots on the same `play_date` share the same bidding window:
  - `opens_at = bidding_date 09:00 Europe/London`
  - `closes_at = bidding_date 12:00 Europe/London`
- Example:
  - `play_date = 2026-04-27`
  - `bidding_date = 2026-04-19`
  - bidding window is `2026-04-19 09:00-12:00 Europe/London`

## Key Changes
- Create a small service with app bootstrap, settings, SQLite models, Pydantic schemas, public routes, admin routes, and DB transaction handling.
- Seed 2 courts once: `Court 1`, `Court 2`.
- Auto-generate and maintain slots for the next 14 calendar days in London time. Use an idempotent sync routine called on startup and before slot-listing/bid/admin reads so the horizon stays current without a scheduler.
- Domain model:
  - `Court`
  - `AuctionSlot`: `court_id`, `play_date`, `start_time`, `end_time`, `bidding_date`, `opens_at`, `closes_at`, decision status
  - `Bid`: `slot_id`, `user_id`, `amount_gbp`, `created_at`
  - `Reservation`: approved winning bid for a slot
- Slot states:
  - `NOT_OPEN_YET`
  - `OPEN`
  - `CLOSED_PENDING_ADMIN`
  - `CLOSED_NO_BIDS`
  - `RESERVED`
  - `CLOSED_UNASSIGNED`
- Bid rules:
  - bids allowed only when `opens_at <= now < closes_at`
  - require `X-User-Id`
  - request field is `amount_gbp`
  - `amount_gbp` is a string decimal, e.g. `"12.50"`
  - valid amounts must be multiples of `0.50`
  - each new bid must be at least `0.50` higher than the current highest bid
  - bids are append-only; no edit/cancel in v1
  - use exact decimal handling, not floats
  - highest-bid validation and insert happen in one DB transaction; if another request wins first, return `409` with the new minimum valid amount
- Admin rules:
  - after close, admin can approve only the current highest bid
  - after close, admin can reject the slot, leaving it unassigned
  - rejecting does not fall back to the second-highest bid

## Public APIs / Interfaces
- Public endpoints:
  - `GET /health`
  - `GET /courts`
  - `GET /slots?play_date=YYYY-MM-DD`
  - `GET /slots/{slot_id}`
  - `POST /slots/{slot_id}/bids`
- Bid request:
  - `{ "amount_gbp": "12.50" }`
- Slot responses include:
  - court info
  - `play_date`
  - `bidding_date`
  - slot start/end time
  - `opens_at`
  - `closes_at`
  - computed state
  - current highest bid summary
  - reservation summary if approved
- Admin endpoints with `X-Admin-Token`:
  - `GET /admin/slots?state=CLOSED_PENDING_ADMIN`
  - `GET /admin/slots/{slot_id}`
  - `POST /admin/slots/{slot_id}/approve`
  - `POST /admin/slots/{slot_id}/reject`

## Test Plan
- Bootstrap creates 2 courts only once.
- Horizon sync creates slots for today through the next 13 days in London time and does not duplicate rows on rerun.
- For any `play_date`, `bidding_date`, `opens_at`, and `closes_at` are derived correctly.
- Each `play_date` has exactly 24 slots across the 2 courts.
- Bids before `opens_at` fail.
- Valid bids during the window succeed.
- Bids at or after `closes_at` fail.
- Invalid amounts fail:
  - malformed decimal strings
  - values with more than 2 decimals
  - values not divisible by `0.50`
- Lower, equal, or under-increment bids fail.
- Concurrent bids on the same slot produce one committed leader and one `409`.
- Admin cannot approve or reject before close.
- Approve creates exactly one reservation for the slot’s highest bid.
- Reject leaves the slot `CLOSED_UNASSIGNED` with no reservation.
- State reads correctly for all six slot states.

## Assumptions
- The user-facing API uses pounds, not pence.
- The API supports only the next 14 play dates; dates outside that window are not returned or bid-able.
- All dates and times use `Europe/London`.
- No real auth, payments, refunds, notifications, Telegram/WhatsApp integration, or web UI in this phase.
