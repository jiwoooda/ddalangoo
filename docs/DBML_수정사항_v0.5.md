# DBML 수정사항 (코드 기준 v0.5)

> 기준: Phase 3-3 구현 완료 코드 (2026-05-24)
> 비교 대상: docs/DBschema.md v0.4

---

## 1. Enum 값 변경

### conversations.status
- **현재 DBML**: `started, intent_detected, searching_product, recommending, waiting_user_confirmation, confirmed, payment_in_progress, order_completed, failed, cancelled`
- **실제 코드 사용 값**:
  - 생성 시 (`agent_service.py:92`): `"intent_detected"`
  - Mock 데이터 (`mock_data/conversations.py`): `"waiting_user_confirmation"`, `"idle"`
  - `payment_service.py` 결과 처리: `"completed"`, `"cancelled"`, `"failed"`
- **수정 필요**:
  ```
  idle
  intent_detected
  waiting_user_confirmation
  completed
  failed
  cancelled
  ```
- **근거**: `agent_service.py:92`, `mock_data/conversations.py`, `payment_service.py:49-59`
- **참고**: `conversations.stage`는 별도 컬럼으로 `ShoppingState.Stage` 값 그대로 사용 (`idle, searching, product_confirming, cart_shopping, payment_processing, completed, failed`)

---

### agent_intents.intent (신규 Enum 정의 필요)
- **현재 DBML**: Enum 정의 없음 (varchar만)
- **실제 코드 값** (`src/state/schema.py:18-32`, `intent_agent.py:18-22`):
  ```
  buy
  reorder
  confirm
  deny
  next
  refine
  compare_platforms
  quantity_change
  address_change
  option_select
  ask
  cancel
  unclear
  ```
- **근거**: `src/state/schema.py:18`

---

### agent_intents.intent_type
- **현재 DBML**: `repurchase, new_purchase, cart_request, order_status_check, cancel_request, clarification_needed, unknown` (분석용 상위 분류 의도)
- **실제 코드 동작** (`conversation_repository.py:41`): `intent_type = intent` (intent 값을 그대로 복사)
- **수정 필요**: intent_type에 별도 상위 분류를 저장할 로직이 없음. 두 가지 선택:
  - **(A)** `intent_type` 컬럼 제거, `intent` 컬럼만 유지
  - **(B)** intent_type 저장 로직 추가 (개발 결정 필요)
- **근거**: `conversation_repository.py:41`

---

### payments.payment_status (Enum 정의 필요)
- **현재 DBML**: Enum 정의 없음 (varchar만)
- **vendor 코드** (`src/state/schema.py:153-159` PaymentStatus): `pending, pending_user_action, processing, success, failed`
- **backend mock_data** (`mock_data/payments.py`): `"paid"`
- **불일치**: vendor는 `success`, backend는 `paid` — 정규화 필요
- **수정 필요** (통일 권고):
  ```
  pending
  pending_user_action
  processing
  paid
  failed
  cancelled
  ```
- **근거**: `src/state/schema.py:153`, `mock_data/payments.py:2`

---

### orders.status
- **현재 DBML**: `pending_confirmation, confirmed, payment_pending, paid, order_requested, order_completed, failed, cancelled`
- **실제 코드 사용 값**:
  - 생성 시 (`mock_tools.py:373`): `"pending_confirmation"`
  - Mock 데이터 (`mock_data/orders.py:6`): `"order_completed"`
  - 취소 처리 (`order_repository.py:21`): `"cancelled"`
- **미사용 추정**: `confirmed`, `payment_pending`, `paid`, `order_requested`
- **수정 필요** (최소화):
  ```
  pending_confirmation
  order_completed
  failed
  cancelled
  ```
- **근거**: `mock_tools.py:373`, `mock_data/orders.py:6`

---

## 2. 필드 추가

### conversations
- 추가: `keyword varchar` — 대화 주제 키워드 (검색/조회용)
- 추가: `summary text` — 메시지 10개 초과 시 memory_agent가 저장하는 대화 요약
- 추가: `summary_message_count int` — 요약 시점의 메시지 수
- 근거: `conversation_repository.py:59-60`, `memory_agent.py:177-186`

### purchase_histories
- 추가: `keyword varchar` — 재구매 검색용 키워드
- 근거: `mock_data/purchase_histories.py:2-4` (`"keyword": "strawberry"` 사용)

