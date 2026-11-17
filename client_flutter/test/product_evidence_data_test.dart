import 'dart:typed_data';
import 'dart:convert';

import 'package:corte/data/corte_repository.dart';
import 'package:corte/data/image_cache.dart';
import 'package:corte/data/snapshot_projection.dart';
import 'package:flutter_test/flutter_test.dart';

const _scopeA =
    'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';
const _scopeB =
    'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb';
const _path = '/img/e/100-0123456789abcdef?v=1234abcd&t=sm';

class _EvidenceAdapter implements CorteHttpAdapter {
  final calls = <Map<String, String>>[];
  @override
  Future<CorteResponse> request(
    String method,
    String path, {
    Map<String, String> headers = const {},
    Object? body,
  }) async {
    calls.add(headers);
    return CorteResponse(
      statusCode: 200,
      headers: {'content-type': 'application/json'},
      bodyBytes: Uint8List.fromList(utf8.encode('{"rev":1}')),
    );
  }

  @override
  void close() {}
}

JsonMap _snapshot() => {
  'version_esquema': 1,
  'local': <String, dynamic>{},
  'muestras': [],
  'productos': [
    {'product_id': '100'},
  ],
  'meta_imagenes': {
    _path: {'w': 300, 'h': 300},
  },
  'extras': {
    'productos': {
      '100': {
        'evidencia_rev': 7,
        'tabla_tallas': {
          'estado': 'disponible',
          'tabla': {
            'columnas': ['Talla', 'Pecho'],
            'filas': [
              ['M', '96'],
            ],
            'unidad': 'cm',
            'imagenes': [_path],
          },
        },
        'resenas': {
          'estado': 'disponible',
          'total': null,
          'items': [
            {
              'id': 'synthetic-review',
              'texto': 'Opinión sintética',
              'imagenes': [_path],
            },
          ],
          'siguiente_cursor': '20',
        },
      },
    },
  },
};

void main() {
  test(
    'evidence import requires and binds the current creator scope',
    () async {
      final adapter = _EvidenceAdapter();
      final repo = CorteRepository(adapter: adapter);
      addTearDown(repo.close);
      await expectLater(
        repo.put('/api/productos/100/evidencia', body: {'rev': 0}),
        throwsA(
          isA<ErrorApi>().having(
            (error) => error.codigo,
            'code',
            'sesion_cambiada',
          ),
        ),
      );
      expect(adapter.calls, isEmpty);
      repo.setScopes(ownerScope: _scopeA, cacheScope: _scopeB);
      await repo.write(
        'PUT',
        '/api/productos/100/evidencia',
        body: {'rev': 0},
        headers: {'X-Corte-Cache-Scope': _scopeA},
      );
      expect(adapter.calls.single['X-Corte-Cache-Scope'], _scopeB);
      await repo.post('/api/productos/100/extraer', body: {'rev': 1});
      expect(adapter.calls.last['X-Corte-Cache-Scope'], _scopeB);
    },
  );
  test(
    'evidence DTO retains units, table cells, source and nullable verification',
    () {
      final detail = ProductoExtendidoDto(
        jsonMap((jsonMap(_snapshot()['extras'])['productos'] as Map)['100']),
      );
      expect(detail.evidenciaRev, 7);
      expect(detail.tablaTallas!.tabla!.unidad, 'cm');
      expect(detail.tablaTallas!.tabla!.filas.single, ['M', '96']);
      expect(detail.resenas!.total, isNull);
      expect(detail.resenas!.items.single.compraVerificada, isNull);
      expect(detail.resenas!.items.single.imagenes, [_path]);
      expect(detail.resenas!.siguienteCursor, '20');
      expect(
        () => detail.tablaTallas!.tabla!.filas.single.add('invented'),
        throwsUnsupportedError,
      );
      expect(
        () => DatosTablaTallasDto({
          'filas': [
            [42],
          ],
        }).filas,
        throwsFormatException,
      );
    },
  );

  test(
    'offline evidence uses stored revision and never invents a subsequent review page',
    () {
      final snapshot = _snapshot();
      final product = proyectarSnapshot('/api/productos/100', snapshot)!;
      expect(jsonMap(product['extendido'])['evidencia_rev'], 7);
      final evidence = proyectarSnapshot(
        '/api/productos/100/evidencia',
        snapshot,
      )!;
      expect(evidence['rev'], 7);
      expect(jsonMap(evidence['tabla_tallas'])['estado'], 'disponible');
      final firstPage = proyectarSnapshot(
        '/api/productos/100/resenas?cursor=0',
        snapshot,
      )!;
      expect(jsonMap(firstPage['resenas'])['siguiente_cursor'], '20');
      expect(
        proyectarSnapshot('/api/productos/100/resenas?cursor=20', snapshot),
        isNull,
      );
      expect(
        proyectarSnapshot('/api/productos/999/evidencia', snapshot),
        isNull,
      );
      expect(proyectarSnapshot('/api/productos/999/resenas', snapshot), isNull);
    },
  );

  test(
    'evidence images persist privately with strict product/hash/version identity',
    () async {
      final cache = CorteImageCache(MemoryCorteDataStore());
      final bytes = Uint8List.fromList([1, 2, 3]);
      const headers = {'etag': '"1234abcd-sm"', 'content-type': 'image/webp'};
      await cache.put(_scopeA, _path, bytes, headers);
      expect(await cache.read(_scopeA, _path), bytes);
      expect(await cache.read(_scopeB, _path), isNull);
      for (final invalid in [
        '/img/e/100-0123456789abcdef?v=0&t=sm',
        '/img/e/100-0123456789abcde?v=1234abcd&t=sm',
        '/img/e/100-0123456789abcdefg?v=1234abcd&t=sm',
        '/img/e/100-0123456789ABCDEF?v=1234abcd&t=sm',
        '/img/e/100%2F200-0123456789abcdef?v=1234abcd&t=sm',
        '/img/e/100-0123456789abcdef?v=1234abcd&t=sm&other=1',
      ]) {
        await cache.put(_scopeA, invalid, bytes, headers);
        expect(await cache.read(_scopeA, invalid), isNull);
      }
      expect(
        await cache.read(
          _scopeA,
          '/img/e/101-0123456789abcdef?v=1234abcd&t=sm',
        ),
        isNull,
      );
    },
  );
}
