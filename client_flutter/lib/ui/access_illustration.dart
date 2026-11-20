import 'dart:math' as math;

import 'package:flutter/material.dart';

import 'brand_mark.dart';
import 'brand_mark_geometry.dart';
import 'theme.dart';

class CorteAccessIllustration extends StatelessWidget {
  const CorteAccessIllustration({super.key, required this.dark});

  final bool dark;

  @override
  Widget build(BuildContext context) {
    final reducedMotion = CorteMotion.reducedOf(context);
    final color = dark
        ? CorteColors.chromeInk.withValues(alpha: .88)
        : context.corte.ink.withValues(alpha: .85);
    return ExcludeSemantics(
      child: IgnorePointer(
        child: LayoutBuilder(
          builder: (context, limits) {
            final canvasSize = Size(limits.maxWidth, limits.maxHeight);
            final frame = _accessFrame(canvasSize, dark);
            // The viewfinder shows a taller editorial crop of the same mark
            // used in the compact wordmark above it.
            final zoomY = dark ? 1.25 : 1.17;
            final markAspect = corteMarkHeight / corteMarkWidth * zoomY;
            final markSize = math.min(
              frame.width * (dark ? .82 : .67),
              frame.height * (dark ? .72 : .68) / markAspect,
            );
            return CustomPaint(
              painter: _FramingMarks(color, large: dark),
              child: Center(
                child: TweenAnimationBuilder<double>(
                  tween: Tween(begin: reducedMotion ? 1 : 0, end: 1),
                  duration: reducedMotion ? Duration.zero : CorteMotion.intro,
                  curve: CorteMotion.enter,
                  builder: (context, value, child) => Opacity(
                    opacity: .72 + .28 * value,
                    child: Transform.translate(
                      offset: Offset(
                        8 * (1 - value),
                        (dark ? 8 : 2) + 4 * (1 - value),
                      ),
                      child: Transform.scale(
                        scale: .94 + .06 * value,
                        child: child,
                      ),
                    ),
                  ),
                  child: Transform.scale(
                    scaleX: 1,
                    scaleY: zoomY,
                    child: CorteBrandMark(size: markSize),
                  ),
                ),
              ),
            );
          },
        ),
      ),
    );
  }
}

Rect _accessFrame(Size size, bool large) {
  final horizontalInset = size.width * (large ? .025 : .09);
  final verticalInset = size.height * (large ? .055 : .09);
  return Rect.fromLTRB(
    horizontalInset,
    verticalInset,
    size.width - horizontalInset,
    size.height - verticalInset,
  );
}

class CorteAccessTimeline extends StatelessWidget {
  const CorteAccessTimeline({super.key});

  @override
  Widget build(BuildContext context) => const ExcludeSemantics(
    child: IgnorePointer(
      child: SizedBox(
        width: double.infinity,
        height: 34,
        child: CustomPaint(painter: _TimelineTicks()),
      ),
    ),
  );
}

class _FramingMarks extends CustomPainter {
  const _FramingMarks(this.color, {required this.large});
  final Color color;
  final bool large;

  @override
  void paint(Canvas canvas, Size size) {
    final frame = _accessFrame(size, large);
    final corner = frame.height * .093;
    final crosshair = frame.height * .031;
    final paint = Paint()
      ..color = color
      ..strokeWidth = large ? 2.6 : 1.5
      ..style = PaintingStyle.stroke;

    for (final (point, x, y) in [
      (frame.topLeft, 1, 1),
      (frame.topRight, -1, 1),
      (frame.bottomLeft, 1, -1),
      (frame.bottomRight, -1, -1),
    ]) {
      canvas.drawPath(
        Path()
          ..moveTo(point.dx + x * corner, point.dy)
          ..lineTo(point.dx, point.dy)
          ..lineTo(point.dx, point.dy + y * corner),
        paint,
      );
    }
    paint.strokeWidth = large ? 1.7 : 1.2;
    for (final y in [frame.top + 2, frame.bottom - 2]) {
      canvas.drawLine(
        Offset(frame.center.dx - crosshair, y),
        Offset(frame.center.dx + crosshair, y),
        paint,
      );
      canvas.drawLine(
        Offset(frame.center.dx, y - crosshair),
        Offset(frame.center.dx, y + crosshair),
        paint,
      );
    }
    for (var i = 0; i < 6; i++) {
      final y = frame.top + frame.height * (.29 + .084 * i);
      canvas.drawLine(
        Offset(frame.left, y),
        Offset(frame.left + crosshair, y),
        paint,
      );
      canvas.drawLine(
        Offset(frame.right - crosshair, y),
        Offset(frame.right, y),
        paint,
      );
    }
  }

