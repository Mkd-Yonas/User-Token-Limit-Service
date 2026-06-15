# Token Limit Service (TLS)

> **Production-grade token quota enforcement sidecar for LLM systems.**
> Built with FastAPI · PostgreSQL · Redis · Prometheus · Docker

---

## What Is This?

TLS is a **standalone FastAPI microservice** that enforces token quotas and rate limits for LLM/AI systems. The RAG FastAPI calls TLS before and after every LLM request. Next.js frontend calls TLS to show usage dashboards.

**TLS never touches the LLM itself — it only validates and records.**

```
┌─────────────┐     ┌─────────────┐     ┌─────────────────┐
│   Next.js   │────▶│  RAG FastAPI│────▶│  LLM (vLLM)     │
│  (Frontend) │     │  (Gateway)  │     │  Keural-SFT2    │
└─────────────┘     └──────┬──────┘     └─────────────────┘
                           │                      │
                    [check]│[consume]              │
                           ▼                      ▼
                    ┌─────────────┐        ┌─────────────┐
                    │     TLS     │        │  Spring API │
                    │  (This svc) │        │  (Database) │
                    └──────┬──────┘        └─────────────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
          ┌──────┐   ┌──────────┐  ┌──────────┐
          │Redis │   │PostgreSQL│  │Prometheus│
          └──────┘   └──────────┘  └──────────┘
```

---

## How It Works

1. **RAG FastAPI calls `/v1/limits/check` before every LLM request** → TLS checks if the user has quota. Returns `allowed: true` or `429 blocked`.
2. **RAG FastAPI calls `/v1/limits/consume` after every LLM response** → TLS records actual tokens used and updates the balance.
3. **Next.js calls `/v1/limits/usage`** → TLS returns daily/monthly usage for the dashboard.

---

## Project Structure

```
User-Token-Limit-Service/
├── app/
│   ├── main.py              # FastAPI app + health endpoints + reaper scheduler
│   ├── config.py            # All environment variables (Pydantic Settings)
│   ├── dependencies.py      # PostgreSQL session, Redis client, API key auth
│   ├── reaper_job.py        # Standalone reaper script (for K8s CronJob)
│   ├── models/
│   │   ├── database.py      # SQLAlchemy ORM models (4 tables)
│   │   └── schemas.py       # Pydantic request/response schemas
│   ├── routers/
│   │   ├── limits.py        # /v1/limits/* endpoints
│   │   └── admin.py         # /v1/admin/* endpoints
│   ├── services/
│   │   ├── limit_checker.py # Pre-flight check logic
│   │   ├── limit_consumer.py# Post-flight consume logic
│   │   ├── quota_service.py # Daily/monthly quota calculations
│   │   ├── rate_limiter.py  # Redis sliding-window rate limiter
│   │   └── reaper.py        # Stale request cleanup
│   └── utils/
│       ├── token_estimator.py # Model cost multipliers
│       └── idempotency.py     # request_id deduplication
├── migrations/
│   ├── env.py               # Alembic async config
│   └── versions/
│       └── 0001_initial_schema.py  # Full schema + 3 default tiers
├── tests/
│   ├── conftest.py          # fakeredis + aiosqlite fixtures
│   ├── unit/                # Token estimator unit tests
│   └── integration/         # Full API integration tests
├── k8s/
│   ├── deployment.yaml      # Kubernetes deployment + secret
│   ├── service.yaml         # ClusterIP service
│   └── cronjob-reaper.yaml  # Reaper CronJob (every 1 min)
├── docker/
│   ├── Dockerfile           # Multi-stage: base → prod → reaper
│   └── docker-compose.yml   # Full local stack (PG + Redis + Prometheus)
├── prometheus/
│   └── prometheus.yml       # Prometheus scrape config
├── .env.example             # All required environment variables
├── requirements.txt         # Production dependencies
├── requirements-dev.txt     # Dev + test dependencies
├── pyproject.toml           # Build config + all dependencies
└── alembic.ini              # Alembic migration config
```

---

## Quick Start

