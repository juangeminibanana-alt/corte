import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../app.dart';
import 'format.dart';
import 'theme.dart';
import 'widgets.dart';
import 'work.dart' show SampleTile, samplePending;

/// Desktop uses the same scoped API data and actions as the phone home screen.
/// Only the composition and information density differ.
class DesktopHomePage extends StatelessWidget {
  const DesktopHomePage({super.key});

  @override
  Widget build(BuildContext context) => ApiData(
    path: '/api/dashboard',
    query: const {'periodo': '30d'},
    builder: (context, data) {
      final ui = CorteScope.of(context);
      final kpis = mapOf(data['kpis']);
      final points = rowsOf(mapOf(data['serie'])['puntos']);
      final stores = rowsOf(data['top_tiendas']);
      return RefreshIndicator(
        onRefresh: () async => ui.refresh(),
        child: ListView(
          padding: const EdgeInsets.fromLTRB(28, 24, 28, 32),
          children: [
            PageTitle(
              'Inicio',
              subtitle: 'Tus resultados y próximos pasos',
              action: OutlinedButton.icon(
                onPressed: () => ui.go('/muestras'),
                icon: const Icon(Icons.inventory_2_outlined, size: 18),
                label: const Text('Ver muestras'),
              ),
            ),
            _DesktopMetrics([
              (
                'Comisión · últimos 30 días',
                money(kpis['comision_total_centavos']),
              ),
              ('Ventas', money(kpis['ventas_centavos'])),
              (
                'Pedidos válidos',
                kpis['pedidos_validos'] == null
                    ? '—'
                    : integer(kpis['pedidos_validos']),
              ),
              (
                'Unidades',
                kpis['unidades'] == null ? '—' : integer(kpis['unidades']),
              ),
            ]),
            const SizedBox(height: 24),
            LayoutBuilder(
              builder: (context, limits) {
                final twoColumns =
                    limits.maxWidth >= 850 &&
                    MediaQuery.textScalerOf(context).scale(14) / 14 <= 1.6;
                final pending = _DesktopPanel(
                  title: 'Tu próximo video',
                  action: TextButton(
                    onPressed: () => ui.go('/muestras'),
                    child: const Text('Ver todas'),
                  ),
                  child: ApiData(
                    path: '/api/muestras',
                    padding: EdgeInsets.zero,
                    builder: (context, response) {
                      final items = rowsOf(
                        response['items'],
                      ).where(samplePending).take(4).toList();
                      if (items.isEmpty) {
                        return const EmptyState(
                          'Estás al día',
                          text: 'Tus muestras pendientes aparecerán aquí.',
                        );
                      }
                      return Column(
                        children: [
                          for (final sample in items)
                            SampleTile(muestra: sample, compact: true),
                        ],
                      );
                    },
                  ),
                );
                final results = Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    _DesktopPanel(
                      title: 'Comisión estimada',
                      subtitle: 'Últimos 30 días',
                      child: _DesktopCommissionChart(points),
                    ),
                    const SizedBox(height: 20),
                    _DesktopPanel(
                      // The server orders this shortlist by attention, not by
                      // earnings. Do not imply an unsupported sales ranking.
                      title: 'Tiendas',
                      action: TextButton(
                        onPressed: () => ui.go('/tiendas'),
                        child: const Text('Ver tiendas'),
                      ),
                      child: stores.isEmpty
                          ? const EmptyState(
                              'Todavía no hay tiendas en este periodo',
                            )
                          : Column(
                              children: [
                                for (final shop in stores.take(3))
                                  _DesktopStoreRow(shop),
                              ],
                            ),
                    ),
                  ],
                );
                if (!twoColumns) {
                  return Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [pending, const SizedBox(height: 24), results],
                  );
                }
                return Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Expanded(flex: 165, child: pending),
                    const SizedBox(width: 24),
                    Expanded(flex: 100, child: results),
                  ],
                );
              },
            ),
          ],
        ),
      );
    },
  );
}

