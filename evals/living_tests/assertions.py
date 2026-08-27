"""Deterministic assertion 체커 — Living Test의 `expected_assertions`를 실제
실행 결과(agent 출력 dict 또는 graph 실행의 executed_nodes)와 비교한다.

지금 실제 케이스가 쓰는 종류만 구현한다(필요해지면 추가하는 최소주의):
  - field_equals: 노드 출력(dict)의 특정 경로 값이 기대값과 같은지
  - field_contains / field_not_contains: LLM이 생성한 자연어 필드처럼 문구가
    매번 조금씩 달라지는 값은 정확히 일치시킬 수 없다 — 특정 부분 문자열을
    포함하는지/안 하는지만 본다(대소문자 무시). not_contains는 프롬프트
    수정으로 없앤 문구가 회귀로 다시 나오지 않는지 확인할 때 쓴다.
  - executed_nodes_contains / executed_nodes_not_contains: graph 실행 시
    특정 노드가 (안) 돌았는지 — Agent 하나만으로는 못 잡는 라우팅/핸드오프
    버그(예: routing-2026-08-18-001)를 위한 것.
"""
from __future__ import annotations

import re
from typing import Any


def _resolve_path(data: Any, path: str) -> Any:
    """'selected_product.brand', 'cart_items[0].quantity' 같은 경로를 읽는다.
    중간에 없는 키/인덱스를 만나면 None."""
    obj = data
    for part in re.split(r"\.|\[|\]", path):
        if part == "":
            continue
        if obj is None:
            return None
        if isinstance(obj, list):
            try:
                obj = obj[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(obj, dict):
            obj = obj.get(part)
        else:
            return None
    return obj


def _check_field_equals(assertion: dict, output: dict, executed_nodes: list[str]) -> dict:
    path = assertion["path"]
    expected = assertion["value"]
    actual = _resolve_path(output, path)
    return {
        "type": "field_equals", "path": path,
        "expected": expected, "actual": actual,
        "passed": actual == expected,
    }


def _check_field_contains(assertion: dict, output: dict, executed_nodes: list[str]) -> dict:
    """field_equals의 형제 - LLM이 생성한 자연어 필드(explanation 등)처럼 문구가
    매번 조금씩 달라지는 값은 정확히 일치시킬 수 없다. 부분 문자열 포함 여부만
    본다(대소문자 구분 없음)."""
    path = assertion["path"]
    expected = assertion["value"]
    actual = _resolve_path(output, path)
    passed = isinstance(actual, str) and str(expected).lower() in actual.lower()
    return {
        "type": "field_contains", "path": path,
        "expected": expected, "actual": actual,
        "passed": passed,
    }


def _check_field_not_contains(assertion: dict, output: dict, executed_nodes: list[str]) -> dict:
    """field_contains의 반대 — LLM이 특정 문구/패턴을 다시 쓰지 않는지 확인할
    때 쓴다(예: 페르소나가 강제하던 억지 공감 문구가 프롬프트 수정 후 안
    나오는지 회귀 확인, smalltalk_agent 등). 필드가 문자열이 아니면(값이
    아예 없는 경우 포함) 애초에 그 문구를 쓸 수 없으므로 통과로 본다."""
    path = assertion["path"]
    expected = assertion["value"]
    actual = _resolve_path(output, path)
    passed = not (isinstance(actual, str) and str(expected).lower() in actual.lower())
    return {
        "type": "field_not_contains", "path": path,
        "expected": expected, "actual": actual,
        "passed": passed,
    }


def _check_executed_nodes_contains(assertion: dict, output: dict, executed_nodes: list[str]) -> dict:
    value = assertion["value"]
    return {
        "type": "executed_nodes_contains", "value": value,
        "executed_nodes": executed_nodes,
        "passed": value in (executed_nodes or []),
    }


def _check_executed_nodes_not_contains(assertion: dict, output: dict, executed_nodes: list[str]) -> dict:
    value = assertion["value"]
    return {
        "type": "executed_nodes_not_contains", "value": value,
        "executed_nodes": executed_nodes,
        "passed": value not in (executed_nodes or []),
    }


_CHECKERS = {
    "field_equals": _check_field_equals,
    "field_contains": _check_field_contains,
    "field_not_contains": _check_field_not_contains,
    "executed_nodes_contains": _check_executed_nodes_contains,
    "executed_nodes_not_contains": _check_executed_nodes_not_contains,
}


class UnknownAssertionType(ValueError):
    pass


def run_assertions(
    assertions: list[dict], output: dict, executed_nodes: list[str] | None = None,
) -> list[dict]:
    """각 assertion을 채점해서 결과 리스트로 반환한다(각 항목에 passed: bool 포함).
    모르는 type이 오면 즉시 실패 처리(조용히 넘어가지 않음 — 오탐지보다 명시적
    에러가 낫다)."""
    results = []
    for assertion in assertions:
        checker = _CHECKERS.get(assertion.get("type"))
        if checker is None:
            raise UnknownAssertionType(
                f"모르는 assertion type: {assertion.get('type')!r} (지원: {list(_CHECKERS)})"
            )
        results.append(checker(assertion, output, executed_nodes or []))
    return results


def verdict_from_assertions(assertion_results: list[dict]) -> str:
    """assertion이 하나도 없으면 'uncertain'(사람 검토 필요) — 있는데 하나라도
    실패하면 'fail', 다 통과하면 'pass'."""
    if not assertion_results:
        return "uncertain"
    return "pass" if all(r["passed"] for r in assertion_results) else "fail"
