import 'dart:convert';

import 'package:corte/app.dart';
import 'package:corte/auth/auth_controller.dart';
import 'package:corte/platform/corte_runtime.dart';
import 'package:corte/ui/catalog.dart';
import 'package:corte/ui/desktop.dart';
import 'package:corte/ui/theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

const _product = {'product_id': '120', 'titulo': 'Suéter de algodón'};

Map<String, Object?> _sample(
  String id,
  String variant, {
  String stage = 'por_planear',
  String? planId,
}) => {
  'application_id': id,
  'variante': variant,
  'etiqueta': 'Muestra recibida',
  'producto': _product,
  'tienda': {'tienda_key': 'tienda-de-prueba', 'nombre': 'Tienda de prueba'},
  'avance': {'etapa': stage, 'plan_id': planId},
};

void main() {
  for (final (size, platform) in [
    (const Size(390, 844), TargetPlatform.android),
    (const Size(1536, 1040), TargetPlatform.windows),
  ]) {
    testWidgets(
      'opens the matching sample plan and keeps older samples visible',
      variant: TargetPlatformVariant.only(platform),
      (tester) async {
        tester.view.devicePixelRatio = 1;
        tester.view.physicalSize = size;
        addTearDown(tester.view.resetDevicePixelRatio);
        addTearDown(tester.view.resetPhysicalSize);
        final auth = CorteAuthController(
          runtime: CorteRuntime(
            platform: 'web',
            baseUri: Uri.parse(corteCloudOrigin),
          ),
          client: MockClient((request) async {
            final response = switch (request.url.path) {
              '/api/productos/120' => {
                'ficha': _product,
                'muestras': [
                  _sample('110', 'Azul / M'),
                  _sample('111', 'Verde / XL', stage: 'planeada', planId: 'p1'),
                  _sample('_antigua', 'Rojo / S'),
                  _sample('no/válida', 'Lila / M'),
                ],
              },
              '/api/plan' => {
                'items': [
                  {
                    'id': 'p1',
                    'application_id': '111',
                    'titulo': 'Video para la muestra verde',
                    'estado': 'planeada',
                    'fecha_plan': '2026-11-20',
                    'rev': 1,
                  },
                ],
              },
              _ => {'items': []},
            };
            return http.Response.bytes(
              utf8.encode(jsonEncode(response)),
              200,
              headers: {'content-type': 'application/json; charset=utf-8'},
            );
          }),
        );
        final ui = CorteUiController(auth: auth);
        addTearDown(() {
          ui.dispose();
          auth.dispose();
        });
        await tester.pumpWidget(
          MaterialApp(
            theme: platform == TargetPlatform.windows
                ? desktopWorkspaceTheme(corteTheme())
                : corteTheme(),
            home: CorteScope(
              controller: ui,
              child: const Scaffold(body: ProductDetailPage(id: '120')),
            ),
          ),
        );
        await tester.pumpAndSettle();

        expect(find.text('Suéter de algodón'), findsOneWidget);
        final pageScroll = find.byType(Scrollable).first;
        final samples = find.text('Tus muestras');
        await tester.scrollUntilVisible(samples, 200, scrollable: pageScroll);
        final plan = find.text('Gestionar avance');
        await tester.scrollUntilVisible(plan, 180, scrollable: pageScroll);
        expect(find.text('Azul / M'), findsOneWidget);
        expect(find.text('Planear video'), findsOneWidget);
        expect(find.text('Verde / XL'), findsOneWidget);
        expect(find.text('Planeada'), findsOneWidget);
        await tester.tap(plan);
        await tester.pumpAndSettle();
        expect(find.text('Editar plan'), findsOneWidget);
        expect(find.text('Video para la muestra verde'), findsOneWidget);
        await tester.tap(find.byTooltip('Cerrar'));
        await tester.pumpAndSettle();

        final invalid = find.text('No se pudo identificar esta muestra.');
        await tester.scrollUntilVisible(invalid, 130, scrollable: pageScroll);
        expect(find.text('Rojo / S'), findsOneWidget);
        expect(find.text('Lila / M'), findsOneWidget);
        final details = find.text('Ver muestra y mensaje');
        final invalidSample = find.widgetWithText(Container, 'Lila / M');
        expect(
          find.descendant(of: invalidSample, matching: details),
          findsNothing,
        );
        final olderSample = find.widgetWithText(Container, 'Rojo / S');
        final olderDetails = find.descendant(
          of: olderSample,
          matching: details,
        );
        expect(olderDetails, findsOneWidget);
        await tester.ensureVisible(olderDetails);
        await tester.tap(olderDetails);
        expect(ui.location, '/muestras/m/_antigua');
        expect(tester.takeException(), isNull);
        await tester.pumpWidget(const SizedBox.shrink());
      },
    );
  }
}
