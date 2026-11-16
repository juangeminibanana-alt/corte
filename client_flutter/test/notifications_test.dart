import 'dart:convert';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:corte/platform/notifications.dart';
import 'package:corte/platform/corte_runtime.dart';
import 'package:corte/data/corte_repository.dart';

class _Adapter implements CorteHttpAdapter {
  _Adapter(this.body, {this.status = 200, this.routes = const {}});
  final JsonMap body;
  final Map<String, JsonMap> routes;
  final int status;
  @override
  Future<CorteResponse> request(
    String method,
    String path, {
    Map<String, String> headers = const {},
    Object? body,
  }) async => CorteResponse(
    statusCode: status,
    headers: const {},
    bodyBytes: Uint8List.fromList(
      utf8.encode(jsonEncode(routes[path] ?? this.body)),
    ),
  );
  @override
  void close() {}
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  const channel = MethodChannel('corte/notifications-test');
  final runtime = CorteRuntime(
    platform: 'android',
    baseUri: Uri.parse(corteCloudOrigin),
  );
  final messenger =
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
  tearDown(() => messenger.setMockMethodCallHandler(channel, null));
  int epoch(DateTime time) => time.millisecondsSinceEpoch ~/ 1000;

  test(
    'uses Mexico calendar at midnight boundary, not the device timezone',
    () {
      final list = calcularNotificaciones({
        'muestras': [],
        'local': {
          'preferencias': {
            'recordatorio_diario': true,
            'hora_recordatorio': '23:00',
            'dias_videos': [6],
          },
          'planes': [
            {
              'id': 'p',
              'estado': 'planeada',
              'fecha_plan': '2026-11-15',
              'titulo': 'Video real',
              'orden': 0,
            },
          ],
        },
      }, ahora: DateTime.utc(2026, 11, 16, 2));
      expect(list.single['id'], 'plan-2026-11-15');
      expect(list.single['at'], epoch(DateTime.utc(2026, 11, 16, 5)));
    },
  );

  test(
    'expiration and latest nonremoved promise exclude a fulfilled sample',
    () {
      final deadline = epoch(DateTime.utc(2026, 11, 18, 18));
      JsonMap sample(String id, String stage) => {
        'application_id': id,
        'grupo': 'por_vencer',
        'fecha_limite_at': deadline,
        'avance': {'etapa': stage, 'vinculo_origen': 'manual'},
        'producto': {'titulo': 'Muestra real'},
        'tienda': {'nombre': 'Tienda'},
      };
      final result = calcularNotificaciones({
        'muestras': [sample('a', 'planeada'), sample('b', 'publicada')],
        'local': {
          'preferencias': {
            'aviso_por_vencer': true,
            'aviso_promesas': true,
            'hora_recordatorio': '10:00',
          },
          'avisos': [
            {
              'id': 'old',
              'marcado_enviado_at': 1,
              'quitado_at': null,
              'compromisos': {'a': '2026-11-18'},
            },
            {
              'id': 'new',
              'marcado_enviado_at': 2,
              'quitado_at': null,
              'compromisos': {'a': '2026-11-20'},
            },
            {
              'id': 'removed',
              'marcado_enviado_at': 3,
              'quitado_at': 4,
              'compromisos': {'a': '2026-11-21'},
            },
          ],
        },
      }, ahora: DateTime.utc(2026, 11, 16, 12));
      expect(result.map((n) => n['id']).toSet(), {
        'vence-a-48',
        'vence-a-24',
        'promesa-new-a',
      });
      expect(result.last['at'], epoch(DateTime.utc(2026, 11, 19, 16)));
    },
  );

