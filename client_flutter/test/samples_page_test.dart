import 'dart:convert';
import 'package:corte/app.dart';
import 'package:corte/auth/auth_controller.dart';
import 'package:corte/platform/corte_runtime.dart';
import 'package:corte/ui/desktop.dart';
import 'package:corte/ui/editors.dart';
import 'package:corte/ui/theme.dart';
import 'package:corte/ui/work.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

Map<String, Object?> _sample(
  String id,
  String product,
  String store, {
  String group = 'vencida',
  String? priority = 'alta',
  String stage = 'por_planear',
  bool sent = false,
}) => {
  'application_id': id,
  'grupo': group,
  'prioridad': priority,
  'posicion_cola': int.parse(id),
  'tienda': {'tienda_key': id, 'nombre': store},
  'producto': {'titulo': product},
  'avance': {
    'etapa': stage,
    if (stage == 'planeada') 'fecha_planeada': '2026-11-20',
  },
  'avisos': {'ultimo_enviado_at': sent ? 1790000000 : null},
};

final _items = [
  _sample('1', 'Camiséta de algodón', 'Tienda A', stage: 'planeada'),
  _sample('2', 'Cinturón de piel', 'Tienda B', priority: 'media', sent: true),
  _sample('3', 'Video pendiente de revisión', 'Tienda C', group: 'en_revision'),
  _sample('4', 'Prenda descartada', 'Tienda D', stage: 'no_se_puede'),
];

Future<CorteUiController> _mount(
  WidgetTester tester,
  Widget page, {
  required Size size,
  double textScale = 1,
  List<http.Request>? requests,
}) async {
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
      requests?.add(request);
      final response = switch (request.url.path) {
        '/api/muestras' => {'items': _items, 'total': _items.length},
        '/api/plan' => {'items': []},
        '/api/plantillas' => {
          'items': [
            {
              'id': 'disculpa_y_fecha',
              'nombre': 'Disculpa y fecha',
              'cuerpo': 'Hola, {tienda}. Les comparto el aviso.',
            },
          ],
        },
        '/api/preferencias' => {'firma_mensajes': 'Cuenta de prueba'},
        _ => {
          'error': {'codigo': 'no_encontrado'},
        },
      };
      return http.Response.bytes(
        utf8.encode(jsonEncode(response)),
        response.containsKey('error') ? 404 : 200,
        headers: {'content-type': 'application/json; charset=utf-8'},
      );
    }),
  );
  final controller = CorteUiController(auth: auth);
  addTearDown(() {
    controller.dispose();
    auth.dispose();
  });
  await tester.pumpWidget(
    MaterialApp(
      theme: desktopWorkspaceTheme(corteTheme()),
      builder: (context, child) => MediaQuery(
        data: MediaQuery.of(
          context,
        ).copyWith(textScaler: TextScaler.linear(textScale)),
        child: child!,
      ),
      home: CorteScope(
        controller: controller,
        child: Scaffold(body: page),
      ),
    ),
  );
  await tester.pumpAndSettle();
  return controller;
}

