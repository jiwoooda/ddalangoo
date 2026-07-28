"""
스모크 테스트 — 딸랑구 에이전트 x context_routing_eval 데이터셋.

목적은 "정확한가"가 아니라 "크래시 없이 도는가"다. 본 실험(전체 Baseline
비교, 최종 지표 산출)은 이 스크립트의 스코프가 아니다.

_filter_results / _rank_with_metadata / evaluators.py의 내부 로직은
전혀 건드리지 않는다 — 어댑터(adapter.py)에서만 필드를 맞춘다.

사용법:
  python -m evals.context_routing_eval.smoke_test
"""
from __future__ import annotations

import json
import random
import sys
import time
import traceback
import uuid
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo(ddalangoo-langgraph) root

from evals.context_routing_eval.adapter import (
    ensure_onboarded,
    prepare_candidates_for_eval,
    record_to_expected_output,
    record_to_intent_input,
    record_to_messages,
    seed_purchase_history,
)
from evals.candidate_slicer import get_eval_candidates
from evals.evaluators import mrr_evaluator, ndcg_at_3_evaluator

from src.agents.intent_agent import intent_agent_node
from src.agents.context_agent import context_agent_node
from src.agents.product_agent import _filter_results, _rank_with_metadata
from src.agents.response_agent import response_agent_node
from src.state.schema import get_default_shopping_state

try:
    from scipy.stats import kendalltau
except ImportError:
    kendalltau = None

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "final_dataset.jsonl"
REPORT_PATH = Path(__file__).resolve().parent / "smoke_test_report.json"
GOLDEN_USER_ID = "AEVHCUQXKFL7XGG645HYFHQ7CGTQ"
BATCH_SEED = 42
BATCH_NORMAL_N = 15
BATCH_EDGE_N = 4


# ══════════════════════════════════════════════
# 데이터 로드
# ══════════════════════════════════════════════

def load_records(path: Path = DATA_PATH) -> list[dict]:
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def group_records(records: list[dict]) -> dict[str, list[dict]]:
    buckets: dict[str, list[dict]] = {}
    for r in records:
        buckets.setdefault(r.get("meta", {}).get("group", "unknown"), []).append(r)
    return buckets


# ══════════════════════════════════════════════
# 2단계: 노드별 단위 점검
#
# 스펙 원문 순서는 1(후보)->2(필터)->3(랭킹)->4(intent)->5(context)->6(response)지만,
# 실제 데이터 의존성은 그 순서가 아니다: 3(랭킹)은 4(intent)가 뽑은 keywords와
# 5(context)가 만든 preference_context가 있어야 의미 있게 돌아간다. 그래서 실행은
# 1->2->4->5->3->6 순으로 하고, 결과는 스펙 번호(1~6) 그대로 키를 맞춰서 리포트한다.
# ══════════════════════════════════════════════

_SEARCH_LIKE_INTENTS = {"buy", "reorder", "refine", "compare_platforms"}


