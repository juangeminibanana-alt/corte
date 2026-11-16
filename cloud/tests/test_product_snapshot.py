"""Product galleries/SKUs survive the real SQLite offline snapshot; synthetic data only."""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'hub'))
from creatorhub.almacen import crear_almacen
from creatorhub.analitica.servicio import AnaliticaSqlite, MAX_FICHAS_COPIA
from creatorhub.analitica.vista import Vista
from creatorhub.api.rutas import crear_despachador
from creatorhub.interfaces import CTX_UI
from creatorhub.sincronizador_ficha import skus_muestra


class ProductSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.now = 1_800_000_000
        self.clock = SimpleNamespace(ahora=lambda: self.now, monotonico=lambda: 1_000_000.0)
        self.store = crear_almacen(str(Path(self.folder.name) / 'synthetic.sqlite'), self.clock)
        self.analytics = AnaliticaSqlite(self.store, self.clock)

    def tearDown(self):
        self.store.cerrar()
        self.folder.cleanup()

    def product(self, pid, sample=False):
        with self.store.escritor() as db:
            db.execute('INSERT INTO productos(product_id,titulo,actualizado_at) VALUES(?,?,?)',
                       (pid, 'Producto sintético ' + pid, self.now))
            db.execute('INSERT INTO vitrina(product_id,galeria_json,actualizado_at) VALUES(?,?,?)',
                       (pid, json.dumps(['https://p.tiktokcdn.com/synthetic-a.jpg',
                                         'https://p.tiktokcdn.com/synthetic-b.jpg']), self.now))
            if sample:
                db.execute('INSERT INTO muestras(application_id,product_id,estado_api,clase,subestado,'
                           'clase_desde_at,primera_vez_at,huella,actualizado_at) VALUES(?,?,?,?,?,?,?,?,?)',
                           ('9' + pid, pid, 'COMPLETE', 'entregada', 'video_aprobado',
                            self.now, self.now, 'synthetic', self.now))

    def test_real_snapshot_keeps_gallery_variants_and_precaches_downloaded_gallery(self):
        self.product('100', sample=True)
        normalized = skus_muestra({'sample_product': {'sample_sku_list': [{
            'id': '200', 'sale_properties': [{'name': 'Color', 'value_name': 'Azul'},
                                            {'name': 'Talla', 'value_name': 'M'}],
            'price': {'amount': '123.45', 'currency': 'MXN'}, 'is_available': True}]}})
        with self.store.escritor() as db:
            db.execute('INSERT INTO muestra_etiquetas(product_id,puede_solicitar,skus_json,consultado_at,'
                       'huella,actualizado_at) VALUES(?,?,?,?,?,?)',
                       ('100', 1, json.dumps(normalized), self.now, 'synthetic', self.now))
            for index, state, version in [(0, 'ok', '1234abcd'), (1, 'pendiente', None)]:
                db.execute('INSERT INTO imagenes(img_key,tipo,ref_id,url_origen,estado,version,ancho,alto,'
                           'actualizado_at) VALUES(?,?,?,?,?,?,?,?,?)',
                           (f'g:100-{index}', 'g', f'100-{index}', 'https://p.tiktokcdn.com/synthetic.jpg',
                            state, version, 800, 800, self.now))
        snapshot = self.analytics.snapshot(None, {}, {})
        detail = snapshot['extras']['productos']['100']
        self.assertEqual(detail['galeria'], ['/img/g/100-0?v=1234abcd', '/img/g/100-1?v=0'])
        sku = detail['muestra']['skus'][0]
        self.assertEqual(sku['variante'], 'Azul / M')
        self.assertEqual(sku['propiedades'][0], {'nombre': 'Color', 'valor': 'Azul'})
        self.assertEqual(sku['precio_centavos'], 12345)
        self.assertIn('/img/g/100-0?v=1234abcd', snapshot['meta_imagenes'])
        self.assertIn('/img/g/100-0?v=1234abcd&t=sm', snapshot['imagenes'])
        self.assertNotIn('/img/g/100-1?v=0&t=sm', snapshot['imagenes'])

    def test_bounded_selection_prioritizes_pending_samples_and_never_adds_unrepresented_products(self):
        for n in range(MAX_FICHAS_COPIA + 2):
            self.product(str(1000 + n))
        pending = str(1000 + MAX_FICHAS_COPIA + 1)
        with self.store.lector() as db:
            view = Vista(db, self.now)
            with patch.object(view, 'producto_extendido', wraps=view.producto_extendido) as render:
                selected = self.analytics._productos_copia(view, [{'product_id': pending}], [],
                                                          [{'product_id': str(1000 + n)}
                                                           for n in range(MAX_FICHAS_COPIA + 1)])
        self.assertEqual(len(selected), MAX_FICHAS_COPIA)
        self.assertEqual(next(iter(selected)), pending)
        self.assertEqual(render.call_count, MAX_FICHAS_COPIA)
        self.assertNotIn(str(1000 + MAX_FICHAS_COPIA), selected)

    def test_uncached_product_is_not_fabricated_or_queried_remotely(self):
        self.product('100')
        with self.store.lector() as db:
            view = Vista(db, self.now)
            with patch.object(view, 'producto_extendido', wraps=view.producto_extendido) as render:
                selected = self.analytics._productos_copia(view, [], [], [{'product_id': '999'}])
        self.assertEqual(selected, {})
        render.assert_not_called()

    def test_old_snapshot_tag_fetches_new_representation_then_matching_tag_returns_304(self):
        hub = SimpleNamespace(analitica=self.analytics, reloj=self.clock,
                              auth=SimpleNamespace(cuenta=lambda: None, conexion=lambda: {}),
                              sincronizador=SimpleNamespace(estado=lambda: {}))
        dispatcher = crear_despachador(hub)
        old_tag = 'W/"' + self.analytics.etag() + '"'
        first = dispatcher.despachar('GET', '/api/snapshot', '', {'If-None-Match': old_tag}, b'', CTX_UI)
        self.assertEqual(first.status, 200)
        current_tag = dict(first.cabeceras)['ETag']
        self.assertNotEqual(current_tag, old_tag)
        body = json.loads(first.cuerpo)
        self.assertEqual(body['extras']['productos'], {})
        self.assertEqual(body['version_esquema'], 1)
        self.assertIn('img_rev', body)
        second = dispatcher.despachar('GET', '/api/snapshot', '', {'If-None-Match': current_tag}, b'', CTX_UI)
        self.assertEqual(second.status, 304)
        self.assertEqual(second.cuerpo, b'')


if __name__ == '__main__':
    unittest.main()