### Prerequisites
- Docker + Docker Compose installed on your server
- Ports `8000`, `5432`, `6379`, `9090` available

### Run It

```bash
# 1. Clone
git clone https://github.com/Mkd-Yonas/User-Token-Limit-Service.git
cd User-Token-Limit-Service

# 2. Create config
cp .env.example .env

# 3. Start all services
docker compose -f docker/docker-compose.yml up -d

# 4. Verify
curl http://localhost:8000/health/ready
# Expected: {"status":"ok","postgres":"ok","redis":"ok"}

# 5. Open API docs
# http://localhost:8000/docs
```

> Migrations run automatically on startup. Three default tiers (`free`, `pro`, `enterprise`) are seeded.

### Stop / Remove

```bash
# Stop (keeps data)
docker compose -f docker/docker-compose.yml down

# Remove everything including data
docker compose -f docker/docker-compose.yml down -v --rmi all
```

---

## What Starts When You Run Docker Compose

| Container | Port | Purpose |
|-----------|------|---------|
| `docker-tls-1` | 8000 | TLS FastAPI service |
| `docker-postgres-1` | 5432 | Usage storage (partitioned by month) |
| `docker-redis-1` | 6379 | Rate limiting + quota cache |
| `docker-prometheus-1` | 9090 | Metrics monitoring |

---

## API Endpoints

**Base URL:** `http://your-server:8000/v1`
**Auth:** `Authorization: Bearer <API_KEY>` header on every request.

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/health/live` | None | Is the process up? |
| GET | `/health/ready` | None | Are PG + Redis connected? |
| POST | `/v1/limits/check` | Service key | Pre-flight quota check |
| POST | `/v1/limits/consume` | Service key | Post-flight token deduction |
| GET | `/v1/limits/usage` | Service key | Current usage for a user |
| GET | `/v1/limits/history` | Service key | Paginated request history |
| POST | `/v1/admin/limits` | Admin key | Override limits for a user |
| POST | `/v1/admin/refill` | Admin key | Add credits to a user |
| GET | `/v1/admin/tiers` | Admin key | List all tiers |
| POST | `/v1/admin/tiers` | Admin key | Create or update a tier |

---

## API Examples

### POST `/v1/limits/check` — Before LLM call
```json
Request:
{
  "user_id": "uuid",
  "estimated_input_tokens": 1500,
  "estimated_output_tokens": 500,
  "model_id": "gpt-4o",
  "request_id": "uuid"
}

Response 200 (allowed):
{
  "allowed": true,
  "request_id": "uuid",
  "remaining_tokens": 84500,
  "resets_at": "2026-06-12T00:00:00Z",
  "tier": "pro"
}

Response 429 (blocked):
{
  "allowed": false,
  "reason": "TOKEN_QUOTA_EXCEEDED",
  "limit_type": "daily_tokens",
  "current_usage": 100000,
  "limit": 100000,
  "resets_at": "2026-06-12T00:00:00Z",
  "suggested_action": "UPGRADE_TIER"
}
```

### POST `/v1/limits/consume` — After LLM response
```json
Request:
{
  "user_id": "uuid",
  "request_id": "uuid",
  "actual_input_tokens": 1450,
  "actual_output_tokens": 620,
  "model_id": "gpt-4o"
}

