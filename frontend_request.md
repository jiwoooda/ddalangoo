# Backend Handoff: Speech Segment 분리 + 프론트 순차 재생

작성일: 2026-08-06

## 목적

딸랑구 음성이 재생될 때, 말풍선 텍스트도 전체 문장을 한 번에 보여주지 않고 "한 문장씩" 순차적으로 표시하고 싶다.

이 기능은 프론트 단독 처리보다, 백엔드가 문장 단위를 명시적으로 내려주고 프론트가 그 순서를 따라 재생/표시하는 구조가 더 적합하다.

이 문서는 실제 구현 요청이 아니라, 백엔드 전달용 TODO 및 권장 구현 방향 정리 문서다.

## 현재 상태

### 프론트 현재 동작

- `frontend_v3/lib/features/shopping/screens/shopping_flow_screen.dart`
  - 말풍선은 현재 `assistantMessage` 전체 문자열을 그대로 표시한다.
  - 음성도 현재 `VoiceService.speak(text)`로 전체 문자열을 한 번에 TTS 요청한다.
- `frontend_v3/lib/core/services/voice_service.dart`
  - `/api/voice/tts`에 `{"text": "...전체 문장..."}` 형태로 요청한다.

### 백엔드 현재 동작

- `backend/app/schemas/agent.py`
  - `AgentResponse`에는 현재 `assistantMessage`만 있고 `speechMode`, `speechSegments`가 없다.
- `backend/app/routers/voice.py`
  - `/api/voice/tts`는 단일 텍스트를 단일 오디오로 변환한다.

### 참고

- 프론트의 `AgentResponse` 파싱 모델에는 이미 `speechMode`, `speechSegments` 필드가 준비되어 있다.
  - `frontend_v3/lib/data/models/agent_model.dart`
- 즉, 프론트 모델은 일부 준비되어 있지만, 백엔드 응답 계약은 아직 연결되지 않은 상태다.

## 왜 백엔드에서 분리하는 게 맞는가

프론트에서 단순히 문자열을 문장 부호 기준으로 잘라도 동작은 가능하다. 하지만 아래 이유로 백엔드가 분리 기준을 내려주는 쪽이 더 안정적이다.

- 한국어 문장 경계가 항상 단순하지 않다.
- 상품명, 옵션, 수량, 주소, 전화번호 같은 텍스트는 프론트 임의 분리 시 어색하게 끊길 수 있다.
- 나중에 TTS 발화 단위와 화면 표시 단위를 정확히 맞추려면 "같은 기준"이 필요하다.
- 여러 화면에서 같은 말풍선 정책을 재사용하기 쉽다.
- 로그/실험/A-B 테스트 기준도 백엔드에서 통일하기 좋다.

## 권장 역할 분리

### 백엔드 역할

- `assistantMessage`를 유지한다.
- 추가로 `speechMode`, `speechSegments`를 함께 내려준다.
- 각 `speechSegment`는 "한 문장" 기준으로 분리한다.
- 필요 시 향후 `durationMs`, `audioUrl` 같은 메타데이터도 확장 가능하게 만든다.

### 프론트 역할

- `speechSegments`가 있으면 전체 문장을 한 번에 보여주지 않고 현재 segment만 표시한다.
- segment 단위로 TTS를 재생한다.
- segment 재생 완료 후 다음 segment로 넘어간다.
- `speechSegments`가 없으면 기존 `assistantMessage` 전체 표시 방식으로 fallback 한다.

## 권장 API 계약

기존 `assistantMessage`는 유지하고, 아래 필드를 추가한다.

```json
{
  "conversationId": 101,
  "status": "waiting_user_confirmation",
  "stage": "product_confirming",
  "assistantMessage": "김영희님, 뭐가 필요하세요? 천천히 말씀해 주세요.",
  "speechMode": "segmented",
  "speechSegments": [
    {
      "index": 0,
      "text": "김영희님, 뭐가 필요하세요?"
    },
    {
      "index": 1,
      "text": "천천히 말씀해 주세요."
    }
  ]
}
```

### 필드 제안

- `speechMode`
  - `"full_text"`: 기존과 동일하게 전체 텍스트 처리
  - `"segmented"`: `speechSegments` 순차 처리
- `speechSegments`
  - `index: int`
  - `text: str`
  - `audioUrl: Optional[str]` (지금은 생략 가능)
  - `durationMs: Optional[int]` (지금은 생략 가능)

## 권장 구현 방식

### 1. 백엔드 schema 확장

수정 대상:

- `backend/app/schemas/agent.py`

추가 제안:

```python
class SpeechSegment(BaseModel):
    index: int
    text: str
    audioUrl: Optional[str] = None
    durationMs: Optional[int] = None


class AgentResponse(BaseModel):
    ...
    assistantMessage: str
    speechMode: Optional[str] = None
    speechSegments: List[SpeechSegment] = []
```

## 2. 문장 분리 유틸 추가

권장 신규 파일:

- `backend/app/utils/speech_segments.py`

역할:

- `assistantMessage`를 화면 표시용 발화 단위로 분리
- 반환 형태는 `list[dict]` 또는 schema object list

예시 인터페이스:

```python
def build_speech_segments(text: str) -> list[dict]:
    ...
```

### 분리 규칙 제안

- 기본 기준은 문장 종결 부호
  - `.`, `?`, `!`
  - `요.`, `니다.`, `까요?`, `세요.`
