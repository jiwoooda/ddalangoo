"""
context_routing_eval 데이터셋(final_dataset.jsonl) <-> 딸랑구 에이전트 스키마 어댑터.

final_dataset.jsonl은 별도 파이프라인(Amazon-C4 기반)에서 만들어진 데이터셋이라
필드명이 시스템(src/agents/*)이 기대하는 것과 다르다. 이 모듈은 그 차이를
흡수하는 역할만 하고, src/agents/*의 내부 로직은 전혀 건드리지 않는다.

핵심 제약 2가지 (evals/data/final_dataset_report.json으로 확인됨):
  1. candidates는 gold_product를 절대 포함하지 않도록 만들어졌다
     (gold_in_candidates_check.offender_count == 0). 그래서 반드시
     candidate_slicer.get_eval_candidates(..., ensure_gold=True)를 거쳐야
     gold가 포함된 후보 리스트가 나온다 — 이걸 건너뛰면 mrr/ndcg가 항상 0이 된다.
  2. candidates에 product_url이 없으면 src.agents.product_agent._filter_results가
     100% 걸러낸다(`if not p.get("product_url"): continue`). 그래서
     map_candidate_to_system_schema가 asin 기반 더미 product_url을 반드시 채운다.
"""
from __future__ import annotations

from typing import Any

from evals.candidate_slicer import get_eval_candidates


# ══════════════════════════════════════════════
# 후보 필드 매핑
# ══════════════════════════════════════════════

def map_candidate_to_system_schema(candidate: dict) -> dict:
    """final_dataset.jsonl candidate 1개 -> 시스템(product_agent) 스키마.

    필드 매핑 근거:
      title            -> product_name  (이름만 다름, 의미 동일)
      price            -> price         (그대로, 둘 다 숫자)
      average_rating   -> rating        (이름만 다름)
      store            -> platform      (판매처라는 의미가 제일 가까움)
      asin             -> product_url   (원본에 URL이 아예 없음 — _filter_results가
                                          product_url 없는 후보를 전부 걸러내므로
                                          asin으로 결정론적 더미 URL을 만들어 채운다.
                                          실제 URL이 아니라 "필터 통과 + 후보 식별"용)
      review_count, brand는 원본에 대응 필드가 없다 — 억지로 채우지 않고 생략한다.
      (product_agent._format_products/_baseline_rank 모두 .get()으로 접근해서
      없으면 "정보 없음"/0으로 안전하게 처리되므로 None을 채워 넣는 것보다 낫다.)
    """
    asin = candidate.get("asin", "")
    return {
        "product_name": candidate.get("title", ""),
        "price": candidate.get("price"),
        "rating": candidate.get("average_rating"),
        "platform": candidate.get("store", ""),
        "product_url": f"https://example.com/{asin}",
        "_asin": asin,  # 디버그/추적용 — 시스템 필드 아님, product_agent가 안 읽음
    }


def prepare_candidates_for_eval(record: dict, k: int = 20) -> list[dict]:
    """평가에 쓸 후보 리스트를 만드는 유일한 진입점.

    candidate_slicer.get_eval_candidates(record, k=k, ensure_gold=True)로
    gold가 포함된 top-k를 먼저 확보한 다음, 각 항목을 시스템 스키마로 변환한다.
    ensure_gold=True 경로는 항상 {"candidates": [...], "meta": {...}} 형태의
    dict를 반환하므로(bare list 아님) "candidates" 키로 꺼내야 한다.

    이 함수를 거치지 않고 record["candidates"]를 직접 시스템에 넣으면 안 된다 —
    gold가 없어서 mrr/ndcg가 항상 0이 나오고, product_url도 없어서
    _filter_results가 전부 걸러낸다.
    """
    sliced = get_eval_candidates(record, k=k, ensure_gold=True)
    candidates = sliced["candidates"]
    return [map_candidate_to_system_schema(c) for c in candidates]


# ══════════════════════════════════════════════
# 정답(expected output) 매핑
# ══════════════════════════════════════════════

