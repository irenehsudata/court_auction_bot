from __future__ import annotations

from collections.abc import Generator
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from court_auction_api.config import Settings
from court_auction_api.database import Base, create_engine_and_sessionmaker, session_dependency
from court_auction_api.schemas import BidAccepted, BidCreate, CourtRead, SlotRead, SlotState
from court_auction_api.services import (
    Clock,
    BidValidationError,
    ConflictError,
    InvalidStateError,
    NotFoundError,
    SlotLockRegistry,
    approve_slot,
    create_bid,
    get_slot,
    list_courts,
    list_slots,
    reject_slot,
)

UI_DIR = Path(__file__).resolve().parent / "ui"


def create_app(settings: Settings | None = None, clock: Clock | None = None) -> FastAPI:
    resolved_settings = settings or Settings.from_env()
    engine, session_factory = create_engine_and_sessionmaker(resolved_settings.database_url)
    resolved_clock = clock or Clock(ZoneInfo(resolved_settings.timezone))
    locks = SlotLockRegistry()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        Base.metadata.create_all(bind=engine)
        session = session_factory()
        try:
            from court_auction_api.services import sync_horizon

            sync_horizon(session, resolved_settings, resolved_clock)
        finally:
            session.close()
        yield

    app = FastAPI(title="Court Auction API", version="0.1.0", lifespan=lifespan)
    app.state.settings = resolved_settings
    app.state.clock = resolved_clock
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.locks = locks
    app.mount("/assets", StaticFiles(directory=UI_DIR), name="assets")

    def get_session() -> Generator[Session, None, None]:
        yield from session_dependency(session_factory)

    def require_admin_token(x_admin_token: str = Header(...)) -> None:
        if x_admin_token != resolved_settings.admin_token:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid admin token")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(UI_DIR / "index.html")

    @app.get("/courts", response_model=list[CourtRead])
    def get_courts(session: Session = Depends(get_session)) -> list[CourtRead]:
        courts = list_courts(session)
        return [CourtRead.model_validate(court) for court in courts]

    @app.get("/slots", response_model=list[SlotRead])
    def get_slots(
        play_date: date | None = Query(default=None),
        session: Session = Depends(get_session),
    ) -> list[SlotRead]:
        return list_slots(session, resolved_settings, resolved_clock, play_date=play_date)

    @app.get("/slots/{slot_id}", response_model=SlotRead)
    def get_slot_by_id(slot_id: int, session: Session = Depends(get_session)) -> SlotRead:
        try:
            return get_slot(session, resolved_settings, resolved_clock, slot_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    @app.post("/slots/{slot_id}/bids", response_model=BidAccepted, status_code=status.HTTP_201_CREATED)
    def post_bid(
        slot_id: int,
        payload: BidCreate,
        x_user_id: str = Header(...),
        session: Session = Depends(get_session),
    ) -> BidAccepted:
        try:
            slot, accepted_bid = create_bid(
                session=session,
                settings=resolved_settings,
                clock=resolved_clock,
                locks=locks,
                slot_id=slot_id,
                user_id=x_user_id,
                amount_gbp=payload.amount_gbp,
            )
        except NotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except InvalidStateError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        except BidValidationError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except ConflictError as exc:
            detail = {"message": str(exc)}
            if exc.minimum_valid_bid is not None:
                detail["minimum_valid_bid"] = f"{exc.minimum_valid_bid:.2f}"
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail) from exc
        return BidAccepted(slot=slot, accepted_bid=accepted_bid)

    @app.get("/admin/slots", response_model=list[SlotRead], dependencies=[Depends(require_admin_token)])
    def admin_list_slots(
        state: SlotState | None = Query(default=None),
        session: Session = Depends(get_session),
    ) -> list[SlotRead]:
        return list_slots(session, resolved_settings, resolved_clock, state=state)

    @app.get("/admin/slots/{slot_id}", response_model=SlotRead, dependencies=[Depends(require_admin_token)])
    def admin_get_slot(slot_id: int, session: Session = Depends(get_session)) -> SlotRead:
        try:
            return get_slot(session, resolved_settings, resolved_clock, slot_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    @app.post(
        "/admin/slots/{slot_id}/approve",
        response_model=SlotRead,
        dependencies=[Depends(require_admin_token)],
    )
    def admin_approve_slot(slot_id: int, session: Session = Depends(get_session)) -> SlotRead:
        try:
            return approve_slot(session, resolved_settings, resolved_clock, locks, slot_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except InvalidStateError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    @app.post(
        "/admin/slots/{slot_id}/reject",
        response_model=SlotRead,
        dependencies=[Depends(require_admin_token)],
    )
    def admin_reject_slot(slot_id: int, session: Session = Depends(get_session)) -> SlotRead:
        try:
            return reject_slot(session, resolved_settings, resolved_clock, locks, slot_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except InvalidStateError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    return app


app = create_app()
