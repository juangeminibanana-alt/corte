import 'dart:async';
import 'dart:convert';

import 'package:flutter/services.dart';

import '../data/corte_repository.dart';
import 'corte_runtime.dart';

/// Android's existing AlarmManager/Keystore host; no permission prompt on launch.
class CorteNotifications {
  CorteNotifications({
    CorteRuntime? runtime,
    MethodChannel? channel,
    DateTime Function()? now,
  }) : _runtime = runtime ?? CorteRuntime.current(),
       _channel = channel ?? const MethodChannel('corte/native'),
       _now = now ?? DateTime.now;
  final CorteRuntime _runtime;
  final MethodChannel _channel;
  final DateTime Function() _now;
  FutureOr<void> Function(String)? _onOpen;
  String? _last;
  bool _refreshing = false;
  bool _disposed = false;
  bool get supported => _runtime.platform == 'android';

  Future<void> initialize({
    required FutureOr<void> Function(String) onOpen,
  }) async {
    _onOpen = onOpen;
    if (!supported || _disposed) return;
    _channel.setMethodCallHandler((call) async {
      if (call.method == 'notificationOpened') await _open();
    });
    await _open();
  }

  Future<void> _open() async {
    final route = await readLaunchRoute();
    if (route == null || _disposed) return;
    try {
      await _onOpen?.call(route);
    } catch (_) {
      /* Navigation must not crash launch. */
    }
  }

  Future<String?> readLaunchRoute() async {
    if (!supported || _disposed) return null;
    try {
      final route = await _channel.invokeMethod<String>(
        'notificationLaunchRoute',
      );
      return route != null &&
              RegExp(r'^#/[A-Za-z0-9/_.~?=&%\-]{0,200}$').hasMatch(route)
          ? route
          : null;
    } catch (_) {
      return null;
    }
  }

  Future<String> permission() async => _permission('notificationPermission');

  /// Call only after an explicit user action.
  Future<String> requestPermission() async =>
      _permission('requestNotificationPermission');
  Future<String> _permission(String method) async {
    if (!supported || _disposed) return 'no_disponible';
    try {
      return await _channel.invokeMethod<String>(method) ?? 'denegado';
    } catch (_) {
      return 'no_disponible';
    }
  }

  /// A failed/incomplete read leaves the existing native alarms intact.
  Future<bool> refresh(CorteRepository repo, {SnapshotDto? snapshot}) async {
    if (!supported || _disposed || _refreshing) return false;
    _refreshing = true;
    final scope = repo.cacheScope;
    final owner = repo.ownerScope;
    try {
      if (scope == null || owner == null) return false;
      final currentSnapshot = snapshot ?? await repo.snapshot();
      final local = currentSnapshot.local;
      if (local == null ||
          local['preferencias'] is! Map ||
          currentSnapshot.raw['muestras'] is! List) {
        return false;
      }
      // Repository projections include pending local changes; rejected changes are excluded.
      final parts = await Future.wait([
        repo.get('/api/plan'),
        repo.get('/api/recordatorios'),
        repo.get('/api/avisos'),
        repo.get('/api/preferencias'),
      ]);
      if (_disposed || scope != repo.cacheScope || owner != repo.ownerScope) {
        return false;
      }
      if (parts.take(3).any((part) => part['items'] is! List)) return false;
      final preferences = _map(parts[3]['preferencias'] ?? parts[3]);
      if (preferences['hora_recordatorio'] is! String ||
          preferences['dias_videos'] is! List) {
        return false;
      }
      final current = <String, dynamic>{
        ...currentSnapshot.raw,
        'local': <String, dynamic>{
          ...local,
          'planes': parts[0]['items'],
          'recordatorios': parts[1]['items'],
          'avisos': parts[2]['items'],
          'preferencias': preferences,
        },
      };
      final notifications = calcularNotificaciones(current, ahora: _now());
      final payload = jsonEncode(notifications);
      if (utf8.encode(payload).length > 65536) return false;
      final signature = '$scope:$payload';
      if (_last == signature) return true;
      await _channel.invokeMethod<void>('scheduleNotifications', {
        'notifications': payload,
      });
      if (!_disposed && scope == repo.cacheScope) _last = signature;
      return true;
    } catch (_) {
      return false;
    } finally {
      _refreshing = false;
    }
  }

  void dispose() {
    _disposed = true;
    if (supported) _channel.setMethodCallHandler(null);
    _onOpen = null;
  }
}

