import 'dart:convert';

import 'package:corte/app.dart';
import 'package:corte/auth/auth_controller.dart';
import 'package:corte/platform/corte_runtime.dart';
import 'package:corte/platform/data_store.dart';
import 'package:corte/ui/shell.dart';
import 'package:corte/ui/theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

const _path = '/api/catalogo/vitrina';
final _scope = 'a' * 64;

class _MemoryStore implements CorteDataStore {
  final _data = <String, String>{};

  @override
  Future<String?> read(String key) async => _data[key];

  @override
  Future<void> write(String key, String value) async {
    _data[key] = value;
  }

  @override
  Future<void> remove(String key) async {
    _data.remove(key);
  }
}

http.Response _json(Object body, [int status = 200]) => http.Response.bytes(
  utf8.encode(jsonEncode(body)),
  status,
  headers: {'content-type': 'application/json; charset=utf-8'},
);

Map<String, Object?> _product(String id, String title) => {
  'product_id': id,
  'titulo': title,
  'tienda': 'Tienda de prueba',
  'precio_min': '120.15',
  'precio_max': '120.15',
  'moneda': 'MXN',
};

Future<CorteUiController> _app(
  WidgetTester tester, {
  required Map<String, bool> capabilities,
  required http.Response Function(http.Request request) showcase,
  bool compact = false,
}) async {
  tester.view.devicePixelRatio = 1;
  tester.view.physicalSize = compact
      ? const Size(390, 1000)
      : const Size(1300, 1000);
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  final auth = CorteAuthController(
    runtime: CorteRuntime(
      platform: 'web',
      baseUri: Uri.parse(corteCloudOrigin),
    ),
    client: MockClient(
      (request) async => switch (request.url.path) {
        '/api/session' => _json({'capacidades': capabilities}),
        '/api/analitica/productos' => _json({'items': [], 'total': 0}),
        _ => showcase(request),
      },
    ),
  );
  final ui = CorteUiController(auth: auth)..replace('/productos');
  ui.repo.attachStore(_MemoryStore());
  ui.repo.setScopes(ownerScope: 'owner', cacheScope: _scope);
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

Future<void> _tap(WidgetTester tester, Finder finder) async {
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

  testWidgets('LIVE conserva su ancla de paginación y es de solo lectura', (
    tester,
  ) async {
    final reads = <Map<String, String>>[];
    await _app(
      tester,
      capabilities: {
        'vitrina_creator': true,
        'vitrina_creator_escribir': true,
        'enlaces_afiliado_creator': true,
      },
      showcase: (request) {
        if (request.url.path != _path) return _json({}, 404);
        expect(request.method, 'GET');
        final query = request.url.queryParameters;
        reads.add(query);
        if (query['origin'] == 'LIVE') {
          if (query['cursor'] == 'live-2') {
            return _json({
              'productos': [
                {
                  ..._product('202', 'Segunda página LIVE'),
                  'estado_agregado': 'NOT_ADDED',
                },
              ],
            });
          }
          return _json({
            'productos': [
              {
                ..._product('201', 'Primer producto LIVE'),
                'estado_agregado': 'ADDED',
              },
            ],
            'cursor_siguiente': 'live-2',
          });
        }
        return _json({
          'productos': [_product('101', 'Producto de vitrina')],
          'cursor_siguiente': 'vitrina-2',
        });
      },
    );
    await _tap(tester, find.text('Vitrina'));
    expect(find.text('Producto de vitrina'), findsOneWidget);
    await _tap(tester, find.text('Productos para LIVE'));
    expect(find.text('Producto de vitrina'), findsNothing);
    expect(find.text('Primer producto LIVE'), findsOneWidget);
    expect(find.textContaining('Agregado según TikTok'), findsOneWidget);
    expect(find.text('Agregar productos'), findsNothing);
    expect(find.text('Fijar arriba'), findsNothing);
    expect(find.text('Quitar'), findsNothing);
    expect(find.text('Generar enlace'), findsNothing);
    await _tap(tester, find.text('Cargar más'));
    expect(find.text('Segunda página LIVE'), findsOneWidget);
    expect(find.textContaining('Pendiente de agregar'), findsOneWidget);
    await _tap(tester, find.widgetWithText(ChoiceChip, 'Vitrina'));
    expect(find.text('Primer producto LIVE'), findsNothing);
    expect(find.text('Producto de vitrina'), findsOneWidget);
    expect(find.text('Agregar productos'), findsOneWidget);
    expect(reads, [
      {'limit': '20'},
      {'limit': '20', 'origin': 'LIVE'},
      {'limit': '20', 'origin': 'LIVE', 'cursor': 'live-2'},
      {'limit': '20'},
    ]);
  }, variant: const TargetPlatformVariant({TargetPlatform.windows}));

  testWidgets('sin permiso de lectura no consulta la vitrina', (tester) async {
    final requests = <http.Request>[];
    final ui = await _app(
      tester,
      capabilities: {'vitrina_creator': false},
      showcase: (request) {
        requests.add(request);
        return _json({}, 404);
      },
    );
    expect(find.text('Vitrina'), findsNothing);
    ui.go('/productos?segmento=vitrina');
    await tester.pumpAndSettle();
    expect(find.text('Vitrina no disponible'), findsOneWidget);
    expect(requests.where((request) => request.url.path == _path), isEmpty);
  }, variant: const TargetPlatformVariant({TargetPlatform.windows}));

  testWidgets(
    'vitrina móvil pagina, agrega un lote parcial y pide confirmación',
    (tester) async {
      final writes = <http.Request>[];
      var pages = 0;
      await _app(
        tester,
        compact: true,
        capabilities: {
          'vitrina_creator': true,
          'vitrina_creator_escribir': true,
        },
        showcase: (request) {
          if (request.url.path == _path) {
            if (request.url.queryParameters['cursor'] == 'pagina-2') {
              return _json({
                'productos': [_product('202', 'Silla')],
              });
            }
            pages++;
            expect(request.url.queryParameters['limit'], '20');
            return _json({
              'productos': [
                _product('101', 'Florero'),
                if (pages > 1) _product('303', 'Maceta'),
              ],
              'cursor_siguiente': 'pagina-2',
            });
          }
          writes.add(request);
          if (request.url.path == '$_path/agregar') {
            return _json({
              'resultados': [
                {'product_id': '303', 'ok': true, 'mensaje': 'Agregado.'},
                {'product_id': '404', 'ok': false, 'mensaje': 'No disponible.'},
              ],
            });
          }
          if (request.url.path == '$_path/fijar') {
            return _json({
              'resultados': [
                {'product_id': '101', 'ok': true, 'mensaje': 'Fijado.'},
              ],
            });
          }
          return _json({
            'error': {
              'codigo': 'sin_permiso',
              'mensaje': 'TikTok rechazó quitar.',
            },
          }, 403);
        },
      );

      await _tap(tester, find.text('Vitrina'));
      expect(find.text('Florero'), findsOneWidget);
      await _tap(tester, find.text('Cargar más'));
      expect(find.text('Silla'), findsOneWidget);
      await _tap(tester, find.text('Agregar productos'));
      await tester.enterText(find.byType(TextFormField), '303, 404, 303');
      await _tap(tester, find.text('Agregar a la vitrina'));
      expect(writes.single.headers['x-corte-cache-scope'], _scope);
      expect(jsonDecode(writes.single.body), {
        'product_ids': ['303', '404'],
      });
      expect(find.text('303 · Agregado.'), findsOneWidget);
      expect(find.text('404 · No disponible.'), findsOneWidget);
      expect(find.text('Maceta'), findsOneWidget);
      expect(pages, 2);

      await _tap(tester, find.text('Fijar arriba').first);
      await _tap(tester, find.text('Cancelar'));
      expect(writes, hasLength(1));
      await _tap(tester, find.text('Fijar arriba').first);
      await _tap(tester, find.text('Fijar producto'));
      expect(writes.last.url.path, '$_path/fijar');
      expect(find.text('101 · Fijado.'), findsOneWidget);

      await _tap(tester, find.text('Quitar').first);
      await _tap(tester, find.text('Quitar producto'));
      expect(writes.last.url.path, '$_path/quitar');
      expect(find.text('TikTok rechazó quitar.'), findsOneWidget);
      expect(find.text('Florero'), findsOneWidget);
    },
    variant: const TargetPlatformVariant({TargetPlatform.android}),
  );

  testWidgets('genera enlaces con permiso y rechaza dominios ajenos', (
    tester,
  ) async {
    final links = <http.Request>[];
    await _app(
      tester,
      capabilities: {
        'vitrina_creator': true,
        'vitrina_creator_escribir': false,
        'enlaces_afiliado_creator': true,
      },
      showcase: (request) {
        if (request.url.path == _path) {
          return _json({
            'productos': [_product('101', 'Florero')],
          });
        }
        links.add(request);
        return _json({
          'resultados': [
            {
              'product_id': '101',
              'enlace': links.length == 1
                  ? 'https://shop.tiktok.com/view/product/101'
                  : 'https://shop.tiktok.com.example.org/101',
            },
          ],
        });
      },
    );
    await _tap(tester, find.text('Vitrina'));
    expect(find.text('Agregar productos'), findsNothing);
    expect(find.text('Fijar arriba'), findsNothing);
    await _tap(tester, find.widgetWithText(TextButton, 'Generar enlace'));
    await _tap(tester, find.widgetWithText(FilledButton, 'Generar enlace'));
    expect(links.single.url.path, '/api/catalogo/enlaces-afiliado');
    expect(links.single.headers['x-corte-cache-scope'], _scope);
    expect(jsonDecode(links.single.body), {
      'product_ids': ['101'],
    });
    expect(find.text('Copiar enlace'), findsOneWidget);
    expect(find.text('Abrir enlace'), findsOneWidget);
    await _tap(tester, find.widgetWithText(TextButton, 'Generar enlace'));
    await tester.enterText(find.byType(TextFormField).first, '123');
    await tester.enterText(find.byType(TextFormField).last, '456');
    await _tap(tester, find.widgetWithText(FilledButton, 'Generar enlace'));
    expect(jsonDecode(links.last.body), {
      'product_ids': ['101'],
      'publisher_id': '123',
      'campaign_id': '456',
    });
    expect(find.text('Copiar enlace'), findsNothing);
    expect(
      find.text('TikTok no devolvió un enlace de afiliado válido.'),
      findsOneWidget,
    );
  }, variant: const TargetPlatformVariant({TargetPlatform.windows}));

  testWidgets('una confirmación abierta no escribe tras cambiar la cuenta', (
    tester,
  ) async {
    var writes = 0;
    final ui = await _app(
      tester,
      capabilities: {'vitrina_creator': true, 'vitrina_creator_escribir': true},
      showcase: (request) {
        if (request.method == 'POST') writes++;
        return _json({
          'productos': [_product('101', 'Florero')],
        });
      },
    );
    await _tap(tester, find.text('Vitrina'));
    await _tap(tester, find.text('Quitar'));
    ui.repo.setScopes(ownerScope: 'otra', cacheScope: 'b' * 64);
    await _tap(tester, find.text('Quitar producto'));
    expect(writes, 0);
    expect(
      find.text('La cuenta cambió. Actualiza la vitrina y vuelve a elegir.'),
      findsOneWidget,
    );
  }, variant: const TargetPlatformVariant({TargetPlatform.windows}));
}
