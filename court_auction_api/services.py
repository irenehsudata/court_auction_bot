from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from threading import Lock
from zoneinfo import ZoneInfo

from sqlalchemy import Select, select
from sqlalchemy.orm import Session, joinedload

from court_auction_api.config import Settings
from court_auction_api.models import AuctionSlot, Bid, Court, Reservation
from court_auction_api.schemas import BidSummary, CourtRead, ReservationSummary, SlotRead, SlotState

MIN_INCREMENT = Decimal("0.50")
SYNC_LOCK = Lock()


class ServiceError(Exception):
    pass


class NotFoundError(ServiceError):
    pass


class InvalidStateError(ServiceError):
    pass


class BidValidationError(ServiceError):
    def __init__(self, message: str, minimum_valid_bid: Decimal | None = None) -> None:
        super().__init__(message)
        self.minimum_valid_bid = minimum_valid_bid


class ConflictError(ServiceError):
    def __init__(self, message: str, minimum_valid_bid: Decimal | None = None) -> None:
        super().__init__(message)
        self.minimum_valid_bid = minimum_valid_bid


class SlotLockRegistry:
    def __init__(self) -> None:
        self._index_lock = Lock()
        self._locks: dict[int, Lock] = {}

    def get_lock(self, slot_id: int) -> Lock:
        with self._index_lock:
            if slot_id not in self._locks:
                self._locks[slot_id] = Lock()
            return self._locks[slot_id]


@dataclass
class Clock:
    timezone: ZoneInfo

    def now(self) -> datetime:
        return datetime.now(tz=self.timezone)


def parse_iso_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


def exact_decimal(value: Decimal | str) -> Decimal:
    try:
        decimal_value = Decimal(value)
    except (InvalidOperation, TypeError) as exc:
        raise BidValidationError("amount_gbp must be a valid decimal string") from exc
    if decimal_value.quantize(Decimal("0.01")) != decimal_value:
        raise BidValidationError("amount_gbp must have at most 2 decimal places")
    return decimal_value


def validate_bid_amount(value: Decimal | str) -> Decimal:
    amount = exact_decimal(value)
    if amount <= Decimal("0"):
        raise BidValidationError("amount_gbp must be greater than 0")
    if amount % MIN_INCREMENT != Decimal("0.00"):
        raise BidValidationError("amount_gbp must be in increments of 0.50")
    return amount


def horizon_bounds(settings: Settings, now: datetime) -> tuple[date, date]:
    start = now.date()
    end = start + timedelta(days=settings.play_horizon_days - 1)
    return start, end


def slot_in_horizon(play_date: date, settings: Settings, now: datetime) -> bool:
    start, end = horizon_bounds(settings, now)
    return start <= play_date <= end


def build_bidding_window(play_date: date, settings: Settings, timezone: ZoneInfo) -> tuple[date, str, str]:
    bidding_date = play_date - timedelta(days=settings.bidding_lead_days)
    opens_at = datetime.combine(bidding_date, settings.bidding_open_time, tzinfo=timezone)
    closes_at = datetime.combine(bidding_date, settings.bidding_close_time, tzinfo=timezone)
    return bidding_date, opens_at.isoformat(), closes_at.isoformat()


def utcnow_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def current_highest_bid(session: Session, slot_id: int) -> Bid | None:
    return session.scalar(
        select(Bid)
        .where(Bid.slot_id == slot_id)
        .order_by(Bid.amount_gbp.desc(), Bid.created_at.asc(), Bid.id.asc())
        .limit(1)
    )


def ensure_seed_data(session: Session) -> list[Court]:
    existing = {court.code: court for court in session.scalars(select(Court)).all()}
    created = False
    for code, name in (("COURT_1", "Court 1"), ("COURT_2", "Court 2")):
        if code not in existing:
            court = Court(code=code, name=name)
            session.add(court)
            existing[code] = court
            created = True
    if created:
        session.commit()
    return [existing["COURT_1"], existing["COURT_2"]]


