# Failure-Path 회복탄력성 보강 계획 (v2)

## Context

시스템의 Failure Path(재시도/폴백/복구/성능축소)를 조사·정리한 뒤, 4대 회복탄력성 패턴(Technical Retry, Fallback, Recovery, Graceful Degradation) 기준으로 재평가했다. 이후 v1 계획에 대해 사용자로부터 6가지 구체적 기술 지적을 받았고, 모두 실제 설치된 LangGraph 1.2.2 소스로 검증 완료했다:

- `langgraph.graph.state.StateGraph.add_node(..., error_handler=...)`가 실제로 존재하며, 시그니처는 `def handler(state: State, error: NodeError) -> Command`(`NodeError`는 `node`/`error` 필드를 가진 frozen dataclass, `langgraph.errors.NodeError`) — **검증 완료**.
- `langgraph.runtime.Runtime.execution_info.node_attempt`(1-indexed, `langgraph/runtime.py:49`)가 실제로 존재 — **검증 완료**. 직접 attempt 카운터를 근사할 필요 없음.

이 v2 계획은 사용자의 6가지 지적을 전부 반영해 재작성한 것이다. 이후 사용자가 v2에 대해 다시 6가지를 지적했고(v3), 반영 완료.

## v2 → v3 수정 사항 (이번 라운드)

1. **SDK Retry 비활성화 범위 축소**: `get_llm()`은 그래프 노드 밖(eval 스크립트, 유틸)에서도 쓰이므로 전역 `max_retries=0`은 그 호출처들의 재시도를 통째로 없앤다. `get_llm(..., retry_owner="sdk"|"application")` 파라미터로 소유권을 명시 — 그래프 노드/`retry_call()` 내부만 `"application"`(SDK 재시도 끔), 나머지는 기본값 `"sdk"`(기존 동작 유지).
2. **재시도 로그 기록 위치 수정**: 노드 진입부에서는 직전 실패의 예외 타입을 알 수 없다. `retry_attempt_started`(노드 진입부)/`transient_failure`(except 블록에서 re-raise 직전, 예외 타입 포함)/`retry_exhausted`(`error_handler` 내부)로 3분리.
3. **401 인증 오류는 품질 실패가 아니라 별도의 "영구적 기술 오류"**: 예외를 3분류로 재정의 — Transient Technical(연결/타임아웃/429/5xx → Retry) / Permanent Technical(401/권한/설정 오류 → Retry 없이 운영 오류로 로그, 안전 응답) / Quality-Validation(스키마 검증 실패/ValueError → 품질 축소 응답). 사용자에게 보이는 응답은 비슷해도 운영 로그의 원인 분류는 반드시 구분.
4. **`recipe_agent`는 우선 Call-level Retry로**: Node 전체가 순수 함수이고 부수효과가 전혀 없음을 코드로 확인하기 전까지는 Node RetryPolicy를 적용하지 않는다.
5. **4대 패턴 재정의 — "품질 재생성"을 Recovery로 통합**: Technical Retry / Fallback / Recovery(품질 재생성, 재검색·재계획, 사용자 확인 후 재실행) / Graceful Degradation(기능 축소) 4개로 유지하되 Recovery의 정의를 넓힘. Baseline Ranking은 Fallback이 아니라 Graceful Degradation으로 재분류.
6. **매 턴 관측 필드 리셋을 전용 노드로 분리**: `intent_agent_node` 진입부에 끼워 넣지 않고, `wait_for_input` → `reset_turn_observability`(신규 노드) → `intent_agent` 순서로 그래프에 명시적 노드 추가. Intent 노드는 팬아웃 지점(향후 intent를 안 거치는 진입 경로가 생겨도) 없이 "의도 분류"라는 단일 책임 유지.

## v1 → v2 핵심 수정 사항

1. **Retry 소진 후 Degradation 연결 누락 수정**: `retry_policy`만 붙이면 소진 시 그래프 실행이 그대로 실패한다. 반드시 `error_handler`를 함께 등록해 소진 후 `Command(update={...degraded 상태...}, goto="respond")`로 연결한다.
2. **Retry 경계를 노드 전체가 아니라 책임 단위로 분리**:
   - **Node 전체 RetryPolicy**: `intent_agent`, `smalltalk_agent`, `recipe_agent` (단일 LLM 호출 중심, 외부 부수효과 없음 확인 필요)
   - **호출 단위(call-level) 재시도**: `context_agent`의 분류 LLM, `product_agent`의 Scoring LLM, `response_agent`의 설명 생성/단순화 LLM — 노드 안에 검색·프로필 저장 등 다른 부수효과가 섞여 있어 노드 전체 재시도 시 그것도 반복되므로 LLM 호출 지점만 감싸는 헬퍼로 재시도
   - **Tool-level 재시도**: `meta_mcp_client`의 원격 MCP/네이버 API
   - **자동 Retry 금지**: `payment_agent`