/// Same fixed Mexico-centre calendar as the existing Corte scheduler (UTC-6).
/// Only future events in the next seven days; stable IDs avoid duplicates.
List<JsonMap> calcularNotificaciones(
  JsonMap snapshot, {
  required DateTime ahora,
  int dias = 7,
}) {
  const day = 86400;
  final now = ahora.toUtc().millisecondsSinceEpoch ~/ 1000;
  final horizon = now + dias.clamp(1, 7) * day;
  final local = _map(snapshot['local']);
  final pref = _map(local['preferencias']);
  final samples = _rows(snapshot['muestras']);
  final plans = _rows(local['planes']);
  final avisos = _rows(local['avisos']);
  final byId = {for (final m in samples) m['application_id']: m};
  final output = <String, JsonMap>{};
  final mx = ahora.toUtc().subtract(const Duration(hours: 6));
  final today = DateTime.utc(mx.year, mx.month, mx.day);
  final clock = RegExp(
    r'^(\d{1,2}):(\d{2})$',
  ).firstMatch('${pref['hora_recordatorio'] ?? ''}');
  final hour = int.tryParse(clock?.group(1) ?? '') ?? 10;
  final minute = int.tryParse(clock?.group(2) ?? '') ?? 0;
  final h = hour >= 0 && hour < 24 && minute >= 0 && minute < 60 ? hour : 10;
  final min = hour >= 0 && hour < 24 && minute >= 0 && minute < 60 ? minute : 0;
  int at(DateTime date, int hour, int minute) =>
      date
          .add(Duration(hours: hour + 6, minutes: minute))
          .millisecondsSinceEpoch ~/
      1000;
  String date(DateTime d) => d.toIso8601String().substring(0, 10);
  bool pending(JsonMap m) {
    final advance = _map(m['avance']);
    return const ['por_vencer', 'vencida', 'pausada'].contains(m['grupo']) &&
        advance['etapa'] != 'no_se_puede' &&
        !(advance['etapa'] == 'publicada' &&
            advance['vinculo_origen'] != 'video_previo');
  }

  bool validPlan(JsonMap p) =>
      p['estado'] == 'planeada' &&
      _date(p['fecha_plan']) != null &&
      (byId[p['application_id']] == null ||
          pending(byId[p['application_id']]!));
  String name(JsonMap? m, [JsonMap? p]) => _short(
    p?['nombre_corto'] ??
        _map(m?['producto'])['titulo_corto'] ??
        _map(m?['producto'])['titulo'] ??
        p?['titulo'] ??
        'Tu muestra',
    80,
  );
  String store(JsonMap? m) => '${_map(m?['tienda'])['nombre'] ?? 'tu tienda'}';
  void put(String id, String title, String text, int when, String route) {
    if (when <= now ||
        when > horizon ||
        !RegExp(r'^[A-Za-z0-9._:\-]{1,80}$').hasMatch(id)) {
      return;
    }
    output.putIfAbsent(
      id,
      () => {
        'id': id,
        'titulo': _short(title, 120),
        'texto': _short(text, 400),
        'at': when,
        'ruta': route,
      },
    );
  }

  for (var k = 0; k <= dias.clamp(1, 7); k++) {
    final d = today.add(Duration(days: k));
    final stamp = date(d);
    if (pref['recordatorio_diario'] == true &&
        (pref['dias_videos'] is List &&
            (pref['dias_videos'] as List).contains(d.weekday - 1))) {
      final items =
          plans.where((p) => validPlan(p) && p['fecha_plan'] == stamp).toList()
            ..sort((a, b) {
              final order = _int(a['orden']) - _int(b['orden']);
              if (order != 0) return order;
              final position =
                  _int(
                    byId[a['application_id']]?['posicion_cola'],
                    1000000000,
                  ) -
                  _int(byId[b['application_id']]?['posicion_cola'], 1000000000);
              return position != 0
                  ? position
                  : '${a['id']}'.compareTo('${b['id']}');
            });
      if (items.isNotEmpty) {
        final first = items.first;
        final m = byId[first['application_id']];
        put(
          'plan-$stamp',
          items.length == 1
              ? 'Hoy toca: 1 video de muestra'
              : 'Hoy toca: ${items.length} videos de muestras',
          '${name(m, first)} (${store(m)})${items.length > 1 ? ' y ${items.length - 1} más' : ''}.',
          at(d, h, min),
          '#/muestras/sesion',
        );
      }
    }
    if (pref['resumen_semanal'] == true && d.weekday == DateTime.monday) {
      final start = date(d.subtract(const Duration(days: 7)));
      final n = plans
          .where(
            (p) =>
                p['estado'] == 'publicada' &&
                p['vinculo_origen'] != 'video_previo' &&
                p['fecha_publicada'] is String &&
                (p['fecha_publicada'] as String).compareTo(start) >= 0 &&
                (p['fecha_publicada'] as String).compareTo(stamp) < 0,
          )
          .length;
      put(
        'resumen-$stamp',
        'Tu resumen de la semana',
        '$n ${n == 1 ? 'video de muestra publicado' : 'videos de muestras publicados'} la semana pasada. Toca para ver tus ventas.',
        at(d, 9, 0),
        '#/ventas',
      );
    }
  }
  for (final m in samples) {
    final id = '${m['application_id']}';
    final advance = _map(m['avance']);
    if (pref['aviso_por_vencer'] == true &&
        m['grupo'] == 'por_vencer' &&
        m['fecha_limite_at'] is num &&
        pending(m)) {
      for (final hours in [48, 24]) {
        put(
          'vence-$id-$hours',
          'Una muestra vence en ${hours == 48 ? '2 días' : '1 día'}',
          '${name(m)} de ${store(m)}. Publica el video para que cuente en TikTok.',
          _int(m['fecha_limite_at']) - hours * 3600,
          '#/muestras/m/$id',
        );
      }
    }
    if (pref['aviso_promesas'] != true ||
        const ['publicada', 'no_se_puede'].contains(advance['etapa'])) {
      continue;
    }
    JsonMap? promise;
    for (final aviso in avisos) {
      if (aviso['marcado_enviado_at'] is! num ||
          aviso['quitado_at'] != null ||
          _map(aviso['compromisos'])[id] is! String) {
        continue;
      }
      if (promise == null ||
          _int(aviso['marcado_enviado_at']) >
              _int(promise['marcado_enviado_at'])) {
        promise = aviso;
      }
    }
    final promised = _date(_map(promise?['compromisos'])[id]);
    if (promise != null && promised != null) {
      put(
        'promesa-${promise['id']}-$id',
        'Mañana vence lo que le prometiste a ${store(m)}',
        '${name(m)}: le dijiste que lo publicabas a más tardar el ${date(promised)}.',
        at(promised.subtract(const Duration(days: 1)), h, min),
        '#/muestras/m/$id',
      );
    }
  }
  if (pref['aviso_atrasados'] == true) {
    final d = at(today, h, min) > now
        ? today
        : today.add(const Duration(days: 1));
    final n = plans
        .where(
          (p) =>
              validPlan(p) &&
              (p['fecha_plan'] as String).compareTo(date(d)) < 0,
        )
        .length;
    if (n > 0) {
      put(
        'atrasados-${date(d)}',
        n == 1
            ? 'Te quedó 1 video de días anteriores'
            : 'Te quedaron $n videos de días anteriores',
        n == 1 ? 'Toca para moverlo a hoy.' : 'Toca para moverlos a hoy.',
        at(d, h, min),
        '#/muestras/agenda',
      );
    }
  }
  for (final r in _rows(local['recordatorios'])) {
    if (r['estado'] != 'activo') continue;
    final due = _int(r['vence_at']);
    final postponed = _int(r['pospuesto_hasta']);
    final base = postponed > due ? postponed : due;
    final entity = r['entidad'];
    final id = r['entidad_id'];
    final m = byId[id];
    var route = '#/inicio';
    var text = 'Toca para verlo.';
    if (entity == 'muestra' && id is String) {
      route = '#/muestras/m/$id';
      if (m != null) text = '${name(m)} de ${store(m)}.';
    } else if (entity == 'tienda' && id is String) {
      route = '#/tiendas/${Uri.encodeComponent(id)}';
    } else if (entity == 'plan') {
      route = '#/muestras/agenda';
      text = 'Revisa tu agenda.';
    }
    if (r['repetir'] == 'no' || r['repetir'] == null) {
      put(
        'recordatorio-${r['id']}',
        '${r['titulo'] ?? 'Recordatorio'}',
        text,
        base,
        route,
      );
      continue;
    }
    final step = r['repetir'] == 'diario' ? day : 7 * day;
    var when = base <= now ? base + ((now - base) ~/ step + 1) * step : base;
    for (; when <= horizon; when += step) {
      final d = DateTime.fromMillisecondsSinceEpoch(
        (when - 21600) * 1000,
        isUtc: true,
      );
      put(
        'recordatorio-${r['id']}-${date(d)}',
        '${r['titulo'] ?? 'Recordatorio'}',
        text,
        when,
        route,
      );
    }
  }
  final result = output.values.toList()
    ..sort((a, b) {
      final order = _int(a['at']) - _int(b['at']);
      return order != 0 ? order : '${a['id']}'.compareTo('${b['id']}');
    });
  return List.unmodifiable(result.take(64));
}

JsonMap _map(Object? value) =>
    value is Map ? Map<String, dynamic>.from(value) : {};
List<JsonMap> _rows(Object? value) =>
    value is List ? value.whereType<Map>().map(_map).toList() : [];
int _int(Object? value, [int fallback = 0]) =>
    value is num && value.isFinite ? value.toInt() : fallback;
String _short(Object? value, int max) =>
    String.fromCharCodes('$value'.runes.take(max));
DateTime? _date(Object? value) {
  if (value is! String || !RegExp(r'^\d{4}-\d{2}-\d{2}$').hasMatch(value)) {
    return null;
  }
  final date = DateTime.tryParse('${value}T00:00:00Z');
  return date != null && date.toIso8601String().startsWith(value) ? date : null;
}
