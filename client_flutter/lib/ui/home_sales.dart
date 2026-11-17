import 'package:flutter/material.dart';

import 'format.dart';
import 'theme.dart';

/// Purchase-day totals and the payment calendar remain separate concepts.
class HomeSalesOverview extends StatelessWidget {
  const HomeSalesOverview({super.key, required this.actualidad, this.now});
  final Map<String, dynamic> actualidad;
  final DateTime? now;

  @override
  Widget build(BuildContext context) {
    final today = mapOf(actualidad['hoy']);
    final week = mapOf(actualidad['semana']);
    final payment = mapOf(actualidad['pago_semana']);
    final pending = mapOf(actualidad['pendiente']);
    final mxToday = (now ?? DateTime.now())
        .toUtc()
        .subtract(const Duration(hours: 6))
        .toIso8601String()
        .substring(0, 10);
    final past = today['fecha'] is String && today['fecha'] != mxToday;
    final cards = <Widget>[
      _SalesSummary(
        title: past
            ? 'Ventas del ${_calendar(today['fecha'])}'
            : 'Ventas de hoy',
        icon: Icons.shopping_bag_outlined,
        amount: money(today['ventas_centavos'], decimals: true),
        accent: context.corte.action,
        detail: today['pedidos_validos'] == null
            ? 'Esperando la actualización de tus ventas'
            : '${integer(today['pedidos_validos'])} pedidos · ${integer(today['unidades'])} productos',
        children: [
          Text(
            'Comisión estimada ${money(today['comision_estimada_centavos'], decimals: true)}',
          ),
        ],
      ),
      _SalesSummary(
        title: 'Ventas de la semana',
        icon: Icons.date_range_outlined,
        amount: money(week['ventas_centavos'], decimals: true),
        accent: context.corte.cyanInk,
        detail: week['desde'] == null
            ? 'De lunes a domingo'
            : '${_calendar(week['desde'])} – ${_calendar(week['hasta'])}',
        children: [
          Text(
            'Comisión estimada ${money(week['comision_estimada_centavos'], decimals: true)}',
          ),
        ],
      ),
      _SalesSummary(
        title: 'Próximo pago',
        icon: Icons.account_balance_wallet_outlined,
        amount: payment['monto_centavos'] == null
            ? 'Por confirmar'
            : money(payment['monto_centavos'], decimals: true),
        accent: context.corte.action,
        detail: payment['fecha_programada'] == null
            ? 'Miércoles'
            : 'Miércoles ${_calendar(payment['fecha_programada'])}',
        children: [
          Text(
            'Pendiente de liquidar ${money(pending['comision_por_liquidar_centavos'], decimals: true)}',
          ),
          const SizedBox(height: 6),
          const Text(
            'El saldo pendiente puede abarcar varios pagos. TikTok aún no confirma el importe de este depósito.',
            style: TextStyle(fontSize: 12, height: 1.5),
          ),
        ],
      ),
    ];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        LayoutBuilder(
          builder: (context, limits) {
            final scale = MediaQuery.textScalerOf(context).scale(14) / 14;
            if (limits.maxWidth >= 960 && scale <= 1.6) {
              return IntrinsicHeight(
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    for (var i = 0; i < cards.length; i++) ...[
                      if (i > 0) const SizedBox(width: 16),
                      Expanded(child: cards[i]),
                    ],
                  ],
                ),
              );
            }
            if (limits.maxWidth >= 620 && scale <= 1.6) {
              return Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  IntrinsicHeight(
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        Expanded(child: cards[0]),
                        const SizedBox(width: 16),
                        Expanded(child: cards[1]),
                      ],
                    ),
                  ),
                  const SizedBox(height: 16),
                  cards[2],
                ],
              );
            }
            return Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                for (var i = 0; i < cards.length; i++) ...[
                  if (i > 0) const SizedBox(height: 12),
                  cards[i],
                ],
              ],
            );
          },
        ),
        const SizedBox(height: 10),
        Text(
          past
              ? 'Copia del ${_calendar(today['fecha'])}. Conéctate para actualizar las ventas de hoy.'
              : 'Pedidos pagados · Horario de Ciudad de México',
          style: TextStyle(fontSize: 12, color: context.corte.muted),
        ),
      ],
    );
  }
}

String _calendar(Object? raw) {
  final value = DateTime.tryParse('$raw');
  if (value == null) return '—';
  const months = [
    'ene',
    'feb',
    'mar',
    'abr',
    'may',
    'jun',
    'jul',
    'ago',
    'sep',
    'oct',
    'nov',
    'dic',
  ];
  return '${value.day} ${months[value.month - 1]}';
}

class _SalesSummary extends StatelessWidget {
  const _SalesSummary({
    required this.title,
    required this.icon,
    required this.amount,
    required this.detail,
    required this.accent,
    required this.children,
  });
  final String title, amount, detail;
  final IconData icon;
  final Color accent;
  final List<Widget> children;

  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.all(20),
    decoration: BoxDecoration(
      color: context.corte.soft,
      border: Border.all(color: context.corte.line),
      borderRadius: BorderRadius.circular(8),
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(icon, color: accent, size: 20),
            const SizedBox(width: 9),
            Expanded(
              child: Text(
                title,
                style: const TextStyle(
                  fontSize: 14,
                  height: 1.4,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ),
          ],
        ),
        const SizedBox(height: 16),
        Text(
          amount,
          style: const TextStyle(
            fontSize: 28,
            height: 1.2,
            letterSpacing: -.7,
            fontWeight: FontWeight.w700,
          ),
        ),
        const SizedBox(height: 8),
        Text(
          detail,
          style: TextStyle(
            color: context.corte.muted,
            fontSize: 13,
            height: 1.5,
          ),
        ),
        const SizedBox(height: 14),
        DefaultTextStyle(
          style: TextStyle(
            fontFamily: 'MonaSans',
            color: context.corte.muted,
            fontSize: 13,
            height: 1.5,
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: children,
          ),
        ),
      ],
    ),
  );
}
