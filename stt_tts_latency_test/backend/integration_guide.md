# Backend Integration Guide

현재 워크스페이스에는 백엔드 실제 소스 파일이 없고 `FrontEnd/openapi.json`만 확인되었습니다.

확인된 endpoint는 아래 두 개가 핵심입니다.

1. `POST /api/agent/shopping-requests`
2. `POST /api/agent/conversations/{conversationId}/messages`

추가로 confirm endpoint도 같은 방식으로 확장 가능합니다.

## 권장 전달 방식

기존 request body 스키마를 유지하기 위해 아래 header를 사용합니다.

- `X-Latency-Session-Id`
- `X-Latency-Request-Id`
- `X-Latency-Turn-Index`

## 백엔드 측정 포인트

각 endpoint에서 아래 순서로 기록합니다.

1. `backend_request_received`
2. `agent_start`
3. 실제 agent 처리
4. `agent_end`
5. 응답 직전 `backend_response_sent`

## FastAPI 예시

`latency_logger.py`의 `FASTAPI_EXAMPLE` 문자열 그대로 삽입하면 됩니다.

핵심은 아래 형태입니다.

```python
latency = latency_context_from_headers(dict(request.headers))
latency.mark("agent_start")
response = await agent_service.send_message(conversation_id, body)
latency.mark("agent_end")
latency.mark("backend_response_sent")
emit_latency_log(latency.to_log())
return response
```

## 백엔드 로그 예시

```json
{
  "event": "backend_latency_turn",
  "session_id": "session-1747828200123456-abcd1234",
  "request_id": "request-1747828201456789-efgh5678",
  "turn_index": 4,
  "mode": "TEXT_AGENT_ONLY",
  "agent_processing_ms": 650,
  "backend_processing_ms": 700
}
```
