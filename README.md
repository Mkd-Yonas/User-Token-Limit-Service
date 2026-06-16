# TLS (Token Limit Service)

> **성용 팀장님께** — TLS 모듈 구조 및 동작 방식 정리 문서입니다.
> 검토 후 수정 제안이 있으시면 언제든지 말씀해 주세요.

---

## 1. 개요

> **참고:** 대표님의 피드백에 따라 현 단계는 간단한 POC(개념 검증) 수준으로 구현했습니다. 복잡한 패키지(Redis, PostgreSQL, Alembic, Prometheus, 요금제 티어 등)를 모두 제거하고 핵심 기능만 남겼습니다. 추후 필요 시 확장 가능한 구조로 설계되어 있습니다.

TLS는 **Keural 사용자의 토큰 사용량을 제한**하는 독립형 FastAPI 마이크로서비스입니다.

- 사용자당 **50,000 토큰** 소진 시 → **5시간 차단**
- 5시간 후 **자동 해제** (MongoDB 기준)
- Spring API 관리자가 **즉시 수동 해제** 가능 (`POST /v1/admin/reset`)
- 데이터베이스: **MongoDB** (컬렉션: `tls_users`)
- TLS에 장애가 발생해도 **fail-open** — 사용자 요청은 통과됨 (경고 로그만 기록)

---

## 2. 전체 아키텍처

```
┌────────────┐
│  Next.js   │  ← 프론트엔드 (사용자 인터페이스)
└─────┬──────┘
      │ HTTP
      ▼
┌─────────────────────────────────────────────────────────────────┐
│          Keural FastAPI  (mkd-keural-be-fastapi)                │
│                                                                 │
│  process_response()  ← 모든 채팅 요청의 단일 진입점              │
│       │                                                         │
│  [2.5] TLS check ──────────────────────────────────────────┐    │
│       │          POST /v1/limits/check                     │    │
│       │          → 허용(200) or 차단(429)                   │    │
│       │                                                    │    │
│  [3] stream_agent() ← 오케스트레이터                        │    │
│       │   ├─ rag-agent                                     │    │
│       │   ├─ web-agent                                     │    │
│       │   └─ file-creation-agent                           │    │
│       │        ↕ 최대 30회 LLM 호출 (Keural/Gemma/Qwen 등) │    │
│       │                                                    │    │
│  [finally] TLS consume ◀───────────────────────────────────┘    │
│            POST /v1/limits/consume                              │
│            ← 실제 사용 토큰 기록 (응답 완료 후)                   │
└─────────────────────────────────────────────────────────────────┘

            TLS 호출 방향 (Keural FastAPI만 호출)
            ┌──────────────────────────────┐
            │           TLS                │  ← 이 레포지토리
            │   (mkd-keural-api-tls)       │
            └──────────────┬───────────────┘
                           │
                    ┌──────▼──────┐
                    │   MongoDB   │  tls_users 컬렉션
                    └─────────────┘

┌─────────────┐
│  Spring API │ → POST /v1/admin/reset  (관리자 수동 해제 전용)
└─────────────┘
```

**핵심 포인트:**
- Next.js와 Spring은 TLS를 **직접 호출하지 않습니다** (Spring의 admin reset 제외)
- TLS를 호출하는 것은 **Keural FastAPI 하나뿐**입니다
- 채팅 1턴당 정확히 **2번** 호출됩니다 (check → consume)

---

## 3. 토큰 제한 정책

| 항목 | 값 |
|------|-----|
| 토큰 한도 | 50,000 토큰 |
| 초과 시 처리 | 5시간 차단 |
| 자동 해제 | 5시간 후 자동 (다음 요청 시 MongoDB에서 확인) |
| 수동 해제 | Spring API → `POST /v1/admin/reset` |

> 토큰 수 계산 방식: `(사용자 메시지 길이 + AI 응답 길이) // 4`
> (오케스트레이터가 여러 모델을 호출하므로 단일 `response.usage`가 없어 문자 길이 기반으로 추정합니다)

---

## 4. MongoDB 데이터 구조

컬렉션명: `tls_users`

```json
{
  "_id": "user_12345",
  "tokens_used": 43200,
  "blocked_at": null,
  "unblocked_at": null
}
```

| 필드 | 설명 |
|------|------|
| `_id` | Keural에서 전달하는 user_id (문자열) |
| `tokens_used` | 누적 토큰 사용량 |
| `blocked_at` | 차단 시작 시각 (차단 중일 때만 값 있음) |
| `unblocked_at` | 자동 해제 예정 시각 |

---

## 5. API 엔드포인트

**인증:** 모든 요청에 `Authorization: Bearer <API_KEY>` 헤더 필요

### Keural FastAPI가 사용하는 엔드포인트

#### `POST /v1/limits/check` — 채팅 시작 전 사전 확인
```json
요청:
{
  "user_id": "user_12345",
  "estimated_tokens": 800
}

응답 200 (허용):
{
  "allowed": true,
  "tokens_used": 12000,
  "token_limit": 50000
}

응답 429 (차단):
{
  "allowed": false,
  "tokens_used": 50000,
  "token_limit": 50000,
  "unblocked_at": "2026-06-16T18:30:00Z",
  "reason": "token limit exceeded"
}
```

#### `POST /v1/limits/consume` — 응답 완료 후 토큰 기록
```json
요청:
{
  "user_id": "user_12345",
  "tokens": 1240
}

응답 200:
{
  "consumed": true,
  "tokens_used": 13240,
  "token_limit": 50000,
  "blocked": false,
  "unblocked_at": null
}
```

