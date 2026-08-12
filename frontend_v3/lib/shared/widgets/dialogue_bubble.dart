import 'dart:async';

import 'package:flutter/material.dart';

import '../../app/theme/app_colors.dart';
import '../../app/theme/app_radii.dart';
import '../../app/theme/app_spacing.dart';
import '../../app/theme/app_surface_styles.dart';
import '../../app/theme/app_text_styles.dart';

class DialogueSegment {
  const DialogueSegment({required this.text, this.emphasized = false});

  final String text;
  final bool emphasized;
}

enum DialogueBubbleTail { none, left, right }

class DialogueBubble extends StatelessWidget {
  const DialogueBubble({
    super.key,
    this.text,
    this.highlightedWords = const <String>[],
    this.segments,
    this.tail = DialogueBubbleTail.left,
    this.textAlign = TextAlign.left,
    this.style,
    this.emphasizedStyle,
    this.contentKey,
    this.animateTextChanges = false,
    this.cyclePages = false,
    this.cyclePageInterval = const Duration(milliseconds: 2600),
    this.backgroundColor = Colors.white,
    this.borderColor,
    this.padding = const EdgeInsets.all(AppSpacing.lg),
    this.minHeight,
    this.scrollableContent = false,
    this.contentAlignment = Alignment.topLeft,
  }) : assert(
         text != null || segments != null,
         'Either text or segments must be provided.',
       );

  final String? text;
  final List<String> highlightedWords;
  final List<DialogueSegment>? segments;
  final DialogueBubbleTail tail;
  final TextAlign textAlign;
  final TextStyle? style;
  final TextStyle? emphasizedStyle;
  final Key? contentKey;
  final bool animateTextChanges;

  /// true면 전체 문구를 한 번에 다 보여주는 대신, 문장(또는 명시적으로
  /// '\n'으로 나눈 문단) 단위로 하나씩 순서대로 보여준다. 딸랑구가 실제로
  /// 한 문장씩 말하는 듯한 느낌을 주고, 문구가 길어도 말풍선 높이를 고정으로
  /// 유지하면서 잘리는 문제 없이 다 보여줄 수 있다. [contentKey]가 바뀌면
  /// (새 메시지로 교체되면) 처음 문장부터 다시 시작한다.
  final bool cyclePages;

  /// [cyclePages]가 true일 때 문장이 넘어가는 간격.
  final Duration cyclePageInterval;

  final Color backgroundColor;
  final Color? borderColor;
  final EdgeInsets padding;
  final double? minHeight;
  final bool scrollableContent;
  final Alignment contentAlignment;

  @override
  Widget build(BuildContext context) {
    final baseStyle = style ?? AppTextStyles.body1;
    final accentStyle =
        emphasizedStyle ??
        baseStyle.copyWith(
          color: AppColors.primaryPinkDark,
          fontWeight: FontWeight.w800,
        );

    final fragments = _buildFragments(
      source: text,
      highlightedWords: highlightedWords,
      segments: segments,
      baseStyle: baseStyle,
      accentStyle: accentStyle,
    );

    final Widget content;
    if (cyclePages) {
      content = _CyclingDialogueContent(
        key:
            contentKey ??
            ValueKey(text ?? segments?.map((s) => s.text).join('|') ?? ''),
        fragments: fragments,
        baseStyle: baseStyle,
        textAlign: textAlign,
        interval: cyclePageInterval,
      );
    } else if (animateTextChanges) {
      content = AnimatedSwitcher(
        duration: const Duration(milliseconds: 260),
        switchInCurve: Curves.easeOutCubic,
        switchOutCurve: Curves.easeInCubic,
        transitionBuilder: (child, animation) {
          return FadeTransition(opacity: animation, child: child);
        },
        child: _WordBoundaryTextLayout(
          key: contentKey,
          fragments: fragments,
          baseStyle: baseStyle,
          textAlign: textAlign,
        ),
      );
    } else {
      content = _WordBoundaryTextLayout(
        key: contentKey,
        fragments: fragments,
        baseStyle: baseStyle,
        textAlign: textAlign,
      );
    }

    return _BubbleContainer(
      tail: tail,
      backgroundColor: backgroundColor,
      padding: padding,
      minHeight: minHeight,
      contentAlignment: contentAlignment,
      child: scrollableContent
          ? SingleChildScrollView(
              primary: false,
              physics: const ClampingScrollPhysics(),
              child: content,
            )
          : content,
    );
  }
}