---

## 3. 필드 제거 / 이름 변경

### conversations
| 구분 | 필드명 | 이유 |
|------|--------|------|
| 제거 | `langgraph_thread_id` | 코드 어디서도 저장/조회 안 함 (LangGraph conversation_id = conversations.id 직접 사용) |
| 제거 | `started_at`, `ended_at` | mock_data 및 repository에 없음. `created_at`으로 대체 가능 |

### agent_intents
| 구분 | 필드명 | 이유 |
|------|--------|------|
| 제거 또는 재정의 | `intent_type` | 코드에서 intent 값을 그대로 복사. 상위분류 로직 없음 |
| 제거 | `stage` | `create_agent_intent()` 저장 안 함 |
| 제거 | `pending_action_type` | 저장 안 함 |
| 제거 | `target_category` | 저장 안 함 |
| 제거 | `target_product_name` | 저장 안 함 |
| 제거 | `clarification_reason` | 저장 안 함 (confidence, needs_clarification만 저장) |
| 변경 | `extracted_keywords text` → `extracted_keywords varchar` | 코드에서 keywords를 `", ".join(list)`으로 저장 (짧은 문자열) |

- 근거: `conversation_repository.py:34-46`

### purchase_histories
| 구분 | DBML 필드명 | 코드 실제 필드명 | 근거 |
|------|------------|----------------|------|
| 이름 변경 | `product_name_snapshot` | `product_name` | `memory_tools.py:36`, `mock_data/purchase_histories.py` |
| 이름 변경 | `option_snapshot` | `option_text` | `memory_tools.py:37`, `mock_data/purchase_histories.py` |
| 이름 변경 | `brand_snapshot` | `brand` | `mock_data/purchase_histories.py:2` |
| 이름 변경 | `category_snapshot` | `category` | `mock_data/purchase_histories.py:2` |
| 이름 변경 | `satisfaction` | `satisfaction_score` | `mock_data/purchase_histories.py:2` |
| 제거 | `payment_id` | 없음 | `memory_tools.py` 저장 시 미포함 |
| 제거 | `external_order_id` | 없음 | 저장 시 미포함 |
| 제거 | `external_product_order_id` | 없음 | 저장 시 미포함 |
| 제거 | `product_url_snapshot` | `product_url` (vendor만) | backend는 미저장 |
| 제거 | `selected_options` | 없음 | backend 저장 시 미포함 |
| 제거 | `memo` | `memo` (mock_data에만) | 저장 로직 없음 |

### orders
| 구분 | DBML 필드명 | 코드 실제 필드명 | 근거 |
|------|------------|----------------|------|
| 이름 변경 | `recipient_name_snapshot` | `shipping_recipient_name` | `mock_data/orders.py:6` |
| 이름 변경 | `recipient_phone_snapshot` | `shipping_recipient_phone` | `mock_data/orders.py:6` |
| 이름 변경 | `shipping_address_snapshot` | `shipping_address` | `mock_data/orders.py:6` |
| 이름 변경 | `delivery_request_snapshot` | `delivery_request` | `mock_data/orders.py:6` |

### recommendation_items
| 구분 | DBML 필드명 | 코드 실제 필드명 | 근거 |
|------|------------|----------------|------|
| 이름 변경 | `product_name_snapshot` | `product_name` | `mock_data/recommendations.py` |
| 이름 변경 | `brand_snapshot` | `brand` | `mock_data/recommendations.py` |
| 이름 변경 | `option_snapshot` | `option_text` | `mock_data/recommendations.py` |
| 이름 변경 | `price_at_recommendation` | `price` | `mock_data/recommendations.py` |
| 이름 변경 | `delivery_info_snapshot` | `delivery_info` | `mock_data/recommendations.py` |
| 이름 변경 | `rating_snapshot` | `rating` | `mock_data/recommendations.py` |
| 이름 변경 | `review_count_snapshot` | `review_count` | `mock_data/recommendations.py` |
| 이름 변경 | `image_url_snapshot` | `image_url` | `mock_data/recommendations.py` |
| 이름 변경 | `product_url_snapshot` | `product_url` | `mock_data/recommendations.py` |
| 제거 | `is_presented`, `presented_at` | 없음 | mock_data에 없음, 저장 로직 없음 |

