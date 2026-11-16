import 'dart:convert';

import 'package:corte/app.dart';
import 'package:corte/auth/auth_controller.dart';
import 'package:corte/data/corte_repository.dart';
import 'package:corte/platform/corte_runtime.dart';
import 'package:corte/ui/desktop.dart';
import 'package:corte/ui/desktop_home.dart';
import 'package:corte/ui/theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

const _scope =
    'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';

http.Response _response(Object value) => http.Response(
  jsonEncode(value),
  200,
  headers: {'content-type': 'application/json; charset=utf-8'},
);

class _HomeFixture {
  _HomeFixture({this.empty = false}) {
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
  }

  final bool empty;
  late final CorteAuthController auth;
  late final CorteUiController ui;

  JsonMap get preferences => {'rev': 1, 'tema': 'oscuro'};
  List<JsonMap> get samples => empty
      ? []
      : [
          for (var i = 0; i < 4; i++)
            {
              'application_id': 'synthetic-sample-$i',
              'grupo': 'vencida',
              'etiqueta': 'Vencida sin video',
              'recibida': true,
              'variante': 'Café Marrón muy largo / Extra grande',
              'producto': {
                'product_id': 'synthetic-product-$i',
                'titulo_corto':
                    'Chaqueta de invierno con un nombre largo y completo $i',
              },
              'tienda': {
                'tienda_key': 'synthetic-store-$i',
                'nombre': 'Tienda de ropa y accesorios con nombre largo',
              },
              'avance': {'etapa': 'por_planear'},
            },
        ];

  Future<http.Response> _handle(http.Request request) async {
    switch (request.url.path) {
      case '/api/dashboard':
        expect(request.url.queryParameters['periodo'], '30d');
        return _response({
          'kpis': empty
              ? <String, dynamic>{}
              : {
                  'comision_total_centavos': 1234500,
                  'ventas_centavos': 9876500,
                  'pedidos_validos': 41,
                  'unidades': 52,
                },
          'serie': {
            'puntos': empty
                ? <JsonMap>[]
                : [
                    for (var i = 0; i < 30; i++)
                      {
                        'etiqueta': '${i + 1} nov',
                        'comision_estimada_centavos': i == 4
                            ? -2000
                            : i == 5
                            ? 0
                            : 10000 + i * 550,
                      },
                  ],
          },
          'top_tiendas': empty
              ? <JsonMap>[]
              : [
                  for (var i = 0; i < 3; i++)
                    {
                      'tienda_key': 'synthetic-store-$i',
                      'nombre':
                          'Una tienda con nombre suficientemente largo $i',
                      'ventas': {
                        'comision_estimada_centavos': 45000 + i * 4000,
                      },
                    },
                ],
        });
      case '/api/muestras':
        return _response({'items': samples});
      case '/api/preferencias':
        return _response(preferences);
      case '/api/cloud/revision':
        return _response({
          'revision': 'synthetic-stable',
          'owner_scope': _scope,
          'cache_scope': _scope,
        });
      case '/api/snapshot':
        return _response({
          'version_esquema': 1,
          'muestras': samples,
          'local': {
            'preferencias': preferences,
            'planes': [],
            'notas': [],
            'recordatorios': [],
            'avisos': [],
            'plantillas': [],
          },
        });
      default:
        return http.Response('', 404);
    }
  }

  void dispose() {
    ui.dispose();
    auth.dispose();
  }
}

Future<void> _mount(
  WidgetTester tester,
  _HomeFixture fixture, {
  double contentWidth = 1000,
  double textScale = 1,
}) async {
  // Home applies 28 px on both sides. Test the requested available content
  // width instead of accidentally testing a narrower viewport minus padding.
  tester.view.physicalSize = Size(contentWidth + 56, 1600);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  addTearDown(fixture.dispose);
  await tester.pumpWidget(
    CorteScope(
      controller: fixture.ui,
      child: MaterialApp(
        theme: desktopWorkspaceTheme(corteTheme(brightness: Brightness.dark)),
        builder: (context, child) => MediaQuery(
          data: MediaQuery.of(
            context,
          ).copyWith(textScaler: TextScaler.linear(textScale)),
          child: child!,
        ),
        home: const Scaffold(body: DesktopHomePage()),
      ),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  for (final contentWidth in [1000.0, 850.0, 640.0]) {
    for (final textScale in [1.0, 1.44, 2.0]) {
      testWidgets(
        'desktop home fits content $contentWidth at text scale $textScale',
        (tester) async {
          final fixture = _HomeFixture();
          await _mount(
            tester,
            fixture,
            contentWidth: contentWidth,
            textScale: textScale,
          );
          expect(tester.takeException(), isNull);
          expect(find.text(r'$12,345'), findsOneWidget);
          expect(find.text(r'$98,765'), findsOneWidget);
          expect(
            MediaQuery.textScalerOf(
              tester.element(find.byType(DesktopHomePage)),
            ).scale(14),
            closeTo(14 * textScale, .001),
          );
          final stores = find.text('Tiendas');
          await tester.ensureVisible(stores);
          await tester.pumpAndSettle();
          expect(tester.takeException(), isNull);
          expect(find.text('Comisión estimada'), findsOneWidget);
        },
        variant: TargetPlatformVariant.only(TargetPlatform.windows),
      );
    }
  }

  testWidgets('view samples navigates to the actual samples route', (
    tester,
  ) async {
    final fixture = _HomeFixture();
    await _mount(tester, fixture, textScale: 1.44);
    await tester.tap(find.widgetWithText(OutlinedButton, 'Ver muestras'));
    await tester.pumpAndSettle();
    expect(fixture.ui.location, '/muestras');
    expect(tester.takeException(), isNull);
  }, variant: TargetPlatformVariant.only(TargetPlatform.windows));

  testWidgets(
    'absent metrics stay unknown instead of becoming invented zeroes',
    (tester) async {
      final fixture = _HomeFixture(empty: true);
      await _mount(tester, fixture, textScale: 1.44);
      expect(find.text('—'), findsNWidgets(4));
      expect(find.text(r'$0'), findsNothing);
      expect(find.text('0'), findsNothing);
      expect(find.text('Estás al día'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
    variant: TargetPlatformVariant.only(TargetPlatform.windows),
  );
}
