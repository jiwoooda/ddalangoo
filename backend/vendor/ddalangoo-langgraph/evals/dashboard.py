"""
로컬 프롬프트/성능 비교 대시보드 (Streamlit). LangSmith 없이 동작한다.

- "지표 비교" 탭: evals/local_runner.py로 만든 evals/runs/*.json 두 개를
  골라 지표를 비교하고, 그 시점의 프롬프트 diff를 같이 보여준다.
- "프롬프트 히스토리" 탭: eval run과 무관하게, 프롬프트 파일을 건드린
  모든 커밋을 git log로 나열해서 고르면 그 버전 전체 내용을 보여주고,
  두 버전을 골라 diff도 볼 수 있다.

실행: streamlit run evals/dashboard.py  (backend/vendor/ddalangoo-langgraph 에서)
"""
import difflib
import json
import subprocess
import sys
from pathlib import Path

import streamlit as st

BASE_DIR = Path(__file__).resolve().parent.parent  # backend/vendor/ddalangoo-langgraph
RUNS_DIR = BASE_DIR / "evals" / "runs"
WORKTREE_LABEL = "작업트리 (커밋 안 됨)"

AGENT_PROMPT_FILES = {
    "context": ["src/prompts/context_prompt.py"],
    "product": ["src/prompts/scoring_prompt.py", "src/prompts/product_prompt.py"],
    "response": ["src/prompts/response_prompt.py"],
    "intent": ["src/prompts/intent_prompt.py"],
    "recipe": ["src/prompts/recipe_prompt.py"],
    "smalltalk": ["src/prompts/smalltalk_prompt.py"],
    "reorder": [],  # reorder_agent는 현재 전용 프롬프트 파일이 없음(코드/라우팅 로직 위주)
}

# evaluators.py의 evaluator key(영문, 코드용) → 이름만 읽어도 뜻이 바로
# 오는 한글 라벨. evaluators.py에 새 evaluator를 추가했는데 여기 없으면
# _metric_label()이 원래 key를 그대로 보여준다 (라벨 갱신을 잊어도 안 깨짐).
METRIC_LABELS: dict[str, str] = {
    "intent_accuracy": "의도 정확도",
    "keyword_overlap": "키워드 일치도",
    "needs_clarification_accuracy": "재질문 판단 정확도",
    "schema_compliance": "출력형식 정확도(엄격)",
    "schema_loose": "출력형식 정확도(느슨)",
    "latency_ms": "응답속도(ms)",
    "ttft_ms": "첫응답속도(ms)",
    "input_tokens": "입력 토큰수",
    "output_tokens": "출력 토큰수",
    "cost_usd": "비용(달러)",
    "ranking_accuracy": "랭킹 정확도",
    "tool_call_success_rate": "도구호출 성공률",
    "mrr": "정답랭킹 역수",
    "ndcg_at_3": "상위3 랭킹품질",
    "condition_adherence": "정렬조건 준수율",
    "hallucination_free_rate": "환각없음 비율",
    "reflection_pass_rate": "자기검토 통과율",
    "haiku_fallback_rate": "경량모델 대체율",
    "elderly_friendliness": "어르신친화도(규칙)",
    "g_eval_elderly": "어르신친화도(LLM채점)",
    "preference_adherence": "선호 반영률",
    "preferred_brands": "선호브랜드 정확도",
    "preferred_platform": "선호플랫폼 정확도",
    "price_range": "가격대 정확도",
    "repurchase_patterns": "재구매패턴 정확도",
    "keyword_history_count": "구매이력 개수충족",
    "keyword_history_products": "구매이력 상품일치도",
    "coverage": "키워드 반영률",
    "faithfulness": "충실도(사실기반)",
    "cold_start_pass": "신규유저 처리율",
    "conciseness": "요약 간결성",
}


def _metric_label(key: str) -> str:
    return METRIC_LABELS.get(key, key)


@st.cache_data(show_spinner=False)
def _load_runs() -> list[dict]:
    runs = []
    for path in sorted(RUNS_DIR.glob("*.json"), reverse=True):
        try:
            with open(path, encoding="utf-8") as f:
                record = json.load(f)
            record["_path"] = str(path)
            record["_filename"] = path.name
            runs.append(record)
        except Exception:
            continue
    return runs


def _git_show(commit: str, rel_path: str) -> str:
    try:
        proc = subprocess.run(
            ["git", "show", f"{commit}:{rel_path}"],
            cwd=BASE_DIR, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10,
        )
        if proc.returncode != 0:
            return f"(git show 실패: {proc.stderr.strip()[:200]})"
        return proc.stdout
    except Exception as e:
        return f"(git show 오류: {e})"