3. **SDK 자체 Retry와 LangGraph Retry 중첩 방지**: LangGraph가 Retry를 소유하는 것으로 정하고, `ChatAnthropic`/`ChatOpenAI` 생성 시 `max_retries=0`으로 SDK 자체 재시도를 끈다.
4. **Anthropic/OpenAI 예외 계층 구조 정정**: 두 SDK는 공통 부모가 없는 별개 클래스 계층이므로 `isinstance` 튜플에 양쪽을 모두 명시하고, `status_code` 속성 기반 폴백 체크(408/429/5xx)를 추가한다.
5. **State/Log 책임 재분리**: `attempt_count`/`fallback_path`처럼 실행 시점·노드에 종속적인 값은 `ShoppingState`에 넣지 않고 JSONL 로그와 `runtime.execution_info.node_attempt`로만 추적한다. State에는 그 턴의 결과 요약(`degraded_mode`, `degradation_reason`, `failure_stage`, `ranking_mode`, `source_used`)만 남기고, **매 턴 시작 시 반드시 초기화**해 이전 턴의 실패 상태가 새 턴에 잔존하지 않게 한다.
6. **검증 방식 수정**: 잘못된 API 키(401 AuthenticationError)는 재시도 대상이 아니므로 Retry 테스트로 부적절 — `llm.invoke`를 monkeypatch해 1~2차 호출에서 transient 예외, 3차에서 정상 반환하는 결정론적 테스트로 교체.

---

## Phase 0 — Retry 소유권 결정 (선행 작업)

`get_llm()`을 전역으로 `max_retries=0` 처리하면 안 됨 — `configs/llm_config.py`의 `get_llm()`은 그래프 노드 외에 `evals/`, `scripts/`, 기타 유틸에서도 호출되므로, 전역으로 끄면 그래프 밖 호출처의 SDK 재시도가 통째로 사라진다. 대신 호출처가 소유권을 명시하도록 파라미터 추가:

```python
def get_llm(agent: str, *, retry_owner: Literal["sdk", "application"] = "sdk", **kwargs) -> BaseChatModel:
    max_retries = 0 if retry_owner == "application" else 2  # 기존 SDK 기본값 유지
    ...
```

- **`retry_owner="application"`** (SDK 재시도 끔, LangGraph가 유일한 재시도 계층): 그래프 노드 안에서 호출되는 모든 `get_llm()` 지점, `retry.py`의 `retry_call()` 내부
- **`retry_owner="sdk"` (기본값, 변경 없음)**: `evals/`, `scripts/`, 그 외 그래프 밖 호출처

이렇게 하면 SDK 3회 × LangGraph 3회 = 최대 9회 중첩 문제는 그래프 실행 경로에서만 해소되고, 그래프 밖 호출처의 기존 동작은 그대로 유지된다.

---

## Phase 1 — 예외 분류 + 책임 단위별 Retry

### 1-1. 공용 예외 분류 유틸 — 3분류

`backend/vendor/ddalangoo-langgraph/src/utils/retry.py` (신규). 예외를 **Transient Technical / Permanent Technical / Quality-Validation** 3가지로 분류 — 401을 품질 실패로 취급하지 않는 것이 핵심:

