"""Synthetic product evidence: source integrity, revisions, media isolation and migration.

No TikTok/Google calls or customer data. The fake image queue writes the same pending
image references as the real queue, and checks that evidence committed first.
"""
from concurrent.futures import ThreadPoolExecutor
import copy
import json
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'hub'))
from creatorhub.almacen import crear_almacen, leer_recurso_sql
from creatorhub.analitica.servicio import AnaliticaSqlite
from creatorhub.analitica.vista import Vista
from creatorhub.api.rutas import crear_despachador
from creatorhub.errores import ErrorDominio
from creatorhub.imagenes import claves
from creatorhub.interfaces import Contexto, CTX_UI
from creatorhub.productos_evidencia import ServicioEvidencia


class PendingImages:
    def __init__(self, store, now):
        self.store, self.now = store, now
        self.calls = []

    def encolar(self, requests):
        # In particular, do not let image processing/network work escape before
        # the document has durably passed its optimistic revision check.
        if self.store._w.in_transaction:
            raise AssertionError('image queue called before evidence commit')
        requests = list(requests)
        self.calls.extend(requests)
        with self.store.escritor() as db:
            for request in requests:
                db.execute('INSERT INTO imagenes(img_key,tipo,ref_id,url_origen,estado,actualizado_at) '
                           'VALUES(?,?,?,?,?,?) ON CONFLICT(img_key) DO UPDATE SET url_origen=excluded.url_origen',
                           (f'{request.tipo}:{request.ref_id}', request.tipo, request.ref_id,
                            request.url, 'pendiente', self.now))


class ProductEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.now = 1_800_000_000
        self.clock = SimpleNamespace(ahora=lambda: self.now, monotonico=lambda: 1000.0)
        self.store = crear_almacen(str(Path(self.folder.name) / 'synthetic.sqlite'), self.clock)
        self.images = PendingImages(self.store, self.now)
        self.bus = Mock()
        self.service = ServicioEvidencia(self.store, self.images, self.bus, self.clock)
        self.analytics = AnaliticaSqlite(self.store, self.clock)
        with self.store.escritor() as db:
            db.execute('INSERT INTO productos(product_id,titulo,actualizado_at) VALUES(?,?,?)',
                       ('100', 'Producto sintético de prueba', self.now))

    def tearDown(self):
        self.store.cerrar()
        self.folder.cleanup()

    def source(self, pid='100'):
        return {'tipo': 'captura_tiktok', 'url': f'https://shop.tiktok.com/view/product/{pid}',
                'nombre': 'TikTok Shop'}

    def document(self, reviews=1):
        return {'rev': 0,
                'tabla_tallas': {'estado': 'disponible', 'fuente': self.source(), 'consultado_at': self.now,
                                 'tabla': {'columnas': ['Talla', 'Pecho'], 'filas': [['M', '96'], ['L', '100']],
                                           'unidad': 'cm', 'imagenes': ['https://p.tiktokcdn.com/synthetic-chart.jpg']}},
                'resenas': {'estado': 'disponible', 'fuente': self.source(), 'consultado_at': self.now,
                            'promedio': 4.5, 'total': reviews,
                            'items': [{'id': f'review-{n}', 'texto': f'Reseña sintética {n}', 'estrellas': 5,
                                       'fecha': self.now - 60, 'variante': 'Azul / M',
                                       'compra_verificada': None,
                                       'imagenes': ['https://p.tiktokcdn.com/synthetic-review.jpg']}
                                      for n in range(reviews)]}}

    def assert_invalid(self, document):
        before = self.store.versiones()
        queued = len(self.images.calls)
        with self.assertRaises(ErrorDominio) as caught:
            self.service.guardar('100', document, CTX_UI)
        self.assertIn(caught.exception.http, (400, 413, 422))
        self.assertEqual(self.store.versiones(), before)
        self.assertEqual(len(self.images.calls), queued)
        with self.store.lector() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM producto_evidencia').fetchone()[0], 0)

    def test_new_product_is_unqueried_not_zero_reviews(self):
        result = self.service.leer('100')
        self.assertEqual(result['product_id'], '100')
        self.assertEqual(result['rev'], 0)
        self.assertIsNone(result['tabla_tallas'])
        self.assertIsNone(result['resenas'])

    def test_image_queue_failure_preserves_commit_and_retry_with_current_revision_is_idempotent(self):
        document = self.document()
        real_queue = self.images.encolar
        self.images.encolar = Mock(side_effect=RuntimeError('synthetic image worker unavailable'))
        first = self.service.guardar('100', document, CTX_UI)
        self.assertEqual(first['rev'], 1)
        self.assertTrue(first['imagenes_pendientes'])
        self.assertIn('guardó', first['aviso'])
        self.assertEqual(self.service.leer('100')['resenas']['items'][0]['texto'], 'Reseña sintética 0')
        versions = self.store.versiones()
        self.images.encolar = real_queue
        document['rev'] = first['rev']
        retried = self.service.guardar('100', document, CTX_UI)
        self.assertEqual(retried['rev'], first['rev'])
        self.assertEqual(self.store.versiones(), versions)
        self.assertFalse(retried['imagenes_pendientes'])
        self.assertEqual(len(retried['tabla_tallas']['tabla']['imagenes']), 1)
        self.assertEqual(len(retried['resenas']['items'][0]['imagenes']), 1)

    def test_import_keeps_exact_measurements_and_buyer_photos_separate(self):
        original = self.document()
        before = copy.deepcopy(original)
        result = self.service.guardar('100', original, CTX_UI)
        self.assertEqual(original, before, 'normalization must not mutate caller data')
        self.assertEqual(result['rev'], 1)
        table = result['tabla_tallas']['tabla']
        self.assertEqual(table['filas'], [['M', '96'], ['L', '100']])
        self.assertEqual(table['unidad'], 'cm')
        chart = table['imagenes'][0]
        buyer = result['resenas']['items'][0]['imagenes'][0]
        pattern = r'^/img/e/100-[0-9a-f]{16}\?v=0$'
        self.assertRegex(chart, pattern)
        self.assertRegex(buyer, pattern)
        self.assertNotEqual(chart, buyer)
        self.assertIsNone(result['resenas']['items'][0]['compra_verificada'])
        self.assertNotIn('p.tiktokcdn.com', json.dumps(result))
        self.assertEqual(self.service.leer('100')['tabla_tallas'], result['tabla_tallas'])
        self.bus.notificar_cambio.assert_called()
        self.assertGreaterEqual(len(self.images.calls), 2)

    def test_same_url_in_distinct_reviews_keeps_distinct_image_identity(self):
        result = self.service.guardar('100', self.document(2), CTX_UI)
        first, second = result['resenas']['items']
        self.assertNotEqual(first['imagenes'][0], second['imagenes'][0])

    def test_stale_revision_returns_current_proxy_only_document_without_queuing(self):
        current = self.service.guardar('100', self.document(), CTX_UI)
        queued, versions = len(self.images.calls), self.store.versiones()
        wrong = self.document()
        wrong['tabla_tallas']['tabla']['filas'][0][1] = '999'
        with self.assertRaises(ErrorDominio) as caught:
            self.service.guardar('100', wrong, CTX_UI)
        self.assertEqual(caught.exception.http, 409)
        self.assertEqual(caught.exception.codigo, 'conflicto')
        self.assertEqual(caught.exception.vigente['rev'], current['rev'])
        self.assertNotIn('p.tiktokcdn.com', json.dumps(caught.exception.vigente))
        self.assertEqual(len(self.images.calls), queued)
        self.assertEqual(self.store.versiones(), versions)
        self.assertEqual(self.service.leer('100')['tabla_tallas']['tabla']['filas'][0][1], '96')

    def test_partial_update_preserves_other_block_and_advances_revision(self):
        first = self.service.guardar('100', self.document(), CTX_UI)
        changed = copy.deepcopy(self.document()['tabla_tallas'])
        changed['tabla']['filas'][0][1] = '97'
        second = self.service.guardar('100', {'rev': 1, 'tabla_tallas': changed}, CTX_UI)
        self.assertEqual(second['rev'], 2)
        self.assertEqual(second['resenas'], first['resenas'])
        self.assertEqual(second['tabla_tallas']['tabla']['filas'][0][1], '97')

    def test_simultaneous_first_imports_cannot_silently_overwrite_each_other(self):
        service = ServicioEvidencia(self.store, self.images, self.bus, self.clock, threading.RLock())
        first, second = self.document(), self.document()
        second['tabla_tallas']['tabla']['filas'][0][1] = '97'

        def save(document):
            try:
                return service.guardar('100', document, CTX_UI)['rev']
            except ErrorDominio as error:
                return error.http

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(save, (first, second)))
        self.assertCountEqual(results, [1, 409])
        result = self.service.leer('100')
        self.assertEqual(result['rev'], 1)
        self.assertIn(result['tabla_tallas']['tabla']['filas'][0][1], ('96', '97'))

    def test_readonly_and_unknown_product_do_not_persist_or_queue(self):
        readonly = Contexto(origen='lan', plataforma='android', permisos='lectura')
        with self.assertRaises(ErrorDominio) as caught:
            self.service.guardar('100', self.document(), readonly)
        self.assertEqual(caught.exception.http, 403)
        missing_document = self.document()
        missing_document['tabla_tallas']['fuente'] = self.source('999')
        missing_document['resenas']['fuente'] = self.source('999')
        for action in (lambda: self.service.leer('999'),
                       lambda: self.service.guardar('999', missing_document, CTX_UI),
                       lambda: self.service.resenas('999', {})):
            with self.subTest(action=action), self.assertRaises(ErrorDominio) as missing:
                action()
            self.assertEqual(missing.exception.http, 404)
        self.assertEqual(self.images.calls, [])

    def test_source_cannot_claim_another_product(self):
        bad = self.document()
        bad['tabla_tallas']['fuente'] = self.source('999')
        self.assert_invalid(bad)

    def test_rejects_untrusted_image_origins_including_local_network_and_proxy_input(self):
        for url in ('https://127.0.0.1/chart.jpg', 'https://evil.example/chart.jpg',
                    'http://p.tiktokcdn.com/chart.jpg', 'https://p.tiktokcdn.com@evil.example/chart.jpg',
                    '/img/p/100?v=1234abcd'):
            with self.subTest(url=url):
                bad = self.document()
                bad['resenas']['items'][0]['imagenes'] = [url]
                self.assert_invalid(bad)

    def test_schema_hard_limits_are_enforced_before_database_or_image_queue(self):
        cases = []
        bad = self.document(101)
        cases.append(('101 reviews', bad))
        bad = self.document()
        bad['tabla_tallas']['tabla'] = {'columnas': [f'Col {n}' for n in range(17)],
                                       'filas': [['x'] * 17], 'imagenes': []}
        cases.append(('17 columns', bad))
        bad = self.document()
        bad['tabla_tallas']['tabla']['filas'] = [['M', '96']] * 101
        cases.append(('101 rows', bad))
        bad = self.document()
        bad['tabla_tallas']['tabla']['filas'] = [['M']]
        cases.append(('misaligned row', bad))
        bad = self.document()
        bad['tabla_tallas']['tabla']['filas'][0][1] = 'x' * 151
        cases.append(('oversize cell', bad))
        bad = self.document()
        bad['resenas']['items'][0]['texto'] = 'x' * 5001
        cases.append(('oversize review', bad))
        bad = self.document(2)
        bad['resenas']['items'][1]['id'] = bad['resenas']['items'][0]['id']
        cases.append(('duplicate review identity', bad))
        bad = self.document()
        bad['resenas']['total'] = 0
        cases.append(('total below received items', bad))
        for name, bad in cases:
            with self.subTest(name=name):
                self.assert_invalid(bad)

    def test_large_document_is_rejected_even_when_every_individual_review_is_valid(self):
        document = self.document(50)
        for review in document['resenas']['items']:
            review['texto'] = 'á' * 4500
        # The limit must use encoded bytes, not Python character count.
        self.assert_invalid(document)

    def test_boolean_numbers_nonfinite_values_and_unknown_fields_are_rejected(self):
        changes = [('rev', lambda d: d.update(rev=True)),
                   ('timestamp', lambda d: d['resenas'].update(consultado_at=True)),
                   ('total', lambda d: d['resenas'].update(total=True)),
                   ('rating', lambda d: d['resenas']['items'][0].update(estrellas=True)),
                   ('rating range', lambda d: d['resenas']['items'][0].update(estrellas=6)),
                   ('NaN', lambda d: d['resenas'].update(promedio=float('nan'))),
                   ('Infinity', lambda d: d['resenas'].update(promedio=float('inf'))),
                   ('unknown root', lambda d: d.update(automatic_tiktok_verified=True)),
                   ('unknown review', lambda d: d['resenas']['items'][0].update(buyer_email='none@example.test'))]
        for name, change in changes:
            with self.subTest(name=name):
                bad = self.document()
                change(bad)
                self.assert_invalid(bad)

    def test_error_or_pending_does_not_turn_unknown_reviews_into_zero(self):
        for status in ('pendiente', 'error', 'no_disponible', 'no_aplica'):
            with self.subTest(status=status):
                payload = {'rev': self.service.leer('100')['rev'], 'resenas': {
                    'estado': status, 'fuente': self.source(), 'consultado_at': self.now}}
                result = self.service.guardar('100', payload, CTX_UI)
                block = result['resenas']
                self.assertEqual(block['estado'], status)
                self.assertIsNone(block['promedio'])
                self.assertIsNone(block['total'])
                self.assertEqual(block['items'], [])

    def test_only_confirmed_zero_with_source_is_zero(self):
        payload = self.document(0)
        payload['resenas']['promedio'] = None
        result = self.service.guardar('100', payload, CTX_UI)
        self.assertEqual(result['resenas']['total'], 0)
        self.assertIsNone(result['resenas']['promedio'])
        self.assertEqual(result['resenas']['items'], [])

    def test_reviews_paginate_without_changing_global_total_or_duplicating(self):
        document = self.document(25)
        document['resenas']['total'] = 400
        result = self.service.guardar('100', document, CTX_UI)
        first = result['resenas']
        self.assertEqual(len(first['items']), 20)
        self.assertEqual(first['siguiente_cursor'], '20')
        self.assertEqual(first['cargadas'], 25)
        self.assertEqual(first['total'], 400)
        second = self.service.resenas('100', {'cursor': first['siguiente_cursor']})['resenas']
        self.assertEqual(len(second['items']), 5)
        self.assertIsNone(second['siguiente_cursor'])
        self.assertEqual(second['total'], 400)
        self.assertEqual(second['cargadas'], 25)
        self.assertEqual([review['id'] for review in first['items'] + second['items']],
                         [f'review-{n}' for n in range(25)])

    def test_cursor_cannot_alias_first_page_or_inject_arbitrary_query(self):
        self.service.guardar('100', self.document(25), CTX_UI)
        for query in ({'cursor': '-1'}, {'cursor': '1'}, {'cursor': '101'},
                      {'cursor': '20;drop table productos'}, {'cursor': '20', 'product_id': '999'}):
            with self.subTest(query=query), self.assertRaises(ErrorDominio):
                self.service.resenas('100', query)

    def test_offline_snapshot_includes_evidence_without_skus_or_vitrina_and_only_cached_media(self):
        result = self.service.guardar('100', self.document(), CTX_UI)
        chart = result['tabla_tallas']['tabla']['imagenes'][0]
        ref = chart.split('/')[3].split('?')[0]
        with self.store.escritor() as db:
            db.execute('INSERT INTO muestras(application_id,product_id,estado_api,clase,subestado,'
                       'clase_desde_at,primera_vez_at,huella,actualizado_at) VALUES(?,?,?,?,?,?,?,?,?)',
                       ('9100', '100', 'COMPLETE', 'entregada', 'video_aprobado',
                        self.now, self.now, 'synthetic', self.now))
            db.execute("UPDATE imagenes SET estado='ok',version='1234abcd',ancho=800,alto=900 WHERE ref_id=?", (ref,))
        snapshot = self.analytics.snapshot(None, {}, {})
        extra = snapshot['extras']['productos']['100']
        url = f'/img/e/{ref}?v=1234abcd'
        self.assertEqual(extra['tabla_tallas']['tabla']['imagenes'], [url])
        self.assertEqual(extra['resenas']['items'][0]['id'], 'review-0')
        self.assertIn(url, snapshot['meta_imagenes'])
        self.assertIn(url + '&t=sm', snapshot['imagenes'])
        self.assertFalse(any('?v=0' in item for item in snapshot['imagenes']))

    def test_image_namespace_allows_only_product_plus_stable_hash(self):
        ref = '100-0123456789abcdef'
        self.assertTrue(claves.ref_valido('e', ref))
        self.assertEqual(claves.clave('e', ref), 'e:' + ref)
        route = claves.ruta_rel_og('e', ref, '1234abcd', 'jpg')
        self.assertTrue(claves.nombre_de_cache(Path(route).name))
        for bad in ('100-0123456789abcde', '100-0123456789abcdef0', '100-0123456789abcdeg',
                    '../100-0123456789abcdef', '100/0123456789abcdef', '１００-0123456789abcdef'):
            with self.subTest(ref=bad):
                self.assertFalse(claves.ref_valido('e', bad))

    def test_account_erasure_removes_evidence(self):
        self.service.guardar('100', self.document(), CTX_UI)
        self.store.borrar('tiktok')
        with self.store.lector() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM producto_evidencia').fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT count(*) FROM imagenes WHERE tipo='e'").fetchone()[0], 0)

    def test_routes_enforce_write_permissions_and_new_snapshot_representation(self):
        hub = SimpleNamespace(analitica=self.analytics, evidencia=self.service, reloj=self.clock,
                              auth=SimpleNamespace(cuenta=lambda: None, conexion=lambda: {}),
                              sincronizador=SimpleNamespace(estado=lambda: {}))
        router = crear_despachador(hub)
        body = json.dumps(self.document()).encode()
        readonly = Contexto(origen='lan', plataforma='android', permisos='lectura')
        denied = router.despachar('PUT', '/api/productos/100/evidencia', '', {}, body, readonly)
        self.assertEqual(denied.status, 403)
        saved = router.despachar('PUT', '/api/productos/100/evidencia', '', {}, body, CTX_UI)
        self.assertEqual(saved.status, 200)
        for path in ('/api/productos/100/evidencia', '/api/productos/100/resenas'):
            response = router.despachar('GET', path, '', {}, b'', readonly)
            self.assertEqual(response.status, 200)
            self.assertNotIn('p.tiktokcdn.com', response.cuerpo.decode())
        old = 'W/"' + self.analytics.etag() + '-f1"'
        snapshot = router.despachar('GET', '/api/snapshot', '', {'If-None-Match': old}, b'', CTX_UI)
        self.assertEqual(snapshot.status, 200)
        tag = dict(snapshot.cabeceras)['ETag']
        self.assertNotEqual(tag, old)

    def test_public_extraction_fetches_outside_sql_transaction_and_persists_proxy_only(self):
        document = self.document()
        captured = {key: value for key, value in document.items() if key != 'rev'}

        def source(pid, ahora, url=None):
            self.assertEqual((pid, ahora), ('100', self.now))
            self.assertFalse(self.store._w.in_transaction,
                             'public HTTP fetch must not hold an SQLite transaction')
            return copy.deepcopy(captured)

        with patch('creatorhub.productos_publicos.obtener_producto_publico', side_effect=source) as fetch:
            result = self.service.extraer('100', {'rev': 0}, CTX_UI)
        fetch.assert_called_once()
        self.assertEqual(result['rev'], 1)
        self.assertEqual(result['tabla_tallas']['tabla']['filas'][0], ['M', '96'])
        self.assertEqual(result['resenas']['total'], 1)
        self.assertEqual(result['resenas']['items'][0]['id'], 'review-0')
        self.assertRegex(result['resenas']['items'][0]['imagenes'][0], r'^/img/e/100-[0-9a-f]{16}\?v=0$')
        self.assertNotIn('p.tiktokcdn.com', json.dumps(result))
        self.assertEqual(self.service.leer('100')['rev'], 1)

    def test_public_extraction_rejects_readonly_or_unknown_product_before_fetch(self):
        readonly = Contexto(origen='lan', plataforma='android', permisos='lectura')
        with patch('creatorhub.productos_publicos.obtener_producto_publico') as fetch:
            for pid, context, expected in (('100', readonly, 403), ('999', CTX_UI, 404)):
                with self.subTest(pid=pid, expected=expected), self.assertRaises(ErrorDominio) as caught:
                    self.service.extraer(pid, {'rev': 0}, context)
                self.assertEqual(caught.exception.http, expected)
            fetch.assert_not_called()
        self.assertEqual(self.images.calls, [])
        self.assertEqual(self.service.leer('100')['rev'], 0)

    def test_public_extraction_rejects_stale_revision_before_fetch(self):
        self.service.guardar('100', self.document(), CTX_UI)
        before = self.service.leer('100')
        with patch('creatorhub.productos_publicos.obtener_producto_publico') as fetch:
            with self.assertRaises(ErrorDominio) as caught:
                self.service.extraer('100', {'rev': 0}, CTX_UI)
            self.assertEqual(caught.exception.http, 409)
            fetch.assert_not_called()
        self.assertEqual(self.service.leer('100'), before)

    def test_public_extraction_source_failure_preserves_previous_data_and_sanitizes_error(self):
        self.service.guardar('100', self.document(), CTX_UI)
        before = self.service.leer('100')
        versions, queue_count = self.store.versiones(), len(self.images.calls)
        bus_count = self.bus.notificar_cambio.call_count
        failures = (RuntimeError('private source payload: token=never-publish'),
                    ErrorDominio('fuente_no_disponible', 'No pudimos consultar el producto.', http=503))
        for failure in failures:
            with self.subTest(kind=type(failure).__name__):
                with patch('creatorhub.productos_publicos.obtener_producto_publico', side_effect=failure) as fetch:
                    with self.assertRaises(ErrorDominio) as caught:
                        self.service.extraer('100', {'rev': 1}, CTX_UI)
                    self.assertEqual(caught.exception.http, 503)
                    self.assertNotIn('private source payload', str(caught.exception))
                    self.assertNotIn('never-publish', json.dumps(caught.exception.a_respuesta()))
                    fetch.assert_called_once()
                self.assertEqual(self.service.leer('100'), before)
                self.assertEqual(self.store.versiones(), versions)
                self.assertEqual(len(self.images.calls), queue_count)
                self.assertEqual(self.bus.notificar_cambio.call_count, bus_count)
                # A failed read cannot replace the existing reviews with a
                # fabricated zero count or an empty list.
                self.assertEqual(self.service.leer('100')['resenas']['total'], 1)
                self.assertEqual(len(self.service.leer('100')['resenas']['items']), 1)

    def test_public_extraction_rechecks_revision_after_fetch_and_preserves_concurrent_change(self):
        captured = self.document()
        captured.pop('rev')
        concurrent = self.document()
        concurrent['tabla_tallas']['tabla']['filas'][0][1] = '99'

        def source(pid, ahora, url=None):
            self.assertFalse(self.store._w.in_transaction)
            # A different edit commits after extraction started but before its
            # result is applied. The old result must not overwrite that edit.
            self.service.guardar(pid, concurrent, CTX_UI)
            return copy.deepcopy(captured)

        with patch('creatorhub.productos_publicos.obtener_producto_publico', side_effect=source) as fetch:
            with self.assertRaises(ErrorDominio) as caught:
                self.service.extraer('100', {'rev': 0}, CTX_UI)
            self.assertEqual(caught.exception.http, 409)
            fetch.assert_called_once()
        current = self.service.leer('100')
        self.assertEqual(current['rev'], 1)
        self.assertEqual(current['tabla_tallas']['tabla']['filas'][0][1], '99')

    def test_public_extraction_partial_result_preserves_last_available_reviews(self):
        self.service.guardar('100', self.document(), CTX_UI)
        previous = self.service.leer('100')['resenas']
        chart = self.document()['tabla_tallas']
        chart['tabla']['filas'][0][1] = '98'
        captured = {'tabla_tallas': chart,
                    'resenas': {'estado': 'no_disponible', 'fuente': self.source(), 'consultado_at': self.now}}
        with patch('creatorhub.productos_publicos.obtener_producto_publico', return_value=captured) as fetch:
            result = self.service.extraer('100', {'rev': 1}, CTX_UI)
            fetch.assert_called_once()
        self.assertEqual(result['rev'], 2)
        self.assertEqual(result['tabla_tallas']['tabla']['filas'][0][1], '98')
        self.assertEqual(result['resenas'], previous)

    def test_public_extraction_without_available_data_never_overwrites_previous_evidence(self):
        self.service.guardar('100', self.document(), CTX_UI)
        previous = self.service.leer('100')
        versions, queue_count = self.store.versiones(), len(self.images.calls)
        captured = {'tabla_tallas': {'estado': 'no_disponible'}, 'resenas': {'estado': 'pendiente'}}
        with patch('creatorhub.productos_publicos.obtener_producto_publico', return_value=captured) as fetch:
            with self.assertRaises(ErrorDominio) as caught:
                self.service.extraer('100', {'rev': 1}, CTX_UI)
            self.assertEqual(caught.exception.http, 503)
            self.assertEqual(caught.exception.codigo, 'fuente_sin_datos')
            fetch.assert_called_once()
        self.assertEqual(self.service.leer('100'), previous)
        self.assertEqual(self.store.versiones(), versions)
        self.assertEqual(len(self.images.calls), queue_count)


