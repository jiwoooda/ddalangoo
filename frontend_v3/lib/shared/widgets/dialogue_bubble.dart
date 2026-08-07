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
  final Color backgroundColor;
  final Color? borderColor;
  final EdgeInsets padding;
  final double? minHeight;
  final bool scrollableContent;
  final Alignment contentAlignment;

  @override
  Widget build(BuildContext context) {
    final content = animateTextChanges
        ? AnimatedSwitcher(
            duration: const Duration(milliseconds: 260),
            switchInCurve: Curves.easeOutCubic,
            switchOutCurve: Curves.easeInCubic,
            transitionBuilder: (child, animation) {
              return FadeTransition(opacity: animation, child: child);
            },
            child: _DialogueText(
              key: contentKey,
              text: text,
              highlightedWords: highlightedWords,
              segments: segments,
              textAlign: textAlign,
              style: style,
              emphasizedStyle: emphasizedStyle,
            ),
          )
        : _DialogueText(
            key: contentKey,
            text: text,
            highlightedWords: highlightedWords,
            segments: segments,
            textAlign: textAlign,
            style: style,
            emphasizedStyle: emphasizedStyle,
          );

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

class _DialogueText extends StatelessWidget {
  const _DialogueText({
    super.key,
    required this.text,
    required this.highlightedWords,
    required this.segments,
    required this.textAlign,
    required this.style,
    required this.emphasizedStyle,
  });

  final String? text;
  final List<String> highlightedWords;
  final List<DialogueSegment>? segments;
  final TextAlign textAlign;
  final TextStyle? style;
  final TextStyle? emphasizedStyle;

  @override
  Widget build(BuildContext context) {
    final baseStyle = style ?? AppTextStyles.body1;
    final accentStyle =
        emphasizedStyle ??
        baseStyle.copyWith(
          color: AppColors.primaryPinkDark,
          fontWeight: FontWeight.w800,
        );

    final fragments = _fragments(
      source: text,
      highlightedWords: highlightedWords,
      segments: segments,
      baseStyle: baseStyle,
      accentStyle: accentStyle,
    );

    return _WordBoundaryTextLayout(
      fragments: fragments,
      baseStyle: baseStyle,
      textAlign: textAlign,
    );
  }

  List<_StyledFragment> _fragments({
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
        fragments.add(
          _StyledFragment(text: buffer.toString(), style: baseStyle),
        );
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
}

class _WordBoundaryTextLayout extends StatelessWidget {
  const _WordBoundaryTextLayout({
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