```python
import anthropic
import openai
from enum import Enum

class FailureClass(Enum):
    TRANSIENT_TECHNICAL = "transient_technical"   # 연결/타임아웃/429/5xx → Retry
    PERMANENT_TECHNICAL = "permanent_technical"    # 401/403/설정오류 → Retry 없이 운영오류 기록
    QUALITY_VALIDATION = "quality_validation"      # 스키마 검증 실패/ValueError → 품질 축소 응답

_TRANSIENT_TYPES = (
    anthropic.APIConnectionError, anthropic.APITimeoutError,
    anthropic.RateLimitError, anthropic.InternalServerError,
    openai.APIConnectionError, openai.APITimeoutError,
    openai.RateLimitError, openai.InternalServerError,
)
_PERMANENT_TYPES = (
    anthropic.AuthenticationError, anthropic.PermissionDeniedError, anthropic.BadRequestError,
    openai.AuthenticationError, openai.PermissionDeniedError, openai.BadRequestError,
)

def classify_failure(exc: BaseException) -> FailureClass:
    """anthropic/openai는 공통 부모가 없는 별개 SDK 예외 계층이므로 둘 다 명시."""
    if isinstance(exc, _TRANSIENT_TYPES):
        return FailureClass.TRANSIENT_TECHNICAL
    if isinstance(exc, _PERMANENT_TYPES):
        return FailureClass.PERMANENT_TECHNICAL
    status_code = getattr(exc, "status_code", None)
    if status_code == 408 or status_code == 429 or (isinstance(status_code, int) and status_code >= 500):
        return FailureClass.TRANSIENT_TECHNICAL
    if isinstance(status_code, int) and status_code in (400, 401, 403):
        return FailureClass.PERMANENT_TECHNICAL
    return FailureClass.QUALITY_VALIDATION  # pydantic.ValidationError, 수동 ValueError 등

def is_transient_llm_error(exc: BaseException) -> bool:
    return classify_failure(exc) is FailureClass.TRANSIENT_TECHNICAL

NODE_RETRY_POLICY = RetryPolicy(
    retry_on=is_transient_llm_error, max_attempts=3,
    initial_interval=0.5, backoff_factor=2.0, jitter=True,
)
```

`retry_call(fn, *args, max_attempts=3, **kwargs)` — call-level 재시도용 얇은 헬퍼도 같은 파일에 추가 (context_agent/product_agent/response_agent의 개별 LLM 호출을 감쌀 용도, `classify_failure`로 재시도 여부 판정 후 소진 시 원래 예외 re-raise). `FailureClass.PERMANENT_TECHNICAL`은 재시도하지 않되 `Quality-Validation`과 다른 로그 이벤트/`failure_stage` 값으로 남겨 운영자가 "일시 장애로 로직 재검토가 필요한지" vs "설정/인증 문제인지"를 구분할 수 있게 한다.

### 1-2. Node 전체 RetryPolicy 적용 대상 — 2개 노드만 (recipe_agent는 보류)

먼저 각 노드가 정말 "단일 LLM 호출 + 부수효과 없음"인지 코드 재확인 후 적용:
- `intent_agent_node` — `src/agents/intent_agent.py:201-341` — **Node RetryPolicy**
- `smalltalk_agent_node` — `src/agents/smalltalk_agent.py` — **Node RetryPolicy**
- `recipe_agent_node` — `src/agents/recipe_agent.py` — **1-4의 Call-level Retry로 우선 적용**. 4가지 모드 분기가 있어 Node 전체가 순수 함수(부수효과 없음)임을 코드로 확인하기 전까지는 Node RetryPolicy를 걸지 않는다. `_generate_items`(LLM 호출부)만 `retry_call()`로 감싼다. 확인 후 안전하면 추후 Node RetryPolicy로 승격.

각 노드의 `except Exception`을 3분류 기반으로 분리:
```python
except Exception as e:
    fc = classify_failure(e)
    if fc is FailureClass.TRANSIENT_TECHNICAL:
        agent_logger.log_transient_failure(node="intent_agent", node_attempt=..., exception_type=type(e).__name__)
        raise  # RetryPolicy가 노드 재실행, 소진되면 error_handler로 이동
    # PERMANENT_TECHNICAL(401 등) / QUALITY_VALIDATION 모두 즉시 축소 응답이지만
    # failure_stage/degradation_reason에 fc.value를 남겨 운영 로그에서 구분되게 한다
    ...기존 폴백 로직 + degraded_mode=True, failure_stage=fc.value 추가...
```
`node_attempt`는 `runtime: Runtime` 파라미터를 노드 함수에 추가해 `runtime.execution_info.node_attempt`로 읽는다(직접 카운팅 안 함, 2-1 참고).

### 1-3. `error_handler`로 Retry 소진 후 Degradation 연결

`error_handler`는 두 경로 모두에서 호출된다는 점에 유의: (a) `RetryPolicy`가 재시도했지만 `max_attempts` 소진, (b) 예외가 `retry_on`에 안 걸려(예: 401 `PERMANENT_TECHNICAL`) 애초에 재시도 없이 즉시 전달된 경우. 핸들러 내부에서 `classify_failure(error.error)`로 다시 분기해 로그 이벤트를 구분한다:

