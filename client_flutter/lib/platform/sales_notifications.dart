import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

import '../data/corte_repository.dart';
import 'corte_runtime.dart';

/// Push enrollment belongs to a verified device and creator, never to a cache.
class CorteSalesNotifications extends ChangeNotifier {
  CorteSalesNotifications({CorteRuntime? runtime, MethodChannel? channel})
    : runtime = runtime ?? CorteRuntime.current(),
      _channel = channel ?? const MethodChannel('corte/sales');

  final CorteRuntime runtime;
  final MethodChannel _channel;
  CorteRepository? _repo;
  Timer? _timer;
  FutureOr<void> Function(String)? _onOpen;
  bool _closed = false, _refreshing = false, busy = false, enabled = false;
  bool _refreshAutomatically = true;
  int _generation = 0;
  String? _scope, _owner, error;
  String? _registeredSignature;
  bool get supported =>
      runtime.platform == 'android' || runtime.platform == 'windows';
  bool get isWindows => runtime.platform == 'windows';

  Future<void> initialize({
    required FutureOr<void> Function(String) onOpen,
  }) async {
    _onOpen = onOpen;
    if (!supported) return;
    _channel.setMethodCallHandler((call) async {
      if (call.method == 'saleNotificationOpened') await _open();
      if (call.method == 'pushTokenChanged' && enabled) {
        try {
          await _registerCurrentToken();
        } catch (_) {
          /* Retry during the next refresh. */
        }
      }
    });
    _timer = Timer.periodic(
      const Duration(seconds: 25),
      (_) => unawaited(refresh()),
    );
    await _open();
  }

  Future<void> _open() async {
    try {
      final route = await _channel.invokeMethod<String>(
        'notificationLaunchRoute',
      );
      if (!_closed && route == '#/ventas') await _onOpen?.call(route!);
    } catch (_) {
      /* A notification must not interrupt startup. */
    }
  }

  void bind(
    CorteRepository repo, {
    required bool authenticated,
    bool refreshAutomatically = true,
  }) {
    final scope = authenticated ? repo.cacheScope : null;
    final owner = authenticated ? repo.ownerScope : null;
    _repo = repo;
    final resumed = refreshAutomatically && !_refreshAutomatically;
    _refreshAutomatically = refreshAutomatically;
    final scopeChanged = _scope != scope || _owner != owner;
    if (scopeChanged) {
      _scope = scope;
      _owner = owner;
      _generation++;
      _registeredSignature = null;
      enabled = false;
      error = null;
      unawaited(_configure(false, null));
    }
    if (scopeChanged || resumed) unawaited(refresh());
  }

  bool _current(int generation) =>
      !_closed && generation == _generation && _scope != null && _owner != null;
  Future<bool> _configure(bool value, String? scope) async {
    if (!supported) return false;
    try {
      final result = await _channel.invokeMethod<Object?>('configureSales', {
        'enabled': value,
        'cache_scope': scope,
      });
      return !value ||
          result == true ||
          result is Map && result['enabled'] == true;
    } catch (_) {
      /* Retry on enrollment/resume; no synthetic notification. */
      return false;
    }
  }

  Future<String> permission() async {
    if (!supported) return 'no_disponible';
    try {
      return await _channel.invokeMethod<String>('notificationPermission') ??
          'no_disponible';
    } catch (_) {
      return 'no_disponible';
    }
  }

