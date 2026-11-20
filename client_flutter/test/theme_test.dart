import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:corte/ui/desktop.dart';
import 'package:corte/ui/theme.dart';
import 'package:corte/ui/widgets.dart';

double contrast(Color foreground, Color background) {
  final a = foreground.computeLuminance();
  final b = background.computeLuminance();
  return ((a > b ? a : b) + .05) / ((a < b ? a : b) + .05);
}

void main() {
  for (final desktop in [false, true]) {
    testWidgets(
      'PageTitle and SectionHeading render with CUTGCDisplay (desktop: $desktop)',
      (tester) async {
        final base = corteTheme();
        await tester.pumpWidget(
          MaterialApp(
            theme: desktop ? desktopWorkspaceTheme(base) : base,
            home: const Scaffold(
              body: Column(
                children: [
                  PageTitle('Dinero', subtitle: 'Últimos 30 días'),
                  SectionHeading('Resumen'),
                ],
              ),
            ),
          ),
        );
        for (final heading in ['Dinero', 'Resumen']) {
          final paragraph = tester.renderObject<RenderParagraph>(
            find.text(heading),
          );
          expect(paragraph.text.style?.fontFamily, 'CUTGCDisplay');
          expect(paragraph.text.style?.fontWeight, FontWeight.w700);
        }
        final subtitle = tester.renderObject<RenderParagraph>(
          find.text('Últimos 30 días'),
        );
        expect(subtitle.text.style?.fontFamily, isNot('CUTGCDisplay'));
        expect(tester.takeException(), isNull);
      },
    );
  }

  for (final brightness in Brightness.values) {
    test('Text and interactive accents have AA contrast in $brightness', () {
      final palette = CortePalette(isDark: brightness == Brightness.dark);
      for (final background in [palette.surface, palette.soft, palette.rose]) {
        for (final foreground in [
          palette.ink,
          palette.muted,
          palette.action,
          palette.cyanInk,
          palette.success,
          palette.danger,
          palette.warning,
        ]) {
          expect(
            contrast(foreground, background),
            greaterThanOrEqualTo(4.5),
            reason: '$foreground against $background in $brightness',
          );
        }
      }
      final theme = corteTheme(brightness: brightness);
      final chip = theme.chipTheme;
      expect(
        contrast(
          chip.secondaryLabelStyle!.color!,
          chip.secondarySelectedColor!,
        ),
        greaterThanOrEqualTo(4.5),
      );
      final button = theme.filledButtonTheme.style!;
      expect(
        contrast(
          button.foregroundColor!.resolve({})!,
          button.backgroundColor!.resolve({})!,
        ),
        greaterThanOrEqualTo(4.5),
      );
    });
  }

  testWidgets('System follows OS changes, explicit themes override them', (
    tester,
  ) async {
    addTearDown(tester.platformDispatcher.clearPlatformBrightnessTestValue);
    Future<void> mount(ThemeMode mode) async {
      await tester.pumpWidget(
        MaterialApp(
          theme: corteTheme(),
          darkTheme: corteTheme(brightness: Brightness.dark),
          themeMode: mode,
          home: const Scaffold(body: InlineNotice(text: 'Sin conexión')),
        ),
      );
      await tester.pumpAndSettle();
    }

    Brightness actual() =>
        Theme.of(tester.element(find.byType(InlineNotice))).brightness;
    tester.platformDispatcher.platformBrightnessTestValue = Brightness.dark;
    await mount(ThemeMode.system);
    expect(actual(), Brightness.dark);
    tester.platformDispatcher.platformBrightnessTestValue = Brightness.light;
    await tester.pumpAndSettle();
    expect(actual(), Brightness.light);
    await mount(ThemeMode.dark);
    expect(actual(), Brightness.dark);
    tester.platformDispatcher.platformBrightnessTestValue = Brightness.dark;
    await mount(ThemeMode.light);
    expect(actual(), Brightness.light);
  });
}
