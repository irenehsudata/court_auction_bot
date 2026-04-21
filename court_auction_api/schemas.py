from __future__ import annotations

from datetime import date, time
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator


class SlotState(str, Enum):
    NOT_OPEN_YET = "NOT_OPEN_YET"
    OPEN = "OPEN"
    CLOSED_PENDING_ADMIN = "CLOSED_PENDING_ADMIN"
    CLOSED_NO_BIDS = "CLOSED_NO_BIDS"
    RESERVED = "RESERVED"
    CLOSED_UNASSIGNED = "CLOSED_UNASSIGNED"


class CourtRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str


class BidCreate(BaseModel):
    amount_gbp: Decimal = Field(..., examples=["12.50"])

    @field_validator("amount_gbp", mode="before")
    @classmethod
    def validate_amount_type(cls, value: object) -> object:
        if not isinstance(value, str):
            raise ValueError("amount_gbp must be a string decimal value")
        return value

    @field_validator("amount_gbp")
    @classmethod
    def validate_decimal_places(cls, value: Decimal) -> Decimal:
        quantized = value.quantize(Decimal("0.01"))
        if quantized != value:
            raise ValueError("amount_gbp must have at most 2 decimal places")
        if value <= Decimal("0"):
            raise ValueError("amount_gbp must be greater than 0")
        return value

    @field_serializer("amount_gbp")
    def serialize_amount(self, value: Decimal) -> str:
        return f"{value:.2f}"


class BidSummary(BaseModel):
    user_id: str
    amount_gbp: Decimal
    created_at: str

    @field_serializer("amount_gbp")
    def serialize_amount(self, value: Decimal) -> str:
        return f"{value:.2f}"


class ReservationSummary(BaseModel):
    user_id: str
    amount_gbp: Decimal
    confirmed_at: str

    @field_serializer("amount_gbp")
    def serialize_amount(self, value: Decimal) -> str:
        return f"{value:.2f}"


class SlotRead(BaseModel):
    id: int
    court: CourtRead
    play_date: date
    bidding_date: date
    start_time: time
    end_time: time
    opens_at: str
    closes_at: str
    state: SlotState
    highest_bid: BidSummary | None = None
    reservation: ReservationSummary | None = None


class BidAccepted(BaseModel):
    slot: SlotRead
    accepted_bid: BidSummary
