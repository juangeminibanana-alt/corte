import 'dart:convert';

import 'package:corte/app.dart';
import 'package:corte/auth/auth_controller.dart';
import 'package:corte/data/corte_repository.dart';
import 'package:corte/platform/corte_runtime.dart';
import 'package:corte/ui/desktop.dart';
import 'package:corte/ui/desktop_home.dart';
import 'package:corte/ui/theme.dart';
import 'package:corte/ui/work.dart';
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
  _HomeFixture({
    this.empty = false,
    this.sessionUnavailable = false,
    this.disconnected = false,
  }) {
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

  final bool empty, sessionUnavailable, disconnected;
  int syncRequests = 0;
  late final CorteAuthController auth;
  late final CorteUiController ui;

  JsonMap get preferences => {'rev': 1, 'tema': 'oscuro'};
  List<JsonMap> get samples => empty
      ? []
      : [
          for (var i = 0; i < 6; i++)
            {
              'application_id': 'synthetic-sample-$i',
              'grupo': i == 0 ? 'por_vencer' : 'vencida',
              'fecha_limite_at': 1744000000 + (i == 3 ? 1 : i) * 3600,
              'posicion_cola': 6 - i,
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
              'avance': {
                'etapa': i == 4 || i == 5 ? 'publicada' : 'por_planear',
                if (i == 5) 'vinculo_origen': 'video_previo',
              },
            },
        ];

  Future<http.Response> _handle(http.Request request) async {
    switch (request.url.path) {
      case '/api/session':
        if (sessionUnavailable) return http.Response('', 503);
        return _response({
          'conexion': {'estado': disconnected ? 'sin_conectar' : 'conectada'},
          'capacidades': {'sincronizar': true},
          'datos': {'hay_datos': !empty},
          'sync': {'en_curso': false},
        });
      case '/api/sync':
        expect(request.method, 'POST');
        syncRequests++;
        return _response({
          'estado': {'en_curso': true},
        });
      case '/api/dashboard':
        expect(request.url.queryParameters['periodo'], '30d');
        return _response({
          if (!empty)
            'perfil_tiktok': {
              'username': 'creadora_demo',
              'seguidores': 23501,
              'seguidores_cambio_7d': -12,
            },
          'kpis': empty
              ? {
                  'ventas_centavos': 0,
                  'comision_estimada_centavos': 0,
                  'pedidos': 0,
                }
              : {
                  'comision_estimada_centavos': 1234500,
                  'comision_total_centavos': 8765400,
                  'ventas_centavos': 9876500,
                  'pedidos': 67,
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
  bool mobile = false,
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
        home: Scaffold(
          body: mobile ? const HomePage() : const DesktopHomePage(),
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('móvil muestra Inicio web y conserva seguidores en el detalle', (
    tester,
  ) async {
    await _mount(tester, _HomeFixture(), contentWidth: 334, mobile: true);
    expect(find.text('Tu negocio, en orden'), findsOneWidget);
    expect(find.text('Resultados'), findsOneWidget);
    await tester.scrollUntilVisible(find.text('@creadora_demo'), 300);
    expect(find.text('23,501 seguidores en TikTok'), findsOneWidget);
    expect(find.text('−12 en 7 días'), findsOneWidget);
    expect(tester.takeException(), isNull);
  }, variant: TargetPlatformVariant.only(TargetPlatform.android));

  for (final contentWidth in [1000.0, 850.0, 640.0, 280.0]) {
    for (final textScale in [1.0, 1.44, 2.0]) {
      testWidgets('Inicio cabe en $contentWidth dp con texto ${textScale}x', (
        tester,
      ) async {
        await _mount(
          tester,
          _HomeFixture(),
          contentWidth: contentWidth,
          textScale: textScale,
        );
        expect(tester.takeException(), isNull);
        expect(find.text('Tu negocio, en orden'), findsOneWidget);
        final commission = find.text(r'$12,345');
        await tester.scrollUntilVisible(commission, 200, maxScrolls: 15);
        expect(commission, findsOneWidget);
        expect(find.text(r'$98,765'), findsOneWidget);
        expect(find.text('67'), findsOneWidget);
        expect(find.text(r'$87,654'), findsNothing);
        expect(find.text('41'), findsNothing);
        expect(
          MediaQuery.textScalerOf(
            tester.element(find.byType(DesktopHomePage)),
          ).scale(14),
          closeTo(14 * textScale, .001),
        );
        await tester.scrollUntilVisible(
          find.text('Comisión estimada por día'),
          350,
          maxScrolls: 30,
        );
        final error = tester.takeException();
        expect(
          error,
          isNull,
          reason: error is FlutterError
              ? error.diagnostics.map((node) => node.toStringDeep()).join()
              : null,
        );
      }, variant: TargetPlatformVariant.only(TargetPlatform.windows));
    }
  }

  testWidgets('Ver muestras abre la pantalla de Muestras', (tester) async {
    final fixture = _HomeFixture();
    await _mount(tester, fixture, textScale: 1.44);
    await tester.tap(find.text('Ver muestras'));
    await tester.pumpAndSettle();
    expect(fixture.ui.location, '/muestras');
    expect(tester.takeException(), isNull);
  }, variant: TargetPlatformVariant.only(TargetPlatform.windows));

  testWidgets('El KPI abre Ventas con el periodo de 30 días', (tester) async {
    final fixture = _HomeFixture();
    await _mount(tester, fixture);
    await tester.tap(find.text('Pedidos'));
    await tester.pumpAndSettle();
    expect(fixture.ui.location, '/ventas?periodo=30d');
  });

  testWidgets(
    'Prioriza vencidas, fecha y posición. El detalle abre la muestra elegida',
    (tester) async {
      final fixture = _HomeFixture();
      await _mount(tester, fixture);
      Finder sample(int i) =>
          find.text('Chaqueta de invierno con un nombre largo y completo $i');
      expect(
        tester.getTopLeft(sample(3)).dy,
        lessThan(tester.getTopLeft(sample(1)).dy),
      );
      expect(
        tester.getTopLeft(sample(2)).dy,
        lessThan(tester.getTopLeft(sample(0)).dy),
      );
      expect(sample(4), findsNothing);
      expect(sample(5), findsOneWidget);
      await tester.tap(sample(3));
      await tester.pumpAndSettle();
      expect(fixture.ui.location, '/muestras/m/synthetic-sample-3');
    },
  );

  testWidgets('Actualizar usa la sincronización existente de TikTok', (
    tester,
  ) async {
    final fixture = _HomeFixture();
    await _mount(tester, fixture);
    await tester.tap(find.text('Actualizar'));
    await tester.pumpAndSettle();
    expect(fixture.syncRequests, 1);
    expect(find.textContaining('Actualización solicitada'), findsOneWidget);
  });

  testWidgets('Una sesión sin conexión shop ofrece Ajustes de TikTok', (
    tester,
  ) async {
    final fixture = _HomeFixture(disconnected: true);
    await _mount(tester, fixture);
    expect(find.text('Conecta tu cuenta de TikTok Shop'), findsOneWidget);
    await tester.tap(find.text('Conectar cuenta'));
    await tester.pumpAndSettle();
    expect(fixture.ui.location, '/ajustes/tiktok');
    expect(fixture.syncRequests, 0);
  });

  testWidgets('La sesión no disponible conserva resultados y prioridades', (
    tester,
  ) async {
    await _mount(tester, _HomeFixture(sessionUnavailable: true));
    expect(find.textContaining('No pudimos cargar tu cuenta.'), findsOneWidget);
    expect(find.text(r'$12,345'), findsOneWidget);
    expect(find.text('Tus prioridades'), findsOneWidget);
    expect(find.text('Conectar cuenta'), findsNothing);
  });

  testWidgets('No muestra ceros inventados cuando no hay datos', (
    tester,
  ) async {
    await _mount(tester, _HomeFixture(empty: true), textScale: 1.44);
    expect(
      find.descendant(
        of: find.byKey(const ValueKey('home-history-metrics')),
        matching: find.text('—'),
      ),
      findsNWidgets(3),
    );
    expect(find.text(r'$0'), findsNothing);
    expect(find.text('0'), findsNothing);
    expect(find.text('Todo empieza con tus muestras'), findsOneWidget);
    await tester.scrollUntilVisible(
      find.text('Seguidores de TikTok no disponibles'),
      350,
      maxScrolls: 30,
    );
    expect(tester.takeException(), isNull);
  }, variant: TargetPlatformVariant.only(TargetPlatform.windows));
}
