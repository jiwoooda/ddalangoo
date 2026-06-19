# Technical Details Presentation Outline

발표 주제:
- System Architecture
- Multi-Agent 구조
- LangGraph 설계
- 음성 처리 파이프라인

이 문서는 발표 슬라이드 구성안과 발표 멘트를 빠르게 준비하기 위한 노트입니다.

---

## 1. System Architecture

### 슬라이드 제목
`System Architecture`

### 이 슬라이드에서 답할 질문
`이 시스템은 어떤 계층으로 나뉘어 있고, 각 계층은 무엇을 담당하는가?`

### 핵심 한 줄
`전체 시스템은 음성 입출력, 대화 의사결정, 비즈니스 처리, 프론트 UI 계층으로 분리되어 있습니다.`

### 추천 시각화
- `sequenceDiagram` 또는 block diagram
- 추천 소스: [langgraph_mermaid_presentation.md](/Users/synuo/Documents/GitHub/AYearApart/backend/app/agent/langgraph_mermaid_presentation.md) 의 `Slide 7. End-to-End Architecture`

### 슬라이드에 넣을 핵심 포인트
- Frontend는 음성 녹음/재생과 UI 상태 표시를 담당
- Voice layer는 STT/TTS를 담당
- Agent API는 LangGraph와 비즈니스 로직을 연결
- LangGraph는 대화 상태 기반 의사결정 담당
- DB / WebView / 외부 검색은 실행 계층 담당

### 30초 발표 멘트
`먼저 전체 구조입니다. 사용자가 음성으로 요청하면 프론트엔드가 오디오를 받아 STT로 텍스트를 만들고, Agent API가 LangGraph를 통해 현재 대화 상태에 맞는 결정을 내립니다. 그 결과는 AgentResponse로 프론트에 전달되고, 최종 assistantMessage는 다시 TTS를 거쳐 음성으로 재생됩니다. 즉, 음성 계층과 대화 의사결정 계층, 그리고 비즈니스 실행 계층을 분리한 구조입니다.`

---

## 2. Multi-Agent Structure

### 슬라이드 제목
`Multi-Agent Structure`

### 이 슬라이드에서 답할 질문
`왜 하나의 모델이 아니라 여러 agent로 나눴고, 각 agent는 무엇을 하는가?`

### 핵심 한 줄
`하나의 거대 모델이 모든 결정을 하지 않고, 역할별 전문 agent를 LangGraph 위에서 조합했습니다.`

### 추천 시각화
- `flowchart`
- 추천 소스: [langgraph_mermaid_presentation.md](/Users/synuo/Documents/GitHub/AYearApart/backend/app/agent/langgraph_mermaid_presentation.md) 의 `Slide 1. One-Screen Summary`

### 슬라이드에 넣을 핵심 포인트
- `intent_agent`: 사용자 발화 구조화
- `memory_agent`: 구매 이력 / 선호도 문맥 준비
- `platform_agent`: 검색 플랫폼 선택 및 검색
- `product_agent`: 상품 랭킹 / 설명 / QA
- `payment_agent`: 수량 / 장바구니 / 결제 단계 처리
- `respond`: 최종 사용자 응답 문장 확정

### 30초 발표 멘트
`이 시스템은 하나의 모델에 모든 책임을 몰아주지 않았습니다. intent_agent는 발화를 해석하고, memory_agent는 장기 문맥을 준비하고, platform_agent와 product_agent는 상품 탐색과 추천을 담당합니다. 이후 payment_agent가 장바구니와 결제 흐름을 이어가고, 마지막 respond 노드에서만 실제 사용자에게 들려줄 문장이 확정됩니다. 이렇게 역할을 나누면 유지보수와 제어성이 좋아집니다.`

---

## 3. LangGraph Design

### 슬라이드 제목
`LangGraph Design`

### 이 슬라이드에서 답할 질문
`이 agent들은 어떤 원리로 오케스트레이션되며, 왜 LangGraph가 필요한가?`

### 핵심 한 줄
`이 시스템은 단순 질의응답이 아니라, 상태 기반으로 흐름을 이어가는 대화 엔진입니다.`

### 추천 시각화
- 대표: 상태 머신형 flowchart
- 보조: state-centered diagram
- 추천 소스:
  - [langgraph_mermaid_presentation.md](/Users/synuo/Documents/GitHub/AYearApart/backend/app/agent/langgraph_mermaid_presentation.md) 의 `Slide 2. State-Centered Design`
  - [langgraph_mermaid_presentation.md](/Users/synuo/Documents/GitHub/AYearApart/backend/app/agent/langgraph_mermaid_presentation.md) 의 `Slide 3. Main Conversation Flow`
  - [langgraph_mermaid_presentation.md](/Users/synuo/Documents/GitHub/AYearApart/backend/app/agent/langgraph_mermaid_presentation.md) 의 `Slide 4. Why Router Matters`

