import 'dart:typed_data';
import 'package:flutter_test/flutter_test.dart';
import '../lib/data/corte_repository.dart';
import '../lib/data/snapshot_projection.dart';
import '../lib/domain/messages.dart';
import 'corte_data_test.dart'
    show FakeAdapter, response, operation, scopeA, scopeB;

JsonMap fixtureSnapshot() => {
  'version_esquema': 1,
  'generado_at': DateTime.utc(2026, 11, 16, 18).millisecondsSinceEpoch ~/ 1000,
  'muestras': [
    {
      'application_id': 'm1',
      'producto': {'product_id': 'p1', 'titulo': 'Producto sintético'},
      'tienda': {'tienda_key': 't1'},
      'avance': {
        'plan_id': 'plan1',
        'etapa': 'planeada',
        'fecha_planeada': '2026-11-20',
        'rev': 1,
      },
    },
  ],
  'local': {
    'notas': [],
    'planes': [
      {
        'id': 'plan1',
        'application_id': 'm1',
        'estado': 'planeada',
        'fecha_plan': '2026-11-20',
        'rev': 1,
      },
    ],
    'recordatorios': [],
    'avisos': [],
    'plantillas': [],
    'preferencias': {'rev': 1, 'capacidad_diaria': 2},
  },
  'productos': [
    {'product_id': 'p1'},
  ],
  'videos': [],
  'tiendas': [],
  'ordenes_recientes': [],
  'dashboard': {
    '30d': {
      'ventas': {'total': 4},
    },
    'todo': {
      'periodo': {'desde': '2026-01-01', 'hasta': '2026-11-16'},
    },
  },
  'extras': {
    'productos': {
      'p1': {
        'galeria': ['/img/g/123-0?v=1234abcd'],
        'skus': [
          {
            'sku_id': 's1',
            'propiedades': [
              {'nombre': 'Color', 'valor': 'Café'},
            ],
          },
        ],
      },
    },
    'muestras': {
      'm1': {
        'historial': [
          {'campo': 'recibida', 'despues': true},
        ],
      },
    },
  },
};

class FailingStore extends MemoryCorteDataStore {
  bool fail = false;
  @override
  Future<void> write(String key, String value) async {
    if (fail) throw StateError('simulated disk failure');
    return super.write(key, value);
  }
}