---

## 4. 수정된 DBML 전체 코드

```sql
// 딸랑구 DB Schema v0.5
// v0.5 변경 (코드 기준 정합 작업):
//  - conversations.status Enum 실제 사용 값으로 재정의
//  - conversations에 keyword, summary, summary_message_count 추가
//  - conversations에서 langgraph_thread_id, started_at, ended_at 제거
//  - agent_intents.intent Enum 정의 추가
//  - agent_intents에서 intent_type, stage, pending_action_type 등 미사용 필드 제거
//  - purchase_histories 필드명 _snapshot 접미사 제거 (product_name, option_text 등)
//  - purchase_histories.satisfaction → satisfaction_score 이름 변경
//  - purchase_histories.keyword 추가
//  - orders 배송지 snapshot 필드명 코드 기준으로 통일
//  - recommendation_items 필드명 _snapshot 접미사 제거
//  - payments.payment_status Enum 정의 추가

// [이하 변경 없는 테이블: users, user_naver_accounts, user_addresses,
//  crawled_product_snapshots, products, product_options, external_product_mappings,
//  carts, cart_items, checkout_sessions, order_items,
//  naver_order_mappings, external_api_logs, agent_events]

// ─── 변경된 테이블만 기재 ───

Table conversations {
  id bigint [pk, increment]
  user_id bigint [not null, ref: > users.id]
  // langgraph_thread_id 제거 — LangGraph는 conversations.id를 thread_id로 직접 사용
  status varchar [not null]                // idle, intent_detected, waiting_user_confirmation, completed, failed, cancelled
  stage varchar [not null]                 // idle, searching, product_confirming, cart_shopping, payment_processing, completed, failed
  keyword varchar                          // 대화 주제 키워드
  summary text                             // 메시지 10개 초과 시 memory_agent가 저장
  summary_message_count int                // 요약 시점 메시지 수
  // started_at, ended_at 제거 — created_at으로 대체
  created_at datetime [not null]
  updated_at datetime [not null]
}

Table agent_intents {
  id bigint [pk, increment]
  conversation_id bigint [not null, ref: > conversations.id]
  user_id bigint [not null, ref: > users.id]

  raw_user_request text [not null]
  intent varchar [not null]                // buy, reorder, confirm, deny, next, refine, compare_platforms,
                                           // quantity_change, address_change, option_select, ask, cancel, unclear
  // intent_type 제거 — 코드에서 intent와 동일값 저장. 상위분류 로직 없음
  // stage, pending_action_type, target_category, target_product_name, clarification_reason 제거 — 저장 안 함
  extracted_keywords varchar                // intent_agent 추출 키워드 comma-separated

  confidence float
  needs_clarification boolean

  created_at datetime [not null]
}

Table purchase_histories {
  id bigint [pk, increment]
  user_id bigint [not null, ref: > users.id]
  product_id bigint [ref: > products.id]
  product_option_id bigint [ref: > product_options.id]
  conversation_id bigint [ref: > conversations.id]
  order_id bigint [ref: > orders.id]
  // payment_id 제거 — 저장 로직 없음

  platform varchar
  keyword varchar                          // 재구매 검색용 키워드

  // 구매 당시 상품 정보 snapshot (필드명 코드 기준으로 통일)
  product_name varchar [not null]          // (구 product_name_snapshot)
  option_text varchar                      // (구 option_snapshot)
  brand varchar                            // (구 brand_snapshot)
  category varchar                         // (구 category_snapshot)
  price_at_purchase int [not null]
  // product_url_snapshot, selected_options, external_order_id 제거

  quantity int [not null]
  total_price int [not null]
  purchased_at datetime [not null]
  satisfaction_score int                   // (구 satisfaction)
  memo text
  created_at datetime [not null]
}

Table orders {
  id bigint [pk, increment]
  user_id bigint [not null, ref: > users.id]
  conversation_id bigint [ref: > conversations.id]
  cart_id bigint [ref: > carts.id]
  checkout_session_id bigint [ref: > checkout_sessions.id]
  recommendation_id bigint [ref: > recommendations.id]
  shipping_address_id bigint [ref: > user_addresses.id]

  // 배송지 snapshot (필드명 코드 기준으로 통일)
  shipping_recipient_name varchar          // (구 recipient_name_snapshot)
  shipping_recipient_phone varchar         // (구 recipient_phone_snapshot)
  shipping_address text                    // (구 shipping_address_snapshot)
  delivery_request text                    // (구 delivery_request_snapshot)

  platform varchar [not null]
  order_type varchar [not null]
  status varchar [not null]                // pending_confirmation, order_completed, failed, cancelled

  total_product_price int [not null]
  delivery_fee int
  total_payment_amount int [not null]

  confirmed_by_user boolean [not null]
  confirmed_at datetime
  ordered_at datetime
  idempotency_key varchar
  failed_reason text

  created_at datetime [not null]
  updated_at datetime [not null]
}

Table payments {
  id bigint [pk, increment]
  order_id bigint [not null, ref: > orders.id]

  payment_provider varchar [not null]
  payment_method varchar
  payment_status varchar [not null]        // pending, pending_user_action, processing, paid, failed, cancelled
  payment_amount int [not null]

  external_payment_id varchar
  approval_number varchar
  payment_url text                         // 결제창 재진입용 임시 참고값

  paid_at datetime
  cancelled_at datetime
  failure_reason text

  created_at datetime [not null]
  updated_at datetime [not null]
}

Table recommendation_items {
  id bigint [pk, increment]
  recommendation_id bigint [not null, ref: > recommendations.id]

  product_id bigint [ref: > products.id]
  product_option_id bigint [ref: > product_options.id]
  matched_purchase_history_id bigint [ref: > purchase_histories.id]

  rank int [not null]
  score float
  score_detail json
  reason text

  // 추천 당시 상품 정보 snapshot (필드명 코드 기준으로 통일, _snapshot 접미사 제거)
  product_name varchar [not null]          // (구 product_name_snapshot)
  brand varchar                            // (구 brand_snapshot)
  category varchar                         // (구 category_snapshot)
  option_text varchar                      // (구 option_snapshot)
  platform varchar
  price int                                // (구 price_at_recommendation)
  delivery_fee int
  delivery_info varchar                    // (구 delivery_info_snapshot)
  rating float                             // (구 rating_snapshot)
  review_count int                         // (구 review_count_snapshot)
  product_url text                         // (구 product_url_snapshot)
  image_url text                           // (구 image_url_snapshot)

  // is_presented, presented_at 제거 — 저장 로직 없음
  is_selected boolean [not null]

  is_orderable boolean [not null]
  order_block_reason varchar

  created_at datetime [not null]
}
```

