// «Origen de tus ventas» de la ficha completa (contrato rev. 7), en dos grupos que nunca se suman: los pedidos
// recientes con el enlace que reporta orders/search 202410 (`origen_ventas_actual`) y el histórico cerrado de
// orders/trace/search (`origen_ventas`, retirada el 15/08/2026). El grupo reciente solo aparece si TikTok reportó algún
// enlace: Corte no crea enlaces, y un grupo entero de «Sin enlace reportado» no dice de dónde vino ninguna venta. Un hub
// anterior no manda `origen_ventas_actual` y el mosaico queda como antes.
import 'package:flutter/material.dart';
import 'format.dart';
import 'theme.dart';
import 'video_catalog.dart';
import 'widgets.dart';

const notaOrigen =
    'Según lo que TikTok reporta de cada pedido. «Sin enlace reportado» no dice de dónde vino la venta.';

/// El grupo reciente si se muestra (al menos un enlace reportado en líneas observadas), o null.
Map<String, dynamic>? origenActualVisible(Map<String, dynamic> extended) {
  final a = mapOf(extended['origen_ventas_actual']);
  final enlaces = a['con_enlace'], lineas = a['lineas'];
  return enlaces is num &&
          enlaces > 0 &&
          lineas is num &&
          lineas > 0 &&
          rowsOf(a['por_tipo_enlace']).isNotEmpty
      ? a
      : null;
}

/// 'Pedidos del 13 sep al 17 nov' ('Pedidos del 13 sep' si es un solo día), en hora de México.
String periodoActual(Map<String, dynamic> a, {DateTime? ahora}) {
  final desde = a['desde_at'], hasta = a['hasta_at'];
  if (desde is! num || hasta is! num) return 'Pedidos recientes';
  final d = fechaDeInstante(desde, ahora: ahora),
      h = fechaDeInstante(hasta, ahora: ahora);
  return d == h ? 'Pedidos del $d' : 'Pedidos del $d al $h';
}

String lineasTexto(Object? n) =>
    '${integer(n)} ${intOf(n) == 1 ? 'línea' : 'líneas'}';

class SalesOriginTile extends StatelessWidget {
  const SalesOriginTile({super.key, required this.extended, this.ahora});
  final Map<String, dynamic> extended;

  /// Solo para pruebas: el «hoy» que decide si la fecha lleva el año.
  final DateTime? ahora;

  @override
  Widget build(BuildContext context) {
    final actual = origenActualVisible(extended);
    final historico = mapOf(extended['origen_ventas']);
    if (actual == null && historico.isEmpty) return const SizedBox.shrink();
    final hasta = historico['hasta_at'];
    final rotuloHistorico = hasta is num
        ? 'Histórico hasta el ${fechaDeInstante(hasta, ahora: ahora)}'
        : 'Histórico';
    return ExpansionTile(
      title: const Text('Origen de tus ventas'),
      subtitle: actual == null && hasta is num ? Text(rotuloHistorico) : null,
      tilePadding: EdgeInsets.zero,
      expandedCrossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (actual != null) ...[
          Text(notaOrigen, style: TextStyle(color: context.corte.muted)),
          _Grupo(periodoActual(actual, ahora: ahora)),
          for (final o in rowsOf(actual['por_tipo_enlace']))
            DefinitionRow(textOf(o['texto']), lineasTexto(o['lineas'])),
          // Nota aparte, no una fila más: no es un tipo de enlace y puede incluir pedidos posteriores al periodo.
          if (intOf(actual['lineas_sin_dato']) > 0)
            Text(
              '${lineasTexto(actual['lineas_sin_dato'])} más todavía sin este dato',
              style: TextStyle(color: context.corte.muted),
            ),
        ],
        if (historico.isNotEmpty) ...[
          if (actual != null) _Grupo(rotuloHistorico),
          for (final o in rowsOf(historico['por_tipo_contenido']))
            DefinitionRow(textOf(o['texto']), lineasTexto(o['lineas'])),
          for (final o in rowsOf(historico['por_tipo_enlace']))
            DefinitionRow(textOf(o['texto']), lineasTexto(o['lineas'])),
        ],
      ],
    );
  }
}

class _Grupo extends StatelessWidget {
  const _Grupo(this.texto);
  final String texto;
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(top: 14, bottom: 2),
    child: Semantics(
      header: true,
      child: Text(texto, style: Theme.of(context).textTheme.titleSmall),
    ),
  );
}