def _read_worktree(rel_path: str) -> str:
    try:
        return (BASE_DIR / rel_path).read_text(encoding="utf-8")
    except Exception as e:
        return f"(파일 읽기 오류: {e})"


@st.cache_data(show_spinner=False)
def _get_prompt_history(rel_path: str) -> list[dict]:
    """이 프롬프트 파일을 건드린 커밋을 최신순으로 반환. 맨 앞엔 작업트리(커밋 전) 버전을 얹는다."""
    entries = [{"full": None, "short": None, "date": "지금", "subject": WORKTREE_LABEL}]
    try:
        proc = subprocess.run(
            ["git", "log", "--format=%H|%h|%ad|%s", "--date=short", "--", rel_path],
            cwd=BASE_DIR, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10,
        )
        if proc.returncode == 0:
            for line in proc.stdout.strip().splitlines():
                parts = line.split("|", 3)
                if len(parts) == 4:
                    full, short, date, subject = parts
                    entries.append({"full": full, "short": short, "date": date, "subject": subject})
    except Exception:
        pass
    return entries


def _content_at(entry: dict, rel_path: str) -> str:
    if entry["full"] is None:
        return _read_worktree(rel_path)
    return _git_show(entry["full"], rel_path)


def _validate_python(content: str, rel_path: str) -> str | None:
    """편집한 내용이 유효한 파이썬인지 확인. 문제 없으면 None, 있으면 에러 메시지."""
    try:
        compile(content, rel_path, "exec")
        return None
    except SyntaxError as e:
        return f"{e.msg} ({rel_path}:{e.lineno})"


def _git_diff_worktree(rel_path: str) -> str:
    try:
        proc = subprocess.run(
            ["git", "diff", "--", rel_path],
            cwd=BASE_DIR, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10,
        )
        return proc.stdout
    except Exception as e:
        return f"(git diff 오류: {e})"


def _git_commit_file(rel_path: str, message: str) -> tuple[bool, str]:
    """이 파일 하나만 add + commit. 로컬 커밋만 만들고 push는 하지 않는다."""
    if not message.strip():
        return False, "커밋 메시지를 입력하세요."
    try:
        add_proc = subprocess.run(
            ["git", "add", "--", rel_path],
            cwd=BASE_DIR, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10,
        )
        if add_proc.returncode != 0:
            return False, f"git add 실패: {add_proc.stderr.strip()}"
        commit_proc = subprocess.run(
            ["git", "commit", "-m", message, "--", rel_path],
            cwd=BASE_DIR, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10,
        )
        if commit_proc.returncode != 0:
            return False, f"git commit 실패: {(commit_proc.stderr or commit_proc.stdout).strip()}"
        return True, commit_proc.stdout.strip()
    except Exception as e:
        return False, f"git 오류: {e}"


def _run_label(run: dict) -> str:
    return f"{run['timestamp'][:19]}  ·  {run['git_commit']}  ·  {run['case_count']}건"


def _render_metric_comparison(run_a: dict, run_b: dict) -> None:
    names = sorted(set(run_a["aggregate"]) | set(run_b["aggregate"]))
    rows = []
    for name in names:
        a = (run_a["aggregate"].get(name) or {}).get("mean")
        b = (run_b["aggregate"].get(name) or {}).get("mean")
        delta = (b - a) if isinstance(a, (int, float)) and isinstance(b, (int, float)) else None
        rows.append({"지표": _metric_label(name), "B (현재)": b, "A (이전)": a, "변화": delta})
    st.dataframe(rows, width='stretch', hide_index=True)


def _render_prompt_diff(agent: str, commit_a: str, commit_b: str) -> None:
    files = AGENT_PROMPT_FILES.get(agent, [])
    if not files:
        st.info(f"'{agent}' 에이전트에 매핑된 프롬프트 파일이 없습니다.")
        return
    for rel_path in files:
        st.markdown(f"**`{rel_path}`**")
        if commit_a == commit_b:
            st.caption("두 run이 같은 커밋이라 diff가 없습니다.")
            continue
        text_a = _git_show(commit_a, rel_path)
        text_b = _git_show(commit_b, rel_path)
        diff_lines = list(difflib.unified_diff(
            text_a.splitlines(), text_b.splitlines(),
            fromfile=f"{commit_a}", tofile=f"{commit_b}", lineterm="",
        ))
        if not diff_lines:
            st.caption("이 커밋 사이엔 이 파일 변경 없음.")
            continue
        st.code("\n".join(diff_lines), language="diff")


