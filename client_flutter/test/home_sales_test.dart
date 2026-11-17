import 'package:corte/ui/home_sales.dart';
import 'package:corte/ui/theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

final data = <String, dynamic>{
  'hoy': {
    'fecha': '2026-11-16',
    'ventas_centavos': 120050,
    'comision_estimada_centavos': 10025,
    'pedidos_validos': 4,
    'unidades': 5,
  },
  'semana': {
    'desde': '2026-11-16',
    'hasta': '2026-11-22',
    'ventas_centavos': 220050,
    'comision_estimada_centavos': 20025,
  },
  'pendiente': {'comision_por_liquidar_centavos': 700050},
  'pago_semana': {'monto_centavos': null, 'fecha_programada': '2026-11-18'},
};

void main() {
  for (final width in [390.0, 1536.0]) {
    for (final brightness in Brightness.values) {
      testWidgets(
        'separates day, week and unconfirmed payout $width $brightness',
        (tester) async {
          tester.view.physicalSize = Size(width, 1200);
          tester.view.devicePixelRatio = 1;
          addTearDown(tester.view.resetPhysicalSize);
          addTearDown(tester.view.resetDevicePixelRatio);
          await tester.pumpWidget(
            MaterialApp(
              theme: corteTheme(brightness: brightness),
              home: Scaffold(
                body: MediaQuery(
                  data: MediaQueryData(
                    size: Size(width, 1200),
                    textScaler: TextScaler.linear(2),
                  ),
                  child: SingleChildScrollView(
                    child: Padding(
                      padding: const EdgeInsets.all(20),
                      child: HomeSalesOverview(
                        actualidad: data,
                        now: DateTime.utc(2026, 11, 16, 18),
                      ),
                    ),
                  ),
                ),
              ),
            ),
          );
          expect(find.text('Ventas de hoy'), findsOneWidget);
          expect(find.text('Ventas de la semana'), findsOneWidget);
          expect(find.text('Próximo pago'), findsOneWidget);
          expect(find.text('Por confirmar'), findsOneWidget);
          expect(find.text(r'$1,200.50'), findsOneWidget);
          expect(find.text('Miércoles 18 nov'), findsOneWidget);
          expect(find.text(r'Pendiente de liquidar $7,000.50'), findsOneWidget);
          expect(tester.takeException(), isNull);
        },
      );
    }
  }
  testWidgets('previous offline date is never relabeled as today', (
    tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: corteTheme(),
        home: Scaffold(
          body: SingleChildScrollView(
            child: HomeSalesOverview(
              actualidad: data,
              now: DateTime.utc(2026, 11, 17, 18),
            ),
          ),
        ),
      ),
    );
    expect(find.text('Ventas de hoy'), findsNothing);
    expect(find.text('Ventas del 16 nov'), findsOneWidget);
    expect(find.textContaining('Conéctate para actualizar'), findsOneWidget);
  });
}
