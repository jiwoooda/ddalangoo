"""전체 그래프(intent_agent → context_agent → product_agent → response_agent)
인터랙티브 REPL — 스몰톡으로 이미 프로필이 채워진 유저가 실제 구매 요청을
했을 때 개인화(안전 배제/제외 키워드/조건·정렬/소프트 선호)가 정말
반영되는지 눈으로 확인하기 위한 도구다.

smalltalk_repl.py는 온보딩(스몰톡)만 다루고, intent_repl.py는 intent_agent
분류 결과만 보여줄 뿐 실제 검색·추천은 안 돈다 — 이 스크립트는 그 사이,
"온보딩 끝난 프로필로 첫 구매 요청을 하면 실제로 무슨 일이 일어나는가"를
그래프 전체로 돌려서 보여준다.

실행:
    python tests/shopping_repl.py
    python tests/shopping_repl.py --user my_test_user --seed-profile profile.json

명령:
    /profile   현재 mock 프로필 출력
    /context   최근 턴의 recommendation_context.preference_context 출력
                (safety_constraints/exclude_additions/soft_preferences 등)
    /state     최근 턴의 핵심 state(keywords/exclude_keywords/condition 등) 출력
    /quit      종료
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pathlib import Path

from dotenv import load_dotenv

# COUPANG_ACCESS_KEY/SECRET_KEY는 루트 .env가 아니라 backend/.env에 있다 —
# bare load_dotenv()는 cwd(backend/vendor/ddalangoo-langgraph)에서 위로
# 탐색하다 처음 찾은 .env 하나만 로드해서 이 값을 놓칠 수 있으므로,
# evals/smalltalk_population/runner.py의 _load_api_env()와 같은 패턴으로
# 후보 경로를 전부 훑는다(override=False라 먼저 로드된 값이 우선).
_REPO = Path(__file__).resolve().parents[1]
_WORKSPACE = _REPO.parents[2]
for _candidate in (_WORKSPACE / ".env", _WORKSPACE / "backend" / ".env", _REPO / ".env"):
    if _candidate.exists():
        load_dotenv(_candidate, override=False)

# 사용자가 실측으로 확인해달라고 준 예시 프로필 — food_dislikes에 "없음"
# 센티널과 실제 항목("유제품")이 섞여 있는 것도 그대로 재현(실제 REPL
# 세션에서 나온 값을 그대로 씀). 유당불내증/유제품 알레르기가 있는데
# "우유 사줘" 같은 요청을 하면 안전 배제(safety_constraints)가 실제로
# exclude_keywords에 반영되는지 확인하기 좋은 케이스다.
_DEFAULT_SEED_PROFILE = {
    "food_dislikes": ["없음", "유제품"],
    "delivery_priority": "빠른배송",
    "household_size": 4,
    "favorite_foods": ["된장찌개"],
    "health_notes": ["유당불내증"],
    "inconveniences": ["귀찮음"],
    "preferred_name": "영희",
    "allergens": ["유제품"],
    "diet_restrictions": ["유당불내증"],
    "onboarded_at": "2026-08-13T14:06:48.063985+00:00",
    "computed_at": "2026-08-13T14:06:48.063985+00:00",
}


def _ensure_graph_compatibility() -> None:
    import langgraph.errors
    from langgraph.runtime import Runtime

    if not hasattr(langgraph.errors, "NodeError"):
        class NodeError(Exception):
            pass

        langgraph.errors.NodeError = NodeError
    if not hasattr(Runtime, "execution_info"):
        Runtime.execution_info = None


def _extract_reply(graph, config) -> str | None:
    vals = graph.get_state(config).values
    for msg in reversed(vals.get("messages", [])):
        role = getattr(msg, "type", None) or (msg.get("role") if isinstance(msg, dict) else None)
        if role in ("ai", "assistant"):
            return getattr(msg, "content", None) or (msg.get("content") if isinstance(msg, dict) else None)
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="전체 그래프 구매 흐름 REPL (개인화 반영 확인용)")
    parser.add_argument("--model", default="gpt-4o-mini")
    parser.add_argument("--user", default="shopping_repl_test_user", help="mock 유저 ID")
    parser.add_argument(
        "--seed-profile", default=None,
        help="이 경로의 JSON을 프로필로 시드(생략하면 스크립트에 박힌 기본 예시 프로필 사용)",
    )
    parser.add_argument("--no-seed", action="store_true", help="프로필을 시드하지 않고 빈 상태로 시작")
    args = parser.parse_args()

    os.environ["LLM_BACKEND"] = "api"
    os.environ["CONTEXT_MODEL"] = args.model
    os.environ["DB_MODE"] = "mock"
    os.environ["SEARCH_MODE"] = "mcp"  # mock 대신 실제 MCP(현재는 쿠팡 Open API 직접 연동) 사용

    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY가 설정되지 않았습니다. .env를 확인하세요.")
    if not (os.getenv("COUPANG_ACCESS_KEY") and os.getenv("COUPANG_SECRET_KEY")):
        raise SystemExit(
            "COUPANG_ACCESS_KEY / COUPANG_SECRET_KEY가 설정되지 않았습니다.\n"
            "meta-mcp/src/adapters/coupang.ts가 이 두 값을 요구합니다(쿠팡 파트너스 Open API).\n"
            "루트 .env(또는 meta-mcp/.env)에 추가한 뒤 다시 실행하세요 — "
            "meta_mcp_client.py가 현재 프로세스 환경변수를 그대로 Node 서브프로세스에 넘기므로 "
            "루트 .env에 넣는 것만으로 충분합니다."
        )

    _ensure_graph_compatibility()
    from src.graph.builder import build_graph
    from src.state.schema import get_default_shopping_state
    from src.tools import db_client
    from src.agents import product_agent as _product_agent_mod

    # 지금은 쿠팡 Open API 직접 연동만 안정적으로 붙어 있어서(네이버/컬리는
    # 별도 설정 필요), 이 REPL에서만 검색 대상 플랫폼을 쿠팡으로 좁힌다 —
    # product_agent 소스 자체는 안 건드리고, 이 프로세스 안에서만
    # ALL_PLATFORMS를 재바인딩한다(운영 코드에 영향 없음).
    _product_agent_mod.ALL_PLATFORMS = ["coupang"]

    user_id = args.user
    if not args.no_seed:
        seed = _DEFAULT_SEED_PROFILE
        if args.seed_profile:
            with open(args.seed_profile, encoding="utf-8") as f:
                seed = json.load(f)
        db_client.save_profile(user_id, seed)

    session_id = f"shopping-repl-{user_id}"
    config = {"configurable": {"thread_id": session_id}}
    graph = build_graph()
    graph.invoke(get_default_shopping_state(user_id, session_id), config)

    print("=" * 64)
    print("  Shopping Flow REPL — 전체 그래프(intent→context→product→response)")
    print(f"  model={args.model} | user={user_id} | SEARCH_MODE={os.environ['SEARCH_MODE']}")
    print(f"  프로필 시드: {'없음(--no-seed)' if args.no_seed else (args.seed_profile or '기본 예시(영희, 유제품 알레르기)')}")
    print("  /profile  /context  /state  /quit")
    print("=" * 64)
    profile = db_client.get_profile(user_id) or {}
    print("\n[시드된 프로필]")
    print(json.dumps(profile, ensure_ascii=False, indent=2))

    while True:
        try:
            user_input = input("\n사용자 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n종료합니다.")
            break

        if not user_input:
            continue
        if user_input.startswith("/"):
            cmd = user_input.lower()
            if cmd in ("/quit", "/exit", "/q"):
                print("종료합니다.")
                break
            if cmd == "/profile":
                print(json.dumps(db_client.get_profile(user_id) or {}, ensure_ascii=False, indent=2))
                continue
            if cmd == "/context":
                vals = graph.get_state(config).values
                ctx = (vals.get("recommendation_context") or {}).get("preference_context") or {}
                print(json.dumps(ctx, ensure_ascii=False, indent=2, default=str))
                continue
            if cmd == "/state":
                vals = graph.get_state(config).values
                keys = ("stage", "intent", "keywords", "exclude_keywords", "condition",
                        "selected_product", "last_agent", "pending_action")
                for k in keys:
                    print(f"  {k}: {vals.get(k)!r}")
                continue
            print("알 수 없는 명령: /profile /context /state /quit")
            continue

        graph.update_state(config, {"messages": [{"role": "user", "content": user_input}]})
        try:
            graph.invoke(None, config)
        except Exception as exc:
            print(f"\n[호출 실패] {type(exc).__name__}: {exc}")
            continue

        reply = _extract_reply(graph, config)
        vals = graph.get_state(config).values
        print(f"\n딸랑구 > {reply}")
        print(f"  └─ stage={vals.get('stage')}  intent={vals.get('intent')}  "
              f"exclude_keywords={vals.get('exclude_keywords')}  condition={vals.get('condition')}")


if __name__ == "__main__":
    main()
