import 'dart:convert';

import 'package:corte/app.dart';
import 'package:corte/auth/auth_controller.dart';
import 'package:corte/platform/corte_runtime.dart';
import 'package:corte/ui/marketplace.dart';
import 'package:corte/ui/shell.dart';
import 'package:corte/ui/theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

http.Response _json(Object body, [int status = 200]) => http.Response.bytes(
  utf8.encode(jsonEncode(body)),
  status,
  headers: {'content-type': 'application/json; charset=utf-8'},
);

Map<String, Object?> _producto(String id, String titulo) => {
  'product_id': id,
  'titulo': titulo,
  'tienda': 'Tienda de prueba',
  'precio_min': '250',
  'precio_max': '299',
  'moneda': 'MXN',
  'comision_porcentaje': 12.5,
  'unidades_vendidas': 13,
  'categorias': [
    {'id': '101', 'nombre': 'Hogar'},
  ],
  'enlace': 'https://shop.tiktok.com/view/product/$id',
};

Future<CorteUiController> _abrirCorte(
  WidgetTester tester, {
  required bool acceso,
  required http.Response Function(Uri url) mercado,
}) async {
  final auth = CorteAuthController(
    runtime: CorteRuntime(
      platform: 'web',
      baseUri: Uri.parse(corteCloudOrigin),
    ),
    client: MockClient(
      (request) async => switch (request.url.path) {
        '/api/session' => _json({
          'capacidades': {'marketplace_creator': acceso},
        }),
        '/api/analitica/productos' => _json({'items': [], 'total': 0}),
        '/api/catalogo/marketplace' => mercado(request.url),
        _ => _json({
          'error': {'codigo': 'no_encontrado'},
        }, 404),
      },
    ),
  );
  final ui = CorteUiController(auth: auth)..replace('/productos');
  addTearDown(() {
    ui.dispose();
    auth.dispose();
  });
  await tester.pumpWidget(
    MaterialApp(
      theme: corteTheme(),
      home: CorteScope(controller: ui, child: const CorteShell()),
    ),
  );
  await tester.pumpAndSettle();
  return ui;
}

Finder _campo(String etiqueta) => find.byWidgetPredicate(
  (widget) => widget is TextField && widget.decoration?.labelText == etiqueta,
);

Future<void> _pulsar(WidgetTester tester, Finder finder) async {
  await tester.ensureVisible(finder);
  await tester.tap(finder);
  await tester.pumpAndSettle();
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUpAll(() async {
    final fonts = FontLoader('MonaSans')
      ..addFont(rootBundle.load('assets/fonts/MonaSans.ttf'));
    await fonts.load();
  });

  testWidgets('la cuenta sin permiso ni siquiera consulta el Marketplace', (
    tester,
  ) async {
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(1300, 1000);
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    var consultas = 0;
    final ui = await _abrirCorte(
      tester,
      acceso: false,
      mercado: (_) {
        consultas++;
        return _json({'productos': []});
      },
    );
    expect(find.text('Explorar TikTok Shop'), findsNothing);
    ui.go('/productos?segmento=marketplace');
    await tester.pumpAndSettle();
    expect(find.text('Búsqueda de TikTok Shop no disponible'), findsOneWidget);
    expect(find.widgetWithText(FilledButton, 'Buscar'), findsNothing);
    expect(consultas, 0);
    await _pulsar(tester, find.text('Volver'));
    expect(ui.location, '/productos');
  }, variant: const TargetPlatformVariant({TargetPlatform.windows}));

  testWidgets(
    'Productos busca, conserva filtros y pagina en una ventana compacta',
    (tester) async {
      tester.view.devicePixelRatio = 1;
      tester.view.physicalSize = const Size(390, 1100);
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final consultas = <Map<String, String>>[];
      final ui = await _abrirCorte(
        tester,
        acceso: true,
        mercado: (url) {
          final filtros = url.queryParameters;
          consultas.add(filtros);
          if (filtros.containsKey('category_id')) {
            return _json({'productos': []});
          }
          if (filtros.containsKey('cursor')) {
            return _json({
              'productos': [_producto('200', 'Termo oscuro')],
              'cursor_siguiente': null,
            });
          }
          return _json({
            'productos': [_producto('100', 'Termo claro')],
            'cursor_siguiente': 'b2=',
          });
        },
      );
      await _pulsar(tester, find.text('Explorar TikTok Shop'));
      expect(ui.location, '/productos?segmento=marketplace');
      expect(consultas, isEmpty);
      await tester.enterText(_campo('Producto'), ' termo ');
      await tester.enterText(_campo('Precio mínimo'), '250,50');
      await tester.enterText(_campo('Comisión mínima (%)'), '12,5');
      await _pulsar(tester, find.text('Relevancia'));
      await _pulsar(tester, find.text('Más vendidos').last);
      await _pulsar(tester, find.text('Buscar'));
      expect(find.text('Termo claro'), findsOneWidget);
      expect(find.text('MXN 250.00 a MXN 299.00'), findsOneWidget);
      expect(find.text('Ver en TikTok'), findsOneWidget);
      expect(consultas.first, {
        'limit': '20',
        'q': 'termo',
        'min_price': '250.50',
        'min_commission': '12.5',
        'sort': 'units_sold',
        'direction': 'DESC',
      });
      final lista = find
          .descendant(
            of: find.byType(MarketplacePage),
            matching: find.byType(Scrollable),
          )
          .first;
      await tester.scrollUntilVisible(
        find.text('Cargar más productos'),
        140,
        scrollable: lista,
      );
      await _pulsar(tester, find.text('Cargar más productos'));
      expect(find.text('Termo oscuro'), findsOneWidget);
      expect(consultas[1], {...consultas[0], 'cursor': 'b2='});
      await _pulsar(tester, find.widgetWithText(ActionChip, 'Hogar').last);
      await _pulsar(tester, find.text('Buscar'));
      expect(consultas[2], {...consultas[0], 'category_id': '101'});
      expect(find.text('No encontramos productos'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );
}
