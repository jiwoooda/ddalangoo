# VIVID Regression Specification

## 목적

VIVID는 딸랑구 전체 Multi-Agent Workflow의
사용자 관점 E2E Regression Test로 사용한다.

Agent Unit Test와는 별개이며,
주요 수정 Cycle 종료 후 동일한 조건으로 다시 실행한다.


# Environment

catalog: mock_catalog_v1
catalog_items:
- 딸기
- 계란/달걀
- 우유
- 사과
- 참기름
- 두부

total_personas: 4
total_scenarios: 4
total_sessions: 16


# Personas

## P1 김순자
- 78세 여성
- 경상도
- 스마트폰 초보
- 특징:
  - 사투리 사용
  - 대화를 통한 안심/라포 형성에 긍정적
  - 쇼핑 과정에서는 명확한 안내 필요

## P2 이말순
- 80세 여성
- 충청도
- 스마트폰 초보
- 특징:
  - 사투리 사용
  - 반복 오류가 발생하면 강한 좌절
  - 구매/결제 과정에 명확한 안내 필요

## P3 박종수
- 71세 남성
- 전라도
- 스마트폰 중급
- 특징:
  - 비교적 직접적인 요청
  - 반복 오류 시 빠르게 불만 표현

## P4 정영호
- 66세 남성
- 표준어
- 스마트폰 능숙
- 특징:
  - 목적 지향적
  - 불필요한 스몰토크를 마찰로 느낄 수 있음
  - 빠른 task completion 선호


# Scenarios

## S1 탐색형

시작:
특별히 구매 품목을 정하지 않은 상태에서
자연스럽게 대화를 시작한다.

목표:
Smalltalk을 통해 사용자의 쇼핑 의도를 발견하고
실제 상품 탐색/구매 단계로 자연스럽게 전환하는지 평가.

핵심 평가:
- 자연스러운 smalltalk
- 쇼핑 의도 발견
- smalltalk → commerce 전환


## S2 즉시 요청

대표 시작:
"우유 좀 사줘"

조건:
사용자가 처음부터 품목과 수량을 비교적 명확하게 말한다.

목표:
불필요한 smalltalk 없이 즉시 구매 workflow로 진입.

핵심 평가:
- intent 인식
- 상품/브랜드/수량 유지
- 장바구니 조작
- 주문 진행


## S3 애매 요청

대표 시작:
"뭐 먹을 거 좀 사야 하는데"

목표:
사용자가 원하는 상품을 스스로 명확히 말하지 못할 때
Agent가 적절한 추천을 수행하는지 평가.

핵심 평가:
- recommendation intent
- 실제 추천 행동
- 반복 질문/echo loop 방지
- 필요할 때만 clarification


## S4 화제 이탈

조건:
계란/참기름 등 구매 의도가 있는 상태에서
무릎, 날씨 등 다른 이야기가 중간에 등장한다.

목표:
Smalltalk/context를 자연스럽게 처리하면서도
원래 쇼핑 task를 잃어버리지 않는지 평가.

핵심 평가:
- context 유지
- topic switching
- task recovery
- cart state 유지


# Baseline

현재 최초 VIVID 결과:

goal_success: 3/16
abandon: 7/16
cart_decrease: 0/9 observed transitions

scenario_success:
- S1 탐색형: 3/4
- S2 즉시 요청: 0/4
- S3 애매 요청: 0/4
- S4 화제 이탈: 0/4


# Regression Rule

주요 Agent/Workflow 수정 Cycle 종료 후
동일한 4 personas × 4 scenarios를 재실행한다.

비교할 것:

- goal success
- abandon
- cart remove/change success
- explicit brand follow
- explicit quantity follow
- recommendation completion
- payment/delivery/address response
- false fallback
- repeated intent loop
- smalltalk → shopping transition


# 중요

VIVID Failure만 보고 특정 Agent/Prompt 문제라고 단정하지 않는다.

VIVID는 E2E failure discovery 용도이다.

Failure 발견 후:

VIVID
→ Failure Inbox
→ Trace 분석
→ Unit / Integration / E2E 원인 분류
→ Living Test 생성
→ 수정
→ Regression
→ VIVID 재실행