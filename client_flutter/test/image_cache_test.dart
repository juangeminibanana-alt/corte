import 'dart:convert';
import 'dart:typed_data';

import 'package:crypto/crypto.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:corte/data/image_cache.dart';
import 'package:corte/platform/data_store.dart';

final scopeA = List.filled(64, 'a').join();
final scopeB = List.filled(64, 'b').join();
const path = '/img/p/100?v=deadbeef&t=sm';
final bytes = Uint8List.fromList([1, 2, 3, 4]);
Map<String, String> headers([String tag = '"deadbeef-sm"']) => {
  'ETag': tag,
  'Content-Type': 'image/webp; charset=binary',
  'Cache-Control': 'private, no-store',
};
String fileKey(String scope, String route) =>
    'corte.data.$scope.image.${sha256.convert(utf8.encode(route))}';

class RecordingStore implements CorteDataStore {
  final values = <String, String>{};
  final removed = <String>[];
  String? failWrite;
  @override
  Future<String?> read(String key) async => values[key];
  @override
  Future<void> write(String key, String value) async {
    if (key == failWrite) throw StateError('synthetic write failure');
    values[key] = value;
  }

  @override
  Future<void> remove(String key) async {
    removed.add(key);
    values.remove(key);
  }
}

void main() {
  test(
    'private versioned photo round-trips without HTTP cache and isolates owner/creator',
    () async {
      final store = RecordingStore();
      final cache = CorteImageCache(store);
      await cache.put(scopeA, path, bytes, headers());
      expect(await cache.read(scopeA, path), bytes);
      expect(await cache.read(scopeB, path), isNull);
      expect(store.values.keys.every(validCorteDataKey), isTrue);
      expect(validCorteDataKey('corte.data.$scopeA.image.not-a-hash'), isFalse);
      expect(validCorteDataKey('corte.data.$scopeA.secret'), isFalse);
    },
  );

  test(
    'v0, ambiguous/foreign routes, mismatched or weak ETags and HTML never persist',
    () async {
      final store = RecordingStore();
      final cache = CorteImageCache(store);
      for (final route in [
        '/img/p/100?v=0',
        '/img/p/100',
        '/img/p/100?v=deadbeef&v=deadbeef',
        '/img/p/100?v=deadbeef&t=sm&x=1',
        '/img/p/100%2F200?v=deadbeef&t=sm',
        'https://example.test$path',
        '/img/../p/100?v=deadbeef&t=sm',
        '/img/g/100-12?v=deadbeef&t=sm',
        '$path#fragment',
      ]) {
        await cache.put(scopeA, route, bytes, headers());
      }
      for (final tag in [
        'W/"deadbeef-sm"',
        '"cafebabe-sm"',
        '"deadbeef-md"',
        '',
      ]) {
        await cache.put(scopeA, path, bytes, headers(tag));
      }
      await cache.put(scopeA, path, bytes, {
        ...headers(),
        'Content-Type': 'text/html',
      });
      expect(store.values, isEmpty);
    },
  );

  test(
    'only opt-in sm fallback with identical source route and version is allowed',
    () async {
      final cache = CorteImageCache(RecordingStore());
      await cache.put(scopeA, path, bytes, headers());
      const requested = '/img/p/100?v=deadbeef&t=md';
      expect(await cache.read(scopeA, requested), isNull);
      expect(await cache.read(scopeA, requested, allowSmFallback: true), bytes);
      for (final route in [
        '/img/v/100?v=deadbeef&t=md',
        '/img/p/101?v=deadbeef&t=md',
        '/img/p/100?v=cafebabe&t=md',
        '/img/g/100-0?v=deadbeef&t=md',
      ]) {
        expect(await cache.read(scopeA, route, allowSmFallback: true), isNull);
      }
      final large = Uint8List.fromList([5, 6]);
      await cache.put(scopeA, requested, large, headers('"deadbeef-md"'));
      expect(await cache.read(scopeA, requested, allowSmFallback: true), large);
    },
  );

  test(
    'canonical query order and gallery index 11 retain their precise identity',
    () async {
      final cache = CorteImageCache(RecordingStore());
      await cache.put(
        scopeA,
        '/img/g/100-11?t=sm&v=deadbeef',
        bytes,
        headers(),
      );
      expect(await cache.read(scopeA, '/img/g/100-11?v=deadbeef&t=sm'), bytes);
      expect(await cache.read(scopeA, '/img/g/100-1?v=deadbeef&t=sm'), isNull);
    },
  );

  test(
    'LRU evicts only image entries in this exact scope and obeys byte/count bounds',
    () async {
      final store = RecordingStore();
      final cache = CorteImageCache(store, maxEntries: 2, maxBytes: 4096);
      store.values['corte.data.$scopeA.snapshot'] = 'preserved snapshot';
      store.values['corte.data.$scopeA.outbox'] = 'preserved queue';
      await cache.put(scopeB, path, bytes, headers());
      await cache.put(scopeA, path, bytes, headers());
      const second = '/img/p/200?v=deadbeef&t=sm';
      const third = '/img/p/300?v=deadbeef&t=sm';
      await cache.put(scopeA, second, bytes, headers());
      await cache.read(
        scopeA,
        path,
      ); // The second photo is now least recently used.
      await cache.put(scopeA, third, bytes, headers());
      expect(await cache.read(scopeA, path), bytes);
      expect(await cache.read(scopeA, second), isNull);
      expect(await cache.read(scopeA, third), bytes);
      expect(await cache.read(scopeB, path), bytes);
      expect(store.values['corte.data.$scopeA.snapshot'], 'preserved snapshot');
      expect(store.values['corte.data.$scopeA.outbox'], 'preserved queue');
      expect(store.removed, [fileKey(scopeA, second)]);
      final index =
          jsonDecode(store.values['corte.data.$scopeA.images']!) as Map;
      expect((index['entries'] as List).length, 2);
    },
  );

  test(
    'corrupt payload is removed instead of displaying unrelated bytes',
    () async {
      final store = RecordingStore();
      final cache = CorteImageCache(store);
      await cache.put(scopeA, path, bytes, headers());
      final key = fileKey(scopeA, path);
      final payload = jsonDecode(store.values[key]!) as Map<String, dynamic>;
      payload['data'] = base64Encode([4, 3, 2, 1]);
      store.values[key] = jsonEncode(payload);
      expect(await cache.read(scopeA, path), isNull);
      expect(store.values.containsKey(key), isFalse);
    },
  );

  test(
    'failed payload write leaves no untracked file and preserves unrelated documents',
    () async {
      final store = RecordingStore()..failWrite = fileKey(scopeA, path);
      final cache = CorteImageCache(store);
      store.values['corte.data.$scopeA.outbox'] = 'original';
      await expectLater(
        cache.put(scopeA, path, bytes, headers()),
        throwsStateError,
      );
      final index =
          jsonDecode(store.values['corte.data.$scopeA.images']!) as Map;
      expect(index['entries'], isEmpty);
      expect(store.values.containsKey(fileKey(scopeA, path)), isFalse);
      expect(store.values['corte.data.$scopeA.outbox'], 'original');
    },
  );

  test(
    'malformed index cannot be overwritten and orphan old images silently',
    () async {
      final store = RecordingStore();
      const raw = '{broken';
      store.values['corte.data.$scopeA.images'] = raw;
      final cache = CorteImageCache(store);
      await expectLater(
        cache.put(scopeA, path, bytes, headers()),
        throwsA(isA<CorteImageCacheException>()),
      );
      expect(store.values['corte.data.$scopeA.images'], raw);
    },
  );

  test('byte budget includes durable encoding and metadata', () async {
    final store = RecordingStore();
    final cache = CorteImageCache(store, maxEntries: 10, maxBytes: 4096);
    const second = '/img/p/200?v=deadbeef&t=sm';
    await cache.put(scopeA, path, bytes, headers());
    final limit = utf8.encode(store.values[fileKey(scopeA, path)]!).length + 1;
    final bounded = CorteImageCache(store, maxEntries: 10, maxBytes: limit);
    await bounded.put(scopeA, second, bytes, headers());
    final index = jsonDecode(store.values['corte.data.$scopeA.images']!) as Map;
    final entries = index['entries'] as List;
    expect(entries.length, 1);
    expect(
      entries.fold<int>(0, (sum, e) => sum + (e['stored_size'] as int)),
      lessThanOrEqualTo(limit),
    );
    expect(await cache.read(scopeA, path), isNull);
    expect(await cache.read(scopeA, second), bytes);
  });

  test(
    'existing valid offline photo stays readable if its LRU update cannot be written',
    () async {
      final store = RecordingStore();
      final cache = CorteImageCache(store);
      await cache.put(scopeA, path, bytes, headers());
      store.failWrite = 'corte.data.$scopeA.images';
      expect(await cache.read(scopeA, path), bytes);
    },
  );

  test(
    'concurrent inserts preserve both entries rather than racing index updates',
    () async {
      final cache = CorteImageCache(RecordingStore());
      const second = '/img/v/200?v=deadbeef&t=sm';
      await Future.wait([
        cache.put(scopeA, path, bytes, headers()),
        cache.put(scopeA, second, bytes, headers()),
      ]);
      expect(await cache.read(scopeA, path), bytes);
      expect(await cache.read(scopeA, second), bytes);
    },
  );
}
