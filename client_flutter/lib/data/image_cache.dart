import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:crypto/crypto.dart';

import 'corte_store.dart';

/// Private offline files, never a browser/HTTP cache. Identity includes the
/// opaque account/creator scope, image route, source version and size variant.
class CorteImageCache {
  CorteImageCache(
    this.store, {
    int maxBytes = 128 * 1024 * 1024,
    int maxEntries = 500,
  }) : maxBytes = maxBytes.clamp(1, 128 * 1024 * 1024),
       maxEntries = maxEntries.clamp(1, 500);

  final CorteDataStore store;
  final int maxBytes;
  final int maxEntries;
  Future<void> _tail = Future<void>.value();
  static const _imageLimit = 10 * 1024 * 1024;

  Future<T> _serial<T>(Future<T> Function() action) {
    final next = _tail.then((_) => action());
    _tail = next.then<void>((_) {}, onError: (Object _) {});
    return next;
  }

  Future<Uint8List?> read(
    String scope,
    String path, {
    bool allowSmFallback = false,
  }) => _serial(() async {
    final image = _ImageRoute.parse(path);
    if (!_scope(scope) || image == null) return null;
    final index = await _load(scope);
    final exact = await _read(scope, image, index);
    if (exact != null || !allowSmFallback || image.variant == 'sm') {
      return exact;
    }
    // This changes only the rendition; never the source, kind, ID or version.
    return _read(scope, image.small, index);
  });

  /// A response with v=0, an unproven ETag, or a non-image MIME stays online
  /// only. Cache-Control no-store still applies to HTTP; these are app-private
  /// offline documents protected by the authenticated account gate.
  Future<void> put(
    String scope,
    String path,
    Uint8List bytes,
    Map<String, String> headers,
  ) => _serial(() async {
    final image = _ImageRoute.parse(path);
    final normalizedHeaders = {
      for (final e in headers.entries) e.key.toLowerCase(): e.value,
    };
    final mime = normalizedHeaders['content-type']
        ?.split(';')
        .first
        .trim()
        .toLowerCase();
    if (!_scope(scope) ||
        image == null ||
        normalizedHeaders['etag'] != image.etag ||
        mime == null ||
        !mime.startsWith('image/') ||
        mime.length > 128 ||
        bytes.isEmpty ||
        bytes.length > _imageLimit ||
        bytes.length > maxBytes) {
      return;
    }
    final index = await _load(scope);
    if (await _read(scope, image, index) != null) return;
    final payload = jsonEncode({
      'version': 1,
      'path': image.path,
      'etag': image.etag,
      'mime': mime,
      'size': bytes.length,
      'checksum': sha256.convert(bytes).toString(),
      'data': base64Encode(bytes),
    });
    final storedSize = utf8.encode(payload).length;
    if (storedSize > maxBytes) return;

    while (index.entries.length >= maxEntries ||
        index.totalBytes + storedSize > maxBytes) {
      final oldest = index.entries.values.reduce(
        (a, b) => a.used <= b.used ? a : b,
      );
      // Delete before committing its removal. A crash may leave a missing
      // indexed file, which is repairable, rather than an untracked orphan.
      await store.remove(_fileKey(scope, oldest.hash));
      index.entries.remove(oldest.hash);
    }
    final hash = image.hash;
    index.entries[hash] = _Entry(
      image.path,
      bytes.length,
      storedSize,
      ++index.clock,
    );
    // Reserve the entry durably before writing its payload. Failed/crashed
    // writes remain tracked and can be repaired or evicted on the next access.
    await _save(scope, index);
    try {
      await store.write(_fileKey(scope, hash), payload);
    } catch (_) {
      index.entries.remove(hash);
      try {
        await _save(scope, index);
      } catch (_) {
        /* Reservation is bounded. */
      }
      rethrow;
    }
  });

  Future<Uint8List?> _read(
    String scope,
    _ImageRoute image,
    _Index index,
  ) async {
    final entry = index.entries[image.hash];
    if (entry == null) return null;
    final raw = await store.read(_fileKey(scope, image.hash));
    Uint8List? bytes;
    if (raw != null && raw.length <= 15 * 1024 * 1024) {
      try {
        final value = jsonDecode(raw);
        if (value is Map<String, dynamic> &&
            value['version'] == 1 &&
            value['path'] == image.path &&
            value['etag'] == image.etag &&
            value['size'] == entry.size &&
            value['mime'] is String &&
            (value['mime'] as String).startsWith('image/') &&
            value['data'] is String) {
          final decoded = base64Decode(value['data'] as String);
          if (decoded.length == entry.size &&
              decoded.length <= _imageLimit &&
              sha256.convert(decoded).toString() == value['checksum']) {
            bytes = decoded;
          }
        }
      } on FormatException {
        /* A partial/corrupt file cannot become a cover. */
      }
    }
    if (bytes == null) {
      await store.remove(_fileKey(scope, image.hash));
      index.entries.remove(image.hash);
    } else {
      index.entries[image.hash] = _Entry(
        entry.path,
        entry.size,
        entry.storedSize,
        ++index.clock,
      );
    }
    if (bytes == null) {
      await _save(scope, index);
    } else {
      try {
        await _save(scope, index);
      } catch (_) {
        // A failed access-time update must not hide a previously verified
        // offline photo. Its committed index still refers to this same file.
      }
    }
    return bytes;
  }

