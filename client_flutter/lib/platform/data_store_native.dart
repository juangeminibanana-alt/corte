import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:path_provider/path_provider.dart';

import 'android_startup.dart';
import 'data_store.dart';
import 'native_bridge.dart';

CorteDataStore createStore({bool? isAndroid}) =>
    _NativeStore(isAndroid ?? Platform.isAndroid);

class _NativeStore implements CorteDataStore {
  _NativeStore(this._isAndroid);

  final bool _isAndroid;
  final _tails = <String, Future<void>>{};
  Future<Directory>? _directory;
  Future<T> _serial<T>(String key, Future<T> Function() action) {
    if (!validCorteDataKey(key)) {
      throw const CorteStoreException('La clave de la copia no es válida.');
    }
    final next = (_tails[key] ?? Future<void>.value()).then((_) => action());
    _tails[key] = next.then<void>((_) {}, onError: (Object _) {});
    return next;
  }

  Future<Directory> _root() => _directory ??= () async {
    try {
      return await _openRoot();
    } catch (_) {
      _directory = null;
      rethrow;
    }
  }();

  Future<Directory> _openRoot() async {
    // Keep the same Android filesDir as path_provider while avoiding its
    // Dart-to-JNI calls on the first read of the authenticated journal.
    final String parent;
    if (_isAndroid) {
      CorteAndroidStartup.mark('local_directory_open');
      final path = await const CorteNativeBridge().filesDirectory();
      if (path == null || path.isEmpty) {
        throw const CorteStoreException(
          'Android no devolvió la carpeta de CUTGC.',
        );
      }
      parent = path;
    } else {
      parent = (await getApplicationSupportDirectory()).path;
    }
    final root = await Directory(
      '$parent${Platform.pathSeparator}corte_flutter_data',
    ).create(recursive: true);
    if (_isAndroid) CorteAndroidStartup.mark('local_directory_ready');
    return root;
  }

  Future<File> _file(String key) async =>
      File('${(await _root()).path}${Platform.pathSeparator}$key.json');

  @override
  Future<String?> read(String key) => _serial(key, () async {
    try {
      final file = await _file(key);
      if (!await file.exists()) return null;
      if (await file.length() > 32 * 1024 * 1024) {
        throw const CorteStoreException('La copia supera el límite permitido.');
      }
      return await file.readAsString();
    } on CorteStoreException {
      rethrow;
    } catch (_) {
      throw const CorteStoreException('No pudimos leer la copia guardada.');
    }
  });

  @override
  Future<void> write(String key, String value) => _serial(key, () async {
    if (utf8.encode(value).length > 32 * 1024 * 1024) {
      throw const CorteStoreException('La copia supera el límite permitido.');
    }
    File? temporary;
    try {
      final destination = await _file(key);
      temporary = File(
        '${destination.path}.${DateTime.now().microsecondsSinceEpoch}.$pid.tmp',
      );
      await temporary.writeAsString(value, flush: true);
      // Same directory/volume; never delete the previous committed copy first.
      await temporary.rename(destination.path);
    } catch (_) {
      throw const CorteStoreException(
        'No pudimos guardar el cambio. La copia anterior se conserva.',
      );
    } finally {
      if (temporary != null) {
        try {
          if (await temporary.exists()) await temporary.delete();
        } catch (_) {}
      }
    }
  });

  @override
  Future<void> remove(String key) => _serial(key, () async {
    try {
      final file = await _file(key);
      if (await file.exists()) await file.delete();
    } catch (_) {
      throw const CorteStoreException('No pudimos quitar esta copia.');
    }
  });
}
