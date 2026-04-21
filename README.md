# Court Auction API MVP

FastAPI + SQLite service for auctioning two courts across hourly play slots.

## Requirements

- Python 3.10+

## Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn court_auction_api.main:app --reload
```

Then open:

- App UI: `http://127.0.0.1:8000/`
- Swagger docs: `http://127.0.0.1:8000/docs`

## Environment

- `DATABASE_URL` default: `sqlite:///./court_auction.db`
- `ADMIN_TOKEN` default: `dev-admin-token`
- `TIMEZONE` default: `Europe/London`
- `PLAY_HORIZON_DAYS` default: `14`
- `BIDDING_LEAD_DAYS` default: `8`
- `BIDDING_OPEN_TIME` default: `09:00`
- `BIDDING_CLOSE_TIME` default: `12:00`

## Test

```bash
pytest
```
