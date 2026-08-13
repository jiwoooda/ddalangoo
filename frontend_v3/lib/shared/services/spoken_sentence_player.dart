import '../../core/services/voice_service.dart';

/// 화면에 "지금 보이는 문장"과 실제로 TTS가 "지금 말하고 있는 문장"이 항상
/// 같도록 순서대로 재생하는 작은 헬퍼.
///
/// 여러 화면(홈/스몰토크/플랫폼체크/구매이력 로딩/분석 안내 등)이 각자
/// 비슷한 for-loop(문장별 setState → speak 대기 → 다음 문장)를 복붙해서
/// 쓰다 보면 화면마다 조금씩 다르게 구현되어 싱크가 어긋나기 쉽다. 그래서
/// 한 곳으로 모았다. `DialogueBubble.cyclePages`(고정 타이머로 문장을
/// 순환하는 순수 시각 효과)와는 다르다 — 이 클래스는 실제 TTS 재생
/// 완료를 기다렸다가만 다음 문장으로 넘어간다.
class SpokenSentencePlayer {
  SpokenSentencePlayer({VoiceService? voiceService})
    : _voiceService = voiceService ?? VoiceService.instance;

  final VoiceService _voiceService;
  int _runId = 0;

  /// [sentences]를 순서대로, 한 문장씩 [onSentence]로 화면에 반영한 뒤
  /// 그 문장의 TTS 재생이 끝날 때까지 기다렸다가 다음 문장으로 넘어간다.
  ///
  /// 같은 인스턴스에서 이 메서드를 다시 호출하면(예: 새 메시지 도착) 이전
  /// 재생 루프는 더 이상 진행하지 않고 조용히 멈춘다(runId 비교로 취소).
  Future<void> play(
    List<String> sentences, {
    required bool Function() isMounted,
    required void Function(String sentence) onSentence,
  }) async {
    final runId = ++_runId;
    final queue = sentences
        .map((sentence) => sentence.trim())
        .where((sentence) => sentence.isNotEmpty)
        .toList(growable: false);

    for (final sentence in queue) {
      if (!isMounted() || runId != _runId) {
        return;
      }
      onSentence(sentence);
      try {
        await _voiceService.speak(sentence);
      } catch (_) {
        // TTS는 진행 보조 기능이라 실패해도 다음 문장 진행은 막지 않는다.
      }
    }
  }

  /// 현재 재생 루프를 취소한다(다음 sentence로 넘어가지 않게 함). 이미
  /// 시작된 speak() 자체를 중단시키지는 않으므로, 오디오까지 즉시 멈추고
  /// 싶으면 VoiceService.stopSpeaking()을 같이 호출해야 한다.
  void cancel() {
    _runId += 1;
  }

  /// 마침표/느낌표/물음표 기준 정규식 문장 분리. 백엔드 응답이 없는
  /// 하드코딩 안내 문구를 문장 단위로 나눌 때 쓴다(백엔드
  /// split_response_sentences와 같은 목적의 프론트 전용 버전. 화면
  /// 안내문에서 줄바꿈('\n')으로 문장을 이미 나눠둔 경우에는 그 쪽을
  /// 우선 쓰는 게 더 정확하다).
  static List<String> splitSentences(String message) {
    final normalized = message.trim();
    if (normalized.isEmpty) {
      return const <String>[];
    }
    final matches = RegExp(r'[^.!?。？！]+[.!?。？！]?').allMatches(normalized);
    final sentences = matches
        .map((match) => match.group(0)?.trim() ?? '')
        .where((sentence) => sentence.isNotEmpty)
        .toList(growable: false);
    return sentences.isEmpty ? <String>[normalized] : sentences;
  }
}
