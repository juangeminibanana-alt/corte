"""Synthetic sale notifications only: no live FCM sends or device registrations."""
import copy
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'hub'))
from creatorhub.almacen import crear_almacen
from creatorhub.errores import ErrorDominio
from cloud.push_service import PushService, firebase_sender, paid_snapshot

UID, SCOPE, DEVICE = 'synthetic-owner', 'a' * 64, 'd' * 24
TOKEN = 'synthetic-fcm-token-must-never-be-returned'


def sale(oid='101', pid='200', at=1_800_000_001, qty=1):
    return {'order_id': oid, 'product_id': pid, 'nombre': 'Producto sintético', 'creada_at': at,
            'cantidad': qty, 'venta_centavos': 12345 * qty, 'comision_estimada_centavos': 1234 * qty, 'moneda': 'MXN'}


class PushServiceTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = str(Path(self.folder.name) / 'push.sqlite')
        self.now = 1_800_000_000
        self.snapshot = {'scope': SCOPE, 'sales': [], 'awaiting': []}
        self.active = True
        self.sender = Mock()
        self.service = self.create()

    def create(self):
        return PushService(self.path, 'synthetic-encryption-secret' * 3,
            lambda uid: copy.deepcopy(self.snapshot), lambda uid, device: self.active,
            self.sender, lambda: self.now)

    def tearDown(self):
        self.service.close()
        self.folder.cleanup()

    def register(self, platform='windows', token=None):
        body = {'platform': platform, 'permission': 'concedido'}
        if token is not None:
            body['token'] = token
        return self.service.register(UID, SCOPE, DEVICE, body)

    def events(self):
        return self.service.events(UID, SCOPE, DEVICE, '0')['items']

    def test_baseline_history_new_payment_transition_and_unknown_history(self):
        self.snapshot.update(sales=[sale('1', at=self.now - 1000)], awaiting=['2'])
        initial = self.register()
        self.assertTrue(initial['enabled'])
        self.service.tick()
        self.assertEqual(self.events(), [])
        self.now += 2
        self.snapshot['sales'] += [sale('2', at=self.now - 500), sale('3', at=self.now - 900), sale('4', at=self.now)]
        self.snapshot['awaiting'] = []
        self.service.tick()
        self.assertEqual({e['order_id'] for e in self.events()}, {'2', '4'})
        self.sender.assert_not_called()  # Windows reads the Google feed, no FCM token.

    def test_paid_product_is_once_even_after_updates_restart_or_repeated_ticks(self):
        self.register()
        self.now += 2
        self.snapshot['sales'] = [sale(at=self.now, qty=3), sale('101', '201', self.now)]
        self.service.tick()
        one = self.events()
        self.assertEqual(len(one), 2)
        self.assertEqual(one[0]['cantidad'], 3)
        self.assertIn('Comisión estimada', one[0]['texto'])
        self.snapshot['sales'][0]['cantidad'] = 4
        self.service.tick()
        self.service = self.create()
        self.service.tick()
        self.assertEqual(self.events(), one)

    def test_opt_out_survives_ticks_and_resume_has_new_baseline(self):
        self.register('android', TOKEN)
        self.service.disable(UID, DEVICE, SCOPE)
        self.now += 10
        self.snapshot['sales'] = [sale(at=self.now)]
        self.service.tick()
        self.assertFalse(self.service.status(UID, SCOPE, DEVICE)['enabled'])
        self.assertEqual(self.events(), [])
        self.sender.assert_not_called()
        self.now += 10
        self.register('android', TOKEN)
        self.service.tick()
        self.assertEqual(self.events(), [])
        self.assertFalse(self.sender.called)

    def test_token_is_encrypted_and_never_echoed_in_status_feed(self):
        result = self.register('android', TOKEN)
        self.assertNotIn(TOKEN, str(result))
        self.assertNotIn(TOKEN.encode(), Path(self.path).read_bytes())
        self.now += 1
        self.snapshot['sales'] = [sale(at=self.now)]
        self.service.tick()
        self.assertEqual(self.sender.call_count, 1)
        token, data = self.sender.call_args.args
        self.assertEqual(token, TOKEN)
        self.assertEqual(data['type'], 'sale')
        self.assertEqual(data['cache_scope'], SCOPE)
        self.assertEqual(data['ruta'], '#/ventas')
        self.assertTrue(all(isinstance(v, str) for v in data.values()))
        self.assertNotIn(TOKEN, str(self.events()))
        self.service.tick()
        self.assertEqual(self.sender.call_count, 1)

    def test_transient_provider_failure_retries_stable_event_without_logging_token(self):
        self.register('android', TOKEN)
        self.sender.side_effect = RuntimeError(TOKEN)
        self.now += 1
        self.snapshot['sales'] = [sale(at=self.now)]
        with self.assertLogs('corte.push', level='WARNING') as logs:
            self.service.tick()
        self.assertNotIn(TOKEN, str(logs.output))
        first = self.sender.call_args.args[1]
        self.sender.side_effect = None
        self.now += 29
        self.service.tick()
        self.assertEqual(self.sender.call_count, 1)
        self.now += 1
        self.service.tick()
        self.assertEqual(self.sender.call_count, 2)
        self.assertEqual(self.sender.call_args.args[1], first)

    def test_revoked_device_or_creator_change_clears_token_before_delivery(self):
        for changed in ('device', 'creator'):
            with self.subTest(changed=changed):
                self.active = True
                self.snapshot['scope'] = SCOPE
                self.register('android', TOKEN)
                if changed == 'device':
                    self.active = False
                else:
                    self.snapshot['scope'] = 'b' * 64
                self.now += 1
                self.snapshot['sales'] = [sale(at=self.now)]
                self.service.tick()
                self.assertFalse(self.service.status(UID, SCOPE, DEVICE)['enabled'])
                with closing(sqlite3.connect(self.path)) as db:
                    self.assertIsNone(db.execute('SELECT token FROM subscriptions').fetchone()[0])
        self.sender.assert_not_called()

    def test_ack_is_scoped_to_owner_creator_device_and_contiguous_cursor(self):
        self.register()
        self.now += 2
        self.snapshot['sales'] = [sale(str(i), at=self.now) for i in range(1, 4)]
        self.service.tick()
        rows = self.events()
        self.service.ack('other-owner', SCOPE, DEVICE, {'ids': [rows[0]['id']]})
        self.service.ack(UID, 'b' * 64, DEVICE, {'ids': [rows[0]['id']]})
        self.service.ack(UID, SCOPE, 'x' * 24, {'ids': [rows[0]['id']]})
        self.assertEqual(len(self.events()), 3)
        self.service.ack(UID, SCOPE, DEVICE, {'ids': [rows[2]['id']]})
        self.assertEqual(self.service.status(UID, SCOPE, DEVICE)['cursor'], '0')
        self.service.ack(UID, SCOPE, DEVICE, {'ids': [rows[0]['id'], rows[1]['id']]})
        self.assertEqual(self.events(), [])
        self.assertEqual(self.service.status(UID, SCOPE, DEVICE)['cursor'], rows[2]['id'])

    def test_feed_pages_and_other_devices_have_independent_delivery_ids(self):
        self.register()
        self.service.register(UID, SCOPE, 'e' * 24, {'platform': 'windows', 'permission': 'concedido'})
        self.now += 2
        self.snapshot['sales'] = [sale(str(i), at=self.now) for i in range(1, 61)]
        self.service.tick()
        first = self.service.events(UID, SCOPE, DEVICE, '0')
        self.assertEqual(len(first['items']), 50)
        self.assertTrue(first['has_more'])
        second = self.service.events(UID, SCOPE, DEVICE, first['cursor'])
        self.assertEqual(len(second['items']), 10)
        self.assertFalse(second['has_more'])
        other = self.service.events(UID, SCOPE, 'e' * 24, '0')
        self.assertNotEqual(other['items'][0]['id'], first['items'][0]['id'])

    def test_permission_token_payload_and_scope_validation(self):
        invalid = [{}, {'platform': 'android', 'permission': 'denegado', 'token': TOKEN},
                   {'platform': 'android', 'permission': 'concedido'},
                   {'platform': 'android', 'permission': 'concedido', 'token': 'bad\ntoken'},
                   {'platform': 'windows', 'permission': 'concedido', 'token': TOKEN},
                   {'platform': 'windows', 'permission': 'concedido', 'uid': 'other'}]
        for body in invalid:
            with self.subTest(body=body), self.assertRaises(ErrorDominio):
                self.service.register(UID, SCOPE, DEVICE, body)
        for after in ('-1', 'x', '1.5', '9007199254740992'):
            with self.assertRaises(ErrorDominio):
                self.service.events(UID, SCOPE, DEVICE, after)
        self.snapshot['scope'] = 'b' * 64
        with self.assertRaises(ErrorDominio) as error:
            self.register()
        self.assertEqual(error.exception.http, 409)

    def test_future_clock_error_is_not_marked_seen_before_it_becomes_current(self):
        self.register()
        self.snapshot['sales'] = [sale(at=self.now + 600)]
        self.service.tick()
        self.assertEqual(self.events(), [])
        self.now += 600
        self.service.tick()
        self.assertEqual(len(self.events()), 1)

    def test_delivery_guard_rechecks_creator_between_each_provider_send(self):
        self.register('android', TOKEN)
        @contextmanager
        def guard(uid, scope, device):
            yield self.snapshot['scope'] == scope
        self.service.delivery_guard = guard
        self.now += 1
        self.snapshot['sales'] = [sale('101', at=self.now), sale('102', at=self.now)]
        self.sender.side_effect = lambda *args: self.snapshot.update(scope='b' * 64)
        self.service.tick()
        self.assertEqual(self.sender.call_count, 1)
        self.assertFalse(self.service.status(UID, SCOPE, DEVICE)['enabled'])

    def test_permanent_failure_for_rotated_token_does_not_disable_new_registration(self):
        self.register('android', TOKEN)
        new_token = 'synthetic-new-fcm-token-safe-rotation'
        class UnregisteredError(Exception):
            pass
        def rotate_then_fail(*args):
            self.register('android', new_token)
            raise UnregisteredError()
        self.sender.side_effect = rotate_then_fail
        self.now += 1
        self.snapshot['sales'] = [sale(at=self.now)]
        with self.assertLogs('corte.push', level='WARNING'):
            self.service.tick()
        self.assertTrue(self.service.status(UID, SCOPE, DEVICE)['enabled'])
        self.sender.side_effect = None
        self.service.tick()
        self.assertEqual(self.sender.call_args.args[0], new_token)

    def test_provider_identity_outage_leaves_registration_and_pending_event_intact(self):
        self.register('android', TOKEN)
        @contextmanager
        def unavailable(*identity):
            raise ErrorDominio('identidad_no_disponible', 'Proveedor temporalmente no disponible.', http=503)
            yield False
        self.service.delivery_guard = unavailable
        self.now += 1
        self.snapshot['sales'] = [sale(at=self.now)]
        with self.assertRaises(ErrorDominio):
            self.service.tick()
        self.assertTrue(self.service.status(UID, SCOPE, DEVICE)['enabled'])
        self.assertEqual(len(self.events()), 1)
        self.sender.assert_not_called()

    def test_fcm_http_message_is_data_only_high_priority_with_bounded_no_retry_transport(self):
        data = {'type': 'sale', 'event_id': '1', 'cache_scope': SCOPE, 'titulo': 'Venta', 'texto': 'Prueba', 'ruta': '#/ventas'}
        app = SimpleNamespace(project_id='corte-test', credential=Mock())
        with patch('google.auth.transport.requests.AuthorizedSession') as session_class:
            client = session_class.return_value.__enter__.return_value
            client.post.return_value.status_code = 200
            firebase_sender(SimpleNamespace(app=app))(TOKEN, data)
        self.assertEqual(session_class.call_args.kwargs['max_refresh_attempts'], 0)
        self.assertEqual(session_class.call_args.kwargs['refresh_timeout'], 3)
        request = client.post.call_args
        self.assertEqual(request.args[0], 'https://fcm.googleapis.com/v1/projects/corte-test/messages:send')
        self.assertEqual(request.kwargs['json'], {'message': {'token': TOKEN, 'data': data,
                              'android': {'priority': 'HIGH', 'ttl': '86400s'}}})
        self.assertFalse(request.kwargs['allow_redirects'])
        self.assertLessEqual(request.kwargs['max_allowed_time'], 10)
        self.assertEqual(request.kwargs['timeout'], (2, 5))
        self.assertEqual(client.mount.call_args.args[1].max_retries.total, 0)
        client.post.return_value.close.assert_called_once()

    def test_fcm_invalid_registration_is_classified_without_retry_or_raw_details(self):
        from cloud.push_service import UnregisteredError
        app = SimpleNamespace(project_id='corte-test', credential=Mock())
        with patch('google.auth.transport.requests.AuthorizedSession') as session_class:
            client = session_class.return_value.__enter__.return_value
            client.post.return_value.status_code = 404
            client.post.return_value.json.return_value = {'error': {'details': [{
                '@type': 'type.googleapis.com/google.firebase.fcm.v1.FcmError', 'errorCode': 'UNREGISTERED'}]}}
            with self.assertRaises(UnregisteredError):
                firebase_sender(SimpleNamespace(app=app))(TOKEN, {})
        client.post.assert_called_once()
        client.post.return_value.close.assert_called_once()

    def test_48_hour_old_fcm_delivery_is_not_replayed_by_feed_or_counted_unread(self):
        self.register('android', TOKEN)
        self.now += 1
        self.snapshot['sales'] = [sale(at=self.now)]
        self.service.tick()
        self.assertEqual(self.sender.call_count, 1)
        self.assertEqual(len(self.events()), 1)
        self.now += 48 * 3600
        # Reads are safe even before the resident worker gets its next turn.
        self.assertEqual(self.events(), [])
        self.assertEqual(self.service.status(UID, SCOPE, DEVICE)['unread'], 0)
        self.service.tick()
        self.assertEqual(self.sender.call_count, 1)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT state,acked FROM events').fetchone(), ('expired', 1))
        self.assertEqual(len(self.snapshot['sales']), 1)  # notification expiry does not delete sales

    def test_expired_failed_outbox_is_not_sent_and_future_sales_still_work(self):
        self.register('android', TOKEN)
        self.sender.side_effect = RuntimeError('Synthetic provider unavailable')
        self.now += 1
        self.snapshot['sales'] = [sale(at=self.now)]
        with self.assertLogs('corte.push', level='WARNING'):
            self.service.tick()
        self.assertEqual(self.sender.call_count, 1)
        self.now += 48 * 3600
        self.sender.side_effect = None
        self.service.tick()
        self.assertEqual(self.sender.call_count, 1)
        self.assertEqual(self.events(), [])
        self.assertTrue(self.service.status(UID, SCOPE, DEVICE)['enabled'])
        self.snapshot['sales'].append(sale('102', at=self.now))
        self.service.tick()
        self.assertEqual(self.sender.call_count, 2)
        self.assertEqual([e['order_id'] for e in self.events()], ['102'])

    def test_fcm_retry_ttl_is_remaining_lifetime_and_expired_event_never_calls_provider(self):
        from cloud.push_service import ExpiredNotification
        app = SimpleNamespace(project_id='corte-test', credential=Mock())
        data = {'type': 'sale', 'expires_at': str(self.now + 60)}
        with patch('google.auth.transport.requests.AuthorizedSession') as session_class, \
                patch('cloud.push_service.time.time', return_value=self.now):
            client = session_class.return_value.__enter__.return_value
            client.post.return_value.status_code = 200
            firebase_sender(SimpleNamespace(app=app))(TOKEN, data)
            self.assertEqual(client.post.call_args.kwargs['json']['message']['android']['ttl'], '60s')
            client.post.reset_mock()
            with patch('cloud.push_service.time.time', return_value=self.now + 60), self.assertRaises(ExpiredNotification):
                firebase_sender(SimpleNamespace(app=app))(TOKEN, data)
            client.post.assert_not_called()

    def test_explicit_test_targets_only_own_active_scope_and_never_creates_observed_sales(self):
        self.register('android', TOKEN)
        self.service.register(UID, SCOPE, 'w' * 24, {'platform': 'windows', 'permission': 'concedido'})
        self.service.register('other-owner', SCOPE, 'x' * 24, {'platform': 'windows', 'permission': 'concedido'})
        self.snapshot['scope'] = 'b' * 64
        self.service.register(UID, 'b' * 64, 'y' * 24, {'platform': 'windows', 'permission': 'concedido'})
        self.snapshot['scope'] = SCOPE
        snapshot_reader = self.service.snapshot
        self.service.snapshot = Mock(side_effect=AssertionError('A test must not read or mutate sales'))
        result = self.service.test_notification(UID, SCOPE, DEVICE, {})
        self.service.snapshot = snapshot_reader
        self.assertEqual(result['targets'], 2)
        self.assertEqual(result['platforms'], {'android': 1, 'windows': 1})
        self.assertEqual(result['delivery']['provider_accepted'], 0)
        self.assertEqual(result['delivery']['acknowledged'], 0)
        rows = self.events()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['kind'], 'test')
        self.assertEqual(rows[0]['titulo'], 'PRUEBA · Corte')
        self.assertIn('No corresponde a una venta', rows[0]['texto'])
        self.assertTrue(rows[0]['order_id'].startswith('test:'))
        self.assertEqual(rows[0]['product_id'], 'notification-test')
        self.assertEqual(rows[0]['ruta'], '#/ventas')
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM observed_sales').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM events').fetchone()[0], 2)
        self.assertEqual(self.service.events('other-owner', SCOPE, 'x' * 24, '0')['items'], [])
        self.assertIsNone(self.service.status('other-owner', SCOPE, 'x' * 24)['last_test'])
        self.assertNotIn(TOKEN, str(result))
        self.assertNotIn(DEVICE, str(result))

    def test_test_idempotency_and_minute_rate_limit_are_persistent(self):
        self.register()
        rid = '847b13e0-7af9-438e-a4da-7b6857a3ad04'
        first = self.service.test_notification(UID, SCOPE, DEVICE, {'request_id': rid})
        second = self.service.test_notification(UID, SCOPE, DEVICE, {'request_id': rid})
        self.assertEqual(first, second)
        self.service = self.create()
        self.assertEqual(self.service.test_notification(UID, SCOPE, DEVICE, {'request_id': rid}), first)
        self.assertEqual(len(self.events()), 1)
        with self.assertRaises(ErrorDominio) as error:
            self.service.test_notification(UID, SCOPE, DEVICE, {})
        self.assertEqual(error.exception.http, 429)
        self.assertEqual(error.exception.reintentar_en_s, 60)
        self.now += 59
        with self.assertRaises(ErrorDominio) as error:
            self.service.test_notification(UID, SCOPE, DEVICE, {})
        self.assertEqual(error.exception.reintentar_en_s, 1)
        self.now += 1
        self.service.test_notification(UID, SCOPE, DEVICE, {})
        self.assertEqual(len(self.events()), 2)

    def test_test_receipts_distinguish_provider_acceptance_ack_and_cleanup(self):
        self.register('android', TOKEN)
        self.service.register(UID, SCOPE, 'w' * 24, {'platform': 'windows', 'permission': 'concedido'})
        initial = self.service.test_notification(UID, SCOPE, DEVICE, {})
        self.assertEqual(initial['delivery']['queued'], 2)
        self.service.tick()
        self.assertEqual(self.sender.call_count, 1)
        self.assertEqual(self.sender.call_args.args[1]['type'], 'sale')  # existing 2.3 clients
        self.assertEqual(self.sender.call_args.args[1]['titulo'], 'PRUEBA · Corte')
        accepted = self.service.status(UID, SCOPE, DEVICE)['last_test']
        self.assertEqual(accepted['delivery']['provider_accepted'], 1)
        self.assertEqual(accepted['delivery']['acknowledged'], 0)
        self.assertEqual(accepted['delivery']['queued'], 1)
        own_id = self.events()[0]['id']
        self.service.ack(UID, SCOPE, DEVICE, {'ids': [own_id, own_id]})
        self.service.ack(UID, SCOPE, DEVICE, {'ids': [own_id]})
        self.assertEqual(self.service.status(UID, SCOPE, DEVICE)['last_test']['delivery']['acknowledged'], 1)
        self.service.disable(UID, 'w' * 24, SCOPE)
        self.now += 48 * 3600
        self.service.tick()
        final = self.service.status(UID, SCOPE, DEVICE)['last_test']
        self.assertEqual(final['delivery']['provider_accepted'], 1)
        self.assertEqual(final['delivery']['acknowledged'], 1)  # disable/expiry never forge a device ACK
        self.assertEqual(final['delivery']['expired'], 2)

    def test_test_empty_target_and_invalid_body_do_not_consume_rate_limit(self):
        with self.assertRaises(ErrorDominio) as error:
            self.service.test_notification(UID, SCOPE, DEVICE, {})
        self.assertEqual(error.exception.http, 409)
        self.assertEqual(error.exception.detalle['platforms']['android'], 0)
        self.register()
        for body in (None, [], {'token': TOKEN}, {'uid': 'other-owner'}, {'request_id': 'not-uuid'},
                     {'request_id': None}, {'request_id': '847b13e07af9438ea4da7b6857a3ad04'}):
            with self.subTest(body=body), self.assertRaises(ErrorDominio) as error:
                self.service.test_notification(UID, SCOPE, DEVICE, body)
            self.assertEqual(error.exception.http, 422)
        self.assertEqual(self.service.test_notification(UID, SCOPE, DEVICE, {})['targets'], 1)

    def test_expired_test_summary_and_old_ack_are_safe_before_worker_tick(self):
        self.register()
        self.service.test_notification(UID, SCOPE, DEVICE, {})
        event_id = self.events()[0]['id']
        self.now += 24 * 3600
        summary = self.service.status(UID, SCOPE, DEVICE)['last_test']
        self.assertEqual(summary['state'], 'expired')
        self.assertEqual(summary['delivery']['queued'], 0)
        self.assertEqual(summary['delivery']['expired'], 1)
        self.assertEqual(summary['delivery']['acknowledged'], 0)
        response = self.service.ack(UID, SCOPE, DEVICE, {'ids': [event_id]})
        self.assertEqual(response['last_test']['delivery']['acknowledged'], 0)
        self.assertEqual(response['last_test']['state'], 'expired')
        self.sender.assert_not_called()

    def test_concurrent_same_request_is_idempotent_across_service_instances(self):
        self.register()
        other = self.create()
        gate = threading.Barrier(2)
        self.service.device_active = other.device_active = lambda *identity: gate.wait(timeout=5) is not None
        body = {'request_id': '847b13e0-7af9-438e-a4da-7b6857a3ad04'}
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                responses = list(pool.map(lambda service: service.test_notification(UID, SCOPE, DEVICE, body),
                                          [self.service, other]))
            self.assertEqual(responses[0], responses[1])
            self.assertEqual(len(self.events()), 1)
            self.assertEqual(responses[0]['targets'], 1)
        finally:
            other.close()

    def test_android_test_selects_only_latest_android_and_never_windows(self):
        self.register('android', TOKEN)
        self.now += 10
        self.service.register(UID, SCOPE, 'e' * 24,
            {'platform': 'android', 'permission': 'concedido', 'token': TOKEN + '-new'})
        self.now += 10
        self.service.register(UID, SCOPE, 'w' * 24, {'platform': 'windows', 'permission': 'concedido'})
        result = self.service.test_notification(UID, SCOPE, 'w' * 24, {'platform': 'android'})
        self.assertEqual(result['targets'], 1)
        self.assertEqual(result['platforms'], {'android': 1, 'windows': 0})
        self.assertEqual(self.events(), [])  # older Android
        self.assertEqual(self.service.events(UID, SCOPE, 'w' * 24, '0')['items'], [])
        self.assertEqual(len(self.service.events(UID, SCOPE, 'e' * 24, '0')['items']), 1)
        self.service.tick()
        self.assertEqual(self.sender.call_count, 1)
        self.assertEqual(self.sender.call_args.args[0], TOKEN + '-new')
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM observed_sales').fetchone()[0], 0)

    def test_platform_selection_skips_revoked_latest_and_breaks_after_one_active(self):
        self.register('android', TOKEN)
        self.now += 10
        self.service.register(UID, SCOPE, 'e' * 24,
            {'platform': 'android', 'permission': 'concedido', 'token': TOKEN + '-new'})
        validity = Mock(side_effect=lambda uid, device: device != 'e' * 24)
        self.service.device_active = validity
        result = self.service.test_notification(UID, SCOPE, DEVICE, {'platform': 'android'})
        self.assertEqual(result['targets'], 1)
        self.assertEqual([call.args[1] for call in validity.call_args_list], ['e' * 24, DEVICE])
        self.assertEqual(len(self.events()), 1)
        self.assertEqual(self.service.events(UID, SCOPE, 'e' * 24, '0')['items'], [])

    def test_platform_selection_with_equal_times_is_deterministic(self):
        self.service.register(UID, SCOPE, 'f' * 24,
            {'platform': 'android', 'permission': 'concedido', 'token': TOKEN + '-f'})
        self.service.register(UID, SCOPE, 'e' * 24,
            {'platform': 'android', 'permission': 'concedido', 'token': TOKEN + '-e'})
        self.service.test_notification(UID, SCOPE, DEVICE, {'platform': 'android'})
        self.assertEqual(len(self.service.events(UID, SCOPE, 'e' * 24, '0')['items']), 1)
        self.assertEqual(self.service.events(UID, SCOPE, 'f' * 24, '0')['items'], [])

    def test_android_test_without_android_target_never_falls_back_to_windows(self):
        self.register()
        with self.assertRaises(ErrorDominio) as error:
            self.service.test_notification(UID, SCOPE, DEVICE, {'platform': 'android'})
        self.assertEqual(error.exception.http, 409)
        self.assertEqual(error.exception.detalle, {'targets': 0, 'platforms': {'android': 0, 'windows': 0}})
        self.assertEqual(self.events(), [])
        self.sender.assert_not_called()
        for platform in (None, '', 'Android', 'web', [], True):
            with self.subTest(platform=platform), self.assertRaises(ErrorDominio) as error:
                self.service.test_notification(UID, SCOPE, DEVICE, {'platform': platform})
            self.assertEqual(error.exception.http, 422)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM push_tests').fetchone()[0], 0)

    def test_test_replay_cannot_change_or_widen_platform(self):
        self.register()
        self.service.register(UID, SCOPE, 'e' * 24,
            {'platform': 'android', 'permission': 'concedido', 'token': TOKEN})
        rid = '847b13e0-7af9-438e-a4da-7b6857a3ad04'
        body = {'request_id': rid, 'platform': 'android'}
        first = self.service.test_notification(UID, SCOPE, DEVICE, body)
        self.assertEqual(self.service.test_notification(UID, SCOPE, DEVICE, body), first)
        for requested in ({'request_id': rid}, {'request_id': rid, 'platform': 'windows'}):
            with self.subTest(requested=requested), self.assertRaises(ErrorDominio) as error:
                self.service.test_notification(UID, SCOPE, DEVICE, requested)
            self.assertEqual(error.exception.http, 409)
            self.assertEqual(error.exception.codigo, 'prueba_destino_incompatible')
        self.assertEqual(self.events(), [])  # no Windows notification was queued
        self.now += 60
        broad_id = '91be6c27-08a8-4828-90a6-57dfcc6474b8'
        broad = self.service.test_notification(UID, SCOPE, DEVICE, {'request_id': broad_id})
        self.assertEqual(broad['targets'], 2)  # existing {} semantics remain intact
        with self.assertRaises(ErrorDominio) as error:
            self.service.test_notification(UID, SCOPE, DEVICE, {'request_id': broad_id, 'platform': 'android'})
        self.assertEqual(error.exception.http, 409)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM events').fetchone()[0], 3)

    def test_legacy_test_metadata_gets_additive_platform_migration_without_retargeting(self):
        legacy_path = str(Path(self.folder.name) / 'legacy-push.sqlite')
        rid = '847b13e0-7af9-438e-a4da-7b6857a3ad04'
        with closing(sqlite3.connect(legacy_path)) as db:
            db.execute('CREATE TABLE push_tests(uid TEXT,scope TEXT,request_id TEXT,at INTEGER,android_targets INTEGER,'
                       'windows_targets INTEGER,provider_accepted INTEGER DEFAULT 0,acknowledged INTEGER DEFAULT 0,'
                       'PRIMARY KEY(uid,scope,request_id))')
            db.execute('INSERT INTO push_tests VALUES(?,?,?,?,0,1,0,1)', (UID, SCOPE, rid, self.now))
            db.commit()
        legacy = PushService(legacy_path, 'synthetic-encryption-secret' * 3,
            lambda uid: copy.deepcopy(self.snapshot), lambda uid, device: True, self.sender, lambda: self.now)
        try:
            with closing(sqlite3.connect(legacy_path)) as db:
                self.assertIsNone(db.execute('SELECT target_platform FROM push_tests').fetchone()[0])
                self.assertEqual(db.execute('SELECT acknowledged FROM push_tests').fetchone()[0], 1)
            with self.assertRaises(ErrorDominio) as error:
                legacy.test_notification(UID, SCOPE, DEVICE, {'request_id': rid, 'platform': 'android'})
            self.assertEqual(error.exception.http, 409)
            self.assertEqual(legacy.status(UID, SCOPE, DEVICE)['last_test']['platforms'], {'android': 0, 'windows': 1})
            self.assertEqual(legacy.events(UID, SCOPE, DEVICE, '0')['items'], [])
        finally:
            legacy.close()