### 슬라이드에 넣을 핵심 포인트
- 중심 데이터는 `ShoppingState`
- `router`는 `intent + stage + pending_action`을 함께 봄
- 같은 사용자 발화도 state에 따라 의미가 달라짐
- `interrupt_before=["wait_for_input"]`로 턴 단위 resume 가능
- `conversation_id` 단위로 상태를 이어감

### 40초 발표 멘트
`LangGraph를 쓴 이유는 대화를 상태 기반으로 관리하기 위해서입니다. 이 시스템의 중심은 LLM이 아니라 ShoppingState입니다. 각 노드는 state를 읽고 일부를 갱신하고, router는 intent만 보는 것이 아니라 현재 stage와 pending_action까지 함께 보고 다음 노드를 결정합니다. 그래서 같은 ‘응’이라는 발화도 상품 구매 확인인지, 수량 응답인지, 결제 확인인지 문맥에 맞게 해석할 수 있습니다.`

---

## 4. Voice Processing Pipeline

### 슬라이드 제목
`Voice Processing Pipeline`

### 이 슬라이드에서 답할 질문
`사용자 음성이 어떻게 실제 대화 응답으로 변환되고 다시 음성으로 재생되는가?`

### 핵심 한 줄
`음성 계층은 입출력을 담당하고, LangGraph는 그 사이에서 대화 결정을 담당합니다.`

### 추천 시각화
- `sequenceDiagram`
- 추천 소스: [langgraph_mermaid_presentation.md](/Users/synuo/Documents/GitHub/AYearApart/backend/app/agent/langgraph_mermaid_presentation.md) 의 `Slide 7. End-to-End Architecture`

### 슬라이드에 넣을 핵심 포인트
- 사용자 음성 -> STT -> transcript
- transcript -> Agent API -> LangGraph
- LangGraph -> `ShoppingState`
- mapper -> `AgentResponse`
- `assistantMessage` -> TTS -> 음성 재생

### 30초 발표 멘트
`음성 처리 파이프라인은 입력과 출력이 명확히 분리되어 있습니다. 사용자의 음성은 먼저 STT를 통해 transcript로 변환되고, 이 텍스트가 LangGraph 기반 에이전트 시스템으로 들어갑니다. LangGraph는 현재 대화 상태를 바탕으로 assistantMessage를 만들고, 그 결과는 다시 TTS를 통해 오디오로 변환되어 재생됩니다. 즉, 음성은 인터페이스이고, LangGraph는 그 안의 의사결정 엔진입니다.`

---

## 추천 발표 순서

1. `System Architecture`
2. `Multi-Agent Structure`
3. `LangGraph Design`
4. `Voice Processing Pipeline`

이 순서가 좋은 이유:
- 먼저 전체 시스템 경계를 보여주고
- 그 안의 agent 역할 분리를 설명한 뒤
- LangGraph가 그 agent들을 어떻게 오케스트레이션하는지 보여주고
- 마지막에 사용자 관점 end-to-end 음성 흐름으로 닫을 수 있습니다.

---

## 발표 팁

- `System Architecture`에서는 기술 스택보다 계층 분리를 강조하는 편이 좋습니다.
- `Multi-Agent`에서는 agent 이름보다 역할을 쉽게 말하는 편이 이해가 빠릅니다.
- `LangGraph Design`은 “왜 상태 기반이어야 하는가”를 예시 발화 `"응"`으로 설명하면 직관적입니다.
- `Voice Pipeline`에서는 STT/TTS 모델명보다 “입력/결정/출력의 분리”를 먼저 말하는 게 좋습니다.

---

## 2분 버전 요약 멘트

`저희 시스템은 음성 쇼핑 어시스턴트를 만들기 위해, 음성 입출력 계층과 대화 의사결정 계층을 분리했습니다. 사용자의 발화는 먼저 STT로 텍스트가 되고, 이 텍스트는 LangGraph 기반 multi-agent 구조로 들어갑니다. 여기서 intent agent가 발화를 해석하고, memory, platform, product, payment agent가 역할별로 협업합니다. 중요한 점은 이 전체 흐름이 ShoppingState 중심으로 동작한다는 것입니다. 즉, 단순한 Q&A가 아니라 대화 상태를 이어가는 상태 기반 엔진이며, 최종 assistantMessage만 TTS를 통해 다시 사용자에게 음성으로 전달됩니다.`