  test(
    'postponed repeating reminders have stable IDs and a bounded earliest-first batch',
    () {
      final now = DateTime.utc(2026, 11, 16, 12);
      final result = calcularNotificaciones({
        'muestras': [],
        'local': {
          'preferencias': {},
          'recordatorios': [
            {
              'id': 'daily',
              'estado': 'activo',
              'titulo': 'Seguimiento',
              'vence_at': epoch(now.subtract(const Duration(days: 10))),
              'pospuesto_hasta': epoch(now.add(const Duration(hours: 1))),
              'repetir': 'diario',
              'entidad': 'plan',
            },
            ...List.generate(
              100,
              (i) => {
                'id': 'custom-$i',
                'estado': 'activo',
                'titulo': 'Aviso',
                'vence_at': epoch(now.add(Duration(hours: i + 2))),
                'repetir': 'no',
              },
            ),
            {
              'id': 'done',
              'estado': 'hecho',
              'titulo': 'Terminado',
              'vence_at': epoch(now.add(const Duration(hours: 1))),
              'repetir': 'no',
            },
          ],
        },
      }, ahora: now);
      expect(result.length, 64);
      expect(result.first['id'], 'recordatorio-daily-2026-11-16');
      expect(result.first['at'], epoch(now.add(const Duration(hours: 1))));
      expect(result.map((n) => n['id']).toSet().length, 64);
      expect(result.any((n) => n['id'] == 'recordatorio-done'), false);
      expect(
        result.map((n) => n['at']),
        orderedEquals([...result.map((n) => n['at'] as int)]..sort()),
      );
    },
  );

  test(
    'failed snapshot preserves existing alarms; permission request is explicit',
    () async {
      final calls = <String>[];
      messenger.setMockMethodCallHandler(channel, (call) async {
        calls.add(call.method);
        if (call.method == 'notificationPermission') return 'denegado';
        if (call.method == 'requestNotificationPermission') return 'concedido';
        return null;
      });
      final notifications = CorteNotifications(
        runtime: runtime,
        channel: channel,
      );
      await notifications.initialize(onOpen: (_) {});
      expect(calls, ['notificationLaunchRoute']);
      expect(await notifications.permission(), 'denegado');
      expect(calls, isNot(contains('requestNotificationPermission')));
      final repo = CorteRepository(
        adapter: _Adapter({
          'error': {'codigo': 'sin_red', 'mensaje': 'Sin red'},
        }, status: 503),
        ownerScope: 'a' * 64,
        cacheScope: 'b' * 64,
      );
      expect(await notifications.refresh(repo), false);
      expect(calls, isNot(contains('scheduleNotifications')));
      expect(await notifications.requestPermission(), 'concedido');
      notifications.dispose();
    },
  );

  test(
    'a complete repository snapshot schedules once and preserves the actual reminder route',
    () async {
      final now = DateTime.utc(2026, 11, 16, 12);
      final pref = <String, dynamic>{
        'hora_recordatorio': '10:00',
        'dias_videos': [],
      };
      final reminder = <String, dynamic>{
        'id': 'real',
        'estado': 'activo',
        'titulo': 'Mi recordatorio',
        'vence_at': epoch(now.add(const Duration(hours: 2))),
        'repetir': 'no',
        'entidad': 'muestra',
        'entidad_id': 'a',
      };
      final repo = CorteRepository(
        adapter: _Adapter(
          {},
          routes: {
            '/api/snapshot': {
              'muestras': [],
              'local': {'preferencias': pref},
            },
            '/api/plan': {'items': []},
            '/api/avisos': {'items': []},
            '/api/recordatorios': {
              'items': [reminder],
            },
            '/api/preferencias': pref,
          },
        ),
        ownerScope: 'a' * 64,
        cacheScope: 'b' * 64,
      );
      final scheduled = <Object?>[];
      messenger.setMockMethodCallHandler(channel, (call) async {
        if (call.method == 'scheduleNotifications') {
          scheduled.add(call.arguments);
        }
        return null;
      });
      final notifications = CorteNotifications(
        runtime: runtime,
        channel: channel,
        now: () => now,
      );
      expect(await notifications.refresh(repo), true);
      expect(await notifications.refresh(repo), true);
      expect(scheduled, hasLength(1));
      final payload =
          jsonDecode((scheduled.single as Map)['notifications'] as String)
              as List;
      expect(payload.single['ruta'], '#/muestras/m/a');
      expect(payload.single['at'], reminder['vence_at']);
      notifications.dispose();
    },
  );

  test('unsupported platforms never invoke native notification APIs', () async {
    final calls = <String>[];
    messenger.setMockMethodCallHandler(channel, (call) async {
      calls.add(call.method);
      return null;
    });
    final notifications = CorteNotifications(
      runtime: CorteRuntime(
        platform: 'windows',
        baseUri: Uri.parse(corteCloudOrigin),
      ),
      channel: channel,
    );
    await notifications.initialize(onOpen: (_) {});
    expect(await notifications.requestPermission(), 'no_disponible');
    expect(await notifications.readLaunchRoute(), null);
    expect(calls, isEmpty);
    notifications.dispose();
  });
}
