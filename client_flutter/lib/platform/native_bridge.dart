import 'package:flutter/services.dart';

const deviceSessionKey = 'corte.nube.dispositivo.v1';
const pendingAuthorizationKey = 'corte.nube.autorizacion.v1';
const sessionOwnerKey = 'corte.nube.propietario.v1';

abstract interface class CorteCredentialStore {
  Future<String?> read(String key);
  Future<void> write(String key, String value);
  Future<void> delete(String key);
}

/// Sólo lo utiliza auth nativo. No exporta credenciales al estado de los widgets.
class CorteNativeBridge implements CorteCredentialStore {
  const CorteNativeBridge({
    MethodChannel channel = const MethodChannel('corte/native'),
  }) : _channel = channel;
  final MethodChannel _channel;
  static const _keys = {
    deviceSessionKey,
    pendingAuthorizationKey,
    sessionOwnerKey,
  };
  static const _legacyNames = {
    'snapshot',
    'meta',
    'outbox',
    'archive_snapshot',
    'archive_outbox',
  };

  void _checkKey(String key) {
    if (!_keys.contains(key)) {
      throw ArgumentError('Entrada segura no permitida.');
    }
  }

  @override
  Future<String?> read(String key) {
    _checkKey(key);
    return _channel.invokeMethod<String>('secureRead', {'key': key});
  }

  @override
  Future<void> write(String key, String value) {
    _checkKey(key);
    return _channel.invokeMethod<void>('secureWrite', {
      'key': key,
      'value': value,
    });
  }

  @override
  Future<void> delete(String key) {
    _checkKey(key);
    return _channel.invokeMethod<void>('secureDelete', {'key': key});
  }

  Future<Map<String, Object?>> legacyInfo() async {
    final result = await _channel.invokeMapMethod<String, Object?>(
      'legacyInfo',
    );
    return Map.unmodifiable(result ?? const <String, Object?>{});
  }

  Future<Uint8List?> legacyRead(String name) {
    if (!_legacyNames.contains(name)) {
      throw ArgumentError('Archivo anterior no permitido.');
    }
    return _channel.invokeMethod<Uint8List>('legacyRead', {'name': name});
  }
}
