from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from zoneinfo import ZoneInfo

from court_auction_api.services import SlotState


def admin_headers() -> dict[str, str]:
    return {"X-Admin-Token": "secret-admin"}


def bid_headers(user_id: str) -> dict[str, str]:
    return {"X-User-Id": user_id}


def first_slot_id(client) -> int:
    response = client.get("/slots?play_date=2026-04-18")
    response.raise_for_status()
    return response.json()[0]["id"]


def test_root_serves_frontend(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Court Auction Console" in response.text


def test_bootstrap_creates_two_courts_and_rolling_horizon(client, settings):
    courts_response = client.get("/courts")
    assert courts_response.status_code == 200
    assert [court["name"] for court in courts_response.json()] == ["Court 1", "Court 2"]

    slots_response = client.get("/slots")
    slots = slots_response.json()
    assert slots_response.status_code == 200
    assert len(slots) == 14 * 24
    assert len({slot["play_date"] for slot in slots}) == 14
    assert slots[0]["bidding_date"] == "2026-04-10"
    assert slots[0]["opens_at"] == "2026-04-10T09:00:00+01:00"
    assert slots[0]["closes_at"] == "2026-04-10T12:00:00+01:00"

    second_response = client.get("/slots")
    assert len(second_response.json()) == 14 * 24


def test_each_play_date_has_24_slots(client):
    response = client.get("/slots?play_date=2026-04-20")
    assert response.status_code == 200
    slots = response.json()
    assert len(slots) == 24
    assert slots[0]["play_date"] == "2026-04-20"
    assert {slot["court"]["name"] for slot in slots} == {"Court 1", "Court 2"}


def test_bids_before_open_fail(client, clock):
    slot_id = first_slot_id(client)
    clock.set(datetime(2026, 4, 9, 8, 59, tzinfo=ZoneInfo("Europe/London")))
    response = client.post(f"/slots/{slot_id}/bids", headers=bid_headers("user-1"), json={"amount_gbp": "10.50"})
    assert response.status_code == 409
    assert response.json()["detail"] == "slot is not open for bidding"


def test_valid_bid_during_window_succeeds(client, clock):
    slot_id = first_slot_id(client)
    clock.set(datetime(2026, 4, 10, 9, 30, tzinfo=ZoneInfo("Europe/London")))
    response = client.post(f"/slots/{slot_id}/bids", headers=bid_headers("user-1"), json={"amount_gbp": "10.50"})
    assert response.status_code == 201
    body = response.json()
    assert body["accepted_bid"]["amount_gbp"] == "10.50"
    assert body["slot"]["highest_bid"]["user_id"] == "user-1"
    assert body["slot"]["state"] == SlotState.OPEN


def test_bid_after_close_fails(client, clock):
    slot_id = first_slot_id(client)
    clock.set(datetime(2026, 4, 10, 12, 0, tzinfo=ZoneInfo("Europe/London")))
    response = client.post(f"/slots/{slot_id}/bids", headers=bid_headers("user-1"), json={"amount_gbp": "10.50"})
    assert response.status_code == 409
    assert response.json()["detail"] == "slot is not open for bidding"


def test_invalid_amounts_fail(client, clock):
    slot_id = first_slot_id(client)
    clock.set(datetime(2026, 4, 10, 10, 0, tzinfo=ZoneInfo("Europe/London")))

    bad_format = client.post(f"/slots/{slot_id}/bids", headers=bid_headers("user-1"), json={"amount_gbp": 10.5})
    assert bad_format.status_code == 422

    too_precise = client.post(
        f"/slots/{slot_id}/bids", headers=bid_headers("user-1"), json={"amount_gbp": "10.555"}
    )
    assert too_precise.status_code == 422

    wrong_increment = client.post(
        f"/slots/{slot_id}/bids", headers=bid_headers("user-1"), json={"amount_gbp": "10.25"}
    )
    assert wrong_increment.status_code == 400
    assert wrong_increment.json()["detail"] == "amount_gbp must be in increments of 0.50"


def test_lower_equal_or_under_increment_bids_fail(client, clock):
    slot_id = first_slot_id(client)
    clock.set(datetime(2026, 4, 10, 10, 0, tzinfo=ZoneInfo("Europe/London")))
    first = client.post(f"/slots/{slot_id}/bids", headers=bid_headers("user-1"), json={"amount_gbp": "10.50"})
    assert first.status_code == 201

    equal = client.post(f"/slots/{slot_id}/bids", headers=bid_headers("user-2"), json={"amount_gbp": "10.50"})
    assert equal.status_code == 409
    assert equal.json()["detail"]["minimum_valid_bid"] == "11.00"

    under_increment = client.post(
        f"/slots/{slot_id}/bids", headers=bid_headers("user-2"), json={"amount_gbp": "10.75"}
    )
    assert under_increment.status_code == 400


def test_concurrent_bids_produce_one_winner_and_one_conflict(client, clock):
    slot_id = first_slot_id(client)
    clock.set(datetime(2026, 4, 10, 10, 15, tzinfo=ZoneInfo("Europe/London")))

    def submit(user_id: str):
        return client.post(f"/slots/{slot_id}/bids", headers=bid_headers(user_id), json={"amount_gbp": "10.50"})

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(submit, ["user-1", "user-2"]))

    status_codes = sorted(response.status_code for response in responses)
    assert status_codes == [201, 409]
    conflict = next(response for response in responses if response.status_code == 409)
    assert conflict.json()["detail"]["minimum_valid_bid"] == "11.00"


