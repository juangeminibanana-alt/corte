// Synthetic schema fixtures only. No captured buyer data or session cookies.
import 'dart:convert';

import 'package:corte/data/public_product_source.dart';
import 'package:corte/domain/corte_models.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

const _now = 1800000000;
const _cdn = 'https://p16-oec-va.ibyteimg.com/synthetic/';
const _url = 'https://shop.tiktok.com/mx/pdp/synthetic/100';

JsonMap _component() => {
  'product_info': {
    'product_id': '100',
    'size_guide': {
      'image': {
        'url_list': ['${_cdn}chart.webp', '${_cdn}chart-backup.webp'],
      },
    },
    'images': [
      {
        'url_list': ['${_cdn}catalog.webp'],
      },
    ],
    'review': {'product_rating': 4.6},
  },
  'review_info': {
    'total_reviews': '60',
    'review_ratings': {'overall_score': 4.6},
    'product_reviews': [
      {
        'review_id': 'r1',
        'product_id': '100',
        'review_text': 'Comentario sintético A',
        'review_rating': 5,
        'review_time': '${(_now - 86400) * 1000}',
        'sku_specification': 'Azul / M',
        'is_verified_purchase': true,
        'review_images': ['${_cdn}review-a.webp'],
        'reviewer_name': 'Not retained',
      },
      {
        'review_id': 'r2',
        'review_text': 'Comentario sintético B',
        'review_rating': 4,
        'review_images': ['${_cdn}review-b.webp'],
      },
    ],
  },
};

String _html({
  JsonMap? component,
  String canonical = _url,
  String routeId = '100',
}) =>
    '<html><title>Producto sintético</title><script id="__MODERN_ROUTER_DATA__">${jsonEncode({
      'loaderData': {
        'layout': null,
        'product/page': {
          'route_info': {'route_product_id': routeId, 'canonical_url': canonical},
          'page_config': {
            'components_map': [
              {
                'component_data': {
                  'product_info': {'product_id': '999'},
                },
              },
              {'component_data': component ?? _component()},
            ],
          },
        },
      },
    })}</script></html>';

JsonMap _parse(String html) => parsePublicProductPage(
  html,
  productId: '100',
  sourceUrl: '$_url?source=public',
  now: _now,
);

Matcher _error(String code) =>
    throwsA(isA<ErrorApi>().having((e) => e.codigo, 'code', code));

