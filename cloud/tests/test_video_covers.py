"""Video identity and signed-cover cache regressions; synthetic data only."""
import datetime as dt
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'hub'))
from creatorhub.almacen import crear_almacen
from creatorhub.analitica.display import DatosDisplay
from creatorhub.analitica.vista import Vista
from creatorhub.imagenes.servicio import _Imagenes
from creatorhub.interfaces import PedidoImagen


class VideoIdentityTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            CREATE TABLE imagenes(img_key TEXT, tipo TEXT, ref_id TEXT, estado TEXT, version TEXT,
                                  url_origen TEXT, ancho INTEGER, alto INTEGER, lqip TEXT, color TEXT);
            CREATE TABLE cuenta(username TEXT, id INTEGER);
            CREATE TABLE videos(content_id TEXT, portada_product_id TEXT);
            INSERT INTO videos VALUES('7001','100'),('7002','100');
            INSERT INTO cuenta VALUES('creador_sintetico', 1);
            INSERT INTO imagenes VALUES('p:100','p','100','ok','11111111','https://p.tiktokcdn.com/product.jpg',800,800,NULL,NULL);
            INSERT INTO imagenes VALUES('v:7001','v','7001','ok','22222222','https://p.tiktokcdn.com/video.jpg',720,1280,NULL,NULL);
        ''')

    def tearDown(self):
        self.db.close()

    def view(self, display=None):
        view = Vista(self.db, 1_800_000_000)
        view.__dict__['M'] = []
        view.__dict__['display'] = display
        view.__dict__['L'] = [{'content_id': cid, 'product_id': '100', 'tipo_contenido': 'VIDEO',
                             'com_estimada_centavos': 400, 'valida': True, 'order_id': 'synthetic-' + cid,
                             'tienda_nombre': 'Tienda sintética', 'fecha': '2026-11-01',
                             '_d': dt.date(2026, 11, 1), 'unidades_netas': 1,
                             'ventas_linea_centavos': 5000, 'es_pedido_muestra': False} for cid in ('7001', '7002')]
        return view

    def test_real_cover_is_bound_to_video_even_when_same_product_sold_in_two_videos(self):
        view = self.view()
        by_id = {v['content_id']: v for v in view.videos_todos(None, None)}
        self.assertEqual(by_id['7001']['miniatura'], '/img/v/7001?v=22222222')
        self.assertEqual(by_id['7001']['portada'], by_id['7001']['miniatura'])
        self.assertEqual(by_id['7001']['producto_principal_id'], '100')
        self.assertIsNone(by_id['7002']['miniatura'])
        self.assertIsNone(by_id['7002']['portada'])
        self.assertTrue(all(v['miniatura_origen'] is None for v in by_id.values()))
        self.assertNotIn('/img/p/', str(by_id))
        self.assertIn('/img/v/7001?v=22222222', view.img.meta_para(list(by_id.values())))

    def test_missing_optional_metrics_do_not_erase_real_cached_cover_in_product_or_video_lists(self):
        view = self.view(DatosDisplay(videos={}))
        rows = view.videos_del_producto('100')
        by_id = {v['content_id']: v for v in rows}
        self.assertEqual(by_id['7001']['portada'], '/img/v/7001?v=22222222')
        self.assertIsNone(by_id['7002']['portada'])
        self.assertIsNone(by_id['7001']['vistas'])
        self.assertEqual(view.videos_todos(None, None)[0]['portada'], '/img/v/7001?v=22222222')


class SignedCoverCacheTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.now = 1_800_000_000
        self.clock = SimpleNamespace(ahora=lambda: self.now, monotonico=lambda: 1_000_000.0)
        self.store = crear_almacen(str(Path(self.folder.name) / 'synthetic.sqlite'), self.clock)
        self.images = _Imagenes(self.store, Mock(), self.clock, str(Path(self.folder.name) / 'images'), Mock())

    def tearDown(self):
        self.store.cerrar()
        self.folder.cleanup()

    def insert(self, key, state='pendiente', attempts=0, age=0):
        kind, ref = key.split(':')
        with self.store.escritor() as db:
            db.execute('INSERT INTO imagenes(img_key,tipo,ref_id,url_origen,url_huella,estado,intentos,actualizado_at) '
                       'VALUES(?,?,?,?,?,?,?,?)', (key, kind, ref,
                       'https://p.tiktokcdn.com/synthetic.jpg?x-expires=1800000010', 'synthetic-path-fingerprint',
                       state, attempts, self.now - age))

    def test_pending_real_video_covers_resume_after_restart_but_deferred_gallery_does_not(self):
        self.insert('v:7001')
        self.insert('g:100-0')
        self.insert('m:100')
        self.images._cargar_pendientes()
        self.assertIn('v:7001', self.images._cola.claves())
        self.assertNotIn('g:100-0', self.images._cola.claves())
        self.assertNotIn('m:100', self.images._cola.claves())

    def test_failed_video_covers_are_eligible_for_bounded_long_retry(self):
        self.insert('v:7001', 'error', 4, 86401)
        self.insert('g:100-0', 'error', 4, 86401)
        self.images._revisar_errores_largos()
        self.assertEqual(self.images._cola.claves(), ['v:7001'])

    def test_fresh_signature_requeues_failed_cover_and_keeps_exact_video_key(self):
        old = 'https://p.tiktokcdn.com/synthetic-cover.jpg?x-expires=1&x-signature=old'
        new = 'https://p.tiktokcdn.com/synthetic-cover.jpg?x-expires=1800020000&x-signature=new'
        self.images.encolar([PedidoImagen('v', '7001', old, 1, 'portada')])
        self.images._cola.vaciar()
        with self.store.escritor() as db:
            db.execute("UPDATE imagenes SET estado='error',intentos=4,ultimo_error='http_403' WHERE img_key='v:7001'")
        self.images.encolar([PedidoImagen('v', '7001', new, 1, 'portada')])
        self.assertEqual(self.images._cola.claves(), ['v:7001'])
        with self.store.lector() as db:
            row = db.execute("SELECT url_origen,intentos,ultimo_error FROM imagenes WHERE img_key='v:7001'").fetchone()
        self.assertEqual(row['url_origen'], new)
        self.assertEqual(row['intentos'], 0)
        self.assertIsNone(row['ultimo_error'])


if __name__ == '__main__':
    unittest.main()
