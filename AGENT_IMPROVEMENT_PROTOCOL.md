# Agent Improvement Protocol

딸랑구의 LangGraph 쇼핑 에이전트(intent/context/product/response/smalltalk/reorder 등)에서 **행동 버그**가 발견됐을 때 따르는 절차. 대상: VIVID(mphora.ai) 가상유저 검증 실패, 수동 QA/REPL 테스트 실패, e2e 테스트 실패, 프로덕션에서 관측된 이상 동작.

구현: `backend/vendor/ddalangoo-langgraph/evals/living_tests/`

## 목적

> 딸랑구에서 실제 Failure가 발생했을 때, 어디서 처음 잘못됐는지 찾아 가장 작은 책임 Component를 수정하고, 그 Failure를 Test로 남겨 같은 문제가 다시 발생하지 않게 한다.

Eval Platform이나 Prompt Optimization Framework를 만드는 게 목적이 아니다.

## 책임 분리

```text
Failure          = 무엇이 실패했는가 + 지금도 재현되는가(reproduction) + 왜 실패했는가(root_cause, reproduced일 때만)
Reproduction Run  = 지금 시스템을 다시 실행했을 때 실제로 무엇이 나왔는가 (사실 기록, 판정 아님)
Test              = 앞으로 어떤 Behavior를 보장해야 하는가
Test Run          = 이번 실행이 그 Behavior를 통과했는가
```

`root_cause`는 **Failure의 소유**고, `reproduced`일 때만 의미가 있다. Test는 `source_failure`로 그 Failure를 가리킬 뿐 원인을 다시 저장하지 않는다. 재현 판정("지금도 문제인가")의 **Source of Truth는 오직 `Failure.reproduction.status`뿐**이다 — Reproduction Run(`runs/reproduction/*.json`)은 실행 사실(`observed`)만 담고 판정 필드를 갖지 않는다.

## 핵심 원칙 — 절대 약화 안 함

- Failure를 발견하면 **곧바로 프롬프트/코드를 고치지 않는다.**
- Failure를 확인하면 **먼저 지금 코드에서 같은 조건으로 재현되는지부터 확인한다** — 이미 다른 변경으로 해결됐을 수 있다.
- **재현되지 않은(`not_reproduced`) 또는 재현 불가(`blocked`) Failure는 Trace/Diagnose/Fix로 진행하지 않는다.** `failure.status`도 `traced`가 되지 않는다 — TRACE 자체를 안 했기 때문이다. `traced`는 오직 실제로 Trace 분석을 수행했다는 뜻으로만 쓴다.
- 원인은 `unknown`에서 시작한다. Trace 없이 Prompt/Agent 문제로 단정하지 않는다.
- Trace로 "어디까지 정상이고 어디서 처음 어긋났는지" 확인한 뒤에만 원인을 확정한다(DIAGNOSE).
- 최초로 깨진 지점을 재현하는 **최소** Test를 만들고, 그 지점을 고친다.
- 고친 뒤 기존 Test가 안 깨졌는지 회귀 확인한다.
- Trace가 지나간 모든 지점에 자동으로 Test를 만들지 않는다 — 원인이 실제로 있는 지점에만. 대부분 Failure 1개 → Test 1개, 재발 방지 가치가 뚜렷할 때만 +1.

## Improvement Loop

```
FAILURE REPORT → CAPTURE → REPRODUCE/VALIDATE → TRACE → DIAGNOSE
              → MINIMAL TEST → SMALLEST FIX → REGRESSION → RECORD
```
Cycle(여러 fix 묶음) 종료 시: `→ VIVID 16-session CHECKPOINT`

1. **CAPTURE**
   ```
   python -m evals.living_tests.log_failure --source manual_repl --by human:<handle> \
       --observed "<무엇이 잘못됐는지>" [--input '{"user":"...", "state": {...}}'] [--context-summary "..."] \
       [--from-log <agent_logger .jsonl>] [--turn N]
   ```
   `root_cause`는 자동으로 `unknown`, `status`는 `unassigned`, `reproduction.status`는 자동으로 `pending`으로 생성된다. VIVID 실패는 `--source vivid_trial --ref <trial 경로>`. **VIVID 결과를 보고 곧바로 특정 Agent 문제로 단정하지 않는다.**

   `input.user`(재현 시 흘려보낼 실제 발화)와 `input.state`(선택, cart 초기 수량 등 재현에 필요한 작은 state 조각)는 기계가 그대로 읽는 값이다. `context_summary`는 사람이 Inbox를 훑어볼 때 이해하기 위한 설명일 뿐 — Runner는 이 필드를 절대 해석해서 state를 만들지 않는다.

