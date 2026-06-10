# Token Limit Service (TLS)

> **Production-grade token quota enforcement sidecar for LLM systems.**  
> Built with FastAPI · PostgreSQL · Redis · Prometheus  
> Language: Python 3.11+

---

## What Is This?

TLS is a **standalone microservice** that sits between your API gateway (Spring) and your LLM/RAG systems. It enforces token quotas, rate limits, and usage tracking **without touching the LLM itself**.

```
┌─────────────┐     ┌─────────────┐     ┌─────────────────┐
│   Next.js   │────▶│  Spring API │────▶│  LLM / RAG      │
│   (Client)  │     │  (Gateway)  │     │  (Your Systems) │
└─────────────┘     └──────┬──────┘     └─────────────────┘
                           │
                           ▼
                    ┌─────────────┐
                    │  TLS Module │  ◀── This repository
                    │  (FastAPI)  │
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
          ┌──────┐   ┌──────────┐  ┌──────────┐
          │Redis │   │PostgreSQL│  │Prometheus│
          │(Rate)│   │(Usage)   │  │(Metrics) │
          └──────┘   └──────────┘  └──────────┘
```

**Design principle:** TLS is a sidecar validation service. Your existing systems call TLS *before* and *after* every LLM interaction. TLS never touches the LLM itself.

---

## Features

| Feature | Details |
|---------|---------|
| Pre-flight check | Block requests before they hit the LLM if quota exceeded |
| Post-flight consume | Deduct actual tokens used, refund overestimates |
| Rate limiting | RPM, RPH, TPM, concurrent requests — all Redis-backed |
| Daily & monthly quotas | PostgreSQL-persisted, Redis-cached (5 min TTL) |
| Tier system | Free / Pro / Enterprise with custom overrides per user |
| Model multipliers | gpt-4o=1x, claude-opus=3x, gpt-4o-mini=0.25x, etc. |
| Idempotency | request_id deduplication prevents double-billing |
| Stale request reaper | Auto-releases stuck reservations every minute |
| Audit log | All limit changes tracked in `tls_limit_changes` |
| Prometheus metrics | Latency, 429 rate, reaper stats |
| Health probes | `/health/live` + `/health/ready` for Kubernetes |

---

## Quick Start (Docker Compose)

### Prerequisites
- Docker + Docker Compose installed
- Ports `8000`, `5432`, `6379`, `9090` available

### Steps

```bash
# 1. Clone the repository
git clone https://github.com/Mkd-Yonas/User-Token-Limit-Service.git
cd User-Token-Limit-Service

# 2. Copy and configure environment
cp .env.example .env
# Edit .env — change API keys at minimum

# 3. Start all services
docker compose -f docker/docker-compose.yml up -d

# 4. Verify everything is running
curl http://localhost:8000/health/ready
# Expected: {"status":"ok","postgres":"ok","redis":"ok"}

# 5. Open API docs
open http://localhost:8000/docs
```

Migrations run automatically on startup. Three default tiers (`free`, `pro`, `enterprise`) are seeded.

---

## API Reference

**Base URL:** `http://your-server:8000/v1`  
**Authentication:** All endpoints require `Authorization: Bearer <API_KEY>` header.  
Two keys exist: service key (for Spring) and admin key (for admin operations).

### Endpoints

| Method | Path | Auth | Called By | Purpose |
|--------|------|------|-----------|---------|
| GET | `/health/live` | None | K8s | Liveness probe |
| GET | `/health/ready` | None | K8s | Readiness — checks PG + Redis |
| POST | `/v1/limits/check` | Service key | Spring | Pre-flight quota check |
| POST | `/v1/limits/consume` | Service key | Spring | Post-flight token deduction |
| GET | `/v1/limits/usage` | Service key | Next.js | Current period usage |
| GET | `/v1/limits/history` | Service key | Next.js | Paginated request history |
| POST | `/v1/admin/limits` | Admin key | Admin panel | Set/override user limits |
| POST | `/v1/admin/refill` | Admin key | Billing system | Add credits to user |
| GET | `/v1/admin/tiers` | Admin key | Admin panel | List all tiers |
| POST | `/v1/admin/tiers` | Admin key | Admin panel | Create/update a tier |

