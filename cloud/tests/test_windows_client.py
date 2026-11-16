"""Pruebas de cliente Windows con SQLite real y transporte sintético."""
from __future__ import annotations
import json
from pathlib import Path
import secrets
import sqlite3
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import Mock
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'hub'))
from creatorhub.almacen import crear_almacen
from creatorhub.boveda import BovedaDpapi
from creatorhub.cliente_nativo import ClienteNativo, CacheNativa, DespachadorNativo, HttpsCorte, SinRed, codificar, respuesta, ORIGEN
from creatorhub.config import rutas_para
from creatorhub.eventos import crear_bus
from creatorhub.interfaces import CTX_UI
from creatorhub.local import crear_estado_local
from creatorhub.reloj import crear_reloj


class WindowsClientTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        rutas = rutas_para('real', self.folder.name)
        self.reloj = crear_reloj()
        self.bus = crear_bus()
        self.db = crear_almacen(rutas.db, self.reloj)
        local = crear_estado_local(self.db, self.bus, self.reloj)
        local.sembrar()
        self.hub = types.SimpleNamespace(rutas=rutas, reloj=self.reloj, bus=self.bus, local=local,
                                          boveda=BovedaDpapi(None, {'open_id': 'synthetic-account'}), abrir_url=Mock())
        self.transport = Mock()
        self.transport.pedir.side_effect = AssertionError('Unexpected network call')
        self.vault = BovedaDpapi(None, {'native_token': 'corte_native_v1_' + 'a' * 43,
                                      'expires_at': int(time.time()) + 3600})
        self.client = ClienteNativo(self.hub, self.transport, self.vault)

    def tearDown(self):
        self.client.detener()
        self.db.cerrar()
        self.folder.cleanup()

    def snapshot(self):
        return {'version_esquema': 1, 'muestras': [], 'imagenes': [],
                'local': self.client.local.exportar()}

    def test_state_never_exposes_token_or_proof_and_401_really_clears_auth(self):
        self.assertTrue(self.client.estado()['authenticated'])
        self.assertNotIn('corte_native_v1_', json.dumps(self.client.estado()))
        self.transport.pedir.side_effect = None
        self.transport.pedir.return_value = respuesta({'error': {'codigo': 'sesion_invalida'}}, 401)
        self.client.remoto('GET', '/api/native/session')
        self.assertFalse(self.client.estado()['authenticated'])
        self.assertFalse(self.client.token())

    def test_tiktok_403_is_not_a_device_logout(self):
        self.transport.pedir.side_effect = None
        self.transport.pedir.return_value = respuesta({'error': {'codigo': 'sin_permiso_tiktok'}}, 403)
        self.client.remoto('POST', '/api/sync', {})
        self.assertTrue(self.client.estado()['authenticated'])

    def test_late_401_cannot_clear_newly_approved_credential(self):
        def approve_while_old_request_is_inflight(*args):
            self.vault.mutar(lambda d: d.update(native_token='corte_native_v1_' + 'b' * 43))
            return respuesta({'error': {'codigo': 'sesion_nativa_invalida'}}, 401)
        self.transport.pedir.side_effect = approve_while_old_request_is_inflight
        self.client.remoto('GET', '/api/session')
        self.assertTrue(self.client.estado()['authenticated'])
        self.assertTrue(self.client.token().endswith('b' * 43))

    def test_temporary_identity_outage_keeps_pending_pkce_request(self):
        self.client.pending = {'request_id': 'synthetic-request', 'code_verifier': 'v' * 43,
                               'expires_at': int(time.time()) + 600, 'user_code': 'ABCD-EFGH',
                               'verification_uri': ORIGEN + '/conectar-dispositivo?codigo=ABCD-EFGH'}
        self.transport.pedir.side_effect = None
        self.transport.pedir.return_value = respuesta({'error': {'codigo': 'identidad_no_disponible'}}, 503)
        self.client._consultar_autorizacion()
        self.assertIsNotNone(self.client.pending)

    def test_native_file_import_reads_selected_json_and_sends_only_organization(self):
        payload = {'formato': 'corte-local', 'version': 1, 'planes': [], 'notas': [],
                   'app_secret': 'must-never-be-forwarded'}
        self.transport.pedir.side_effect = [respuesta({'tiktok_open_id': 'synthetic-account'}),
                                            respuesta({'importados': {}})]
        dispatcher = DespachadorNativo(self.client, Mock())
        with patch('creatorhub.api.archivos.leer_json_usuario', return_value=payload):
            r = dispatcher.despachar('POST', '/api/local/importar', '', {},
                                      codificar({'ruta': 'C:\\selected.json'}), CTX_UI)
        self.assertEqual(r.status, 200)
        self.assertEqual(self.transport.pedir.call_args.args[1], '/api/cloud/import')
        self.assertNotIn('app_secret', self.transport.pedir.call_args.args[2].decode())
        self.assertEqual(self.transport.pedir.call_args.args[4], 'synthetic-account')

    def test_migration_can_be_deferred_without_destroying_backups(self):
        self.client.manual_original = True
        self.assertTrue(self.client.estado()['migration_pending'])
        self.client.migrar(False)
        self.assertFalse(self.client.estado()['migration_pending'])
        self.assertTrue(self.client.estado()['migration_available'])
        self.client._migrar({'tiktok_open_id': 'synthetic-account'})
        self.transport.pedir.assert_not_called()
        self.assertTrue(Path(self.hub.rutas.raiz, 'datos', 'antes_de_nube.sqlite').exists())

    def test_pkce_flow_opens_only_system_browser_and_keeps_token_out_of_public_state(self):
        self.transport.pedir.side_effect = None
        self.transport.pedir.return_value = respuesta({'request_id': 'synthetic-request', 'user_code': 'ABCD-EFGH',
                                                     'verification_uri': ORIGEN + '/conectar-dispositivo?codigo=ABCD-EFGH',
                                                     'expires_in': 600, 'interval': 3})
        state = self.client.conectar()
        self.hub.abrir_url.assert_called_once()
        self.assertNotIn('code_verifier', json.dumps(state))
        request = json.loads(self.transport.pedir.call_args.args[2])
        self.assertEqual(len(request['code_challenge']), 43)
        self.transport.pedir.return_value = respuesta({'estado': 'autorizado', 'device_id': 'synthetic-device',
                                                       'token': 'corte_native_v1_' + 'b' * 43,
                                                       'expires_at': int(time.time()) + 3600,
                                                       'owner': {'uid': 'synthetic-owner', 'email': 'owner@example.test'}})
        self.client._consultar_autorizacion()
        self.assertTrue(self.client.estado()['authenticated'])
        self.assertEqual(self.client.token(), 'corte_native_v1_' + 'b' * 43)
        self.assertNotIn('corte_native_v1_', json.dumps(self.client.estado()))

    def test_redirect_and_arbitrary_upstream_paths_are_rejected_before_network(self):
        http = HttpsCorte()
        for path in ['https://evil.example/api/session', '//evil.example/api/session', '/api/../secret', '/api/x\\y',
                     '/api/native/%73ession', '/api/native%2fsession', '/api/native/%2573ession',
                     '/api/x//session', '/api/x/./session', '/api/x/%2e%2e/session']:
            with self.assertRaises(ValueError):
                http.pedir('GET', path)
        self.transport.pedir.side_effect = None
        self.transport.pedir.return_value = respuesta({'request_id': 'request', 'user_code': 'CODE',
                                                       'verification_uri': 'https://evil.example/conectar-dispositivo',
                                                       'expires_in': 600})
        with self.assertRaises(ValueError):
            self.client.conectar()
        self.hub.abrir_url.assert_not_called()

    def test_native_private_routes_and_encoded_variants_never_reach_google_or_cache(self):
        dispatcher = DespachadorNativo(self.client, Mock())
        for path in ['/api/native/%73ession', '/api/native//session', '/api/native/./session',
                     '/api/native/session/', '/api/native/auth/start', '/api/native/devices/self/revoke']:
            with self.subTest(path=path):
                self.client.cache.guardar(path, respuesta({'tiktok_open_id': 'must-stay-private'}))
                r = dispatcher.despachar('GET', path, '', {}, b'', CTX_UI)
                self.assertIn(r.status, (404, 422))
                self.assertNotIn('must-stay-private', r.cuerpo.decode())
        public = dispatcher.despachar('GET', '/api/native/session', '', {}, b'', CTX_UI)
        self.assertEqual(public.status, 200)
        self.assertNotIn('tiktok_open_id', json.loads(public.cuerpo))
        self.transport.pedir.assert_not_called()

    def test_encoded_business_query_is_preserved_without_path_decoding(self):
        http = HttpsCorte()
        remote = Mock()
        remote.code, remote.headers = 200, {}
        remote.read.return_value = b'{}'
        remote.__enter__ = Mock(return_value=remote)
        remote.__exit__ = Mock(return_value=False)
        http.opener = Mock()
        http.opener.open.return_value = remote
        result = http.pedir('GET', '/api/muestras?q=texto%20con%2Fseparador')
        self.assertEqual(result.status, 200)
        self.assertTrue(http.opener.open.call_args.args[0].full_url.endswith('?q=texto%20con%2Fseparador'))

    @unittest.skipUnless(sys.platform == 'win32', 'Windows shell')
    def test_access_gate_closes_cleanly_and_authenticated_shell_keeps_close_dialog(self):
        from creatorhub.plataforma.windows.ventana import ShellVentana
        for estado in ({'authenticated': False}, {'authenticated': True, 'migration_pending': True},
                       {'authenticated': True, 'migration_pending': False}):
            with self.subTest(estado=estado):
                shell = ShellVentana.__new__(ShellVentana)
                shell.hub = types.SimpleNamespace(cliente_nativo=Mock(), ajustes_pc=lambda: {'segundo_plano': None})
                shell.hub.cliente_nativo.estado.return_value = estado
                shell._saliendo, shell._pregunta_at = False, None
                shell._monotonico = lambda: 1
                shell._despedirse, shell._publicar, shell.mostrar = Mock(), Mock(), Mock()
                with patch('creatorhub.plataforma.windows.ventana.threading.Thread'):
                    cerrado = shell.al_cerrar()
                if not estado['authenticated'] or estado.get('migration_pending'):
                    self.assertTrue(cerrado)
                    shell._despedirse.assert_called_once()
                    shell._publicar.assert_not_called()
                else:
                    self.assertFalse(cerrado)
                    shell._despedirse.assert_not_called()
                    shell._publicar.assert_called_once_with({'tipo': 'ventana.preguntar_cierre'})

    def test_sqlite_cache_survives_reopening_and_offline_reads_are_immediate(self):
        self.client.cache.guardar('/api/snapshot', respuesta(self.snapshot()))
        restored = CacheNativa(self.client.cache.ruta)
        self.assertIsNotNone(restored.leer('/api/snapshot'))
        dispatcher = DespachadorNativo(self.client, Mock())
        result = dispatcher.despachar('GET', '/api/snapshot', '', {}, b'', CTX_UI)
        self.assertEqual(result.status, 200)
        self.assertIn(('X-CH-Fuente', 'copia'), result.cabeceras)
        self.transport.pedir.assert_not_called()

    def test_historical_database_and_organization_backup_are_preserved(self):
        file = Path(self.hub.rutas.raiz, 'datos', 'antes_de_nube.sqlite')
        self.assertTrue(file.is_file())
        backup = sqlite3.connect(file)
        try:
            self.assertGreater(backup.execute('SELECT COUNT(*) FROM plantillas').fetchone()[0], 0)
        finally:
            backup.close()
        self.assertTrue(Path(self.hub.rutas.raiz, 'datos', 'organizacion_antes_de_nube.json').is_file())
        self.assertNotEqual(self.client.replica.ruta, self.db.ruta)
        self.client.cache.guardar('/api/snapshot', respuesta(self.snapshot()))
        self.transport.pedir.side_effect = None
        self.transport.pedir.return_value = respuesta(self.snapshot())
        self.client._actualizar_copia()
        with self.db.lector() as db:
            self.assertGreater(db.execute('SELECT COUNT(*) FROM plantillas').fetchone()[0], 0)

    def test_durable_outbox_replays_same_operation_id_and_clears_only_confirmation(self):
        revision = self.client.local.exportar()['preferencias']['rev']
        op = {'op_id': secrets.token_hex(16), 'tipo': 'preferencias.editar',
              'cambios': {'tema': 'oscuro', 'rev': revision}}
        result = self.client.aplicar_ops([op])
        self.assertEqual(result['en_cola'], [op['op_id']])
        self.assertEqual(CacheNativa(self.client.cache.ruta).pendientes(), [op])
        self.transport.pedir.side_effect = SinRed()
        with self.assertRaises(SinRed):
            self.client.flush()
        self.assertEqual(len(self.client.cache.pendientes()), 1)
        self.transport.pedir.side_effect = None
        self.transport.pedir.return_value = respuesta({'resultados': [{'op_id': op['op_id'], 'estado': 'duplicada'}]})
        self.client.flush()
        self.assertEqual(self.client.cache.pendientes(), [])
        payload = json.loads(self.transport.pedir.call_args.args[2])
        self.assertEqual(payload['ops'][0]['op_id'], op['op_id'])

    def test_logout_preserves_copy_and_pending_work(self):
        self.client.cache.guardar('/api/snapshot', respuesta(self.snapshot()))
        self.client.cache.encolar([{'op_id': 'pending-id', 'tipo': 'nota.crear'}])
        self.transport.pedir.side_effect = SinRed()
        state = self.client.salir()
        self.assertFalse(state['authenticated'])
        self.assertTrue(state['hay_copia'])
        self.assertEqual(len(self.client.cache.pendientes()), 1)

    def test_migration_requires_exact_tiktok_identity_and_confirmed_200(self):
        self.client.manual_original = True
        self.client._migrar({'tiktok_open_id': 'another-account'})
        self.transport.pedir.assert_not_called()
        self.assertIsNone(self.client.cache.meta('organizacion_migrada'))
        self.transport.pedir.side_effect = None
        self.transport.pedir.return_value = respuesta({}, 503)
        self.client._migrar({'tiktok_open_id': 'synthetic-account'})
        self.assertIsNone(self.client.cache.meta('organizacion_migrada'))
        self.transport.pedir.return_value = respuesta({'importados': {}})
        self.client._migrar({'tiktok_open_id': 'synthetic-account'})
        self.assertEqual(self.client.cache.meta('organizacion_migrada'), '1')
        self.assertNotIn('app_secret', self.transport.pedir.call_args.args[2].decode())


if __name__ == '__main__':
    unittest.main()
