import 'dart:async';

import 'package:corte/platform/theme_chrome.dart';
import 'package:corte/ui/theme.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  const channel = MethodChannel('corte/window');
  final binding = TestWidgetsFlutterBinding.ensureInitialized();

  tearDown(() {
    binding.defaultBinaryMessenger.setMockMethodCallHandler(channel, null);
    binding.platformDispatcher.clearPlatformBrightnessTestValue();
  });

  Widget frame(ThemeMode mode) => MaterialApp(
    theme: corteTheme(),
    darkTheme: corteTheme(brightness: Brightness.dark),
    themeMode: mode,
    builder: (_, child) => ThemeChromeSync(child: child!),
    home: const Scaffold(body: Text('Corte')),
  );

  testWidgets('Window chrome follows resolved app brightness and resume', (
    tester,
  ) async {
    final updates = <bool>[];
    binding.defaultBinaryMessenger.setMockMethodCallHandler(channel, (
      call,
    ) async {
      expect(call.method, 'setDarkMode');
      updates.add(call.arguments as bool);
      return null;
    });
    tester.platformDispatcher.platformBrightnessTestValue = Brightness.dark;
    await tester.pumpWidget(frame(ThemeMode.system));
    await tester.pumpAndSettle();
    expect(updates.last, isTrue);
    tester.platformDispatcher.platformBrightnessTestValue = Brightness.light;
    await tester.pumpAndSettle();
    expect(updates.last, isFalse);
    await tester.pumpWidget(frame(ThemeMode.dark));
    await tester.pumpAndSettle();
    expect(updates.last, isTrue);
    final before = updates.length;
    tester.platformDispatcher.platformBrightnessTestValue = Brightness.dark;
    await tester.pumpAndSettle();
    expect(updates.length, before);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pumpAndSettle();
    expect(updates.length, before + 1);
    expect(updates.last, isTrue);
  }, variant: TargetPlatformVariant.only(TargetPlatform.windows));

  testWidgets('Older runners and disposal do not interrupt theme changes', (
    tester,
  ) async {
    final pending = Completer<Object?>();
    binding.defaultBinaryMessenger.setMockMethodCallHandler(
      channel,
      (_) => pending.future,
    );
    await tester.pumpWidget(frame(ThemeMode.dark));
    await tester.pumpWidget(const SizedBox.shrink());
    pending.completeError(MissingPluginException());
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
  }, variant: TargetPlatformVariant.only(TargetPlatform.windows));

  testWidgets('Other platforms do not invoke the Windows-only channel', (
    tester,
  ) async {
    var calls = 0;
    binding.defaultBinaryMessenger.setMockMethodCallHandler(channel, (_) async {
      calls++;
      return null;
    });
    await tester.pumpWidget(frame(ThemeMode.dark));
    await tester.pumpAndSettle();
    expect(calls, 0);
  }, variant: TargetPlatformVariant.only(TargetPlatform.android));
}