---

## 5. Enum 값 정의 문서

```
conversations.status:
  idle, intent_detected, waiting_user_confirmation, completed, failed, cancelled

conversations.stage:
  idle, searching, product_confirming, cart_shopping, payment_processing, completed, failed

agent_intents.intent:
  buy, reorder, confirm, deny, next, refine, compare_platforms,
  quantity_change, address_change, option_select, ask, cancel, unclear

orders.status:
  pending_confirmation, order_completed, failed, cancelled

payments.payment_status:
  pending, pending_user_action, processing, paid, failed, cancelled

checkout_sessions.status:
  pending, active
  (vendor: "active" / backend mock: "pending" — 정규화 필요)
```

---

## 6. 결정 필요 사항 (DB 담당자 확인 필요)

| # | 항목 | 현황 | 선택지 |
|---|------|------|--------|
| 1 | `agent_intents.intent_type` | 코드에서 intent 값 그대로 저장 | (A) 컬럼 제거 / (B) 상위분류 매핑 로직 추가 |
| 2 | `purchase_histories` 필드명 | 코드는 `_snapshot` 없이 사용 | (A) DB 컬럼명을 코드 기준으로 변경 / (B) 코드를 `_snapshot` 접미사로 통일 |
| 3 | `payments.payment_status` 값 | vendor `success` vs backend `paid` | `paid`로 통일 권고 (결제 완료 상태 의미가 같음) |
| 4 | `recommendation_items` 필드명 | 코드는 `_snapshot` 없이 사용 | (A) DB 컬럼명을 코드 기준으로 변경 / (B) 코드를 `_snapshot` 접미사로 통일 |
| 5 | `checkout_sessions.status` | vendor `active`, backend `pending` 혼용 | 값 통일 필요 |