def _render_case_table(run: dict, label: str) -> None:
    st.markdown(f"**{label} — 케이스별 상세**")
    rows = []
    for case in run["cases"]:
        row = {"case_id": case["case_id"]}
        for name, score in case["scores"].items():
            row[_metric_label(name)] = score.get("score")
        rows.append(row)
    st.dataframe(rows, width='stretch', hide_index=True)


def _tab_metric_comparison(runs: list[dict]) -> None:
    if not runs:
        st.warning(
            "저장된 run이 없습니다. 먼저 `python -m evals.local_runner --agent context`를 "
            "backend/vendor/ddalangoo-langgraph 에서 실행하세요."
        )
        return

    agents = sorted({r["agent"] for r in runs})
    agent = st.selectbox("에이전트", agents, key="metric_agent")
    agent_runs = [r for r in runs if r["agent"] == agent]

    if len(agent_runs) < 2:
        st.info(f"'{agent}' run이 {len(agent_runs)}개뿐입니다. 비교하려면 2개 이상 필요합니다.")
        if agent_runs:
            st.subheader(_run_label(agent_runs[0]))
            st.json(agent_runs[0]["aggregate"])
        return

    labels = [_run_label(r) for r in agent_runs]
    col_b, col_a = st.columns(2)
    idx_b = col_b.selectbox("B (현재/비교대상)", range(len(agent_runs)), format_func=lambda i: labels[i], index=0)
    idx_a = col_a.selectbox("A (이전/기준)", range(len(agent_runs)), format_func=lambda i: labels[i], index=min(1, len(agent_runs) - 1))

    run_a, run_b = agent_runs[idx_a], agent_runs[idx_b]

    st.subheader("지표 비교")
    _render_metric_comparison(run_a, run_b)

    st.subheader("프롬프트 diff (A → B)")
    _render_prompt_diff(agent, run_a["git_commit"], run_b["git_commit"])

    with st.expander("케이스별 상세 점수 보기"):
        c2, c1 = st.columns(2)
        with c2:
            _render_case_table(run_b, "B (현재)")
        with c1:
            _render_case_table(run_a, "A (이전)")


def _tab_prompt_history() -> None:
    st.caption("eval run과 무관하게, 이 파일을 건드린 모든 커밋 + 아직 커밋 안 한 작업트리 버전까지 전부 브라우징합니다.")
    agent = st.selectbox("에이전트", sorted(AGENT_PROMPT_FILES), key="history_agent")

    for rel_path in AGENT_PROMPT_FILES[agent]:
        st.markdown(f"### `{rel_path}`")
        history = _get_prompt_history(rel_path)
        if len(history) <= 1:
            st.caption("이 파일을 건드린 커밋을 못 찾았습니다 (아직 커밋된 적 없음).")
            continue

        labels = [f"{h['date']}  ·  {h['short'] or '-':<8}  ·  {h['subject'][:70]}" for h in history]

        view_idx = st.selectbox(
            "버전 선택 — 전체 내용 보기", range(len(history)),
            format_func=lambda i: labels[i], key=f"view_{rel_path}",
        )
        st.code(_content_at(history[view_idx], rel_path), language="python", line_numbers=True)

        with st.expander("두 버전 비교 (diff)"):
            col_x, col_y = st.columns(2)
            idx_x = col_x.selectbox("버전 X (이전)", range(len(history)), format_func=lambda i: labels[i], key=f"diffx_{rel_path}", index=min(1, len(history) - 1))
            idx_y = col_y.selectbox("버전 Y (이후)", range(len(history)), format_func=lambda i: labels[i], key=f"diffy_{rel_path}", index=0)

            if history[idx_x] is history[idx_y] or (history[idx_x]["full"] == history[idx_y]["full"]):
                st.caption("같은 버전입니다.")
            else:
                text_x = _content_at(history[idx_x], rel_path)
                text_y = _content_at(history[idx_y], rel_path)
                diff_lines = list(difflib.unified_diff(
                    text_x.splitlines(), text_y.splitlines(),
                    fromfile=labels[idx_x], tofile=labels[idx_y], lineterm="",
                ))
                st.code("\n".join(diff_lines) or "변경 없음", language="diff")

        with st.expander("✏️ 편집 & 커밋 (작업트리 버전만)"):
            st.caption(
                "지금 디스크에 있는 내용을 직접 고쳐서 저장하고, 그 자리에서 커밋까지 "
                "할 수 있습니다. 저장 전 파이썬 문법을 자동으로 검사하며, 커밋은 이 "
                "파일 하나만 로컬에 만듭니다 (push는 하지 않습니다)."
            )
            disk_content = _read_worktree(rel_path)
            edited = st.text_area(
                "내용 편집", value=disk_content, height=420, key=f"edit_{rel_path}",
            )

            if edited != disk_content:
                error = _validate_python(edited, rel_path)
                if error:
                    st.error(f"파이썬 문법 오류라 저장할 수 없습니다: {error}")
                else:
                    preview = list(difflib.unified_diff(
                        disk_content.splitlines(), edited.splitlines(),
                        fromfile="디스크", tofile="편집본", lineterm="",
                    ))
                    st.code("\n".join(preview), language="diff")
                    if st.button("저장 (디스크에 쓰기)", key=f"save_{rel_path}"):
                        _write_worktree(rel_path, edited)
                        st.success("저장했습니다.")
                        st.rerun()
            else:
                st.caption("편집한 내용이 없습니다.")

            worktree_diff = _git_diff_worktree(rel_path)
            if worktree_diff.strip():
                st.markdown("**커밋 안 된 변경사항 (git diff)**")
                st.code(worktree_diff, language="diff")
                commit_msg = st.text_input(
                    "커밋 메시지", value=f"prompt: {rel_path} 수정",
                    key=f"msg_{rel_path}",
                )
                if st.button("커밋하기 (로컬 전용, push 안 함)", key=f"commit_{rel_path}"):
                    ok, detail = _git_commit_file(rel_path, commit_msg)
                    if ok:
                        st.success(f"커밋했습니다.\n\n{detail}")
                        _get_prompt_history.clear()
                        st.rerun()
                    else:
                        st.error(detail)
            else:
                st.caption("커밋 안 된 변경사항이 없습니다 (디스크 내용이 마지막 커밋과 동일).")


