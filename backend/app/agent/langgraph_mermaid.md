# LangGraph Mermaid Diagrams

이 문서는 현재 코드 기준 LangGraph 오케스트레이션 구조를 `mermaid`로 빠르게 확인하기 위한 다이어그램 모음입니다.

기준 코드:
- `backend/vendor/ddalangoo-langgraph/src/graph/builder.py`
- `backend/vendor/ddalangoo-langgraph/src/graph/router.py`
- `backend/vendor/ddalangoo-langgraph/src/payment/subgraph.py`
- `backend/app/agent/runtime.py`
- `backend/app/agent/mapper.py`

## 1. Main Orchestrator Graph

```mermaid
flowchart TD
    A[wait_for_input] --> B[intent_agent]

    B -->|memory_agent| C[memory_agent]
    B -->|reorder_node| D[reorder_node]
    B -->|platform_agent| E[platform_agent]
    B -->|product_agent| F[product_agent]
    B -->|payment_agent| G[payment_agent]
    B -->|quantity_check| H[quantity_check]
    B -->|ask_what_to_buy| I[ask_what_to_buy]
    B -->|respond| J[respond]
    B -->|cancel| K[cancel]
    B -->|end| Z[END]

    C -->|reorder| D
    C -->|buy/refine/compare| E
    C -->|other| J

    D -->|resolved| J
    D -->|fallback to search| E

    E -->|platform_suggest| J
    E -->|search results| F

    F --> J

    H --> J
    I --> J
    K --> J

    G -->|completed| C
    G -->|otherwise| J

    J -->|wait_for_input| A
    J -->|end| Z
```

설명:
- `intent_agent`가 발화를 구조화한 뒤 `router`가 다음 노드를 고릅니다.
- `memory_agent`는 재구매 문맥 또는 선호도 컨텍스트를 준비합니다.
- `platform_agent`는 검색 플랫폼을 고르고, `product_agent`는 랭킹/설명을 만듭니다.
- `payment_agent`는 장바구니/결제 단계 상태를 전개합니다.
- 실제 사용자에게 들려줄 문장은 마지막 `respond` 노드에서 확정됩니다.

## 2. Router Decision Map

```mermaid
flowchart TD
    A[intent_agent output] --> B{needs_clarification\nor low confidence?}
    B -->|yes| R[respond]
    B -->|no| C{intent == cancel?}
    C -->|yes| X[cancel]
    C -->|no| D{stage == payment_processing?}
    D -->|yes| P[payment_agent]
    D -->|no| E{stage == cart_shopping?}

    E -->|new product intent| PL[platform_agent or memory_agent]
    E -->|confirm checkout| P
    E -->|deny/next| Q[ask_what_to_buy]
    E -->|other| R

    E --> F{stage == product_confirming?}
    F -->|quantity missing| N[quantity_check]
    F -->|confirm with quantity| P
    F -->|deny/next/ask| PR[product_agent]
    F -->|refine/compare| PL
    F -->|other| R

    F --> G{stage == searching?}
    G -->|refine/compare| PL
    G -->|other| R

    G --> H[idle/default routing]
    H -->|buy/reorder| M[memory_agent]
    H -->|refine/compare| PL
    H -->|ask/next| PR
    H -->|other| R
```

설명:
- 같은 `"응"`도 현재 `stage`와 `pending_action.type`에 따라 전혀 다른 노드로 갑니다.
- 이 프로젝트의 핵심 분기 기준은 `intent` 하나가 아니라 `intent + stage + pending_action` 조합입니다.

## 3. Product Discovery Flow

```mermaid
flowchart TD
    A[user says product request] --> B[intent_agent]
    B --> C[memory_agent]
    C -->|buy| D[platform_agent]
    C -->|reorder| E[reorder_node]

    D -->|platform_suggest| F[respond with platform suggestion]
    D -->|search results| G[product_agent]

    E -->|product resolved| H[respond with reorder confirm]
    E -->|no match / bad url| D

    G --> I[rank candidate products]
    I --> J[generate explanation]
    J --> K[respond]
```

설명:
- 일반 구매는 `memory_agent -> platform_agent -> product_agent` 흐름이 기본입니다.
- 재구매는 `memory_agent -> reorder_node`로 바로 재주문 후보를 고를 수 있습니다.

## 4. Payment Flow

