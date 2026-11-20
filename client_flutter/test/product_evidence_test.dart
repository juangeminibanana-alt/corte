// All product evidence below is synthetic test data, never production content.
import 'dart:async';
import 'dart:convert';

import 'package:corte/app.dart';
import 'package:corte/auth/auth_controller.dart';
import 'package:corte/data/corte_repository.dart';
import 'package:corte/platform/corte_runtime.dart';
import 'package:corte/ui/desktop.dart';
import 'package:corte/ui/product_evidence.dart';
import 'package:corte/ui/theme.dart';
import 'package:corte/ui/widgets.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

const _scopeA =
    'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';
const _scopeB =
    'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb';
const _photo = '/img/e/100-0123456789abcdef?v=1234abcd';
const _source = {
  'tipo': 'captura_tiktok',
  'nombre': 'Fuente sintética',
  'url': 'https://shop.tiktok.com/view/product/100',
};

JsonMap _review(
  String id, {
  String? text,
  bool? verified,
  List<String> photos = const [],
}) => {
  'id': id,
  'texto': text ?? 'Opinión sintética $id',
  'estrellas': 4,
  'fecha': 1800000000,
  'variante': 'Azul / M',
  'compra_verificada': verified,
  'imagenes': photos,
};

JsonMap _reviews({List<JsonMap>? items, String? next, int? total = 20}) => {
  'estado': 'disponible',
  'fuente': _source,
  'consultado_at': 1800000000,
  'promedio': 4.2,
  'total': total,
  'cargadas': 20,
  'items': items ?? [_review('r1')],
  'siguiente_cursor': next,
};

JsonMap _evidence({JsonMap? reviews, bool chartImage = false}) => {
  'evidencia_rev': 1,
  'tabla_tallas': {
    'estado': 'disponible',
    'fuente': _source,
    'consultado_at': 1800000000,
    'tabla': {
      'columnas': [
        'Talla',
        'Contorno de pecho',
        'Largo de manga',
        'Largo total',
      ],
      'filas': [
        ['M', '96', '62', '68'],
        ['L', '102', '64', '70'],
      ],
      'unidad': 'cm',
      'imagenes': chartImage ? [_photo] : <String>[],
    },
  },
  'resenas': reviews ?? _reviews(),
};

http.Response _json(Object value, {int status = 200}) => http.Response(
  jsonEncode(value),
  status,
  headers: {'content-type': 'application/json; charset=utf-8'},
);

class _Fixture {
  _Fixture() {
    auth = CorteAuthController(
      runtime: CorteRuntime(
        platform: 'web',
        baseUri: Uri.parse(corteCloudOrigin),
      ),
      client: MockClient(_handle),
    );
    ui = CorteUiController(auth: auth);
    ui.repo.attachStore(MemoryCorteDataStore());
    ui.repo.setScopes(ownerScope: _scopeA, cacheScope: _scopeA);
  }

  late final CorteAuthController auth;
  late final CorteUiController ui;
  final pageRequests = <Uri>[];
  final imageRequests = <Uri>[];
  Future<http.Response> Function(http.Request)? page;
  Future<http.Response> Function(http.Request)? extract;
  final extractRequests = <http.Request>[];
  final importRequests = <http.Request>[];
  Future<http.Response> Function(http.Request)? importEvidence;