void main() {
  test(
    'offline projects persisted full sample history and product gallery/SKU',
    () async {
      final store = MemoryCorteDataStore();
      final journal = CorteJournal(store, scopeA);
      await journal.guardarSnapshot(fixtureSnapshot(), 'snapshot-etag');
      final repo = CorteRepository(
        adapter: FakeAdapter((_) {
          throw const CorteTransportException('sin_internet', 'Sin conexión');
        }),
        cacheScope: scopeA,
        store: store,
      );
      final sample = await repo.get('/api/muestras/m1');
      expect((sample['historial'] as List).single['campo'], 'recibida');
      final product = await repo.get('/api/productos/p1');
      expect((product['extendido'] as Map)['galeria'], hasLength(1));
      expect(
        ((product['extendido'] as Map)['skus'] as List)
            .single['propiedades']
            .single['valor'],
        'Café',
      );
      expect(repo.sinConexion, isTrue);
    },
  );

  test(
    'queued note visible online and offline, rejected edits never overlay',
    () async {
      final store = MemoryCorteDataStore();
      await CorteJournal(
        store,
        scopeA,
      ).guardarSnapshot(fixtureSnapshot(), null);
      var online = true;
      final repo = CorteRepository(
        adapter: FakeAdapter((_) {
          if (!online)
            throw const CorteTransportException('sin_internet', 'Sin conexión');
          return response({'items': []});
        }),
        cacheScope: scopeA,
        store: store,
      );
      await repo.encolarOps([operation('note')]);
      expect((await repo.get('/api/notas'))['items'], hasLength(1));
      online = false;
      repo.invalidar();
      expect((await repo.get('/api/notas'))['items'], hasLength(1));
      await CorteJournal(store, scopeA).confirmar(
        [
          {'op_id': 'note', 'estado': 'invalida', 'error': 'No válida'},
        ],
        {'note'},
      );
      repo.invalidar();
      expect((await repo.get('/api/notas'))['items'], isEmpty);
      expect(await repo.opsPendientes(incluirConflictos: true), hasLength(1));
    },
  );

  test(
    'ACK updates private snapshot before outbox removal, survives restart',
    () async {
      final store = MemoryCorteDataStore();
      final journal = CorteJournal(store, scopeA);
      await journal.guardarSnapshot(fixtureSnapshot(), 'old-etag');
      await journal.encolar([operation('ack')]);
      final canonical = {
        ...jsonMap(operation('ack')['datos']),
        'rev': 1,
        'creado_at': 123,
      };
      await journal.confirmar(
        [
          {'op_id': 'ack', 'estado': 'aplicada', 'objeto': canonical},
        ],
        {'ack'},
      );
      expect(await journal.leerOps(), isEmpty);
      final saved = (await journal.leerSnapshot())!;
      expect(saved['etag'], isNull);
      expect((jsonMap(saved['snapshot'])['local'] as Map)['notas'], [
        canonical,
      ]);
    },
  );

  test('resolution replacement is atomic and rejects reuse of op_id', () async {
    final store = FailingStore();
    final journal = CorteJournal(store, scopeA);
    await journal.encolar([operation('old')]);
    await journal.confirmar(
      [
        {
          'op_id': 'old',
          'estado': 'conflicto',
          'objeto': {'id': 'note', 'rev': 3},
        },
      ],
      {'old'},
    );
    await expectLater(
      journal.reemplazar('old', operation('old')),
      throwsA(isA<ErrorApi>()),
    );
    store.fail = true;
    await expectLater(
      journal.reemplazar('old', operation('new')),
      throwsStateError,
    );
    expect(jsonMap((await journal.leerOps()).single['op'])['op_id'], 'old');
    store.fail = false;
    await journal.reemplazar('old', operation('new'));
    expect(jsonMap((await journal.leerOps()).single['op'])['op_id'], 'new');
    expect((await journal.leerOps()).single['estado'], 'pendiente');
    await journal.descartar('new');
    expect(await journal.leerOps(), isEmpty);
  });

  test(
    'disk failure prevents POST; creator change is never reported as queued success',
    () async {
      final store = FailingStore()..fail = true;
      final adapter = FakeAdapter((_) => (throw StateError('must not send')));
      final repo = CorteRepository(
        adapter: adapter,
        cacheScope: scopeA,
        store: store,
      );
      await expectLater(
        repo.guardarOps([operation('disk')]),
        throwsA(
          isA<ErrorApi>().having((e) => e.codigo, 'code', 'copia_no_guardada'),
        ),
      );
      expect(adapter.requests, isEmpty);
      final changed = CorteRepository(
        adapter: FakeAdapter((_) => (response({'cache_scope': scopeB}))),
        cacheScope: scopeA,
        store: MemoryCorteDataStore(),
      );
      await expectLater(
        changed.guardarOps([operation('changed')]),
        throwsA(
          isA<ErrorApi>().having((e) => e.codigo, 'code', 'cuenta_cambiada'),
        ),
      );
    },
  );

  test(
    'online pending plan edit uses actual existing plan and preserves fields',
    () {
      final snapshot = fixtureSnapshot();
      final data = {'items': snapshot['muestras']};
      final projected = aplicarPendientes('/api/muestras', data, [
        {
          'estado': 'pendiente',
          'op': {
            'op_id': 'plan-edit',
            'tipo': 'plan.editar',
            'id': 'plan1',
            'cambios': {
              'rev': 1,
              'estado': 'programada',
              'programada_para_at': 123456,
            },
          },
        },
      ]);
      final advance = (projected['items'] as List).single['avance'];
      expect(advance['etapa'], 'programada');
      expect(advance['fecha_planeada'], '2026-11-20');
      expect(advance['rev'], 2);
    },
  );

  test(
    'snapshot refuses truncated video or uncovered sales range instead of fake completeness',
    () {
      final snap = fixtureSnapshot();
      expect(
        proyectarSnapshot('/api/analitica/productos?desde=2026-11-01', snap),
        isNull,
      );
      expect(proyectarSnapshot('/api/dashboard?periodo=7d', snap), isNull);
      expect(proyectarSnapshot('/api/ordenes', snap), isNull);
      expect(
        proyectarSnapshot('/api/ordenes?desde=2026-11-01', snap),
        isNotNull,
      );
      snap['videos'] = List.generate(100, (i) => {'content_id': '$i'});
      expect(proyectarSnapshot('/api/analitica/videos', snap), isNull);
    },
  );

  test(
    'image retries same identity then persists and serves without a network',
    () async {
      final store = MemoryCorteDataStore();
      var calls = 0;
      final adapter = FakeAdapter((request) {
        calls++;
        if (calls < 3)
          return response({}, status: 503, headers: {'retry-after': '0'});
        return CorteResponse(
          statusCode: 200,
          headers: {'content-type': 'image/jpeg', 'etag': '"1234abcd-md"'},
          bodyBytes: Uint8List.fromList([1, 2, 3]),
        );
      });
      final repo = CorteRepository(
        adapter: adapter,
        cacheScope: scopeA,
        store: store,
      );
      final bytes = await repo.imagen('/img/v/123?v=1234abcd', tamano: 'md');
      expect(bytes, [1, 2, 3]);
      expect(calls, 3);
      expect(adapter.requests.map((r) => r.path).toSet(), {
        '/img/v/123?t=md&v=1234abcd',
      });
      final restarted = CorteRepository(
        adapter: FakeAdapter((_) => (throw StateError('must use image cache'))),
        cacheScope: scopeA,
        store: store,
      );
      expect(await restarted.imagen('/img/v/123?v=1234abcd', tamano: 'md'), [
        1,
        2,
        3,
      ]);
    },
  );

  test('401 never uses a small cached image fallback', () async {
    final store = MemoryCorteDataStore();
    final seed = CorteRepository(
      adapter: FakeAdapter(
        (_) => (CorteResponse(
          statusCode: 200,
          headers: {'content-type': 'image/jpeg', 'etag': '"1234abcd-sm"'},
          bodyBytes: Uint8List.fromList([1]),
        )),
      ),
      cacheScope: scopeA,
      store: store,
    );
    await seed.imagen('/img/v/123?v=1234abcd', tamano: 'sm');
    final revoked = CorteRepository(
      adapter: FakeAdapter(
        (_) => (response({
          'error': {'codigo': 'sesion_revocada'},
        }, status: 401)),
      ),
      cacheScope: scopeA,
      store: store,
    );
    await expectLater(
      revoked.imagen('/img/v/123?v=1234abcd', tamano: 'md'),
      throwsA(isA<ErrorApi>().having((e) => e.http, 'HTTP', 401)),
    );
  });

  test(
    'message variables block missing dates/links and preserve custom braces',
    () {
      final sample = {
        'application_id': 'm1',
        'producto': {'titulo': 'Chaqueta'},
        'variante': 'Café / L',
      };
      final missing = resolverMensaje(
        cuerpo: '{tienda} {lista_fechas} {link_video} {otra}',
        tienda: {'nombre': 'Tienda'},
        muestras: [sample],
      );
      expect(missing.puedeCopiar, isFalse);
      expect(missing.faltantes, {'lista_fechas', 'link_video'});
      expect(missing.texto, contains('{otra}'));
      final ready = resolverMensaje(
        cuerpo: '{lista_productos}\n{lista_fechas}{firma}',
        tienda: {'nombre': 'Tienda'},
        muestras: [sample],
        compromisos: {'m1': '2026-11-20'},
        firma: 'Creadora',
      );
      expect(ready.puedeCopiar, isTrue);
      expect(ready.texto, contains('Café / L'));
      expect(ready.texto, contains('20 de noviembre de 2026'));
      expect(ready.texto, endsWith('\n— Creadora'));
    },
  );
}