Response 200:
{
  "consumed": true,
  "total_deducted": 2070,
  "new_balance": 82430,
  "overage": 0,
  "refunded": 0
}
```

### GET `/v1/limits/usage?user_id=<uuid>`
```json
{
  "user_id": "uuid",
  "tier": "free",
  "daily_used": 3500,
  "daily_limit": 10000,
  "monthly_used": 45000,
  "monthly_limit": 100000,
  "resets_at": "2026-06-12T00:00:00Z",
  "period_date": "2026-06-11"
}
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TLS_DATABASE_URL` | `postgresql+asyncpg://tls:secret@localhost:5432/tls` | PostgreSQL connection |
| `TLS_REDIS_URL` | `redis://localhost:6379/0` | Redis connection |
| `TLS_API_KEY` | `sk-tls-changeme` | Service key — RAG FastAPI uses this |
| `TLS_ADMIN_API_KEY` | `sk-tls-admin-changeme` | Admin key — admin panel uses this |
| `TLS_DEFAULT_TIER` | `free` | Tier for users not in the database |
| `TLS_GRACE_PERCENTAGE` | `5` | % overage allowed before flagging |
| `TLS_STRICT_MODE` | `false` | Block requests exceeding grace % |
| `TLS_ENABLE_ORG_LIMITS` | `true` | Enable org-level limits |
| `TLS_ENABLE_CONCURRENT_LIMITS` | `true` | Enable concurrent request limits |
| `TLS_ENABLE_MODEL_MULTIPLIERS` | `true` | Apply model cost multipliers |
| `TLS_REAPER_INTERVAL_MINUTES` | `1` | How often reaper checks for stuck requests |
| `TLS_REAPER_STALE_THRESHOLD_MINUTES` | `5` | Age before a pending request is reaped |

> **Change `TLS_API_KEY` and `TLS_ADMIN_API_KEY` before going to production.**

---

## Default Tiers (seeded automatically)

| Tier | Daily Tokens | Monthly Tokens | RPM | Concurrent |
|------|-------------|----------------|-----|-----------|
| `free` | 10,000 | 100,000 | 10 | 3 |
| `pro` | 100,000 | 2,000,000 | 60 | 10 |
| `enterprise` | 1,000,000 | 20,000,000 | 200 | 50 |

---

## Model Cost Multipliers

| Model | Multiplier |
|-------|-----------|
| `gpt-4o` | 1.0× (baseline) |
| `gpt-4o-mini` | 0.25× |
| `claude-3-5-sonnet` / `claude-sonnet-4-6` | 1.0× |
| `claude-3-opus` / `claude-opus-4-8` | 3.0× |
| `claude-3-haiku` / `claude-haiku-4-5` | 0.25× |
| `mkd-hossain/keural-sft2` | 1.0× |

Add custom models in [app/utils/token_estimator.py](app/utils/token_estimator.py).

---

## RAG FastAPI Integration

TLS integrates into the RAG FastAPI (`mkd-keural-be-fastapi`) in two steps.

### Step 1 — Add `app/services/tls_client.py`

```python
import os
import logging
import httpx

logger = logging.getLogger(__name__)

TLS_BASE_URL = os.getenv("TLS_BASE_URL", "http://localhost:8000")
TLS_API_KEY  = os.getenv("TLS_API_KEY", "sk-tls-changeme")
TLS_MODEL_ID = "mkd-hossain/keural-sft2"


def tls_check(user_id: str, request_id: str, estimated_input: int, estimated_output: int) -> tuple[dict, int]:
    try:
        resp = httpx.post(
            f"{TLS_BASE_URL}/v1/limits/check",
            headers={"Authorization": f"Bearer {TLS_API_KEY}"},
            json={
                "user_id": user_id,
                "request_id": request_id,
                "estimated_input_tokens": estimated_input,
                "estimated_output_tokens": estimated_output,
                "model_id": TLS_MODEL_ID,
            },
            timeout=5.0,
        )
        return resp.json(), resp.status_code
    except Exception as e:
        logger.error("TLS check failed: %s", e)
        return {"allowed": True}, 200  # fail open — don't block user if TLS is down


def tls_consume(user_id: str, request_id: str, actual_input: int, actual_output: int) -> None:
    try:
        httpx.post(
            f"{TLS_BASE_URL}/v1/limits/consume",
            headers={"Authorization": f"Bearer {TLS_API_KEY}"},
            json={
                "user_id": user_id,
                "request_id": request_id,
                "actual_input_tokens": actual_input,
                "actual_output_tokens": actual_output,
                "model_id": TLS_MODEL_ID,
            },
            timeout=5.0,
        )
    except Exception as e:
        logger.error("TLS consume failed: %s", e)
```

### Step 2 — Modify the LLM endpoint

Wrap the `_client.chat.completions.create()` call with TLS check and consume:

