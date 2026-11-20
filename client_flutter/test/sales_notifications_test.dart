import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:corte/data/corte_repository.dart';
import 'package:corte/platform/corte_runtime.dart';
import 'package:corte/platform/sales_notifications.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

const scope =
    'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';
const otherScope =
    'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb';
const channel = MethodChannel('corte/sales');

class _Adapter implements CorteHttpAdapter {
  Future<JsonMap> Function(String, String, Object?) handle = (_, _, _) async =>
      {};
  final requests = <(String, String, Map<String, String>)>[];
  @override
  Future<CorteResponse> request(
    String method,
    String path, {
    Map<String, String> headers = const {},
    Object? body,
  }) async {
    requests.add((method, path, headers));
    final data = await handle(method, path, body);
    return CorteResponse(
      statusCode: 200,
      headers: const {'content-type': 'application/json'},
      bodyBytes: Uint8List.fromList(utf8.encode(jsonEncode(data))),
    );
  }

  @override
  void close() {}
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  late _Adapter adapter;
  late CorteRepository repo;
  late CorteSalesNotifications service;
  late List<MethodCall> calls;

  setUp(() {
    adapter = _Adapter();
    repo = CorteRepository(
      adapter: adapter,
      ownerScope: scope,
      cacheScope: scope,
    );
    service = CorteSalesNotifications(
      runtime: CorteRuntime(
        platform: 'windows',
        baseUri: Uri.parse(corteCloudOrigin),
      ),
    );
    calls = [];
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (call) async {
          calls.add(call);
          return switch (call.method) {
            'notificationPermission' ||
            'requestNotificationPermission' => 'concedido',
            'showSaleNotification' => true,
            _ => true,
          };
        });
  });
  tearDown(() {
    service.dispose();
    repo.close();
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, null);
  });

  test(
    'sales API requires scope and does not fall back to cached notifications',
    () async {
      repo.setScopes(ownerScope: scope);
      await expectLater(repo.get('/api/push/events'), throwsA(isA<ErrorApi>()));
      await expectLater(
        repo.post('/api/push/register', body: {}),
        throwsA(isA<ErrorApi>()),
      );
      expect(adapter.requests, isEmpty);
      repo.setScopes(ownerScope: scope, cacheScope: scope);
      await repo.get('/api/push/events');
      adapter.handle = (_, _, _) async =>
          throw const CorteTransportException('sin_red', 'Sin red');
      await expectLater(repo.get('/api/push/events'), throwsA(isA<ErrorApi>()));
      expect(adapter.requests.first.$3['X-Corte-Cache-Scope'], scope);
    },
  );

  test(
    'enrollment is explicit and permission is not requested on launch',
    () async {
      final read = Completer<void>();
      adapter.handle = (_, path, _) async {
        if (!read.isCompleted) read.complete();
        return {'enabled': false};
      };
      service.bind(repo, authenticated: true);
      await read.future;
      await Future<void>.delayed(Duration.zero);
      expect(
        calls.where((c) => c.method == 'requestNotificationPermission'),
        isEmpty,
      );
      expect(adapter.requests.where((r) => r.$1 == 'POST'), isEmpty);
      await service.setEnabled(true);
      expect(service.enabled, isTrue);
      expect(
        adapter.requests
            .where((r) => r.$2 == '/api/push/register')
            .single
            .$3['X-Corte-Cache-Scope'],
        scope,
      );
    },
  );

  test(
    'Android defers push requests while clearing a previous notification scope',
    () async {
      service.dispose();
      service = CorteSalesNotifications(
        runtime: CorteRuntime(
          platform: 'android',
          baseUri: Uri.parse(corteCloudOrigin),
        ),
      );
      final requested = Completer<void>();
      adapter.handle = (_, path, _) async {
        if (path == '/api/push/status' && !requested.isCompleted) {
          requested.complete();
        }
        return {'enabled': false};
      };

      service.bind(repo, authenticated: true, refreshAutomatically: false);
      repo.setScopes(ownerScope: scope, cacheScope: otherScope);
      service.bind(repo, authenticated: true, refreshAutomatically: false);
      await service.refresh();

      expect(adapter.requests, isEmpty);
      expect(calls.map((call) => call.method), [
        'configureSales',
        'configureSales',
      ]);
      expect(
        calls.map((call) => call.arguments),
        everyElement({'enabled': false, 'cache_scope': null}),
      );

      service.bind(repo, authenticated: true);
      await requested.future;
      expect(adapter.requests.single.$2, '/api/push/status');
      expect(adapter.requests.single.$3['X-Corte-Cache-Scope'], otherScope);
    },
  );

  test(
    'feed notification is scoped and acked only after native accepts it',
    () async {
      final acked = Completer<void>();
      adapter.handle = (_, path, body) async {
        if (path == '/api/push/status') return {'enabled': true};
        if (path == '/api/push/events')
          return {
            'items': [
              {
                'id': '17',
                'titulo': 'Nueva venta',
                'texto': 'Producto sintético',
                'ruta': '#/ventas',
              },
            ],
          };
        if (path == '/api/push/ack') {
          expect(body, {
            'ids': ['17'],
          });
          acked.complete();
        }
        return {};
      };
      service.bind(repo, authenticated: true);
      await acked.future;
      final notice = calls.singleWhere(
        (c) => c.method == 'showSaleNotification',
      );
      expect(notice.arguments['cache_scope'], scope);
      expect(
        adapter.requests.every((r) => r.$3['X-Corte-Cache-Scope'] == scope),
        isTrue,
      );
    },
  );

  test(
    'creator change during feed read never shows or acknowledges old events',
    () async {
      final requested = Completer<void>(), response = Completer<JsonMap>();
      adapter.handle = (_, path, _) async {
        if (path == '/api/push/status') return {'enabled': true};
        if (path == '/api/push/events') {
          requested.complete();
          return response.future;
        }
        return {};
      };
      service.bind(repo, authenticated: true);
      await requested.future;
      repo.setScopes(ownerScope: scope, cacheScope: otherScope);
      service.bind(repo, authenticated: true);
      response.complete({
        'items': [
          {
            'id': '17',
            'titulo': 'Anterior',
            'texto': 'Anterior',
            'ruta': '#/ventas',
          },
        ],
      });
      await Future<void>.delayed(Duration.zero);
      await Future<void>.delayed(Duration.zero);
      expect(calls.where((c) => c.method == 'showSaleNotification'), isEmpty);
      expect(adapter.requests.where((r) => r.$2 == '/api/push/ack'), isEmpty);
      expect(
        calls
            .where((c) => c.method == 'configureSales')
            .last
            .arguments['enabled'],
        isFalse,
      );
    },
  );
}
