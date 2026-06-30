import 'dart:math' as math;
import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

class DallangResponseText extends StatefulWidget {
  const DallangResponseText({
    super.key,
    required this.text,
    this.fontSize = 34,
    this.maxLines,
    this.ttsDurationMs = 0,
  });

  final String text;
  final double fontSize;
  final int? maxLines;

  /// TTS 총 재생 시간(ms). 0이면 기본 속도 사용.
  final int ttsDurationMs;

  @override
  State<DallangResponseText> createState() => _DallangResponseTextState();
}

class _DallangResponseTextState extends State<DallangResponseText>
    with SingleTickerProviderStateMixin {
  late AnimationController _controller;
  String _displayedText = '';

  static const _waveDuration = 300.0;
  static const _defaultCharDelay = 60.0;
  static const _minCharDelay = 30.0;
  static const _maxCharDelay = 120.0;

  double _calcCharDelay(String text, int ttsDurationMs) {
    if (ttsDurationMs <= 0 || text.isEmpty) return _defaultCharDelay;
    // 글자가 다 나오는 시점을 TTS 종료 시점의 80%로 맞춤
    final targetMs = ttsDurationMs * 0.80;
    final delay = (targetMs - _waveDuration) / text.length;
    return delay.clamp(_minCharDelay, _maxCharDelay);
  }

  @override
  void initState() {
    super.initState();
    _displayedText = widget.text;
    final charDelay = _calcCharDelay(widget.text, widget.ttsDurationMs);
    final totalMs = widget.text.length * charDelay + _waveDuration;
    _controller = AnimationController(
      vsync: this,
      duration: Duration(milliseconds: totalMs.round()),
    )..forward();
  }

  @override
  void didUpdateWidget(DallangResponseText old) {
    super.didUpdateWidget(old);
    if (old.text != widget.text || old.ttsDurationMs != widget.ttsDurationMs) {
      _displayedText = widget.text;
      final charDelay = _calcCharDelay(widget.text, widget.ttsDurationMs);
      final totalMs = widget.text.length * charDelay + _waveDuration;
      _controller.duration = Duration(milliseconds: totalMs.round());
      _controller.forward(from: 0);
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final charDelay = _calcCharDelay(_displayedText, widget.ttsDurationMs);

    return LayoutBuilder(
      builder: (context, constraints) {
        final balancedText = widget.maxLines == 1
            ? _displayedText
                  .replaceAll('\n', ' ')
                  .replaceAll(RegExp(r'\s+'), ' ')
                  .trim()
            : _balanceTextByWords(
                _displayedText,
                GoogleFonts.jua(
                  textStyle: TextStyle(
                    fontSize: widget.fontSize,
                    height: 1.38,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                constraints.maxWidth,
              );
        final chars = balancedText.characters.toList();
        final totalChars = chars.length;

        return AnimatedBuilder(
          animation: _controller,
          builder: (context, _) {
            final elapsed =
                _controller.value * (totalChars * charDelay + _waveDuration);

            return _StyledTextWave(
              chars: chars,
              elapsed: elapsed,
              charDelay: charDelay,
              waveDuration: _waveDuration,
              fontSize: widget.fontSize,
              maxLines: widget.maxLines,
              highlightPattern: _highlightPattern,
              searchKeywordPattern: _searchKeywordPattern,
              fullText: balancedText,
            );
          },
        );
      },
    );
  }

  static final RegExp _highlightPattern = RegExp(
    r'('
    r'\d[\d,]*원|'
    r'\d+\s*개|'
    r'\d+\s*자리|'
    r'몇 개|'
    r'가장 싼|'
    r'최저가|'
    r'리뷰가 좋고|'
    r'인기 있는|'
    r'6자리|'
    r'진행 중|'
    r'결제가 완료|'
    r'주문이 완료|'
    r'구매를 완료|'
    r'구매가 완료|'
    r'다른 상품|'
    r')',
  );
  static final RegExp _searchKeywordPattern = RegExp(
    r'([^.!?。！？\n]+?)(?=(?:을|를)\s*찾고 있어요)|([^.!?。！？\n]+?)(?=\s*님)',
  );
}

class _StyledTextWave extends StatelessWidget {
  const _StyledTextWave({
    required this.chars,
    required this.elapsed,
    required this.charDelay,
    required this.waveDuration,
    required this.fontSize,
    required this.maxLines,
    required this.highlightPattern,
    required this.searchKeywordPattern,
    required this.fullText,
  });

  final List<String> chars;
  final double elapsed;
  final double charDelay;
  final double waveDuration;
  final double fontSize;
  final int? maxLines;
  final RegExp highlightPattern;
  final RegExp searchKeywordPattern;
  final String fullText;

  bool _isHighlighted(int charIndex) {
    final pos = _charBytePosition(charIndex);
    final matches = [
      ...highlightPattern.allMatches(fullText),
      ...searchKeywordPattern.allMatches(fullText),
    ];
    for (final m in matches) {
      if (pos >= m.start && pos < m.end) return true;
    }
    return false;
  }

  int _charBytePosition(int charIndex) {
    int bytePos = 0;
    for (int i = 0; i < charIndex && i < chars.length; i++) {
      bytePos += chars[i].length;
    }
    return bytePos;
  }

  @override
  Widget build(BuildContext context) {
    final baseStyle = GoogleFonts.jua(
      textStyle: TextStyle(
        fontSize: fontSize,
        height: 1.38,
        color: const Color(0xFF112030),
        fontWeight: FontWeight.w700,
        letterSpacing: -0.4,
      ),
    );

    final widgets = <Widget>[];
    final lineChars = <(String, bool, double, double)>[];

    for (int i = 0; i < chars.length; i++) {
      final ch = chars[i];
      final highlighted = ch != '\n' && _isHighlighted(i);
      final charStart = i * charDelay;
      final charProgress = ((elapsed - charStart) / waveDuration).clamp(
        0.0,
        1.0,
      );
      lineChars.add((ch, highlighted, charProgress, charStart));
    }

    // Build line by line for text alignment
    final lines = <List<(String, bool, double, double)>>[];
    var currentLine = <(String, bool, double, double)>[];
    for (final entry in lineChars) {
      if (entry.$1 == '\n') {
        lines.add(currentLine);
        currentLine = [];
      } else {
        currentLine.add(entry);
      }
    }
    if (currentLine.isNotEmpty) lines.add(currentLine);

    if (maxLines == 1) {
      return FittedBox(
        fit: BoxFit.scaleDown,
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: lineChars.map((entry) {
            final ch = entry.$1;
            if (ch == '\n') {
              return const SizedBox.shrink();
            }
            final highlighted = entry.$2;
            final progress = entry.$3;
            final opacity = progress.clamp(0.0, 1.0);
            final waveOffset = progress < 1.0
                ? -8.0 * math.sin(progress * math.pi)
                : 0.0;

            return Opacity(
              opacity: opacity,
              child: Transform.translate(
                offset: Offset(0, waveOffset),
                child: Text(
                  ch,
                  style: baseStyle.copyWith(
                    color: highlighted
                        ? const Color(0xFFD77B9E)
                        : const Color(0xFF112030),
                    fontWeight: highlighted ? FontWeight.w800 : FontWeight.w700,
                  ),
                ),
              ),
            );
          }).toList(),
        ),
      );
    }

    for (int li = 0; li < lines.length; li++) {
      final line = lines[li];
      widgets.add(
        Row(
          mainAxisAlignment: MainAxisAlignment.center,
          mainAxisSize: MainAxisSize.min,
          children: line.map((entry) {
            final ch = entry.$1;
            final highlighted = entry.$2;
            final progress = entry.$3;

            final opacity = progress.clamp(0.0, 1.0);
            // wave: sine curve peaking mid-animation then settling
            final waveOffset = progress < 1.0
                ? -8.0 * math.sin(progress * math.pi)
                : 0.0;

            return Opacity(
              opacity: opacity,
              child: Transform.translate(
                offset: Offset(0, waveOffset),
                child: Text(
                  ch,
                  style: baseStyle.copyWith(
                    color: highlighted
                        ? const Color(0xFFD77B9E)
                        : const Color(0xFF112030),
                    fontWeight: highlighted ? FontWeight.w800 : FontWeight.w700,
                  ),
                ),
              ),
            );
          }).toList(),
        ),
      );
      if (li < lines.length - 1) {
        widgets.add(SizedBox(height: fontSize * 0.38));
      }
    }

    return Column(mainAxisSize: MainAxisSize.min, children: widgets);
  }
}

String _balanceTextByWords(String source, TextStyle style, double maxWidth) {
  final normalized = source
      .replaceAll('\n', ' ')
      .replaceAll(RegExp(r'\s+'), ' ')
      .trim();
  if (normalized.isEmpty) {
    return normalized;
  }

  final tokens = normalized.split(' ');
  final lines = <String>[];
  final buffer = StringBuffer();

  for (final token in tokens) {
    final candidate = buffer.isEmpty ? token : '${buffer.toString()} $token';
    final linePainter = TextPainter(
      text: TextSpan(text: candidate, style: style),
      textDirection: TextDirection.ltr,
      maxLines: 1,
    )..layout(maxWidth: maxWidth);

    if (linePainter.didExceedMaxLines) {
      if (buffer.isNotEmpty) {
        lines.add(buffer.toString());
        buffer
          ..clear()
          ..write(token);
      } else {
        lines.add(token);
      }
      continue;
    }

    if (buffer.isNotEmpty) {
      buffer.write(' ');
    }
    buffer.write(token);
  }

  if (buffer.isNotEmpty) {
    lines.add(buffer.toString());
  }

  return lines.join('\n');
}