```python
def intent_error_handler(state: ShoppingState, error: NodeError) -> Command:
    fc = classify_failure(error.error)
    if fc is FailureClass.TRANSIENT_TECHNICAL:
        agent_logger.log_retry_exhausted(node="intent_agent", exception_type=type(error.error).__name__)
    else:
        agent_logger.log_permanent_technical_error(node="intent_agent", exception_type=type(error.error).__name__)
    return Command(
        update={
            "intent": "unclear",
            "needs_clarification": True,
            "clarification_reason": "일시적 오류, 다시 시도해 주세요",
            "confidence": 0.0,
            "degraded_mode": True,
            "failure_stage": fc.value,
            "degradation_reason": type(error.error).__name__,  # 예외 메시지 원문 대신 클래스명만(2-5 참고)
        },
        goto="respond",
    )
```
`graph/builder.py:52-63`에서 `add_node("intent_agent", intent_agent_node, retry_policy=NODE_RETRY_POLICY, error_handler=intent_error_handler)` 형태로 등록. `smalltalk_agent`도 동일 패턴. `recipe_agent`는 1-2에서 Call-level Retry로 우선 처리하므로 이번 Phase에서는 `error_handler` 등록 대상에서 제외.

### 1-4. Call-level 재시도 (노드 전체 재시도 금지 대상)

- `context_agent.py`의 `_classify_context`/`_sync_safety_from_session`, `product_agent.py`의 `_run_scoring_llm` 호출부, `response_agent.py`의 `_generate_explanation`/`_simplify_with_haiku` — 각 LLM `.invoke()` 호출만 `retry.py`의 `retry_call()` 헬퍼로 감싸고, 소진 시 기존 폴백(빈 리스트/원본 순서/코드 기반 문장)으로 자연스럽게 떨어지도록 함. 이 경로는 **노드 자체가 실패하지 않으므로 `error_handler`가 필요 없다** — 함수 내부에서 이미 폴백을 반환하기 때문.
- `product_agent_node`에는 **Node 전체 RetryPolicy를 절대 붙이지 않는다** — 검색(멀티 소스 폴백 체인 전체) 이후에 스코어링 LLM이 있어, 노드 전체를 재시도하면 검색까지 통째로 재실행된다는 사용자 지적을 그대로 반영.

### 1-5. Tool-level 재시도: `meta_mcp_client.py`

- `tools/meta_mcp_client.py:279` `_call_remote_meta_mcp`의 `urlopen`, `tools/meta_mcp_client.py:139` `_call_naver_search_api`의 플랫폼별 `urlopen` — 연결/타임아웃 계열 예외만 최대 2~3회 짧은 재시도 후 다음 폴백 단계(Source Fallback)로 전환. `_call_meta_mcp`의 subprocess 타임아웃은 재시도하지 않고 바로 다음 단계로(재기동 비용 큼).

### 1-6. `payment_agent` — 자동 Retry 계속 금지

Phase 4에서 멱등성 키가 들어가기 전까지 `retry_policy`/`error_handler` 둘 다 붙이지 않는다.

---

## Phase 2 — State/Log 책임 분리 관측성

### 2-1. `ShoppingState`에는 "이번 턴 결과 요약"만

`state/schema.py` `error` 필드 아래에 추가:

```python
degraded_mode: bool
degradation_reason: Optional[str]
failure_stage: Optional[str]        # "intent_llm" | "scoring_llm" | "search" | ...
ranking_mode: Optional[str]         # "llm" | "baseline" (Phase 3)
source_used: Optional[str]          # "remote_mcp" | "local_mcp" | "naver_api" | "kurly_fallback"
```

`attempt_count`, `fallback_path`는 **State에 넣지 않는다** (어느 노드 기준인지 불명확, 실패한 attempt는 State update를 반환 못해 증가값이 유실됨, last-write-wins로 경로 유실). 대신:
- attempt 횟수 → `runtime.execution_info.node_attempt` (LangGraph가 이미 제공, 노드 함수에 `runtime: Runtime` 파라미터 추가해서 읽음)
- fallback 경로 → JSONL 로그 전용 필드

`get_default_shopping_state`에 위 5개 필드 기본값 추가.

