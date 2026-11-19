"""Contrato de la lectura Marketplace Creator, sin credenciales reales ni red."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'hub'))

from creatorhub.api.rutas import DespachadorHub
from creatorhub.errores import ErrorApi
from creatorhub.interfaces import CTX_UI, Contexto
from creatorhub.tiktok.marketplace import MarketplaceCreator, RUTA, SCOPE


class MarketplaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.grant = {'user_type': 1, 'open_id': 'creador-prueba', 'epoca_credenciales': 4,
                      'granted_scopes': [SCOPE]}
        boveda = SimpleNamespace(leer=lambda: dict(self.grant))
        self.conexion = {'estado': 'conectada'}
        self.cliente = Mock()
        self.cliente.llamar.return_value = {'products': []}
        self.marketplace = MarketplaceCreator(self.cliente, boveda, lambda: self.conexion)
        self.hub = SimpleNamespace(marketplace=self.marketplace)
        self.api = DespachadorHub(self.hub)

    def buscar(self, filtros: dict[str, str], ctx: Contexto = CTX_UI, metodo: str = 'GET'):
        r = self.api.despachar(metodo, '/api/catalogo/marketplace', urlencode(filtros), {}, b'', ctx)
        return r, json.loads(r.cuerpo)

    def test_pagina_con_filtros_y_datos_del_contrato(self):
        self.cliente.llamar.return_value = {
            'products': [{'id': '1729482465811396590', 'title': ' Mini lámpara ', 'sale_region': 'MX',
                          'shop': {'name': 'Tienda prueba'},
                          'sales_price': {'currency': 'MXN', 'minimum_amount': '120.35', 'maximum_amount': '200'},
                          'commission': {'rate': 3587}, 'units_sold': 0, 'has_inventory': False,
                          'category_chains': [{'id': '456', 'local_name': 'Lámparas', 'parent_id': '123'},
                                              {'id': '123', 'local_name': 'Hogar', 'parent_id': '0'}],
                          'detail_link': 'https://shop.tiktok.com/view/product/1729482465811396590?region=MX',
                          'main_image_url': 'https://p16-test.ibyteimg.com/synthetic.jpg', 'interno': 'no proyectar'}],
            'next_page_token': 'pagina+/=', 'total_count': 421,
        }
        r, cuerpo = self.buscar({'q': 'mini lámpara', 'category_id': '123', 'min_price': '120.35',
                                 'max_price': '201', 'min_commission': '35.87', 'max_commission': '40',
                                 'sort': 'commission_rate', 'direction': 'DESC', 'limit': '8', 'cursor': 'entrada+/='})
        self.assertEqual(r.status, 200)
        self.assertEqual(dict(r.cabeceras)['Cache-Control'], 'no-store')
        args, kwargs = self.cliente.llamar.call_args
        self.assertEqual(args, ('POST', RUTA, {'page_size': '8', 'page_token': 'entrada+/=',
                                              'sort_field': 'commission_rate', 'sort_order': 'DESC'},
                                {'title_keywords': ['mini', 'lámpara'], 'category': {'id': '123'},
                                 'sales_price_range': {'amount_ge': '120.35', 'amount_lt': '201'},
                                 'commission_rate_range': {'rate_ge': 3587, 'rate_lt': 4000}}))
        self.assertEqual(kwargs['ctx'].open_id, 'creador-prueba')
        self.assertEqual(kwargs['ctx'].epoca_credenciales, 4)
        self.assertIsNone(kwargs['ctx'].sync_id)
        self.assertEqual(cuerpo, {'productos': [{'product_id': '1729482465811396590', 'titulo': 'Mini lámpara',
                                                'region': 'MX', 'tienda': 'Tienda prueba', 'moneda': 'MXN',
                                                'precio_min': '120.35', 'precio_max': '200',
                                                'comision_porcentaje': 35.87, 'unidades_vendidas': 0,
                                                'inventario': False, 'categorias': [{'id': '123', 'nombre': 'Hogar'}],
                                                'enlace': 'https://shop.tiktok.com/view/product/1729482465811396590?region=MX',
                                                'imagen_url': 'https://p16-test.ibyteimg.com/synthetic.jpg'}],
                                   'total': 421, 'cursor_siguiente': 'pagina+/='})

    def test_rangos_invalidos_no_llegan_a_tiktok(self):
        for filtros in ({'min_price': '1e2'}, {'min_price': '0'}, {'min_price': '20', 'max_price': '20'},
                        {'min_commission': '0.99'}, {'max_commission': '9.99'}, {'min_commission': '81'},
                        {'min_commission': '50', 'max_commission': '40'}, {'sort': 'other'},
                        {'direction': 'ASC'}, {'limit': '21'}, {'cursor': 'no valido'},
                        {'q': ' '.join(['x'] * 21)}, {'category_id': 'https://example.test'}, {'sign': 'inject'}):
            with self.subTest(filtros=filtros):
                r, cuerpo = self.buscar(filtros)
                self.assertEqual(r.status, 400)
                self.assertEqual(cuerpo['error']['codigo'], 'parametros_invalidos')
        self.cliente.llamar.assert_not_called()

    def test_exige_conexion_scope_y_tipo_de_cuenta(self):
        self.assertTrue(self.marketplace.disponible(self.conexion))
        self.grant['granted_scopes'] = ['creator.showcase.write']
        self.assertFalse(self.marketplace.disponible(self.conexion))
        r, cuerpo = self.buscar({})
        self.assertEqual((r.status, cuerpo['error']['codigo']), (403, 'sin_permiso_tiktok'))
        self.grant.update(granted_scopes=[SCOPE], user_type=2)
        r, cuerpo = self.buscar({})
        self.assertEqual((r.status, cuerpo['error']['codigo']), (403, 'sin_permiso_tiktok'))
        self.conexion['estado'] = 'reautorizar'
        r, cuerpo = self.buscar({})
        self.assertEqual((r.status, cuerpo['error']['codigo']), (409, 'reautorizar'))
        self.cliente.llamar.assert_not_called()

    def test_respuesta_de_otra_cuenta_se_descarta_y_denegacion_no_expone_detalle(self):
        def cambio(*_args, **_kwargs):
            self.grant.update(open_id='otra-cuenta', epoca_credenciales=5)
            return {'products': [{'id': '11'}]}

        self.cliente.llamar.side_effect = cambio
        r, cuerpo = self.buscar({'q': 'una búsqueda'})
        self.assertEqual((r.status, cuerpo['error']['codigo']), (409, 'cuenta_cambio_sin_aplicar'))
        self.cliente.llamar.side_effect = ErrorApi(105005, 'detalle de TikTok', 'omitir_paso')
        r, cuerpo = self.buscar({'q': 'una búsqueda'})
        self.assertEqual((r.status, cuerpo['error']['codigo']), (403, 'sin_permiso_tiktok'))
        self.assertNotIn('detalle de TikTok', cuerpo['error']['mensaje'])

    def test_valores_no_reportados_y_urls_fuera_de_lista_quedan_nulos(self):
        self.cliente.llamar.return_value = {'products': [{'id': '10', 'units_sold': True,
                                                             'commission': {'rate': 9000},
                                                             'main_image_url': 'https://ibyteimg.com.example.test/x',
                                                             'detail_link': 'https://shop.tiktok.com@example.test/x'},
                                                            {'id': '10'}, {'id': 11}],
                                            'next_page_token': 'misma'}
        r, cuerpo = self.buscar({'cursor': 'misma'})
        self.assertEqual(r.status, 200)
        self.assertEqual(len(cuerpo['productos']), 1)
        self.assertIsNone(cuerpo['cursor_siguiente'])
        self.assertIsNone(cuerpo['total'])
        for campo in ('enlace', 'imagen_url', 'comision_porcentaje', 'unidades_vendidas', 'moneda', 'precio_min'):
            self.assertIsNone(cuerpo['productos'][0][campo])

    def test_precio_original_si_la_promocion_no_da_importe_y_moneda_validos(self):
        original = {'currency': 'MXN', 'minimum_amount': '200.00', 'maximum_amount': '240.00'}
        promociones = ({'minimum_amount': '190.00'}, {'currency': 'MXN'},
                       {'currency': 'MXN', 'minimum_amount': 'indisponible'},
                       {'currency': 'MXN', 'maximum_amount': '195.00'})
        productos = [{'id': str(i), 'original_price': original, 'sales_price': promocion}
                     for i, promocion in enumerate(promociones, 1)]
        productos.append({'id': '5', 'sale_region': 'MX', 'original_price': {'minimum_amount': '200.00'}})
        self.cliente.llamar.return_value = {'products': productos}

        r, cuerpo = self.buscar({})

        self.assertEqual(r.status, 200)
        precios = [(p['precio_min'], p['precio_max'], p['moneda']) for p in cuerpo['productos']]
        self.assertEqual(precios, [('200.00', '240.00', 'MXN')] * 3 + [(None, '195.00', 'MXN'), (None, None, None)])

    def test_limita_la_ruta_al_hub_nube_y_no_admite_post(self):
        r, _ = self.buscar({}, ctx=Contexto(origen='lan', plataforma='android', permisos='lectura_escritura'))
        self.assertEqual(r.status, 403)
        r, _ = self.buscar({}, metodo='POST')
        self.assertEqual(r.status, 405)
        self.hub.marketplace = None
        r, _ = self.buscar({})
        self.assertEqual(r.status, 404)
        self.cliente.llamar.assert_not_called()