---

### POST `/v1/limits/check`

Call this **before** every LLM request.

**Request:**
```json
{
  "user_id": "uuid",
  "org_id": "uuid",
  "estimated_input_tokens": 1500,
  "estimated_output_tokens": 500,
  "model_id": "gpt-4o",
  "request_id": "uuid"
}
```

**Response 200 — Allowed:**
```json
{
  "allowed": true,
  "request_id": "uuid",
  "remaining_tokens": 84500,
  "resets_at": "2026-06-11T00:00:00Z",
  "tier": "pro"
}
```

**Response 429 — Blocked:**
```json
{
  "allowed": false,
  "reason": "TOKEN_QUOTA_EXCEEDED",
  "limit_type": "daily_tokens",
  "current_usage": 100000,
  "limit": 100000,
  "resets_at": "2026-06-11T00:00:00Z",
  "suggested_action": "UPGRADE_TIER"
}
```

---

### POST `/v1/limits/consume`

Call this **after** every LLM response — even on error (use 0 tokens if cancelled).

**Request:**
```json
{
  "user_id": "uuid",
  "request_id": "uuid",
  "actual_input_tokens": 1450,
  "actual_output_tokens": 620,
  "model_id": "gpt-4o",
  "metadata": {
    "conversation_id": "uuid",
    "feature": "rag_chat"
  }
}
```

**Response 200:**
```json
{
  "consumed": true,
  "total_deducted": 2070,
  "new_balance": 82430,
  "overage": 0,
  "refunded": 0
}
```

---

### GET `/v1/limits/usage`

**Query params:** `user_id=<uuid>`

**Response 200:**
```json
{
  "user_id": "uuid",
  "tier": "free",
  "daily_used": 3500,
  "daily_limit": 10000,
  "monthly_used": 45000,
  "monthly_limit": 100000,
  "resets_at": "2026-06-11T00:00:00Z",
  "period_date": "2026-06-10"
}
```

---

### GET `/v1/limits/history`

**Query params:** `user_id=<uuid>&page=1&page_size=20`

**Response 200:**
```json
{
  "user_id": "uuid",
  "page": 1,
  "page_size": 20,
  "total": 142,
  "records": [
    {
      "request_id": "uuid",
      "tokens_input": 1450,
      "tokens_output": 620,
      "tokens_total": 2070,
      "model_id": "gpt-4o",
      "created_at": "2026-06-10T12:00:00Z",
      "metadata": {"feature": "rag_chat"}
    }
  ]
}
```

---

## Spring API Integration

Add this interceptor to your Spring project. It calls TLS before and after every LLM request.

```java
@Component
public class TokenLimitInterceptor implements HandlerInterceptor {

    private static final String TLS_BASE = "http://tls-service/v1";
    private static final String TLS_API_KEY = System.getenv("TLS_API_KEY");

    @Override
    public boolean preHandle(HttpServletRequest req, HttpServletResponse res, Object handler) throws Exception {
        String userId = jwtUtil.getUserId(req);
        String requestId = UUID.randomUUID().toString();
        int estimatedInput = estimateTokens(req.getBody());
        int estimatedOutput = 500; // your default estimate

        HttpHeaders headers = new HttpHeaders();
        headers.set("Authorization", "Bearer " + TLS_API_KEY);
        headers.setContentType(MediaType.APPLICATION_JSON);

        Map<String, Object> body = Map.of(
            "user_id", userId,
            "estimated_input_tokens", estimatedInput,
            "estimated_output_tokens", estimatedOutput,
            "model_id", "gpt-4o",
            "request_id", requestId
        );

        ResponseEntity<Map> response = restTemplate.postForEntity(
            TLS_BASE + "/limits/check",
            new HttpEntity<>(body, headers),
            Map.class
        );

        if (response.getStatusCode() == HttpStatus.TOO_MANY_REQUESTS) {
            res.setStatus(429);
            res.getWriter().write(response.getBody().toString());
            return false;
        }

        // Store request_id for consume step
        req.setAttribute("tls_request_id", requestId);
        req.setAttribute("tls_user_id", userId);
        return true;
    }

    @Override
    public void afterCompletion(HttpServletRequest req, HttpServletResponse res, Object handler, Exception ex) {
        String requestId = (String) req.getAttribute("tls_request_id");
        String userId = (String) req.getAttribute("tls_user_id");
        int actualInput = (int) req.getAttribute("actual_input_tokens");   // set by your LLM handler
        int actualOutput = (int) req.getAttribute("actual_output_tokens"); // set by your LLM handler

        // Always call consume — even on error (use 0 tokens)
        if (requestId == null) return;

        HttpHeaders headers = new HttpHeaders();
        headers.set("Authorization", "Bearer " + TLS_API_KEY);
        headers.setContentType(MediaType.APPLICATION_JSON);

        Map<String, Object> body = Map.of(
            "user_id", userId,
            "request_id", requestId,
            "actual_input_tokens", actualInput,
            "actual_output_tokens", actualOutput,
            "model_id", "gpt-4o"
        );

        restTemplate.postForEntity(
            TLS_BASE + "/limits/consume",
            new HttpEntity<>(body, headers),
            Map.class
        );
    }
}
```

