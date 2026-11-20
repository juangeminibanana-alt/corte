import 'dart:math' as math;

import 'package:flutter/material.dart';

import 'brand_mark_geometry.dart';
import 'theme.dart';

/// One entrance per authenticated shell. The navigable workspace is mounted
/// below the artwork from the first frame.
class CorteStudioEntrance extends StatefulWidget {
  const CorteStudioEntrance({
    super.key,
    required this.child,
    this.ready = true,
    this.enabled = true,
  });

  final Widget child;
  final bool ready;
  final bool enabled;

  @override
  State<CorteStudioEntrance> createState() => _CorteStudioEntranceState();
}

class _CorteStudioEntranceState extends State<CorteStudioEntrance>
    with SingleTickerProviderStateMixin {
  late final AnimationController _animation = AnimationController(
    vsync: this,
    duration: CorteMotion.intro,
  );
  bool _started = false;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _playWhenReady();
  }

  @override
  void didUpdateWidget(CorteStudioEntrance oldWidget) {
    super.didUpdateWidget(oldWidget);
    _playWhenReady();
  }

  void _playWhenReady() {
    if (!widget.enabled || CorteMotion.reducedOf(context)) {
      _animation.value = 1;
      _started = true;
    } else if (widget.ready && !_started) {
      _started = true;
      _animation.forward();
    }
  }

  @override
  void dispose() {
    _animation.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
    animation: _animation,
    child: widget.child,
    builder: (context, child) {
      return Stack(
        fit: StackFit.expand,
        children: [
          child!,
          if (_started && !_animation.isCompleted && widget.enabled)
            Positioned.fill(
              child: IgnorePointer(
                child: ExcludeSemantics(
                  child: CustomPaint(
                    key: const ValueKey('studio-entry-artwork'),
                    painter: _StudioEntryPainter(_animation.value),
                  ),
                ),
              ),
            ),
        ],
      );
    },
  );
}

class _StudioEntryPainter extends CustomPainter {
  const _StudioEntryPainter(this.progress);

  final double progress;

  @override
  void paint(Canvas canvas, Size size) {
    double animation(double begin, double end, Curve curve) =>
        curve.transform(((progress - begin) / (end - begin)).clamp(0.0, 1.0));
    final entry = animation(0, .39, Curves.easeOutCubic);
    final lettering = animation(.25, .49, Curves.easeOutCubic);
    final exit = animation(.64, 1, Curves.easeInOutCubic);
    final width = math.min(size.width * .53, 320.0);
    final scale = width / corteLogoWidth;
    final height = corteLogoHeight * scale;
    final slope = size.height * .32;
    final edge = -slope + exit * (size.width + slope);
    final paint = Paint();
    canvas.save();
    canvas.clipPath(
      Path()
        ..moveTo(edge + slope, 0)
        ..lineTo(size.width, 0)
        ..lineTo(size.width, size.height)
        ..lineTo(edge, size.height)
        ..close(),
    );
    canvas.drawRect(Offset.zero & size, paint..color = CorteColors.chrome);
    canvas.translate((size.width - width) / 2, (size.height - height) / 2);
    canvas.scale(scale);
    for (final (index, item) in corteMarkPaths.indexed) {
      final (color, path) = item;
      final direction = index == 0 ? -1 : 1;
      canvas.save();
      canvas.translate(direction * (1 - entry) * (size.width / scale) * .37, 0);
      canvas.drawPath(path, paint..color = color);
      canvas.restore();
    }
    canvas.clipRect(
      Rect.fromLTWH(
        corteWordmarkX,
        corteWordmarkY + corteWordmarkHeight * (1 - lettering),
        corteWordmarkWidth,
        corteWordmarkHeight * lettering,
      ),
    );
    canvas.translate(corteWordmarkX, corteWordmarkY);
    canvas.drawPath(corteWordmarkPath, paint..color = CorteColors.onAction);
    canvas.restore();
  }

  @override
  bool shouldRepaint(_StudioEntryPainter oldDelegate) =>
      oldDelegate.progress != progress;
}
