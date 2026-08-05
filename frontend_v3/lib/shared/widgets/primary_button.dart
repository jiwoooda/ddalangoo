import 'package:flutter/material.dart';

import '../../app/theme/app_sizes.dart';

class PrimaryButton extends StatelessWidget {
  const PrimaryButton({
    super.key,
    required this.label,
    this.onPressed,
    this.icon,
    this.expand = true,
  });

  final String label;
  final VoidCallback? onPressed;
  final IconData? icon;
  final bool expand;

  @override
  Widget build(BuildContext context) {
    final button = FilledButton.icon(
      onPressed: onPressed,
      icon: icon == null ? const SizedBox.shrink() : Icon(icon),
      label: Text(label),
    );

    return SizedBox(
      width: expand ? double.infinity : null,
      height: AppSizes.buttonHeight,
      child: icon == null
          ? FilledButton(onPressed: onPressed, child: Text(label))
          : button,
    );
  }
}
