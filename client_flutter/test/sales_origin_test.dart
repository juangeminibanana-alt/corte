// Datos sintéticos de prueba: nunca contenido de producción.
import 'package:corte/ui/sales_origin.dart';
import 'package:corte/ui/theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// Instante en segundos de una fecha al mediodía de México (UTC−6).
int _epoch(String fecha) =>
    DateTime.parse('${fecha}T12:00:00-06:00').millisecondsSinceEpoch ~/ 1000;

final _ahora = DateTime.utc(2026, 11, 18, 18);

Map<String, dynamic> _historico({bool conPeriodo = true}) => {
  'lineas': 40,
  'por_tipo_contenido': [
    {'tipo': 'VIDEO', 'texto': 'Video', 'lineas': 30},
    {'tipo': null, 'texto': 'Sin dato', 'lineas': 10},
  ],
  'por_tipo_enlace': [
    {'tipo': 'SPECIFIC', 'texto': 'Enlace para un publicador', 'lineas': 39},
    {'tipo': null, 'texto': 'Sin enlace reportado', 'lineas': 1},
  ],
  if (conPeriodo) ...{
    'fuente': 'orders_trace_search_202505_retirada',
    'pedidos': 38,
    'desde_at': _epoch('2026-05-16'),
    'hasta_at': _epoch('2026-08-14'),
  },
};

Map<String, dynamic> _actual({int conEnlace = 5, int sinDato = 3}) => {
  'lineas': 20,
  'con_enlace': conEnlace,
  'por_tipo_enlace': [
    {'tipo': null, 'texto': 'Sin enlace reportado', 'lineas': 20 - conEnlace},
    if (conEnlace > 0)
      {'tipo': 'GENERAL', 'texto': 'Enlace general', 'lineas': conEnlace},
  ],
  'lineas_sin_dato': sinDato,
  'pedidos': 19,
  'fuente': 'orders_search_202410',
  'desde_at': _epoch('2026-09-13'),
  'hasta_at': _epoch('2026-11-17'),
  'capturada_at': _epoch('2026-11-18'),
};

Future<void> _mostrar(WidgetTester tester, Map<String, dynamic> extended) async {
  await tester.pumpWidget(
    MaterialApp(
      theme: corteTheme(),
      home: Scaffold(
        body: ListView(
          children: [SalesOriginTile(extended: extended, ahora: _ahora)],
        ),
      ),
    ),
  );
  if (find.text('Origen de tus ventas').evaluate().isNotEmpty) {
    await tester.tap(find.text('Origen de tus ventas'));
    await tester.pumpAndSettle();
  }
}

void main() {
  testWidgets('solo el histórico: rotulado con su fecha, como antes', (tester) async {
    await _mostrar(tester, {'origen_ventas': _historico()});
    expect(find.text('Histórico hasta el 14 ago'), findsOneWidget);
    expect(find.text(notaOrigen), findsNothing);
    expect(find.text('Video'), findsOneWidget);
    expect(find.text('30 líneas'), findsOneWidget);
    expect(find.text('1 línea'), findsOneWidget);
    expect(find.textContaining('Pedidos del'), findsNothing);
  });

  testWidgets('un hub anterior sin periodo no inventa la fecha', (tester) async {
    await _mostrar(tester, {'origen_ventas': _historico(conPeriodo: false)});
    expect(find.textContaining('Histórico'), findsNothing);
    expect(find.text('Enlace para un publicador'), findsOneWidget);
  });

  testWidgets('con enlaces reportados: grupo reciente primero y aparte del histórico', (
    tester,
  ) async {
    await _mostrar(tester, {
      'origen_ventas': _historico(),
      'origen_ventas_actual': _actual(),
    });
    expect(find.text(notaOrigen), findsOneWidget);
    final reciente = find.text('Pedidos del 13 sep al 17 nov');
    final historico = find.text('Histórico hasta el 14 ago');
    expect(reciente, findsOneWidget);
    expect(historico, findsOneWidget);
    expect(
      tester.getTopLeft(reciente).dy < tester.getTopLeft(historico).dy,
      isTrue,
    );
    expect(find.text('Enlace general'), findsOneWidget);
    expect(find.text('15 líneas'), findsOneWidget);
    // «Sin dato» es una nota aparte, no una fila que parezca otro tipo de enlace.
    expect(find.text('3 líneas más todavía sin este dato'), findsOneWidget);
    expect(find.text('Sin dato todavía'), findsNothing);
    final nota = find.text('3 líneas más todavía sin este dato');
    expect(
      tester.getTopLeft(nota).dy > tester.getTopLeft(find.text('Enlace general')).dy &&
          tester.getTopLeft(nota).dy < tester.getTopLeft(historico).dy,
      isTrue,
    );
    // Los dos «Sin enlace reportado» quedan en su grupo, sin sumarse.
    expect(find.text('Sin enlace reportado'), findsNWidgets(2));
    expect(find.text('16 líneas'), findsNothing);
  });

  testWidgets('si TikTok no reportó ningún enlace no aparece el grupo reciente', (
    tester,
  ) async {
    await _mostrar(tester, {
      'origen_ventas_actual': _actual(conEnlace: 0, sinDato: 0),
    });
    expect(find.text('Origen de tus ventas'), findsNothing);
    await _mostrar(tester, {
      'origen_ventas': _historico(),
      'origen_ventas_actual': _actual(conEnlace: 0),
    });
    expect(find.textContaining('Pedidos del'), findsNothing);
    expect(find.text('Histórico hasta el 14 ago'), findsOneWidget);
    expect(find.textContaining('sin este dato'), findsNothing);
  });

  test('periodoActual y origenActualVisible', () {
    expect(
      periodoActual({
        'desde_at': _epoch('2026-11-17'),
        'hasta_at': _epoch('2026-11-17'),
      }, ahora: _ahora),
      'Pedidos del 17 nov',
    );
    expect(periodoActual({}, ahora: _ahora), 'Pedidos recientes');
    expect(
      periodoActual({
        'desde_at': _epoch('2025-12-30'),
        'hasta_at': _epoch('2026-01-02'),
      }, ahora: _ahora),
      'Pedidos del 30 dic 2025 al 2 ene',
    );
    expect(origenActualVisible({}), isNull);
    expect(origenActualVisible({'origen_ventas_actual': null}), isNull);
    expect(
      origenActualVisible({'origen_ventas_actual': _actual(conEnlace: 0)}),
      isNull,
    );
    expect(
      origenActualVisible({'origen_ventas_actual': _actual()}),
      isNotNull,
    );
  });
}