def run_node_checks(record: dict, user_id: str, k: int = 20) -> dict:
    steps: dict[str, dict] = {}
    ctx: dict[str, Any] = {}  # 단계 간 전달용 스크래치패드

    # ── 1. 후보 준비 (gold 포함 슬라이스 + 필드 매핑) ──
    try:
        candidates = prepare_candidates_for_eval(record, k=k)
        gold_asin = record["gold_product"]["asin"]
        gold_in = any(c.get("_asin") == gold_asin for c in candidates)
        steps["1_prepare_candidates"] = {
            "pass": len(candidates) > 0 and gold_in,
            "candidate_count": len(candidates),
            "gold_included": gold_in,
        }
        ctx["candidates"] = candidates
    except Exception as e:
        steps["1_prepare_candidates"] = {"pass": False, "error": _fmt_exc(e)}
        return steps  # 후보가 없으면 이후 단계 전부 무의미 — 여기서 중단

    # ── 2. _filter_results 통과 여부 (0개면 치명적 실패, 즉시 중단) ──
    try:
        filtered = _filter_results(ctx["candidates"], [])
        ok = len(filtered) > 0
        steps["2_filter_results"] = {
            "pass": ok,
            "in_count": len(ctx["candidates"]),
            "out_count": len(filtered),
            "critical": not ok,
        }
        if not ok:
            return steps  # 필드 매핑 실패로 간주, 즉시 중단
        ctx["filtered"] = filtered
    except Exception as e:
        steps["2_filter_results"] = {"pass": False, "error": _fmt_exc(e), "critical": True}
        return steps

    # ── 4. intent_agent_node (먼저 실행 — 3/5/6이 이 결과의 keywords를 씀) ──
    try:
        ensure_onboarded(user_id)  # cold-start 강제 smalltalk 분기 회피 — adapter.py 참고
        seed_purchase_history(user_id, record)  # 구매이력 없으면 _classify_context 자체가 스킵됨 — adapter.py 참고
        intent_input = record_to_intent_input(record, user_id)
        intent_out = intent_agent_node(intent_input)
        intent_value = intent_out.get("intent")
        steps["4_intent_agent"] = {
            "pass": intent_value in _SEARCH_LIKE_INTENTS,
            "intent": intent_value,
            "keywords": intent_out.get("keywords"),
            "degraded_mode": intent_out.get("degraded_mode", False),
        }
        ctx["keywords"] = intent_out.get("keywords") or []
    except Exception as e:
        steps["4_intent_agent"] = {"pass": False, "error": _fmt_exc(e)}
        ctx["keywords"] = []

    # ── 5. context_agent_node (smalltalk -> soft_preference/explicit_exclusion 분류) ──
    try:
        context_input = {
            "stage": "idle",
            "intent": "buy",
            "user_id": user_id,
            "keywords": ctx["keywords"],
            "exclude_keywords": [],
            "messages": record_to_messages(record),
        }
        context_out = context_agent_node(context_input)
        recommendation_context = context_out.get("recommendation_context") or {}
        preference_context = recommendation_context.get("preference_context") or {}
        steps["5_context_agent"] = {
            "pass": True,
            "preference_context_raw": preference_context,
        }
        ctx["preference_context"] = preference_context
    except Exception as e:
        steps["5_context_agent"] = {"pass": False, "error": _fmt_exc(e)}
        ctx["preference_context"] = {}

    # ── 3. _rank_with_metadata (keywords + preference_context 확보된 뒤 실행) ──
    try:
        rank_result = _rank_with_metadata(
            candidates=ctx["filtered"],
            keywords=ctx["keywords"],
            condition=None,
            preference_context=ctx["preference_context"],
        )
        ranked = rank_result.get("ranked_products") or []
        scores = [p.get("final_score") for p in ranked if p.get("final_score") is not None]
        sorted_desc = scores == sorted(scores, reverse=True)
        steps["3_rank_with_metadata"] = {
            "pass": len(ranked) > 0,
            "ranked_count": len(ranked),
            "sorted_desc": sorted_desc,
            "ranking_mode": rank_result.get("ranking_mode"),
            "degraded_mode": rank_result.get("degraded_mode", False),
        }
        ctx["ranked"] = ranked
    except Exception as e:
        steps["3_rank_with_metadata"] = {"pass": False, "error": _fmt_exc(e)}
        ctx["ranked"] = []

    # ── 6. response_agent_node (선택된 상품에 대한 설명 생성) ──
    try:
        selected = ctx["ranked"][0] if ctx["ranked"] else None
        response_input = {
            "intent": "buy",  # 설명 생성 경로를 확실히 타게 하려고 고정(ask QA 경로 아님)
            "keywords": ctx["keywords"],
            "condition": None,
            "recommendation_context": {"preference_context": ctx["preference_context"]},
            "recommended_products": ctx["ranked"],
            "current_product_index": 0,
            "selected_product": selected,
            "messages": record_to_messages(record),
            "stage": "searching",
            "quantity": None,
            "user_id": user_id,
        }
        response_out = response_agent_node(response_input)
        explanation = response_out.get("explanation") or ""
        steps["6_response_agent"] = {
            "pass": bool(explanation.strip()) if selected else False,
            "explanation_len": len(explanation),
            "had_selected_product": selected is not None,
            "degraded_mode": response_out.get("degraded_mode", False),
        }
        ctx["explanation"] = explanation
    except Exception as e:
        steps["6_response_agent"] = {"pass": False, "error": _fmt_exc(e)}

    ctx["steps"] = steps
    return ctx