List<_StyledFragment> _buildFragments({
  required String? source,
  required List<String> highlightedWords,
  required List<DialogueSegment>? segments,
  required TextStyle baseStyle,
  required TextStyle accentStyle,
}) {
  if (segments != null && segments.isNotEmpty) {
    return [
      for (final segment in segments)
        _StyledFragment(
          text: segment.text,
          style: segment.emphasized ? accentStyle : baseStyle,
        ),
    ];
  }

  final resolvedSource = source ?? '';
  final words =
      highlightedWords.toSet().where((word) => word.isNotEmpty).toList()
        ..sort((a, b) => b.length.compareTo(a.length));

  if (words.isEmpty) {
    return [_StyledFragment(text: resolvedSource, style: baseStyle)];
  }

  final fragments = <_StyledFragment>[];
  final buffer = StringBuffer();
  var index = 0;

  while (index < resolvedSource.length) {
    String? matched;
    for (final word in words) {
      if (resolvedSource.startsWith(word, index)) {
        matched = word;
        break;
      }
    }

    if (matched == null) {
      buffer.write(resolvedSource[index]);
      index += 1;
      continue;
    }

    if (buffer.isNotEmpty) {
      fragments.add(_StyledFragment(text: buffer.toString(), style: baseStyle));
      buffer.clear();
    }

    fragments.add(_StyledFragment(text: matched, style: accentStyle));
    index += matched.length;
  }

  if (buffer.isNotEmpty) {
    fragments.add(_StyledFragment(text: buffer.toString(), style: baseStyle));
  }

  return fragments;
}

/// [fragments]를 "페이지" 단위로 쪼갠다. 먼저 명시적으로 넣은 '\n'을
/// 문단 경계로 존중하고, 한 문단 안에 마침표/느낌표/물음표로 끝나는 문장이
/// 여러 개 섞여 있으면(백엔드가 여러 문장을 한 번에 내려주는 경우 등)
/// 문장 단위로 한 번 더 쪼갠다. 닫는 따옴표는 앞 문장에 붙여서 문장부호와
/// 따옴표가 서로 다른 페이지로 갈라지지 않게 한다.
List<List<_StyledFragment>> _splitFragmentsIntoPages(
  List<_StyledFragment> fragments,
) {
  final flatChars = <MapEntry<String, TextStyle>>[];
  for (final fragment in fragments) {
    for (final rune in fragment.text.runes) {
      flatChars.add(MapEntry(String.fromCharCode(rune), fragment.style));
    }
  }

  if (flatChars.isEmpty) {
    return [fragments];
  }

  const sentenceEnders = {'.', '!', '?'};
  const closingQuotes = {'"', '”', '’', "'"};

  final pages = <List<_StyledFragment>>[];
  var current = <_StyledFragment>[];
  final buffer = StringBuffer();
  TextStyle? bufferStyle;

  void flushBuffer() {
    if (buffer.isEmpty) return;
    current.add(_StyledFragment(text: buffer.toString(), style: bufferStyle!));
    buffer.clear();
  }

  void flushPage() {
    flushBuffer();
    if (current.isNotEmpty) {
      pages.add(current);
    }
    current = <_StyledFragment>[];
  }

  void writeChar(String char, TextStyle style) {
    if (bufferStyle != style) {
      flushBuffer();
      bufferStyle = style;
    }
    buffer.write(char);
  }

  for (var i = 0; i < flatChars.length; i++) {
    final entry = flatChars[i];
    final char = entry.key;

    if (char == '\n') {
      flushPage();
      continue;
    }

    writeChar(char, entry.value);

    if (sentenceEnders.contains(char)) {
      if (i + 1 < flatChars.length &&
          closingQuotes.contains(flatChars[i + 1].key)) {
        final next = flatChars[i + 1];
        writeChar(next.key, next.value);
        i += 1;
      }
      flushPage();
      while (i + 1 < flatChars.length && flatChars[i + 1].key == ' ') {
        i += 1;
      }
    }
  }
  flushPage();

  return pages.isEmpty ? [fragments] : pages;
}