void main() {
  test(
    'native parser preserves preview totals and photo-review associations',
    () {
      final result = _parse(_html());
      final chart = jsonMap(jsonMap(result['tabla_tallas'])['tabla']);
      expect(chart['imagenes'], ['${_cdn}chart.webp']);
      expect(chart['columnas'], isEmpty);
      final reviews = jsonMap(result['resenas']),
          rows = jsonObjects(jsonMap(result['resenas'])['items']);
      expect(reviews['total'], 60);
      expect(reviews['promedio'], 4.6);
      expect(rows.length, 2);
      expect(rows.first['fecha'], _now - 86400);
      expect(rows.first['compra_verificada'], true);
      expect(rows.last['compra_verificada'], isNull);
      expect(rows.first['imagenes'], ['${_cdn}review-a.webp']);
      expect(rows.last['imagenes'], ['${_cdn}review-b.webp']);
      expect(jsonEncode(result), isNot(contains('reviewer_name')));
      expect(jsonEncode(result), isNot(contains('catalog.webp')));
      expect(jsonMap(jsonMap(result['resenas'])['fuente'])['url'], _url);
    },
  );

  test('missing blocks are omitted and unknown counts never become zero', () {
    final component = _component();
    (component['product_info'] as Map).remove('size_guide');
    (component['review_info'] as Map).remove('total_reviews');
    final result = _parse(_html(component: component));
    expect(result.containsKey('tabla_tallas'), isFalse);
    expect(jsonMap(result['resenas'])['total'], isNull);
    (component['review_info'] as Map).clear();
    expect(
      () => _parse(_html(component: component)),
      _error('fuente_sin_datos'),
    );
  });

  test(
    'explicit zero, invalid source fields and verification remain distinct',
    () {
      final component = _component();
      component['review_info'] = {'total_reviews': '0', 'product_reviews': []};
      final result = _parse(_html(component: component));
      expect(jsonMap(result['resenas'])['total'], 0);
      expect(jsonMap(result['resenas'])['promedio'], isNull);
      expect(
        () => _parse('<title>Security Check</title>Verify to continue:'),
        _error('fuente_verificacion_requerida'),
      );
      expect(
        () => _parse(_html(canonical: 'https://evil.example/mx/pdp/100')),
        _error('fuente_respuesta_invalida'),
      );
      expect(
        () => _parse(_html(routeId: '999')),
        _error('fuente_respuesta_invalida'),
      );
      expect(
        () => _parse('<script id="__MODERN_ROUTER_DATA__">not JSON</script>'),
        _error('fuente_respuesta_invalida'),
      );
    },
  );

  test('unrelated reviews and arbitrary image URLs never enter evidence', () {
    final component = _component();
    final rows = (component['review_info'] as Map)['product_reviews'] as List;
    rows.add({
      'review_id': 'foreign',
      'product_id': '999',
      'review_text': 'Wrong product',
    });
    rows.first['review_images'] = [
      'https://evil.example/private.webp',
      '${_cdn}review-a.webp',
    ];
    final reviews = jsonObjects(
      jsonMap(_parse(_html(component: component))['resenas'])['items'],
    );
    expect(reviews.length, 2);
    expect(reviews.first['imagenes'], ['${_cdn}review-a.webp']);
  });

  test(
    'native HTTP uses the public host without Google or TikTok credentials',
    () async {
      final calls = <http.Request>[];
      final source = CortePublicProductSource(
        clock: () => DateTime.fromMillisecondsSinceEpoch(_now * 1000),
        client: MockClient((request) async {
          calls.add(request);
          expect(
            request.headers.keys.map((k) => k.toLowerCase()),
            isNot(
              anyElement(
                isIn(['authorization', 'cookie', 'origin', 'x-ch-hub']),
              ),
            ),
          );
          if (calls.length == 1)
            return http.Response(
              '',
              302,
              headers: {'location': '$_url?source=public'},
            );
          return http.Response(
            _html(),
            200,
            headers: {'content-type': 'text/html; charset=utf-8'},
          );
        }),
      );
      final result = await source.read('100');
      expect(calls.length, 2);
      expect(
        calls.every(
          (r) => r.url.host == 'shop.tiktok.com' && !r.followRedirects,
        ),
        isTrue,
      );
      expect(jsonMap(result['resenas'])['total'], 60);
    },
  );

  test(
    'foreign redirects and verification stop without another request',
    () async {
      for (final status in [302, 403, 429]) {
        var calls = 0;
        final source = CortePublicProductSource(
          client: MockClient((request) async {
            calls++;
            return http.Response(
              '',
              status,
              headers: {'location': 'https://evil.example/mx/pdp/100'},
            );
          }),
        );
        await expectLater(
          source.read('100'),
          _error(
            status == 302
                ? 'fuente_respuesta_invalida'
                : 'fuente_verificacion_requerida',
          ),
        );
        expect(calls, 1);
      }
    },
  );

  test(
    'non-HTML data and oversized HTML are rejected by the native reader',
    () async {
      final source = CortePublicProductSource(
        client: MockClient(
          (_) async => http.Response(
            'x' * (publicProductMaxBytes + 1),
            200,
            headers: {'content-type': 'text/html'},
          ),
        ),
      );
      await expectLater(
        source.read('100'),
        _error('fuente_respuesta_invalida'),
      );
      final jsonSource = CortePublicProductSource(
        client: MockClient(
          (_) async => http.Response(
            '{}',
            200,
            headers: {'content-type': 'application/json'},
          ),
        ),
      );
      await expectLater(
        jsonSource.read('100'),
        _error('fuente_respuesta_invalida'),
      );
    },
  );
}
