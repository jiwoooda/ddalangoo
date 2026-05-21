# Frontend Integration Guide

기존 파일을 리팩토링하지 않고 최소 변경으로 latency logging을 넣는 기준입니다.

## 확인된 현재 파일

1. 음성 녹음 시작/종료: `FrontEnd/lib/core/services/gemini_voice_service.dart`
2. STT 결과 생성: `FrontEnd/lib/core/services/gemini_voice_service.dart`
3. 백엔드 API 요청 전송: `FrontEnd/lib/data/repositories/agent_repository.dart`
4. 백엔드 응답 수신: `FrontEnd/lib/data/repositories/agent_repository.dart`
5. TTS 생성/재생: `FrontEnd/lib/core/services/gemini_voice_service.dart`
6. 현재 음성 흐름 오케스트레이션: `FrontEnd/lib/presentation/providers/call_provider.dart`

## 권장 추가 import

`call_provider.dart`

```dart
import '../../../stt_tts_latency_test/frontend/latency_logger.dart';
```

`agent_repository.dart`

```dart
import '../../../stt_tts_latency_test/frontend/latency_logger.dart';
```

`gemini_voice_service.dart`

```dart
import '../../../stt_tts_latency_test/frontend/latency_logger.dart';
```

## 1. 세션 시작 / 종료

`CallProvider.startCall()` 시작부:

```dart
FrontendLatencyLogger.instance.startSession();
```

`CallProvider.endCall()` 마지막:

```dart
FrontendLatencyLogger.instance.endSession();
```

## 2. turn 생성과 사용자 발화 구간

`CallProvider`에 필드 추가:

```dart
LatencyRequestContext? _activeLatencyContext;
```

`startListening()`에서 녹음 직전:

```dart
final context = FrontendLatencyLogger.instance.beginTurn();
_activeLatencyContext = context;
FrontendLatencyLogger.instance.mark(context, 'user_speech_start');
```

`stopListeningAndSend()`에서 `_isListening = false;` 직후:

```dart
final context = _activeLatencyContext;
if (context != null) {
  FrontendLatencyLogger.instance.mark(context, 'user_speech_end');
  FrontendLatencyLogger.instance.mark(context, 'frontend_stt_start');
}
```

STT 완료 직후:

```dart
if (context != null) {
  FrontendLatencyLogger.instance.mark(context, 'frontend_stt_end');
}
```

## 3. API 요청 / 응답

`AgentRepository.startShopping()`과 `sendMessage()`에 optional context 추가:

```dart
Future<AgentResponse> startShopping({
  required int userId,
  required String message,
  LatencyRequestContext? latencyContext,
}) async
```

```dart
Future<AgentResponse> sendMessage({
  required int conversationId,
  required String message,
  LatencyRequestContext? latencyContext,
}) async
```

요청 직전:

```dart
if (latencyContext != null) {
  FrontendLatencyLogger.instance.mark(latencyContext, 'frontend_request_sent');
}
```

`dio.post(...)`에 header 추가:

```dart
options: Options(
  headers: {
    ...?latencyContext?.toHeaders(),
  },
),
```

응답 직후:

```dart
if (latencyContext != null) {
  FrontendLatencyLogger.instance.mark(
    latencyContext,
    'frontend_response_received',
  );
}
```

응답 파싱 직후:

```dart
if (latencyContext != null) {
  FrontendLatencyLogger.instance.mark(
    latencyContext,
    'response_text_received',
    responseText: agentResponse.assistantMessage,
  );
}
```

## 4. TTS 생성 / 재생

`GeminiVoiceService.speak(...)` 시그니처:

```dart
Future<void> speak(String text, {LatencyRequestContext? latencyContext}) async
```

메서드 시작부:

```dart
if (latencyContext != null) {
  FrontendLatencyLogger.instance.mark(latencyContext, 'frontend_tts_start');
}
```

`final wavBytes = await _getOrCreateSpeech(text);` 다음:

```dart
if (latencyContext != null) {
  FrontendLatencyLogger.instance.mark(latencyContext, 'frontend_tts_ready');
}
```

`await _player.play(BytesSource(wavBytes));` 직전:

```dart
if (latencyContext != null) {
  FrontendLatencyLogger.instance.mark(latencyContext, 'audio_play_start');
}
```

`_finishSpeaking()` 진입 전 또는 `onPlayerComplete` 내부:

```dart
if (latencyContext != null) {
  FrontendLatencyLogger.instance.mark(latencyContext, 'audio_play_end');
}
```

## 5. CallProvider에서 context 전달

`startShopping(...)`, `sendMessage(...)`, `_voiceService.speak(...)` 호출부에 모두 같은 `context`를 전달합니다.

예:

```dart
final context = _activeLatencyContext;
final response = await _agentRepository.sendMessage(
  conversationId: _conversationId!,
  message: transcript,
  latencyContext: context,
);
await _handleResponse(response, latencyContext: context);
```

그리고 `_handleResponse(...)` 시그니처를 아래처럼 늘립니다.

```dart
Future<void> _handleResponse(
  AgentResponse response, {
  LatencyRequestContext? latencyContext,
}) async
```

TTS 호출:

```dart
await _voiceService.speak(
  response.assistantMessage,
  latencyContext: latencyContext,
).timeout(...);
```

## 프론트엔드 로그 예시

메인 그래프에는 `total_response_latency_ms`를 사용하고, 나머지 STT/TTS/API 관련 지표는 병목 분석용으로 함께 기록합니다.

```json
{
  "event": "frontend_latency_turn",
  "session_id": "session-1747828200123456-abcd1234",
  "request_id": "request-1747828201456789-efgh5678",
  "turn_index": 4,
  "mode": "FRONTEND_STT_TTS",
  "frontend_stt_processing_ms": 320,
  "api_round_trip_ms": 780,
  "frontend_tts_processing_ms": 210,
  "total_response_latency_ms": 1450,
  "total_interaction_latency_ms": 2100
}
```
