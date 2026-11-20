"""Agenda real en SQLite temporal, reloj controlado y transporte sintético."""
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'hub'))
from cloud.tests import test_rutas_publicaciones as rutas
from creatorhub.almacen import USER_VERSION, crear_almacen
from creatorhub.errores import ErrorDominio
from creatorhub.hub import Hub
from creatorhub.tiktok.agenda_publicaciones import AgendaPublicaciones, RECUPERAR_TRAS_S
from creatorhub.tiktok.publicaciones import PublicacionesShop
from creatorhub.tiktok.registro_publicacion import RegistroPublicacion


class AgendaTests(unittest.TestCase):
    def setUp(self):
        carpeta = tempfile.TemporaryDirectory()
        self.addCleanup(carpeta.cleanup)
        self.ruta = Path(carpeta.name) / 'test.sqlite'
        self.instante = 1_800_000_000
        self.ahora = lambda: self.instante
        self.reloj = SimpleNamespace(ahora=self.ahora)
        self.grant = {'user_type': 1, 'open_id': 'creator-sintetico', 'epoca_credenciales': 2,
                      'granted_scopes': ['creator.video.write']}
        self.boveda = SimpleNamespace(leer=lambda: self.grant.copy())
        self.cliente = Mock()
        self.cliente.llamar.return_value = {'video': {'id': '1234'}}
        self.abrir()
        self.addCleanup(lambda: self.db.cerrar())
        self.video = rutas.VIDEO.copy()
        self.body = {**self.video, 'confirmar': True, 'programada_at': self.instante + 60}

    def abrir(self):
        self.db = crear_almacen(str(self.ruta), self.reloj)
        self.registro = RegistroPublicacion(self.db, self.ahora)
        self.publicaciones = PublicacionesShop(self.cliente, self.boveda, lambda: {'estado': 'conectada'},
                                              self.db, self.registro)
        self.agenda = AgendaPublicaciones(self.publicaciones, self.db, self.ahora)

    def test_confirmacion_fecha_permiso_idempotencia_y_purgado(self):
        for cambios in ({'confirmar': False}, {'confirmar': 1}, {'programada_at': self.instante},
                        {'programada_at': True}, {'programada_at': 2**90}, {'product_id': 'bad'}):
            with self.subTest(cambios=cambios), self.assertRaises(ErrorDominio):
                self.agenda.programar({**self.body, **cambios})
        self.assertEqual(self.agenda.listar(), {'items': []})
        self.grant['granted_scopes'] = []
        with self.assertRaises(ErrorDominio):
            self.agenda.programar(self.body)
        self.grant['granted_scopes'] = ['creator.video.write']
        original = self.agenda.programar(self.body)
        self.assertEqual(self.agenda.programar(self.body), original)
        with self.assertRaises(ErrorDominio):
            self.agenda.programar({**self.body, 'titulo': 'Otro'})
        self.assertNotIn('file_id', original)
        self.instante += 60
        self.agenda.ejecutar_siguiente()
        self.assertEqual(self.agenda.programar(self.body)['video_id'], '1234')
        self.db.borrar('tiktok')
        self.assertEqual(self.agenda.listar(), {'items': []})
        with self.db.lector() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM agenda_publicaciones_shop').fetchone()[0], 0)

    def test_ejecuta_despues_de_reinicio_solo_cuando_vence(self):
        plan = self.agenda.programar(self.body)
        self.agenda.ejecutar_siguiente()
        self.cliente.llamar.assert_not_called()
        self.db.cerrar()
        self.abrir()
        self.instante += 60
        self.agenda.ejecutar_siguiente()
        self.agenda.ejecutar_siguiente()
        self.cliente.llamar.assert_called_once()
        self.assertEqual(self.agenda.listar()['items'], [{**plan, 'estado': 'aceptada', 'video_id': '1234'}])
        with self.db.lector() as db:
            self.assertIsNone(db.execute('SELECT file_id FROM agenda_publicaciones_shop').fetchone()[0])

    def test_aislamiento_cancelacion_y_permiso_revocado(self):
        plan = self.agenda.programar(self.body)
        self.grant['open_id'] = 'otra-cuenta'
        self.assertEqual(self.agenda.listar(), {'items': []})
        with self.assertRaises(ErrorDominio) as error:
            self.agenda.cancelar(plan['id'], {})
        self.assertEqual(error.exception.http, 404)
        self.instante += 60
        self.agenda.ejecutar_siguiente()
        self.grant.update(open_id='creator-sintetico', granted_scopes=[])
        self.assertEqual(self.agenda.listar()['items'][0]['id'], plan['id'])
        cancelado = self.agenda.cancelar(plan['id'], {})
        self.assertEqual(self.agenda.cancelar(plan['id'], {}), cancelado)
        self.assertEqual(cancelado['estado'], 'cancelada')
        self.agenda.ejecutar_siguiente()
        self.grant['granted_scopes'] = ['creator.video.write']
        nuevo = self.agenda.programar({**self.body, 'programada_at': self.instante + 3})
        self.grant['granted_scopes'] = []
        self.instante += 4
        self.agenda.ejecutar_siguiente()
        estado = {p['id']: p['estado'] for p in self.agenda.listar()['items']}
        self.assertEqual(estado, {plan['id']: 'cancelada', nuevo['id']: 'fallida'})
        self.cliente.llamar.assert_not_called()

    def test_dos_trabajadores_y_cancelacion_durante_envio(self):
        plan = self.agenda.programar(self.body)
        inicio, fin = threading.Event(), threading.Event()

        def enviar(*args, **kwargs):
            inicio.set()
            if not fin.wait(10):
                raise RuntimeError('El transporte sintético no recibió la señal.')
            return {'video': {'id': '1234'}}

        self.cliente.llamar.side_effect = enviar
        self.instante += 60
        hilo = threading.Thread(target=self.agenda.ejecutar_siguiente)
        hilo.start()
        try:
            self.assertTrue(inicio.wait(5))
            self.agenda.ejecutar_siguiente()
            with self.assertRaises(ErrorDominio) as error:
                self.agenda.cancelar(plan['id'], {})
            self.assertEqual(error.exception.http, 409)
        finally:
            fin.set()
            hilo.join(5)
        self.cliente.llamar.assert_called_once()
        self.assertEqual(self.agenda.listar()['items'][0]['estado'], 'aceptada')

    def test_recuperacion_tras_reserva_o_aceptacion_interrumpida(self):
        for tipo in ('antes', 'incierto', 'aceptado'):
            with self.subTest(tipo=tipo):
                video = {**self.video, 'file_id': 'archivo-' + tipo}
                plan = self.agenda.programar({**video, 'confirmar': True, 'programada_at': self.instante + 2})
                with self.db.escritor() as db:
                    db.execute("UPDATE agenda_publicaciones_shop SET estado='enviando', intento='viejo', intento_at=? "
                               "WHERE id=?", (self.instante, plan['id']))
                if tipo == 'incierto':
                    self.registro.iniciar(self.publicaciones.contexto(), video['file_id'],
                                          self.publicaciones.preparar(video)['payload'])
                if tipo == 'aceptado':
                    self.publicaciones.publicar({**video, 'confirmar': True})
                    self.grant['granted_scopes'] = []
                self.cliente.reset_mock()
                self.instante += RECUPERAR_TRAS_S + 1
                self.agenda.ejecutar_siguiente()
                self.agenda.ejecutar_siguiente()
                fila = next(p for p in self.agenda.listar()['items'] if p['id'] == plan['id'])
                self.assertEqual(fila['estado'], 'por_verificar' if tipo == 'incierto' else 'aceptada')
                self.assertEqual(self.cliente.llamar.call_count, int(tipo == 'antes'))

    def test_migra_desde_v8_conservando_datos(self):
        self.db.cerrar()
        with sqlite3.connect(self.ruta) as db:
            db.execute('DROP TABLE agenda_publicaciones_shop')
            db.execute('PRAGMA user_version=8')
        db.close()
        self.abrir()
        self.assertTrue(Path(str(self.ruta) + '.bak-v8').is_file())
        self.agenda.programar(self.body)
        with self.db.lector() as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], USER_VERSION)


