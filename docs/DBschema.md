2. 테이블 분류
| 레이어 | 담당 | 저장 대상 | 직접 DB 설계 여부 |
| --- | --- | --- | --- |
| LangGraph State | 세션 중 임시 작업 공간 | 현재 메시지, 검색 결과, 추천 후보, 선택 상품 | 아님 (TypedDict로 코드 정의) |
| LangGraph Checkpointer | State 스냅샷 저장 | thread별 State, messages | LangGraph 자동 관리 |
| LangGraph Store | 장기 기억 | 선호, 반복 구매 패턴, 모호한 표현 해석 | LangGraph 자동 관리 |
| 비즈니스 DB | 서비스 데이터 | 사용자, 배송지, 상품, 구매 이력, 추천 로그, 주문, 결제 | 직접 설계 (SQLAlchemy ORM) |

LangGraph State는 영구 저장소가 아니라 Agent 실행 중 Node 간 데이터를 전달하기 위한 임시 작업 공간이다. 예를 들어 검색 결과, 추천 후보, 선택 상품은 다음 Node에서 사용하기 위해 State에 일시적으로 담길 수 있다. 단, 사용자에게 실제로 노출된 추천 후보는 `recommendation_items`에 저장하고, 최종 주문 결과는 `orders`, `order_items`, `payments`, `purchase_histories`에 별도로 저장한다.

> 📌 비즈니스 DB는 SQLAlchemy ORM으로 직접 관리한다. LangGraph Store/Checkpointer는 같은 PostgreSQL 안에 있을 수 있지만, 우리가 직접 설계하는 비즈니스 테이블과는 논리적으로 분리된다. LangGraph 내부 테이블(langgraph_checkpoints, langgraph_store 등)은 LangGraph가 관리하기 때문에 우리가 ORM 모델로 만들 필요가 없다.
>
### 2.2 DB 테이블 분류

| 분류 | 테이블 | 한 줄 요약 |
| --- | --- | --- |
| 사용자 / 배송지 | `users`, `user_naver_accounts`,  `user_addresses` | 사용자 기본 정보, 네이버 계정 연결, 배송지 |
| 상품 / 크롤링 / 외부 상품 매핑 | `crawled_product_snapshots`, `products`, `product_options`, `external_product_mappings` | 크롤링 원본 상품 데이터, 정제된 내부 상품 정보, 옵션, 외부 플랫폼 상품 식별자 매핑 관리 |
| 구매 이력 | `purchase_histories` | 사용자의 과거 구매 기록과 재구매 판단 근거 저장 |
| 대화 / Agent 로그 | `conversations`, `conversation_messages`, `agent_intents`, `recommendations`, `recommendation_items`, `agent_events` | 대화 흐름, AI 의도 분석, 추천 후보, 사용자 선택 로그, Agent 실행 흐름 로그 저장 |
| 장바구니 / 주문 / 결제 | `carts`, `cart_items`, `checkout_sessions`, `orders`, `order_items`, `payments`, `naver_order_mappings` | 장바구니, 결제 준비, 주문, 결제, 네이버페이 주문/결제 ID 연결 관리 |
| 외부 API / 크롤링 로그 | `external_api_logs` | 외부 상품 API, 크롤링, MCP tool, 네이버페이 API 호출 결과 및 실패 로그 저장 |
각 디버그 테이블의 책임 분리

- `conversation_messages` = 사용자/AI 대화 내용 원문 저장
- `agent_intents` = Intent Agent의 사용자 요청 해석 결과 저장
- `recommendations` / `recommendation_items` = 추천 요청 1회 묶음과 그 안의 상위 2~3개 scoring 후보 저장
- 딸랑구는 음성 UX 특성상 후보를 한 번에 여러 개 보여주지 않고 rank 순서대로 하나씩 제시한다. 따라서 recommendation_items에는 내부적으로 상위 2~3개 후보를 저장하되, 실제로 사용자에게 읽어준 후보만 is_presented=true로 업데이트하고, 최종 선택된 후보만 is_selected=true로 저장한다.
- `external_api_logs` = 외부 API / tool 호출 결과 저장
- `agent_events` = Agent 내부 실행 흐름 로그 저장