**Register the interceptor:**
```java
@Configuration
public class WebConfig implements WebMvcConfigurer {
    @Autowired
    TokenLimitInterceptor tokenLimitInterceptor;

    @Override
    public void addInterceptors(InterceptorRegistry registry) {
        registry.addInterceptor(tokenLimitInterceptor)
                .addPathPatterns("/api/llm/**"); // adjust to your LLM routes
    }
}
```

**Environment variable Spring needs:**
```bash
TLS_API_KEY=sk-tls-changeme
TLS_BASE_URL=http://tls-service:8000  # or your deployed URL
```

---

## Next.js Integration

**Never expose `TLS_API_KEY` to the browser.** Always proxy through a server-side API route.

**Usage dashboard — `app/api/tls/usage/route.ts`:**
```typescript
import { NextRequest, NextResponse } from "next/server";
import { getUserFromSession } from "@/lib/auth";

const TLS_BASE = process.env.TLS_BASE_URL!;
const TLS_API_KEY = process.env.TLS_API_KEY!;

export async function GET(req: NextRequest) {
  const userId = await getUserFromSession(req);
  if (!userId) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const res = await fetch(`${TLS_BASE}/v1/limits/usage?user_id=${userId}`, {
    headers: { Authorization: `Bearer ${TLS_API_KEY}` },
    cache: "no-store",
  });

  const data = await res.json();
  return NextResponse.json(data);
}
```

**History page — `app/api/tls/history/route.ts`:**
```typescript
export async function GET(req: NextRequest) {
  const userId = await getUserFromSession(req);
  const page = req.nextUrl.searchParams.get("page") ?? "1";

  const res = await fetch(
    `${TLS_BASE}/v1/limits/usage-history?user_id=${userId}&page=${page}&page_size=20`,
    { headers: { Authorization: `Bearer ${TLS_API_KEY}` } }
  );

  return NextResponse.json(await res.json());
}
```

**Client-side usage component:**
```typescript
"use client";
import { useEffect, useState } from "react";

export function TokenUsageBar() {
  const [usage, setUsage] = useState<any>(null);

  useEffect(() => {
    fetch("/api/tls/usage").then(r => r.json()).then(setUsage);
  }, []);

  if (!usage) return <div>Loading...</div>;

  const pct = Math.round((usage.daily_used / usage.daily_limit) * 100);
  return (
    <div>
      <p>{usage.daily_used.toLocaleString()} / {usage.daily_limit.toLocaleString()} tokens today ({usage.tier})</p>
      <div style={{ width: "100%", background: "#eee", borderRadius: 4 }}>
        <div style={{ width: `${pct}%`, background: pct > 90 ? "red" : "green", height: 8, borderRadius: 4 }} />
      </div>
      <p>Resets at {new Date(usage.resets_at).toLocaleString()}</p>
    </div>
  );
}
```

