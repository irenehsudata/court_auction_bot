from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from court_auction_api.config import Settings
from court_auction_api.main import create_app
from court_auction_api.services import Clock


class FixedClock(Clock):
    def __init__(self, now_value: datetime, timezone: ZoneInfo) -> None:
        super().__init__(timezone=timezone)
        self._now_value = now_value.astimezone(timezone)

    def now(self) -> datetime:
        return self._now_value

    def set(self, value: datetime) -> None:
        self._now_value = value.astimezone(self.timezone)


@pytest.fixture
def clock() -> FixedClock:
    timezone = ZoneInfo("Europe/London")
    return FixedClock(datetime(2026, 4, 18, 10, 0, tzinfo=timezone), timezone)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    db_path = tmp_path / "test.db"
    return Settings(database_url=f"sqlite:///{db_path}", admin_token="secret-admin")


@pytest.fixture
def client(settings: Settings, clock: FixedClock) -> TestClient:
    app = create_app(settings=settings, clock=clock)
    with TestClient(app) as test_client:
        yield test_client
