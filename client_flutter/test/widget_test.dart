import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:corte/app.dart';
import 'package:corte/auth/auth_controller.dart';
import 'package:corte/platform/corte_runtime.dart';
import 'package:corte/ui/catalog.dart';
import 'package:corte/ui/shell.dart';
import 'package:corte/ui/work.dart';
import 'package:corte/ui/widgets.dart';
import 'package:corte/ui/theme.dart';

void main() {
  testWidgets('Android bottom navigation grows when labels wrap', (
    tester,
  ) async {
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final auth = CorteAuthController(
      runtime: CorteRuntime(
        platform: 'android',
        baseUri: Uri.parse(corteCloudOrigin),
      ),
      client: MockClient((_) async => http.Response('{}', 200)),
    );
    final ui = CorteUiController(auth: auth);
    addTearDown(auth.dispose);
    addTearDown(ui.dispose);
    for (final width in [320.0, 390.0]) {
      tester.view.physicalSize = Size(width, 880);
      await tester.pumpWidget(
        MaterialApp(
          theme: corteTheme(),
          home: CorteScope(controller: ui, child: const CorteShell()),
        ),
      );
      await tester.pump();
      expect(tester.takeException(), isNull);
      expect(find.text('Más'), findsOneWidget);
    }
    await tester.pumpWidget(const SizedBox.shrink());
  }, variant: TargetPlatformVariant.only(TargetPlatform.android));

  testWidgets(
    'browser back and forward restore content and application history',
    (tester) async {
      final auth = CorteAuthController(
        runtime: CorteRuntime(
          platform: 'web',
          baseUri: Uri.parse(corteCloudOrigin),
        ),
        client: MockClient((_) async => http.Response('', 404)),
      );
      final ui = CorteUiController(auth: auth);
      final delegate = CorteRouter(ui);
      await delegate.setNewRoutePath('/inicio');
      ui.go('/muestras');
      ui.go('/productos/synthetic-product');
      var updates = 0;
      ui.addListener(() {
        updates++;
      });
      await delegate.setNewRoutePath('/muestras');
      expect(ui.location, '/muestras');
      expect(updates, greaterThan(0));
      await delegate.setNewRoutePath('/productos/synthetic-product');
      expect(ui.location, '/productos/synthetic-product');
      expect(ui.back(), isTrue);
      expect(ui.location, '/muestras');
      expect(ui.back(), isTrue);
      expect(ui.location, '/inicio');
      delegate.dispose();
      ui.dispose();
      auth.dispose();
    },
  );
  test('a product photo never becomes a video cover', () {
    expect(
      videoCover({
        'content_id': '123',
        'miniatura': '/img/p/456?v=abcd',
        'miniatura_origen': 'producto',
      }),
      isNull,
    );
    expect(
      videoCover({
        'content_id': '123',
        'portada': '/img/v/456?v=abcd',
        'miniatura': '/img/v/123?v=ef01',
      }),
      '/img/v/123?v=ef01',
    );
    expect(
      productPhotos({
        'extendido': {
          'galeria': ['/img/g/p-1?v=a'],
        },
        'ficha': {'imagen': '/img/p/p?v=b'},
      }),
      ['/img/g/p-1?v=a'],
    );
  });

  for (final brightness in Brightness.values) {
    for (final width in [360.0, 768.0, 1440.0]) {
      testWidgets(
        'sample action and long variant fit at width $width in $brightness',
        (tester) async {
          tester.view.physicalSize = Size(width, 900);
          tester.view.devicePixelRatio = 1;
          addTearDown(tester.view.resetPhysicalSize);
          addTearDown(tester.view.resetDevicePixelRatio);
          final auth = CorteAuthController(
            runtime: CorteRuntime(
              platform: 'web',
              baseUri: Uri.parse(corteCloudOrigin),
            ),
            client: MockClient((_) async => http.Response('', 404)),
          );
          final ui = CorteUiController(auth: auth);
          await tester.pumpWidget(
            MaterialApp(
              theme: corteTheme(brightness: brightness),
              home: CorteScope(
                controller: ui,
                child: Scaffold(
                  body: SampleTile(
                    muestra: {
                      'application_id': 'synthetic-sample',
                      'grupo': 'vencida',
                      'etiqueta': 'Vencida sin video',
                      'recibida': true,
                      'variante': 'Café Marrón muy largo / Extra grande',
                      'producto': {
                        'product_id': 'synthetic-product',
                        'titulo_corto':
                            'Chaqueta de invierno con un título largo y completo',
                      },
                      'tienda': {
                        'nombre':
                            'Tienda de prendas y accesorios con nombre largo',
                      },
                      'avance': {'etapa': 'por_planear'},
                    },
                  ),
                ),
              ),
            ),
          );
          await tester.pump();
          expect(tester.takeException(), isNull);
          expect(
            find.widgetWithText(OutlinedButton, 'Planear'),
            findsOneWidget,
          );
          await tester.pumpWidget(const SizedBox.shrink());
          ui.dispose();
          auth.dispose();
        },
      );
    }
  }
  testWidgets('gallery selection resets when changing product', (tester) async {
    final auth = CorteAuthController(
      runtime: CorteRuntime(
        platform: 'web',
        baseUri: Uri.parse(corteCloudOrigin),
      ),
      client: MockClient((_) async => http.Response('', 404)),
    );
    final ui = CorteUiController(auth: auth);
    Widget frame(String id, List<String> photos) => MaterialApp(
      theme: corteTheme(),
      home: CorteScope(
        controller: ui,
        child: Scaffold(
          body: ProductGallery(productId: id, photos: photos),
        ),
      ),
    );
    await tester.pumpWidget(
      frame('a', const ['/img/g/a-1?v=abcd', '/img/g/a-2?v=abcd']),
    );
    await tester.tap(find.bySemanticsLabel('Ver foto 2 de 2'));
    await tester.pump();
    expect(find.text('2 / 2'), findsOneWidget);
    await tester.pumpWidget(
      frame('b', const ['/img/g/b-1?v=abcd', '/img/g/b-2?v=abcd']),
    );
    await tester.pump();
    expect(find.text('1 / 2'), findsOneWidget);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox.shrink());
    ui.dispose();
    auth.dispose();
  });
  testWidgets('a new API identity does not retain the previous product', (
    tester,
  ) async {
    final auth = CorteAuthController(
      runtime: CorteRuntime(
        platform: 'web',
        baseUri: Uri.parse(corteCloudOrigin),
      ),
      client: MockClient(
        (request) async => http.Response(
          jsonEncode({'name': request.url.path}),
          200,
          headers: {'content-type': 'application/json'},
        ),
      ),
    );
    final ui = CorteUiController(auth: auth);
    Widget frame(String path) => MaterialApp(
      home: CorteScope(
        controller: ui,
        child: Scaffold(
          body: ApiData(
            path: path,
            builder: (context, data) => Text('${data['name']}'),
          ),
        ),
      ),
    );
    await tester.pumpWidget(frame('/api/productos/first'));
    await tester.pumpAndSettle();
    expect(find.text('/api/productos/first'), findsOneWidget);
    await tester.pumpWidget(frame('/api/productos/second'));
    await tester.pump();
    expect(find.text('/api/productos/first'), findsNothing);
    await tester.pumpAndSettle();
    expect(find.text('/api/productos/second'), findsOneWidget);
    await tester.pumpWidget(const SizedBox.shrink());
    ui.dispose();
    auth.dispose();
  });
}
