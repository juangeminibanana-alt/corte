"""Public MX PDP extraction; every fixture is synthetic, with no captured buyer data."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'hub'))
from creatorhub.errores import ErrorDominio
from creatorhub.productos_evidencia import _validar
from creatorhub.productos_publicos import (
    MAX_HTML_BYTES, MAX_RESENAS, MAX_SEGUNDOS, _descargar, extraer_evidencia_publica, obtener_producto_publico,
)

PID = '100'
NOW = 1_800_000_000
URL = 'https://shop.tiktok.com/mx/pdp/producto-sintetico/100'
CDN = 'https://p16-oec-va.ibyteimg.com/synthetic/'


def component():
    return {
        'product_info': {'product_id': PID,
                         'size_guide': {'title': 'Size guide', 'image': {
                             'url_list': [CDN + 'chart.webp', CDN + 'chart-backup.webp'],
                             'thumb_url_list': [CDN + 'chart-thumb.webp']}},
                         'images': [{'url_list': [CDN + 'catalog.webp']}],
                         'review': {'product_rating': 4.6, 'review_count': '60'}},
        'review_info': {
            'has_more': True, 'total_reviews': '60',
            'review_ratings': {'review_count': '60', 'overall_score': 4.6,
                               'rating_result': {'1': '2', '2': '1', '3': '3', '4': '5', '5': '49'}},
            'product_reviews': [
                {'review_id': '900', 'product_id': PID, 'review_rating': 5,
                 'review_time': str((NOW - 86400) * 1000), 'is_verified_purchase': True,
                 'review_text': 'Comentario de prueba A', 'sku_specification': 'Azul / M',
                 'review_images': [CDN + 'review-a.webp', CDN + 'review-a-detail.webp'],
                 'reviewer_name': 'Nombre sintético que no se conserva'},
                {'review_id': '901', 'product_id': PID, 'review_rating': 4,
                 'review_time': str((NOW - 172800) * 1000), 'is_verified_purchase': False,
                 'review_text': 'Comentario de prueba B', 'sku_specification': 'Rojo / S',
                 'review_images': [CDN + 'review-b.webp']},
                {'review_id': '902', 'product_id': PID, 'review_rating': 5,
                 'review_text': 'Comentario de prueba C', 'review_images': []},
            ],
        },
    }


def html_for(data=None, route=None):
    if data is None:
        data = component()
    route = route if route is not None else {'route_product_id': PID, 'canonical_url': URL}
    document = {'loaderData': {'layout': None,
        '(region)/pdp/(product_name_slug$)/(product_id)/page': {
            'route_info': route, 'page_config': {'components_map': [
                {'component_name': 'irrelevant', 'component_data': {'product_info': {'product_id': '999'}}},
                {'component_name': 'pdp', 'component_data': data},
            ]}}}, 'errors': None}
    # JSON scripts contain data, never code to evaluate.
    return '<html><title>Producto sintético</title><script id="__MODERN_ROUTER_DATA__">' + json.dumps(document) + '</script></html>'


class PublicProductParserTests(unittest.TestCase):
    def parse(self, data=None, route=None, url=URL):
        return extraer_evidencia_publica(html_for(data, route), PID, url, NOW)

    def test_real_observed_schema_keeps_chart_and_partial_reviews_separate(self):
        result = self.parse()
        chart = result['tabla_tallas']['tabla']
        self.assertEqual(chart, {'columnas': [], 'filas': [], 'unidad': None,
                                 'imagenes': [CDN + 'chart.webp']})
        reviews = result['resenas']
        self.assertEqual((reviews['total'], reviews['promedio'], len(reviews['items'])), (60, 4.6, 3))
        self.assertEqual(reviews['items'][0]['fecha'], NOW - 86400)
        self.assertEqual(reviews['items'][0]['variante'], 'Azul / M')
        self.assertTrue(reviews['items'][0]['compra_verificada'])
        self.assertFalse(reviews['items'][1]['compra_verificada'])
        self.assertEqual(result['tabla_tallas']['fuente']['url'], URL)
        self.assertEqual(result['tabla_tallas']['consultado_at'], NOW)
        self.assertNotIn('reviewer_name', json.dumps(result))
        # Same contract the persistence service uses, without depending on a network call.
        revision, normalized = _validar(dict(result, rev=0), PID, NOW)
        self.assertEqual(revision, 0)
        self.assertEqual(normalized, result)

    def test_photos_remain_with_their_review_and_never_use_catalog_or_display_fallback(self):
        data = component()
        data['review_info']['product_reviews'][2]['display_image_url'] = CDN + 'not-a-review-list.webp'
        rows = self.parse(data)['resenas']['items']
        self.assertEqual(rows[0]['imagenes'], [CDN + 'review-a.webp', CDN + 'review-a-detail.webp'])
        self.assertEqual(rows[1]['imagenes'], [CDN + 'review-b.webp'])
        self.assertEqual(rows[2]['imagenes'], [])

    def test_missing_section_is_omitted_instead_of_clearing_previous_evidence(self):
        data = component()
        del data['product_info']['size_guide']
        self.assertNotIn('tabla_tallas', self.parse(data))
        data = component()
        del data['review_info']
        self.assertNotIn('resenas', self.parse(data))
        del data['product_info']['size_guide']
        with self.assertRaises(ErrorDominio) as error:
            self.parse(data)
        self.assertEqual(error.exception.codigo, 'fuente_sin_datos')

    def test_absent_total_is_unknown_but_explicit_zero_is_preserved(self):
        data = component()
        del data['review_info']['total_reviews']
        data['review_info']['review_ratings'] = {}
        self.assertIsNone(self.parse(data)['resenas']['total'])
        data['review_info'] = {'total_reviews': '0', 'product_reviews': [], 'has_more': False}
        result = self.parse(data)['resenas']
        self.assertEqual(result['total'], 0)
        self.assertEqual(result['items'], [])
        self.assertIsNone(result['promedio'])

    def test_wrong_product_canonical_route_or_review_is_never_imported(self):
        for route in ({'route_product_id': '999', 'canonical_url': URL},
                      {'canonical_url': 'https://shop.tiktok.com/mx/pdp/999'}):
            with self.subTest(route=route), self.assertRaises(ErrorDominio):
                self.parse(route=route)
        data = component()
        data['product_info']['product_id'] = '999'
        with self.assertRaises(ErrorDominio):
            self.parse(data)
        data = component()
        data['review_info']['product_reviews'][0]['product_id'] = '999'
        self.assertEqual([r['id'] for r in self.parse(data)['resenas']['items']], ['901', '902'])

    def test_controls_dates_flags_and_untrusted_image_origins_are_normalized(self):
        data = component()
        row = data['review_info']['product_reviews'][0]
        row.update(review_rating=True, review_time=str((NOW + 3600) * 1000),
                   is_verified_purchase='true', review_text='A\x00B',
                   review_images=['https://evil.invalid/private.jpg', 'http://p16-oec-va.ibyteimg.com/bad.webp',
                                  CDN + 'good.webp', CDN + 'good.webp'])
        result = self.parse(data)['resenas']['items'][0]
        self.assertEqual(result['texto'], 'AB')
        self.assertIsNone(result['fecha'])
        self.assertIsNone(result['estrellas'])
        self.assertIsNone(result['compra_verificada'])
        self.assertEqual(result['imagenes'], [CDN + 'good.webp'])
        data['product_info']['size_guide']['image']['url_list'] = ['https://evil.invalid/chart.jpg']
        self.assertNotIn('tabla_tallas', self.parse(data))

    def test_duplicate_reviews_are_deduplicated_and_missing_ids_are_stable(self):
        data = component()
        rows = data['review_info']['product_reviews']
        rows.append(copy.deepcopy(rows[0]))
        rows[1]['review_id'] = None
        one = self.parse(data)['resenas']['items']
        two = self.parse(data)['resenas']['items']
        self.assertEqual(len(one), 3)
        self.assertEqual(one, two)
        self.assertTrue(one[1]['id'].startswith('public-'))

    def test_large_preview_is_bounded_without_fabricating_full_history(self):
        data = component()
        data['review_info']['total_reviews'] = '500'
        data['review_info']['product_reviews'] = [dict(data['review_info']['product_reviews'][0],
            review_id=str(9000 + n), review_text='Texto sintético ' * 300) for n in range(300)]
        result = self.parse(data)
        self.assertEqual(result['resenas']['total'], 500)
        self.assertLessEqual(len(result['resenas']['items']), MAX_RESENAS)
        self.assertGreater(len(result['resenas']['items']), 0)
        self.assertLess(len(json.dumps(result, ensure_ascii=False).encode('utf-8')), 192 * 1024)
        _validar(dict(result, rev=0), PID, NOW)

    def test_verification_missing_ssr_and_invalid_json_have_distinct_safe_errors(self):
        cases = [('<title>Security Check</title>', 'fuente_verificacion_requerida'),
                 ('<div>Verify to continue: captcha-verify-image</div>', 'fuente_verificacion_requerida'),
                 ('<html>Producto sin datos SSR</html>', 'fuente_sin_datos'),
                 ('<script id="__MODERN_ROUTER_DATA__">not-json</script>', 'fuente_respuesta_invalida')]
        for body, code in cases:
            with self.subTest(code=code), self.assertRaises(ErrorDominio) as error:
                extraer_evidencia_publica(body, PID, URL, NOW)
            self.assertEqual(error.exception.codigo, code)
            self.assertEqual(error.exception.http, 503)
        duplicate = html_for() + '<script id="__MODERN_ROUTER_DATA__">{}</script>'
        with self.assertRaises(ErrorDominio):
            extraer_evidencia_publica(duplicate, PID, URL, NOW)

    def test_canonical_query_is_removed_and_wrong_host_market_or_id_is_rejected(self):
        result = self.parse(url=URL + '?source=public')
        self.assertEqual(result['resenas']['fuente']['url'], URL)
        for url in ['http://shop.tiktok.com/mx/pdp/100', 'https://shop.tiktok.com.evil.invalid/mx/pdp/100',
                    'https://user:pass@shop.tiktok.com/mx/pdp/100', 'https://shop.tiktok.com/us/pdp/100',
                    'https://shop.tiktok.com/mx/pdp/999', 'https://shop.tiktok.com/mx/pdp/100#fragment',
                    'https://shop.tiktok.com:444/mx/pdp/100', 'https://shop.tiktok.com/api/private/100']:
            with self.subTest(url=url), self.assertRaises(ErrorDominio):
                self.parse(url=url)

    def test_oversize_html_is_refused_before_parsing(self):
        with self.assertRaises(ErrorDominio) as error:
            extraer_evidencia_publica(b'x' * (MAX_HTML_BYTES + 1), PID, URL, NOW)
        self.assertEqual(error.exception.codigo, 'fuente_respuesta_invalida')


class FakeSocket:
    def settimeout(self, timeout):
        if not 0 < timeout <= MAX_SEGUNDOS:
            raise AssertionError('unbounded socket timeout')


class FakeResponse:
    def __init__(self, status=200, body=None, headers=None):
        self.status = status
        self.body = html_for().encode() if body is None else body
        self.headers = {'Content-Type': 'text/html; charset=UTF-8', **(headers or {})}
        self.reads = 0

    def getheader(self, key, default=None):
        return self.headers.get(key, default)

    def read1(self, size):
        self.reads += 1
        chunk, self.body = self.body[:size], self.body[size:]
        return chunk


class PublicProductFetchTests(unittest.TestCase):
    def network(self, responses):
        calls = []
        class FakeConnection:
            def __init__(self, host, timeout):
                if host != 'shop.tiktok.com' or not 0 < timeout <= MAX_SEGUNDOS:
                    raise AssertionError('unexpected network destination')
                self.response = responses[len(calls)]
                self.sock = FakeSocket()
                self.closed = False
                calls.append(self)
            def connect(self):
                pass
            def request(self, *args, **kwargs):
                self.request_args, self.request_kwargs = args, kwargs
            def getresponse(self):
                return self.response
            def close(self):
                self.closed = True
        return patch('creatorhub.productos_publicos.http.client.HTTPSConnection', FakeConnection), calls

    def test_observed_numeric_link_follows_canonical_redirect_without_cookies(self):
        first = FakeResponse(301, headers={'Location': URL + '?source=product_detail&enter_method=url_semantic_301',
                                           'Set-Cookie': 'synthetic-cookie=never-reused'})
        network, calls = self.network([first, FakeResponse()])
        with network:
            result = obtener_producto_publico(PID, NOW)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0].request_args, ('GET', '/mx/pdp/100'))
        self.assertEqual(calls[1].request_kwargs, {})
        self.assertTrue(all(c.closed for c in calls))
        self.assertEqual(result['resenas']['fuente']['url'], URL)

    def test_redirect_to_private_host_wrong_product_or_http_stops_before_next_request(self):
        for location in ['https://127.0.0.1/mx/pdp/100', 'https://shop.tiktok.com/mx/pdp/999',
                         'http://shop.tiktok.com/mx/pdp/100']:
            network, calls = self.network([FakeResponse(302, headers={'Location': location})])
            with self.subTest(location=location), network, self.assertRaises(ErrorDominio):
                _descargar(URL, PID)
            self.assertEqual(len(calls), 1)
            self.assertTrue(calls[0].closed)

    def test_403_and_challenge_are_not_retried_or_treated_as_zero_reviews(self):
        response = FakeResponse(403)
        network, calls = self.network([response])
        with network, self.assertRaises(ErrorDominio) as error:
            obtener_producto_publico(PID, NOW)
        self.assertEqual(error.exception.codigo, 'fuente_verificacion_requerida')
        self.assertEqual(len(calls), 1)
        self.assertEqual(response.reads, 0)

    def test_content_type_encoding_and_advertised_length_are_bounded(self):
        for headers in ({'Content-Type': 'application/json'}, {'Content-Encoding': 'gzip'},
                        {'Content-Length': str(MAX_HTML_BYTES + 1)}):
            response = FakeResponse(headers=headers)
            network, calls = self.network([response])
            with self.subTest(headers=headers), network, self.assertRaises(ErrorDominio):
                _descargar(URL, PID)
            self.assertEqual(response.reads, 0)
            self.assertTrue(calls[0].closed)

    def test_chunked_page_cannot_exceed_limit(self):
        response = FakeResponse(body=b'x' * (MAX_HTML_BYTES + 50))
        network, calls = self.network([response])
        with network, self.assertRaises(ErrorDominio) as error:
            _descargar(URL, PID)
        self.assertEqual(error.exception.codigo, 'fuente_respuesta_invalida')
        self.assertEqual(len(response.body), 49)
        self.assertTrue(calls[0].closed)

    def test_maximum_three_redirects_and_total_deadline(self):
        responses = [FakeResponse(302, headers={'Location': URL}) for _ in range(4)]
        network, calls = self.network(responses)
        with network, self.assertRaises(ErrorDominio):
            _descargar(URL, PID)
        self.assertEqual(len(calls), 4)
        self.assertTrue(all(c.closed for c in calls))
        with patch('creatorhub.productos_publicos.time.monotonic', side_effect=[0, MAX_SEGUNDOS + 1]), self.assertRaises(ErrorDominio):
            _descargar(URL, PID)


if __name__ == '__main__':
    unittest.main()
