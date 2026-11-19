import 'package:corte/app.dart';
import 'package:corte/auth/auth_controller.dart';
import 'package:corte/platform/corte_runtime.dart';
import 'package:corte/ui/desktop.dart';
import 'package:corte/ui/desktop_shell.dart';
import 'package:corte/ui/shell.dart';
import 'package:corte/ui/theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

class _Fixture {
  _Fixture() {
    auth = CorteAuthController(
      runtime: CorteRuntime(
        platform: 'web',
        baseUri: Uri.parse(corteCloudOrigin),
      ),
      client: MockClient((_) async => http.Response('', 404)),
    );
    ui = CorteUiController(auth: auth);
  }

  late final CorteAuthController auth;
  late final CorteUiController ui;

  void dispose() {
    ui.dispose();
    auth.dispose();
  }
}

Future<_Fixture> _mount(
  WidgetTester tester, {
  required double height,
  required double scale,
  VoidCallback? onSearch,
  VoidCallback? onSync,
}) async {
  tester.view.physicalSize = Size(1360, height);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  final fixture = _Fixture();
  addTearDown(fixture.dispose);
  await tester.pumpWidget(
    MaterialApp(
      theme: desktopWorkspaceTheme(corteTheme(brightness: Brightness.dark)),
      builder: (context, child) => MediaQuery(
        data: MediaQuery.of(
          context,
        ).copyWith(textScaler: TextScaler.linear(scale)),
        child: CorteScope(controller: fixture.ui, child: child!),
      ),
      home: DesktopShell(
        body: const Center(child: Text('Contenido de escritorio')),
        onSearch: onSearch ?? () {},
        onSync: onSync ?? () {},
        syncing: false,
      ),
    ),
  );
  await tester.pumpAndSettle();
  return fixture;
}

