import 'dart:convert';

import '../domain/corte_models.dart';
import 'corte_store.dart';
import 'snapshot_projection.dart';

const tiposOpLocal = {
  'plan.crear',
  'plan.editar',
  'plan.borrar',
  'nota.crear',
  'nota.editar',
  'nota.borrar',
  'recordatorio.crear',
  'recordatorio.editar',
  'recordatorio.borrar',
  'aviso.crear',
  'aviso.editar',
  'plantilla.editar',
  'preferencias.editar',
};

bool scopeValido(String value) => RegExp(r'^[a-f0-9]{64}$').hasMatch(value);

class CorteJournal {
  CorteJournal(this.store, this.scope) {
    if (!scopeValido(scope)) throw ArgumentError('Scope de copia inválido.');
  }

  final CorteDataStore store;
  final String scope;
  Future<void> _tail = Future.value();
  String key(String kind) => 'corte.data.$scope.$kind';

  Future<T> _serial<T>(Future<T> Function() action) {
    final result = _tail.then((_) => action());
    _tail = result.then<void>((_) {}, onError: (Object _, StackTrace __) {});
    return result;
  }

  Future<JsonMap?> leerSnapshot() async {
    final content = await store.read(key('snapshot'));
    if (content == null) return null;
    final envelope = _envelope(content);
    if (envelope['snapshot'] is! Map) throw _invalid();
    return envelope;
  }

  Future<void> guardarSnapshot(JsonMap snapshot, String? etag) => _serial(
    () async {
      if (snapshot['version_esquema'] != 1 ||
          snapshot['muestras'] is! List ||
          snapshot['local'] is! Map) {
        throw _invalid();
      }
      await store.write(
        key('snapshot'),
        jsonEncode({
          'version': 1,
          'cache_scope': scope,
          'guardada_at': DateTime.now().toUtc().millisecondsSinceEpoch ~/ 1000,
          'etag': etag,
          'snapshot': snapshot,
        }),
      );
    },
  );

  Future<List<JsonMap>> leerOps() async {
    final content = await store.read(key('outbox'));
    if (content == null) return const [];
    final envelope = _envelope(content);
    if (envelope['ops'] is! List) throw _invalid();
    return jsonObjects(envelope['ops']);
  }

  Future<void> encolar(List<JsonMap> ops) => _serial(() async {
    final existing = (await leerOps()).toList();
    final ids = {
      for (final item in existing) jsonMap(item['op'])['op_id']: item,
    };
    for (final operation in ops) {
      final op = immutableJson(operation);
      final id = op['op_id'];
      if (id is! String ||
          id.isEmpty ||
          id.length > 64 ||
          !tiposOpLocal.contains(op['tipo'])) {
        throw ErrorApi(
          codigo: 'operacion_invalida',
          mensaje: 'El cambio no es una operación local válida.',
        );
      }
      final previous = ids[id];
      if (previous != null) {
        if (!_sameJson(previous['op'], op)) {
          throw ErrorApi(
            codigo: 'operacion_repetida',
            mensaje: 'Este cambio ya existe con otro contenido.',
          );
        }
        continue;
      }
      final item = immutableJson({
        'op': op,
        'estado': 'pendiente',
        'resultado': null,
      });
      existing.add(item);
      ids[id] = item;
    }
    if (existing.length > 5000) {
      throw ErrorApi(
        codigo: 'cola_llena',
        mensaje: 'Conecta Corte para enviar los cambios pendientes.',
      );
    }
    await _guardarOps(existing);
  });