2. **REPRODUCE/VALIDATE** — 지금 커밋에서 같은 조건으로 다시 실행해서 여전히 문제인지 확인한다.
   ```
   python -m evals.living_tests.runner --reproduce <failure_id>
   ```
   결과(`observed`)만 `runs/reproduction/{failure_id}_{timestamp}_{git_sha}.json`에 저장된다(판정 필드 없음). 이 결과와 Failure의 `observed_actual`을 비교해 사람이 직접 판정한다:
   ```
   store.set_reproduction(failure_id, "reproduced" | "not_reproduced" | "blocked",
                           run_ref="runs/reproduction/....json", reason="...")
   ```
   - `reproduced` — 같은 문제 확인됨 → TRACE로 진행.
   - `not_reproduced` — 지금은 정상 → Fix 없이 종료(`failure.status = dismissed`). 회귀 방지 가치가 뚜렷하면 root_cause 없이 Test만 별도로 남길 수 있다.
   - `blocked` — 당시 fixture/context가 없어서 재현 자체가 안 됨 → 원인을 추측해서 고치지 않는다. fixture 확보 후 재시도하거나 사람 검토 대기.

3. **TRACE** — **`reproduction.status == "reproduced"`인 Failure만** 대상. 실행을 단계별로 따라가며 어디까지 정상이고 어디서 처음 어긋났는지 확인한다. `agent_logger`의 `.jsonl` 이벤트(`intent_agent`/`router`/`context_agent`/`product_agent`/`scoring_agent`/`respond` 등)를 순서대로 읽는다 — 이게 유일한 Source of Truth이며, Run 기록에 이 내용을 다시 복제하지 않는다. 결과는 `store.set_trace_notes(failure_id, notes)`로 Failure에 남긴다(`status`가 `unassigned`→`traced`로 자동 전이 — `reproduction.status`가 `reproduced`가 아니면 이 호출 자체가 거부된다).

4. **DIAGNOSE ROOT CAUSE** — Trace로 확정된 원인을 아래 taxonomy로 기록한다(`store.set_root_cause`). `component`(파일/함수)와 `reason`(한두 문장)으로 항상 구체화한다.

   | `type` | 의미 |
   |---|---|
   | `unknown` | Trace/Diagnose 전 기본값 |
   | `prompt` | 프롬프트 지시/예시 공백 |
   | `model` | prompt/context/tool/state/orchestration을 **다 확인했고 통제된 입력으로 재현까지 됐을 때만**. 원인을 못 찾았으면 `model`이 아니라 `unknown`으로 남긴다 — 마지막 쓰레기통으로 쓰지 않는다. |
   | `orchestration` | Router/Handoff/Graph(엣지·전이 구조) |
   | `context_memory` | Context 구성, 구매이력/기억 조회 |
   | `tool` | Tool 경계 자체 — 어떤 tool을 부를지/입력/출력/실행 |
   | `state` | State 구조/전이(cart, stage 등) |
   | `data` | Catalog/mock 데이터 |
   | `code_logic` | tool이 정상 값을 돌려준 **다음**, 그걸 갖고 판단하는 우리 코드(랭킹 가중치, 필터, priority_resolver 등) |
   | `response` | 최종 문구/템플릿 |

   **`tool` vs `code_logic`**: tool 경계 자체가 문제면 `tool`, tool은 정상이었고 그 결과를 갖고 우리 코드가 내린 결정이 문제면 `code_logic`. (예: 검색 tool이 브랜드 일치 상품을 정상 반환했는데 랭킹이 다른 브랜드를 골랐다면 `code_logic`.)

5. **ASSIGN / MINIMAL TEST** — 원인이 실제로 있는 지점을 재현하는 Test를 최소한으로 만든다.
   ```
   python -m evals.living_tests.triage --failure <failure_id> \
       --trace-notes "..." \
       --root-cause-type <...> --root-cause-component "..." --root-cause-reason "..." \
       --scope <unit|integration|e2e> --target <...> \
       --expected-behavior "..." --rationale "..."
   ```
   `expected_behavior`가 제품 정책상 애매하거나 사람 결정이 필요하면, AI가 임의로 정답을 확정하지 말고 `store.append_case_event(case_id, "status_change", status="needs_human_review", reason="...")`로 남기고 **여기서 멈춘다.**

6. **TEST** — 만든 케이스가 현재 코드로 실제 fail하는지 확인한다(케이스가 진짜 이 버그를 판별하는지 검증).

7. **SMALLEST FIX** — 프롬프트/에이전트 코드/툴/라우터 중 실제 원인만 고친다. `root_cause.type == "prompt"`인 경우엔 아래 Prompt Modification Gate를 거친다.

