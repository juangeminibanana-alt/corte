import 'dart:async';
import 'dart:io';

import 'package:corte/platform/data_store.dart';
import 'package:corte/platform/data_store_native.dart' as native_store;
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('Android opens an existing offline journal in filesDir', (
    tester,
  ) async {
    final messenger =
        TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    const native = MethodChannel('corte/native');
    const startup = MethodChannel('corte/startup');
    var directoryLookups = 0;
    await tester.runAsync(() async {
      final files = await Directory.systemTemp.createTemp('cutgc-files-');
      try {
        final root = await Directory.fromUri(
          files.uri.resolve('corte_flutter_data/'),
        ).create();
        final key = 'corte.data.${'a' * 64}.outbox';
        final saved = File.fromUri(root.uri.resolve('$key.json'));
        await saved.writeAsString('{"pending":1}');
        messenger.setMockMethodCallHandler(native, (call) async {
          expect(call.method, 'filesDirectory');
          directoryLookups++;
          return files.path;
        });
        messenger.setMockMethodCallHandler(startup, (_) async => null);
        final store = native_store.createStore(isAndroid: true);
        expect(await store.read(key), '{"pending":1}');
        await store.write(key, '{"pending":2}');
        expect(await saved.readAsString(), '{"pending":2}');
        expect(directoryLookups, 1);
      } finally {
        messenger.setMockMethodCallHandler(native, null);
        messenger.setMockMethodCallHandler(startup, null);
        await files.delete(recursive: true);
      }
    });
  }, variant: const TargetPlatformVariant({TargetPlatform.android}));

  testWidgets(
    'a failed shared Android lookup can be retried on the same store',
    (tester) async {
      final messenger =
          TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
      const native = MethodChannel('corte/native');
      const startup = MethodChannel('corte/startup');
      final outbox = 'corte.data.${'a' * 64}.outbox';
      final snapshot = 'corte.data.${'a' * 64}.snapshot';
      var directoryLookups = 0;

      await tester.runAsync(() async {
        final files = await Directory.systemTemp.createTemp('cutgc-retry-');
        final failedLookup = Completer<String?>();
        final lookupStarted = Completer<void>();
        try {
          messenger.setMockMethodCallHandler(native, (call) async {
            expect(call.method, 'filesDirectory');
            directoryLookups++;
            if (directoryLookups == 1) {
              lookupStarted.complete();
              return failedLookup.future;
            }
            return files.path;
          });
          messenger.setMockMethodCallHandler(startup, (_) async => null);
          final store = native_store.createStore(isAndroid: true);
          final first = expectLater(
            store.read(outbox),
            throwsA(isA<CorteStoreException>()),
          );
          final second = expectLater(
            store.read(snapshot),
            throwsA(isA<CorteStoreException>()),
          );
          await lookupStarted.future;
          failedLookup.complete(null);
          await Future.wait([first, second]);
          expect(directoryLookups, 1);

          await store.write(outbox, '{"pending":2}');
          expect(await store.read(outbox), '{"pending":2}');
          expect(directoryLookups, 2);
        } finally {
          messenger.setMockMethodCallHandler(native, null);
          messenger.setMockMethodCallHandler(startup, null);
          await files.delete(recursive: true);
        }
      });
    },
    variant: const TargetPlatformVariant({TargetPlatform.android}),
  );
}
