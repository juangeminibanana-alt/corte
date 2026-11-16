import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:corte/app.dart';
import 'package:corte/auth/auth_controller.dart';
import 'package:corte/data/corte_repository.dart';
import 'package:corte/platform/corte_runtime.dart';
import 'package:corte/ui/settings.dart';
import 'package:corte/ui/theme.dart';

final scope = List.filled(64, 'a').join();
http.Response response(Object value) => http.Response(
  jsonEncode(value),
  200,
  headers: {'content-type': 'application/json; charset=utf-8'},
);

class Fixture {
  Fixture({this.conflict = false}) {
    auth = CorteAuthController(
      runtime: CorteRuntime(
        platform: 'web',
        baseUri: Uri.parse(corteCloudOrigin),
      ),
      client: MockClient(handle),
    );
    ui = CorteUiController(auth: auth);
    ui.repo.attachStore(MemoryCorteDataStore());
    ui.repo.setScopes(ownerScope: scope, cacheScope: scope);
  }
  final bool conflict;
  late final CorteAuthController auth;
  late final CorteUiController ui;
  JsonMap preferences = {
    'rev': 4,
    'capacidad_videos_dia': 3,
    'dias_videos': [0, 1, 2, 3, 4, 5],
    'firma': 'Firma original',
  };
  final operations = <JsonMap>[];
  final notes = <JsonMap>[];
  Future<http.Response> handle(http.Request request) async {
    switch (request.url.path) {
      case '/api/sesion':
        return response({
          'cuenta': {'username': 'synthetic_creator'},
          'conexion': {'estado': 'conectada'},
          'sync': {'en_curso': false},
          'capacidades': {},
        });
      case '/api/display/estado':
        return response({'estado': 'conectada'});
      case '/api/preferencias':
        return response(preferences);
      case '/api/cloud/revision':
        return response({
          'revision': 'stable',
          'owner_scope': scope,
          'cache_scope': scope,
        });
      case '/api/notas':
        return response({'items': notes});
      case '/api/snapshot':
        return response({
          'version_esquema': 1,
          'muestras': [],
          'local': {
            'planes': [],
            'notas': notes,
            'avisos': [],
            'plantillas': [],
            'recordatorios': [],
            'preferencias': preferences,
          },
        });
      case '/api/local/ops':
        expect(request.headers['X-Corte-Cache-Scope'], scope);
        final body = jsonDecode(request.body) as Map;
        final batch = (body['ops'] as List)
            .map((v) => Map<String, dynamic>.from(v as Map))
            .toList();
        operations.addAll(batch);
        return response({
          'resultados': [
            for (final op in batch)
              {
                'op_id': op['op_id'],
                'estado': conflict ? 'conflicto' : 'aplicada',
                'error': conflict
                    ? 'Tus preferencias cambiaron en otro dispositivo.'
                    : null,
                'objeto': conflict
                    ? {...preferences, 'rev': 5, 'firma': 'Otra firma'}
                    : apply(op),
              },
          ],
        });
      default:
        return response({});
    }
  }

  JsonMap apply(JsonMap op) {
    if (op['tipo'] == 'preferencias.editar') {
      preferences = {
        ...preferences,
        ...Map<String, dynamic>.from(op['cambios'] as Map),
        'rev': (preferences['rev'] as int) + 1,
      };
      return preferences;
    }
    final note = {...Map<String, dynamic>.from(op['datos'] as Map), 'rev': 1};
    notes.add(note);
    return note;
  }

  void close() {
    ui.dispose();
    auth.dispose();
  }
}