class AgendaRutasTests(unittest.TestCase):
    def test_lectura_cancelacion_y_tic_por_las_entradas_reales(self):
        web = rutas.RutasPublicacionesTests()
        web.setUp()
        self.addCleanup(web.doCleanups)
        pub = web.hub.publicaciones_shop
        instante = 1_800_000_000
        web.hub.agenda_shop = AgendaPublicaciones(pub, pub._almacen, lambda: instante)
        scope = web.scope()
        plan = {**rutas.VIDEO, 'programada_at': instante + 1, 'confirmar': True}
        for metodo, path, kw in [('GET', 'agenda', {}), ('POST', 'agenda', {'json': plan}),
                                 ('POST', 'agenda/abc/cancelar', {'json': {}})]:
            self.assertEqual(web.request(metodo, path, **kw).status_code, 409)
        web.hub.planificador = Mock()
        web.hub.modo = 'real'
        web.hub._tarea_publicar_video = lambda: Hub._tarea_publicar_video(web.hub)
        web.hub._parar = threading.Event()
        Hub.registrar_tareas(web.hub)
        tic = next(c.args[2] for c in web.hub.planificador.registrar_tarea.call_args_list
                   if c.args[0] == 'publicar_videos_programados')
        resultado = web.request('POST', 'agenda', cabeceras=scope, json=plan)
        self.assertEqual(resultado.status_code, 200)
        self.assertEqual(web.request('GET', 'agenda', cabeceras=scope).json['items'], [resultado.json])
        instante += 1
        web.cliente.llamar.return_value = {'video': {'id': '789'}}
        tic()
        self.assertEqual(web.request('GET', 'agenda', cabeceras=scope).json['items'][0]['video_id'], '789')
        self.assertEqual(web.request('POST', 'agenda/' + resultado.json['id'] + '/cancelar',
                                     cabeceras=scope, json={}).status_code, 409)
