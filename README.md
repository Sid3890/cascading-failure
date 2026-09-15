# Cascading Failure Prototype — Backend

FastAPI backend for a planner-facing prototype that models interdependent infrastructure and estimates how disruptions spread.

## Technology stack

- Python 3.12 and FastAPI: typed HTTP API with OpenAPI generated from the same models used at runtime.
- Pydantic: validation and a stable frontend contract.
- Uvicorn: local ASGI server.
- Planned: PostgreSQL + PostGIS for durable network/geospatial data; NetworkX for graph and cascade calculations; Redis/Celery only if simulations need background workers.

Phase 2 uses a local SQLite database for durable network data. It avoids external setup while preserving a clean repository boundary for a later move to PostgreSQL/PostGIS.

## Workflow

`network data → network graph → failure scenario → redistribution/cascade simulation → impact and criticality metrics → comparison view`

Phase 3 is implemented: scenarios and simulation results are stored in the same SQLite database as network data. The deterministic prototype model redirects load across connected assets, detects overloads, applies dependency effects, and returns a timeline suitable for a map or chart.

Phase 4 is implemented: the API ranks nodes and connections by simulated failure impact, path betweenness, or load ratio, and compares up to ten same-network scenarios by service loss.

## Development

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
python -m uvicorn app.main:app --reload --env-file .env
```

Open `http://localhost:8000/docs` for live API documentation. The database is created at `data/cascading_failure.db`; edit `.env` before starting if the frontend runs on another origin or if you want to enable `API_KEY` protection.

## Test and diagnose

Run the automated checks from the project root:

```powershell
python -m pytest
python -m ruff check .
```

Run the API server in one terminal, then use a second PowerShell terminal for a basic smoke test:

```powershell
Invoke-RestMethod http://localhost:8000/health
Invoke-RestMethod http://localhost:8000/api/v1/meta
```

If `API_KEY` is set in `.env`, include it for API routes:

```powershell
Invoke-RestMethod http://localhost:8000/api/v1/meta -Headers @{"X-API-Key"="your-secret-value"}
```

For request validation errors, check the terminal running Uvicorn and inspect the JSON response's `error` and `request_id` fields. You can view mutating API activity through `GET /api/v1/audit-events`.

## Docker

```powershell
Copy-Item .env.example .env
docker compose up --build
```

The Compose setup exposes the API at port 8000 and stores SQLite data in the local `data` folder.

The detailed integration agreement is in [docs/API_CONTRACT.md](docs/API_CONTRACT.md).

## Local data

The server creates `data/cascading_failure.db` automatically. It is intentionally excluded from Git. Set `DATABASE_PATH` to use a different SQLite file.
