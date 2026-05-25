# Local Setup

This guide is for local portfolio review. It does not describe the original production deployment.

## Docker

```bash
cp .env.example .env
docker compose up --build
```

Open:

- Frontend: `http://localhost:8080`
- API health: `http://localhost:8000/health`

Run migrations inside the API container if you want to exercise database-backed flows:

```bash
docker compose exec app alembic upgrade head
```

## Backend Without Docker

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
```

The backend expects PostgreSQL and Redis URLs from `.env`.

## Frontend Without Docker

```bash
cd frontend
npm install
npm run dev
```

## External Integrations

LLM, OCR, OAuth, email, payment, and Telegram integrations are disabled until placeholder values in `.env` are replaced with real credentials. Do not commit real credentials.

For portfolio review, the most useful paths are the service modules, worker orchestration, schema migrations, tests, and frontend case workflow.