void main() {
  testWidgets(
    'Pendientes groups priority, opens and closes the progress, and filters by accent-insensitive search',
    (tester) async {
      await _mount(tester, const SamplesPage(), size: const Size(1380, 1200));
      expect(find.text('Muestras'), findsOneWidget);
      expect(find.text('2 pendientes'), findsOneWidget);
      expect(find.text('Avisar a mis tiendas'), findsOneWidget);
      expect(find.text('Prioridad alta'), findsOneWidget);
      expect(find.text('Prioridad media'), findsOneWidget);
      expect(find.text('En revisión de TikTok'), findsOneWidget);
      expect(find.text('Prenda descartada'), findsNothing);

      await tester.tap(find.text('Tu avance'));
      await tester.pumpAndSettle();
      expect(find.text('Tiendas avisadas: 1 de 2'), findsOneWidget);
      expect(find.text('Te faltan 2 videos'), findsOneWidget);

      await tester.enterText(find.byType(TextField), 'camiseta algodon');
      await tester.pumpAndSettle();
      expect(find.text('Camiséta de algodón'), findsOneWidget);
      expect(find.text('Prioridad media'), findsNothing);
      expect(find.text('1 resultado'), findsOneWidget);
      await tester.tap(find.text('Limpiar filtros'));
      await tester.pumpAndSettle();
      expect(find.text('Prioridad media'), findsOneWidget);

      await tester.tap(find.text('Vista: Lista'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Tabla'));
      await tester.pumpAndSettle();
      expect(find.text('Variante'), findsWidgets);
      await tester.tap(find.text('Vista: Tabla'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Tablero'));
      await tester.pumpAndSettle();
      expect(
        find.bySemanticsLabel('Tablero de muestras por etapa'),
        findsOneWidget,
      );
      expect(find.text('Por planear'), findsOneWidget);
      expect(find.text('Prioridad alta'), findsNothing);
      await tester.tap(find.text('Vista: Tablero'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Lista'));
      await tester.pumpAndSettle();
      expect(find.text('Prioridad alta'), findsOneWidget);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox.shrink());
    },
    variant: TargetPlatformVariant.only(TargetPlatform.windows),
  );

  testWidgets(
    'Pendientes and Agenda retain their navigation with narrow large text',
    (tester) async {
      final controller = await _mount(
        tester,
        const SamplesPage(),
        size: const Size(320, 1000),
        textScale: 2,
      );
      expect(find.text('2 pendientes'), findsOneWidget);
      expect(find.text('Tu avance'), findsOneWidget);
      expect(find.text('Agenda'), findsOneWidget);
      final list = find
          .byWidgetPredicate(
            (widget) =>
                widget is Scrollable &&
                widget.axisDirection == AxisDirection.down,
          )
          .first;
      await tester.scrollUntilVisible(
        find.text('Vista: Lista').hitTestable(),
        230,
        scrollable: list,
      );
      await tester.tap(find.text('Vista: Lista'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Tablero'));
      await tester.pumpAndSettle();
      final board = find.byKey(const PageStorageKey('muestras-tablero'));
      await tester.scrollUntilVisible(board, 220, scrollable: list);
      await tester.dragFrom(
        tester.getTopLeft(board) + const Offset(144, 20),
        const Offset(-210, 0),
      );
      await tester.pumpAndSettle();
      expect(board, findsOneWidget);
      final lanes = find.descendant(
        of: board,
        matching: find.byType(Scrollable),
      );
      expect(
        tester.state<ScrollableState>(lanes).position.pixels,
        greaterThan(0),
      );

      tester.state<ScrollableState>(list).position.jumpTo(0);
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.text('Agenda'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Agenda'));
      await tester.pumpAndSettle();
      expect(controller.location, '/muestras/agenda');
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox.shrink());
    },
    variant: TargetPlatformVariant.only(TargetPlatform.android),
  );

  testWidgets(
    'Avisar opens the stored template editor without marking a message sent',
    (tester) async {
      final requests = <http.Request>[];
      await _mount(
        tester,
        const SampleStoreNoticesPage(),
        size: const Size(760, 1000),
        requests: requests,
      );
      expect(find.text('1 de 2 tiendas avisadas'), findsOneWidget);
      expect(find.text('Tienda B'), findsNothing);
      await tester.tap(find.text('Tienda A'));
      await tester.pumpAndSettle();
      expect(find.byType(MessageEditorDialog), findsOneWidget);
      expect(find.text('Copiar mensaje'), findsOneWidget);
      expect(
        requests.map((request) => request.url.path),
        contains('/api/plantillas'),
      );
      expect(requests.where((request) => request.method != 'GET'), isEmpty);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox.shrink());
    },
  );

  testWidgets(
    'Selected samples open the local notices flow only for their stores',
    (tester) async {
      final requests = <http.Request>[];
      final controller = await _mount(
        tester,
        const SamplesPage(),
        size: const Size(1380, 1200),
        requests: requests,
      );
      await tester.tap(find.text('Seleccionar'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Camiséta de algodón'));
      await tester.pumpAndSettle();
      expect(find.text('1 seleccionada'), findsOneWidget);
      await tester.tap(find.text('Avisar a estas tiendas'));
      await tester.pumpAndSettle();
      final route = Uri.parse(controller.location);
      expect(route.path, '/muestras/avisos');
      expect(route.queryParameters['tiendas'], '1');
      expect(requests.where((request) => request.method != 'GET'), isEmpty);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox.shrink());
    },
    variant: TargetPlatformVariant.only(TargetPlatform.windows),
  );

  testWidgets('Avisos can be limited to a selection of stores', (tester) async {
    await _mount(
      tester,
      const SampleStoreNoticesPage(storeKeys: {'2'}),
      size: const Size(760, 1000),
    );
    expect(find.text('1 de 1 tiendas avisadas'), findsOneWidget);
    expect(find.text('Tienda A'), findsNothing);
    expect(find.text('Ya estás al día con tus tiendas'), findsOneWidget);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox.shrink());
  });
}
