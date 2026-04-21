from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import time


def _parse_time(value: str) -> time:
    hour_str, minute_str = value.split(":", 1)
    return time(hour=int(hour_str), minute=int(minute_str))


@dataclass(frozen=True)
class Settings:
    database_url: str = "sqlite:///./court_auction.db"
    admin_token: str = "dev-admin-token"
    timezone: str = "Europe/London"
    play_horizon_days: int = 14
    bidding_lead_days: int = 8
    bidding_open_time: time = time(hour=9, minute=0)
    bidding_close_time: time = time(hour=12, minute=0)

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=os.getenv("DATABASE_URL", cls.database_url),
            admin_token=os.getenv("ADMIN_TOKEN", cls.admin_token),
            timezone=os.getenv("TIMEZONE", cls.timezone),
            play_horizon_days=int(os.getenv("PLAY_HORIZON_DAYS", cls.play_horizon_days)),
            bidding_lead_days=int(os.getenv("BIDDING_LEAD_DAYS", cls.bidding_lead_days)),
            bidding_open_time=_parse_time(
                os.getenv("BIDDING_OPEN_TIME", cls.bidding_open_time.strftime("%H:%M"))
            ),
            bidding_close_time=_parse_time(
                os.getenv("BIDDING_CLOSE_TIME", cls.bidding_close_time.strftime("%H:%M"))
            ),
        )