/// [DialogueBubble.cyclePages]가 true일 때 문장을 하나씩 순서대로
/// 페이드 전환하며 보여주는 위젯. 위젯 자체가 (contentKey를 통해) 메시지가
/// 바뀔 때마다 새로 생성되므로, 매 메시지마다 자연스럽게 첫 문장부터 다시
/// 시작한다.
class _CyclingDialogueContent extends StatefulWidget {
  const _CyclingDialogueContent({
    super.key,
    required this.fragments,
    required this.baseStyle,
    required this.textAlign,
    required this.interval,
  });

  final List<_StyledFragment> fragments;
  final TextStyle baseStyle;
  final TextAlign textAlign;
  final Duration interval;

  @override
  State<_CyclingDialogueContent> createState() =>
      _CyclingDialogueContentState();
}

class _CyclingDialogueContentState extends State<_CyclingDialogueContent> {
  Timer? _timer;
  int _index = 0;
  late final List<List<_StyledFragment>> _pages = _splitFragmentsIntoPages(
    widget.fragments,
  );

  @override
  void initState() {
    super.initState();
    _scheduleTimer();
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  void _scheduleTimer() {
    _timer?.cancel();
    if (_pages.length <= 1) {
      return;
    }
    // 마지막 문장까지 보여준 뒤에는 멈춘다(처음으로 되돌아가 무한 반복하지
    // 않는다). 마지막 페이지에 도달하면 타이머 자체를 취소한다.
    _timer = Timer.periodic(widget.interval, (timer) {
      if (!mounted) {
        timer.cancel();
        return;
      }
      if (_index >= _pages.length - 1) {
        timer.cancel();
        return;
      }
      setState(() {
        _index += 1;
      });
    });
  }

  @override
  Widget build(BuildContext context) {
    final page = _pages.isEmpty
        ? const <_StyledFragment>[]
        : _pages[_index.clamp(0, _pages.length - 1)];

    return AnimatedSwitcher(
      duration: const Duration(milliseconds: 260),
      switchInCurve: Curves.easeOutCubic,
      switchOutCurve: Curves.easeInCubic,
      transitionBuilder: (child, animation) {
        return FadeTransition(opacity: animation, child: child);
      },
      child: _WordBoundaryTextLayout(
        key: ValueKey(_index),
        fragments: page,
        baseStyle: widget.baseStyle,
        textAlign: widget.textAlign,
      ),
    );
  }
}

class _WordBoundaryTextLayout extends StatelessWidget {
  const _WordBoundaryTextLayout({
    super.key,
    required this.fragments,
    required this.baseStyle,
    required this.textAlign,
  });

  final List<_StyledFragment> fragments;
  final TextStyle baseStyle;
  final TextAlign textAlign;

  @override
  Widget build(BuildContext context) {
    final paragraphs = _paragraphs();

    return Column(
      crossAxisAlignment: _crossAxisAlignmentFor(textAlign),
      children: [
        for (var index = 0; index < paragraphs.length; index++) ...[
          SizedBox(
            width: double.infinity,
            child: Wrap(
              alignment: _wrapAlignmentFor(textAlign),
              spacing: _spaceWidth,
              runSpacing: 0,
              children: [
                for (final token in paragraphs[index])
                  RichText(
                    softWrap: false,
                    textAlign: textAlign,
                    text: TextSpan(
                      style: baseStyle,
                      children: [
                        for (final fragment in token.fragments)
                          TextSpan(text: fragment.text, style: fragment.style),
                      ],
                    ),
                  ),
              ],
            ),
          ),
          if (index != paragraphs.length - 1)
            SizedBox(height: _paragraphSpacing),
        ],
      ],
    );
  }

  double get _spaceWidth => (baseStyle.fontSize ?? 16) * 0.28;

  double get _paragraphSpacing {
    final lineHeight = baseStyle.height ?? 1.3;
    return (baseStyle.fontSize ?? 16) * (lineHeight - 1).clamp(0.15, 0.45);
  }

