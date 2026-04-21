from __future__ import annotations

from datetime import date, time
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Numeric, String, Time, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from court_auction_api.database import Base


class Court(Base):
    __tablename__ = "courts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))

    slots: Mapped[list["AuctionSlot"]] = relationship(back_populates="court")


class AuctionSlot(Base):
    __tablename__ = "auction_slots"
    __table_args__ = (
        UniqueConstraint("court_id", "play_date", "start_time", name="uq_slot_court_date_start"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    court_id: Mapped[int] = mapped_column(ForeignKey("courts.id"), index=True)
    play_date: Mapped[date] = mapped_column(Date, index=True)
    bidding_date: Mapped[date] = mapped_column(Date, index=True)
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    opens_at: Mapped[str] = mapped_column(String(64))
    closes_at: Mapped[str] = mapped_column(String(64))
    rejected_at: Mapped[str | None] = mapped_column(String(64), nullable=True)

    court: Mapped["Court"] = relationship(back_populates="slots")
    bids: Mapped[list["Bid"]] = relationship(back_populates="slot", cascade="all, delete-orphan")
    reservation: Mapped["Reservation | None"] = relationship(
        back_populates="slot", cascade="all, delete-orphan", uselist=False
    )


class Bid(Base):
    __tablename__ = "bids"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    slot_id: Mapped[int] = mapped_column(ForeignKey("auction_slots.id"), index=True)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    amount_gbp: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    created_at: Mapped[str] = mapped_column(String(64), index=True)

    slot: Mapped["AuctionSlot"] = relationship(back_populates="bids")


class Reservation(Base):
    __tablename__ = "reservations"
    __table_args__ = (UniqueConstraint("slot_id", name="uq_reservation_slot"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    slot_id: Mapped[int] = mapped_column(ForeignKey("auction_slots.id"), index=True)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    winning_bid_id: Mapped[int] = mapped_column(ForeignKey("bids.id"), unique=True)
    confirmed_at: Mapped[str] = mapped_column(String(64))

    slot: Mapped["AuctionSlot"] = relationship(back_populates="reservation")
    winning_bid: Mapped["Bid"] = relationship()