  @override
  bool shouldRepaint(covariant _FramingMarks oldDelegate) =>
      color != oldDelegate.color || large != oldDelegate.large;
}

class _TimelineTicks extends CustomPainter {
  const _TimelineTicks();

  @override
  void paint(Canvas canvas, Size size) {
    final y = size.height / 2;
    final paint = Paint()
      ..strokeWidth = 1.5
      ..color = CorteColors.chromeInk.withValues(alpha: .92);
    canvas.drawPath(
      Path()
        ..moveTo(0, y - 12)
        ..lineTo(23, y)
        ..lineTo(0, y + 12)
        ..close(),
      paint,
    );
    const start = 45.0;
    for (var i = 0; i <= 14; i++) {
      final x = start + (size.width - start - 1) * i / 14;
      final tick = i % 7 == 0 ? 14.0 : 4.5;
      canvas.drawLine(Offset(x, y - tick), Offset(x, y + tick), paint);
    }
  }

  @override
  bool shouldRepaint(covariant _TimelineTicks oldDelegate) => false;
}

/// Matches the Google sign-in vector used by the web client.
class CorteGoogleMark extends StatelessWidget {
  const CorteGoogleMark({super.key});

  @override
  Widget build(BuildContext context) => const SizedBox.square(
    dimension: 20,
    child: CustomPaint(painter: _GoogleMarkPainter()),
  );
}

class _GoogleMarkPainter extends CustomPainter {
  const _GoogleMarkPainter();

  static final _paths = <(Color, Path)>[
    (
      const Color(0xFF4285F4),
      Path()
        ..moveTo(43.6, 24.5)
        ..relativeCubicTo(0, -1.5, -.1, -2.9, -.4, -4.3)
        ..lineTo(24, 20.2)
        ..relativeLineTo(0, 8.2)
        ..relativeLineTo(11, 0)
        ..relativeCubicTo(-.5, 2.6, -1.9, 4.7, -4.1, 6.2)
        ..relativeLineTo(0, 5.1)
        ..relativeLineTo(6.6, 0)
        ..relativeCubicTo(3.9, -3.6, 6.1, -8.9, 6.1, -15.2)
        ..close(),
    ),
    (
      const Color(0xFF34A853),
      Path()
        ..moveTo(24, 44)
        ..relativeCubicTo(5.5, 0, 10.1, -1.8, 13.5, -4.9)
        ..relativeLineTo(-6.6, -5.1)
        ..relativeCubicTo(-1.8, 1.2, -4.1, 1.9, -6.9, 1.9)
        ..relativeCubicTo(-5.3, 0, -9.8, -3.6, -11.4, -8.4)
        ..lineTo(5.8, 27.5)
        ..relativeLineTo(0, 5.3)
        ..cubicTo(9.2, 39.5, 16.1, 44, 24, 44)
        ..close(),
    ),
    (
      const Color(0xFFFBBC05),
      Path()
        ..moveTo(12.6, 27.5)
        ..relativeArcToPoint(
          const Offset(0, -7),
          radius: const Radius.circular(12),
        )
        ..lineTo(12.6, 15.2)
        ..lineTo(5.8, 15.2)
        ..relativeArcToPoint(
          const Offset(0, 17.6),
          radius: const Radius.circular(20),
          clockwise: false,
        )
        ..relativeLineTo(6.8, -5.3)
        ..close(),
    ),
    (
      const Color(0xFFEA4335),
      Path()
        ..moveTo(24, 12.1)
        ..relativeCubicTo(3, 0, 5.6, 1, 7.7, 3)
        ..relativeLineTo(5.8, -5.8)
        ..arcToPoint(
          const Offset(24, 4),
          radius: const Radius.circular(19.3),
          clockwise: false,
        )
        ..cubicTo(16.1, 4, 9.2, 8.5, 5.8, 15.2)
        ..relativeLineTo(6.8, 5.3)
        ..relativeCubicTo(1.6, -4.8, 6.1, -8.4, 11.4, -8.4)
        ..close(),
    ),
  ];

  @override
  void paint(Canvas canvas, Size size) {
    canvas.scale(size.width / 48, size.height / 48);
    final paint = Paint();
    for (final (color, path) in _paths) {
      canvas.drawPath(path, paint..color = color);
    }
  }

  @override
  bool shouldRepaint(covariant _GoogleMarkPainter oldDelegate) => false;
}