class PaidSaleSnapshotTests(unittest.TestCase):
    def test_complete_paid_mxn_net_quantities_group_without_samples_or_unpaid(self):
        with tempfile.TemporaryDirectory() as folder:
            clock = SimpleNamespace(ahora=lambda: 1_800_000_000)
            store = crear_almacen(str(Path(folder) / 'hub.sqlite'), clock)
            try:
                with store.escritor() as db:
                    for oid, state, currency, fingerprint in [
                        ('1', 'To-SETTLE', 'MXN', 'complete'), ('2', 'SETTLED', 'MXN', 'complete'),
                        ('3', 'AWAITING PAYMENT', 'MXN', 'complete'), ('4', 'FROZEN', 'MXN', 'complete'),
                        ('5', 'REFUNDED', 'MXN', 'complete'), ('6', 'To-SETTLE', 'USD', 'complete'),
                        ('7', 'To-SETTLE', 'MXN', 'incompleta'), ('8', 'To-SETTLE', 'MXN', 'complete')]:
                        db.execute('INSERT INTO ordenes(order_id,creada_at,estado,huella,actualizado_at) VALUES(?,?,?,?,?)',
                                   (oid, 1_800_000_000, state, fingerprint, 1_800_000_000))
                        db.execute('INSERT INTO orden_lineas(order_id,linea_n,product_id,producto_nombre,precio_centavos,'
                                   'moneda,cantidad,reembolsadas,devueltas,com_estimada_centavos) VALUES(?,0,?,?,?,?,?,?,?,?)',
                                   (oid, '200', 'Sintético', 1000, currency, 3, 1, 0, 200))
                    db.execute('INSERT INTO orden_lineas(order_id,linea_n,product_id,producto_nombre,precio_centavos,'
                               'moneda,cantidad,com_estimada_centavos) VALUES(?,1,?,?,?,?,?,?)',
                               ('1', '200', 'Sintético', 1200, 'MXN', 1, 120))
                    db.execute("INSERT INTO muestras(application_id,product_id,main_order_id,estado_api,clase,subestado,"
                               "clase_desde_at,primera_vez_at,huella,actualizado_at) VALUES('10','200','8','COMPLETE',"
                               "'entregada','video_aprobado',1800000000,1800000000,'synthetic',1800000000)")
                snapshot = paid_snapshot(SimpleNamespace(almacen=store))
                self.assertEqual(snapshot['awaiting'], ['3'])
                self.assertEqual({s['order_id'] for s in snapshot['sales']}, {'1', '2'})
                first = next(s for s in snapshot['sales'] if s['order_id'] == '1')
                self.assertEqual(first['cantidad'], 3)
                self.assertEqual(first['venta_centavos'], 3200)
                self.assertEqual(first['comision_estimada_centavos'], 320)
            finally:
                store.cerrar()


if __name__ == '__main__':
    unittest.main()
