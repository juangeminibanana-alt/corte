import 'package:flutter/material.dart';

abstract final class CorteColors {
  static const ink = Color(0xFF161823);
  static const muted = Color(0xFF62636F);
  static const chrome = Color(0xFF08090B);
  static const chromeMuted = Color(0xFFB9BAC2);
  static const coral = Color(0xFFFE2C55);
  static const action = Color(0xFFE31C48);
  static const cyan = Color(0xFF25F4EE);
  static const cyanInk = Color(0xFF007D84);
  static const line = Color(0xFFE9E9EE);
  static const soft = Color(0xFFF6F6F8);
  static const rose = Color(0xFFFFEDF2);
}

ThemeData corteTheme() => ThemeData(
  useMaterial3: true,
  brightness: Brightness.light,
  fontFamily: 'MonaSans',
  scaffoldBackgroundColor: Colors.white,
  colorScheme: ColorScheme.fromSeed(seedColor: CorteColors.action).copyWith(
    primary: CorteColors.action,
    secondary: CorteColors.cyanInk,
    surface: Colors.white,
    onSurface: CorteColors.ink,
    outline: CorteColors.line,
  ),
  textTheme: const TextTheme(
    headlineLarge: TextStyle(
      fontSize: 36,
      height: 1.15,
      fontWeight: FontWeight.w800,
      letterSpacing: -1.1,
    ),
    headlineMedium: TextStyle(
      fontSize: 25,
      height: 1.2,
      fontWeight: FontWeight.w800,
      letterSpacing: -.65,
    ),
    titleLarge: TextStyle(
      fontSize: 20,
      height: 1.3,
      fontWeight: FontWeight.w700,
    ),
    titleMedium: TextStyle(
      fontSize: 16,
      height: 1.35,
      fontWeight: FontWeight.w700,
    ),
    bodyLarge: TextStyle(fontSize: 16, height: 1.5),
    bodyMedium: TextStyle(fontSize: 14, height: 1.5),
    bodySmall: TextStyle(fontSize: 12, height: 1.4, color: CorteColors.muted),
  ).apply(bodyColor: CorteColors.ink, displayColor: CorteColors.ink),
  dividerTheme: const DividerThemeData(
    color: CorteColors.line,
    thickness: 1,
    space: 1,
  ),
  filledButtonTheme: FilledButtonThemeData(
    style: FilledButton.styleFrom(
      backgroundColor: CorteColors.action,
      foregroundColor: Colors.white,
      minimumSize: const Size(44, 46),
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
      textStyle: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
    ),
  ),
  outlinedButtonTheme: OutlinedButtonThemeData(
    style: OutlinedButton.styleFrom(
      foregroundColor: CorteColors.action,
      minimumSize: const Size(44, 42),
      side: const BorderSide(color: CorteColors.coral),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(7)),
      textStyle: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600),
    ),
  ),
  inputDecorationTheme: InputDecorationTheme(
    filled: true,
    fillColor: CorteColors.soft,
    contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 13),
    border: OutlineInputBorder(
      borderRadius: BorderRadius.circular(8),
      borderSide: const BorderSide(color: CorteColors.line),
    ),
    enabledBorder: OutlineInputBorder(
      borderRadius: BorderRadius.circular(8),
      borderSide: const BorderSide(color: CorteColors.line),
    ),
    focusedBorder: OutlineInputBorder(
      borderRadius: BorderRadius.circular(8),
      borderSide: const BorderSide(color: CorteColors.action, width: 2),
    ),
  ),
  snackBarTheme: const SnackBarThemeData(behavior: SnackBarBehavior.floating),
  dialogTheme: DialogThemeData(
    backgroundColor: Colors.white,
    surfaceTintColor: Colors.transparent,
    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
  ),
  datePickerTheme: DatePickerThemeData(
    backgroundColor: Colors.white,
    surfaceTintColor: Colors.transparent,
    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
  ),
  menuTheme: MenuThemeData(style: MenuStyle(
    backgroundColor: const WidgetStatePropertyAll(Colors.white),
    surfaceTintColor: const WidgetStatePropertyAll(Colors.transparent),
    shape: WidgetStatePropertyAll(RoundedRectangleBorder(borderRadius: BorderRadius.circular(8))),
  )),
);

class CorteMark extends StatelessWidget {
  const CorteMark({super.key, this.size = 28});
  final double size;
  @override
  Widget build(BuildContext context) => Semantics(
    label: 'Corte',
    child: SizedBox.square(
      dimension: size,
      child: CustomPaint(painter: _MarkPainter()),
    ),
  );
}

class _MarkPainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    canvas.scale(size.width / 40, size.height / 40);
    final paint = Paint()
      ..strokeWidth = 7
      ..strokeCap = StrokeCap.round;
    canvas.drawLine(
      const Offset(5, 32),
      const Offset(22, 8),
      paint..color = CorteColors.coral,
    );
    canvas.drawLine(
      const Offset(18, 32),
      const Offset(35, 8),
      paint..color = CorteColors.cyan,
    );
  }

  @override
  bool shouldRepaint(_MarkPainter oldDelegate) => false;
}
