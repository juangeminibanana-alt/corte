"""El proveedor puede revocar un token cuya fecha todavía es futura.

Estas regresiones usan el cliente y la bóveda reales con transporte sintético;
nunca leen una conexión del operador ni llaman a TikTok.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'hub'))

from creatorhub.errores import ErrorApi
from creatorhub.hub import iniciar_hub
from creatorhub.interfaces import OpcionesHub
from creatorhub.nube import BovedaNube
from creatorhub.tiktok.cliente import P_PERFIL, P_REFRESH
from creatorhub.tiktok.politica import Politica


class RevokedTikTokTokenTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'CORTE_PUBLIC_URL': 'https://corte.example',
                                          'CORTE_ENCRYPTION_KEY': 'synthetic-master-' * 4})
        self.env.start()
        self.hub = iniciar_hub(OpcionesHub(modo='real', nube=True, sin_lan=True,
                                          raiz_datos=self.folder.name, sync_al_iniciar=False))
        self.future = int(time.time()) + 86400
        self.credentials = {'app_key': 'synthetic-app-key', 'app_secret': 'SyntheticSecretForTests123456',
                            'access_token': 'synthetic-old-access-token',
                            'refresh_token': 'synthetic-old-refresh-token', 'open_id': 'synthetic-open-id',
                            'access_expira_at': self.future, 'refresh_expira_at': self.future + 86400 * 30,
                            'user_type': 1, 'granted_scopes': ['creator.affiliate.info'], 'origen': 'importado'}
        self.hub.boveda.mutar(lambda d: d.update(self.credentials), cambia_credenciales=True)
        self.hub.auth._espejar()
        with self.hub.almacen.escritor() as conn:
            conn.execute("INSERT INTO preferencias(clave,valor_json,actualizado_at) VALUES ('keep-data','true',1)")
        self.client = self.hub.cliente
        self.client._esperar = Mock()  # Avoid backoff waits on synthetic upstream failures.
        self.transport = Mock()
        self.transport.manejar.side_effect = AssertionError('Unexpected request in synthetic refresh test')
        self.client.transporte = self.transport

    def tearDown(self):
        self.hub.detener(10)
        self.env.stop()
        self.folder.cleanup()

    def rejected(self):
        return (200, {'code': 36009005, 'message': 'Invalid credentials. Your token has been deauthorized.'})

    def rotated(self):
        data = {'access_token': 'synthetic-new-access-token', 'refresh_token': 'synthetic-new-refresh-token',
                'access_token_expire_in': self.future + 3600,
                'refresh_token_expire_in': self.future + 86400 * 30,
                'user_type': 1, 'open_id': 'synthetic-open-id', 'granted_scopes': ['creator.affiliate.info']}
        return (200, {'code': 0, 'data': data})

    def assert_preserved(self):
        saved = self.hub.boveda.leer()
        for field in ('app_key', 'app_secret', 'open_id'):
            self.assertEqual(saved[field], self.credentials[field])
        with self.hub.almacen.lector() as conn:
            self.assertEqual(conn.execute("SELECT valor_json FROM preferencias WHERE clave='keep-data'").fetchone()[0],
                             'true')

    def test_policy_routes_revoked_token_through_one_refresh(self):
        rule = Politica().decidir(200, 36009005)
        self.assertEqual(rule.decision, 'refrescar_token')
        self.assertEqual(rule.reintentos, 1)

    def test_future_expiration_does_not_prevent_refresh_and_one_successful_retry(self):
        self.transport.manejar.side_effect = [self.rejected(), self.rotated(),
                                            (200, {'code': 0, 'data': {'username': 'synthetic_creator'}})]
        profile = self.client.llamar('GET', P_PERFIL)
        self.assertEqual(profile['username'], 'synthetic_creator')
        calls = self.transport.manejar.call_args_list
        self.assertEqual([urlsplit(c.args[1]).path for c in calls], [P_PERFIL, P_REFRESH, P_PERFIL])
        self.assertEqual(calls[0].args[2]['x-tts-access-token'], 'synthetic-old-access-token')
        self.assertEqual(calls[2].args[2]['x-tts-access-token'], 'synthetic-new-access-token')
        refresh = parse_qs(urlsplit(calls[1].args[1]).query)
        self.assertEqual(refresh['grant_type'], ['refresh_token'])
        self.assertEqual(refresh['refresh_token'], ['synthetic-old-refresh-token'])
        reopened = BovedaNube(self.hub.boveda.ruta, 'synthetic-master-' * 4, 'shop')
        self.assertEqual(reopened.leer()['refresh_token'], 'synthetic-new-refresh-token')
        self.assertEqual(self.hub.auth.conexion()['estado'], 'conectada')
        self.assert_preserved()

    def test_second_rejection_after_refresh_marks_reauthorization_without_erasing_data(self):
        self.transport.manejar.side_effect = [self.rejected(), self.rotated(), self.rejected()]
        with self.assertRaises(ErrorApi) as context:
            self.client.llamar('GET', P_PERFIL)
        self.assertEqual((context.exception.codigo, context.exception.decision), (36009005, 'reautorizar'))
        self.assertEqual(self.transport.manejar.call_count, 3)
        self.assertEqual(self.hub.auth.conexion()['estado'], 'reautorizar')
        self.assertEqual(self.hub.boveda.leer()['access_token'], 'synthetic-new-access-token')
        self.assert_preserved()

    def test_recent_manual_refresh_uses_breaker_and_marks_reauthorization(self):
        self.client.ultimo_refresh_ok_at = self.client.ahora()
        self.client.token_de_mi_refresh = self.credentials['access_token']
        self.transport.manejar.side_effect = [self.rejected()]
        with self.assertRaises(ErrorApi) as context:
            self.client.llamar('GET', P_PERFIL)
        self.assertEqual((context.exception.codigo, context.exception.decision), (36009005, 'reautorizar'))
        self.assertEqual(self.transport.manejar.call_count, 1)
        self.assertEqual(self.hub.auth.conexion()['estado'], 'reautorizar')
        self.assert_preserved()

    def test_refresh_rejected_keeps_original_material_and_requires_authorization(self):
        rejection = (200, {'code': 105001, 'message': 'Synthetic expired authorization'})
        self.transport.manejar.side_effect = [self.rejected(), rejection, rejection]
        original = self.hub.boveda.leer()
        with self.assertRaises(ErrorApi) as context:
            self.client.llamar('GET', P_PERFIL)
        self.assertEqual(context.exception.decision, 'reautorizar')
        self.assertEqual(self.transport.manejar.call_count, 3)
        self.assertEqual(self.hub.boveda.leer(), original)
        self.assertEqual(self.hub.auth.conexion()['estado'], 'reautorizar')
        self.assert_preserved()

    def test_transient_refresh_failure_does_not_claim_revocation(self):
        failure = (503, {'code': -1, 'message': 'Synthetic upstream unavailable'})
        self.transport.manejar.side_effect = [self.rejected(), failure, failure, failure, failure]
        original = self.hub.boveda.leer()
        with self.assertRaises(ErrorApi) as context:
            self.client.llamar('GET', P_PERFIL)
        self.assertEqual(context.exception.codigo, 'renovacion_pendiente')
        self.assertTrue(context.exception.transitorio)
        self.assertEqual(self.hub.boveda.leer(), original)
        self.assertEqual(self.hub.auth.conexion()['estado'], 'conectada')
        self.assert_preserved()

    def test_existing_expired_token_breaker_keeps_its_non_revocation_semantics(self):
        expired = (200, {'code': 105002, 'message': 'Synthetic token expired'})
        self.transport.manejar.side_effect = [expired, self.rotated(), expired]
        with self.assertRaises(ErrorApi) as context:
            self.client.llamar('GET', P_PERFIL)
        self.assertEqual(context.exception.codigo, 'token_rechazado')
        self.assertEqual(context.exception.decision, 'abortar')
        self.assertEqual(self.transport.manejar.call_count, 3)
        self.assertEqual(self.hub.auth.conexion()['estado'], 'conectada')
        self.assert_preserved()


if __name__ == '__main__':
    unittest.main()