**Environment variables Next.js needs:**
```bash
TLS_API_KEY=sk-tls-changeme
TLS_BASE_URL=http://tls-service:8000  # or your deployed URL
```

---

## Environment Variables

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `TLS_DATABASE_URL` | — | Yes | `postgresql+asyncpg://user:pass@host:5432/db` |
| `TLS_REDIS_URL` | — | Yes | `redis://host:6379/0` |
| `TLS_API_KEY` | — | Yes | Service auth key (Spring uses this) |
| `TLS_ADMIN_API_KEY` | — | Yes | Admin auth key (admin panel uses this) |
| `TLS_DEFAULT_TIER` | `free` | No | Fallback tier for unknown users |
| `TLS_GRACE_PERCENTAGE` | `5` | No | % overage allowed before flagging |
| `TLS_STRICT_MODE` | `false` | No | Block requests exceeding grace |
| `TLS_ENABLE_ORG_LIMITS` | `true` | No | Enable org-level limits |
| `TLS_ENABLE_CONCURRENT_LIMITS` | `true` | No | Enable concurrent request limits |
| `TLS_ENABLE_MODEL_MULTIPLIERS` | `true` | No | Apply model cost multipliers |
| `TLS_REAPER_INTERVAL_MINUTES` | `1` | No | How often reaper runs |
| `TLS_REAPER_STALE_THRESHOLD_MINUTES` | `5` | No | Age before pending request is reaped |

---

## Default Tiers

| Tier | Daily Tokens | Monthly Tokens | RPM | RPH | TPM | Concurrent |
|------|-------------|----------------|-----|-----|-----|-----------|
| `free` | 10,000 | 100,000 | 10 | 100 | 20,000 | 3 |
| `pro` | 100,000 | 2,000,000 | 60 | 1,000 | 200,000 | 10 |
| `enterprise` | 1,000,000 | 20,000,000 | 200 | 5,000 | 1,000,000 | 50 |

Create custom tiers via `POST /v1/admin/tiers` using the admin key.

---

## Model Cost Multipliers

| Model | Multiplier | Effective Cost |
|-------|-----------|----------------|
| `gpt-4o` | 1.0× | baseline |
| `gpt-4o-mini` | 0.25× | 4× cheaper |
| `gpt-4-turbo` | 2.0× | 2× more expensive |
| `claude-3-5-sonnet` / `claude-sonnet-4-6` | 1.0× | same as baseline |
| `claude-3-opus` / `claude-opus-4-8` | 3.0× | 3× more expensive |
| `claude-3-haiku` / `claude-haiku-4-5` | 0.25× | 4× cheaper |

Add custom models in [app/utils/token_estimator.py](app/utils/token_estimator.py).

---

## Kubernetes Deployment

```bash
# 1. Build and push image to your registry
docker build -f docker/Dockerfile --target prod -t your-registry/tls-service:latest .
docker push your-registry/tls-service:latest

# 2. Edit k8s/deployment.yaml — update image and Secret values

# 3. Apply manifests
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
kubectl apply -f k8s/cronjob-reaper.yaml

# 4. Run migrations as a Job before deploying
kubectl exec -it <tls-pod> -- alembic upgrade head
```

---

## Database Migrations

```bash
# Apply all migrations
TLS_DATABASE_URL=postgresql+asyncpg://... alembic upgrade head

# Create migration after model changes
alembic revision --autogenerate -m "describe your change"

# Rollback one step
alembic downgrade -1
```

**Partition management:** The `tls_usage` table is partitioned by month. New partitions must be created before month-end. For production, install `pg_partman` + `pg_cron`:

```sql
CREATE EXTENSION IF NOT EXISTS pg_partman;
CREATE EXTENSION IF NOT EXISTS pg_cron;

SELECT partman.create_parent('public.tls_usage', 'period_start', 'native', 'monthly', p_premake := 2);
SELECT cron.schedule('tls-partman', '0 1 * * *', 'SELECT partman.run_maintenance(p_analyze := false)');
```

---

