# STT/TTS Latency Test Kit

이 디렉터리는 기존 코드를 직접 수정하지 않고, 현재 프로젝트의 프론트엔드 STT/TTS 흐름에 latency logging을 붙이기 위한 최소 변경용 자료를 모아둔 곳입니다.

## 이 디렉터리에 들어있는 것

- `frontend/latency_logger.dart`
  프론트엔드용 session/request/turn/timestamp 및 structured JSON log 유틸
- `frontend/integration_guide.md`
  현재 `FrontEnd` 코드에 어디를 어떻게 최소 수정해야 하는지 정리한 가이드
- `backend/latency_logger.py`
  백엔드용 structured JSON log 유틸과 FastAPI 예시
- `backend/integration_guide.md`
  백엔드 endpoint 적용 가이드
- `scripts/latency_jsonl_to_csv.py`
  프론트엔드/백엔드 로그를 CSV와 turn 평균 CSV로 변환하는 스크립트

## Repository 확인 결과

현재 워크스페이스에서 확인된 파일 기준으로 음성 흐름은 아래와 같습니다.

1. 프론트엔드에서 음성 녹음 시작/종료 처리
   `FrontEnd/lib/core/services/gemini_voice_service.dart`
2. 프론트엔드에서 STT 결과 생성
   `FrontEnd/lib/core/services/gemini_voice_service.dart`
3. 프론트엔드에서 백엔드 API 요청 전송
   `FrontEnd/lib/data/repositories/agent_repository.dart`
4. 프론트엔드에서 백엔드 응답 수신
   `FrontEnd/lib/data/repositories/agent_repository.dart`
5. 프론트엔드에서 TTS 생성/재생 처리
   `FrontEnd/lib/core/services/gemini_voice_service.dart`
6. 백엔드 텍스트 endpoint
   실제 소스는 워크스페이스에 없었고, `FrontEnd/openapi.json`에서 아래 endpoint를 확인했습니다.
   `POST /api/agent/shopping-requests`
   `POST /api/agent/conversations/{conversationId}/messages`

## Timestamp 기록 위치

프론트엔드:

- `interaction_start`
  `CallProvider.startListening()`에서 turn 생성 직후
- `user_speech_start`
  `GeminiVoiceService.startRecording()` 호출 직전 또는 직후
- `user_speech_end`
  `CallProvider.stopListeningAndSend()`에서 사용자가 녹음을 끝낸 직후
- `frontend_stt_start`
  `GeminiVoiceService.stopRecordingAndTranscribe()` 호출 직전
- `frontend_stt_end`
  `stopRecordingAndTranscribe()` 결과를 받은 직후
- `frontend_request_sent`
  `AgentRepository.startShopping()` / `sendMessage()`의 `dio.post(...)` 직전
- `frontend_response_received`
  `dio.post(...)` 응답 직후
- `response_text_received`
  `AgentResponse.fromJson(...)` 완료 직후
- `frontend_tts_start`
  `GeminiVoiceService.speak()` 시작 시점
- `frontend_tts_ready`
  `_getOrCreateSpeech(text)` 완료 직후
- `audio_play_start`
  `_player.play(...)` 직전
- `audio_play_end`
  `onPlayerComplete` 또는 `_finishSpeaking()`에서 재생 종료 확인 시점

백엔드:

- `backend_request_received`
  endpoint 진입 직후
- `agent_start`
  실제 agent/service 호출 직전
- `agent_end`
  agent/service 호출 완료 직후
- `backend_response_sent`
  `return response` 직전

## 측정되는 latency metric

메인 그래프의 핵심 지표:

- `total_response_latency_ms = audio_play_start - user_speech_end`
  사용자가 말을 끝낸 시점부터 AI 음성 응답이 실제로 재생되기 시작할 때까지의 시간

병목 분석용 보조 지표:

- `frontend_stt_processing_ms`
- `api_round_trip_ms`
- `agent_processing_ms`
- `frontend_tts_processing_ms`

프론트엔드:

- `frontend_stt_processing_ms = frontend_stt_end - frontend_stt_start`
- `api_round_trip_ms = frontend_response_received - frontend_request_sent`
- `frontend_tts_processing_ms = audio_play_start - frontend_tts_start`
- `total_response_latency_ms = audio_play_start - user_speech_end`
- `total_interaction_latency_ms = audio_play_start - interaction_start`

