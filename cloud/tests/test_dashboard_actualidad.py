"""Synthetic paid-sale summaries; bank payouts are deliberately not inferred."""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'hub'))
from creatorhub.almacen import crear_almacen
from creatorhub.analitica.actualidad import resumen_actualidad
from creatorhub.analitica.servicio import AnaliticaSqlite
from creatorhub.api.rutas import crear_despachador
from creatorhub.comun import epoch_de_fecha_local
from creatorhub.interfaces import CTX_UI


class DashboardActualidadTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.instant = [epoch_de_fecha_local('2026-11-16', hora=12)]  # Monday in Mexico City.
        self.clock = SimpleNamespace(ahora=lambda: self.instant[0], monotonico=lambda: 1000.0)
        self.store = crear_almacen(str(Path(self.folder.name) / 'synthetic.sqlite'), self.clock)
        self.analytics = AnaliticaSqlite(self.store, self.clock)

    def tearDown(self):
        self.store.cerrar()
        self.folder.cleanup()

    def order(self, oid, *, at=None, state='To-SETTLE', price=10000, commission=1000,
              quantity=1, refunded=0, returned=0, currency='MXN', sample=False, incomplete=False,
              actual=None, tax=0):
        at = self.instant[0] - 60 if at is None else at
        with self.store.escritor() as db:
            db.execute('INSERT INTO ordenes(order_id,creada_at,estado,huella,actualizado_at) VALUES(?,?,?,?,?)',
                       (oid, at, state, 'incompleta' if incomplete else 'synthetic', self.instant[0]))
            db.execute('INSERT INTO orden_lineas(order_id,linea_n,product_id,precio_centavos,moneda,cantidad,'
                       'reembolsadas,devueltas,com_estimada_centavos,com_real_centavos,isr_centavos,iva_centavos,'
                       'compartido_centavos) VALUES(?,0,?,?,?,?,?,?,?,?,?,?,?)',
                       (oid, '100', price, currency, quantity, refunded, returned, commission, actual, tax, tax, tax))
            if sample:
                db.execute('INSERT INTO muestras(application_id,product_id,main_order_id,estado_api,clase,subestado,'
                           'clase_desde_at,primera_vez_at,huella,actualizado_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
                           ('sample-' + oid, '100', oid, 'COMPLETE', 'entregada', 'video_aprobado',
                            at, at, 'synthetic', at))

    def summary(self):
        with self.store.lector() as db:
            return resumen_actualidad(db, self.instant[0])

    def test_paid_sales_are_separate_from_unpaid_and_other_states_and_samples(self):
        self.order('paid', quantity=2, refunded=1, commission=700)
        self.order('settled', state='SETTLED', price=5000, commission=300, actual=250)
        self.order('unpaid', state='AWAITING PAYMENT', price=90000, commission=9000)
        self.order('frozen', state='FROZEN', commission=600)
        self.order('refund', state='REFUNDED', commission=800)
        self.order('missing', state='NO_DEVUELTA', commission=900)
        self.order('sample', sample=True, price=70000, commission=7000)
        result = self.summary()
        self.assertEqual(result['hoy']['pedidos_validos'], 2)
        self.assertEqual(result['hoy']['pedidos_pendientes_pago'], 1)
        self.assertEqual(result['hoy']['unidades'], 2)
        self.assertEqual(result['hoy']['ventas_centavos'], 15000)
        self.assertEqual(result['hoy']['comision_estimada_centavos'], 1000)
        self.assertEqual(result['pendiente']['comision_por_liquidar_centavos'], 700)
        self.assertEqual(result['pendiente']['comision_retenida_centavos'], 600)
        self.assertEqual(result['pendiente']['comision_pedidos_sin_pagar_centavos'], 9000)

    def test_multiple_lines_of_one_order_count_one_sale_and_commission_is_not_multiplied(self):
        self.order('paid', quantity=2, commission=500)
        with self.store.escritor() as db:
            db.execute('INSERT INTO orden_lineas(order_id,linea_n,product_id,precio_centavos,moneda,cantidad,'
                       'com_estimada_centavos) VALUES(?,1,?,?,?,?,?)', ('paid', '200', 3000, 'MXN', 3, 200))
        result = self.summary()['hoy']
        self.assertEqual(result['pedidos_validos'], 1)
        self.assertEqual(result['unidades'], 5)
        self.assertEqual(result['ventas_centavos'], 29000)
        self.assertEqual(result['comision_estimada_centavos'], 700)

    def test_mexico_midnight_and_monday_start_do_not_use_utc_calendar(self):
        midnight = epoch_de_fecha_local('2026-11-16', hora=0)
        self.order('sunday', at=midnight - 1, commission=1100)
        self.order('monday', at=midnight, commission=2200)
        # This instant is Tuesday UTC but still Monday in Mexico.
        self.instant[0] = epoch_de_fecha_local('2026-11-16', hora=23)
        self.order('late-monday', at=self.instant[0] - 1, commission=3300)
        result = self.summary()
        self.assertEqual(result['hoy']['fecha'], '2026-11-16')
        self.assertEqual(result['hoy']['pedidos_validos'], 2)
        self.assertEqual(result['hoy']['comision_estimada_centavos'], 5500)
        self.assertEqual(result['semana']['desde'], '2026-11-16')
        self.assertEqual(result['semana']['hasta'], '2026-11-22')
        self.assertEqual(result['semana']['comision_generada_estimada_centavos'], 5500)

    def test_week_sales_and_today_sales_are_distinct_and_future_orders_are_excluded(self):
        self.instant[0] = epoch_de_fecha_local('2026-11-22', hora=12)
        self.order('monday', at=epoch_de_fecha_local('2026-11-16'), commission=100)
        self.order('today', commission=200)
        self.order('previous-week', at=epoch_de_fecha_local('2026-11-15'), commission=400)
        self.order('future-today', at=self.instant[0] + 1, commission=800)
        self.order('future-week', at=epoch_de_fecha_local('2026-11-23'), commission=1600)
        result = self.summary()
        self.assertEqual(result['hoy']['pedidos_validos'], 1)
        self.assertEqual(result['hoy']['comision_estimada_centavos'], 200)
        self.assertEqual(result['semana']['pedidos_validos'], 2)
        self.assertEqual(result['semana']['comision_estimada_centavos'], 300)
        self.assertEqual(result['pendiente']['comision_por_liquidar_centavos'], 700)

    def test_pending_commission_is_lifetime_backlog_and_not_next_wednesday_payout(self):
        self.order('old-pending', at=epoch_de_fecha_local('2026-01-05'), commission=12345)
        self.order('old-settled', at=epoch_de_fecha_local('2026-01-05'), state='SETTLED', actual=999999,
                   commission=80000)
        result = self.summary()
        self.assertEqual(result['hoy']['comision_estimada_centavos'], 0)
        self.assertEqual(result['semana']['comision_generada_estimada_centavos'], 0)
        self.assertEqual(result['pendiente']['comision_por_liquidar_centavos'], 12345)
        payout = result['pago_semana']
        self.assertEqual(payout['estado'], 'no_disponible')
        self.assertIsNone(payout['monto_centavos'])
        self.assertIsNone(payout['fecha_prevista'])
        self.assertEqual(payout['fecha_programada'], '2026-11-18')
        self.assertEqual(payout['dia_pago'], 3)
        self.assertEqual(payout['horario'], 'madrugada')
        self.assertEqual(payout['origen_calendario'], 'usuario')

    def test_wednesday_calendar_is_inclusive_and_handles_next_week_and_new_year(self):
        for day, expected in [('2026-11-18', '2026-11-18'), ('2026-11-19', '2026-11-25'),
                              ('2026-12-31', '2027-01-06')]:
            with self.subTest(day=day):
                self.instant[0] = epoch_de_fecha_local(day, hora=18)
                self.assertEqual(self.summary()['pago_semana']['fecha_programada'], expected)

    def test_missing_amount_and_currency_are_unknown_instead_of_zero_or_assumed_mxn(self):
        self.order('unknown', price=None, commission=None)
        result = self.summary()
        self.assertEqual(result['hoy']['pedidos_validos'], 1)
        self.assertIsNone(result['hoy']['ventas_centavos'])
        self.assertIsNone(result['hoy']['comision_estimada_centavos'])
        self.assertIsNone(result['pendiente']['comision_por_liquidar_centavos'])
        with self.store.escritor() as db:
            db.execute("UPDATE orden_lineas SET precio_centavos=1000,com_estimada_centavos=100,moneda='USD'")
        self.assertIsNone(self.summary()['hoy']['ventas_centavos'])
        self.assertIsNone(self.summary()['hoy']['comision_estimada_centavos'])

    def test_actual_zero_is_preserved_and_taxes_or_partner_share_are_not_subtracted_twice(self):
        self.order('zero', price=0, commission=0)
        self.assertEqual(self.summary()['hoy']['ventas_centavos'], 0)
        self.assertEqual(self.summary()['hoy']['comision_estimada_centavos'], 0)
        self.order('net-commission', commission=100, tax=500)
        self.assertEqual(self.summary()['hoy']['comision_estimada_centavos'], 100)
        self.assertEqual(self.summary()['pendiente']['comision_por_liquidar_centavos'], 100)

    def test_fully_returned_or_refunded_units_are_not_paid_sales(self):
        self.order('returned', quantity=2, returned=2, commission=1000)
        self.order('refunded', quantity=2, refunded=2, commission=2000)
        self.order('partial', quantity=3, returned=1, refunded=1, commission=3000)
        result = self.summary()
        self.assertEqual(result['hoy']['pedidos_validos'], 1)
        self.assertEqual(result['hoy']['unidades'], 2)  # MAX(returned,refunded), never subtract both.
        self.assertEqual(result['hoy']['ventas_centavos'], 20000)
        self.assertEqual(result['hoy']['comision_estimada_centavos'], 3000)

    def test_incomplete_order_does_not_invent_a_complete_monetary_total(self):
        self.order('incomplete', incomplete=True)
        result = self.summary()
        self.assertTrue(result['hoy']['datos_parciales'])
        self.assertIsNone(result['hoy']['ventas_centavos'])
        self.assertIsNone(result['hoy']['comision_estimada_centavos'])
        self.assertIsNone(result['pendiente']['comision_por_liquidar_centavos'])

    def test_dashboard_period_and_legacy_kpis_are_not_redefined_by_paid_today_summary(self):
        self.order('paid')
        self.order('unpaid', state='AWAITING PAYMENT')
        thirty = self.analytics.dashboard('30d')
        lifetime = self.analytics.dashboard('todo')
        self.assertEqual(thirty['kpis']['pedidos_validos'], 2)  # Preserve the existing contract.
        self.assertEqual(thirty['actualidad']['hoy']['pedidos_validos'], 1)
        self.assertEqual(thirty['actualidad'], lifetime['actualidad'])
        snapshot = self.analytics.snapshot(None, {}, {})
        self.assertEqual(snapshot['dashboard']['30d']['actualidad'], thirty['actualidad'])
        self.assertEqual(snapshot['dashboard']['todo']['actualidad'], thirty['actualidad'])

    def test_snapshot_etag_expires_at_mexico_midnight_without_data_version_change(self):
        self.order('paid')
        hub = SimpleNamespace(analitica=self.analytics, reloj=self.clock,
                              auth=SimpleNamespace(cuenta=lambda: None, conexion=lambda: {}),
                              sincronizador=SimpleNamespace(estado=lambda: {}))
        dispatcher = crear_despachador(hub)
        first = dispatcher.despachar('GET', '/api/snapshot', '', {}, b'', CTX_UI)
        self.assertEqual(first.status, 200)
        tag = dict(first.cabeceras)['ETag']
        versions = self.store.versiones()
        self.instant[0] = epoch_de_fecha_local('2026-11-17', hora=0)
        second = dispatcher.despachar('GET', '/api/snapshot', '', {'If-None-Match': tag}, b'', CTX_UI)
        self.assertEqual(second.status, 200)
        self.assertNotEqual(dict(second.cabeceras)['ETag'], tag)
        self.assertEqual(self.store.versiones(), versions)
        body = json.loads(second.cuerpo)
        self.assertEqual(body['dashboard']['30d']['actualidad']['hoy']['fecha'], '2026-11-17')
        self.assertEqual(body['dashboard']['30d']['actualidad']['hoy']['pedidos_validos'], 0)
        matching = dispatcher.despachar('GET', '/api/snapshot', '',
                                        {'If-None-Match': dict(second.cabeceras)['ETag']}, b'', CTX_UI)
        self.assertEqual(matching.status, 304)

    def test_dashboard_read_crossing_mexico_midnight_cannot_validate_yesterdays_body(self):
        midnight = epoch_de_fecha_local('2026-11-18', hora=0)
        self.instant[0] = midnight - 1
        self.order('paid')
        dashboard = self.analytics.dashboard

        def dashboard_crossing_midnight(periodo):
            result = dashboard(periodo)
            self.instant[0] = midnight
            return result

        self.analytics.dashboard = dashboard_crossing_midnight
        dispatcher = crear_despachador(SimpleNamespace(analitica=self.analytics, reloj=self.clock))
        first = dispatcher.despachar('GET', '/api/dashboard', '', {}, b'', CTX_UI)
        self.assertEqual(first.status, 200)
        self.assertEqual(json.loads(first.cuerpo)['actualidad']['hoy']['fecha'], '2026-11-17')
        first_tag = dict(first.cabeceras).get('ETag')

        self.analytics.dashboard = dashboard
        headers = {'If-None-Match': first_tag} if first_tag else {}
        second = dispatcher.despachar('GET', '/api/dashboard', '', headers, b'', CTX_UI)
        self.assertEqual(second.status, 200)
        self.assertEqual(json.loads(second.cuerpo)['actualidad']['hoy']['fecha'], '2026-11-18')
        self.assertIsNotNone(dict(second.cabeceras).get('ETag'))


if __name__ == '__main__':
    unittest.main()