def _write_worktree(rel_path: str, content: str) -> None:
    (BASE_DIR / rel_path).write_text(content, encoding="utf-8")


def _tab_operational_metrics() -> None:
    st.caption(
        "agent_logger가 남긴 .jsonl 로그를 집계합니다. LOG_AGENT_TRACE=true로 "
        "돌린 세션이 있어야 데이터가 쌓입니다."
    )
    sys.path.insert(0, str(BASE_DIR))
    from scripts.check_fallback_rate import compute_fallback_stats, _DEFAULT_LOG_DIRS
    from scripts.check_turn_latency import compute_turn_latencies

    st.subheader("Stage4 스코어링 폴백률")
    fb_stats = compute_fallback_stats(_DEFAULT_LOG_DIRS)
    if fb_stats["total"] == 0:
        st.info("scoring_agent 이벤트가 아직 없습니다.")
    else:
        col1, col2, col3 = st.columns(3)
        col1.metric("총 스코어링 호출", fb_stats["total"])
        col2.metric("폴백 발생", fb_stats["fallback"])
        col3.metric("폴백률", f"{fb_stats['fallback_rate']*100:.1f}%")
        if fb_stats["fallback_error_breakdown"]:
            st.markdown("**폴백 원인별 건수**")
            rows = [{"원인": err, "건수": n} for err, n in fb_stats["fallback_error_breakdown"].items()]
            st.dataframe(rows, width='stretch', hide_index=True)

    st.subheader("턴당 총 소요시간 (turn_start → respond)")
    lat_stats = compute_turn_latencies(_DEFAULT_LOG_DIRS)
    if lat_stats["n"] == 0:
        st.info("측정된 턴이 아직 없습니다 (ts 필드가 찍힌 이후 로그부터 집계됩니다).")
    else:
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("평균", f"{lat_stats['mean_ms']:.0f}ms")
        col2.metric("p50", f"{lat_stats['p50_ms']:.0f}ms")
        col3.metric("p90", f"{lat_stats['p90_ms']:.0f}ms")
        col4.metric("최대", f"{lat_stats['max_ms']:.0f}ms")
        st.caption(f"측정된 턴 수: {lat_stats['n']}")


def main() -> None:
    st.set_page_config(page_title="딸랑구 로컬 Eval 대시보드", layout="wide")
    st.title("딸랑구 로컬 프롬프트/성능 비교 대시보드")
    st.caption("LangSmith 없이 evals/runs/*.json + git log 기반")

    runs = _load_runs()
    tab_metrics, tab_history, tab_ops = st.tabs([
        "지표 비교 (eval run)", "프롬프트 히스토리 (버전 전체보기)", "운영 지표 (폴백률)",
    ])
    with tab_metrics:
        _tab_metric_comparison(runs)
    with tab_history:
        _tab_prompt_history()
    with tab_ops:
        _tab_operational_metrics()


if __name__ == "__main__":
    main()