def sync_horizon(session: Session, settings: Settings, clock: Clock) -> None:
    with SYNC_LOCK:
        now = clock.now()
        timezone = clock.timezone
        courts = ensure_seed_data(session)
        start_date, end_date = horizon_bounds(settings, now)
        existing_keys = {
            (slot.court_id, slot.play_date, slot.start_time)
            for slot in session.scalars(
                select(AuctionSlot).where(AuctionSlot.play_date.between(start_date, end_date))
            ).all()
        }

        created = False
        for day_offset in range(settings.play_horizon_days):
            play_date = start_date + timedelta(days=day_offset)
            bidding_date, opens_at, closes_at = build_bidding_window(play_date, settings, timezone)
            for court in courts:
                for hour in range(7, 19):
                    start_time_value = time(hour=hour, minute=0)
                    end_time_value = time(hour=hour + 1, minute=0)
                    key = (court.id, play_date, start_time_value)
                    if key in existing_keys:
                        continue
                    session.add(
                        AuctionSlot(
                            court_id=court.id,
                            play_date=play_date,
                            bidding_date=bidding_date,
                            start_time=start_time_value,
                            end_time=end_time_value,
                            opens_at=opens_at,
                            closes_at=closes_at,
                            rejected_at=None,
                        )
                    )
                    created = True
        if created:
            session.commit()


def slot_query() -> Select[tuple[AuctionSlot]]:
    return select(AuctionSlot).options(
        joinedload(AuctionSlot.court),
        joinedload(AuctionSlot.bids),
        joinedload(AuctionSlot.reservation).joinedload(Reservation.winning_bid),
    )


def get_slot_or_404(session: Session, slot_id: int) -> AuctionSlot:
    slot = session.execute(slot_query().where(AuctionSlot.id == slot_id)).unique().scalar_one_or_none()
    if slot is None:
        raise NotFoundError("slot not found")
    return slot


def slot_state(slot: AuctionSlot, now: datetime) -> SlotState:
    if slot.reservation is not None:
        return SlotState.RESERVED
    if slot.rejected_at is not None:
        return SlotState.CLOSED_UNASSIGNED

    opens_at = parse_iso_datetime(slot.opens_at)
    closes_at = parse_iso_datetime(slot.closes_at)

    if now < opens_at:
        return SlotState.NOT_OPEN_YET
    if opens_at <= now < closes_at:
        return SlotState.OPEN
    if not slot.bids:
        return SlotState.CLOSED_NO_BIDS
    return SlotState.CLOSED_PENDING_ADMIN


def highest_bid_summary(slot: AuctionSlot) -> BidSummary | None:
    if not slot.bids:
        return None
    highest = max(slot.bids, key=lambda bid: (bid.amount_gbp, -bid.id))
    return BidSummary(
        user_id=highest.user_id,
        amount_gbp=highest.amount_gbp,
        created_at=highest.created_at,
    )


def reservation_summary(slot: AuctionSlot) -> ReservationSummary | None:
    if slot.reservation is None:
        return None
    return ReservationSummary(
        user_id=slot.reservation.user_id,
        amount_gbp=slot.reservation.winning_bid.amount_gbp,
        confirmed_at=slot.reservation.confirmed_at,
    )


def serialize_slot(slot: AuctionSlot, now: datetime) -> SlotRead:
    return SlotRead(
        id=slot.id,
        court=CourtRead.model_validate(slot.court),
        play_date=slot.play_date,
        bidding_date=slot.bidding_date,
        start_time=slot.start_time,
        end_time=slot.end_time,
        opens_at=slot.opens_at,
        closes_at=slot.closes_at,
        state=slot_state(slot, now),
        highest_bid=highest_bid_summary(slot),
        reservation=reservation_summary(slot),
    )


def list_courts(session: Session) -> list[Court]:
    ensure_seed_data(session)
    return session.scalars(select(Court).order_by(Court.id.asc())).all()


def list_slots(
    session: Session,
    settings: Settings,
    clock: Clock,
    play_date: date | None = None,
    state: SlotState | None = None,
) -> list[SlotRead]:
    sync_horizon(session, settings, clock)
    now = clock.now()
    horizon_start, horizon_end = horizon_bounds(settings, now)
    query = slot_query().where(AuctionSlot.play_date.between(horizon_start, horizon_end))
    if play_date is not None:
        query = query.where(AuctionSlot.play_date == play_date)
    slots = (
        session.execute(query.order_by(AuctionSlot.play_date, AuctionSlot.court_id, AuctionSlot.start_time))
        .unique()
        .scalars()
        .all()
    )
    serialized = [serialize_slot(slot, now) for slot in slots]
    if state is None:
        return serialized
    return [slot for slot in serialized if slot.state == state]