```python
from app.services.tls_client import tls_check, tls_consume
import uuid

@app.post("/ask", response_model=QueryResponse)
def ask(request: ChatRequest):  # ChatRequest already has user_id and room_id

    # Generate a unique ID for this specific message
    tls_request_id = str(uuid.uuid4())

    # Estimate tokens before the LLM call
    estimated_input  = len(request.query) // 4 + 800  # query + RAG context overhead
    estimated_output = 512                             # MAX_TOKENS

    # ── TLS Check (before LLM) ────────────────────────────────────────────────
    tls_result, status_code = tls_check(
        user_id=request.user_id,
        request_id=tls_request_id,
        estimated_input=estimated_input,
        estimated_output=estimated_output,
    )
    if status_code == 429:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "Token quota exceeded",
                "reason": tls_result.get("reason"),
                "resets_at": tls_result.get("resets_at"),
            }
        )

    # ... existing retrieval and LLM call ...
    response = _client.chat.completions.create(...)

    # ── TLS Consume (after LLM) ───────────────────────────────────────────────
    usage = response.usage
    tls_consume(
        user_id=request.user_id,
        request_id=tls_request_id,
        actual_input=usage.prompt_tokens,
        actual_output=usage.completion_tokens,
    )
```

### FastAPI environment variables needed

```bash
TLS_API_KEY=sk-tls-changeme
TLS_BASE_URL=http://localhost:8000   # or http://tls:8000 if running in Docker together
```

---

## Next.js Integration

**Never expose `TLS_API_KEY` to the browser.** Always proxy through server-side routes.

```typescript
// app/api/tls/usage/route.ts
import { NextRequest, NextResponse } from "next/server";

const TLS_BASE = process.env.TLS_BASE_URL!;
const TLS_API_KEY = process.env.TLS_API_KEY!;

export async function GET(req: NextRequest) {
  const userId = await getUserFromSession(req); // your auth function
  if (!userId) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const res = await fetch(`${TLS_BASE}/v1/limits/usage?user_id=${userId}`, {
    headers: { Authorization: `Bearer ${TLS_API_KEY}` },
    cache: "no-store",
  });

  return NextResponse.json(await res.json());
}
```

**Next.js environment variables needed:**
```bash
TLS_API_KEY=sk-tls-changeme
TLS_BASE_URL=http://tls:8000
```

---

## Running Migrations Manually

```bash
# Apply all migrations
TLS_DATABASE_URL=postgresql+asyncpg://tls:secret@localhost:5432/tls alembic upgrade head

# Create a new migration after model changes
alembic revision --autogenerate -m "describe your change"

# Rollback one step
alembic downgrade -1
```

> Inside Docker Compose, migrations run automatically before the server starts.

---

## Running Tests

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

> Tests use `fakeredis` and `aiosqlite` — no real PostgreSQL or Redis needed.

---

## Kubernetes Deployment

```bash
# Build and push image
docker build -f docker/Dockerfile --target prod -t your-registry/user-token-limit-service:latest .
docker push your-registry/user-token-limit-service:latest

# Edit k8s/deployment.yaml — update image URL and Secret values

# Deploy
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
kubectl apply -f k8s/cronjob-reaper.yaml
```

---

## Monitoring

- **Prometheus** → `http://localhost:9090`
- **Metrics endpoint** → `http://localhost:8000/metrics`

| Metric | Alert When |
|--------|-----------|
| `tls_request_duration_seconds` p99 | > 50ms (check), > 100ms (consume) |
| `tls_requests_total{result="blocked"}` | > 10% of total requests |
| `tls_reaper_reaped_total` | > 5% of requests |

---

## Security

| Layer | Implementation |
|-------|---------------|
| Authentication | `Authorization: Bearer <key>` header |
| Two permission levels | Service key (`/limits/*`) vs Admin key (`/admin/*`) |
| Double-billing prevention | `request_id` unique constraint at DB + Redis level |
| Audit trail | All limit changes logged to `tls_limit_changes` table |
| No LLM access | TLS never reads prompts or responses |

---

## GitHub

**Repository:** https://github.com/MKD-CORP/User-Token-Limit-Service

Open a GitHub Issue for bugs or integration questions.
