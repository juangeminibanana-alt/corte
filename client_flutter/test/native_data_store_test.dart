import 'dart:io';

import 'package:corte/platform/data_store.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets(
    'Android opens an existing offline journal in filesDir',
    (tester) async {
      final messenger =
          TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
      const native = MethodChannel('corte/native');
      const startup = MethodChannel('corte/startup');
      var directoryLookups = 0;
      await tester.runAsync(() async {
        final files = await Directory.systemTemp.createTemp('cutgc-files-');
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
        try {
          final store = await createCorteDataStore();
          expect(await store.read(key), '{"pending":1}');
          await store.write(key, '{"pending":2}');
          expect(await saved.readAsString(), '{"pending":2}');
          expect(directoryLookups, 1);
        } finally {
          messenger.setMockMethodCallHandler(native, null);
          messenger.setMockMethodCallHandler(startup, null);
          await saved.delete();
          await root.delete();
          await files.delete();
        }
      });
    },
    variant: const TargetPlatformVariant({TargetPlatform.android}),
  );
}
