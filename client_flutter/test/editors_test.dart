import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:corte/app.dart';
import 'package:corte/auth/auth_controller.dart';
import 'package:corte/platform/corte_runtime.dart';
import 'package:corte/ui/editors.dart';
import 'package:corte/ui/theme.dart';

void main() {
  testWidgets(
    'clipboard failure keeps message and does not register a copied notice',
    (tester) async {
      final writes = <http.Request>[];
      final auth = CorteAuthController(
        runtime: CorteRuntime(
          platform: 'web',
          baseUri: Uri.parse(corteCloudOrigin),
        ),
        client: MockClient((request) async {
          if (request.method != 'GET') writes.add(request);
          final body = request.url.path == '/api/plantillas'
              ? {
                  'items': [
                    {
                      'id': 'ya_la_recibi',
                      'nombre': 'Ya la recibí',
                      'cuerpo': 'Hola, {tienda}. Ya recibí {producto}.{firma}',
                      'rev': 1,
                      'predeterminada': true,
                    },
                  ],
                }
              : request.url.path == '/api/preferencias'
              ? {'firma': 'Firma sintética', 'rev': 1}
              : {};
          return http.Response(
            jsonEncode(body),
            200,
            headers: {'content-type': 'application/json'},
          );
        }),
      );
      final ui = CorteUiController(auth: auth);
      tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
        SystemChannels.platform,
        (call) async {
          if (call.method == 'Clipboard.setData')
            throw PlatformException(code: 'clipboard-denied');
          return null;
        },
      );
      addTearDown(
        () => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
          SystemChannels.platform,
          null,
        ),
      );
      await tester.pumpWidget(
        MaterialApp(
          theme: corteTheme(),
          home: CorteScope(
            controller: ui,
            child: Builder(
              builder: (context) => Scaffold(
                body: TextButton(
                  onPressed: () => showMessageEditor(
                    context,
                    tienda: {'tienda_key': 't1', 'nombre': 'Tienda sintética'},
                    muestras: [
                      {
                        'application_id': 'm1',
                        'producto': {'titulo': 'Chaqueta sintética'},
                      },
                    ],
                    plantillaId: 'ya_la_recibi',
                  ),
                  child: const Text('Abrir mensaje'),
                ),
              ),
            ),
          ),
        ),
      );
      await tester.tap(find.text('Abrir mensaje'));
      await tester.pumpAndSettle();
      expect(
        find.textContaining('Ya recibí Chaqueta sintética'),
        findsOneWidget,
      );
      await tester.tap(find.widgetWithText(FilledButton, 'Copiar mensaje'));
      await tester.pumpAndSettle();
      expect(
        find.textContaining('No pudimos copiar al portapapeles.'),
        findsOneWidget,
      );
      expect(
        find.textContaining('Ya recibí Chaqueta sintética'),
        findsOneWidget,
      );
      expect(writes, isEmpty);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox.shrink());
      ui.dispose();
      auth.dispose();
    },
  );

  testWidgets(
    'online-only conflict keeps note text and can save with the reviewed revision',
    (tester) async {
      var attempts = 0;
      final changes = <Map<String, dynamic>>[];
      final auth = CorteAuthController(
        runtime: CorteRuntime(
          platform: 'web',
          baseUri: Uri.parse(corteCloudOrigin),
        ),
        client: MockClient((request) async {
          if (request.url.path == '/api/local/ops') {
            attempts++;
            final op = Map<String, dynamic>.from(
              (jsonDecode(request.body)['ops'] as List).single as Map,
            );
            changes.add(op);
            return http.Response(
              jsonEncode({
                'resultados': [
                  {
                    'op_id': op['op_id'],
                    'estado': attempts == 1 ? 'conflicto' : 'aplicada',
                    'objeto': {
                      'id': 'n1',
                      'rev': attempts == 1 ? 5 : 6,
                      'texto': 'Texto de otro equipo',
                    },
                  },
                ],
              }),
              200,
              headers: {'content-type': 'application/json'},
            );
          }
          return http.Response(
            '{}',
            200,
            headers: {'content-type': 'application/json'},
          );
        }),
      );
      final ui = CorteUiController(auth: auth);
      await tester.pumpWidget(
        MaterialApp(
          theme: corteTheme(),
          home: CorteScope(
            controller: ui,
            child: Builder(
              builder: (context) => Scaffold(
                body: TextButton(
                  onPressed: () => showNoteEditor(
                    context,
                    'general',
                    null,
                    note: {
                      'id': 'n1',
                      'rev': 1,
                      'texto': 'Borrador original',
                      'fijada': false,
                    },
                  ),
                  child: const Text('Abrir nota'),
                ),
              ),
            ),
          ),
        ),
      );
      await tester.tap(find.text('Abrir nota'));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byType(TextFormField),
        'Mi edición conservada',
      );
      await tester.tap(find.widgetWithText(FilledButton, 'Guardar'));
      await tester.pumpAndSettle();
      expect(find.text('Mi edición conservada'), findsOneWidget);
      expect(find.textContaining('Versión actual 5'), findsOneWidget);
      await tester.ensureVisible(
        find.text('Revisé el conflicto; conservar mi edición'),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.text('Revisé el conflicto; conservar mi edición'));
      await tester.pump();
      await tester.tap(find.widgetWithText(FilledButton, 'Guardar'));
      await tester.pumpAndSettle();
      expect(attempts, 2);
      expect(changes[1]['cambios']['rev'], 5);
      expect(changes[1]['cambios']['texto'], 'Mi edición conservada');
      expect(changes[0]['op_id'], isNot(changes[1]['op_id']));
      expect(find.byType(Dialog), findsNothing);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox.shrink());
      ui.dispose();
      auth.dispose();
    },
  );
}
