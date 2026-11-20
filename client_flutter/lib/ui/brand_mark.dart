import 'dart:math' as math;

import 'package:flutter/widgets.dart';

import 'brand_mark_geometry.dart';

class CorteBrandMark extends StatelessWidget {
  const CorteBrandMark({super.key, this.size = 28, this.monochrome});

  final double size;
  final Color? monochrome;

  @override
  Widget build(BuildContext context) => Semantics(
    label: 'CUTGC',
    image: true,
    child: SizedBox.square(
      dimension: size,
      child: CustomPaint(painter: _CorteBrandPainter(monochrome: monochrome)),
    ),
  );
}

class CorteBrandWordmark extends StatelessWidget {
  const CorteBrandWordmark({
    super.key,
    this.markSize = 28,
    this.gap = 9,
    this.showLabel = true,
    this.color = const Color(0xFFFFFFFF),
    this.labelSize = 20,
    this.monochrome,
  });

  final double markSize;

  /// Retained for existing callers. Spacing inside the signature follows the
  /// proportions of the traced master.
  final double gap;
  final bool showLabel;
  final Color color;
  final double labelSize;
  final Color? monochrome;

  @override
  Widget build(BuildContext context) {
    if (!showLabel) {
      return CorteBrandMark(size: markSize, monochrome: monochrome);
    }
    final scale = labelSize * .75 / corteWordmarkHeight;
    return Semantics(
      label: 'CUTGC',
      image: true,
      child: Align(
        alignment: AlignmentDirectional.centerStart,
        widthFactor: 1,
        heightFactor: 1,
        child: SizedBox(
          width: corteLogoWidth * scale,
          height: math.max(markSize, corteLogoHeight * scale),
          child: CustomPaint(
            painter: _CorteBrandPainter(
              monochrome: monochrome,
              wordmarkColor: color,
              scaleLimit: scale,
            ),
          ),
        ),
      ),
    );
  }
}

class _CorteBrandPainter extends CustomPainter {
  const _CorteBrandPainter({
    this.monochrome,
    this.wordmarkColor,
    this.scaleLimit = double.infinity,
  });

  final Color? monochrome;
  final Color? wordmarkColor;
  final double scaleLimit;

  @override
  void paint(Canvas canvas, Size size) {
    final wordmark = wordmarkColor;
    final width = wordmark == null ? corteMarkWidth : corteLogoWidth;
    final height = wordmark == null ? corteMarkHeight : corteLogoHeight;
    final scale = math.min(
      scaleLimit,
      math.min(size.width / width, size.height / height),
    );
    canvas.save();
    canvas.translate(
      (size.width - width * scale) / 2,
      (size.height - height * scale) / 2,
    );
    canvas.scale(scale);
    final paint = Paint();
    for (final (color, path) in corteMarkPaths) {
      canvas.drawPath(path, paint..color = monochrome ?? color);
    }
    if (wordmark != null) {
      canvas.translate(corteWordmarkX, corteWordmarkY);
      canvas.drawPath(corteWordmarkPath, paint..color = monochrome ?? wordmark);
    }
    canvas.restore();
  }

  @override
  bool shouldRepaint(_CorteBrandPainter oldDelegate) =>
      oldDelegate.monochrome != monochrome ||
      oldDelegate.wordmarkColor != wordmarkColor ||
      oldDelegate.scaleLimit != scaleLimit;
}
