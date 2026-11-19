import 'package:flutter/material.dart';

// Vector geometry from lucide-react 1.63.0, pinned by ui/package.json.
// The ISC and Feather MIT notices are bundled in assets/icons/LICENSE-Lucide.txt.
enum CorteIconName {
  house,
  package,
  store,
  chartColumn,
  squarePlay,
  shirt,
  search,
  logIn,
  logOut,
  refreshCw,
  settings,
  chevronDown,
  chevronLeft,
  chevronRight,
  ellipsis,
  arrowRight,
  circleAlert,
  circleCheckBig,
  circleHelp,
  x,
  menu,
}

/// A CUTGC Lucide icon. Supply a label only when the icon conveys meaning on
/// its own. An icon embedded in a labeled button is decorative.
class CorteIcon extends StatelessWidget {
  const CorteIcon(
    this.name, {
    super.key,
    this.size = 20,
    this.color,
    this.semanticLabel,
  });

  final CorteIconName name;
  final double size;
  final Color? color;
  final String? semanticLabel;

  @override
  Widget build(BuildContext context) {
    final theme = IconTheme.of(context);
    final tint =
        color ?? theme.color ?? Theme.of(context).colorScheme.onSurface;
    final opacity = theme.opacity ?? 1;
    final icon = Center(
      widthFactor: 1,
      heightFactor: 1,
      child: SizedBox.square(
        dimension: size,
        child: CustomPaint(
          painter: _LucidePainter(
            name,
            tint.withValues(alpha: tint.a * opacity),
            size <= 14 ? 2 : 1.75,
          ),
        ),
      ),
    );
    final label = semanticLabel;
    return label == null
        ? icon
        : Semantics(label: label, image: true, child: icon);
  }
}

class _LucidePainter extends CustomPainter {
  const _LucidePainter(this.name, this.color, this.strokeWidth);

  final CorteIconName name;
  final Color color;
  final double strokeWidth;

  @override
  void paint(Canvas canvas, Size size) {
    canvas.save();
    canvas.scale(size.width / 24, size.height / 24);
    canvas.drawPath(
      _lucidePaths[name]!,
      Paint()
        ..color = color
        ..style = PaintingStyle.stroke
        ..strokeWidth = strokeWidth
        ..strokeCap = StrokeCap.round
        ..strokeJoin = StrokeJoin.round,
    );
    canvas.restore();
  }

  @override
  bool shouldRepaint(_LucidePainter oldDelegate) =>
      name != oldDelegate.name ||
      color != oldDelegate.color ||
      strokeWidth != oldDelegate.strokeWidth;
}

extension on Path {
  void arc(
    double x,
    double y,
    double radius, {
    bool clockwise = true,
    bool largeArc = false,
  }) {
    arcToPoint(
      Offset(x, y),
      radius: Radius.circular(radius),
      clockwise: clockwise,
      largeArc: largeArc,
    );
  }
}

