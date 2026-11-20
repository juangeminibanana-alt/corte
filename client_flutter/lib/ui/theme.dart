import 'package:flutter/material.dart';

import 'brand_mark.dart';
import 'design_tokens.g.dart';

abstract final class CorteColors {
  static const canvas = CutgcDesignTokens.canvas;
  static const ink = CutgcDesignTokens.ink;
  static const muted = CutgcDesignTokens.muted;
  static const chrome = CutgcDesignTokens.chrome;
  static const chromeInk = CutgcDesignTokens.onChrome;
  static const chromeMuted = CutgcDesignTokens.chromeMuted;
  static const chromeLine = CutgcDesignTokens.chromeLine;
  static const chromeSoft = CutgcDesignTokens.chromeSoft;
  static const coral = CutgcDesignTokens.brandCoral;
  static const action = CutgcDesignTokens.action;
  static const actionHover = CutgcDesignTokens.actionHover;
  static const cyan = CutgcDesignTokens.brandCyan;
  static const cyanInk = CutgcDesignTokens.focus;
  static const line = CutgcDesignTokens.line;
  static const soft = CutgcDesignTokens.canvas;
  static const rose = CutgcDesignTokens.rose;
  static const onAction = CutgcDesignTokens.onAction;
  static const actionOnChrome = CutgcDesignTokens.darkActionInk;
}

abstract final class CorteSpace {
  static const xs = CutgcDesignTokens.space1;
  static const small = CutgcDesignTokens.space2;
  static const medium = CutgcDesignTokens.space3;
  static const large = CutgcDesignTokens.space4;
  static const xl = CutgcDesignTokens.space6;
  static const xxl = CutgcDesignTokens.space8;
  static const block = CutgcDesignTokens.space12;
  static const section = CutgcDesignTokens.space16;
}

abstract final class CorteRadius {
  static const control = CutgcDesignTokens.radiusControl;
  static const panel = CutgcDesignTokens.radiusPanel;
  static const dialog = CutgcDesignTokens.radiusDialog;
}

abstract final class CorteType {
  static const displayFamily = CutgcDesignTokens.displayFontFamily;
  static const display = CutgcDesignTokens.typeDisplay;
  static const page = CutgcDesignTokens.typePage;
  static const section = CutgcDesignTokens.typeSection;
  static const title = CutgcDesignTokens.typeTitle;
  static const body = CutgcDesignTokens.typeBody;
  static const label = CutgcDesignTokens.typeLabel;
  static const meta = CutgcDesignTokens.typeMeta;
}

TextStyle studioDisplay(
  BuildContext context, {
  required double size,
  Color? color,
}) => TextStyle(
  fontFamily: CorteType.displayFamily,
  fontFamilyFallback: const [CutgcDesignTokens.fontFamily, 'Segoe UI', 'Arial'],
  fontSize: size,
  fontWeight: FontWeight.w700,
  height: 1,
  color: color ?? context.corte.ink,
  fontFeatures: const [FontFeature.tabularFigures()],
);

abstract final class CorteMotion {
  static const micro = CutgcDesignTokens.durationControl;
  static const view = CutgcDesignTokens.durationView;
  static const intro = CutgcDesignTokens.durationIntro;
  static const enter = CutgcDesignTokens.easeExit;

  static bool reducedOf(BuildContext context) =>
      MediaQuery.disableAnimationsOf(context) ||
      MediaQuery.accessibleNavigationOf(context);
}

/// Semantic content colors. Brand chrome and photo overlays keep their own
/// fixed colors; content follows the selected Material brightness.
class CortePalette {
  const CortePalette({this.isDark = false});
  final bool isDark;
  Color get canvas =>
      isDark ? CutgcDesignTokens.darkCanvas : CutgcDesignTokens.canvas;
  Color get surface =>
      isDark ? CutgcDesignTokens.darkSurface : CutgcDesignTokens.surface;
  Color get ink => isDark ? CutgcDesignTokens.darkInk : CutgcDesignTokens.ink;
  Color get muted =>
      isDark ? CutgcDesignTokens.darkMuted : CutgcDesignTokens.muted;
  Color get line =>
      isDark ? CutgcDesignTokens.darkLine : CutgcDesignTokens.line;
  Color get inputBorder => isDark
      ? CutgcDesignTokens.darkInputBorder
      : CutgcDesignTokens.inputBorder;
  Color get soft =>
      isDark ? CutgcDesignTokens.darkSurfaceRaised : CutgcDesignTokens.canvas;
  Color get rose =>
      isDark ? CutgcDesignTokens.darkRose : CutgcDesignTokens.rose;
  Color get selected =>
      isDark ? CutgcDesignTokens.darkSelected : CutgcDesignTokens.selected;
  Color get action =>
      isDark ? CutgcDesignTokens.darkActionInk : CutgcDesignTokens.actionInk;
  Color get cyanInk =>
      isDark ? CutgcDesignTokens.brandCyan : CutgcDesignTokens.focus;
  Color get focus =>
      isDark ? CutgcDesignTokens.darkFocus : CutgcDesignTokens.focus;
  Color get success =>
      isDark ? CutgcDesignTokens.darkSuccess : CutgcDesignTokens.success;
  Color get danger =>
      isDark ? CutgcDesignTokens.darkDanger : CutgcDesignTokens.danger;
  Color get warning =>
      isDark ? CutgcDesignTokens.darkWarning : CutgcDesignTokens.warning;
}