def get_slot(session: Session, settings: Settings, clock: Clock, slot_id: int) -> SlotRead:
    sync_horizon(session, settings, clock)
    slot = get_slot_or_404(session, slot_id)
    now = clock.now()
    if not slot_in_horizon(slot.play_date, settings, now):
        raise NotFoundError("slot not found")
    return serialize_slot(slot, now)


def create_bid(
    session: Session,
    settings: Settings,
    clock: Clock,
    locks: SlotLockRegistry,
    slot_id: int,
    user_id: str,
    amount_gbp: Decimal | str,
) -> tuple[SlotRead, BidSummary]:
    sync_horizon(session, settings, clock)
    amount = validate_bid_amount(amount_gbp)
    lock = locks.get_lock(slot_id)
    with lock:
        slot = get_slot_or_404(session, slot_id)
        now = clock.now()
        if not slot_in_horizon(slot.play_date, settings, now):
            raise NotFoundError("slot not found")
        if slot_state(slot, now) != SlotState.OPEN:
            raise InvalidStateError("slot is not open for bidding")

        highest = current_highest_bid(session, slot_id)
        minimum_valid = MIN_INCREMENT if highest is None else highest.amount_gbp + MIN_INCREMENT
        if amount < minimum_valid:
            raise ConflictError("bid is too low", minimum_valid_bid=minimum_valid)

        bid = Bid(slot_id=slot.id, user_id=user_id, amount_gbp=amount, created_at=utcnow_iso())
        session.add(bid)
        session.commit()
        session.expire_all()
        refreshed_slot = get_slot_or_404(session, slot_id)
        return serialize_slot(refreshed_slot, now), BidSummary(
            user_id=bid.user_id, amount_gbp=bid.amount_gbp, created_at=bid.created_at
        )


def approve_slot(
    session: Session,
    settings: Settings,
    clock: Clock,
    locks: SlotLockRegistry,
    slot_id: int,
) -> SlotRead:
    sync_horizon(session, settings, clock)
    lock = locks.get_lock(slot_id)
    with lock:
        slot = get_slot_or_404(session, slot_id)
        now = clock.now()
        if slot_state(slot, now) != SlotState.CLOSED_PENDING_ADMIN:
            raise InvalidStateError("slot is not awaiting admin approval")
        highest = current_highest_bid(session, slot.id)
        if highest is None:
            raise InvalidStateError("slot has no bids to approve")
        slot.reservation = Reservation(
            slot_id=slot.id,
            user_id=highest.user_id,
            winning_bid_id=highest.id,
            confirmed_at=utcnow_iso(),
        )
        session.add(slot.reservation)
        session.commit()
        session.expire_all()
        refreshed_slot = get_slot_or_404(session, slot_id)
        return serialize_slot(refreshed_slot, now)


def reject_slot(
    session: Session,
    settings: Settings,
    clock: Clock,
    locks: SlotLockRegistry,
    slot_id: int,
) -> SlotRead:
    sync_horizon(session, settings, clock)
    lock = locks.get_lock(slot_id)
    with lock:
        slot = get_slot_or_404(session, slot_id)
        now = clock.now()
        current_state = slot_state(slot, now)
        if current_state == SlotState.RESERVED:
            raise InvalidStateError("slot is already reserved")
        if current_state == SlotState.NOT_OPEN_YET or current_state == SlotState.OPEN:
            raise InvalidStateError("slot cannot be rejected before bidding closes")
        if slot.rejected_at is not None:
            raise InvalidStateError("slot is already rejected")
        slot.rejected_at = utcnow_iso()
        session.add(slot)
        session.commit()
        session.expire_all()
        refreshed_slot = get_slot_or_404(session, slot_id)
        return serialize_slot(refreshed_slot, now)