**매 턴 리셋은 전용 노드로 분리** — `intent_agent_node` 진입부에 끼워 넣지 않는다:
```python
def reset_turn_observability_node(state: ShoppingState) -> dict:
    return {
        "degraded_mode": False, "degradation_reason": None,
        "failure_stage": None, "ranking_mode": None, "source_used": None,
    }
```
`graph/builder.py`에 `add_node("reset_turn_observability", reset_turn_observability_node)`를 추가하고 `wait_for_input → reset_turn_observability → intent_agent` 순서로 엣지를 재배선한다. 이렇게 하면 `intent_agent`는 "의도 분류"라는 단일 책임을 유지하고, 나중에 intent_agent를 거치지 않는 새 진입 경로가 생기더라도 리셋 누락 위험이 없다.

### 2-2. `agent_logger.py`에 이벤트 전용 메서드 추가 — 기록 시점을 정확히 분리

기존 `log_scoring_fallback` 패턴(전용 `event` 문자열 → `scripts/check_fallback_rate.py`가 필터링)을 재사용하되, **노드 진입 시점에는 직전 실패의 예외 타입을 알 수 없으므로** 3개 메서드로 시점을 분리:
- `log_retry_attempt_started(node, node_attempt)` — 노드 진입부, `runtime.execution_info.node_attempt`를 그대로 전달 (예외 타입 없음, 단순 시도 횟수 기록)
- `log_transient_failure(node, node_attempt, exception_type)` — **except 블록에서 re-raise 직전** 호출 (여기서만 실제 예외 객체를 알 수 있음)
- `log_retry_exhausted(node, exception_type)` / `log_permanent_technical_error(node, exception_type)` — `error_handler` 내부, `classify_failure`로 둘을 구분해 호출 (1-3 참고)
- `log_source_fallback(from_source, to_source, reason)` — meta_mcp_client 폴백 전환 지점 (Fallback)
- `log_quality_regeneration(node, reason)` — response_agent의 `_simplify_with_haiku` 호출 시, 결제 재시도 confirm 등 (Recovery — 2-5 패턴 재정의 참고)
- `log_graceful_degradation(node, reason, stage)` — baseline ranking, 코드 기반 설명 등 최종 축소 응답 반환 직전 (Graceful Degradation)

### 2-3. 집계 스크립트

`scripts/check_fallback_rate.py`와 동일한 `_DEFAULT_LOG_DIRS`/`_iter_events`/`Counter` 템플릿으로 `scripts/check_resilience_metrics.py` 신설: 노드별 실패율, technical_retry 성공/소진 비율, source_fallback 진입률(소스별), quality_regeneration 비율, graceful_degradation 비율, baseline_ranking 사용률.

### 2-4. Eval — 별도 Reliability 평가셋으로 분리

일반 정확도 평가(`INTENT_EVALUATORS` 등 `evals/evaluators.py` 기존 리스트)에 `degradation_evaluator`를 섞지 않는다 — 정상 케이스는 당연히 `degraded_mode=False`라 신호가 희석됨. 대신 장애를 의도적으로 주입하는 별도 데이터셋/실험(`evals/run_experiment.py`에 `--inject-failure` 류 옵션 또는 별도 스크립트)과 전용 `RELIABILITY_EVALUATORS` 리스트(재시도 성공 여부, fallback 전환 여부, degradation 발생 시 응답 유효성)를 신설.

---

### 2-5. 4대 패턴 재정의 — "품질 재생성"을 Recovery로 통합

| 상위 패턴 | 포함되는 동작 |
|---|---|
| Technical Retry | 일시적 기술 오류(TRANSIENT_TECHNICAL)의 동일 호출 재시도 |
| Fallback | 다른 모델·도구·데이터 소스로 전환 (meta_mcp_client의 원격MCP→로컬MCP→네이버→컬리) |
| Recovery | 품질 재생성(Reflection→Haiku 단순화), 재검색·재계획, 사용자 확인 후 재실행(결제 재시도 confirm) |
| Graceful Degradation | 코드 기반 설명, 고정 인사말, baseline ranking 등 기능 축소 |

이 기준으로 기존 로그 이벤트를 매핑: `log_source_fallback`→Fallback, `log_quality_regeneration`→Recovery, `log_graceful_degradation`→Degradation. Technical Retry는 `log_retry_attempt_started`/`log_transient_failure`/`log_retry_exhausted`(2-2)로 별도 추적.