```mermaid
flowchart TD
    A[product_confirming + confirm] --> B{quantity exists?}
    B -->|no| Q[quantity_confirm]
    B -->|yes| C[cart_shopping\ncontinue_shopping]

    Q --> R[respond]
    C --> D{user wants checkout?}
    D -->|no, shop more| S[ask_what_to_buy / platform flow]
    D -->|yes| E[payment_method_confirm]

    E --> F{address exists?}
    F -->|no| G[address_required]
    F -->|yes| H[address_confirm]

    H --> I[payment_password]
    I --> J[bridge_shopping_to_payment]
    J --> K[payment_flow]
    K --> L[bridge_payment_to_shopping]
    L --> M[completed]

    M --> N[respond with completion message]
    G --> N
```

설명:
- 현재 결제는 완전 독립 그래프라기보다 `payment_agent_node` 안에서 `pending_action.type` 기반으로 단계가 전개됩니다.
- 실제 DB `cart/order/payment` 생성은 LangGraph 밖 `agent_service` 후처리가 담당합니다.

## 5. Real Browser / WebView Branch

```mermaid
flowchart TD
    A[payment_agent] --> B{USE_REAL_BROWSER and kurly?}
    B -->|no| C[normal payment prompts]
    B -->|yes| D[run_kurly_purchase]

    D -->|cancelled| E[idle]
    D -->|price changed| F[price_change_confirm]
    D -->|cart added| G[cart_shopping]
    D -->|failed| H[failed]

    F --> I[respond]
    G --> I
    E --> I
    H --> I
    C --> I
```

설명:
- 컬리 실브라우저 모드가 켜지면 `payment_agent` 안에서 Playwright 웹뷰 자동화로 분기합니다.
- 이 경로는 `webview_progress`와 연결되어 프론트의 `asyncStatus`에도 반영됩니다.

## 6. Runtime Resume Model

```mermaid
sequenceDiagram
    participant API as FastAPI agent_service
    participant RT as runtime.py
    participant LG as LangGraph
    participant CP as Checkpointer

    API->>RT: start(user_id, message, conversation_id)
    RT->>LG: ainvoke(initial_state, thread_id)
    LG-->>RT: interrupt before wait_for_input
    RT->>LG: aupdate_state(messages=[user])
    RT->>LG: ainvoke(None)
    LG->>CP: save snapshot
    LG-->>RT: interrupt before next wait_for_input
    RT-->>API: snapshot.values

    API->>RT: resume(conversation_id, message)
    RT->>LG: aupdate_state(messages=[user])
    RT->>LG: ainvoke(None)
    LG->>CP: save snapshot
    LG-->>RT: interrupt before next wait_for_input
    RT-->>API: snapshot.values
```

설명:
- `thread_id = conversation_id`로 같은 대화를 이어갑니다.
- 한 턴이 끝날 때마다 상태 스냅샷이 저장되고, 다음 입력에서 이어서 재개됩니다.

## 7. Frontend to Voice to LangGraph Sequence

```mermaid
sequenceDiagram
    participant U as User
    participant FE as Frontend CallProvider
    participant STT as /api/voice/stt
    participant AG as /api/agent/*
    participant LG as LangGraph
    participant MP as AgentResponse mapper
    participant TTS as /api/voice/tts

    U->>FE: speak
    FE->>STT: upload wav file
    STT-->>FE: transcript

    FE->>AG: shopping-requests or messages
    AG->>LG: start/resume
    LG-->>AG: ShoppingState
    AG->>MP: state_to_response()
    MP-->>FE: AgentResponse

    FE->>TTS: assistantMessage
    TTS-->>FE: audioBase64
    FE-->>U: play audio
```

설명:
- LangGraph 내부 state는 프론트로 직접 가지 않습니다.
- `mapper.state_to_response()`가 프론트가 쓰는 `AgentResponse` 계약으로 변환합니다.

## 8. State Ownership Summary

```mermaid
flowchart LR
    A[ShoppingState] --> B[intent / keywords / product / pending_action]
    A --> C[cart / order / payment summary]
    A --> D[assistant messages]
    A --> E[webview progress refs]

    B --> F[router decisions]
    D --> G[respond_node]
    C --> H[mapper -> AgentResponse]
    E --> H
```

설명:
- 실질적으로 `ShoppingState`가 시스템의 단일 작업 메모리 역할을 합니다.
- 프론트 UI 전환도 결국 `stage`, `pending_action`, `messages`에서 파생됩니다.