  List<List<_StyledToken>> _paragraphs() {
    final paragraphs = <List<_StyledToken>>[];
    final currentParagraph = <_StyledToken>[];
    final currentToken = <_StyledFragment>[];

    void pushTokenPiece(String text, TextStyle style) {
      if (text.isEmpty) {
        return;
      }

      if (currentToken.isNotEmpty && currentToken.last.style == style) {
        final merged = currentToken.removeLast();
        currentToken.add(
          _StyledFragment(text: '${merged.text}$text', style: style),
        );
        return;
      }

      currentToken.add(_StyledFragment(text: text, style: style));
    }

    void flushToken() {
      if (currentToken.isEmpty) {
        return;
      }
      currentParagraph.add(
        _StyledToken(List<_StyledFragment>.from(currentToken)),
      );
      currentToken.clear();
    }

    void flushParagraph() {
      flushToken();
      paragraphs.add(List<_StyledToken>.from(currentParagraph));
      currentParagraph.clear();
    }

    for (final fragment in fragments) {
      for (final rune in fragment.text.runes) {
        final character = String.fromCharCode(rune);
        if (character == '\n') {
          flushParagraph();
          continue;
        }
        if (_isInlineWhitespace(character)) {
          flushToken();
          continue;
        }
        pushTokenPiece(character, fragment.style);
      }
    }

    if (currentToken.isNotEmpty ||
        currentParagraph.isNotEmpty ||
        paragraphs.isEmpty) {
      flushParagraph();
    }

    return paragraphs;
  }

  bool _isInlineWhitespace(String character) =>
      character == ' ' || character == '\t';

  WrapAlignment _wrapAlignmentFor(TextAlign align) {
    switch (align) {
      case TextAlign.center:
        return WrapAlignment.center;
      case TextAlign.right:
      case TextAlign.end:
        return WrapAlignment.end;
      case TextAlign.justify:
      case TextAlign.left:
      case TextAlign.start:
        return WrapAlignment.start;
    }
  }

  CrossAxisAlignment _crossAxisAlignmentFor(TextAlign align) {
    switch (align) {
      case TextAlign.center:
        return CrossAxisAlignment.center;
      case TextAlign.right:
      case TextAlign.end:
        return CrossAxisAlignment.end;
      case TextAlign.justify:
      case TextAlign.left:
      case TextAlign.start:
        return CrossAxisAlignment.start;
    }
  }
}

class _StyledFragment {
  const _StyledFragment({required this.text, required this.style});

  final String text;
  final TextStyle style;
}

class _StyledToken {
  const _StyledToken(this.fragments);

  final List<_StyledFragment> fragments;
}

class _BubbleContainer extends StatelessWidget {
  const _BubbleContainer({
    required this.child,
    required this.tail,
    required this.backgroundColor,
    required this.padding,
    required this.minHeight,
    required this.contentAlignment,
  });

  final Widget child;
  final DialogueBubbleTail tail;
  final Color backgroundColor;
  final EdgeInsets padding;
  final double? minHeight;
  final Alignment contentAlignment;

  @override
  Widget build(BuildContext context) {
    return Stack(
      clipBehavior: Clip.none,
      children: [
        Container(
          width: double.infinity,
          constraints: BoxConstraints(minHeight: minHeight ?? 0),
          padding: padding,
          decoration: AppSurfaceStyles.floatingCard(
            radius: AppRadii.xl,
            color: backgroundColor,
            boxShadow: AppSurfaceStyles.bubbleShadow,
          ),
          child: Align(alignment: contentAlignment, child: child),
        ),
        if (tail != DialogueBubbleTail.none)
          Positioned(
            bottom: -7,
            left: tail == DialogueBubbleTail.left ? 26 : null,
            right: tail == DialogueBubbleTail.right ? 26 : null,
            child: Transform.rotate(
              angle: 0.7853981633974483,
              child: Container(
                width: 16,
                height: 16,
                decoration: BoxDecoration(
                  color: backgroundColor,
                  boxShadow: AppSurfaceStyles.bubbleShadow,
                ),
              ),
            ),
          ),
      ],
    );
  }
}
