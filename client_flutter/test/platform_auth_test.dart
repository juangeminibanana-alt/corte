import 'dart:async';
import 'dart:convert';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:corte/auth/auth_controller.dart';
import 'package:corte/auth/web_sign_in.dart';
import 'package:corte/platform/corte_runtime.dart';
import 'package:corte/platform/corte_transport.dart';
import 'package:corte/platform/external_links.dart';
import 'package:corte/platform/native_bridge.dart';

const origin = corteCloudOrigin;
const now = 1795000000;
String repeated(String value, int n) => List.filled(n, value).join();
String token(String value) => 'corte_native_v1_${repeated(value, 43)}';
final cacheScope = repeated('c', 64);
final runtime = CorteRuntime(platform: 'android', baseUri: Uri.parse(origin));
http.Response jsonResponse(
  Object value, [
  int status = 200,
  Map<String, String> headers = const {},
]) => http.Response(
  jsonEncode(value),
  status,
  headers: {'content-type': 'application/json', ...headers},
);
Map<String, Object?> device([String marker = 'a', bool owner = true]) => {
  'token': token(marker),
  'device_id': repeated('d', 24),
  'expires_at': now + 3600,
  if (owner) 'owner_uid': 'synthetic-owner',
  if (owner) 'cache_scope': cacheScope,
};
Map<String, Object?> session() => {
  'authenticated': true,
  'device_id': repeated('d', 24),
  'expires_at': now + 3600,
  'owner': {'uid': 'synthetic-owner', 'email': 'synthetic@example.test'},
  'owner_scope': repeated('b', 64),
  'cache_scope': cacheScope,
  'tiktok_open_id': 'synthetic-private-creator',
};
Map<String, Object?> startResponse() => {
  'request_id': repeated('r', 43),
  'user_code': 'ABCD-EFGH',
  'verification_uri': '$origin/conectar-dispositivo?codigo=ABCD-EFGH',
  'expires_in': 600,
  'interval': 3,
};
Map<String, Object?> grant([String marker = 'a']) => {
  'estado': 'autorizado',
  ...device(marker),
  'owner': {'uid': 'synthetic-owner', 'email': 'synthetic@example.test'},
};

class TestStore implements CorteCredentialStore {
  final values = <String, String>{};
  bool readFails = false;
  Future<void> Function(String, String)? beforeWrite;
  @override
  Future<String?> read(String key) async {
    if (readFails) throw StateError('synthetic store unavailable');
    return values[key];
  }

  @override
  Future<void> write(String key, String value) async {
    await beforeWrite?.call(key, value);
    values[key] = value;
  }

  @override
  Future<void> delete(String key) async {
    values.remove(key);
  }
}

class TestLinks implements CorteExternalLinks {
  final opened = <Uri>[];
  bool Function()? beforeOpen;
  @override
  Future<bool> open(Uri uri) async {
    expect(beforeOpen?.call() ?? true, isTrue);
    opened.add(uri);
    return true;
  }
}

class TestWebAuth implements CorteWebSignIn {
  @override
  Future<bool> finishRedirect() async => false;
  @override
  Future<void> redirectSignIn() async {}
  @override
  Future<bool> signIn() async => true;
  @override
  Future<void> signOut() async {}
}

CorteAuthController auth(
  TestStore store,
  MockClient client, {
  TestLinks? links,
  String platform = 'android',
  Future<String?> Function()? androidSignIn,
}) => CorteAuthController(
  runtime: CorteRuntime(platform: platform, baseUri: Uri.parse(origin)),
  credentials: store,
  client: client,
  links: links ?? TestLinks(),
  androidSignIn: androidSignIn,
  clock: () => DateTime.fromMillisecondsSinceEpoch(now * 1000, isUtc: true),
);