  /// Permission requests are initiated by the user's notification button.
  Future<void> setEnabled(bool value) async {
    final repo = _repo;
    if (!supported || repo == null || _scope == null || _owner == null || busy)
      return;
    final generation = _generation;
    busy = true;
    error = null;
    notifyListeners();
    try {
      if (!value) {
        await _configure(false, null);
        await repo.delete('/api/push/register');
        _registeredSignature = null;
        if (_current(generation)) enabled = false;
      } else {
        var allowed = await permission();
        if (allowed != 'concedido') {
          allowed =
              await _channel.invokeMethod<String>(
                'requestNotificationPermission',
              ) ??
              'denegado';
        }
        if (!_current(generation)) return;
        if (allowed != 'concedido')
          throw StateError(
            'Permite las notificaciones de CUTGC en los ajustes del dispositivo.',
          );
        if (!await _configure(true, _scope)) {
          throw StateError(
            'El dispositivo no pudo activar las notificaciones de CUTGC. Vuelve a intentar.',
          );
        }
        if (!_current(generation)) return;
        await _registerCurrentToken(requireEnabled: false);
        if (_current(generation)) enabled = true;
      }
    } catch (e) {
      if (_current(generation)) {
        error = !value
            ? 'No pudimos guardar la desactivación en Google. Reintenta con conexión.'
            : e is ErrorApi
            ? e.mensaje
            : e is StateError
            ? '${e.message}'
            : 'No pudimos activar los avisos. Comprueba tu conexión y vuelve a intentar.';
        if (!enabled) await _configure(false, null);
      }
    } finally {
      busy = false;
      if (!_closed) notifyListeners();
    }
  }

  Future<void> _registerCurrentToken({bool requireEnabled = true}) async {
    final repo = _repo;
    final generation = _generation;
    if (repo == null || !_current(generation) || requireEnabled && !enabled)
      return;
    final token = runtime.platform == 'android'
        ? await _channel.invokeMethod<String>('pushToken')
        : null;
    if (!_current(generation)) return;
    if (runtime.platform == 'android' && (token == null || token.isEmpty)) {
      throw StateError(
        'Firebase aún no entregó el registro de notificaciones. Vuelve a intentar con Internet.',
      );
    }
    final signature = '$_scope:${runtime.platform}:$token';
    if (requireEnabled && _registeredSignature == signature) return;
    await repo.post(
      '/api/push/register',
      body: {
        'platform': runtime.platform,
        'permission': 'concedido',
        if (token != null) 'token': token,
      },
    );
    if (_current(generation)) _registeredSignature = signature;
  }

  Future<void> refresh() async {
    final repo = _repo;
    final generation = _generation;
    if (!supported ||
        !_refreshAutomatically ||
        repo == null ||
        !_current(generation) ||
        _refreshing ||
        busy)
      return;
    _refreshing = true;
    try {
      final status = await repo.get(
        '/api/push/status',
        force: true,
        permitirCacheSinRed: false,
      );
      if (!_current(generation)) return;
      final active = status['enabled'] == true;
      final changed = active != enabled;
      enabled = active;
      await _configure(active, active ? _scope : null);
      if (!_current(generation)) return;
      if (changed) notifyListeners();
      if (!active) return;
      if (await permission() != 'concedido' || !_current(generation)) return;
      if (runtime.platform == 'android') await _registerCurrentToken();
      if (!_current(generation)) return;
      final feed = await repo.get(
        '/api/push/events',
        force: true,
        permitirCacheSinRed: false,
      );
      if (!_current(generation)) return;
      final ids = <String>[];
      for (final raw in (feed['items'] as List? ?? const [])) {
        if (raw is! Map || !_current(generation)) break;
        final event = Map<String, dynamic>.from(raw);
        final id = '${event['id'] ?? ''}';
        if (!RegExp(r'^[0-9]{1,20}$').hasMatch(id) ||
            event['ruta'] != '#/ventas')
          continue;
        final accepted = await _channel
            .invokeMethod<bool>('showSaleNotification', {
              'id': id,
              'titulo': event['titulo'],
              'texto': event['texto'],
              'ruta': '#/ventas',
              'cache_scope': _scope,
            });
        if (!_current(generation)) return;
        if (accepted == true) {
          ids.add(id);
        } else {
          break;
        }
      }
      if (ids.isNotEmpty && _current(generation))
        await repo.post('/api/push/ack', body: {'ids': ids});
    } catch (_) {
      // Preserve enrollment during a temporary outage. Scope guards apply before showing/acking.
    } finally {
      _refreshing = false;
    }
  }

  @override
  void dispose() {
    _closed = true;
    _generation++;
    _timer?.cancel();
    if (supported) _channel.setMethodCallHandler(null);
    _onOpen = null;
    super.dispose();
  }
}
