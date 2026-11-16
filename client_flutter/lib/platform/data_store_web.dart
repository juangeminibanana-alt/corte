import 'dart:js_interop';

import 'data_store.dart';

@JS('corteData.read')
external JSPromise<JSAny?> _read(JSString key);
@JS('corteData.write')
external JSPromise<JSAny?> _write(JSString key, JSString value);
@JS('corteData.remove')
external JSPromise<JSAny?> _remove(JSString key);

CorteDataStore createStore() => const _WebStore();

class _WebStore implements CorteDataStore {
  const _WebStore();
  void _check(String key) {
    if (!validCorteDataKey(key)) {
      throw const CorteStoreException('La clave de la copia no es válida.');
    }
  }

  @override
  Future<String?> read(String key) async {
    _check(key);
    try {
      final value = (await _read(key.toJS).toDart)?.dartify();
      return value is String ? value : null;
    } catch (_) {
      throw const CorteStoreException(
        'No pudimos leer la copia del navegador.',
      );
    }
  }

  @override
  Future<void> write(String key, String value) async {
    _check(key);
    try {
      await _write(key.toJS, value.toJS).toDart;
    } catch (_) {
      throw const CorteStoreException(
        'No pudimos guardar el cambio en este navegador. La copia anterior se conserva.',
      );
    }
  }

  @override
  Future<void> remove(String key) async {
    _check(key);
    try {
      await _remove(key.toJS).toDart;
    } catch (_) {
      throw const CorteStoreException(
        'No pudimos quitar esta copia del navegador.',
      );
    }
  }
}