8. **REGRESSION** — 고친 케이스 하나 재검증 → 그다음 관련 scope 전체 재실행 → `newly_failing` 없는지 확인(직전 run과 비교).

9. **RECORD**
   ```
   store.record_fix(case_id, by="human:<handle>", fix_component="...", fix_summary="...", regression_result="pass")
   ```
   Test 정의 자체(`expected_behavior`/`rationale`)는 절대 다시 쓰지 않는다 — `case_events.jsonl`에만 append. `fixed`/`verified`/`wontfix`/`needs_human_review` 같은 진행 상태는 계속 여기서만 관리하고 Failure에는 안 붙인다 — Failure의 status(`unassigned`/`traced`/`triaged`/`dismissed`)는 Trace/Triage 진행만 나타낸다. 나중에 "이 Failure가 지금 어디까지 왔는지" 보려면 `failure.status` + 연결된 케이스의 최신 `case_events` 이벤트만 읽으면 된다.

## Prompt Modification Gate (`root_cause.type == "prompt"`일 때만)

```
DISTILL → GENERALIZE → MINIMIZE → REGRESSION
```

- **DISTILL**: 사용자/리뷰어가 지적한 문장을 그대로 프롬프트에 복사하지 않는다. "실제로 깨진 behavior가 뭔가?"만 뽑는다. 상세 경위는 프롬프트가 아니라 Failure의 `trace_notes`/Test의 `rationale`에 남긴다 — **프롬프트는 실패 이력 저장소가 아니다.**
- **GENERALIZE**: 개별 사례가 아니라 그 실패 클래스 전체에 적용되는 원칙을 뽑는다.
- **MINIMIZE**: 편집 우선순위 `NO_CHANGE → REPLACE/CLARIFY → CONSOLIDATE → ADD`. **이미 같은 정책이 프롬프트에 있으면 새 규칙을 append하지 않는다** — 대신 "왜 기존 규칙이 실행 안 됐는지"를 다시 조사한다(root_cause가 사실 `prompt`가 아니라 `model`/다른 컴포넌트일 수 있음).
- **REGRESSION**: 원본 seed 케이스 pass + 필요하면 1~3개 변형(neighborhood probe)을 수동으로 확인 + 관련 세트 재실행. Probe는 검증용일 뿐 항상 영구 Test로 남기지 않는다 — 장기 회귀 가치가 있다고 판단될 때만 정식 케이스로 추가한다.

Prompt Hygiene: 리뷰어 피드백 문장을 그대로 복사하지 않는다 / 진짜 정책 경계가 아니면 케이스별 if-X-then-Y 패치를 계속 안 쌓는다 / 반복 금지 규칙보다 일반화된 긍정적 판단 원칙을 선호한다 / "왜 틀렸는지"의 역사는 프롬프트가 아니라 Failure/Test 기록에 남긴다 / 새 규칙 추가보다 기존 규칙 통합·교체를 우선한다.

수정 기록은 `case_events.jsonl`의 `fix_recorded` 이벤트 `fix_summary` 한 줄로 충분하다(예: "기존 다중 라우팅 규칙을 health_notes까지 포함하도록 확장(REPLACE, append 아님)") — 별도 구조화 메타데이터, 토큰 카운터, Prompt Optimizer는 만들지 않는다. 프롬프트 비대화 여부는 `git diff`로 확인한다.

## VIVID

VIVID는 원인 판정 도구가 아니라 **Cycle 단위 E2E checkpoint**다. 4 persona × 4 scenario = 16세션을 baseline v1로 고정하고, 매 fix가 아니라 주요 개선 Cycle 종료 시에만 재실행해서 Before/After 비교한다. VIVID 실패도 다른 소스와 동일하게 `CAPTURE → TRACE → DIAGNOSE → ...` 루프를 그대로 탄다 — VIVID 실행 자체는 `MatrAIx-Persona-8B` 도구를 그대로 쓰고, 결과만 `log_failure.py --source vivid_trial`로 반입한다.

## PII

`log_failure.py`는 저장 전 `redact.py`를 항상 거친다. 원본이 필요하면 git에 올라가지 않는 안전한 위치를 가리키는 `source_ref`만 남긴다.

## 만들지 않는 것

Harness Registry, Prompt Optimizer, Trace DB, 별도 Prompt Change DB, 새 Dashboard, 새 Observability 플랫폼, LLM-as-Judge(지금은 deterministic assertion + 필요시 사람 검토로 충분), 자동 엣지케이스 생성, 자동 Improvement Controller(상태 모델은 나중에 붙이기 좋게 정리해뒀지만 지금 구현 안 함).
