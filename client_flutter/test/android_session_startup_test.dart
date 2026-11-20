import 'dart:async';
import 'dart:convert';

import 'package:corte/app.dart';
import 'package:corte/auth/auth_controller.dart';
import 'package:corte/data/corte_store.dart';
import 'package:corte/platform/corte_runtime.dart';
import 'package:corte/platform/native_bridge.dart';
import 'package:corte/ui/shell.dart';
import 'package:corte/ui/theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

class _Credentials implements CorteCredentialStore {
  _Credentials(this.values);

  final Map<String, String> values;

  @override
  Future<String?> read(String key) async => values[key];

  @override
  Future<void> write(String key, String value) async => values[key] = value;

  @override
  Future<void> delete(String key) async => values.remove(key);
}

void main() {
  for (final (restore, recovery) in [
    (false, false),
    (true, false),
    (true, true),
  ]) {
    testWidgets(
      recovery
          ? 'Android recovery opens Inicio without loading account data automatically'
          : restore
          ? 'Android opens Inicio when it restores an existing session'
          : 'Android opens Inicio on return from a successful Google sign-in',
      (tester) async {
        const nativeChannel = MethodChannel('corte/native');
        final messenger =
            TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
        messenger.setMockMethodCallHandler(nativeChannel, (_) async => null);
        addTearDown(
          () => messenger.setMockMethodCallHandler(nativeChannel, null),
        );
        tester.view.devicePixelRatio = 1;
        tester.view.physicalSize = const Size(390, 844);
        addTearDown(tester.view.resetDevicePixelRatio);
        addTearDown(tester.view.resetPhysicalSize);

        const now = 1795000000;
        const owner = 'synthetic-owner';
        final cacheScope = List.filled(64, 'c').join();
        final deviceId = List.filled(24, 'd').join();
        final bearer = 'corte_native_v1_${List.filled(43, 'a').join()}';
        final device = {
          'token': bearer,
          'device_id': deviceId,
          'expires_at': now + 3600,
          'owner_uid': owner,
          'cache_scope': cacheScope,
        };
        final ownerInfo = {'uid': owner, 'email': 'synthetic@example.test'};
        final credentials = _Credentials({
          if (restore) ...{
            sessionOwnerKey: owner,
            deviceSessionKey: jsonEncode(device),
          },
        });
        final googleCallback = Completer<String?>();
        final dashboardReady = Completer<void>();
        const googleProof = 'synthetic-firebase-owner-proof';
        var googleRequests = 0;
        final paths = <String>[];
        final auth = CorteAuthController(
          runtime: CorteRuntime(
            platform: 'android',
            baseUri: Uri.parse(corteCloudOrigin),
          ),
          credentials: credentials,
          clock: () => DateTime.fromMillisecondsSinceEpoch(now * 1000),
          androidSignIn: () {
            googleRequests++;
            return googleCallback.future;
          },
          client: MockClient((request) async {
            final path = request.url.path;
            paths.add(path);
            if (path == '/api/dashboard') await dashboardReady.future;
            if (path == '/api/native/auth/google') {
              expectSync(request.headers['authorization'], isNull);
              expectSync(jsonDecode(request.body)['id_token'], googleProof);
            } else {
              expectSync(request.headers['authorization'], 'Bearer $bearer');
            }
            final payload = switch (path) {
              '/api/native/auth/google' => {
                'estado': 'autorizado',
                ...device,
                'owner': ownerInfo,
              },
              '/api/native/session' => {
                'authenticated': true,
                'device_id': deviceId,
                'expires_at': now + 3600,
                'owner': ownerInfo,
                'owner_scope': List.filled(64, 'b').join(),
                'cache_scope': cacheScope,
              },
              '/api/session' => {
                'conexion': {'estado': 'conectada'},
                'datos': {'hay_datos': true},
              },
              '/api/dashboard' => {
                'kpis': {
                  'ventas_centavos': 12500,
                  'comision_estimada_centavos': 1200,
                  'pedidos': 3,
                },
              },
              '/api/muestras' => {'items': []},
              '/api/cloud/revision' => {
                'cache_scope': cacheScope,
                'revision': 1,
              },
              '/api/snapshot' => {
                'version_esquema': 1,
                'muestras': [],
                'local': {},
              },
              _ => <String, Object?>{},
            };
            return http.Response(
              jsonEncode(payload),
              200,
              headers: {'content-type': 'application/json'},
            );
          }),
        );
        final ui = CorteUiController(
          auth: auth,
          openStore: () async => MemoryCorteDataStore(),
          androidRecovery: recovery,
        );
        final router = CorteRouter(ui);
        try {
          await tester.pumpWidget(
            MaterialApp.router(
              theme: corteTheme(),
              routerDelegate: router,
              routeInformationParser: const CorteRouteParser(),
            ),
          );
          expect(find.byType(CorteAccess), findsOneWidget);

          await auth.initialize();
          if (!restore) {
            await tester.pumpAndSettle();
            final accessHeading = tester.renderObject<RenderParagraph>(
              find.descendant(
                of: find.text('Tu estudio\nde creación'),
                matching: find.byType(RichText),
              ),
            );
            expect(accessHeading.text.style?.fontFamily, 'MonaSans');
            await tester.tap(find.text('Continuar con Google'));
            await tester.pump();
            expect(googleRequests, 1);
            auth.pause();
            await auth.resume();
            googleCallback.complete(googleProof);
          }
          await tester.pumpAndSettle();

          expect(find.byType(CorteShell), findsOneWidget);
          expect(find.byType(CorteAccess), findsNothing);
          if (recovery) {
            expect(find.text('Inicio ligero'), findsOneWidget);
            await tester.pump(const Duration(seconds: 30));
            expect(paths, ['/api/native/session']);
            await tester.tap(find.text('Cargar resultados'));
            await tester.pumpAndSettle();
          }
          expect(ui.location, '/inicio');
          expect(find.text('Hoy'), findsWidgets);
          expect(find.text('Comisión estimada'), findsOneWidget);
          expect(find.text('Tus prioridades'), findsOneWidget);
          final sales = find.text('Ventas generadas');
          await tester.scrollUntilVisible(
            sales,
            240,
            maxScrolls: 8,
            duration: const Duration(milliseconds: 16),
          );
          expect(sales, findsOneWidget);
          expect(find.text('Cargando resultados…'), findsWidgets);
          expect(
            paths,
            containsAll([
              '/api/native/session',
              '/api/session',
              '/api/dashboard',
              '/api/muestras',
            ]),
          );
          const backgroundPaths = [
            '/api/cloud/revision',
            '/api/snapshot',
            '/api/push/status',
          ];
          await tester.pump(const Duration(seconds: 2));
          expect(paths.where(backgroundPaths.contains), isEmpty);

          if (restore && !recovery) {
            ui.pause();
            await tester.pump(const Duration(seconds: 7));
            expect(paths.where(backgroundPaths.contains), isEmpty);
            unawaited(ui.resume());
            await tester.pump();
          }
          dashboardReady.complete();
          await tester.pumpAndSettle();
          expect(find.text('Cargando resultados…'), findsNothing);
          expect(find.text(r'$125'), findsOneWidget);
          expect(paths.where(backgroundPaths.contains), isEmpty);
          await tester.pump(const Duration(seconds: 6));
          await tester.pumpAndSettle();
          expect(
            paths.where(backgroundPaths.contains),
            unorderedEquals(recovery ? const <String>[] : backgroundPaths),
          );
          expect(paths.where((path) => path.startsWith('/api/native/auth/')), [
            if (!restore) '/api/native/auth/google',
          ]);
          expect(credentials.values[sessionOwnerKey], owner);
          expect(
            jsonDecode(credentials.values[deviceSessionKey]!)['token'],
            bearer,
          );
          expect(tester.takeException(), isNull);
        } finally {
          if (!dashboardReady.isCompleted) dashboardReady.complete();
          await tester.pumpWidget(const SizedBox.shrink());
          router.dispose();
          ui.dispose();
          auth.dispose();
        }
      },
      variant: TargetPlatformVariant.only(TargetPlatform.android),
    );
  }
}
