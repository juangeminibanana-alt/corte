import 'dart:convert';
import 'dart:typed_data';

import 'package:corte/app.dart';
import 'package:corte/auth/auth_controller.dart';
import 'package:corte/data/corte_repository.dart';
import 'package:corte/data/shop_upload.dart';
import 'package:corte/platform/corte_runtime.dart';
import 'package:corte/platform/corte_transport.dart';
import 'package:corte/platform/data_store.dart';
import 'package:corte/ui/shop_publisher.dart';
import 'package:corte/ui/theme.dart';
import 'package:file_selector/file_selector.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

final scope = 'b' * 64;

class _TestStore implements CorteDataStore {
  final _items = <String, String>{};
  @override
  Future<String?> read(String key) async => _items[key];
  @override
  Future<void> write(String key, String value) async {
    _items[key] = value;
  }

  @override
  Future<void> remove(String key) async {
    _items.remove(key);
  }
}

final runtime = CorteRuntime(
  platform: 'web',
  baseUri: Uri.parse(corteCloudOrigin),
);
http.Response jsonResult(Object json, [int status = 200]) =>
    http.Response.bytes(
      utf8.encode(jsonEncode(json)),
      status,
      headers: {'content-type': 'application/json'},
    );
XFile syntheticFile(int size) =>
    XFile.fromData(Uint8List(size), path: 'clip.mp4', name: 'clip.mp4');

Future<void> tap(WidgetTester tester, String label) async {
  final finder = find.text(label).last;
  await tester.ensureVisible(finder);
  await tester.tap(finder);
  await frames(tester);
}

