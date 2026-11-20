import 'dart:convert';

import 'package:corte/app.dart';
import 'package:corte/auth/auth_controller.dart';
import 'package:corte/data/corte_repository.dart';
import 'package:corte/platform/corte_runtime.dart';
import 'package:corte/ui/catalog.dart';
import 'package:corte/ui/order_tile.dart';
import 'package:corte/ui/theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

const _id = '580009219001008421';
const _shopProduct = '7400000000000000001';

Map<String, dynamic> _order(String id, String state) => {
  'order_id': id,
  'fecha': '2026-11-20',
  'estado': state,
  'estado_etiqueta': state == 'SETTLED' ? 'Liquidado' : 'Reembolsado',
  'comision_real_centavos': 0,
  'comision_estimada_centavos': 87800,
  'total_centavos': 99900,
  'lineas': [
    {
      'product_id': _shopProduct,
      'producto': 'https://producto.example.test/1',
      'cantidad': 1,
    },
  ],
};

void main() {
  test('cleans URLs and uses the next title only for the exact ID', () {
    final catalog = orderCatalog([
      {
        'product_id': _shopProduct,
        'titulo_corto': 'tiktok.com',
        'titulo': 'Chaqueta oliva',
      },
      {'product_id': '123', 'titulo_corto': 'Camisa de lino'},
    ]);
    expect(
      orderProductLabel({
        'producto': '/tienda/prenda-1',
        'product_id': _shopProduct,
      }, catalog),
      'Chaqueta oliva',
    );
    expect(
      orderProductLabel({
        'producto': 'https://producto.example.test/1',
        'product_id': '456',
      }, catalog),
      'Producto',
    );
    expect(
      orderProductLabel({
        'producto': 'Bolso de lona https://producto.example.test/1',
      }, catalog),
      'Bolso de lona',
    );
    expect(shortOrderId(_id), '5800…8421');
  });

  testWidgets('orders page shares one catalog lookup and copies full ID', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final messenger =
        TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    String? clipboard;
    messenger.setMockMethodCallHandler(SystemChannels.platform, (call) async {
      if (call.method == 'Clipboard.setData') {
        clipboard = (call.arguments as Map)['text'] as String;
      }
      return null;
    });
    addTearDown(
      () => messenger.setMockMethodCallHandler(SystemChannels.platform, null),
    );
    var lookups = 0;
    final auth = CorteAuthController(
      runtime: CorteRuntime(
        platform: 'web',
        baseUri: Uri.parse(corteCloudOrigin),
      ),
      client: MockClient((request) async {
        final outcome = switch (request.url.path) {
          '/api/ordenes' => {
            'total': 2,
            'items': [_order(_id, 'SETTLED'), _order('1234', 'REFUNDED')],
          },
          '/api/analitica/productos' => {
            'items': [
              {'product_id': _shopProduct, 'titulo': 'Chaqueta oliva'},
            ],
          },
          _ => {'items': []},
        };
        if (request.url.path == '/api/analitica/productos') lookups++;
        return http.Response(
          jsonEncode(outcome),
          200,
          headers: {'content-type': 'application/json'},
        );
      }),
    );
    final ui = CorteUiController(auth: auth);
    ui.repo.attachStore(MemoryCorteDataStore());
    ui.repo.setScopes(ownerScope: 'a' * 64, cacheScope: 'b' * 64);
    addTearDown(ui.dispose);
    addTearDown(auth.dispose);
    await tester.pumpWidget(
      MaterialApp(
        theme: corteTheme(),
        home: CorteScope(
          controller: ui,
          child: const Scaffold(body: OrdersPage()),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(lookups, 1);
    expect(find.text('Chaqueta oliva'), findsNWidgets(2));
    expect(find.text('Pedido 5800…8421'), findsOneWidget);
    expect(find.text('Comisión liquidada'), findsOneWidget);
    expect(find.text(r'$0.00'), findsOneWidget);
    expect(find.text('Comisión estimada'), findsNothing);
    expect(find.text(r'$878.00'), findsNothing);

    await tester.tap(find.text('Chaqueta oliva').first);
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.text('Copiar ID'));
    await tester.tap(find.text('Copiar ID'));
    expect(clipboard, _id);
    expect(find.text('Total del pedido'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