#### `GET /v1/limits/status?user_id=user_12345` — 현재 상태 조회
```json
{
  "user_id": "user_12345",
  "tokens_used": 13240,
  "token_limit": 50000,
  "blocked": false,
  "blocked_at": null,
  "unblocked_at": null
}
```

### Spring API가 사용하는 엔드포인트

#### `POST /v1/admin/reset` — 관리자 수동 해제
```json
요청 (Admin API Key 필요):
{
  "user_id": "user_12345",
  "reset_by": "admin"
}

응답 200:
{
  "reset": true,
  "user_id": "user_12345"
}
```

> `TLS_ADMIN_API_KEY` 값을 사용합니다. `TLS_API_KEY`와 **다른 키**입니다.

### 헬스 체크

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/health/live` | 프로세스 살아있는지 확인 |
| GET | `/health/ready` | MongoDB 연결 확인 |

---

## 6. Keural FastAPI 연동 코드 위치

**레포지토리:** `mkd-keural-be-fastapi` → `feat/tls-integration` 브랜치 (Enrique 검토 대기 중)

**파일 1:** `app/service/tls/client.py`
- `tls_check()` — 비동기 pre-flight 확인
- `tls_consume()` — 비동기 post-flight 기록 (fire-and-forget)

**파일 2:** `app/service/chat/process.py`
- `[2.5]` 구간: `stream_agent()` 호출 직전에 `tls_check()` 실행
- `finally` 블록: 응답 완료 후 `tls_consume()` 실행

**파일 3:** `app/config/constants.py`
- `TLS_ENABLED: bool = False` — 기본값 비활성화 (배포 시 `True`로 변경)
- `TLS_BASE_URL: str = "http://tls-service:8001"`
- `TLS_API_KEY: str = ""`

---

## 7. 레포지토리 구조

```
mkd-keural-api-tls/
├── app/
│   ├── main.py                  # FastAPI 앱 + 헬스 엔드포인트
│   ├── config.py                # 환경변수 (Pydantic Settings)
│   ├── dependencies.py          # MongoDB 의존성 + Bearer 인증
│   ├── models/
│   │   └── schemas.py           # 요청/응답 스키마
│   ├── routers/
│   │   ├── limits.py            # /v1/limits/* 엔드포인트
│   │   └── admin.py             # /v1/admin/* 엔드포인트
│   └── services/
│       └── limit_service.py     # 토큰 제한 핵심 로직
├── docker/
│   └── docker-compose.yml       # MongoDB + TLS 컨테이너
├── Dockerfile
├── pyproject.toml
├── .env.dev                     # 도커 환경 설정
├── .env.local                   # 로컬 개발 환경 설정
└── pipeline.dev.sh              # 도커 빌드 및 실행 스크립트
```

---

## 8. 환경 변수

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `TLS_MONGO_URL` | `mongodb://localhost:27017` | MongoDB 연결 주소 |
| `TLS_MONGO_DB` | `tls` | 데이터베이스 이름 |
| `TLS_API_KEY` | `sk-tls-changeme` | Keural FastAPI에서 사용하는 서비스 키 |
| `TLS_ADMIN_API_KEY` | `sk-tls-admin-changeme` | Spring API 관리자 키 (별도) |
| `TLS_TOKEN_LIMIT` | `50000` | 사용자당 토큰 한도 |
| `TLS_RESET_HOURS` | `5` | 차단 후 자동 해제까지 시간 |

> **운영 환경 배포 전에 반드시 API_KEY 값을 변경해 주세요.**

---

## 9. 로컬 실행 방법

```bash
# 레포지토리 클론
git clone git@github-mkd:MKD-CORP/mkd-keural-api-tls.git
cd mkd-keural-api-tls

# 도커로 실행 (MongoDB + TLS 함께 시작)
docker compose -f docker/docker-compose.yml up -d

# 헬스 확인
curl http://localhost:8002/health/ready
# 정상: {"status": "ok", "mongodb": "ok"}

# API 문서 확인
# http://localhost:8002/docs
```

| 컨테이너 | 포트 | 용도 |
|---------|------|------|
| `mongodb` | 27017 | 토큰 사용량 저장 |
| `tls` | 8002 | TLS FastAPI 서비스 |

---

## 10. 팀장님께 확인 요청 드리는 사항

현재 구조에서 **Spring API와의 연동**과 관련해 아래 내용을 확인 부탁드립니다.

1. **관리자 수동 해제** — Spring에서 `POST /v1/admin/reset`을 호출할 때 사용할 `TLS_ADMIN_API_KEY` 값을 어떻게 공유하면 좋을까요?

2. **user_id 형식** — 현재 Keural FastAPI에서 전달하는 user_id는 문자열(예: `"user_12345"`) 형태입니다. Spring에서도 동일한 형식을 사용하고 있는지 확인 부탁드립니다.

3. **TLS 서버 네트워크 설정** — TLS는 현재 `keural-network` Docker 네트워크에서 `keural-tls`라는 이름으로 실행됩니다 (`pipeline.dev.sh` 기준). Spring에서 이 주소로 접근 가능한지 확인이 필요합니다.

4. **기타 수정 제안** — 구조나 API 설계에서 개선이 필요한 부분이 있으면 말씀해 주세요.

---

**레포지토리:** `git@github-mkd:MKD-CORP/mkd-keural-api-tls.git`
