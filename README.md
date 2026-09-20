# HPC Performance Platform T01

## Run
Copy `.env.example` to `.env`, then set all required secrets before starting:
```bash
# from repository root
set -a && . ./.env && set +a
docker compose --env-file .env -f infra/docker-compose.yml up -d
cd backend
python -m venv .venv
.venv/Scripts/pip install -e .
# Alembic commands are run from backend (the alembic.ini script root).
.venv/Scripts/python -m alembic upgrade head
.venv/Scripts/python -m alembic downgrade base
.venv/Scripts/python -m alembic upgrade head
.venv/Scripts/python -m pytest -q
```
Windows PowerShell equivalent: `$env:HPC_JWT_SECRET='...'`; use `docker compose --env-file .env -f infra/docker-compose.yml up -d --build` and `.venv\\Scripts\\python.exe -m alembic upgrade head` from `backend`.

The production compose stack contains `backend` (FastAPI/Uvicorn) and `frontend` (Nginx). Nginx proxies `/api/`, `/health/`, `/docs`, and `/openapi.json` to FastAPI; SPA routes fall back to `index.html`. Set `APP_PORT` (default `8080`) and `APP_BIND` (default `0.0.0.0`) for the public listener.

Required: `HPC_JWT_SECRET` (at least 32 bytes; production must be unique), `POSTGRES_DB`, `POSTGRES_USER`, and `POSTGRES_PASSWORD` for Docker. Optional: `HPC_DATABASE_URL` (defaults to SQLite), `HPC_REDIS_URL`, `HPC_BOOTSTRAP_ADMIN_EMAIL`, and `HPC_BOOTSTRAP_ADMIN_PASSWORD` (dev/test only). Docker service ports bind to loopback by default for databases; set `POSTGRES_BIND`/`REDIS_BIND` only when host access is explicitly required.
