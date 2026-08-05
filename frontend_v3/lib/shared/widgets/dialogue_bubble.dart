import 'package:flutter/material.dart';

import '../../app/theme/app_colors.dart';
import '../../app/theme/app_radii.dart';
import '../../app/theme/app_spacing.dart';
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
    this.backgroundColor = AppColors.surface,
    this.borderColor = AppColors.border,
    this.padding = const EdgeInsets.all(AppSpacing.lg),
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
  final Color borderColor;
  final EdgeInsets padding;

  @override
  Widget build(BuildContext context) {
    final body = _BubbleContainer(
      tail: tail,
      backgroundColor: backgroundColor,
      borderColor: borderColor,
      padding: padding,
      child: animateTextChanges
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
            ),
    );

    return body;
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

    return RichText(
      textAlign: textAlign,
      text: TextSpan(
        style: baseStyle,
        children: _spans(
          source: text,
          highlightedWords: highlightedWords,
          segments: segments,
          baseStyle: baseStyle,
          accentStyle: accentStyle,
        ),
      ),
    );
  }

  List<TextSpan> _spans({
    required String? source,
    required List<String> highlightedWords,
    required List<DialogueSegment>? segments,
    required TextStyle baseStyle,
    required TextStyle accentStyle,
  }) {
    if (segments != null && segments.isNotEmpty) {
      return [
        for (final segment in segments)
          TextSpan(
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
      return [TextSpan(text: resolvedSource, style: baseStyle)];
    }

    final spans = <TextSpan>[];
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
        spans.add(TextSpan(text: buffer.toString(), style: baseStyle));
        buffer.clear();
      }

      spans.add(TextSpan(text: matched, style: accentStyle));
      index += matched.length;
    }

    if (buffer.isNotEmpty) {
      spans.add(TextSpan(text: buffer.toString(), style: baseStyle));
    }

    return spans;
  }
}

class _BubbleContainer extends StatelessWidget {
  const _BubbleContainer({
    required this.child,
    required this.tail,
    required this.backgroundColor,
    required this.borderColor,
    required this.padding,
  });

  final Widget child;
  final DialogueBubbleTail tail;
  final Color backgroundColor;
  final Color borderColor;
  final EdgeInsets padding;

  @override
  Widget build(BuildContext context) {
    return Stack(
      clipBehavior: Clip.none,
      children: [
        Container(
          width: double.infinity,
          padding: padding,
          decoration: BoxDecoration(
            color: backgroundColor,
            borderRadius: BorderRadius.circular(AppRadii.xl),
            border: Border.all(color: borderColor),
            boxShadow: const [
              BoxShadow(
                color: AppColors.shadow,
                blurRadius: 18,
                offset: Offset(0, 10),
              ),
            ],
          ),
          child: child,
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
                  border: Border(
                    right: BorderSide(color: borderColor),
                    bottom: BorderSide(color: borderColor),
                  ),
                ),
              ),
            ),
          ),
      ],
    );
  }
}