def test_admin_cannot_approve_before_close(client, clock):
    slot_id = first_slot_id(client)
    clock.set(datetime(2026, 4, 10, 10, 0, tzinfo=ZoneInfo("Europe/London")))
    bid = client.post(f"/slots/{slot_id}/bids", headers=bid_headers("user-1"), json={"amount_gbp": "10.50"})
    assert bid.status_code == 201

    response = client.post(f"/admin/slots/{slot_id}/approve", headers=admin_headers())
    assert response.status_code == 409
    assert response.json()["detail"] == "slot is not awaiting admin approval"


def test_approve_creates_single_reservation(client, clock):
    slot_id = first_slot_id(client)
    clock.set(datetime(2026, 4, 10, 10, 0, tzinfo=ZoneInfo("Europe/London")))
    client.post(f"/slots/{slot_id}/bids", headers=bid_headers("user-1"), json={"amount_gbp": "10.50"})
    clock.set(datetime(2026, 4, 10, 12, 1, tzinfo=ZoneInfo("Europe/London")))

    response = client.post(f"/admin/slots/{slot_id}/approve", headers=admin_headers())
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == SlotState.RESERVED
    assert body["reservation"]["user_id"] == "user-1"
    assert body["reservation"]["amount_gbp"] == "10.50"

    second = client.post(f"/admin/slots/{slot_id}/approve", headers=admin_headers())
    assert second.status_code == 409


def test_reject_sets_closed_unassigned(client, clock):
    slot_id = first_slot_id(client)
    clock.set(datetime(2026, 4, 10, 10, 0, tzinfo=ZoneInfo("Europe/London")))
    client.post(f"/slots/{slot_id}/bids", headers=bid_headers("user-1"), json={"amount_gbp": "10.50"})
    clock.set(datetime(2026, 4, 10, 12, 1, tzinfo=ZoneInfo("Europe/London")))

    response = client.post(f"/admin/slots/{slot_id}/reject", headers=admin_headers())
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == SlotState.CLOSED_UNASSIGNED
    assert body["reservation"] is None


def test_slot_states_cover_all_cases(client, clock):
    not_open = client.get("/slots?play_date=2026-04-27").json()[0]
    assert not_open["state"] == SlotState.NOT_OPEN_YET

    open_slot = client.get("/slots?play_date=2026-04-18").json()[0]
    assert open_slot["state"] == SlotState.CLOSED_NO_BIDS

    currently_open = client.get("/slots?play_date=2026-04-26").json()[0]
    assert currently_open["state"] == SlotState.OPEN

    slot_id = first_slot_id(client)
    clock.set(datetime(2026, 4, 10, 10, 0, tzinfo=ZoneInfo("Europe/London")))
    client.post(f"/slots/{slot_id}/bids", headers=bid_headers("user-1"), json={"amount_gbp": "10.50"})
    open_after_bid = client.get(f"/slots/{slot_id}").json()
    assert open_after_bid["state"] == SlotState.OPEN

    clock.set(datetime(2026, 4, 10, 12, 1, tzinfo=ZoneInfo("Europe/London")))
    pending = client.get(f"/slots/{slot_id}").json()
    assert pending["state"] == SlotState.CLOSED_PENDING_ADMIN

    client.post(f"/admin/slots/{slot_id}/approve", headers=admin_headers())
    reserved = client.get(f"/slots/{slot_id}").json()
    assert reserved["state"] == SlotState.RESERVED


def test_admin_list_filters_by_state(client, clock):
    slot_id = first_slot_id(client)
    clock.set(datetime(2026, 4, 10, 10, 0, tzinfo=ZoneInfo("Europe/London")))
    client.post(f"/slots/{slot_id}/bids", headers=bid_headers("user-1"), json={"amount_gbp": "10.50"})
    clock.set(datetime(2026, 4, 10, 12, 1, tzinfo=ZoneInfo("Europe/London")))

    response = client.get("/admin/slots?state=CLOSED_PENDING_ADMIN", headers=admin_headers())
    assert response.status_code == 200
    slots = response.json()
    assert any(slot["id"] == slot_id for slot in slots)


def test_admin_token_is_required(client):
    response = client.get("/admin/slots")
    assert response.status_code == 422