  Future<_Index> _load(String scope) async {
    final raw = await store.read(_indexKey(scope));
    if (raw == null) return _Index();
    try {
      final value = jsonDecode(raw);
      if (value is! Map<String, dynamic> ||
          value['version'] != 1 ||
          value['clock'] is! int ||
          (value['clock'] as int) < 0 ||
          value['entries'] is! List ||
          (value['entries'] as List).length > 500) {
        throw const FormatException();
      }
      final result = _Index()..clock = value['clock'] as int;
      for (final item in value['entries'] as List) {
        if (item is! Map<String, dynamic> ||
            item['path'] is! String ||
            item['size'] is! int ||
            item['stored_size'] is! int ||
            item['used'] is! int) {
          throw const FormatException();
        }
        final route = _ImageRoute.parse(item['path'] as String);
        final size = item['size'] as int;
        final storedSize = item['stored_size'] as int;
        final used = item['used'] as int;
        if (route == null ||
            size <= 0 ||
            size > _imageLimit ||
            storedSize < size ||
            storedSize > 15 * 1024 * 1024 ||
            used < 0 ||
            used > result.clock ||
            result.entries.containsKey(route.hash)) {
          throw const FormatException();
        }
        result.entries[route.hash] = _Entry(route.path, size, storedSize, used);
      }
      if (result.totalBytes > 128 * 1024 * 1024) throw const FormatException();
      return result;
    } on FormatException {
      // Do not overwrite a broken index and orphan every referenced image.
      // Other scopes and the snapshot/outbox documents remain untouched.
      throw const CorteImageCacheException(
        'No pudimos leer las fotos guardadas.',
      );
    }
  }

  Future<void> _save(String scope, _Index index) => store.write(
    _indexKey(scope),
    jsonEncode({
      'version': 1,
      'clock': index.clock,
      'entries': [
        for (final e in index.entries.values)
          {
            'path': e.path,
            'size': e.size,
            'stored_size': e.storedSize,
            'used': e.used,
          },
      ],
    }),
  );

  static bool _scope(String scope) => RegExp(r'^[a-f0-9]{64}$').hasMatch(scope);
  static String _indexKey(String scope) => 'corte.data.$scope.images';
  static String _fileKey(String scope, String hash) =>
      'corte.data.$scope.image.$hash';
}

class CorteImageCacheException implements Exception {
  const CorteImageCacheException(this.message);
  final String message;
  @override
  String toString() => message;
}

class _Index {
  int clock = 0;
  final entries = <String, _Entry>{};
  int get totalBytes =>
      entries.values.fold(0, (total, e) => total + e.storedSize);
}

class _Entry {
  const _Entry(this.path, this.size, this.storedSize, this.used);
  final String path;
  final int size;
  final int storedSize;
  final int used;
  String get hash => sha256.convert(utf8.encode(path)).toString();
}

class _ImageRoute {
  const _ImageRoute(this.source, this.version, this.variant);
  final String source;
  final String version;
  final String? variant;
  String get path =>
      '$source?v=$version${variant == null ? '' : '&t=$variant'}';
  String get etag => '"$version${variant == null ? '' : '-$variant'}"';
  String get hash => sha256.convert(utf8.encode(path)).toString();
  _ImageRoute get small => _ImageRoute(source, version, 'sm');

  static _ImageRoute? parse(String path) {
    // Canonical source routes only; no aliases, encoded separators, fragments,
    // credentials or unrelated query parameters can share an offline identity.
    final match = RegExp(
      r'^(/img/(?:(?:p|a|m)/[A-Za-z0-9_-]{1,64}|v/[0-9]{1,25}|g/[0-9]{1,25}-(?:[0-9]|1[01])))\?(.+)$',
    ).firstMatch(path);
    if (match == null) return null;
    final parameters = <String, String>{};
    for (final pair in match.group(2)!.split('&')) {
      final parts = pair.split('=');
      if (parts.length != 2 ||
          parameters.containsKey(parts[0]) ||
          !{'v', 't'}.contains(parts[0])) {
        return null;
      }
      parameters[parts[0]] = parts[1];
    }
    final version = parameters['v'];
    final variant = parameters['t'];
    if (version == null ||
        !RegExp(r'^[a-f0-9]{8}$').hasMatch(version) ||
        (variant != null && !{'xs', 'sm', 'md'}.contains(variant))) {
      return null;
    }
    return _ImageRoute(match.group(1)!, version, variant);
  }
}