def record_to_expected_output(record: dict) -> dict:
    """gold_product -> mrr_evaluator/ndcg_at_3_evaluator가 기대하는 reference_outputs 형태.

    evaluators.py를 실제로 읽고 맞춘 형식(evaluators.py:201-226):
      - mrr_evaluator: reference_outputs["expected_top_product"]를 outputs["ranked_products"]
        안에서 product_name 문자열 완전일치로 찾아 순위의 역수를 점수로 준다.
      - ndcg_at_3_evaluator: reference_outputs["expected_ranking"](관련도 내림차순 이름 리스트)를
        보고 rel_map = {name: len(relevant)-i}로 관련도를 매긴 뒤 DCG/IDCG를 계산한다.

    이 데이터셋은 레코드당 gold가 1개뿐이라(다단계 관련도 라벨 없음) "완전한
    정답 랭킹"은 만들 수 없다. 그래서 expected_ranking은 길이 1짜리
    [gold_product 이름]으로 준다 — ndcg_at_3_evaluator 입장에선 "gold가 top-3
    안에 있는지, 있다면 몇 위인지"만 반영하는 단순화된 지표가 된다(관련도
    2단계 이상 비교는 불가). 본 실험에서 더 정교한 랭킹 정답이 필요해지면
    이 함수만 바꾸면 된다 — evaluators.py 쪽은 그대로 재사용 가능.

    이름 매칭은 map_candidate_to_system_schema가 title -> product_name으로
    그대로 옮기므로, gold_product["title"]을 쓰면 ranked_products 안의
    product_name과 정확히 일치한다.
    """
    gold_title = record["gold_product"].get("title", "")
    return {
        "expected_top_product": gold_title,
        "expected_ranking": [gold_title],
    }


# ══════════════════════════════════════════════
# 대화/노드 입력 매핑
# ══════════════════════════════════════════════

def record_to_messages(record: dict) -> list[dict]:
    """query + smalltalk -> ShoppingState["messages"] 형태.

    순서는 [smalltalk..., query] — smalltalk를 먼저 넣고 query를 마지막에 둔다.

    이유(스모크 테스트로 실제 검증됨): src.agents.intent_agent._extract_user_input()은
    messages를 reversed()로 훑어서 처음 만나는(=리스트상 마지막) user 메시지를
    "이번 요청"으로 파싱한다. query를 먼저 넣으면 intent_agent가 매번 마지막
    smalltalk 문장을 "이번 요청"으로 잘못 읽어 들여서 keywords/intent가 실제
    쿼리 내용과 무관하게 나온다 — 최초 구현에서 이 순서([query, smalltalk...])로
    했다가 이 문제가 실제로 확인돼 지금 순서로 뒤집었다. smalltalk(과거 맥락) ->
    query(지금 이 요청) 순서가 실제 대화 흐름과도 더 자연스럽다.

    context_agent._summarize_messages/_classify_context는 messages 안의
    role=="user" 텍스트를 전부 모아서 LLM에 넘기므로 순서가 바뀌어도 선호도
    분류에 쓰는 정보량 자체는 동일하다 — 오히려 "언제 이 말이 나왔는지"가
    실제 대화 흐름과 일치해서 recency 판단(priority_resolver.rank_by_recency)에도
    더 맞다.
    """
    messages = [{"role": "user", "content": line} for line in (record.get("smalltalk") or [])]
    messages.append({"role": "user", "content": record.get("query", "")})
    return messages


def ensure_onboarded(user_id: str, when: str = "2020-01-01T00:00:00+00:00") -> None:
    """user_id를 "이미 온보딩된 사용자"로 미리 표시한다. 노드/그래프 호출
    직전에 반드시 호출할 것 — smoke_test.py와 본 실험(Baseline vs Ours)
    harness 양쪽에서 재사용해야 한다.

    신규유저(구매이력 없음 + 미온보딩)는 그래프 레벨 게이트
    (src.graph.router.route_entry)가 intent_agent를 거치지 않고 바로
    smalltalk_agent로 보낸다(신규유저 온보딩 이벤트 UX) — 이 하네스는
    intent_agent_node/context_agent_node 등을 그래프 밖에서 직접 호출하므로
    이 게이트 자체를 안 타지만, 실서비스에서도 온보딩을 거쳤을 법한 유저를
    평가하는 게 맞으므로 이 함수로 db_client 프로필에 onboarded_at을
    미리 심어서 "온보딩된 유저" 상태로 맞춰둔다.

    기존 프로필이 있으면 병합만 하고(다른 필드 보존), 이미 onboarded_at이
    있으면 재저장하지 않는다(불필요한 computed_at 갱신 방지).
    """
    from src.tools import db_client

    profile = db_client.get_profile(user_id) or {}
    if profile.get("onboarded_at"):
        return
    merged = dict(profile)
    merged["onboarded_at"] = when
    db_client.save_profile(user_id, merged)


