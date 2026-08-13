# vivid_bridge.py — Railway 배포 가이드

VIVID(mphora.ai) 가상유저 검증용 최소 HTTP 브릿지. 프로덕션 백엔드(`backend/app`,
실 Postgres)와 완전히 분리된 독립 배포 대상이다 — 이 디렉터리
(`backend/vendor/ddalangoo-langgraph`)만 배포하면 된다.

## 배포 대상 파일
- `vivid_bridge.py` — FastAPI 앱 본체
- `requirements.txt` — 배포 전용 최소 의존성 (pyproject.toml 전체가 아님)
- `railway.toml` — 빌드/시작 명령 설정

## 필요한 환경변수 (Railway 프로젝트 Variables에 등록)

| 변수 | 값 | 비고 |
|---|---|---|
| `OPENAI_API_KEY` | (본인 키) | Anthropic 크레딧 이슈로 이번 세션 내내 OpenAI로 검증함 — 아래 4개 MODEL 변수와 세트 |
| `CONTEXT_MODEL` | `gpt-4o-mini` | 미설정 시 기본값(Claude)으로 가서 크레딧 오류 남 |
| `INTENT_MODEL` | `gpt-4o-mini` | 〃 |
| `PRODUCT_MODEL` | `gpt-4o-mini` | 〃 |
| `RESPONSE_MODEL` | `gpt-4o-mini` | 〃 |
| `VIVID_BRIDGE_TOKEN` | (임의의 랜덤 문자열) | `/chat` 인증 토큰. 안 넣으면 인증 없이 오픈됨 — **반드시 설정** |
| `ANTHROPIC_API_KEY` | (선택) | Claude 크레딧 문제 해결되면 이걸로 전환 가능 (그땐 위 MODEL 변수들을 지우거나 claude 모델명으로) |

설정 안 해도 되는 것: `DATABASE_URL`(불필요 — `DB_MODE` 기본값이 `mock`이라 real DB
경로를 아예 안 탐), `LANGCHAIN_*`(LangSmith 트레이싱, 선택사항 — 안 넣으면 조용히 비활성).

## 세션 저장 방식 — 인메모리로 유지 (Redis 불필요 판단)

`vivid_bridge.py`는 LangGraph의 `MemorySaver`(프로세스 메모리)로 세션을 유지한다.
검토 결과 **Redis 전환은 불필요**하다고 판단 — 이유:
- VIVID 세션은 짧은 멀티턴 테스트 대화(몇~수십 턴)라 장기 보존이 필요 없음
- **단, Railway 배포 시 반드시 지켜야 할 조건 하나**: 이 서비스는 **단일 인스턴스(replica 1개)**로만 운영해야 한다. Railway에서 replica를 2개 이상으로 늘리면(수평 스케일링) 인스턴스마다 메모리가 분리돼서 같은 `session_id`라도 다른 인스턴스에 요청이 가면 "세션을 못 찾는" 문제가 생긴다. Railway 기본값은 1 replica라 별도 설정 안 건드리면 문제없음.
- 재배포/재시작 시 진행 중이던 세션은 끊긴다 — VIVID 쪽에서 새 세션으로 재시도하는 정상 흐름으로 처리될 걸로 예상. 만약 재배포 중 세션 유지가 꼭 필요해지면 그때 Redis(`RedisSaver`, langgraph 공식 지원)로 전환하면 된다 — 지금 단계에서 미리 붙이는 건 과설계로 판단.

## 배포 절차 (Railway CLI)
```bash
cd backend/vendor/ddalangoo-langgraph
railway login          # 브라우저 OAuth
railway init            # 새 프로젝트 생성 (또는 railway link로 기존 프로젝트 연결)
railway variables set OPENAI_API_KEY=... CONTEXT_MODEL=gpt-4o-mini INTENT_MODEL=gpt-4o-mini PRODUCT_MODEL=gpt-4o-mini RESPONSE_MODEL=gpt-4o-mini VIVID_BRIDGE_TOKEN=...
railway up               # 배포
railway domain           # 고정 도메인 발급 (*.up.railway.app)
```

## Trial → 유료 전환 (끊김 방지)
Railway 공식 문서 기준: 트라이얼 크레딧($5)이 소진되면 워크로드가 stop된다.
**크레딧 소진 전에 결제수단을 등록하고 Hobby 플랜으로 업그레이드하면 끊김 없이
계속 운영된다** ("업그레이드는 언제든 가능"). 6개월 이상 운영 예정이므로
**배포 직후 바로 결제수단 등록 + Hobby 플랜 전환을 권장**한다.
