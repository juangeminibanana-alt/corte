import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import 'theme.dart';

/// Desktop composition is separate from phone/tablet styling. Windows keeps
/// its OS text scaler; narrow desktop windows can adapt individual regions.
bool useDesktopWorkspace(BuildContext context) => kIsWeb
    ? MediaQuery.sizeOf(context).width >= 1000
    : defaultTargetPlatform == TargetPlatform.windows;

ThemeData desktopWorkspaceTheme(ThemeData base) => base.copyWith(
  visualDensity: VisualDensity.standard,
  textTheme: base.textTheme.copyWith(
    headlineLarge: base.textTheme.headlineLarge?.copyWith(
      fontSize: CorteType.page,
      height: 1.25,
      fontWeight: FontWeight.w700,
      letterSpacing: -.6,
    ),
    headlineMedium: base.textTheme.headlineMedium?.copyWith(
      fontSize: CorteType.section,
      height: 1.3,
      fontWeight: FontWeight.w700,
      letterSpacing: -.4,
    ),
    headlineSmall: base.textTheme.headlineSmall?.copyWith(
      fontSize: CorteType.title,
      height: 1.35,
      fontWeight: FontWeight.w600,
    ),
    titleLarge: base.textTheme.titleLarge?.copyWith(
      fontSize: CorteType.title,
      height: 1.4,
      fontWeight: FontWeight.w600,
    ),
    titleMedium: base.textTheme.titleMedium?.copyWith(
      fontSize: CorteType.body,
      height: 1.4,
      fontWeight: FontWeight.w600,
    ),
    bodyLarge: base.textTheme.bodyLarge?.copyWith(
      fontSize: CorteType.body,
      height: 1.5,
    ),
    bodyMedium: base.textTheme.bodyMedium?.copyWith(fontSize: 13, height: 1.5),
    bodySmall: base.textTheme.bodySmall?.copyWith(
      fontSize: CorteType.meta,
      height: 1.4,
    ),
    labelLarge: base.textTheme.labelLarge?.copyWith(
      fontSize: 13,
      fontWeight: FontWeight.w600,
    ),
    labelMedium: base.textTheme.labelMedium?.copyWith(
      fontSize: CorteType.meta,
      fontWeight: FontWeight.w500,
    ),
  ),
  inputDecorationTheme: base.inputDecorationTheme.copyWith(
    contentPadding: const EdgeInsets.symmetric(
      horizontal: CorteSpace.medium,
      vertical: CorteSpace.small,
    ),
  ),
  filledButtonTheme: FilledButtonThemeData(
    style: base.filledButtonTheme.style?.copyWith(
      minimumSize: const WidgetStatePropertyAll(Size(44, 40)),
      padding: const WidgetStatePropertyAll(
        EdgeInsets.symmetric(
          horizontal: CorteSpace.large,
          vertical: CorteSpace.small,
        ),
      ),
      textStyle: const WidgetStatePropertyAll(
        TextStyle(fontSize: 13, fontWeight: FontWeight.w600),
      ),
    ),
  ),
  outlinedButtonTheme: OutlinedButtonThemeData(
    style: base.outlinedButtonTheme.style?.copyWith(
      minimumSize: const WidgetStatePropertyAll(Size(44, 38)),
      textStyle: const WidgetStatePropertyAll(
        TextStyle(fontSize: 13, fontWeight: FontWeight.w500),
      ),
    ),
  ),
);