def _fmt_exc(e: Exception) -> str:
    return "".join(traceback.format_exception_only(type(e), e)).strip()


# ══════════════════════════════════════════════
# 3단계: 그래프 전체 1회 실행
# ══════════════════════════════════════════════

def run_graph_check(record: dict, user_id: str, conversation_id: int) -> dict:
    """runtime.py의 start() 패턴(ainvoke -> aupdate_state -> ainvoke)을 동기 버전으로.
    builder.py가 interrupt_before=["wait_for_input"]로 컴파일되므로 2단계 invoke 필요."""
    from src.graph.builder import build_graph

    try:
        ensure_onboarded(user_id)  # cold-start 강제 smalltalk 분기 회피 — adapter.py 참고
        seed_purchase_history(user_id, record)  # 구매이력 없으면 _classify_context 자체가 스킵됨 — adapter.py 참고
        graph = build_graph()
        config = {"configurable": {"thread_id": str(conversation_id)}}
        initial_state = get_default_shopping_state(user_id=user_id, session_id=str(uuid.uuid4()))
        initial_state["conversation_id"] = conversation_id

        graph.invoke(initial_state, config)  # wait_for_input 직전에서 멈춤
        graph.update_state(config, {"messages": record_to_messages(record)})
        final_state = graph.invoke(None, config)  # 실제 턴 실행

        return {
            "pass": True,
            "stage": final_state.get("stage"),
            "selected_product": final_state.get("selected_product"),
            "recommended_products_count": len(final_state.get("recommended_products") or []),
            "degraded_mode": final_state.get("degraded_mode", False),
        }
    except Exception as e:
        return {"pass": False, "error": _fmt_exc(e)}


# ══════════════════════════════════════════════
# 4단계: 엣지 케이스 스팟 체크
# ══════════════════════════════════════════════

SAFETY_TEST_SENTENCE = "저는 땅콩 알레르기가 있어요"


def run_edge_case_checks(buckets: dict[str, list[dict]]) -> dict:
    results: dict[str, Any] = {}

    for group in ("A_no_history", "B_no_signal", "C_no_smalltalk"):
        pool = buckets.get(group) or []
        if not pool:
            results[group] = {"pass": None, "note": "데이터셋에 해당 그룹 레코드 없음"}
            continue
        record = pool[0]
        user_id = record.get("meta", {}).get("user_id", f"edge_{group}")
        try:
            node_result = run_node_checks(record, user_id)
            results[group] = {
                "pass": all(s.get("pass") for s in node_result.get("steps", node_result).values() if isinstance(s, dict)),
                "record_id": record.get("record_id"),
                "steps": node_result.get("steps", node_result),
            }
        except Exception as e:
            results[group] = {"pass": False, "record_id": record.get("record_id"), "error": _fmt_exc(e)}

    # 안전 트리거 테스트 — 원본 불변, 테스트용 복사본만 수정
    all_records = [r for pool in buckets.values() for r in pool]
    base = next((r for r in all_records if r.get("meta", {}).get("group") == "normal"), all_records[0])
    safety_record = json.loads(json.dumps(base))  # deep copy
    safety_record["smalltalk"] = list(safety_record.get("smalltalk") or []) + [SAFETY_TEST_SENTENCE]
    try:
        from src.agents.context_agent import _sync_safety_from_session
        user_id = f"safety_test_{uuid.uuid4().hex[:8]}"
        messages = record_to_messages(safety_record)
        updated_profile = _sync_safety_from_session(user_id, None, messages)
        allergens = (updated_profile or {}).get("allergens") or []
        results["safety_trigger"] = {
            "pass": len(allergens) > 0,
            "detected_allergens": allergens,
            "base_record_id": base.get("record_id"),
        }
    except Exception as e:
        results["safety_trigger"] = {"pass": False, "error": _fmt_exc(e)}

    # 후보 부족 케이스 (get_eval_candidates가 k=20을 못 채우는 레코드)
    shortfall = []
    for r in all_records:
        try:
            sliced = get_eval_candidates(r, k=20, ensure_gold=True)
            if len(sliced["candidates"]) < 20:
                shortfall.append({"record_id": r.get("record_id"), "count": len(sliced["candidates"])})
        except Exception as e:
            shortfall.append({"record_id": r.get("record_id"), "error": _fmt_exc(e)})
    results["candidate_shortfall"] = {
        "count": len(shortfall),
        "records": shortfall[:20],  # 너무 길어지지 않게 상한
    }

    return results