class _DesktopMetrics extends StatelessWidget {
  const _DesktopMetrics(this.metrics);
  final List<(String, String)> metrics;

  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, limits) {
      final scale = MediaQuery.textScalerOf(context).scale(12) / 12;
      final columns = limits.maxWidth >= 700 * scale
          ? 4
          : limits.maxWidth >= 340 * scale
          ? 2
          : 1;
      return Column(
        children: [
          for (var start = 0; start < metrics.length; start += columns) ...[
            if (start > 0) const SizedBox(height: 12),
            IntrinsicHeight(
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  for (
                    var index = start;
                    index < math.min(start + columns, metrics.length);
                    index++
                  ) ...[
                    if (index > start) const SizedBox(width: 14),
                    Expanded(
                      child: Container(
                        padding: const EdgeInsets.all(16),
                        decoration: BoxDecoration(
                          color: context.corte.soft,
                          border: Border.all(color: context.corte.line),
                          borderRadius: BorderRadius.circular(8),
                        ),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              metrics[index].$1,
                              style: TextStyle(
                                fontSize: 12,
                                height: 1.4,
                                color: context.corte.muted,
                              ),
                            ),
                            const SizedBox(height: 8),
                            Text(
                              metrics[index].$2,
                              style: const TextStyle(
                                fontSize: 24,
                                height: 1.25,
                                fontWeight: FontWeight.w600,
                                letterSpacing: -.5,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ],
                ],
              ),
            ),
          ],
        ],
      );
    },
  );
}

class _DesktopPanel extends StatelessWidget {
  const _DesktopPanel({
    required this.title,
    required this.child,
    this.subtitle,
    this.action,
  });
  final String title;
  final String? subtitle;
  final Widget child;
  final Widget? action;

  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.fromLTRB(16, 12, 16, 16),
    decoration: BoxDecoration(
      color: context.corte.surface,
      border: Border.all(color: context.corte.line),
      borderRadius: BorderRadius.circular(8),
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          children: [
            Expanded(
              child: Semantics(
                header: true,
                child: Text(
                  title,
                  style: Theme.of(context).textTheme.titleLarge,
                ),
              ),
            ),
            if (action != null) ...[const SizedBox(width: 8), action!],
          ],
        ),
        if (subtitle != null) ...[
          const SizedBox(height: 2),
          Text(
            subtitle!,
            style: TextStyle(fontSize: 12, color: context.corte.muted),
          ),
        ],
        const SizedBox(height: 12),
        child,
      ],
    ),
  );
}

class _DesktopStoreRow extends StatelessWidget {
  const _DesktopStoreRow(this.shop);
  final Map<String, dynamic> shop;

