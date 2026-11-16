import 'package:flutter/material.dart';

import '../data/corte_repository.dart';

/// Uses the same revisioned preferences and private offline journal as the
/// working plan. Theme changes never send a stale copy of the other fields.
class CorteThemePreferences extends ChangeNotifier {
  CorteThemePreferences(this.repo);

  final CorteRepository repo;
  String value = 'sistema';
  JsonMap? _preferences;
  String? _scope;
  int _epoch = 0;
  bool _closed = false;
  bool busy = false;
  bool pending = false;
  bool needsReview = false;
  String? error;
  Future<void>? _loading;

  ThemeMode get mode => switch (value) {
    'claro' => ThemeMode.light,
    'oscuro' => ThemeMode.dark,
    _ => ThemeMode.system,
  };
  bool get loaded => _preferences?['rev'] is int;
  String? get _identity =>
      repo.ownerScope == null ? null : '${repo.ownerScope}:${repo.cacheScope}';

  void resetForScope() {
    if (_scope == _identity) return;
    _scope = _identity;
    _epoch++;
    _loading = null;
    _preferences = null;
    value = 'sistema';
    busy = false;
    pending = false;
    needsReview = false;
    error = null;
    _notify();
  }

  Future<void> load({bool force = false}) {
    resetForScope();
    if (_closed || _scope == null || busy) return Future.value();
    if (_loading != null) return _loading!;
    final epoch = _epoch;
    final scope = _scope;
    late final Future<void> request;
    request = () async {
      try {
        final data = await repo.get('/api/preferencias', force: force);
        if (!_current(scope, epoch)) return;
        if (data['rev'] is! int) {
          throw const FormatException('Falta la versión de preferencias.');
        }
        _preferences = data;
        value = _valid(data['tema']) ? data['tema'] as String : 'claro';
        final queue = await repo.opsPendientes(incluirConflictos: true);
        if (!_current(scope, epoch)) return;
        bool isThemeChange(JsonMap entry) {
          final op = entry['op'];
          return op is Map &&
              op['tipo'] == 'preferencias.editar' &&
              op['cambios'] is Map &&
              (op['cambios'] as Map).containsKey('tema');
        }

        pending = queue.any(
          (entry) => entry['estado'] == 'pendiente' && isThemeChange(entry),
        );
        needsReview = queue.any(
          (entry) => entry['estado'] != 'pendiente' && isThemeChange(entry),
        );
        if (needsReview) {
          error =
              'Tu cambio de apariencia necesita revisión. Revisa la sección Copia y cambios pendientes.';
        } else if (error != null && loaded) {
          error = null;
        }
        _notify();
      } catch (_) {
        // Keep the current appearance while offline or during reauthentication.
        if (_current(scope, epoch) && !loaded) {
          error = 'No pudimos cargar tu preferencia de apariencia.';
          _notify();
        }
      } finally {
        if (identical(_loading, request)) _loading = null;
      }
    }();
    _loading = request;
    return request;
  }

  Future<GuardadoDto> choose(String next) async {
    resetForScope();
    if (!_valid(next) ||
        !loaded ||
        busy ||
        pending ||
        needsReview ||
        _scope == null) {
      throw ErrorApi(
        codigo: 'preferencia_no_disponible',
        mensaje: 'Espera a que se confirme la apariencia antes de cambiarla.',
      );
    }
    final previous = value;
    final scope = _scope;
    final epoch = ++_epoch;
    value = next;
    busy = true;
    error = null;
    _notify();
    try {
      final opId = nuevoId();
      final result = await repo.guardarOps([
        {
          'op_id': opId,
          'tipo': 'preferencias.editar',
          'cambios': {'rev': _preferences!['rev'], 'tema': next},
        },
      ]);
      if (!_current(scope, epoch)) {
        throw ErrorApi(
          codigo: 'sesion_cambiada',
          mensaje: 'La cuenta cambió mientras guardábamos la apariencia.',
        );
      }
      pending = result.enCola;
      final objects = result.resultados
          .where((item) => item['op_id'] == opId && item['objeto'] is Map)
          .map((item) => jsonMap(item['objeto']));
      _preferences = objects.isNotEmpty
          ? objects.last
          : {..._preferences!, 'tema': next};
      return result;
    } catch (failure) {
      if (_current(scope, epoch)) {
        final current = failure is ErrorApi ? failure.vigente : null;
        _preferences = current ?? _preferences;
        value = _valid(current?['tema'])
            ? current!['tema'] as String
            : previous;
        error = failure is ErrorApi
            ? failure.mensaje
            : 'No pudimos guardar la apariencia. Vuelve a intentarlo.';
        needsReview =
            failure is ErrorApi &&
            const {'conflicto', 'operacion_invalida'}.contains(failure.codigo);
      }
      rethrow;
    } finally {
      if (_current(scope, epoch)) {
        busy = false;
        _notify();
      }
    }
  }

  bool _current(String? scope, int epoch) =>
      !_closed && scope == _identity && scope == _scope && epoch == _epoch;

  static bool _valid(Object? value) =>
      const {'claro', 'oscuro', 'sistema'}.contains(value);

  void _notify() {
    if (!_closed) notifyListeners();
  }

  @override
  void dispose() {
    _closed = true;
    _epoch++;
    super.dispose();
  }
}
