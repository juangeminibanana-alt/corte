import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';

import '../lib/data/corte_repository.dart';

const scopeA =
    'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';
const scopeB =
    'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb';

class RequestRecord {
  RequestRecord(this.method, this.path, this.headers, this.body);
  final String method;
  final String path;
  final Map<String, String> headers;
  final Object? body;
}

class FakeAdapter implements CorteHttpAdapter {
  FakeAdapter(this.answer);
  final FutureOr<CorteResponse> Function(RequestRecord) answer;
  final requests = <RequestRecord>[];
  @override
  Future<CorteResponse> request(
    String method,
    String path, {
    Map<String, String> headers = const {},
    Object? body,
  }) async {
    final request = RequestRecord(method, path, headers, body);
    requests.add(request);
    return answer(request);
  }

  @override
  void close() {}
}

CorteResponse response(
  JsonMap body, {
  int status = 200,
  Map<String, String> headers = const {},
}) => CorteResponse(
  statusCode: status,
  headers: headers,
  bodyBytes: Uint8List.fromList(utf8.encode(jsonEncode(body))),
);

JsonMap operation(String id) => {
  'op_id': id,
  'tipo': 'nota.crear',
  'datos': {
    'id': 'nota-$id',
    'entidad': 'general',
    'entidad_id': null,
    'texto': 'Nota sintética',
  },
};