  Future<void> confirmar(
    List<JsonMap> resultados,
    Set<String> enviados,
  ) => _serial(() async {
    final current = (await leerOps()).toList();
    final responses = {
      for (final result in resultados)
        if (result['op_id'] is String && enviados.contains(result['op_id']))
          result['op_id']: result,
    };
    final remaining = <JsonMap>[];
    for (final item in current) {
      final result = responses[jsonMap(item['op'])['op_id']];
      if (result == null) {
        remaining.add(item);
      } else if (const ['aplicada', 'duplicada'].contains(result['estado'])) {
        continue;
      } else if (const ['conflicto', 'invalida'].contains(result['estado'])) {
        remaining.add(
          immutableJson({
            ...item,
            'estado': result['estado'],
            'resultado': result,
          }),
        );
      } else {
        remaining.add(item);
      }
    }
    final saved = await leerSnapshot();
    if (saved != null) {
      // Save first: a crash can safely replay the old idempotent operation.
      // The reverse order could permanently hide an acknowledged local edit.
      await store.write(
        key('snapshot'),
        jsonEncode({
          ...saved,
          'etag': null,
          'snapshot': snapshotConResultados(
            jsonMap(saved['snapshot']),
            current,
            responses,
          ),
        }),
      );
    }
    await _guardarOps(remaining);
  });

  /// A deliberate local discard never dispatches a business mutation.
  Future<void> descartar(String opId) => _serial(() async {
    final existing = await leerOps();
    await _guardarOps(
      existing.where((item) => jsonMap(item['op'])['op_id'] != opId).toList(),
    );
  });

  /// Persist the reviewed replacement in the same atomic write as the removal.
  /// A failed disk write leaves the rejected operation intact.
  Future<void> reemplazar(
    String opId,
    JsonMap replacement,
  ) => _serial(() async {
    final existing = (await leerOps()).toList();
    final index = existing.indexWhere(
      (item) => jsonMap(item['op'])['op_id'] == opId,
    );
    if (index < 0 ||
        !const ['conflicto', 'invalida'].contains(existing[index]['estado'])) {
      throw ErrorApi(
        codigo: 'cambio_no_disponible',
        mensaje: 'El cambio pendiente ya no está disponible para resolverlo.',
      );
    }
    final nextId = replacement['op_id'];
    if (nextId is! String ||
        nextId.isEmpty ||
        nextId.length > 64 ||
        nextId == opId ||
        !tiposOpLocal.contains(replacement['tipo']) ||
        existing.any((item) => jsonMap(item['op'])['op_id'] == nextId)) {
      throw ErrorApi(
        codigo: 'operacion_invalida',
        mensaje: 'La corrección necesita una operación nueva y válida.',
      );
    }
    existing[index] = immutableJson({
      'op': replacement,
      'estado': 'pendiente',
      'resultado': null,
    });
    await _guardarOps(existing);
  });

  Future<void> _guardarOps(List<JsonMap> items) async {
    final encoded = jsonEncode({
      'version': 1,
      'cache_scope': scope,
      'ops': items,
    });
    if (utf8.encode(encoded).length > 20 * 1024 * 1024) {
      throw ErrorApi(
        codigo: 'cola_llena',
        mensaje:
            'La copia pendiente alcanzó su límite. Conecta Corte para sincronizar.',
      );
    }
    await store.write(key('outbox'), encoded);
  }

  JsonMap _envelope(String content) {
    try {
      final value = jsonMap(jsonDecode(content));
      if (value['version'] != 1 || value['cache_scope'] != scope)
        throw _invalid();
      return immutableJson(value);
    } on FormatException {
      throw _invalid();
    }
  }

  ErrorApi _invalid() => ErrorApi(
    codigo: 'copia_invalida',
    mensaje:
        'Esta copia no corresponde a la conexión actual o no se puede leer. Conservamos el archivo.',
  );
}

bool _sameJson(Object? left, Object? right) {
  if (left is Map && right is Map) {
    if (left.length != right.length) return false;
    return left.keys.every(
      (key) => right.containsKey(key) && _sameJson(left[key], right[key]),
    );
  }
  if (left is List && right is List) {
    if (left.length != right.length) return false;
    for (var index = 0; index < left.length; index++) {
      if (!_sameJson(left[index], right[index])) return false;
    }
    return true;
  }
  return left == right;
}