void main() {
  test(
    'connection notifications deduplicate healthy requests and retain opaque scopes on web',
    () async {
      for (final isWeb in [false, true]) {
        var online = true;
        final store = TestStore()
          ..values[deviceSessionKey] = jsonEncode(device());
        final controller = CorteAuthController(
          runtime: CorteRuntime(
            platform: isWeb ? 'web' : 'android',
            baseUri: Uri.parse(origin),
          ),
          credentials: store,
          webSignIn: TestWebAuth(),
          clock: () =>
              DateTime.fromMillisecondsSinceEpoch(now * 1000, isUtc: true),
          client: MockClient((r) async {
            if (!online) {
              throw http.ClientException('synthetic network unavailable');
            }
            if (isWeb && r.url.path == '/api/cloud/session') {
              return jsonResponse({
                'cloud': true,
                'authenticated': true,
                'owner_scope': repeated('b', 64),
                'cache_scope': cacheScope,
              });
            }
            return jsonResponse(session());
          }),
        );
        addTearDown(controller.dispose);
        await controller.initialize();
        final owner = controller.state.ownerScope;
        var changes = 0;
        controller.addListener(() => changes++);
        for (var i = 0; i < 3; i++) {
          await controller.transport.request('GET', '/api/example');
        }
        expect(changes, 0);
        online = false;
        for (var i = 0; i < 2; i++) {
          await expectLater(
            controller.transport.request('GET', '/api/example'),
            throwsA(isA<CorteTransportException>()),
          );
        }
        expect(changes, 1);
        expect(controller.state.offline, isTrue);
        expect(controller.state.ownerScope, owner);
        expect(controller.state.cacheScope, cacheScope);
        online = true;
        await controller.transport.request('GET', '/api/example');
        expect(changes, 2);
        expect(controller.state.connected, isTrue);
      }
    },
  );

  test(
    'resume retries unavailable secure storage before starting any authorization',
    () async {
      final store = TestStore()..readFails = true;
      var requests = 0;
      final controller = auth(
        store,
        MockClient((_) async {
          requests++;
          return jsonResponse(startResponse());
        }),
        platform: 'windows',
      );
      addTearDown(controller.dispose);
      await controller.initialize();
      expect(controller.state.phase.name, 'error');
      await controller.signIn();
      expect(requests, 0);
      store.readFails = false;
      await controller.resume();
      expect(controller.state.phase.name, 'signedOut');
      await controller.signIn();
      expect(requests, 1);
      expect(controller.state.phase.name, 'awaitingApproval');
    },
  );
  TestWidgetsFlutterBinding.ensureInitialized();

  test(
    'transport uses fixed origin, private bearer and keeps query and byte/status/header contracts',
    () async {
      final transport = CorteTransport(
        runtime: runtime,
        readBearer: () async => token('a'),
        client: MockClient((r) async {
          expect(r.url.origin, origin);
          expect(r.url.queryParameters['q'], 'Azul / M');
          expect(r.headers['Authorization'], 'Bearer ${token('a')}');
          expect(r.headers['Origin'], origin);
          expect(r.headers['X-CH-Hub'], '1');
          expect(r.followRedirects, isFalse);
          return jsonResponse({'ok': true}, 202, {'ETag': 'synthetic-tag'});
        }),
      );
      final response = await transport.request(
        'GET',
        '/api/productos/100?q=Azul%20%2F%20M',
      );
      expect(response.statusCode, 202);
      expect(response.headers['etag'], 'synthetic-tag');
      expect(jsonDecode(utf8.decode(response.bodyBytes)), {'ok': true});
      transport.close();
    },
  );

  test(
    'transport rejects authorities and normalized/encoded path traversal before HTTP',
    () async {
      var calls = 0;
      final transport = CorteTransport(
        runtime: runtime,
        client: MockClient((_) async {
          calls++;
          return jsonResponse({});
        }),
      );
      for (final path in [
        'https://evil.example/api/session',
        '//evil.example/api/session',
        '/api/../api/native/session',
        '/api/%2e%2e/api/session',
        '/api/a%2fb',
        '/api/a\\b',
        '/api/session#fragment',
      ]) {
        await expectLater(
          transport.request('GET', path),
          throwsA(isA<CorteTransportException>()),
        );
      }
      expect(calls, 0);
      transport.close();
    },
  );

  test(
    'device authorization routes omit bearer; business errors never expire the native session',
    () async {
      var invalidated = 0;
      final transport = CorteTransport(
        runtime: runtime,
        readBearer: () async => token('a'),
        onNativeInvalidSession: (_) async {
          invalidated++;
        },
        client: MockClient((r) async {
          if (r.url.path.startsWith('/api/native/auth/')) {
            expect(r.headers.containsKey('Authorization'), isFalse);
            return jsonResponse({'estado': 'pendiente'}, 202);
          }
          return jsonResponse({
            'error': {
              'codigo': r.url.path.endsWith('expired')
                  ? 'sesion_nativa_invalida'
                  : 'sin_permiso',
            },
          }, r.url.path.endsWith('forbidden') ? 403 : 401);
        }),
      );
      await transport.request(
        'POST',
        '/api/native/auth/start',
        body: {'platform': 'android'},
      );
      await transport.request(
        'POST',
        '/api/native/auth/poll',
        body: {'request_id': 'synthetic'},
      );
      await transport.request(
        'POST',
        '/api/native/auth/google',
        body: {'id_token': 'synthetic'},
      );
      await transport.request('GET', '/api/forbidden');
      await transport.request('GET', '/api/business');
      expect(invalidated, 0);
      await transport.request('GET', '/api/expired');
      expect(invalidated, 1);
      transport.close();
    },
  );

  test(
    'cancel and response limit are bounded, and callers cannot inject Authorization',
    () async {
      final transport = CorteTransport(
        runtime: runtime,
        client: MockClient((_) async => http.Response(repeated('x', 100), 200)),
      );
      final cancel = CorteCancelToken()..cancel();
      await expectLater(
        transport.request('GET', '/api/session', cancelToken: cancel),
        throwsA(isA<CorteTransportException>()),
      );
      await expectLater(
        transport.request('GET', '/api/session', maxResponseBytes: 10),
        throwsA(isA<CorteTransportException>()),
      );
      await expectLater(
        transport.request(
          'GET',
          '/api/session',
          headers: {'Authorization': 'forbidden'},
        ),
        throwsA(isA<CorteTransportException>()),
      );
      transport.close();
    },
  );

  test(
    'native import privately obtains creator and returns only the import response',
    () async {
      final calls = <String>[];
      final transport = CorteTransport(
        runtime: runtime,
        readBearer: () async => token('a'),
        client: MockClient((r) async {
          calls.add(r.url.path);
          if (r.url.path == '/api/native/session') {
            return jsonResponse(session());
          }
          expect(
            r.headers['X-Corte-Expected-Creator'],
            'synthetic-private-creator',
          );
          return jsonResponse({'ok': true});
        }),
      );
      final result = await transport.request(
        'POST',
        '/api/cloud/import',
        body: {'formato': 'corte-local'},
      );
      expect(calls, ['/api/native/session', '/api/cloud/import']);
      expect(
        utf8.decode(result.bodyBytes),
        isNot(contains('synthetic-private-creator')),
      );
      transport.close();
    },
  );

  test(
    'PKCE is stored before browser and successful grant is durable before authenticated state',
    () async {
      final store = TestStore();
      final links = TestLinks()
        ..beforeOpen = () => store.values.containsKey(pendingAuthorizationKey);
      late CorteAuthController controller;
      store.beforeWrite = (key, _) async {
        if (key == deviceSessionKey) {
          expect(controller.state.authenticated, isFalse);
        }
      };
      controller = auth(
        store,
        MockClient((r) async {
          if (r.url.path.endsWith('/start')) {
            final body = jsonDecode(r.body) as Map;
            expect(body.keys.toSet(), {'platform', 'name', 'code_challenge'});
            expect(
              body['code_challenge'],
              matches(RegExp(r'^[A-Za-z0-9_-]{43}$')),
            );
            return jsonResponse(startResponse());
          }
          if (r.url.path.endsWith('/poll')) {
            final body = jsonDecode(r.body) as Map;
            expect(body.keys.toSet(), {'request_id', 'code_verifier'});
            return jsonResponse(grant());
          }
          return jsonResponse(session());
        }),
        links: links,
        platform: 'windows',
      );
      addTearDown(controller.dispose);
      await controller.initialize();
      await controller.signIn();
      expect(controller.state.pending?.userCode, 'ABCD-EFGH');
      expect(links.opened, hasLength(1));
      await controller.pollNow();
      expect(controller.state.authenticated, isTrue);
      expect(controller.state.cacheScope, cacheScope);
      expect(store.values.containsKey(deviceSessionKey), isTrue);
      expect(store.values.containsKey(pendingAuthorizationKey), isFalse);
    },
  );

  test('Android upgrades a pending code to Google inside the app', () async {
    final store = TestStore()
      ..values[pendingAuthorizationKey] = jsonEncode({
        ...startResponse(),
        'code_verifier': repeated('v', 43),
        'expires_at': now + 600,
      });
    final links = TestLinks();
    final calls = <String>[];
    final controller = auth(
      store,
      MockClient((request) async {
        calls.add(request.url.path);
        if (request.url.path == '/api/native/auth/google') {
          expect(request.method, 'POST');
          expect(request.headers['authorization'], isNull);
          expect(jsonDecode(request.body), {
            'id_token': 'synthetic-firebase-id-token',
            'device_name': 'Corte para Android',
          });
          return jsonResponse(grant());
        }
        expect(request.url.path, '/api/native/session');
        expect(request.headers['authorization'], 'Bearer ${token('a')}');
        expect(store.values[deviceSessionKey], isNotNull);
        return jsonResponse(session());
      }),
      links: links,
      androidSignIn: () async => 'synthetic-firebase-id-token',
    );
    addTearDown(controller.dispose);
    await controller.initialize();
    expect(controller.state.pending, isNull);
    expect(controller.state.phase, CorteAuthPhase.signedOut);
    await controller.signIn();
    expect(calls, ['/api/native/auth/google', '/api/native/session']);
    expect(links.opened, isEmpty);
    expect(controller.state.authenticated, isTrue);
    expect(controller.state.cacheScope, cacheScope);
    expect(store.values[pendingAuthorizationKey], isNull);
    expect(
      store.values[deviceSessionKey],
      isNot(contains('synthetic-firebase-id-token')),
    );
  });

  test(
    'Android returns to access if Google is cancelled during resume',
    () async {
      final result = Completer<String?>();
      final store = TestStore()
        ..values[deviceSessionKey] = jsonEncode({
          ...device(),
          'expires_at': now - 1,
        });
      final links = TestLinks();
      var requests = 0;
      final controller = auth(
        store,
        MockClient((_) async {
          requests++;
          return jsonResponse(grant());
        }),
        links: links,
        androidSignIn: () => result.future,
      );
      addTearDown(controller.dispose);
      await controller.initialize();
      final access = controller.signIn();
      controller.pause();
      await controller.resume();
      expect(controller.state.phase, CorteAuthPhase.checking);
      result.complete(null);
      await access;
      expect(controller.state.phase, CorteAuthPhase.signedOut);
      expect(controller.state.errorMessage, isNull);
      expect(requests, 0);
      expect(links.opened, isEmpty);
    },
  );

  test(
    'Android stays open and preserves its stored account if Google is unavailable',
    () async {
      final store = TestStore()
        ..values[sessionOwnerKey] = 'synthetic-owner'
        ..values[deviceSessionKey] = jsonEncode({
          ...device(),
          'expires_at': now - 1,
        });
      final storedValues = Map.of(store.values);
      final links = TestLinks();
      var nativeRequests = 0;
      final controller = auth(
        store,
        MockClient((request) async {
          fail('Unavailable Google must not issue a network request.');
        }),
        links: links,
        androidSignIn: () async {
          nativeRequests++;
          throw PlatformException(code: 'google_services_unavailable');
        },
      );
      addTearDown(controller.dispose);

      await controller.initialize();
      expect(nativeRequests, 0);
      for (var attempt = 1; attempt <= 2; attempt++) {
        await controller.signIn();
        expect(nativeRequests, attempt);
        expect(controller.state.phase, CorteAuthPhase.signedOut);
        expect(
          controller.state.errorMessage,
          'El acceso con Google no está disponible en este dispositivo. Puedes volver a intentarlo desde Corte.',
        );
        expect(store.values, storedValues);
        expect(links.opened, isEmpty);
      }
    },
  );

  test(
    'legacy Windows session without owner is verified before exposing private state',
    () async {
      final store = TestStore()
        ..values[deviceSessionKey] = jsonEncode(device('a', false));
      final controller = auth(
        store,
        MockClient((_) async => jsonResponse(session())),
      );
      addTearDown(controller.dispose);
      expect(controller.state.authenticated, isFalse);
      await controller.initialize();
      expect(controller.state.authenticated, isTrue);
      expect(store.values[sessionOwnerKey], 'synthetic-owner');
      expect(controller.state.cacheScope, cacheScope);
    },
  );

  test(
    '503 identity outage preserves credential and permits only its own known cached scope',
    () async {
      final store = TestStore()
        ..values[deviceSessionKey] = jsonEncode(device());
      final controller = auth(
        store,
        MockClient(
          (_) async => jsonResponse({
            'error': {'codigo': 'identidad_no_disponible'},
          }, 503),
        ),
      );
      addTearDown(controller.dispose);
      await controller.initialize();
      expect(controller.state.authenticated, isTrue);
      expect(controller.state.offline, isTrue);
      expect(controller.state.cacheScope, cacheScope);
      expect(store.values.containsKey(deviceSessionKey), isTrue);
    },
  );

  test(
    '401 of an old request cannot erase a newly persisted single-use credential',
    () async {
      final delayed = Completer<http.Response>();
      final store = TestStore()
        ..values[deviceSessionKey] = jsonEncode(device());
      final controller = auth(
        store,
        MockClient((r) async {
          if (r.url.path == '/api/slow') return delayed.future;
          if (r.url.path.endsWith('/start')) {
            return jsonResponse(startResponse());
          }
          if (r.url.path.endsWith('/poll')) return jsonResponse(grant('b'));
          return jsonResponse(session());
        }),
        platform: 'windows',
      );
      addTearDown(controller.dispose);
      await controller.initialize();
      final old = controller.transport.request('GET', '/api/slow');
      await Future<void>.delayed(Duration.zero);
      await controller.signIn();
      await controller.pollNow();
      delayed.complete(
        jsonResponse({
          'error': {'codigo': 'sesion_nativa_invalida'},
        }, 401),
      );
      await old;
      expect(controller.state.authenticated, isTrue);
      expect(jsonDecode(store.values[deviceSessionKey]!)['token'], token('b'));
    },
  );

  test(
    'logout queued during credential persistence leaves no resurrected token or PKCE',
    () async {
      final entered = Completer<void>(), release = Completer<void>();
      final store = TestStore();
      store.beforeWrite = (key, _) async {
        if (key == deviceSessionKey && !entered.isCompleted) {
          entered.complete();
          await release.future;
        }
      };
      final controller = auth(
        store,
        MockClient((r) async {
          if (r.url.path.endsWith('/start')) {
            return jsonResponse(startResponse());
          }
          if (r.url.path.endsWith('/poll')) return jsonResponse(grant());
          return jsonResponse(session());
        }),
        platform: 'windows',
      );
      addTearDown(controller.dispose);
      await controller.initialize();
      await controller.signIn();
      final poll = controller.pollNow();
      await entered.future;
      final logout = controller.signOut();
      release.complete();
      await Future.wait([poll, logout]);
      expect(controller.state.authenticated, isFalse);
      expect(store.values.containsKey(deviceSessionKey), isFalse);
      expect(store.values.containsKey(pendingAuthorizationKey), isFalse);
      expect(store.values[sessionOwnerKey], 'synthetic-owner');
    },
  );

  test(
    'existing web cookie works online without invented cache scope or native storage',
    () async {
      final store = TestStore();
      final controller = CorteAuthController(
        runtime: CorteRuntime(platform: 'web', baseUri: Uri.parse(origin)),
        credentials: store,
        webSignIn: TestWebAuth(),
        client: MockClient((r) async {
          expect(r.headers.containsKey('Authorization'), isFalse);
          expect(r.headers.containsKey('Origin'), isFalse);
          return jsonResponse({'cloud': true, 'authenticated': true});
        }),
      );
      addTearDown(controller.dispose);
      await controller.initialize();
      expect(controller.state.authenticated, isTrue);
      expect(controller.state.ownerScope, isNull);
      expect(controller.state.cacheScope, isNull);
      expect(store.values, isEmpty);
    },
  );
}