## Running Tests

```bash
pip install ".[dev]"
pytest tests/ -v --cov=app --cov-report=term-missing
```

Tests use `fakeredis` + `aiosqlite` — no real PostgreSQL or Redis needed.

---

## Monitoring

**Prometheus** is available at port `9090` (or `:29090` via SSH tunnel).

Key metrics to watch:

| Metric | Alert Threshold |
|--------|----------------|
| `tls_request_duration_seconds` p99 | > 50ms for check, > 100ms for consume |
| `tls_requests_total{result="blocked"}` | > 10% of total |
| `tls_reaper_reaped_total` | > 5% of requests |

---

## Project Structure

```
tls-service/
├── app/
│   ├── main.py              # FastAPI app + health endpoints + scheduler
│   ├── config.py            # All env vars (Pydantic Settings)
│   ├── dependencies.py      # DB session, Redis client, auth
│   ├── reaper_job.py        # Standalone reaper (for K8s CronJob)
│   ├── models/
│   │   ├── database.py      # SQLAlchemy ORM models
│   │   └── schemas.py       # Pydantic request/response schemas
│   ├── routers/
│   │   ├── limits.py        # /limits/* endpoints
│   │   └── admin.py         # /admin/* endpoints
│   ├── services/
│   │   ├── limit_checker.py # Pre-flight check logic
│   │   ├── limit_consumer.py# Post-flight consume logic
│   │   ├── quota_service.py # Daily/monthly quota calculations
│   │   ├── rate_limiter.py  # Redis sliding-window rate limiter
│   │   └── reaper.py        # Stale request cleanup
│   └── utils/
│       ├── token_estimator.py # Model multipliers
│       └── idempotency.py     # request_id deduplication
├── migrations/              # Alembic migrations
├── tests/                   # pytest (unit + integration)
├── k8s/                     # Kubernetes manifests
├── docker/                  # Dockerfile + docker-compose
├── prometheus/              # Prometheus config
├── .env.example             # All required env vars
└── README.md
```

---

## Security

| Layer | Implementation |
|-------|---------------|
| Authentication | API Key via `Authorization: Bearer` header |
| Service vs Admin | Two separate keys — different permission levels |
| Idempotency | `request_id` deduplication prevents double-billing |
| Audit trail | All limit changes logged to `tls_limit_changes` |
| No LLM access | TLS never reads your prompts or responses |
| Clock trust | Server-generated timestamps only — client time ignored |

---

## Error Handling

| Scenario | TLS Response | What Spring should do |
|----------|-------------|----------------------|
| Redis down | Falls back to PostgreSQL | Continue — slower but correct |
| PostgreSQL down | 503 Service Unavailable | Retry with exponential backoff |
| TLS timeout | — | Default to **allow** (configurable) |
| Duplicate request_id | Idempotent response | Safe to retry |
| Consume without matching check | Logs warning, still deducts | Normal flow |

---

## Technology Stack

| Component | Technology | Why |
|-----------|-----------|-----|
| Framework | FastAPI + Uvicorn | Async, fast, auto-docs |
| ORM | SQLAlchemy 2.0 async + asyncpg | True async PG driver |
| Cache / Rate limit | Redis (async) | Sub-millisecond operations |
| Migrations | Alembic | Schema version control |
| Settings | Pydantic-Settings | Type-safe env vars |
| Metrics | Prometheus-client | Industry standard |
| Scheduler | APScheduler | Embedded reaper (no extra infra) |
| Testing | pytest + fakeredis + aiosqlite | No real infra needed for tests |

---

## Specification

This service was built from the **Token Limit Service Production Specification v2.0** covering:
- All 7 limit types (RPM, RPH, TPM, daily, monthly, hard balance, concurrent)
- Token reservation system (prevents race-condition overages)
- Stale request reaper (auto-releases stuck reservations)
- Overage grace handling (5% default)
- pg_partman-ready schema (monthly partitioned usage table)
- Full idempotency via request_id deduplication at both Redis and DB level

---

## Contact / Issues

Open a GitHub Issue for bugs or integration questions.