extension CorteThemeContext on BuildContext {
  CortePalette get corte =>
      CortePalette(isDark: Theme.of(this).brightness == Brightness.dark);
}

ThemeData corteTheme({Brightness brightness = Brightness.light}) {
  final colors = CortePalette(isDark: brightness == Brightness.dark);
  final controlShape = RoundedRectangleBorder(
    borderRadius: BorderRadius.circular(CorteRadius.control),
  );
  final panelShape = RoundedRectangleBorder(
    side: BorderSide(color: colors.line),
    borderRadius: BorderRadius.circular(CorteRadius.panel),
  );
  final dialogShape = RoundedRectangleBorder(
    borderRadius: BorderRadius.circular(CorteRadius.dialog),
  );
  OutlineInputBorder fieldBorder(Color color, {double width = 1}) =>
      OutlineInputBorder(
        borderRadius: BorderRadius.circular(CorteRadius.control),
        borderSide: BorderSide(color: color, width: width),
      );
  WidgetStateProperty<BorderSide?> focusBorder({
    Color? resting,
    Color? focus,
  }) => WidgetStateProperty.resolveWith((states) {
    if (states.contains(WidgetState.disabled)) {
      return resting == null ? BorderSide.none : BorderSide(color: colors.line);
    }
    if (states.contains(WidgetState.focused)) {
      return BorderSide(color: focus ?? colors.focus, width: 2);
    }
    return resting == null ? BorderSide.none : BorderSide(color: resting);
  });
  final scheme =
      ColorScheme.fromSeed(
        seedColor: CorteColors.action,
        brightness: brightness,
      ).copyWith(
        primary: colors.action,
        onPrimary: colors.isDark ? CorteColors.chrome : CorteColors.onAction,
        primaryContainer: colors.rose,
        onPrimaryContainer: colors.ink,
        secondary: colors.cyanInk,
        onSecondary: colors.isDark ? CorteColors.chrome : CorteColors.onAction,
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
        outline: colors.inputBorder,
        outlineVariant: colors.line,
        error: colors.danger,
        onError: colors.isDark ? CorteColors.chrome : CorteColors.onAction,
        errorContainer: colors.rose,
        onErrorContainer: colors.danger,
        surfaceTint: Colors.transparent,
      );
  return ThemeData(
    useMaterial3: true,
    brightness: brightness,
    fontFamily: CutgcDesignTokens.fontFamily,
    fontFamilyFallback: const ['MonaSansExtended', 'Segoe UI', 'Arial'],
    scaffoldBackgroundColor: colors.canvas,
    canvasColor: colors.surface,
    colorScheme: scheme,
    focusColor: colors.focus.withValues(alpha: .18),
    iconTheme: IconThemeData(color: colors.ink),
    textSelectionTheme: TextSelectionThemeData(
      cursorColor: colors.action,
      selectionColor: colors.action.withValues(alpha: .28),
      selectionHandleColor: colors.action,
    ),
    textTheme: TextTheme(
      headlineLarge: TextStyle(
        fontFamily: CorteType.displayFamily,
        fontSize: CorteType.page,
        height: 1.16,
        fontWeight: FontWeight.w700,
        letterSpacing: -1.15,
      ),
      headlineMedium: TextStyle(
        fontFamily: CorteType.displayFamily,
        fontSize: CorteType.section,
        height: 1.25,
        fontWeight: FontWeight.w700,
        letterSpacing: -.55,
      ),
      titleLarge: TextStyle(
        fontSize: CorteType.section,
        height: 1.3,
        fontWeight: FontWeight.w700,
      ),
      titleMedium: TextStyle(
        fontSize: CorteType.title,
        height: 1.35,
        fontWeight: FontWeight.w700,
      ),
      bodyLarge: TextStyle(fontSize: CorteType.body, height: 1.55),
      bodyMedium: TextStyle(fontSize: CorteType.body, height: 1.5),
      bodySmall: TextStyle(
        fontSize: CorteType.meta,
        height: 1.4,
        color: colors.muted,
      ),
      labelLarge: const TextStyle(
        fontSize: CorteType.label,
        fontWeight: FontWeight.w600,
      ),
      labelMedium: const TextStyle(
        fontSize: CorteType.meta,
        fontWeight: FontWeight.w600,
      ),
    ).apply(bodyColor: colors.ink, displayColor: colors.ink),
    dividerTheme: DividerThemeData(color: colors.line, thickness: 1, space: 1),
    filledButtonTheme: FilledButtonThemeData(
      style:
          FilledButton.styleFrom(
            backgroundColor: CorteColors.action,
            foregroundColor: CorteColors.onAction,
            minimumSize: const Size(44, 46),
            padding: const EdgeInsets.symmetric(
              horizontal: 20,
              vertical: CorteSpace.medium,
            ),
            textStyle: const TextStyle(
              fontFamily: CutgcDesignTokens.fontFamily,
              fontSize: 14,
              fontWeight: FontWeight.w700,
            ),
            shape: controlShape,
          ).copyWith(
            side: focusBorder(focus: CorteColors.cyan),
            backgroundColor: WidgetStateProperty.resolveWith((states) {
              if (states.contains(WidgetState.disabled)) return colors.line;
              if (states.contains(WidgetState.hovered) ||
                  states.contains(WidgetState.pressed)) {
                return CorteColors.actionHover;
              }
              return CorteColors.action;
            }),
          ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        foregroundColor: colors.action,
        minimumSize: const Size(44, 44),
        shape: controlShape,
        textStyle: const TextStyle(
          fontFamily: CutgcDesignTokens.fontFamily,
          fontSize: 14,
          fontWeight: FontWeight.w600,
        ),
      ).copyWith(side: focusBorder(resting: colors.action)),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: colors.soft,
      hintStyle: TextStyle(color: colors.muted),
      labelStyle: TextStyle(color: colors.muted),
      errorStyle: TextStyle(color: colors.danger),
      contentPadding: const EdgeInsets.symmetric(
        horizontal: CorteSpace.large,
        vertical: CorteSpace.medium,
      ),
      border: fieldBorder(colors.inputBorder),
      enabledBorder: fieldBorder(colors.inputBorder),
      disabledBorder: fieldBorder(colors.line),
      focusedBorder: fieldBorder(colors.focus, width: 2),
      errorBorder: fieldBorder(colors.danger),
      focusedErrorBorder: fieldBorder(colors.danger, width: 2),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(
        foregroundColor: colors.action,
        minimumSize: const Size(44, 44),
        shape: controlShape,
      ).copyWith(side: focusBorder()),
    ),
    iconButtonTheme: IconButtonThemeData(
      style: IconButton.styleFrom(
        minimumSize: const Size(44, 44),
        shape: controlShape,
      ).copyWith(side: focusBorder()),
    ),
    cardTheme: CardThemeData(
      color: colors.surface,
      elevation: 0,
      surfaceTintColor: Colors.transparent,
      shape: panelShape,
    ),
    chipTheme: ChipThemeData(
      backgroundColor: colors.surface,
      selectedColor: colors.selected,
      secondarySelectedColor: colors.selected,
      checkmarkColor: colors.action,
      deleteIconColor: colors.muted,
      labelStyle: TextStyle(color: colors.ink, fontWeight: FontWeight.w600),
      secondaryLabelStyle: TextStyle(
        color: colors.ink,
        fontWeight: FontWeight.w700,
      ),
      padding: const EdgeInsets.symmetric(horizontal: CorteSpace.small),
      side: WidgetStateBorderSide.resolveWith((states) {
        if (states.contains(WidgetState.focused)) {
          return BorderSide(color: colors.focus, width: 2);
        }
        return BorderSide(
          color: states.contains(WidgetState.selected)
              ? colors.action
              : colors.inputBorder,
        );
      }),
      shape: controlShape,
    ),
    bottomSheetTheme: BottomSheetThemeData(
      backgroundColor: colors.surface,
      modalBackgroundColor: colors.surface,
      surfaceTintColor: Colors.transparent,
      dragHandleColor: colors.inputBorder,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(
          top: Radius.circular(CorteRadius.dialog),
        ),
      ),
    ),
    snackBarTheme: const SnackBarThemeData(
      behavior: SnackBarBehavior.floating,
      backgroundColor: CorteColors.chrome,
      contentTextStyle: TextStyle(color: CorteColors.chromeInk),
      actionTextColor: CorteColors.cyan,
      closeIconColor: CorteColors.chromeInk,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.all(Radius.circular(CorteRadius.control)),
      ),
    ),
    popupMenuTheme: PopupMenuThemeData(
      color: colors.surface,
      surfaceTintColor: Colors.transparent,
      shape: panelShape,
      textStyle: TextStyle(
        color: colors.ink,
        fontFamily: CutgcDesignTokens.fontFamily,
      ),
    ),
    listTileTheme: ListTileThemeData(
      iconColor: colors.muted,
      textColor: colors.ink,
      selectedColor: colors.action,
      selectedTileColor: colors.selected,
      shape: controlShape,
    ),
    dialogTheme: DialogThemeData(
      backgroundColor: colors.surface,
      surfaceTintColor: Colors.transparent,
      shape: dialogShape,
    ),
    datePickerTheme: DatePickerThemeData(
      backgroundColor: colors.surface,
      surfaceTintColor: Colors.transparent,
      shape: dialogShape,
    ),
    menuTheme: MenuThemeData(
      style: MenuStyle(
        backgroundColor: WidgetStatePropertyAll(colors.surface),
        surfaceTintColor: const WidgetStatePropertyAll(Colors.transparent),
        shape: WidgetStatePropertyAll(panelShape),
      ),
    ),
  );
}

typedef CorteWordmark = CorteBrandWordmark;
typedef CorteMark = CorteBrandMark;
