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

/// Semantic content colors. Brand chrome and photo overlays keep their own
/// fixed colors; content follows the selected Material brightness.
class CortePalette {
  const CortePalette({this.isDark = false});
  final bool isDark;
  Color get surface => isDark ? const Color(0xFF15161B) : Colors.white;
  Color get ink => isDark ? const Color(0xFFF5F5F7) : CorteColors.ink;
  Color get muted => isDark ? const Color(0xFFB4B6C2) : CorteColors.muted;
  Color get line => isDark ? const Color(0xFF363842) : CorteColors.line;
  Color get soft => isDark ? const Color(0xFF202229) : CorteColors.soft;
  Color get rose => isDark ? const Color(0xFF35202A) : CorteColors.rose;
  Color get action =>
      isDark ? const Color(0xFFFF6687) : const Color(0xFFCE1640);
  Color get cyanInk => isDark ? CorteColors.cyan : const Color(0xFF00737A);
  Color get success =>
      isDark ? const Color(0xFF83DBAB) : const Color(0xFF26724D);
  Color get danger =>
      isDark ? const Color(0xFFFF9BA8) : const Color(0xFFBC3446);
  Color get warning =>
      isDark ? const Color(0xFFFFD184) : const Color(0xFF805300);
}

extension CorteThemeContext on BuildContext {
  CortePalette get corte =>
      CortePalette(isDark: Theme.of(this).brightness == Brightness.dark);
}

ThemeData corteTheme({Brightness brightness = Brightness.light}) {
  final colors = CortePalette(isDark: brightness == Brightness.dark);
  final scheme =
      ColorScheme.fromSeed(
        seedColor: CorteColors.action,
        brightness: brightness,
      ).copyWith(
        primary: colors.action,
        onPrimary: colors.isDark ? CorteColors.chrome : Colors.white,
        primaryContainer: colors.rose,
        onPrimaryContainer: colors.ink,
        secondary: colors.cyanInk,
        onSecondary: colors.isDark ? CorteColors.chrome : Colors.white,
        secondaryContainer: colors.soft,
        onSecondaryContainer: colors.ink,
        surface: colors.surface,
        onSurface: colors.ink,
        onSurfaceVariant: colors.muted,
        surfaceContainerLowest: colors.surface,
        surfaceContainerLow: colors.surface,
        surfaceContainer: colors.soft,
        surfaceContainerHigh: colors.soft,
        surfaceContainerHighest: colors.soft,
        outline: colors.muted,
        outlineVariant: colors.line,
        error: colors.danger,
        onError: colors.isDark ? CorteColors.chrome : Colors.white,
        errorContainer: colors.rose,
        onErrorContainer: colors.danger,
        surfaceTint: Colors.transparent,
      );
  return ThemeData(
    useMaterial3: true,
    brightness: brightness,
    fontFamily: 'MonaSans',
    scaffoldBackgroundColor: colors.surface,
    canvasColor: colors.surface,
    colorScheme: scheme,
    iconTheme: IconThemeData(color: colors.ink),
    textSelectionTheme: TextSelectionThemeData(
      cursorColor: colors.action,
      selectionColor: colors.action.withValues(alpha: .28),
      selectionHandleColor: colors.action,
    ),
    textTheme: TextTheme(
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
      bodySmall: TextStyle(fontSize: 12, height: 1.4, color: colors.muted),
    ).apply(bodyColor: colors.ink, displayColor: colors.ink),
    dividerTheme: DividerThemeData(color: colors.line, thickness: 1, space: 1),
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
        foregroundColor: colors.action,
        minimumSize: const Size(44, 42),
        side: BorderSide(color: colors.action),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(7)),
        textStyle: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600),
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: colors.soft,
      hintStyle: TextStyle(color: colors.muted),
      labelStyle: TextStyle(color: colors.muted),
      contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 13),
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(8),
        borderSide: BorderSide(color: colors.line),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(8),
        borderSide: BorderSide(color: colors.line),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(8),
        borderSide: BorderSide(color: colors.action, width: 2),
      ),
    ),
    snackBarTheme: const SnackBarThemeData(behavior: SnackBarBehavior.floating),
    dialogTheme: DialogThemeData(
      backgroundColor: colors.surface,
      surfaceTintColor: Colors.transparent,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
    ),
    datePickerTheme: DatePickerThemeData(
      backgroundColor: colors.surface,
      surfaceTintColor: Colors.transparent,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
    ),
    menuTheme: MenuThemeData(
      style: MenuStyle(
        backgroundColor: WidgetStatePropertyAll(colors.surface),
        surfaceTintColor: const WidgetStatePropertyAll(Colors.transparent),
        shape: WidgetStatePropertyAll(
          RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
        ),
      ),
    ),
  );
}

class CorteWordmark extends StatelessWidget {
  const CorteWordmark({
    super.key,
    this.markSize = 28,
    this.gap = 9,
    this.showLabel = true,
  });

  final double markSize;
  final double gap;
  final bool showLabel;

  @override
  Widget build(BuildContext context) {
    final mark = CorteMark(size: markSize);
    if (!showLabel) return mark;
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        ExcludeSemantics(child: mark),
        SizedBox(width: gap),
        const Flexible(
          child: Text(
            'CUTGC',
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: TextStyle(
              color: Colors.white,
              fontFamily: 'MonaSans',
              fontSize: 20,
              fontWeight: FontWeight.w700,
              letterSpacing: -.3,
              height: 1.15,
            ),
          ),
        ),
      ],
    );
  }
}

class CorteMark extends StatelessWidget {
  const CorteMark({super.key, this.size = 28});
  final double size;
  @override
  Widget build(BuildContext context) => Semantics(
    label: 'CUTGC',
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