`agent_intents`와 `agent_events`는 역할이 다르다. `agent_intents`는 사용자의 요청을 AI가 어떻게 해석했는지 저장하는 테이블이고, `agent_events`는 Orchestrator와 각 Agent Node가 어떤 순서로 실행됐는지 저장하는 실행 로그 테이블이다

## 4. DBML 코드

- DBML 코드 v0.2 — [dbdiagram 링크](https://dbdiagram.io/d/DDal-69ebc0a3ddb9320fdc45e3e9)
    
    ```sql
    // 딸랑구 DB Schema v0.4 Final
    // ERD 생성용 DBML 코드
    // v0.2 변경:
    //  - user_memories, user_preferences 제거 (→ LangGraph Store)
    //  - conversations에 langgraph_thread_id 추가
    // v0.3 변경:
    //  - agent_events, checkout_sessions 신규 추가
    //  - agent_intents에 intent, stage, needs_clarification 등 보강
    //  - recommendation_items에 score, is_presented, presented_at 등 보강
    //  - payments에 payment_url 추가
    //  - purchase_histories에 conversation_id, order_id, payment_id 등 추가
    //  - external_api_logs에 latency_ms 추가
    //  - orders에 checkout_session_id 추가
    //  - conversation_messages에서 message_type 제거
    // v0.4 변경:
    //  - crawled_product_snapshots 추가
    //  - naver_product_mappings → external_product_mappings로 일반화
    //  - products에 normalized_name, volume, unit, original_price, discount_rate, last_crawled_* 추가
    //  - recommendation_items에 score_detail 추가
    //  - recommendation_items의 rating/review_count를 rating_snapshot/review_count_snapshot으로 변경
    //  - conversations.stage 복구
    //  - recommendation_items에 is_orderable, order_block_reason 추가
    //  - user_addresses에 address_label 추가
    
    // 사용자 기본 정보
    Table users {
      id bigint [pk, increment]
      name varchar [not null]
      phone_number varchar
      age_group varchar
      created_at datetime [not null]
      updated_at datetime [not null]
    }
    
    // 네이버 계정/네이버페이 연동 정보
    Table user_naver_accounts {
      id bigint [pk, increment]
      user_id bigint [not null, ref: > users.id]
      naver_user_id varchar
      access_token_encrypted text
      refresh_token_encrypted text
      token_expires_at datetime
      connected_at datetime [not null]
      disconnected_at datetime
      created_at datetime [not null]
      updated_at datetime [not null]
    }
    
    // 사용자 배송지 정보
    Table user_addresses {
      id bigint [pk, increment]
      user_id bigint [not null, ref: > users.id]
      address_label varchar                    // 집, 회사, 부모님댁 등
      recipient_name varchar [not null]
      recipient_phone varchar [not null]
      zip_code varchar
      address_line1 text [not null]
      address_line2 text
      delivery_request text
      is_default boolean [not null]
      created_at datetime [not null]
      updated_at datetime [not null]
    }
    
    // 크롤링 원본 상품 데이터 snapshot
    // 추천 당시 snapshot이 아니라, 외부 플랫폼에서 관찰한 raw 상품 데이터를 보존하는 테이블
    Table crawled_product_snapshots {
      id bigint [pk, increment]
    
      platform varchar [not null]              // kurly, naver, coupang 등
      external_product_id varchar
      external_product_url text                // 참고 링크, 상품 식별 기준으로 사용하지 않음
      crawl_keyword varchar
      crawl_source varchar                     // search, category, detail, manual_seed 등
    
      // 외부 플랫폼에서 가져온 원본값
      raw_product_name text [not null]
      raw_brand varchar
      raw_category varchar
      raw_price varchar
      raw_original_price varchar
      raw_discount_rate varchar
      raw_delivery_info varchar
      raw_rating varchar
      raw_review_count varchar
      raw_image_url text
      raw_is_sold_out varchar
    
      // 원본 응답 일부 또는 전체 요약
      raw_payload json
    
      // 정제 결과
      normalized_name varchar
      normalized_brand varchar
      normalized_category varchar
      normalized_sub_category varchar
      normalized_volume varchar
      normalized_price int
      normalized_original_price int
      normalized_discount_rate float
      normalized_delivery_type varchar
      normalized_rating float
      normalized_review_count int
      normalized_is_available boolean
    
      // 정제 후 내부 products와 연결되면 저장
      product_id bigint [ref: > products.id]
      normalization_status varchar             // pending, normalized, failed
      normalization_error text
    
      crawled_at datetime [not null]
      created_at datetime [not null]
    }
    
    // 정제된 내부 상품 기본 정보
    // MVP에서는 crawled_product_snapshots를 정제해 만든 임시 상품 후보 pool 역할
    Table products {
      id bigint [pk, increment]
      name varchar [not null]
      normalized_name varchar
      brand varchar
      category varchar [not null]
      sub_category varchar
      description text
      volume varchar
      unit varchar
    
      image_url text
      current_price int
      original_price int
      discount_rate float
      rating float
      review_count int
      is_available boolean [not null]
    
      last_crawled_snapshot_id bigint [ref: > crawled_product_snapshots.id]
      last_crawled_at datetime
    
      created_at datetime [not null]
      updated_at datetime [not null]
    }
    
    // 상품 옵션 정보
    Table product_options {
      id bigint [pk, increment]
      product_id bigint [not null, ref: > products.id]
      option_name varchar
      option_value varchar
      volume varchar
      additional_price int
      stock_quantity int
      is_available boolean [not null]
      created_at datetime [not null]
      updated_at datetime [not null]
    }
    
    // 내부 상품과 외부 플랫폼 상품 식별자 매핑
    Table external_product_mappings {
      id bigint [pk, increment]
      product_id bigint [not null, ref: > products.id]
      product_option_id bigint [ref: > product_options.id]
    
      platform varchar [not null]              // kurly, naver, coupang 등
      external_product_id varchar
      external_option_id varchar
      external_product_url text                // 참고 링크, 상품 식별 기준으로 사용하지 않음
      external_product_url_hash varchar        // external_product_id가 불안정할 때 보조 식별값
      mall_name varchar
      seller_name varchar
      metadata json
    
      last_synced_at datetime
      created_at datetime [not null]
      updated_at datetime [not null]
    }
    
    // 과거 구매 이력
    Table purchase_histories {
      id bigint [pk, increment]
      user_id bigint [not null, ref: > users.id]
      product_id bigint [ref: > products.id]
      product_option_id bigint [ref: > product_options.id]
      conversation_id bigint [ref: > conversations.id]
      order_id bigint [ref: > orders.id]
      payment_id bigint [ref: > payments.id]
    
      external_order_id varchar
      external_product_order_id varchar
      platform varchar
    
      // 구매 당시 상품 정보 snapshot
      product_name_snapshot varchar [not null]
      option_snapshot varchar
      brand_snapshot varchar
      category_snapshot varchar
      price_at_purchase int [not null]
      product_url_snapshot text
      selected_options json
    
      quantity int [not null]
      total_price int [not null]
      purchased_at datetime [not null]
      satisfaction int
      memo text
      created_at datetime [not null]
    }
    
    // 대화 세션
    Table conversations {
      id bigint [pk, increment]
      user_id bigint [not null, ref: > users.id]
      langgraph_thread_id varchar              // LangGraph Checkpointer thread와 연결
      status varchar [not null]                // 대화 전체 상태
      stage varchar [not null]                 // 현재 플로우 위치: idle, searching, product_confirming 등
      started_at datetime [not null]
      ended_at datetime
      created_at datetime [not null]
      updated_at datetime [not null]
    }
    
    // 대화 메시지
    Table conversation_messages {
      id bigint [pk, increment]
      conversation_id bigint [not null, ref: > conversations.id]
      role varchar [not null]                  // user, assistant, tool
      content text [not null]
      created_at datetime [not null]
    }
    
    // 사용자 요청에 대한 AI 의도 분석 결과
    Table agent_intents {
      id bigint [pk, increment]
      conversation_id bigint [not null, ref: > conversations.id]
      user_id bigint [not null, ref: > users.id]
    
      raw_user_request text [not null]
      intent varchar [not null]                // Router가 사용하는 실행용 의도
      intent_type varchar [not null]           // 분석/평가용 상위 분류
      stage varchar
      pending_action_type varchar
    
      target_category varchar
      target_product_name varchar
      extracted_keywords text
    
      confidence float
      needs_clarification boolean
      clarification_reason text
    
      created_at datetime [not null]
    }
    
    // 추천 결과 묶음
    // 사용자 요청 1회에 대해 생성된 추천 결과 그룹
    Table recommendations {
      id bigint [pk, increment]
      conversation_id bigint [not null, ref: > conversations.id]
      user_id bigint [not null, ref: > users.id]
      intent_id bigint [ref: > agent_intents.id]
    
      recommendation_type varchar [not null]   // buy, reorder_fallback, refine 등
      keyword varchar
      summary text
      status varchar [not null]                // created, shown, selected, cancelled, failed
    
      created_at datetime [not null]
      updated_at datetime [not null]
    }
    
    // scoring된 추천 후보
    // raw result 전체 저장 아님 — State/Redis에 임시 저장
    // MVP 기준 상위 2~3개 후보만 저장
    Table recommendation_items {
      id bigint [pk, increment]
      recommendation_id bigint [not null, ref: > recommendations.id]
    
      // product_id는 nullable
      // 외부 검색/크롤링 결과가 아직 내부 products에 upsert되지 않았을 수 있음
      product_id bigint [ref: > products.id]
      product_option_id bigint [ref: > product_options.id]
      matched_purchase_history_id bigint [ref: > purchase_histories.id]
    
      rank int [not null]
      score float
      score_detail json                        // 세부 점수, 가중치, scoring mode 저장
      reason text
    
      // 추천 당시 상품 정보 snapshot
      product_name_snapshot varchar [not null]
      brand_snapshot varchar
      category_snapshot varchar
      option_snapshot varchar
      platform varchar
      price_at_recommendation int
      original_price_snapshot int
      discount_rate_snapshot float
      delivery_fee int
      delivery_info_snapshot varchar
      rating_snapshot float
      review_count_snapshot int
      product_url_snapshot text
      image_url_snapshot text
    
      is_presented boolean [not null]          // 실제로 사용자에게 음성/화면으로 제시했는지
      presented_at datetime
      is_selected boolean [not null]           // 사용자가 최종 선택했는지
    
      is_orderable boolean [not null]          // 자동 주문 가능 여부
      order_block_reason varchar               // 옵션 필요, URL 없음, 품절, 자동 주문 불가 등
    
      created_at datetime [not null]
    }
    
    // Agent 실행 흐름 로그
    Table agent_events {
      id bigint [pk, increment]
      conversation_id bigint [not null, ref: > conversations.id]
    
      agent_name varchar [not null]            // orchestrator, memory_agent, platform_agent, product_agent, payment_agent 등
      event_type varchar [not null]            // started, completed, failed, tool_called, routed
      input_summary text
      output_summary text
      error_message text
      latency_ms int
    
      created_at datetime [not null]
    }
    
    // 장바구니
    Table carts {
      id bigint [pk, increment]
      user_id bigint [not null, ref: > users.id]
      conversation_id bigint [ref: > conversations.id]
      status varchar [not null]
      created_at datetime [not null]
      updated_at datetime [not null]
    }
    
    // 장바구니 상품
    Table cart_items {
      id bigint [pk, increment]
      cart_id bigint [not null, ref: > carts.id]
    
      // cart/order로 넘어가는 시점에는 내부 product_id를 확보하는 것을 원칙으로 함
      product_id bigint [not null, ref: > products.id]
      product_option_id bigint [ref: > product_options.id]
      recommendation_item_id bigint [ref: > recommendation_items.id]
    
      quantity int [not null]
    
      // 장바구니 담을 당시 상품 정보 snapshot
      unit_price_snapshot int [not null]
      product_name_snapshot varchar [not null]
      option_snapshot varchar
    
      created_at datetime [not null]
      updated_at datetime [not null]
    }
    
    // 결제 준비 세션
    Table checkout_sessions {
      id bigint [pk, increment]
      user_id bigint [not null, ref: > users.id]
      conversation_id bigint [ref: > conversations.id]
      cart_id bigint [not null, ref: > carts.id]
    
      delivery_address_snapshot text
      address_confirmed boolean [not null]
      total_product_price int
      delivery_fee int
      total_expected_amount int
    
      status varchar [not null]
      idempotency_key varchar
    
      created_at datetime [not null]
      updated_at datetime [not null]
    }
    
    // 주문
    Table orders {
      id bigint [pk, increment]
      user_id bigint [not null, ref: > users.id]
      conversation_id bigint [ref: > conversations.id]
      cart_id bigint [ref: > carts.id]
      checkout_session_id bigint [ref: > checkout_sessions.id]
      recommendation_id bigint [ref: > recommendations.id]
      shipping_address_id bigint [ref: > user_addresses.id]
    
      // 주문 당시 배송지 snapshot
      recipient_name_snapshot varchar
      recipient_phone_snapshot varchar
      shipping_address_snapshot text
      delivery_request_snapshot text
    
      platform varchar [not null]
      order_type varchar [not null]
      status varchar [not null]
    
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
    
    // 주문 상품
    Table order_items {
      id bigint [pk, increment]
      order_id bigint [not null, ref: > orders.id]
    
      // order로 넘어가는 시점에는 내부 product_id를 확보하는 것을 원칙으로 함
      product_id bigint [not null, ref: > products.id]
      product_option_id bigint [ref: > product_options.id]
      recommendation_item_id bigint [ref: > recommendation_items.id]
    
      // 주문 당시 상품 정보 snapshot
      product_name_snapshot varchar [not null]
      option_snapshot varchar
      unit_price int [not null]
      total_price int [not null]
    
      quantity int [not null]
      external_product_order_id varchar
    
      created_at datetime [not null]
    }
    
    // 결제
    Table payments {
      id bigint [pk, increment]
      order_id bigint [not null, ref: > orders.id]
    
      payment_provider varchar [not null]
      payment_method varchar
      payment_status varchar [not null]
      payment_amount int [not null]
    
      external_payment_id varchar
      approval_number varchar
      payment_url text                         // 결제창 재진입용 임시 참고값, 장기 보관 금지
    
      paid_at datetime
      cancelled_at datetime
      failure_reason text
    
      created_at datetime [not null]
      updated_at datetime [not null]
    }
    
    // 내부 주문/결제와 네이버 주문/결제 식별자 매핑
    // 상품 매핑은 external_product_mappings로 일반화하고,
    // 네이버 주문/결제 매핑은 네이버페이 확장 대비로 별도 유지
    Table naver_order_mappings {
      id bigint [pk, increment]
      order_id bigint [not null, ref: > orders.id]
      payment_id bigint [ref: > payments.id]
    
      naver_order_id varchar
      naver_product_order_id varchar
      naver_payment_id varchar
      naver_pay_order_key varchar
      naver_status varchar
    
      last_synced_at datetime
      created_at datetime [not null]
      updated_at datetime [not null]
    }
    
    // 외부 API / 크롤링 / MCP tool 호출 로그
    Table external_api_logs {
      id bigint [pk, increment]
      user_id bigint [ref: > users.id]
      conversation_id bigint [ref: > conversations.id]
    
      provider varchar [not null]              // kurly, naver_search, naver_pay, playwright, mcp 등
      api_name varchar [not null]
      request_summary text
      response_summary text
      status_code int
      success boolean [not null]
      error_message text
      latency_ms int
    
      created_at datetime [not null]
    }
    ```
    
    ---
    
    ## 5. 상태값 Enum 후보
    
    - conversations.status
        
        ```jsx
        started
        intent_detected
        searching_product
        recommending
        waiting_user_confirmation
        confirmed
        payment_in_progress
        order_completed
        failed
        cancelled
        ```
        
    - agent_intents.intent_type
        
        ```jsx
        repurchase
        new_purchase
        cart_request
        order_status_check
        cancel_request
        clarification_needed
        unknown
        ```
        
    - orders.status
        
        ```jsx
        pending_confirmation
        confirmed
        payment_pending
        paid
        order_requested
        order_completed
        failed
        cancelled
        ```
        
    
    ---
    
    ## 6. 실제 처리 흐름
    
    ### 6.1 단계별 흐름
    
    > 🗣️ **사용자 요청:** "저번에 맛있게 먹었던 딸기 다시 사줘."
    > 
    
    | 단계 | Agent | 처리 내용 | DB 저장 위치 |
    | --- | --- | --- | --- |
    | 1 | Memory Agent | 사용자 정보·기억·구매 이력 조회 후 State 주입 | `users`, `purchase_histories`, LangGraph Store 조회 |
    | 2 | Orchestrator | 사용자 요청 분석 | `agent_intents` 저장 |
    | 3 | Platform Agent | 플랫폼 결정·네이버 상품 검색 | `products`, `product_options`, `naver_product_mappings` 갱신/조회 |
    | 4 | Product Agent | 상품 후보 비교·추천 생성 | `recommendations`, `recommendation_items` 생성 |
    | 5 | Orchestrator | 사용자에게 후보 설명 | `conversation_messages` 저장 |
    | 6 | — | 사용자 승인 | — |
    | 7 | Orchestrator | 장바구니·주문 생성 | `carts`, `cart_items`, `orders`, `order_items` 생성, `user_addresses` 조회 및 주문 배송지 snapshot 저장 |
    | 8 | Payment Agent | 네이버페이 결제 요청 | `payments`, `naver_order_mappings` 저장 |
    | 9 | Memory Agent | 구매 이력 저장·기억 업데이트 | `purchase_histories` 저장, LangGraph Store 업데이트 |
    
    ---
    
    ### 6.2 PM님 설계 기준 DB 대응 흐름
    
    ```notion
    Memory Agent 기본 로드
    → users, user_addresses, LangGraph Store, purchase_histories 조회
    → State에 주입
    
    Orchestrator ("딸기 살래" 감지)
    → agent_intents 저장
    → conversations 상태 변경
    
    Memory Agent 딸기 이력 동적 조회
    → purchase_histories, user_memories 조회
    → State.keyword_history 구성
    
    Platform Agent
    → 네이버 쇼핑 검색 API 호출
    → raw data는 필요 시 Redis에 임시 저장하거나 폐기
    → State에는 product_name, price, link, image_url, mall_name 등 경량화된 search_results만 저장
    
    Product Agent
    → recommendations 생성
    → recommendation_items 생성
    
    Orchestrator
    → 사용자에게 설명
    → conversation_messages 저장
    
    사용자 승인
    → conversation_messages 저장
    → carts / cart_items 생성
    → orders / order_items 생성
    
    Payment Agent
    → State에 주입된 배송지 조회
    → 원천은 user_addresses 기반
    → orders에 배송지 snapshot 저장
    → 네이버페이 호출
    → payments, naver_order_mappings 저장
    
    Memory Agent 저장 위임
    → purchase_histories 저장
    → LangGraph Store 업데이트
    ```
    
    ---
 