import 'dart:convert';

import 'package:corte/app.dart';
import 'package:corte/auth/auth_controller.dart';
import 'package:corte/data/corte_repository.dart';
import 'package:corte/platform/corte_runtime.dart';
import 'package:corte/ui/catalog.dart';
import 'package:corte/ui/desktop.dart';
import 'package:corte/ui/theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

const _scope =
    'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';

class _SalesFixture {
  _SalesFixture() {
    auth = CorteAuthController(
      runtime: CorteRuntime(
        platform: 'web',
        baseUri: Uri.parse(corteCloudOrigin),
      ),
      client: MockClient(_handle),
    );
    ui = CorteUiController(auth: auth);
    ui.repo.attachStore(MemoryCorteDataStore());
    ui.repo.setScopes(ownerScope: _scope, cacheScope: _scope);
    ui.replace('/ventas?periodo=30d');
  }

  late final CorteAuthController auth;
  late final CorteUiController ui;
  final requests = <Uri>[];

  void dispose() {
    ui.dispose();
    auth.dispose();
  }

  Future<http.Response> _handle(http.Request request) async {
    final url = request.url;
    requests.add(url);
    return switch (url.path) {
      '/api/dashboard' => _response(
        _dashboard(url.queryParameters['periodo']!),
      ),
      '/api/ordenes' => _response({
        'total': 51,
        'items': [
          {
            'order_id': '12345',
            'estado': 'SETTLED',
            'estado_etiqueta': 'Liquidado',
            'fecha': '2026-11-18',
            'comision_real_centavos': 1275,
            'lineas': [
              {'producto': 'Producto de prueba', 'cantidad': 2},
            ],
          },
        ],
      }),
      '/api/notas' ||
      '/api/tiendas' ||
      '/api/analitica/productos' => _response({'items': []}),
      _ => http.Response('{"codigo":"ruta_no_encontrada"}', 404),
    };
  }

  Map<String, Object?> _dashboard(String period) => {
    'actualidad': {
      'hoy': {'fecha': '2026-11-19'},
    },
    'periodo': {
      'clave': period,
      'desde': period == '2026-10' ? '2026-10-01' : '2026-10-21',
      'hasta': period == '2026-10' ? '2026-10-31' : '2026-11-19',
    },
    'kpis': {
      'comision_total_centavos': 841300,
      'comision_estimada_centavos': 883900,
      'comision_liquidada_centavos': 261300,
      'comision_por_liquidar_centavos': 580000,
      'comision_perdida_reembolsos_centavos': 205800,
      'comision_retenida_centavos': 0,
      'pedidos': 358,
      'pedidos_validos': 301,
      'pedidos_reembolsados': 95,
      'tasa_reembolso': .265,
      'unidades': 275,
      'ventas_centavos': 8841200,
    },
    'kpis_anterior': {
      'comision_total_centavos': 720000,
      'tasa_reembolso': .213,
    },
    'serie': {
      'granularidad': 'dia',
      'puntos': [
        {
          'clave': '2026-11-17',
          'pedidos': 10,
          'pedidos_reembolsados': 1,
          'unidades': 11,
          'comision_estimada_centavos': 10000,
          'comision_liquidada_centavos': 9000,
        },
        {
          'clave': '2026-11-18',
          'pedidos': 20,
          'pedidos_reembolsados': 3,
          'unidades': 23,
          'comision_estimada_centavos': 30000,
          'comision_liquidada_centavos': 15000,
        },
      ],
    },
  };

  http.Response _response(Object value) => http.Response(
    jsonEncode(value),
    200,
    headers: {'content-type': 'application/json; charset=utf-8'},
  );
}

Future<_SalesFixture> _mount(
  WidgetTester tester, {
  required Size size,
  double textScale = 1,
  bool desktop = false,
}) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  final fixture = _SalesFixture();
  addTearDown(fixture.dispose);
  final baseTheme = corteTheme(brightness: Brightness.dark);
  await tester.pumpWidget(
    MaterialApp(
      theme: desktop ? desktopWorkspaceTheme(baseTheme) : baseTheme,
      builder: (context, child) => MediaQuery(
        data: MediaQuery.of(
          context,
        ).copyWith(textScaler: TextScaler.linear(textScale)),
        child: CorteScope(controller: fixture.ui, child: child!),
      ),
      home: const Scaffold(body: SalesPage()),
    ),
  );
  await tester.pumpAndSettle();
  return fixture;
}