  Future<http.Response> _handle(http.Request request) async {
    if (request.method == 'PUT' && request.url.path.endsWith('/evidencia')) {
      importRequests.add(request);
      return importEvidence == null
          ? _json({'rev': 1})
          : await importEvidence!(request);
    }
    if (request.url.path.endsWith('/extraer')) {
      extractRequests.add(request);
      return extract == null ? _json({'rev': 1}) : await extract!(request);
    }
    if (request.url.path.startsWith('/img/')) {
      imageRequests.add(request.url);
      final suffix = request.url.queryParameters['t'];
      return http.Response.bytes(
        base64Decode(
          'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR4nGNgAAIAAAUAAXpeqz8AAAAASUVORK5CYII=',
        ),
        200,
        headers: {
          'content-type': 'image/png',
          'etag': '"1234abcd${suffix == null ? '' : '-$suffix'}"',
        },
      );
    }
    if (request.url.path.endsWith('/resenas')) {
      pageRequests.add(request.url);
      return page == null
          ? _json({
              'product_id': '100',
              'rev': 1,
              'resenas': _reviews(items: []),
            })
          : await page!(request);
    }
    switch (request.url.path) {
      case '/api/preferencias':
        return _json({'rev': 1, 'tema': 'claro'});
      case '/api/cloud/revision':
        return _json({
          'revision': 'synthetic-stable',
          'owner_scope': _scopeA,
          'cache_scope': _scopeA,
        });
      case '/api/snapshot':
        return _json({
          'version_esquema': 1,
          'muestras': [],
          'local': {
            'preferencias': {'rev': 1},
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
  _Fixture fixture,
  JsonMap extended, {
  double width = 390,
  double scale = 1,
  Brightness brightness = Brightness.light,
  String productId = '100',
  VoidCallback? openOriginal,
  Future<JsonMap> Function(String)? capture,
}) async {
  tester.view.physicalSize = Size(width, 1500);
  tester.view.devicePixelRatio = 1;
  final base = corteTheme(brightness: brightness);
  await tester.pumpWidget(
    CorteScope(
      controller: fixture.ui,
      child: MaterialApp(
        theme: width >= 1000 ? desktopWorkspaceTheme(base) : base,
        builder: (context, child) => MediaQuery(
          data: MediaQuery.of(
            context,
          ).copyWith(textScaler: TextScaler.linear(scale)),
          child: child!,
        ),
        home: Scaffold(
          body: SingleChildScrollView(
            padding: const EdgeInsets.all(20),
            child: ProductEvidence(
              productId: productId,
              extended: extended,
              openOriginal: openOriginal,
              captureFromDevice: capture,
            ),
          ),
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
}

void _cleanup(WidgetTester tester, _Fixture fixture) {
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  addTearDown(fixture.dispose);
}

Future<void> _tapMore(WidgetTester tester) async {
  final button = find.widgetWithText(OutlinedButton, 'Ver más reseñas');
  await tester.ensureVisible(button);
  await tester.tap(button);
}

void main() {
  testWidgets(
    'native capture uploads only public blocks to the scoped Google endpoint',
    (tester) async {
      final fixture = _Fixture();
      _cleanup(tester, fixture);
      fixture.importEvidence = (_) async => _json({
        'rev': 1,
        'tabla_tallas': _evidence()['tabla_tallas'],
        'resenas': _reviews(),
      });
      var captures = 0;
      await _mount(
        tester,
        fixture,
        {'evidencia_rev': 0},
        capture: (id) async {
          expect(id, '100');
          captures++;
          return {
            'tabla_tallas': _evidence()['tabla_tallas'],
            'resenas': _reviews(),
          };
        },
      );
      await tester.tap(
        find.widgetWithText(OutlinedButton, 'Obtener tallas y reseñas'),
      );
      await tester.pumpAndSettle();
      expect(captures, 1);
      expect(fixture.extractRequests, isEmpty);
      final request = fixture.importRequests.single;
      expect(request.url.host, 'corte-e-book-21589.web.app');
      expect(request.headers['X-Corte-Cache-Scope'], _scopeA);
      expect(jsonMap(jsonDecode(request.body))['rev'], 0);
      expect(find.text('Unidad: cm'), findsOneWidget);
    },
  );

  testWidgets('native source result cannot be saved after an account change', (
    tester,
  ) async {
    final fixture = _Fixture();
    _cleanup(tester, fixture);
    final pending = Completer<JsonMap>();
    Future<JsonMap> capture(String _) => pending.future;
    await _mount(tester, fixture, {'evidencia_rev': 0}, capture: capture);
    await tester.tap(
      find.widgetWithText(OutlinedButton, 'Obtener tallas y reseñas'),
    );
    await tester.pump();
    fixture.ui.repo.setScopes(ownerScope: _scopeB, cacheScope: _scopeB);
    await _mount(tester, fixture, {'evidencia_rev': 0}, capture: capture);
    pending.complete({
      'tabla_tallas': _evidence()['tabla_tallas'],
      'resenas': _reviews(),
    });
    await tester.pumpAndSettle();
    expect(fixture.importRequests, isEmpty);
    expect(fixture.extractRequests, isEmpty);
  });
  testWidgets('partial public reviews are explicitly shown as a preview', (
    tester,
  ) async {
    final fixture = _Fixture();
    _cleanup(tester, fixture);
    await _mount(
      tester,
      fixture,
      _evidence(reviews: {..._reviews(total: 60), 'cargadas': 3}),
    );
    expect(
      find.textContaining('Vista previa de 3 de 60 reseñas.'),
      findsOneWidget,
    );
    expect(find.text('60 reseñas en la fuente'), findsOneWidget);
  });
  testWidgets(
    'extract saves source-backed blocks with current revision and creator scope',
    (tester) async {
      final fixture = _Fixture();
      _cleanup(tester, fixture);
      fixture.extract = (request) async => _json({
        'rev': 1,
        'tabla_tallas': _evidence()['tabla_tallas'],
        'resenas': _reviews(),
      });
      await _mount(tester, fixture, {'evidencia_rev': 0});
      await tester.tap(
        find.widgetWithText(OutlinedButton, 'Obtener tallas y reseñas'),
      );
      await tester.pumpAndSettle();
      expect(fixture.extractRequests.single.method, 'POST');
      expect(jsonDecode(fixture.extractRequests.single.body), {'rev': 0});
      expect(
        fixture.extractRequests.single.headers['X-Corte-Cache-Scope'],
        _scopeA,
      );
      expect(find.text('Unidad: cm'), findsOneWidget);
      expect(find.text('Opinión sintética r1'), findsOneWidget);
    },
  );

  testWidgets('source failure retains previously saved chart and reviews', (
    tester,
  ) async {
    final fixture = _Fixture();
    _cleanup(tester, fixture);
    fixture.extract = (request) async => _json({
      'error': {
        'codigo': 'fuente_verificacion_requerida',
        'mensaje': 'TikTok requiere verificar el acceso.',
      },
    }, status: 503);
    await _mount(tester, fixture, _evidence());
    await tester.tap(
      find.widgetWithText(OutlinedButton, 'Obtener tallas y reseñas'),
    );
    await tester.pumpAndSettle();
    expect(
      find.textContaining(
        'Actualiza este producto desde la app Android o Windows',
      ),
      findsOneWidget,
    );
    expect(find.text('Unidad: cm'), findsOneWidget);
    expect(find.text('Opinión sintética r1'), findsOneWidget);
  });

  for (final width in [390.0, 1536.0]) {
    for (final brightness in Brightness.values) {
      testWidgets(
        'source-backed table and reviews fit $width $brightness at text scale 2',
        (tester) async {
          final fixture = _Fixture();
          _cleanup(tester, fixture);
          await _mount(
            tester,
            fixture,
            _evidence(),
            width: width,
            scale: 2,
            brightness: brightness,
          );
          expect(find.text('Unidad: cm'), findsOneWidget);
          expect(find.text('Contorno de pecho'), findsOneWidget);
          expect(find.text('96'), findsOneWidget);
          expect(find.text('102'), findsOneWidget);
          expect(find.text('Opinión sintética r1'), findsOneWidget);
          expect(find.text('20 reseñas en la fuente'), findsOneWidget);
          final layout = tester.takeException();
          expect(
            layout,
            isNull,
            reason: layout is FlutterError
                ? layout.diagnostics
                      .map((node) => node.toStringDeep())
                      .join('\n')
                : null,
          );
          final horizontal = find.byWidgetPredicate(
            (widget) =>
                widget is SingleChildScrollView &&
                widget.scrollDirection == Axis.horizontal,
          );
          expect(horizontal, findsOneWidget);
          expect(
            MediaQuery.textScalerOf(
              tester.element(find.byType(ProductEvidence)),
            ).scale(14),
            28,
          );
        },
        variant: TargetPlatformVariant.only(
          width < 1000 ? TargetPlatform.android : TargetPlatform.windows,
        ),
      );
    }
  }

  testWidgets(
    'missing access is distinct from confirmed zero reviews and original is actionable',
    (tester) async {
      final fixture = _Fixture();
      _cleanup(tester, fixture);
      var opens = 0;
      await _mount(tester, fixture, {}, openOriginal: () => opens++);
      expect(
        find.textContaining('Todavía no se han obtenido las opiniones'),
        findsOneWidget,
      );
      expect(find.text('0 reseñas en la fuente'), findsNothing);
      expect(
        find.textContaining('confirma que todavía no hay reseñas'),
        findsNothing,
      );
      await tester.tap(find.text('Consultar producto en TikTok Shop').first);
      expect(opens, 1);
      await _mount(tester, fixture, {'resenas': _reviews(items: [], total: 0)});
      expect(find.text('0 reseñas en la fuente'), findsOneWidget);
      expect(
        find.text(
          'Esta fuente confirma que todavía no hay reseñas publicadas.',
        ),
        findsOneWidget,
      );
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'purchase verification only appears when source explicitly confirms it',
    (tester) async {
      final fixture = _Fixture();
      _cleanup(tester, fixture);
      await _mount(tester, fixture, {
        'resenas': _reviews(
          items: [
            _review('unknown'),
            _review('false', verified: false),
            _review('true', verified: true),
          ],
        ),
      });
      expect(find.text('Compra verificada por la fuente'), findsOneWidget);
      expect(find.text('Opinión sintética unknown'), findsOneWidget);
      expect(find.text('Opinión sintética false'), findsOneWidget);
      expect(find.text('Opinión sintética true'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'buyer photo enlarges using original private image and dialog closes',
    (tester) async {
      final fixture = _Fixture();
      _cleanup(tester, fixture);
      await _mount(tester, fixture, {
        'resenas': _reviews(
          items: [
            _review('photo', photos: [_photo]),
          ],
        ),
      });
      expect(
        fixture.imageRequests.any((url) => url.queryParameters['t'] == 'sm'),
        isTrue,
      );
      final photo = find.byType(CortePhoto);
      await tester.ensureVisible(photo);
      await tester.tap(photo);
      await tester.pumpAndSettle();
      expect(find.byType(Dialog), findsOneWidget);
      expect(find.byType(InteractiveViewer), findsOneWidget);
      expect(
        fixture.imageRequests.any(
          (url) =>
              !url.queryParameters.containsKey('t') &&
              url.queryParameters['v'] == '1234abcd',
        ),
        isTrue,
      );
      await tester.tap(find.byTooltip('Cerrar imagen'));
      await tester.pumpAndSettle();
      expect(find.byType(Dialog), findsNothing);
      expect(find.text('Opinión sintética photo'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'review pagination forwards cursor and deduplicates stable review ids',
    (tester) async {
      final fixture = _Fixture();
      _cleanup(tester, fixture);
      fixture.page = (_) async => _json({
        'product_id': '100',
        'rev': 1,
        'resenas': _reviews(items: [_review('r1'), _review('r2')]),
      });
      await _mount(tester, fixture, {'resenas': _reviews(next: '20')});
      await _tapMore(tester);
      await tester.pumpAndSettle();
      expect(fixture.pageRequests.single.queryParameters['cursor'], '20');
      expect(find.text('Opinión sintética r1'), findsOneWidget);
      expect(find.text('Opinión sintética r2'), findsOneWidget);
      expect(find.text('Ver más reseñas'), findsNothing);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets('page error retains displayed comments and permits retry', (
    tester,
  ) async {
    final fixture = _Fixture();
    _cleanup(tester, fixture);
    fixture.page = (_) async => _json({
      'error': {'codigo': 'forbidden', 'mensaje': 'Error sintético'},
    }, status: 403);
    await _mount(tester, fixture, {'resenas': _reviews(next: '20')});
    await _tapMore(tester);
    await tester.pumpAndSettle();
    expect(find.text('Opinión sintética r1'), findsOneWidget);
    expect(
      find.textContaining('Conservamos las que ya estás viendo'),
      findsOneWidget,
    );
    expect(find.text('Ver más reseñas'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
    'a replacement capture restarts pagination and replaces the old revision and summary',
    (tester) async {
      final fixture = _Fixture();
      _cleanup(tester, fixture);
      fixture.page = (request) async => _json({
        'product_id': '100',
        'rev': 2,
        'resenas': _reviews(
          items: [
            _review(
              request.url.queryParameters['cursor'] == '0'
                  ? 'fresh-first-page'
                  : 'unjoined-new-second-page',
            ),
          ],
          total: 40,
        ),
      });
      await _mount(tester, fixture, {
        'evidencia_rev': 1,
        'resenas': _reviews(next: '20'),
      });
      await _tapMore(tester);
      await tester.pumpAndSettle();
      expect(fixture.pageRequests.map((url) => url.queryParameters['cursor']), [
        '20',
        '0',
      ]);
      expect(find.text('Opinión sintética r1'), findsNothing);
      expect(
        find.text('Opinión sintética unjoined-new-second-page'),
        findsNothing,
      );
      expect(find.text('Opinión sintética fresh-first-page'), findsOneWidget);
      expect(find.text('40 reseñas en la fuente'), findsOneWidget);
      expect(find.text('20 reseñas en la fuente'), findsNothing);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'changing product discards pages already loaded for the previous product',
    (tester) async {
      final fixture = _Fixture();
      _cleanup(tester, fixture);
      fixture.page = (_) async => _json({
        'product_id': '100',
        'rev': 1,
        'resenas': _reviews(items: [_review('extra')]),
      });
      await _mount(tester, fixture, {'resenas': _reviews(next: '20')});
      await _tapMore(tester);
      await tester.pumpAndSettle();
      expect(find.text('Opinión sintética extra'), findsOneWidget);
      await _mount(tester, fixture, {
        'resenas': _reviews(items: [_review('new-product')]),
      }, productId: '200');
      expect(find.text('Opinión sintética extra'), findsNothing);
      expect(find.text('Opinión sintética r1'), findsNothing);
      expect(find.text('Opinión sintética new-product'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'late review response cannot append across an owner and creator scope change',
    (tester) async {
      final fixture = _Fixture();
      _cleanup(tester, fixture);
      final pending = Completer<http.Response>();
      fixture.page = (_) => pending.future;
      await _mount(tester, fixture, {'resenas': _reviews(next: '20')});
      await _tapMore(tester);
      await tester.pump();
      expect(find.text('Cargando reseñas…'), findsOneWidget);
      fixture.ui.repo.setScopes(ownerScope: _scopeB, cacheScope: _scopeB);
      pending.complete(
        _json({
          'product_id': '100',
          'rev': 1,
          'resenas': _reviews(items: [_review('private-old-owner')]),
        }),
      );
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));
      expect(find.text('Opinión sintética private-old-owner'), findsNothing);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox.shrink());
    },
  );

  testWidgets(
    'changing account identity discards previously appended private pages even with identical initial JSON',
    (tester) async {
      final fixture = _Fixture();
      _cleanup(tester, fixture);
      final extended = {'resenas': _reviews(next: '20')};
      fixture.page = (_) async => _json({
        'product_id': '100',
        'rev': 1,
        'resenas': _reviews(items: [_review('old-owner-page')]),
      });
      await _mount(tester, fixture, extended);
      await _tapMore(tester);
      await tester.pumpAndSettle();
      expect(find.text('Opinión sintética old-owner-page'), findsOneWidget);
      fixture.ui.repo.setScopes(ownerScope: _scopeB, cacheScope: _scopeB);
      await _mount(tester, fixture, extended);
      expect(find.text('Opinión sintética old-owner-page'), findsNothing);
      expect(find.text('Opinión sintética r1'), findsOneWidget);
      expect(find.text('Ver más reseñas'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );
}