Future<void> frames(WidgetTester tester) async {
  for (var i = 0; i < 6; i++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
}

void main() {
  test(
    'carga cada bloque en orden y limita la lectura al tamaño de la parte',
    () async {
      final sizes = <int>[];
      final transport = CorteTransport(
        runtime: runtime,
        client: MockClient((req) async {
          expect(req.headers['X-Corte-Cache-Scope'], scope);
          if (req.url.path.endsWith('/iniciar')) {
            expect(jsonDecode(req.body), {
              'nombre': 'video.mp4',
              'bytes': 10 * 1024 * 1024 + 1,
            });
            return jsonResult({'carga_id': 'upload01', 'partes': 2});
          }
          expect(req.method, 'PUT');
          expect(req.headers['Content-Type'], 'application/octet-stream');
          sizes.add(req.bodyBytes.length);
          return jsonResult(
            req.url.path.endsWith('/1') ? {'recibida': 1} : {'file_id': 'f01'},
          );
        }),
      );
      addTearDown(transport.close);
      final repo = CorteRepository(adapter: transport, cacheScope: scope);
      final result = await uploadShopVideo(
        repo,
        syntheticFile(10 * 1024 * 1024 + 1),
        checkAccount: () {},
        onProgress: (_) {},
      );
      expect(result, 'f01');
      expect(sizes, [5 * 1024 * 1024, 5 * 1024 * 1024 + 1]);
    },
  );

  for (final width in [390.0, 1536.0]) {
    testWidgets(
      'la revisión precede al envío y se puede consultar el estado a ancho $width',
      (tester) async {
        tester.view.devicePixelRatio = 1;
        tester.view.physicalSize = Size(width, 1080);
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        final sent = <String>[];
        Map<String, dynamic>? scheduled;
        final auth = CorteAuthController(
          runtime: runtime,
          client: MockClient((req) async {
            switch (req.url.path) {
              case '$shopBase/capacidades':
                return jsonResult({
                  'scope_concedido': true,
                  'cuenta_creator_conectada': true,
                });
              case '/api/productos/123':
                return jsonResult({
                  'ficha': {'product_id': '123', 'titulo': 'Vestido rojo'},
                });
              case '/api/analitica/productos':
                return jsonResult({
                  'items': [
                    {'product_id': '123', 'titulo': 'Vestido rojo'},
                  ],
                });
              case '$shopBase/agenda':
                expect(req.headers['X-Corte-Cache-Scope'], scope);
                if (req.method == 'POST') {
                  sent.add('schedule');
                  final body = jsonDecode(req.body) as Map<String, dynamic>;
                  expect(body['confirmar'], true);
                  expect(
                    body['programada_at'],
                    greaterThan(DateTime.now().millisecondsSinceEpoch ~/ 1000),
                  );
                  scheduled = {...body, 'id': 'abc', 'estado': 'programada'};
                  return jsonResult(scheduled!);
                }
                return jsonResult({
                  'items': [if (scheduled != null) scheduled!],
                });
              case '$shopBase/agenda/abc/cancelar':
                expect(req.method, 'POST');
                expect(jsonDecode(req.body), {});
                sent.add('cancel');
                scheduled = {...scheduled!, 'estado': 'cancelada'};
                return jsonResult(scheduled!);
              case '$shopBase/911/estado':
                return jsonResult({'video_id': '911', 'estado': 'publicada'});
              case '$shopBase/archivo':
                sent.add('upload');
                expect(
                  req.headers['Content-Type'],
                  startsWith('multipart/form-data; boundary='),
                );
                expect(
                  latin1.decode(req.bodyBytes),
                  contains('name="archivo"; filename="video.mp4"'),
                );
                return jsonResult({'file_id': 'archivo1'});
              case '$shopBase/publicar':
                sent.add('publish');
                expect(req.headers['X-Corte-Cache-Scope'], scope);
                expect(jsonDecode(req.body), {
                  'file_id': 'archivo1',
                  'titulo': 'Prueba de prenda',
                  'product_id': '123',
                  'titulo_ancla': 'Vestido rojo',
                  'is_ai_generated': false,
                  'confirmar': true,
                });
                return jsonResult({'video_id': '911', 'estado': 'aceptada'});
              default:
                return jsonResult({});
            }
          }),
        );
        final ui = CorteUiController(
          auth: auth,
          openStore: () async => _TestStore(),
        );
        ui.repo.setScopes(ownerScope: 'owner', cacheScope: scope);
        addTearDown(() {
          ui.dispose();
          auth.dispose();
        });
        await tester.pumpWidget(
          MaterialApp(
            theme: corteTheme(),
            home: CorteScope(
              controller: ui,
              child: Scaffold(
                body: ShopPublisherPage(
                  initialProduct: '123',
                  pickVideo: () async => syntheticFile(10),
                ),
              ),
            ),
          ),
        );
        await frames(tester);
        expect(
          find.text('Elegir video'),
          findsOneWidget,
          reason: tester
              .widgetList<Text>(find.byType(Text))
              .map((t) => t.data)
              .join(' / '),
        );
        await tap(tester, 'Elegir video');
        await tester.enterText(
          find.byType(TextField).first,
          'Prueba de prenda',
        );
        await tap(tester, 'Revisar publicación');
        expect(sent, isEmpty);
        await tap(tester, 'Volver a editar');
        expect(sent, isEmpty);
        await tap(tester, 'Revisar publicación');
        await tap(tester, 'Confirmar publicación');
        expect(sent, ['upload', 'publish']);
        await tap(tester, 'Consultar estado en TikTok');
        expect(find.text('El video está publicado.'), findsOneWidget);
        if (width > 600) {
          await tap(tester, 'Preparar otro video');
          await tap(tester, 'Elegir prenda');
          await tap(tester, 'Vestido rojo');
          await tap(tester, 'Elegir video');
          await tap(tester, 'Programar');
          await tap(tester, 'Elegir fecha y hora local');
          await tester.tap(find.byTooltip('Next month'));
          await frames(tester);
          await tap(tester, '15');
          await tap(tester, 'OK');
          await tap(tester, 'OK');
          await tap(tester, 'Revisar programación');
          expect(sent, ['upload', 'publish']);
          await tap(tester, 'Confirmar programación');
          expect(sent, ['upload', 'publish', 'upload', 'schedule']);
          await tap(tester, 'Cancelar programación');
          await tap(tester, 'Conservar');
          expect(sent.last, 'schedule');
          await tap(tester, 'Cancelar programación');
          await tap(tester, 'Cancelar programación');
          expect(sent.last, 'cancel');
          expect(find.textContaining('Cancelada'), findsOneWidget);
        }
        expect(tester.takeException(), isNull);
      },
    );
  }
}