class ProductEvidenceMigrationTests(unittest.TestCase):
    def test_v5_database_migration_preserves_existing_products_images_notes_and_revisions(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'synthetic-v5.sqlite'
            schema = leer_recurso_sql('schema.sql')
            legacy, removed = re.subn(r'CREATE TABLE IF NOT EXISTS ["\']?producto_evidencia["\']?\s*\(.*?\) STRICT;',
                                      '', schema, flags=re.S)
            self.assertEqual(removed, 1, 'the legacy fixture must remove the v6 evidence table')
            legacy = re.sub(r'CREATE INDEX[^;]+ ON producto_evidencia[^;]+;', '', legacy)
            # rev. 7 · Una base v5 tampoco tiene la tabla de trazas de orders/search 202410 (007.sql).
            legacy, sin_trazas = re.subn(r'CREATE TABLE IF NOT EXISTS orden_lineas_traza\s*\(.*?\) STRICT;', '', legacy,
                                         flags=re.S)
            self.assertEqual(sin_trazas, 1, 'the legacy fixture must remove the v7 trace table')
            legacy = legacy.replace("('p','v','a','g','m','e')", "('p','v','a','g','m')")
            legacy, versiones = re.subn(r'PRAGMA user_version\s*=\s*\d+\s*;', 'PRAGMA user_version = 5;', legacy)
            self.assertEqual(versiones, 1)
            db = sqlite3.connect(path)
            db.executescript(legacy)
            db.execute("INSERT INTO productos(product_id,titulo,actualizado_at) VALUES('100','Original sintético',1800000000)")
            db.execute("INSERT INTO imagenes(img_key,tipo,ref_id,url_origen,version,estado,actualizado_at) "
                       "VALUES('p:100','p','100','https://p.tiktokcdn.com/original.jpg','1234abcd','ok',1800000000)")
            db.execute("INSERT INTO notas(id,entidad,entidad_id,texto,creado_at,actualizado_at) "
                       "VALUES('legacy-note','producto','100','Nota sintética original',1800000000,1800000000)")
            db.executemany('INSERT OR REPLACE INTO meta(clave,valor) VALUES(?,?)',
                           [('data_version', '9'), ('local_rev', '7'), ('img_rev', '5')])
            db.commit()
            db.close()
            clock = SimpleNamespace(ahora=lambda: 1_800_000_000)
            store = crear_almacen(str(path), clock)
            try:
                with store.lector() as db:
                    self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 7)      # 5 → 6 → 7 en una sola apertura
                    self.assertEqual(db.execute('SELECT count(*) FROM orden_lineas_traza').fetchone()[0], 0)
                    self.assertEqual(db.execute('SELECT titulo FROM productos WHERE product_id=?', ('100',)).fetchone()[0],
                                     'Original sintético')
                    self.assertEqual(tuple(db.execute('SELECT tipo,version,estado FROM imagenes').fetchone()),
                                     ('p', '1234abcd', 'ok'))
                    self.assertEqual(db.execute('SELECT texto FROM notas').fetchone()[0], 'Nota sintética original')
                    self.assertEqual(db.execute('SELECT count(*) FROM producto_evidencia').fetchone()[0], 0)
                self.assertEqual(store.versiones(), (9, 7, 5))
                self.assertTrue(Path(str(path) + '.bak-v5').is_file())
                with store.escritor() as db:
                    db.execute("INSERT INTO imagenes(img_key,tipo,ref_id,estado,actualizado_at) "
                               "VALUES('e:100-0123456789abcdef','e','100-0123456789abcdef','pendiente',1800000000)")
            finally:
                store.cerrar()


if __name__ == '__main__':
    unittest.main()
