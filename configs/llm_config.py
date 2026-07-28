"""
LLM 팩토리.

환경변수로 백엔드와 모델을 선택한다.

  LLM_BACKEND=api     → OpenAI / Anthropic API (기본값)
  LLM_BACKEND=ollama  → 로컬 Ollama 서버

모델 오버라이드:
  INTENT_MODEL=llama3.2
  PRODUCT_MODEL=llama3.1:8b
  RESPONSE_MODEL=llama3.1:8b
  CONTEXT_MODEL=llama3.2:1b
  OLLAMA_BASE_URL=http://localhost:11434
"""
import os
import threading
from langchain_core.language_models import BaseChatModel

# ── eval 실험용 thread-local 콜백 저장소 ────────────────────────────────
_eval_local = threading.local()


def set_eval_callbacks(callbacks: list) -> None:
    """실험 실행 전 등록. 이후 get_llm()이 생성하는 모델에 자동 주입."""
    _eval_local.callbacks = list(callbacks)


def clear_eval_callbacks() -> None:
    _eval_local.callbacks = []

_DEFAULT_MODELS: dict[str, dict[str, str]] = {
    "api": {
        "intent":   "claude-haiku-4-5-20251001",
        "product":  "claude-sonnet-4-6",
        "response": "claude-sonnet-4-6",
        "context":  "claude-haiku-4-5-20251001",
        "recipe":   "claude-haiku-4-5-20251001",
    },
    "ollama": {
        # A후보 기본값. B후보는 --model 옵션으로 오버라이드.
        # intent   A=qwen3:32b         B=qwen2.5:72b
        # product  A=xlam-2:32b-fc-r   B=qwen3:32b    (xLAM: FC 특화, BFCL rank 18)
        # context  A=qwen2.5:14b       B=qwen3:8b
        # response A=qwen2.5:7b        B=exaone3.5:7.8b
        "intent":   "qwen3:32b",
        "product":  "xlam-2:32b-fc-r",
        "response": "qwen2.5:7b",
        "context":  "qwen2.5:14b",
        "recipe":   "qwen2.5:7b",
    },
    "vllm": {
        # vLLM OpenAI-compatible 서버 (A100 × 2, AWQ int4 ~18GB)
        # Qwen2.5-32B-Instruct-AWQ: 추론·맥락 이해 강점, Qwen2ForCausalLM (vLLM 0.6.6 지원)
        "intent":   "/home/tta/models/qwen2.5-32b-instruct-awq",
        "product":  "/home/tta/models/qwen2.5-32b-instruct-awq",
        "response": "/home/tta/models/qwen2.5-32b-instruct-awq",
        "context":  "/home/tta/models/qwen2.5-32b-instruct-awq",
        "recipe":   "/home/tta/models/qwen2.5-32b-instruct-awq",
    },
}

_ENV_KEYS: dict[str, str] = {
    "intent":   "INTENT_MODEL",
    "product":  "PRODUCT_MODEL",
    "response": "RESPONSE_MODEL",
    "context":  "CONTEXT_MODEL",
    "recipe":   "RECIPE_MODEL",
}


def get_llm(agent: str, *, retry_owner: str = "sdk", **kwargs) -> BaseChatModel:
    """
    agent: "intent" | "product" | "response" | "context"
    retry_owner: "sdk"(기본값) | "application". anthropic/openai SDK는 연결 오류·429·5xx를
        기본 자동 재시도한다. LangGraph RetryPolicy/retry_call()이 재시도를 전담하는
        그래프 노드 호출부만 "application"으로 넘겨 SDK 자체 재시도를 꺼서, LangGraph
        재시도와 중첩(최대 9회 호출)되지 않게 한다. evals/scripts 등 그래프 밖 호출부는
        기본값을 그대로 쓴다.
    kwargs: temperature, max_tokens 등 — 백엔드별로 자동 변환
    """
    backend = os.getenv("LLM_BACKEND", "api")
    model = os.getenv(_ENV_KEYS[agent], _DEFAULT_MODELS[backend][agent])

    # eval 실험 콜백 주입 (set_eval_callbacks 로 등록된 경우)
    extra_cbs = list(getattr(_eval_local, 'callbacks', None) or [])
    if extra_cbs:
        existing = list(kwargs.pop('callbacks', None) or [])
        kwargs['callbacks'] = existing + extra_cbs

    if backend == "ollama":
        from langchain_ollama import ChatOllama
        # Ollama는 max_tokens 대신 num_predict 사용
        ollama_kwargs = {k: v for k, v in kwargs.items() if k != "max_tokens"}
        if "max_tokens" in kwargs:
            ollama_kwargs["num_predict"] = kwargs["max_tokens"]
        return ChatOllama(
            model=model,
            base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
            **ollama_kwargs,
        )

    # anthropic/openai SDK 기본 재시도(커넥션 오류·429·5xx)와 LangGraph 재시도가
    # 중첩되지 않도록, retry_owner="application"이면 SDK 재시도를 끈다.
    kwargs.setdefault("max_retries", 0 if retry_owner == "application" else 2)

    if backend == "vllm":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model,
            base_url=os.getenv("VLLM_BASE_URL", "http://localhost:8000/v1"),
            api_key="EMPTY",
            **kwargs,
        )

    # 기본은 전부 Anthropic로 통일. 에이전트별 *_MODEL 환경변수에 gpt* 모델명을
    # 지정하면 그 에이전트만 OpenAI로 전환된다 — 원래는 intent만 이 분기를 탔는데
    # (gpt-4o-mini 할당량 없을 때 대비), Anthropic 계정에 크레딧이 없고 OpenAI
    # 계정만 있는 경우 등 다른 에이전트도 같은 방식으로 전환할 수 있어야 해서
    # agent 조건을 없앴다. 아무 *_MODEL도 gpt*로 안 바꾸면 기존 동작과 동일.
    if model.startswith("gpt"):
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=model, **kwargs)

    from langchain_anthropic import ChatAnthropic
    return ChatAnthropic(model=model, **kwargs)


def reset_all_llm_caches() -> None:
    """LLM 교체 실험 시 모든 에이전트 모듈의 싱글톤 캐시를 초기화한다."""
    try:
        import src.agents.intent_agent as ia
        ia._llm = None
        ia._structured_llm = None
    except Exception:
        pass
    try:
        import src.agents.product_agent as pa
        pa._llm = None
    except Exception:
        pass
    try:
        import src.agents.response_agent as ra
        ra._llm = None
    except Exception:
        pass
    try:
        import src.agents.context_agent as ca
        ca._context_llm = None
    except Exception:
        pass