## Phase 3 — 결정론적 Baseline Ranking (패턴 분류: Fallback이 아니라 Graceful Degradation)

*2-5 패턴 재정의에 따라 "다른 소스로 전환"이 아니라 "같은 소스 안에서 기능을 축소"하는 것이므로 Fallback이 아닌 Graceful Degradation으로 분류 — `log_graceful_degradation` 이벤트 사용.*

`_rank_with_metadata` `product_agent.py:334-342`의 폴백을 "원본 검색 순서" → 결정론적 baseline ranking으로 교체:

```python
def _baseline_rank(candidates: list[dict], keywords: list[str]) -> list[dict]:
    """이미 안전조건/제외 필터를 통과한 candidates에 대해서만 동작.
    키워드 매치 개수 → 가격/리뷰 기본 점수 → product_id 기준 안정적 tie-break."""
```
- 입력은 이미 `_filter_results`(안전조건/명시적 제외 적용됨, `product_agent.py:434`)를 통과한 `candidates`이므로 별도 안전 필터링 불필요.
- 반환 필드 수정: `tool_call_success: False`는 의미가 부정확(검색은 성공, 스코어링만 실패)하므로 유지하되 보조 신호로만 두고, 대신 `ranking_mode: "baseline"`, `degraded_mode: True`, `failure_stage: "scoring_llm"`을 명시적으로 채움.
- 동일 입력 → 항상 동일 순서가 나오도록 마지막 tie-break까지 정의(예: `product_id` 문자열 정렬).

---

## Phase 4 — 결제 Idempotency (Request Hash 포함)

### 4-1. 현황

프로덕션은 이미 `AsyncPostgresSaver`(`backend/app/agent/runtime.py`)로 durable checkpointing 중 — "Persistent Checkpointer" 요건은 이미 충족. 재개 방식은 동적 `interrupt()`가 아니라 `aupdate_state()` + `ainvoke(None, config)` 패턴이라 "interrupt 재개 시 노드 처음부터 재실행" 리스크는 현재 구조엔 해당 없음 (Phase 5로 별도 분리).

실제 리스크는 `payment/node.py`의 `mock_add_to_cart`/`mock_clear_cart`/`mock_place_order`(line 249)가 멱등성 키 없이 매번 새 `order_id`를 생성한다는 점.

### 4-2. 멱등성 키 + Request Hash

- `ShoppingState`에 `payment_idempotency_key: Optional[str]` 추가 — 결제 플로우 진입 시점(Step0)에서 1회 생성.
- `mock_tools.py`에 키→(order_id, request_hash) 매핑 저장소 추가. `request_hash`는 `user_id` + 상품ID + 옵션 + 수량 + 가격 + 배송지 참조ID를 해싱.
- `mock_place_order` 호출 시:
  - 같은 키 + 같은 request_hash → 기존 `order_id` 그대로 반환 (진짜 재시도/중복 요청)
  - 같은 키 + 다른 request_hash → 충돌 오류 반환 (장바구니가 바뀐 채로 이전 키가 남아있는 경우, 잘못된 주문 반환 방지)
  - 장바구니 변경/결제 취소/주문 완료 시 다음 결제엔 새 키 발급
- `mock_add_to_cart`도 동일 키 기준 중복 추가 방지 검토(현재는 조사 범위 밖이라 실제 호출 패턴 재확인 필요).

구현 시 추가로 지킬 것:
- **키는 반드시 서버에서 생성** (클라이언트가 제시한 키를 그대로 신뢰하지 않음)
- Hash 입력 필드(user_id/상품ID/옵션/수량/가격/배송지 참조ID)는 **정렬·정규화 후 직렬화**해 해싱(딕셔너리 순서 등으로 같은 요청이 다른 해시가 되는 것 방지)
- 실제 DB로 전환 시 "키 저장"과 "주문 생성"을 하나의 트랜잭션으로 묶어야 함(지금은 mock in-memory라 해당 없음, Phase 5의 실 DB 연동 시 필수 조건으로 명시)
- `degradation_reason`에는 예외 메시지 원문을 저장하지 않고 **안전한 오류 코드 또는 예외 클래스명만** 저장 (1-3의 `type(error.error).__name__` 패턴과 동일 원칙 — 내부 정보 노출 방지)

### 4-3. Recovery 정책 문서화 (사용자 확인 후 재실행 = Recovery)