  @override
  Widget build(BuildContext context) {
    final sales = mapOf(shop['ventas']);
    final commission = sales['comision_estimada_centavos'];
    final key = textOf(shop['tienda_key']);
    final image = textOf(shop['imagen']);
    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: key.isEmpty
            ? null
            : () => CorteScope.of(
                context,
              ).go('/tiendas/${Uri.encodeComponent(key)}'),
        child: Container(
          padding: const EdgeInsets.symmetric(vertical: 12),
          decoration: BoxDecoration(
            border: Border(top: BorderSide(color: context.corte.line)),
          ),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (image.isNotEmpty)
                CortePhoto(
                  image,
                  width: 30,
                  height: 30,
                  label: textOf(shop['nombre']),
                )
              else
                Padding(
                  padding: const EdgeInsets.only(top: 3),
                  child: Icon(
                    Icons.storefront_outlined,
                    size: 20,
                    color: context.corte.muted,
                  ),
                ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      textOf(shop['nombre']),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        fontSize: 13,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    if (commission is num) ...[
                      const SizedBox(height: 3),
                      Text(
                        '${money(commission)} · comisión estimada',
                        style: TextStyle(
                          fontSize: 12,
                          color: context.corte.muted,
                        ),
                      ),
                    ] else if (textOf(shop['salud_porque']).isNotEmpty) ...[
                      const SizedBox(height: 3),
                      Text(
                        textOf(shop['salud_porque']),
                        style: TextStyle(
                          fontSize: 12,
                          color: context.corte.muted,
                        ),
                      ),
                    ],
                  ],
                ),
              ),
              if (key.isNotEmpty) ...[
                const SizedBox(width: 8),
                Icon(
                  Icons.chevron_right_rounded,
                  size: 18,
                  color: context.corte.muted,
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

class _DesktopCommissionChart extends StatelessWidget {
  const _DesktopCommissionChart(this.points);
  final List<Map<String, dynamic>> points;

  @override
  Widget build(BuildContext context) {
    final valid = points
        .where((point) => point['comision_estimada_centavos'] is num)
        .toList();
    if (valid.isEmpty) {
      return const EmptyState('Todavía no hay datos para esta gráfica');
    }
    final values = valid
        .map((point) => intOf(point['comision_estimada_centavos']))
        .toList();
    final high = values.fold<int>(0, math.max);
    final low = values.fold<int>(0, math.min);
    final span = math.max(1, high - low);
    const plotHeight = 148.0;
    final zeroY = high / span * plotHeight;
    final ticks = <int>{0, (valid.length - 1) ~/ 2, valid.length - 1}.toList();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        SizedBox(
          height: plotHeight,
          child: Stack(
            children: [
              for (final y in [0.0, plotHeight / 2, plotHeight - 1])
                Positioned(
                  left: 0,
                  right: 0,
                  top: y,
                  child: Container(height: 1, color: context.corte.line),
                ),
              if (low < 0)
                Positioned(
                  left: 0,
                  right: 0,
                  top: zeroY,
                  child: Container(height: 1, color: context.corte.muted),
                ),
              Row(
                children: [
                  for (var i = 0; i < valid.length; i++)
                    Expanded(
                      child: Tooltip(
                        message:
                            '${textOf(valid[i]['etiqueta'])}: ${money(values[i])}',
                        child: Semantics(
                          label:
                              '${textOf(valid[i]['etiqueta'])}, comisión estimada ${money(values[i])}',
                          child: Padding(
                            padding: const EdgeInsets.symmetric(horizontal: 2),
                            child: SizedBox(
                              height: plotHeight,
                              child: Stack(
                                children: [
                                  if (values[i] != 0)
                                    Positioned(
                                      left: 0,
                                      right: 0,
                                      top: values[i] >= 0
                                          ? (high - values[i]) /
                                                span *
                                                plotHeight
                                          : zeroY,
                                      height: math.max(
                                        2.0,
                                        values[i].abs() / span * plotHeight,
                                      ),
                                      child: DecoratedBox(
                                        decoration: BoxDecoration(
                                          color: values[i] < 0
                                              ? context.corte.danger
                                              : i == valid.length - 1
                                              ? context.corte.cyanInk
                                              : context.corte.action,
                                          borderRadius:
                                              const BorderRadius.vertical(
                                                top: Radius.circular(2),
                                              ),
                                        ),
                                      ),
                                    ),
                                ],
                              ),
                            ),
                          ),
                        ),
                      ),
                    ),
                ],
              ),
            ],
          ),
        ),
        const SizedBox(height: 8),
        Row(
          children: [
            for (var i = 0; i < ticks.length; i++)
              Expanded(
                child: Text(
                  textOf(valid[ticks[i]]['etiqueta']),
                  textAlign: i == 0
                      ? TextAlign.left
                      : i == ticks.length - 1
                      ? TextAlign.right
                      : TextAlign.center,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(fontSize: 12, color: context.corte.muted),
                ),
              ),
          ],
        ),
      ],
    );
  }
}