# ══════════════════════════════════════════════
# 5단계: 소규모 배치
# ══════════════════════════════════════════════

def select_batch(buckets: dict[str, list[dict]]) -> list[dict]:
    rng = random.Random(BATCH_SEED)
    normal_pool = buckets.get("normal") or []
    edge_pool = [r for g in ("A_no_history", "B_no_signal", "C_no_smalltalk") for r in buckets.get(g, [])]

    normal_sample = rng.sample(normal_pool, min(BATCH_NORMAL_N, len(normal_pool)))
    edge_sample = rng.sample(edge_pool, min(BATCH_EDGE_N, len(edge_pool)))
    return normal_sample + edge_sample


def run_batch(records: list[dict]) -> dict:
    per_record = []
    crash_count = 0
    filter_in_total = 0
    filter_out_total = 0

    for record in records:
        user_id = record.get("meta", {}).get("user_id", record.get("record_id", "unknown"))
        started = time.perf_counter()
        entry: dict[str, Any] = {"record_id": record.get("record_id"), "group": record.get("meta", {}).get("group")}
        try:
            node_result = run_node_checks(record, user_id)
            steps = node_result.get("steps", node_result)
            entry["steps"] = steps
            entry["crashed"] = False

            f1 = steps.get("1_prepare_candidates", {})
            f2 = steps.get("2_filter_results", {})
            filter_in_total += f2.get("in_count", 0)
            filter_out_total += f2.get("out_count", 0)

            entry["ranked_products"] = node_result.get("ranked", [])
            entry["expected"] = record_to_expected_output(record)
        except Exception as e:
            crash_count += 1
            entry["crashed"] = True
            entry["error"] = _fmt_exc(e)
        entry["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 1)
        per_record.append(entry)

    elapsed_list = [e["elapsed_ms"] for e in per_record]
    return {
        "n": len(per_record),
        "crash_count": crash_count,
        "crashed_records": [e["record_id"] for e in per_record if e.get("crashed")],
        "filter_pass_rate": (filter_out_total / filter_in_total) if filter_in_total else None,
        "elapsed_ms_avg": round(sum(elapsed_list) / len(elapsed_list), 1) if elapsed_list else None,
        "elapsed_ms_max": max(elapsed_list) if elapsed_list else None,
        "estimated_909_total_minutes": (
            round(sum(elapsed_list) / len(elapsed_list) * 909 / 1000 / 60, 1) if elapsed_list else None
        ),
        "records": per_record,
    }


# ══════════════════════════════════════════════
# 6단계: 지표 스모크 체크
# ══════════════════════════════════════════════

def kendall_tau_smoke(record: dict, ranked_products: list[dict]) -> dict:
    """스모크 테스트 전용 간이 구현 — 본 실험용 정식 정의 아님.

    이 데이터셋은 레코드당 gold가 1개뿐이라 "정답 랭킹 전체"가 없다. 그래서
    여기서는 gold를 1순위로 놓고, 나머지는 원 retriever 순서(candidates 슬라이스
    순서)를 그대로 유지한 "참조 순위"를 만들어 시스템의 예측 순위와 비교한다.
    이건 "시스템이 원 검색 순서를 얼마나 흔들었는지 + gold를 앞으로 끌어왔는지"를
    보는 용도지, 진짜 정답 랭킹과의 상관관계가 아니다. 본 실험에서 더 정교한
    기준이 필요하면(예: 구매이력 embedding_score 기반 다단계 관련도) 이 함수를
    교체해야 한다 — evaluators.py는 안 건드림.
    """
    if kendalltau is None:
        return {"pass": None, "note": "scipy 미설치 — pip install scipy 필요"}

    gold_asin = record["gold_product"]["asin"]
    sliced = get_eval_candidates(record, k=20, ensure_gold=True)
    ref_order_asins = [c["asin"] for c in sliced["candidates"]]
    # gold를 1순위로 끌어온 참조 순위
    ref_order_asins = [gold_asin] + [a for a in ref_order_asins if a != gold_asin]

    pred_order_asins = [p.get("_asin") for p in ranked_products if p.get("_asin")]
    common = [a for a in ref_order_asins if a in pred_order_asins]
    if len(common) < 2:
        return {"pass": False, "note": "비교 가능한 공통 항목 부족(<2)"}

    ref_ranks = [ref_order_asins.index(a) for a in common]
    pred_ranks = [pred_order_asins.index(a) for a in common]
    tau, p_value = kendalltau(ref_ranks, pred_ranks)
    return {"pass": tau is not None, "tau": tau, "p_value": p_value, "n_compared": len(common)}


def run_metric_smoke(batch_result: dict) -> dict:
    mrr_scores, ndcg_scores, tau_scores = [], [], []
    sample_mrr = sample_ndcg = sample_tau = None

    records_by_id = {}  # record_id -> full record, for kendall (needs gold_product/candidates)

    for entry in batch_result["records"]:
        if entry.get("crashed") or not entry.get("ranked_products"):
            continue
        outputs = {"ranked_products": entry["ranked_products"]}
        expected = entry["expected"]

        mrr = mrr_evaluator(outputs, expected)
        ndcg = ndcg_at_3_evaluator(outputs, expected)
        if mrr.get("score") is not None:
            mrr_scores.append(mrr["score"])
            sample_mrr = sample_mrr or mrr
        if ndcg.get("score") is not None:
            ndcg_scores.append(ndcg["score"])
            sample_ndcg = sample_ndcg or ndcg

    return {
        "mrr": {
            "n": len(mrr_scores),
            "nonzero_count": sum(1 for s in mrr_scores if s and s > 0),
            "avg": round(sum(mrr_scores) / len(mrr_scores), 3) if mrr_scores else None,
            "sample": sample_mrr,
        },
        "ndcg_at_3": {
            "n": len(ndcg_scores),
            "nonzero_count": sum(1 for s in ndcg_scores if s and s > 0),
            "avg": round(sum(ndcg_scores) / len(ndcg_scores), 3) if ndcg_scores else None,
            "sample": sample_ndcg,
        },
    }


def run_kendall_smoke(records_map: dict[str, dict], batch_result: dict) -> dict:
    taus = []
    sample = None
    for entry in batch_result["records"]:
        if entry.get("crashed") or not entry.get("ranked_products"):
            continue
        record = records_map.get(entry["record_id"])
        if not record:
            continue
        result = kendall_tau_smoke(record, entry["ranked_products"])
        if result.get("tau") is not None:
            taus.append(result["tau"])
            sample = sample or result
    return {
        "n": len(taus),
        "avg_tau": round(sum(taus) / len(taus), 3) if taus else None,
        "sample": sample,
    }


# ══════════════════════════════════════════════
# 메인
# ══════════════════════════════════════════════

def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    print(f"[smoke_test] 데이터 로드: {DATA_PATH}")
    records = load_records()
    buckets = group_records(records)
    print(f"[smoke_test] 총 {len(records)}건, 그룹: { {k: len(v) for k, v in buckets.items()} }")

    report: dict[str, Any] = {"dataset_path": str(DATA_PATH), "total_records": len(records)}

    # ── golden case ──
    golden = next((r for r in records if r.get("meta", {}).get("user_id") == GOLDEN_USER_ID), None)
    if golden is None:
        print(f"[smoke_test] 경고: golden user_id={GOLDEN_USER_ID} 레코드를 못 찾음 — records[0]으로 대체")
        golden = records[0]
    print(f"[smoke_test] golden record_id={golden.get('record_id')}")

    # ── 2단계 ──
    print("\n[2단계] 노드별 단위 점검 (golden case)")
    golden_node = run_node_checks(golden, GOLDEN_USER_ID)
    golden_steps = golden_node.get("steps", golden_node)
    for key in sorted(golden_steps.keys()):
        s = golden_steps[key]
        status = "PASS" if s.get("pass") else "FAIL"
        print(f"  [{status}] {key}: {s}")
    report["step2_node_checks"] = golden_steps

    # ── 3단계 ──
    print("\n[3단계] 그래프 전체 1회 실행 (golden case)")
    graph_result = run_graph_check(golden, GOLDEN_USER_ID, conversation_id=999001)
    print(f"  [{'PASS' if graph_result.get('pass') else 'FAIL'}] {graph_result}")
    report["step3_graph_check"] = graph_result

    # ── 4단계 ──
    print("\n[4단계] 엣지 케이스 스팟 체크")
    edge_result = run_edge_case_checks(buckets)
    for k, v in edge_result.items():
        if k == "candidate_shortfall":
            print(f"  candidate_shortfall: {v['count']}건")
            continue
        print(f"  [{'PASS' if v.get('pass') else 'FAIL'}] {k}")
    report["step4_edge_cases"] = edge_result

    # ── 5단계 ──
    print(f"\n[5단계] 소규모 배치 (normal {BATCH_NORMAL_N} + edge {BATCH_EDGE_N}, seed={BATCH_SEED})")
    batch_records = select_batch(buckets)
    batch_result = run_batch(batch_records)
    print(f"  n={batch_result['n']}  crash={batch_result['crash_count']}  "
          f"filter_pass_rate={batch_result['filter_pass_rate']}  "
          f"avg_ms={batch_result['elapsed_ms_avg']}  909건 예상={batch_result['estimated_909_total_minutes']}분")
    report["step5_batch"] = batch_result

    # ── 6단계 ──
    print("\n[6단계] 지표 스모크 체크")
    metric_result = run_metric_smoke(batch_result)
    records_map = {r.get("record_id"): r for r in batch_records}
    kendall_result = run_kendall_smoke(records_map, batch_result)
    print(f"  MRR: n={metric_result['mrr']['n']} nonzero={metric_result['mrr']['nonzero_count']} avg={metric_result['mrr']['avg']}")
    print(f"  NDCG@3: n={metric_result['ndcg_at_3']['n']} nonzero={metric_result['ndcg_at_3']['nonzero_count']} avg={metric_result['ndcg_at_3']['avg']}")
    print(f"  Kendall's tau: n={kendall_result['n']} avg={kendall_result['avg_tau']}")
    report["step6_metrics"] = {"mrr_ndcg": metric_result, "kendall_tau": kendall_result}

    # ── 이슈 요약 ──
    issues_blocking, issues_ignorable = [], []
    if not golden_steps.get("2_filter_results", {}).get("pass", True):
        issues_blocking.append("_filter_results가 golden case에서 0개 반환 — 필드 매핑 확인 필요")
    if batch_result["crash_count"] > 0:
        issues_blocking.append(f"배치 중 {batch_result['crash_count']}건 크래시: {batch_result['crashed_records']}")
    if metric_result["mrr"]["nonzero_count"] == 0 and metric_result["mrr"]["n"] > 0:
        issues_blocking.append("MRR이 전부 0 — 어댑터의 gold 매핑(product_name 일치) 재확인 필요")
    if edge_result.get("candidate_shortfall", {}).get("count", 0) > 0:
        issues_ignorable.append(f"candidate pool이 k=20 미만인 레코드 {edge_result['candidate_shortfall']['count']}건 (목록은 리포트 참고)")
    report["issues"] = {"blocking": issues_blocking, "ignorable_for_now": issues_ignorable}

    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\n[smoke_test] 리포트 저장: {REPORT_PATH}")


if __name__ == "__main__":
    main()