Side Effect가 있는 노드(`payment_agent`)에는 자동 Retry(RetryPolicy/error_handler)를 붙이지 않는다는 원칙을 Phase 1 설계와 동일하게 유지. `mock_place_order` 실패 시(현재는 예외 케이스 자체가 없음) 예외를 잡아 `stage="failed"`로 전이하고, 재시도는 사용자 확인을 거치는 명시적 `pending_action` 타입(`"payment_retry_confirm"`)을 신규 추가해 처리.

---

## Phase 5 — 범위 밖 (향후 과제)

- `interrupt()`/`Command(resume=...)` 동적 API 마이그레이션 — 현재 구식 패턴이 정상 동작 중이라 급하지 않음, human-in-the-loop 전체 흐름에 영향을 주는 큰 변경이라 별도 계획 필요
- LangSmith 런타임 트레이싱 (현재 eval 시점에만 존재) — `agent_logger` JSONL로 대체 가능해 우선순위 낮음
- 실제 DB/결제 API 연동 시의 재시도/멱등성 정책 (현재는 mock)

---

## 수정된 실행 순서

| 순서 | 작업 |
|---|---|
| 0 | `get_llm(retry_owner=...)`로 재시도 소유권을 호출처별 명시 (그래프 노드만 SDK 재시도 끔) |
| 1 | 예외를 Transient/Permanent Technical/Quality-Validation 3분류(`classify_failure`) |
| 2 | Node 전체 Retry 가능 노드(intent/smalltalk) vs 호출 단위 Retry 필요 노드(context/product/response/recipe) 구분 적용 |
| 3 | `error_handler`로 Retry 소진·Permanent 오류 모두 Degradation 경로로 연결, 로그는 발생 시점별로 분리 기록 |
| 4 | meta_mcp_client 제한적 Retry + Source Fallback 유지 |
| 5 | State에는 이번 턴 요약만(5개 필드), 전용 `reset_turn_observability` 노드에서 리셋 |
| 6 | attempt/fallback 세부 경로는 JSONL + `runtime.execution_info.node_attempt`로 기록 |
| 7 | 결정론적 Baseline Ranking 적용 — Graceful Degradation으로 분류(Phase 3) |
| 8 | 결제 Idempotency Key + Request Hash(정규화·직렬화) 적용, 오류 코드만 로그(Phase 4) |
| 9 | 장애 주입(monkeypatch) 기반 Reliability 테스트 추가 |

## 검증 방법

- **Phase 1**: `llm.invoke`를 monkeypatch해 결정론적 테스트 — ① `AuthenticationError`(401) → 재시도 없이 즉시 **Permanent Technical**로 분류되어 안전 응답(품질 실패와는 다른 `failure_stage` 값으로 로그 확인), ② `APIConnectionError`/`APITimeoutError`/`RateLimitError`(429)/`InternalServerError`(5xx) → 재시도 후 성공/소진 각각 확인 + `log_transient_failure`가 실제 예외 타입을 정확히 기록하는지 확인, ③ `pydantic.ValidationError`/`ValueError` → 즉시 Quality-Validation Degradation. `LOG_AGENT_TRACE=true`로 실행해 `.jsonl`에서 `retry_attempt_started`/`transient_failure`/`retry_exhausted`/`permanent_technical_error` 4개 이벤트가 각각 올바른 시점에 기록되는지 확인.
- **Phase 2**: 정상 세션 실행 후 `degraded_mode`가 다음 턴에 리셋되는지(전용 노드 경유 확인) 회귀 테스트. `scripts/check_resilience_metrics.py`로 신규 이벤트 집계 검증.
- **Phase 3**: 동일 candidates 입력으로 `_baseline_rank` 반복 호출 시 항상 동일 순서(tie-break 결정론성) 단위 테스트.
- **Phase 4**: 동일 `payment_idempotency_key` + 동일(정규화된) request_hash로 `mock_place_order` 2회 호출 → 같은 `order_id`. 동일 키 + 다른 request_hash → 충돌 오류. 필드 순서만 다르고 값은 같은 요청이 동일 해시가 되는지도 확인(정규화 검증).
- **전체**: 기존 `pytest` 스위트 회귀 확인(특히 `evals`/`scripts`가 `get_llm()`을 `retry_owner="sdk"` 기본값으로 여전히 호출하는지) + `pytest -m llm_smoke` 유지.
