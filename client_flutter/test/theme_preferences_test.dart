import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:corte/data/corte_repository.dart';
import 'package:corte/ui/theme_preferences.dart';

const scopeA =
    'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';
const scopeB =
    'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb';

class RequestRecord {
  RequestRecord(this.method, this.path, this.headers, this.body);
  final String method, path;
  final Map<String, String> headers;
  final Object? body;
}

class FakeAdapter implements CorteHttpAdapter {
  FakeAdapter(this.answer);
  final FutureOr<CorteResponse> Function(RequestRecord) answer;

  @override
  Future<CorteResponse> request(
    String method,
    String path, {
    Map<String, String> headers = const {},
    Object? body,
  }) async => answer(RequestRecord(method, path, headers, body));

  @override
  void close() {}
}

CorteResponse response(JsonMap body) => CorteResponse(
  statusCode: 200,
  headers: const {'content-type': 'application/json'},
  bodyBytes: Uint8List.fromList(utf8.encode(jsonEncode(body))),
);

JsonMap snapshot(JsonMap preferences) => {
  'version_esquema': 1,
  'muestras': <JsonMap>[],
  'local': {'preferencias': preferences},
};

CorteRepository repository(FakeAdapter adapter, CorteDataStore store) =>
    CorteRepository(
      adapter: adapter,
      ownerScope: scopeA,
      cacheScope: scopeA,
      store: store,
    );

void main() {
  test(
    'appearance applies immediately, saves only its field and survives an offline restart',
    () async {
      final store = MemoryCorteDataStore();
      var preferences = <String, dynamic>{
        'rev': 4,
        'tema': 'claro',
        'firma': 'Conservar',
      };
      await CorteJournal(
        store,
        scopeA,
      ).guardarSnapshot(snapshot(preferences), null);
      final ack = Completer<CorteResponse>();
      JsonMap? operation;
      final adapter = FakeAdapter((request) {
        if (request.path == '/api/cloud/revision') {
          return response({'cache_scope': scopeA, 'owner_scope': scopeA});
        }
        if (request.method == 'GET') return response(preferences);
        expect(request.headers['X-Corte-Cache-Scope'], scopeA);
        operation = jsonMap((jsonMap(request.body)['ops'] as List).single);
        return ack.future;
      });
      final repo = repository(adapter, store);
      final theme = CorteThemePreferences(repo);
      await theme.load();
      final saving = theme.choose('oscuro');
      expect(theme.mode, ThemeMode.dark);
      expect(theme.busy, isTrue);
      await Future<void>.delayed(Duration.zero);
      expect(operation!['cambios'], {'rev': 4, 'tema': 'oscuro'});
      expect(operation!['op_id'], matches(RegExp(r'^[a-f0-9-]{36}$')));
      preferences = {...preferences, 'rev': 5, 'tema': 'oscuro'};
      ack.complete(
        response({
          'resultados': [
            {
              'op_id': operation!['op_id'],
              'estado': 'aplicada',
              'objeto': preferences,
            },
          ],
        }),
      );
      expect((await saving).enCola, isFalse);
      expect(preferences['firma'], 'Conservar');
      theme.dispose();
      repo.close();

      final offline = repository(
        FakeAdapter((_) {
          throw const CorteTransportException('sin_internet', 'Sin conexión');
        }),
        store,
      );
      final reopened = CorteThemePreferences(offline);
      await reopened.load();
      expect(reopened.mode, ThemeMode.dark);
      expect(reopened.loaded, isTrue);
      reopened.dispose();
      offline.close();
    },
  );

  test(
    'queued appearance survives restart and a rejected sync rolls it back for review',
    () async {
      final store = MemoryCorteDataStore();
      final preferences = <String, dynamic>{'rev': 1, 'tema': 'claro'};
      await CorteJournal(
        store,
        scopeA,
      ).guardarSnapshot(snapshot(preferences), null);
      var online = false;
      final adapter = FakeAdapter((request) {
        if (!online)
          throw const CorteTransportException('sin_internet', 'Sin conexión');
        if (request.path == '/api/cloud/revision') {
          return response({'cache_scope': scopeA, 'owner_scope': scopeA});
        }
        if (request.method == 'GET')
          return response({...preferences, 'rev': 2});
        final op = jsonMap((jsonMap(request.body)['ops'] as List).single);
        return response({
          'resultados': [
            {
              'op_id': op['op_id'],
              'estado': 'conflicto',
              'objeto': {...preferences, 'rev': 2},
            },
          ],
        });
      });
      final firstRepo = repository(adapter, store);
      final first = CorteThemePreferences(firstRepo);
      await first.load();
      expect((await first.choose('oscuro')).enCola, isTrue);
      expect(first.pending, isTrue);
      first.dispose();
      firstRepo.close();

      final secondRepo = repository(adapter, store);
      final second = CorteThemePreferences(secondRepo);
      await second.load();
      expect(second.mode, ThemeMode.dark);
      expect(second.pending, isTrue);
      await expectLater(second.choose('claro'), throwsA(isA<ErrorApi>()));
      expect(await secondRepo.opsPendientes(), hasLength(1));
      online = true;
      await secondRepo.flushOps();
      await second.load(force: true);
      expect(second.mode, ThemeMode.light);
      expect(second.pending, isFalse);
      expect(second.needsReview, isTrue);
      expect(second.error, contains('necesita revisión'));
      second.dispose();
      secondRepo.close();
    },
  );

  test('an old owner response cannot replace the new account theme', () async {
    final oldResponse = Completer<CorteResponse>();
    var calls = 0;
    final repo = repository(
      FakeAdapter((_) {
        if (calls++ == 0) return oldResponse.future;
        return response({'rev': 1, 'tema': 'claro'});
      }),
      MemoryCorteDataStore(),
    );
    final theme = CorteThemePreferences(repo);
    final oldLoad = theme.load();
    repo.setScopes(ownerScope: scopeB, cacheScope: scopeB);
    theme.resetForScope();
    await theme.load();
    oldResponse.complete(response({'rev': 9, 'tema': 'oscuro'}));
    await oldLoad;
    expect(theme.mode, ThemeMode.light);
    repo.setScopes();
    theme.resetForScope();
    expect(theme.mode, ThemeMode.system);
    expect(theme.loaded, isFalse);
    theme.dispose();
    repo.close();
  });
}