- 빈 segment 제거
- 앞뒤 공백 제거
- segment 순서 유지
- 너무 짧은 문장 조각은 앞 문장과 합치지 말고 우선 그대로 둔다
- 숫자/단위/주소/전화번호는 불필요하게 끊지 않도록 한다

초기 버전은 "완벽한 자연어 분해기"가 아니라, deterministic한 문장 분리기로 시작하는 것이 현실적이다.

## 3. AgentResponse 생성 구간에서 segment 주입

수정 우선 대상:

- `backend/app/agent/mapper.py`
- `backend/app/services/agent_service.py`
- `backend/app/services/payment_service.py`
- 기타 `AgentResponse(...)`를 직접 만드는 서비스

원칙:

- `assistantMessage`를 만들 때 동일한 텍스트로 `speechSegments`도 생성한다.
- `speechMode`는 일단 `"segmented"`를 기본값으로 사용 가능하다.
- 음성/화면 순차 표시가 불필요한 특수 응답은 `"full_text"`도 가능하다.

예시:

```python
message = "결제가 완료되었어요. 주문이 접수되었어요."
segments = build_speech_segments(message)

return AgentResponse(
    ...,
    assistantMessage=message,
    speechMode="segmented",
    speechSegments=segments,
)
```

## 4. `/api/voice/tts`는 일단 유지

현재 단계에서는 `/api/voice/tts`를 바꾸지 않아도 된다.

즉, 1차 구현은 아래 흐름이면 충분하다.

1. 백엔드가 `speechSegments[].text`를 내려준다.
2. 프론트가 segment 텍스트를 하나씩 `/api/voice/tts`에 요청한다.
3. 프론트가 재생 완료 이벤트를 기준으로 다음 segment로 넘어간다.

이 방식의 장점:

- 백엔드 변경 범위를 최소화할 수 있다.
- 기존 TTS endpoint를 재사용할 수 있다.
- 프론트/백엔드 책임이 명확하다.

## 5. 향후 확장안

필요하면 2차로 아래 확장 가능:

- batch TTS endpoint 추가
  - 예: `/api/voice/tts/segments`
- segment별 오디오를 백엔드에서 미리 생성
- `durationMs` 추정값 또는 실제 길이 제공
- 특정 stage에서만 segmented mode 적용
- 말풍선 애니메이션과 TTS 타이밍을 더 정밀하게 동기화

## 백엔드 TODO

### 필수

- `AgentResponse` schema에 `speechMode`, `speechSegments` 추가
- 문장 분리 유틸 추가
- `mapper.py`에서 `assistantMessage` 기준 `speechSegments` 생성
- `agent_service.py`, `payment_service.py` 등 직접 `AgentResponse` 만드는 경로에도 동일 적용
- 응답 테스트 추가

### 권장

- 문장 분리 규칙 테스트 추가
- 빈 메시지/짧은 메시지/긴 메시지/상품명 포함 메시지 테스트 추가
- fallback 정책 정의
  - `speechSegments == []`이면 프론트는 `assistantMessage` 사용

## 테스트 항목

### API 계약 테스트

- `assistantMessage`가 있으면 `speechSegments`도 존재하는지
- `speechSegments[index]`가 정렬된 상태인지
- `speechSegments.text`를 공백 제거한 뒤 join 했을 때 원문 의미가 유지되는지

### 문장 분리 테스트

- `"김영희님, 뭐가 필요하세요?"`
  - 1개 segment
- `"결제가 완료되었어요. 주문이 접수되었어요."`
  - 2개 segment
- `"대추방울토마토 750g부터 보여드릴게요. 괜찮으면 장바구니에 담아볼까요?"`
  - 2개 segment
- `"주소는 서울 용산구 효창로 71길 107동 1206호 맞으세요?"`
  - 주소가 중간에서 부자연스럽게 끊기지 않는지 확인

## 프론트 예상 후속 작업

이번 문서는 백엔드 전달용이지만, 이후 프론트는 아래를 구현하게 된다.

- `shopping_flow_screen.dart`
  - 현재 segment index 상태 관리
  - segment별 말풍선 교체
  - segment별 TTS 순차 재생
- `smalltalk_screen.dart`
  - 동일 구조 적용 여부 검토
- fallback 처리
  - `speechSegments`가 없으면 기존 전체 문장 사용

## 오픈 질문

- 모든 stage에 segmented mode를 적용할지, 특정 stage만 적용할지
- 안내 멘트가 아주 짧은 경우에도 segment를 강제할지
- segment별 TTS를 매번 요청할지, 한 번에 미리 만들지
- 추후 accessibility/native TTS와도 같은 계약을 재사용할지

## 권장 결론

이번 요구사항은 "프론트에서 억지로 문장을 자르는 문제"가 아니라 "백엔드가 발화 단위를 내려주고, 프론트가 그 단위를 재생/표시하는 문제"로 보는 것이 맞다.

따라서 1차 구현 권장안은 아래와 같다.

1. 백엔드가 `assistantMessage + speechSegments`를 함께 내려준다.
2. 프론트가 `speechSegments`를 한 문장씩 표시한다.
3. 프론트가 각 segment를 `/api/voice/tts`로 순차 재생한다.
4. `assistantMessage`는 fallback 및 로그 용도로 유지한다.