// Coordinates use the original SVG viewBox from 0 to 24.
final _lucidePaths = <CorteIconName, Path>{
  CorteIconName.house: Path()
    ..moveTo(15, 21)
    ..lineTo(15, 13)
    ..arc(14, 12, 1, clockwise: false)
    ..lineTo(10, 12)
    ..arc(9, 13, 1, clockwise: false)
    ..lineTo(9, 21)
    ..moveTo(3, 10)
    ..arc(3.709, 8.472, 2)
    ..lineTo(10.709, 2.472)
    ..arc(13.291, 2.472, 2)
    ..lineTo(20.291, 8.472)
    ..arc(21, 10, 2)
    ..lineTo(21, 19)
    ..arc(19, 21, 2)
    ..lineTo(5, 21)
    ..arc(3, 19, 2)
    ..close(),
  CorteIconName.package: Path()
    ..moveTo(11, 21.73)
    ..arc(13, 21.73, 2, clockwise: false)
    ..lineTo(20, 17.73)
    ..arc(21, 16, 2, clockwise: false)
    ..lineTo(21, 8)
    ..arc(20, 6.27, 2, clockwise: false)
    ..lineTo(13, 2.27)
    ..arc(11, 2.27, 2, clockwise: false)
    ..lineTo(4, 6.27)
    ..arc(3, 8, 2, clockwise: false)
    ..lineTo(3, 16)
    ..arc(4, 17.73, 2, clockwise: false)
    ..close()
    ..moveTo(12, 22)
    ..lineTo(12, 12)
    ..moveTo(3.29, 7)
    ..lineTo(12, 12)
    ..lineTo(20.71, 7)
    ..moveTo(7.5, 4.27)
    ..lineTo(16.5, 9.42),
  CorteIconName.store: Path()
    ..moveTo(15, 21)
    ..lineTo(15, 16)
    ..arc(14, 15, 1, clockwise: false)
    ..lineTo(10, 15)
    ..arc(9, 16, 1, clockwise: false)
    ..lineTo(9, 21)
    ..moveTo(17.774, 10.31)
    ..arc(16.225, 10.31, 1.12, clockwise: false)
    ..arc(12.774, 10.31, 2.5)
    ..arc(11.226, 10.31, 1.12, clockwise: false)
    ..arc(7.774, 10.31, 2.5)
    ..arc(6.225, 10.31, 1.12, clockwise: false)
    ..arc(2.455, 7.062, 2.5)
    ..lineTo(5.344, 2.878)
    ..arc(7, 2, 2)
    ..lineTo(17, 2)
    ..arc(18.653, 2.873, 2)
    ..lineTo(21.548, 7.065)
    ..arc(17.774, 10.309, 2.5)
    ..moveTo(4, 10.95)
    ..lineTo(4, 19)
    ..arc(6, 21, 2, clockwise: false)
    ..lineTo(18, 21)
    ..arc(20, 19, 2, clockwise: false)
    ..lineTo(20, 10.95),
  CorteIconName.chartColumn: Path()
    ..moveTo(3, 3)
    ..lineTo(3, 19)
    ..arc(5, 21, 2, clockwise: false)
    ..lineTo(21, 21)
    ..moveTo(18, 17)
    ..lineTo(18, 9)
    ..moveTo(13, 17)
    ..lineTo(13, 5)
    ..moveTo(8, 17)
    ..lineTo(8, 14),
  CorteIconName.squarePlay: Path()
    ..addRRect(
      RRect.fromRectAndRadius(Rect.fromLTWH(3, 3, 18, 18), Radius.circular(2)),
    )
    ..moveTo(9, 9.003)
    ..arc(10.517, 8.144, 1)
    ..lineTo(15.514, 11.141)
    ..arc(15.514, 12.859, 1)
    ..lineTo(10.517, 15.856)
    ..arc(9, 14.996, 1)
    ..close(),
  CorteIconName.shirt: Path()
    ..moveTo(20.38, 3.46)
    ..lineTo(16, 2)
    ..arc(8, 2, 4)
    ..lineTo(3.62, 3.46)
    ..arc(2.28, 5.69, 2, clockwise: false)
    ..lineTo(2.86, 9.16)
    ..arc(3.85, 10, 1, clockwise: false)
    ..lineTo(6, 10)
    ..lineTo(6, 20)
    ..cubicTo(6, 21.1, 6.9, 22, 8, 22)
    ..lineTo(16, 22)
    ..arc(18, 20, 2, clockwise: false)
    ..lineTo(18, 10)
    ..lineTo(20.15, 10)
    ..arc(21.14, 9.16, 1, clockwise: false)
    ..lineTo(21.72, 5.69)
    ..arc(20.38, 3.46, 2, clockwise: false)
    ..close(),
  CorteIconName.search: Path()
    ..moveTo(21, 21)
    ..lineTo(16.66, 16.66)
    ..addOval(Rect.fromCircle(center: Offset(11, 11), radius: 8)),
  CorteIconName.logIn: Path()
    ..moveTo(10, 17)
    ..lineTo(15, 12)
    ..lineTo(10, 7)
    ..moveTo(15, 12)
    ..lineTo(3, 12)
    ..moveTo(15, 3)
    ..lineTo(19, 3)
    ..arc(21, 5, 2)
    ..lineTo(21, 19)
    ..arc(19, 21, 2)
    ..lineTo(15, 21),
  CorteIconName.logOut: Path()
    ..moveTo(16, 17)
    ..lineTo(21, 12)
    ..lineTo(16, 7)
    ..moveTo(21, 12)
    ..lineTo(9, 12)
    ..moveTo(9, 21)
    ..lineTo(5, 21)
    ..arc(3, 19, 2)
    ..lineTo(3, 5)
    ..arc(5, 3, 2)
    ..lineTo(9, 3),
  CorteIconName.refreshCw: Path()
    ..moveTo(3, 12)
    ..arc(12, 3, 9)
    ..arc(18.74, 5.74, 9.75)
    ..lineTo(21, 8)
    ..moveTo(21, 3)
    ..lineTo(21, 8)
    ..lineTo(16, 8)
    ..moveTo(21, 12)
    ..arc(12, 21, 9)
    ..arc(5.26, 18.26, 9.75)
    ..lineTo(3, 16)
    ..moveTo(8, 16)
    ..lineTo(3, 16)
    ..lineTo(3, 21),
  CorteIconName.settings: Path()
    ..moveTo(9.671, 4.136)
    ..arc(14.33, 4.136, 2.34)
    ..arc(17.649, 6.051, 2.34, clockwise: false)
    ..arc(19.979, 10.084, 2.34)
    ..arc(19.979, 13.915, 2.34, clockwise: false)
    ..arc(17.649, 17.948, 2.34)
    ..arc(14.33, 19.863, 2.34, clockwise: false)
    ..arc(9.671, 19.863, 2.34)
    ..arc(6.351, 17.948, 2.34, clockwise: false)
    ..arc(4.021, 13.915, 2.34)
    ..arc(4.021, 10.084, 2.34, clockwise: false)
    ..arc(6.35, 6.051, 2.34)
    ..arc(9.669, 4.136, 2.34, clockwise: false)
    ..addOval(Rect.fromCircle(center: Offset(12, 12), radius: 3)),
  CorteIconName.chevronDown: Path()
    ..moveTo(6, 9)
    ..lineTo(12, 15)
    ..lineTo(18, 9),
  CorteIconName.chevronLeft: Path()
    ..moveTo(15, 18)
    ..lineTo(9, 12)
    ..lineTo(15, 6),
  CorteIconName.chevronRight: Path()
    ..moveTo(9, 18)
    ..lineTo(15, 12)
    ..lineTo(9, 6),
  CorteIconName.ellipsis: Path()
    ..addOval(Rect.fromCircle(center: Offset(12, 12), radius: 1))
    ..addOval(Rect.fromCircle(center: Offset(19, 12), radius: 1))
    ..addOval(Rect.fromCircle(center: Offset(5, 12), radius: 1)),
  CorteIconName.arrowRight: Path()
    ..moveTo(5, 12)
    ..lineTo(19, 12)
    ..moveTo(12, 5)
    ..lineTo(19, 12)
    ..lineTo(12, 19),
  CorteIconName.circleAlert: Path()
    ..addOval(Rect.fromCircle(center: Offset(12, 12), radius: 10))
    ..moveTo(12, 8)
    ..lineTo(12, 12)
    ..moveTo(12, 16)
    ..lineTo(12.01, 16),
  CorteIconName.circleCheckBig: Path()
    ..moveTo(21.801, 10)
    ..arc(17, 3.335, 10, largeArc: true)
    ..moveTo(9, 11)
    ..lineTo(12, 14)
    ..lineTo(22, 4),
  CorteIconName.circleHelp: Path()
    ..addOval(Rect.fromCircle(center: Offset(12, 12), radius: 10))
    ..moveTo(9.09, 9)
    ..arc(14.92, 10, 3)
    ..cubicTo(14.92, 12, 11.92, 13, 11.92, 13)
    ..moveTo(12, 17)
    ..lineTo(12.01, 17),
  CorteIconName.x: Path()
    ..moveTo(18, 6)
    ..lineTo(6, 18)
    ..moveTo(6, 6)
    ..lineTo(18, 18),
  CorteIconName.menu: Path()
    ..moveTo(4, 5)
    ..lineTo(20, 5)
    ..moveTo(4, 12)
    ..lineTo(20, 12)
    ..moveTo(4, 19)
    ..lineTo(20, 19),
};