def seed_purchase_history(user_id: str, record: dict) -> None:
    """record["purchase_history_top_k"]를 mock 구매이력 DB에 심는다. 노드/그래프
    호출 직전에 ensure_onboarded와 함께 반드시 호출할 것 — smoke_test.py와
    본 실험 harness 양쪽에서 재사용해야 한다.

    스팟체크로 실제 확인된 문제: src.agents.context_agent.build_preference_context()는
    _fetch_purchase_histories(user_id)가 빈 리스트면(첫 줄 `if not histories:
    return {"safety_constraints": ...}`) smalltalk 분류(_classify_context) 자체를
    아예 시도하지 않고 조기 반환한다. 이 데이터셋의 user_id는 전부 원본 Amazon
    ID라 시스템 mock DB엔 구매이력이 하나도 없어서, 12건 스팟체크에서
    soft_preferences/exclude_additions/overridden_exclusions가 매번 빈 리스트로
    나왔다 — smalltalk가 아무리 풍부해도 신호 분류 자체가 실행이 안 된 것.
    conflict_signals(현재 의도가 과거 명시적 제외를 override하는지) 검증은
    특히 overridden_exclusions가 채워져야 의미가 있으므로 이 시딩 없이는
    이 데이터셋의 핵심 목적(context routing 검증)을 테스트할 수 없다.

    record["purchase_history_top_k"](asin/title/category_score/embedding_score/
    source_category)를 src.tools.mock_tools.MOCK_PURCHASE_HISTORY가 기대하는
    스키마(product_name/category/keyword/brand/price_at_purchase/platform/
    product_url/purchased_at/...)로 매핑한다. keyword 필드는 억지로 만들어
    매칭을 유리하게 조작하지 않는다 — product_name/category만 채우고, 실제
    매칭 여부(build_preference_context의 substring 비교)는 데이터 자체의
    관련성에 맡긴다. purchased_at은 최신순 정렬 가정(mock_get_purchase_history
    docstring 참고)에 맞춰 인덱스가 작을수록(=원 데이터에서 더 관련도 높은
    순서) 더 최근 시각을 준다.

    같은 user_id로 이미 시딩됐으면 다시 쓰지 않는다(중복 방지, 여러 단계에서
    같은 레코드를 반복 호출해도 안전).
    """
    from datetime import datetime, timedelta, timezone

    from src.tools.mock_tools import MOCK_PURCHASE_HISTORY

    if MOCK_PURCHASE_HISTORY.get(str(user_id)):
        return

    top_k = record.get("purchase_history_top_k") or []
    if not top_k:
        return  # 이 레코드 자체가 구매이력 없음(A_no_history 그룹) — 시딩할 게 없음, 정상

    base_time = datetime.now(timezone.utc)
    entries = []
    for i, h in enumerate(top_k):
        entries.append({
            "id": f"seed_{record.get('record_id')}_{i}",
            "order_id": f"seed_order_{record.get('record_id')}_{i}",
            "product_name": h.get("title", ""),
            "brand": None,
            "category": h.get("source_category"),
            "option_text": None,
            "platform": "amazon",
            "price_at_purchase": 0,
            "quantity": 1,
            "total_price": 0,
            "selected_options": {},
            "product_url": f"https://example.com/{h.get('asin', '')}",
            "purchased_at": (base_time - timedelta(days=i)).isoformat(),
            "satisfaction_score": None,
            "keyword": None,
        })
    MOCK_PURCHASE_HISTORY[str(user_id)] = entries


def record_to_intent_input(record: dict, user_id: str) -> dict:
    """src/state/node_inputs.py의 IntentAgentInput 필드(messages, stage,
    pending_action, keywords, quantity, recipe_dish, recipe_people, user_id)에
    정확히 맞춘 state dict. 첫 턴이므로 stage="idle", pending_action=None,
    나머지 슬롯은 전부 미확정(None/빈 값) 상태로 둔다 — get_default_shopping_state와
    동일한 초기값 규칙을 따름(src/state/schema.py).
    """
    return {
        "messages": record_to_messages(record),
        "stage": "idle",
        "pending_action": None,
        "keywords": [],
        "quantity": None,
        "recipe_dish": None,
        "recipe_people": None,
        "user_id": user_id,
    }
