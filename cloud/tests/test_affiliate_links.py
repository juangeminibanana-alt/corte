"""Contratos de enlaces de afiliado con respuestas simuladas de TikTok Shop."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'hub'))

from creatorhub.errores import ErrorApi, ErrorDominio
from creatorhub.tiktok.affiliate_links import AffiliateLinksCreator, RUTA_GENERAL, RUTA_PUBLISHER, SCOPE


PRODUCTO = '7362840009596339971'
OTRO_PRODUCTO = '7362840009596339972'
ENLACE = f'https://www.tiktok.com/view/product/{PRODUCTO}?chain_key=%7B%22t%22%3A1%7D&scene=pdp'


class AffiliateLinksTests(unittest.TestCase):
    def setUp(self) -> None:
        self.grant = {'user_type': 1, 'open_id': 'creador-prueba', 'epoca_credenciales': 4,
                      'granted_scopes': [SCOPE]}
        self.conexion = {'estado': 'conectada'}
        self.cliente = Mock()
        self.cliente.llamar.return_value = {}
        boveda = SimpleNamespace(leer=lambda: dict(self.grant))
        self.servicio = AffiliateLinksCreator(self.cliente, boveda, lambda: self.conexion)

    def test_general_proyecta_un_resultado_por_producto_y_respeta_atribucion(self):
        self.cliente.llamar.return_value = {
            'sharing_links': [{'material_id': PRODUCTO, 'sharing_link': ENLACE, 'deep_link': 'snssdk1180://ec/pdp'},
                              {'material_id': '999', 'sharing_link': 'https://www.tiktok.com/t/NO_SOLICITADO'}],
            'failed_materials': [{'material_id': OTRO_PRODUCTO, 'fail_reason': 'Product was sold out'}],
        }
        resultados = self.servicio.generar({'product_ids': [OTRO_PRODUCTO, PRODUCTO, PRODUCTO]})['resultados']

        self.assertEqual(resultados, [
            {'product_id': OTRO_PRODUCTO, 'enlace': None, 'codigo': 'producto_agotado',
             'mensaje': 'TikTok Shop informó que este producto está agotado.'},
            {'product_id': PRODUCTO, 'enlace': ENLACE, 'codigo': None, 'mensaje': None},
        ])
        args, kwargs = self.cliente.llamar.call_args
        self.assertEqual(args, ('POST', RUTA_GENERAL, None, {'material': {'ids': [OTRO_PRODUCTO, PRODUCTO],
                                                                          'type': 'PRODUCT'}}))
        self.assertEqual(kwargs['ctx'].open_id, 'creador-prueba')
        self.assertEqual(kwargs['ctx'].epoca_credenciales, 4)
        self.assertIsNone(kwargs['ctx'].sync_id)
        self.assertFalse(kwargs['reintentar'])

    def test_publisher_envia_id_externo_y_campana_y_acepta_material_entero(self):
        campana = '7432840009596339923'
        enlace_corto = 'https://www.tiktok.com/t/AbCdEF123'
        self.cliente.llamar.return_value = {
            'sharing_links': [{'material_id': int(PRODUCTO), 'sharing_link': enlace_corto}],
        }
        respuesta = self.servicio.generar({'product_ids': [PRODUCTO], 'publisher_id': 'publisher_5-a',
                                           'campaign_id': campana})
        self.assertEqual(respuesta['resultados'][0]['enlace'], enlace_corto)
        self.assertEqual(self.cliente.llamar.call_args.args, (
            'POST', RUTA_PUBLISHER.format(publisher_id='publisher_5-a'), None,
            {'material': {'ids': [PRODUCTO], 'type': 'PRODUCT'}, 'campaign_id': campana},
        ))

    def test_valida_parametros_antes_de_enviar(self):
        for cambios in ({'product_ids': []}, {'product_ids': [4]}, {'product_ids': ['0']},
                        {'product_ids': [PRODUCTO] * 21}, {'publisher_id': 'a/../b'},
                        {'publisher_id': 'a%2fb'}, {'publisher_id': 'a?x'}, {'publisher_id': None},
                        {'campaign_id': int(PRODUCTO)}, {'link_type': 'TOKO'}):
            with self.subTest(cambios=cambios), self.assertRaises(ErrorDominio) as error:
                self.servicio.generar({'product_ids': [PRODUCTO], **cambios})
            self.assertEqual(error.exception.http, 400)
        self.cliente.llamar.assert_not_called()

    def test_no_expone_destinos_inseguros_o_credenciales_y_reporta_omisiones(self):
        for enlace in ('snssdk1180://ec/pdp', 'https://www.tiktok.com@example.test/t/Abc',
                       'https://www.tiktok.com.example.test/t/Abc', 'https://www.tiktok.com/link/v2?to=other',
                       'https://vt.tiktok.com/CD12/?refresh_token=secreto_prueba',
                       'http://shop.tiktok.com/view/product/123', 'https://www.tiktok.com:400/t/Abc'):
            with self.subTest(enlace=enlace):
                self.cliente.llamar.return_value = {
                    'sharing_links': [{'material_id': PRODUCTO, 'sharing_link': enlace,
                                       'one_link': 'https://snssdk1180.onelink.me/BAuo'}],
                }
                respuesta = self.servicio.generar({'product_ids': [PRODUCTO, OTRO_PRODUCTO]})['resultados']
                self.assertEqual((respuesta[0]['enlace'], respuesta[0]['codigo']), (None, 'enlace_no_valido'))
                self.assertEqual(respuesta[1]['codigo'], 'producto_sin_respuesta')

        self.cliente.llamar.return_value = {
            'sharing_links': [{'material_id': PRODUCTO, 'sharing_link': 'https://vm.tiktok.com/CD12/'}],
            'failed_materials': [{'material_id': OTRO_PRODUCTO, 'fail_reason': 'detalle interno de prueba'}],
        }
        resultados = self.servicio.generar({'product_ids': [PRODUCTO, OTRO_PRODUCTO]})['resultados']
        self.assertEqual(resultados[0]['enlace'], 'https://vm.tiktok.com/CD12/')
        self.assertEqual(resultados[1]['codigo'], 'enlace_rechazado')
        self.assertNotIn('detalle interno de prueba', resultados[1]['mensaje'])

    def test_exige_el_scope_documentado_y_cuenta_creator_conectada(self):
        self.assertTrue(self.servicio.disponible(self.conexion))
        for cambios in ({'granted_scopes': ['creator.affiliate.link.write']}, {'user_type': 0}, {'open_id': ''}):
            with self.subTest(cambios=cambios):
                grant = self.grant.copy()
                self.grant.update(cambios)
                self.assertFalse(self.servicio.disponible(self.conexion))
                with self.assertRaises(ErrorDominio):
                    self.servicio.generar({'product_ids': [PRODUCTO]})
                self.grant.update(grant)
        self.conexion['estado'] = 'reautorizar'
        with self.assertRaises(ErrorDominio) as error:
            self.servicio.generar({'product_ids': [PRODUCTO]})
        self.assertEqual(error.exception.codigo, 'reautorizar')
        self.cliente.llamar.assert_not_called()

    def test_no_retorna_enlaces_tras_cambio_de_credenciales(self):
        def cambio(*args, **kwargs):
            self.grant['epoca_credenciales'] += 1
            return {'sharing_links': [{'material_id': PRODUCTO, 'sharing_link': ENLACE}]}

        self.cliente.llamar.side_effect = cambio
        with self.assertRaises(ErrorDominio) as error:
            self.servicio.generar({'product_ids': [PRODUCTO]})
        self.assertEqual(error.exception.codigo, 'cuenta_cambio_sin_aplicar')

    def test_no_expone_el_error_de_permiso_del_proveedor(self):
        self.cliente.llamar.side_effect = ErrorApi(105005, 'mensaje interno de prueba', 'omitir_paso')
        with self.assertRaises(ErrorDominio) as error:
            self.servicio.generar({'product_ids': [PRODUCTO]})
        self.assertEqual((error.exception.codigo, error.exception.http), ('sin_permiso_tiktok', 403))
        self.assertNotIn('mensaje interno de prueba', error.exception.mensaje)

    def test_error_transversal_no_confirma_el_lote_y_conserva_fallos_con_id(self):
        self.cliente.llamar.return_value = {
            'sharing_links': [{'material_id': PRODUCTO, 'sharing_link': ENLACE}],
            'failed_materials': [{'material_id': OTRO_PRODUCTO, 'fail_reason': 'Product was sold out'}],
            'errors': [{'message': 'mensaje interno de prueba'}],
        }
        resultados = self.servicio.generar({'product_ids': [PRODUCTO, OTRO_PRODUCTO]})['resultados']
        self.assertEqual([(x['enlace'], x['codigo']) for x in resultados],
                         [(None, 'producto_sin_respuesta'), (None, 'producto_agotado')])


class AffiliateLinksScopeTests(unittest.TestCase):
    def setUp(self) -> None:
        from cloud.tests import test_native_auth as native_tests
        from creatorhub.api.rutas import DespachadorHub

        self.fixture = native_tests.NativeWebTests
        self.fixture.setUp(self)
        self.hub.boveda.leer.return_value = {'user_type': 1, 'open_id': 'synthetic-creator-current',
                                            'epoca_credenciales': 4, 'granted_scopes': [SCOPE]}
        self.hub.despachador = DespachadorHub(self.hub)
        self.cliente_shop = Mock()
        self.cliente_shop.llamar.return_value = {'sharing_links': [{'material_id': PRODUCTO, 'sharing_link': ENLACE}]}
        self.hub.affiliate_links = AffiliateLinksCreator(self.cliente_shop, self.hub.boveda,
                                                         lambda: {'estado': 'conectada'})
        self.cache_scope = self.owner.get('/api/cloud/session', base_url=self.base).json['cache_scope']

    def tearDown(self) -> None:
        self.fixture.tearDown(self)

    def start(self):
        return self.fixture.start(self)

    def enviar(self, cliente, headers):
        return cliente.post('/api/catalogo/enlaces-afiliado', base_url=self.base, headers=headers,
                            json={'product_ids': [PRODUCTO]})

    def test_requiere_sesion_y_alcance_actual_del_creador(self):
        headers = {**self.headers, 'X-Corte-Cache-Scope': self.cache_scope}
        self.assertEqual(self.enviar(self.client, headers).status_code, 401)
        self.assertEqual(self.enviar(self.owner, self.headers).status_code, 409)
        self.hub.boveda.leer.return_value['open_id'] = 'synthetic-creator-new'
        respuesta = self.enviar(self.owner, headers)
        self.assertEqual(respuesta.status_code, 409)
        self.assertEqual(respuesta.json['error']['codigo'], 'cuenta_cambio_sin_aplicar')
        self.cliente_shop.llamar.assert_not_called()

    def test_acepta_sesion_web_o_nativa_con_alcance_vigente(self):
        headers = {**self.headers, 'X-Corte-Cache-Scope': self.cache_scope}
        token = self.fixture.grant(self)['token']
        casos = ((self.owner, headers), (self.client, {**headers, 'Authorization': 'Bearer ' + token}))
        for cliente, cabeceras in casos:
            resultado = self.enviar(cliente, cabeceras)
            self.assertEqual(resultado.status_code, 200)
            self.assertIn('no-store', resultado.headers['Cache-Control'])
            self.assertEqual(resultado.json['resultados'][0]['enlace'], ENLACE)
        self.assertEqual(self.cliente_shop.llamar.call_count, 2)


if __name__ == '__main__':
    unittest.main()