백엔드:

- `agent_processing_ms = agent_end - agent_start`
- `backend_processing_ms = backend_response_sent - backend_request_received`

## 1회 테스트 방법

1. `frontend/integration_guide.md` 기준으로 프론트엔드에 최소 변경을 적용합니다.
2. 백엔드 소스가 있는 저장소에서 `backend/latency_logger.py`와 `backend/integration_guide.md` 기준으로 endpoint logging을 넣습니다.
3. 앱에서 쇼핑 통화를 시작합니다.
4. 마이크 버튼을 눌러 한 번 말합니다.
5. 콘솔에서 `event: frontend_latency_turn` 과 `event: backend_latency_turn` 로그를 확인합니다.

## 1, 4, 7, 10, 20 turn 테스트 방법

각 실험은 "하나의 session 안에서 연속 turn 수" 기준입니다.

1. 새 쇼핑 세션 시작
2. 세션 안에서 음성 질의/응답을 1회, 4회, 7회, 10회, 20회 반복
3. turn마다 같은 `session_id`를 유지하고 `turn_index`가 1부터 증가하는지 확인
4. 세션 종료 후 콘솔 로그를 파일로 저장
5. 아래 스크립트로 CSV 생성

```bash
python3 stt_tts_latency_test/scripts/latency_jsonl_to_csv.py frontend.log backend.log
```

생성 결과:

- `latency_turns.csv`
- `latency_turn_summary.csv`

`latency_turn_summary.csv`에서 아래 평균치를 바로 확인할 수 있습니다.

- `average_total_response_latency_ms`
  메인 그래프용 핵심 지표
- `average_total_response_latency_ms`
- `average_frontend_stt_processing_ms`
- `average_api_round_trip_ms`
- `average_agent_processing_ms`
- `average_frontend_tts_processing_ms`

## 로그 확인 위치

- 프론트엔드: Flutter debug console
- 백엔드: 서버 stdout / application log
- CSV export: 스크립트 실행 결과 파일

## Sample Log Output

프론트엔드:

```json
{
  "event": "frontend_latency_turn",
  "session_id": "session-1747828200123456-abcd1234",
  "request_id": "request-1747828201456789-efgh5678",
  "turn_index": 4,
  "mode": "FRONTEND_STT_TTS",
  "interaction_start": "2026-05-21T03:10:00.123Z",
  "user_speech_start": "2026-05-21T03:10:00.140Z",
  "user_speech_end": "2026-05-21T03:10:02.000Z",
  "frontend_stt_start": "2026-05-21T03:10:02.005Z",
  "frontend_stt_end": "2026-05-21T03:10:02.325Z",
  "frontend_request_sent": "2026-05-21T03:10:02.330Z",
  "frontend_response_received": "2026-05-21T03:10:03.110Z",
  "response_text_received": "2026-05-21T03:10:03.115Z",
  "frontend_tts_start": "2026-05-21T03:10:03.120Z",
  "frontend_tts_ready": "2026-05-21T03:10:03.250Z",
  "audio_play_start": "2026-05-21T03:10:03.330Z",
  "audio_play_end": "2026-05-21T03:10:05.100Z",
  "frontend_stt_processing_ms": 320,
  "api_round_trip_ms": 780,
  "frontend_tts_processing_ms": 210,
  "total_response_latency_ms": 1330,
  "total_interaction_latency_ms": 3207
}
```

백엔드:

```json
{
  "event": "backend_latency_turn",
  "session_id": "session-1747828200123456-abcd1234",
  "request_id": "request-1747828201456789-efgh5678",
  "turn_index": 4,
  "mode": "TEXT_AGENT_ONLY",
  "backend_request_received": "2026-05-21T03:10:02.350Z",
  "agent_start": "2026-05-21T03:10:02.355Z",
  "agent_end": "2026-05-21T03:10:03.005Z",
  "backend_response_sent": "2026-05-21T03:10:03.050Z",
  "agent_processing_ms": 650,
  "backend_processing_ms": 700
}
```