void main() {
  test(
    'snapshot preserves galleries, SKU, metadata, history and local fields immutably',
    () {
      final snapshot = SnapshotDto({
        'version_esquema': 1,
        'muestras': <JsonMap>[],
        'local': {
          'notas': [
            {'id': 'n1', 'texto': 'Anotación sintética'},
          ],
          'planes': [
            {'id': 'p1'},
          ],
        },
        'extras': {
          'muestras': {
            'm1': {
              'historial': [
                {
                  'campo': 'clase',
                  'antes': 'pendiente',
                  'despues': 'entregada',
                },
              ],
            },
          },
          'productos': {
            '900000000000000001': {
              'galeria': List.generate(
                12,
                (index) => '/img/g/900000000000000001-$index?v=0',
              ),
              'muestra': {
                'puede_solicitar': false,
                'skus': [
                  {
                    'sku_id': '900000000000000002',
                    'variante': 'Azul / M',
                    'precio_centavos': 12345,
                    'disponible': false,
                    'propiedades': [
                      {'nombre': 'Color', 'valor': 'Azul'},
                      {'nombre': 'Talla', 'valor': 'M'},
                    ],
                  },
                ],
              },
              'campo_futuro': {'preservado': true},
            },
          },
        },
        'meta_imagenes': {
          '/img/g/900000000000000001-0?v=1234abcd': {
            'w': 800,
            'h': 800,
            'lqip': null,
            'color': '#ffffff',
          },
        },
      });
      final product = snapshot.productoExtendido('900000000000000001')!;
      expect(product.galeria.length, 12);
      expect(product.muestra!.puedeSolicitar, false);
      expect(product.muestra!.skus.single.skuId, '900000000000000002');
      expect(product.muestra!.skus.single.precioCentavos, 12345);
      expect(product.muestra!.skus.single.propiedades.last.valor, 'M');
      expect(product.raw['campo_futuro']['preservado'], true);
      expect(
        snapshot.raw['extras']['muestras']['m1']['historial'],
        hasLength(1),
      );
      expect(snapshot.local!['notas'], hasLength(1));
      expect(snapshot.metaImagenes.values.single.ancho, 800);
      expect(
        () => product.raw['galeria'].add('/img/p/incorrecta'),
        throwsUnsupportedError,
      );
      expect(
        () => product.raw['muestra']['skus'][0]['disponible'] = true,
        throwsUnsupportedError,
      );
    },
  );

  test(
    'video cover accepts only the same video identity and never its product photo',
    () {
      expect(
        VideoDto({
          'content_id': '9001',
          'miniatura': '/img/p/100?v=1234abcd',
        }).portada,
        isNull,
      );
      expect(
        VideoDto({
          'content_id': '9001',
          'portada': '/img/v/9002?v=1234abcd',
        }).portada,
        isNull,
      );
      expect(
        VideoDto({
          'content_id': '9001',
          'portada': '/img/v/9001?v=1234abcd',
        }).portada,
        '/img/v/9001?v=1234abcd',
      );
    },
  );

  test('money stays integer and absent Display metrics stay absent', () {
    expect(
      ProductoResumenDto({
        'product_id': '1',
        'precio_min_centavos': 12345,
      }).precioMinCentavos,
      12345,
    );
    expect(
      () => ProductoResumenDto({
        'product_id': '1',
        'precio_min_centavos': 123.45,
      }).precioMinCentavos,
      throwsFormatException,
    );
    expect(VideoDto({'content_id': '1'}).vistas, isNull);
  });

  test('canonical filters use sorted CSV and backend boolean format', () {
    final path = rutaCanonica('/api/muestras', {
      'grupo': ['vencida', 'pausada'],
      'recibidas': false,
      'q': 'Café',
    });
    final uri = Uri.parse(path);
    expect(uri.queryParameters['grupo'], 'pausada,vencida');
    expect(uri.queryParameters['recibidas'], '0');
    expect(uri.queryParameters['q'], 'Café');
    expect(
      () => rutaCanonica('https://other.invalid/api/muestras', {}),
      throwsArgumentError,
    );
    expect(
      () => rutaCanonica('/api/native/auth/poll', {}),
      throwsArgumentError,
    );
  });

  test(
    'ETag 304 reuses the matching owner cache without fabricating a body',
    () async {
      var call = 0;
      final adapter = FakeAdapter((request) {
        if (call++ == 0)
          return response(
            {
              'items': [
                {'titulo': 'Sintético'},
              ],
            },
            headers: {'ETag': 'W/"dv1-lr2-ir3-f1"'},
          );
        expect(request.headers['If-None-Match'], 'W/"dv1-lr2-ir3-f1"');
        return CorteResponse(
          statusCode: 304,
          headers: {},
          bodyBytes: Uint8List(0),
        );
      });
      final repo = CorteRepository(adapter: adapter, cacheScope: scopeA);
      final first = await repo.get('/api/muestras');
      final second = await repo.get('/api/muestras');
      expect(second, same(first));
      expect(repo.sinConexion, false);
    },
  );

  test('304 without a matching copy is an error', () async {
    final repo = CorteRepository(
      adapter: FakeAdapter(
        (_) => CorteResponse(
          statusCode: 304,
          headers: {},
          bodyBytes: Uint8List(0),
        ),
      ),
    );
    await expectLater(
      repo.get('/api/muestras'),
      throwsA(
        isA<ErrorApi>().having(
          (error) => error.codigo,
          'codigo',
          'cache_invalida',
        ),
      ),
    );
  });

  test(
    'an old in-flight response cannot appear after a creator switch',
    () async {
      final old = Completer<CorteResponse>();
      final adapter = FakeAdapter((_) => old.future);
      final repo = CorteRepository(
        adapter: adapter,
        ownerScope: 'owner',
        cacheScope: scopeA,
      );
      final pending = repo.get('/api/muestras');
      repo.setScopes(ownerScope: 'owner', cacheScope: scopeB);
      old.complete(
        response({
          'items': [
            {'titulo': 'Datos anteriores sintéticos'},
          ],
        }),
      );
      await expectLater(
        pending,
        throwsA(
          isA<ErrorApi>().having(
            (error) => error.codigo,
            'codigo',
            'sesion_cambiada',
          ),
        ),
      );
    },
  );

  test('failed POST is sent once and never retried automatically', () async {
    final adapter = FakeAdapter(
      (_) =>
          throw const CorteTransportException('timeout', 'No hubo respuesta.'),
    );
    final repo = CorteRepository(adapter: adapter);
    await expectLater(
      repo.post('/api/notas', body: {'id': 'n1', 'texto': 'Sintética'}),
      throwsA(isA<ErrorApi>()),
    );
    expect(adapter.requests.length, 1);
    expect((adapter.requests.single.body as Map)['texto'], 'Sintética');
  });

  test('direct 409 keeps the current revision and sanitized message', () async {
    final repo = CorteRepository(
      adapter: FakeAdapter(
        (_) => response({
          'error': {
            'codigo': 'conflicto',
            'mensaje': 'Cambió en otro equipo.',
            'vigente': {'id': 'n1', 'rev': 5},
          },
        }, status: 409),
      ),
    );
    await expectLater(
      repo.patch('/api/notas/n1', body: {'texto': 'Cambio', 'rev': 4}),
      throwsA(
        isA<ErrorApi>().having(
          (error) => error.vigente?['rev'],
          'vigente.rev',
          5,
        ),
      ),
    );
  });

  test(
    'offline save is durable and replay retains op_id after lost response',
    () async {
      final store = MemoryCorteDataStore();
      final offline = CorteRepository(
        adapter: FakeAdapter(
          (_) => throw const CorteTransportException('red', 'Sin conexión.'),
        ),
        store: store,
        ownerScope: 'owner',
        cacheScope: scopeA,
      );
      final saved = await offline.guardarOps([operation('op1')]);
      expect(saved.enCola, true);
      expect(
        jsonMap((await offline.opsPendientes()).single['op'])['op_id'],
        'op1',
      );
      final adapter = FakeAdapter((request) {
        if (request.method == 'GET') return response({'cache_scope': scopeA});
        expect(request.headers['X-Corte-Cache-Scope'], scopeA);
        expect(((request.body as Map)['ops'] as List).single['op_id'], 'op1');
        return response({
          'resultados': [
            {
              'op_id': 'op1',
              'estado': 'duplicada',
              'objeto': {'id': 'nota-op1', 'rev': 1},
            },
          ],
          'local_rev': 1,
        });
      });
      final online = CorteRepository(
        adapter: adapter,
        store: store,
        cacheScope: scopeA,
      );
      await online.flushOps();
      expect(await online.opsPendientes(), isEmpty);
    },
  );

  for (final state in ['conflicto', 'invalida']) {
    test(
      '$state is retained in outbox and thrown instead of false success',
      () async {
        final store = MemoryCorteDataStore();
        final repo = CorteRepository(
          store: store,
          cacheScope: scopeA,
          adapter: FakeAdapter((request) {
            if (request.method == 'GET')
              return response({'cache_scope': scopeA});
            return response({
              'resultados': [
                {
                  'op_id': 'op1',
                  'estado': state,
                  'error': 'Revisa el dato.',
                  'objeto': {'id': 'nota-op1', 'rev': 8},
                },
              ],
              'local_rev': 8,
            });
          }),
        );
        await expectLater(
          repo.guardarOps([operation('op1')]),
          throwsA(
            isA<ErrorApi>().having(
              (error) => error.vigente?['rev'],
              'vigente.rev',
              8,
            ),
          ),
        );
        expect(await repo.opsPendientes(), isEmpty);
        expect(
          (await repo.opsPendientes(incluirConflictos: true)).single['estado'],
          state,
        );
      },
    );
  }

  test(
    'creator mismatch stops replay and preserves the previous namespace',
    () async {
      final store = MemoryCorteDataStore();
      final adapter = FakeAdapter((_) => response({'cache_scope': scopeB}));
      final repo = CorteRepository(
        adapter: adapter,
        store: store,
        cacheScope: scopeA,
      );
      await repo.encolarOps([operation('op1')]);
      await expectLater(
        repo.flushOps(),
        throwsA(
          isA<ErrorApi>().having(
            (error) => error.codigo,
            'codigo',
            'cuenta_cambiada',
          ),
        ),
      );
      expect(
        adapter.requests.every((request) => request.method == 'GET'),
        true,
      );
      expect(await store.read('corte.data.$scopeA.outbox'), isNotNull);
      expect(await repo.opsPendientes(), isEmpty);
    },
  );

  test(
    'snapshot persistence keeps extras after recreating the repository',
    () async {
      final store = MemoryCorteDataStore();
      final first = CorteRepository(
        adapter: FakeAdapter(
          (_) => response(
            {
              'version_esquema': 1,
              'muestras': <JsonMap>[],
              'local': {'notas': <JsonMap>[]},
              'extras': {
                'productos': {
                  '1': {
                    'galeria': ['/img/g/1-0?v=1234abcd'],
                  },
                },
              },
            },
            headers: {'etag': 'W/"dv1-lr1-ir1-f1"'},
          ),
        ),
        store: store,
        cacheScope: scopeA,
      );
      await first.snapshot();
      final next = CorteRepository(
        adapter: FakeAdapter(
          (_) => throw const CorteTransportException('red', 'Sin conexión.'),
        ),
        store: store,
        cacheScope: scopeA,
      );
      final saved = await next.snapshot();
      expect(
        saved.productoExtendido('1')!.galeria.single,
        '/img/g/1-0?v=1234abcd',
      );
      expect(next.sinConexion, true);
    },
  );

  test(
    'missing cache scope keeps online operation working and disables replay',
    () async {
      final adapter = FakeAdapter(
        (request) => response({
          'resultados': [
            {'op_id': 'op1', 'estado': 'aplicada'},
          ],
        }),
      );
      final repo = CorteRepository(
        adapter: adapter,
        store: MemoryCorteDataStore(),
      );
      expect((await repo.guardarOps([operation('op1')])).enCola, false);
      expect(adapter.requests.single.path, '/api/local/ops');
      expect(
        adapter.requests.single.headers.containsKey('X-Corte-Cache-Scope'),
        false,
      );
      await expectLater(
        repo.encolarOps([operation('op2')]),
        throwsA(isA<ErrorApi>()),
      );
      expect((await repo.flushOps()).resultados, isEmpty);
    },
  );
}