Future<void> mount(WidgetTester tester, Fixture fixture, Widget child) async {
  tester.view.physicalSize = const Size(1100, 1600);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  addTearDown(fixture.close);
  await tester.pumpWidget(
    CorteScope(
      controller: fixture.ui,
      child: MaterialApp(
        theme: corteTheme(),
        home: Scaffold(body: child),
      ),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  testWidgets(
    'changing appearance preserves an unsaved signature and advances only its unchanged base revision',
    (tester) async {
      final fixture = Fixture();
      await mount(tester, fixture, const SettingsPage());
      final signature = find.byType(TextFormField);
      await tester.ensureVisible(signature);
      await tester.enterText(signature, 'Mi firma pendiente');
      await tester.pump();
      final dark = find.widgetWithText(ChoiceChip, 'Oscuro');
      await tester.ensureVisible(dark);
      await tester.tap(dark);
      await tester.pumpAndSettle();
      expect(fixture.ui.appearance.mode, ThemeMode.dark);
      expect(fixture.operations.single['cambios'], {
        'rev': 4,
        'tema': 'oscuro',
      });
      expect(
        tester.widget<TextFormField>(signature).controller!.text,
        'Mi firma pendiente',
      );
      final save = find.widgetWithText(FilledButton, 'Guardar preferencias');
      await tester.ensureVisible(save);
      await tester.tap(save);
      await tester.pumpAndSettle();
      expect(fixture.operations, hasLength(2));
      expect((fixture.operations.last['cambios'] as Map)['rev'], 5);
      expect(fixture.preferences['firma'], 'Mi firma pendiente');
      expect(fixture.preferences['tema'], 'oscuro');
    },
  );

  testWidgets(
    'preferences commit canonical revision-scoped operations and confirmed values survive refresh',
    (tester) async {
      final fixture = Fixture();
      await mount(tester, fixture, const SettingsPage());
      final signature = find.byType(TextFormField);
      await tester.ensureVisible(signature);
      await tester.enterText(signature, 'Nueva firma');
      await tester.pump();
      final save = find.widgetWithText(FilledButton, 'Guardar preferencias');
      await tester.ensureVisible(save);
      await tester.tap(save);
      await tester.pumpAndSettle();
      expect(fixture.operations.length, 1);
      final op = fixture.operations.single;
      expect(op['tipo'], 'preferencias.editar');
      expect(op['op_id'], matches(RegExp(r'^[a-f0-9-]{36}$')));
      expect(op['cambios'], {
        'rev': 4,
        'capacidad_videos_dia': 3,
        'dias_videos': [0, 1, 2, 3, 4, 5],
        'firma': 'Nueva firma',
      });
      expect(fixture.preferences['firma'], 'Nueva firma');
      expect(find.text('Preferencias guardadas.'), findsOneWidget);
      expect(
        (await fixture.ui.repo.opsPendientes(incluirConflictos: true)),
        isEmpty,
      );
    },
  );

  testWidgets(
    'conflicting preference edit stays visible and cannot silently overwrite the current version',
    (tester) async {
      final fixture = Fixture(conflict: true);
      await mount(tester, fixture, const SettingsPage());
      final signature = find.byType(TextFormField);
      await tester.ensureVisible(signature);
      await tester.enterText(signature, 'Mi edición pendiente');
      await tester.pump();
      final save = find.widgetWithText(FilledButton, 'Guardar preferencias');
      await tester.ensureVisible(save);
      await tester.tap(save);
      await tester.pumpAndSettle();
      expect(
        tester.widget<TextFormField>(signature).controller!.text,
        'Mi edición pendiente',
      );
      expect(
        find.text('Tus preferencias cambiaron en otro dispositivo.'),
        findsOneWidget,
      );
      expect(tester.widget<FilledButton>(save).onPressed, isNull);
      final queue = await fixture.ui.repo.opsPendientes(
        incluirConflictos: true,
      );
      expect(queue.single['estado'], 'conflicto');
      expect(fixture.operations.length, 1);
    },
  );

  testWidgets(
    'general note editor creates a real revisioned operation through the scoped outbox',
    (tester) async {
      final fixture = Fixture();
      await mount(tester, fixture, const NotesPage());
      await tester.tap(find.widgetWithText(FilledButton, 'Añadir nota'));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byType(TextFormField),
        'Una idea para el próximo video',
      );
      await tester.tap(find.widgetWithText(FilledButton, 'Guardar'));
      await tester.pumpAndSettle();
      final op = fixture.operations.single;
      expect(op['tipo'], 'nota.crear');
      final data = Map<String, dynamic>.from(op['datos'] as Map);
      expect(data['entidad'], 'general');
      expect(data['entidad_id'], isNull);
      expect(data['texto'], 'Una idea para el próximo video');
      expect(data['id'], matches(RegExp(r'^[a-f0-9-]{36}$')));
      expect(find.text('Una idea para el próximo video'), findsOneWidget);
    },
  );
}