void main() {
  for (final height in [500.0, 860.0]) {
    for (final scale in [1.44, 2.0]) {
      testWidgets(
        'desktop frame keeps content and actions visible at 1360x$height with text scale $scale',
        (tester) async {
          var searches = 0;
          var synchronizations = 0;
          await _mount(
            tester,
            height: height,
            scale: scale,
            onSearch: () => searches++,
            onSync: () => synchronizations++,
          );

          expect(find.text('Contenido de escritorio'), findsOneWidget);
          final contentContext = tester.element(
            find.text('Contenido de escritorio'),
          );
          expect(MediaQuery.textScalerOf(contentContext).scale(10), scale * 10);
          expect(tester.takeException(), isNull);
          await tester.tap(find.byTooltip('Buscar en CUTGC'));
          await tester.pumpAndSettle();
          final refresh = find.byTooltip('Actualizar datos');
          await tester.ensureVisible(refresh);
          await tester.tap(refresh);
          await tester.pumpAndSettle();
          expect(searches, 1);
          expect(synchronizations, 1);
          expect(tester.takeException(), isNull);
          await tester.pumpWidget(const SizedBox.shrink());
        },
        variant: TargetPlatformVariant.only(TargetPlatform.windows),
      );
    }
  }

  testWidgets(
    'short desktop window scrolls the sidebar and keeps every navigation action reachable',
    (tester) async {
      final fixture = await _mount(tester, height: 500, scale: 2);
      final scrollable = tester.state<ScrollableState>(find.byType(Scrollable));
      expect(scrollable.position.maxScrollExtent, greaterThan(0));

      final samples = find.byTooltip('Muestras');
      await tester.ensureVisible(samples);
      await tester.tap(samples);
      await tester.pumpAndSettle();
      expect(fixture.ui.location, '/muestras');

      final settings = find.byTooltip('Configuración');
      await tester.ensureVisible(settings);
      await tester.pumpAndSettle();
      expect(scrollable.position.pixels, greaterThan(0));
      await tester.tap(settings);
      await tester.pumpAndSettle();
      expect(fixture.ui.location, '/ajustes');
      expect(find.text('Contenido de escritorio'), findsOneWidget);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox.shrink());
    },
    variant: TargetPlatformVariant.only(TargetPlatform.windows),
  );

  testWidgets(
    'Android header keeps brand and actions visible at 320dp with 2x text',
    (tester) async {
      tester.view.physicalSize = const Size(320, 700);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final fixture = _Fixture();
      addTearDown(fixture.dispose);

      await tester.pumpWidget(
        MaterialApp(
          theme: corteTheme(),
          builder: (context, child) => MediaQuery(
            data: MediaQuery.of(
              context,
            ).copyWith(textScaler: const TextScaler.linear(2)),
            child: CorteScope(controller: fixture.ui, child: child!),
          ),
          home: const CorteShell(),
        ),
      );
      await tester.pumpAndSettle();

      final brand = find.text('CUTGC');
      final search = find.byTooltip('Buscar en CUTGC');
      final refresh = find.byTooltip('Actualizar datos');
      expect(brand, findsOneWidget);
      expect(find.bySemanticsLabel('CUTGC'), findsOneWidget);
      expect(search.hitTestable(), findsOneWidget);
      expect(refresh.hitTestable(), findsOneWidget);
      expect(
        tester.getRect(brand).right,
        lessThanOrEqualTo(tester.getRect(search).left),
      );
      expect(tester.getRect(refresh).right, lessThanOrEqualTo(320));
      expect(MediaQuery.textScalerOf(tester.element(brand)).scale(20), 40);
      expect(tester.takeException(), isNull);

      await tester.pumpWidget(const SizedBox.shrink());
    },
    variant: TargetPlatformVariant.only(TargetPlatform.android),
  );

  testWidgets('mobile sales tabs navigate to the existing catalog routes', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final fixture = _Fixture();
    addTearDown(fixture.dispose);
    fixture.ui.restoreRoute('/ventas');

    await tester.pumpWidget(
      MaterialApp(
        theme: corteTheme(),
        builder: (context, child) =>
            CorteScope(controller: fixture.ui, child: child!),
        home: const CorteShell(),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('Resumen'), findsOneWidget);
    await tester.tap(find.text('Videos'));
    await tester.pumpAndSettle();
    expect(fixture.ui.location, '/videos');
    await tester.tap(find.text('Productos'));
    await tester.pumpAndSettle();
    expect(fixture.ui.location, '/productos');
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox.shrink());
  }, variant: TargetPlatformVariant.only(TargetPlatform.android));

  testWidgets('TikTok shortcut opens the TikTok Shop section in settings', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(390, 640);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final fixture = _Fixture();
    addTearDown(fixture.dispose);
    fixture.ui.restoreRoute('/ajustes/tiktok');

    await tester.pumpWidget(
      MaterialApp(
        theme: corteTheme(),
        builder: (context, child) =>
            CorteScope(controller: fixture.ui, child: child!),
        home: const CorteShell(),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('TikTok Shop').hitTestable(), findsOneWidget);
    expect(find.text('Apariencia').hitTestable(), findsNothing);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox.shrink());
  }, variant: TargetPlatformVariant.only(TargetPlatform.android));

  testWidgets('Android keeps its typography profile even on a wide display', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1536, 960);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    bool? desktop;
    await tester.pumpWidget(
      MaterialApp(
        home: Builder(
          builder: (context) {
            desktop = useDesktopWorkspace(context);
            return const SizedBox.shrink();
          },
        ),
      ),
    );
    expect(desktop, isFalse);
  }, variant: TargetPlatformVariant.only(TargetPlatform.android));

  testWidgets('Windows keeps the desktop profile in a narrow window', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(800, 620);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    bool? desktop;
    await tester.pumpWidget(
      MaterialApp(
        home: Builder(
          builder: (context) {
            desktop = useDesktopWorkspace(context);
            return const SizedBox.shrink();
          },
        ),
      ),
    );
    expect(desktop, isTrue);
  }, variant: TargetPlatformVariant.only(TargetPlatform.windows));
}