Finder _scroll() => find
    .byWidgetPredicate(
      (widget) =>
          widget is Scrollable && widget.axisDirection == AxisDirection.down,
    )
    .first;

void main() {
  testWidgets(
    'desktop Ventas shows web KPI semantics and loads selected calendar month',
    (tester) async {
      final fixture = await _mount(
        tester,
        size: const Size(1360, 950),
        desktop: true,
      );
      expect(find.text('Tu dinero · últimos 30 días'), findsOneWidget);
      expect(find.textContaining('21 oct – 19 nov'), findsOneWidget);
      expect(find.text(r'$8,413'), findsWidgets);
      expect(find.text(r'$8,839'), findsNothing);
      expect(find.text('358'), findsOneWidget);
      expect(find.text('301'), findsNothing);
      expect(find.text('26.5 %'), findsOneWidget);
      expect(find.text(r'≈ $88,412'), findsOneWidget);
      expect(find.text('▲ 5.2 pts'), findsOneWidget);
      await tester.tap(find.text('Comparar con el periodo anterior'));
      await tester.pumpAndSettle();
      expect(find.text('▲ 5.2 pts'), findsNothing);
      await tester.tap(find.byTooltip('Otro periodo'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Mes pasado (oct 2026)'));
      await tester.pumpAndSettle();
      expect(fixture.ui.location, '/ventas?periodo=2026-10');
      expect(
        fixture.requests
            .where((r) => r.path == '/api/dashboard')
            .last
            .queryParameters['periodo'],
        '2026-10',
      );
      expect(tester.takeException(), isNull);
    },
    variant: TargetPlatformVariant.only(TargetPlatform.windows),
  );

  testWidgets(
    '320 dp Ventas renders at 2x, aggregates weekly rates and filters embedded orders',
    (tester) async {
      final fixture = await _mount(
        tester,
        size: const Size(320, 740),
        textScale: 2,
      );
      final table = find.text('Ver como tabla');
      await tester.scrollUntilVisible(table, 450, scrollable: _scroll());
      await tester.pumpAndSettle();
      expect(find.text('Comisión por semana'), findsOneWidget);
      await tester.tap(table);
      await tester.pumpAndSettle();
      final refund = find.widgetWithText(ChoiceChip, 'Tasa de reembolso');
      await tester.ensureVisible(refund);
      await tester.pumpAndSettle();
      expect(refund.hitTestable(), findsOneWidget);
      await tester.tap(refund);
      await tester.pumpAndSettle();
      expect(find.text('Tasa de reembolso por semana'), findsOneWidget);
      final rateInChart = find.descendant(
        of: find.byType(DataTable).first,
        matching: find.text('13.3 %'),
      );
      expect(rateInChart, findsOneWidget);
      expect(
        fixture.requests.where((r) => r.path == '/api/analitica/serie'),
        isEmpty,
      );
      final settled = find.widgetWithText(ChoiceChip, 'Liquidados');
      await tester.scrollUntilVisible(settled, 500, scrollable: _scroll());
      await tester.pumpAndSettle();
      await tester.tap(settled);
      await tester.pumpAndSettle();
      final orderRequest = fixture.requests
          .where((r) => r.path == '/api/ordenes')
          .last;
      expect(orderRequest.queryParameters['estado'], 'SETTLED');
      expect(orderRequest.queryParameters['desde'], '2026-10-21');
      expect(orderRequest.queryParameters['hasta'], '2026-11-19');
      final product = find.text('Producto de prueba');
      await tester.scrollUntilVisible(product, 360, scrollable: _scroll());
      await tester.pumpAndSettle();
      expect(product.hitTestable(), findsOneWidget);
      await tester.tap(product);
      await tester.pumpAndSettle();
      expect(find.text('Comisión real'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
    variant: TargetPlatformVariant.only(TargetPlatform.android),
  );
}
