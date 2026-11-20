import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'corte_icons.dart';
import 'editors.dart';
import 'format.dart';
import 'theme.dart';
import 'video_catalog.dart' show fechaCortaDe;
import 'widgets.dart';

final _productLink = RegExp(
  r'(?:\b[a-z][a-z0-9+.-]*://|//|\bwww\.)[^\s<>]+|\b(?:[a-z0-9-]+\.)+(?:com|mx|net|org|shop|store|co|io)\b[^\s<>]*|(^|\s)/(?:[\w.-]+/)*[\w.?%=&-]+',
  caseSensitive: false,
);

String _productLabel(Object? value) => textOf(value)
    .replaceAll(_productLink, ' ')
    .replaceAll(RegExp(r'\s+'), ' ')
    .replaceAll(RegExp(r'^[\s:·|()\[\]<>–—-]+|[\s:·|()\[\]<>–—-]+$'), '')
    .trim();

Map<String, Map<String, dynamic>> orderCatalog(
  List<Map<String, dynamic>> products,
) => {
  for (final product in products)
    if (textOf(product['product_id']).isNotEmpty)
      textOf(product['product_id']): product,
};

String orderProductLabel(
  Map<String, dynamic> line,
  Map<String, Map<String, dynamic>> catalog,
) {
  final direct = _productLabel(line['producto']);
  if (direct.isNotEmpty) return direct;
  final id = textOf(line['product_id']);
  final product = id.isEmpty ? null : catalog[id];
  final short = _productLabel(product?['titulo_corto']);
  if (short.isNotEmpty) return short;
  final long = _productLabel(product?['titulo']);
  return long.isEmpty ? 'Producto' : long;
}

String shortOrderId(String id) => id.length > 10
    ? '${id.substring(0, 4)}…${id.substring(id.length - 4)}'
    : id;

String? _cachedPhoto(Object? path) {
  final value = textOf(path);
  return value.startsWith('/img/') || value.startsWith('/lan/v1/img/')
      ? value
      : null;
}

bool needsOrderCatalog(Iterable<Map<String, dynamic>> orders) => orders.any(
  (order) => rowsOf(order['lineas']).any(
    (line) =>
        textOf(line['product_id']).isNotEmpty &&
        (_productLabel(line['producto']).isEmpty ||
            _cachedPhoto(line['imagen']) == null),
  ),
);

class OrderTile extends StatelessWidget {
  const OrderTile({
    super.key,
    required this.order,
    this.catalog = const {},
    this.initiallyExpanded = false,
  });

  final Map<String, dynamic> order;
  final Map<String, Map<String, dynamic>> catalog;
  final bool initiallyExpanded;

  String? _image(Map<String, dynamic> line) {
    final id = textOf(line['product_id']);
    final adjacent = id.isEmpty ? null : catalog[id];
    return _cachedPhoto(line['imagen']) ?? _cachedPhoto(adjacent?['imagen']);
  }

  @override
  Widget build(BuildContext context) {
    final lines = rowsOf(order['lineas']);
    final primary = lines.isEmpty ? const <String, dynamic>{} : lines.first;
    final product = orderProductLabel(primary, catalog);
    final id = textOf(order['order_id']);
    final settled = order['estado'] == 'SETTLED';
    final refunded =
        order['estado'] == 'REFUNDED' || order['estado'] == 'NO_DEVUELTA';
    final status = textOf(
      order['estado_etiqueta'],
      textOf(order['estado'], 'Estado sin informar'),
    );
    final day = textOf(order['fecha']);
    final displayDay = DateTime.tryParse(day) == null
        ? date(order['creada_at'])
        : fechaCortaDe(day);
    final commissionLabel = refunded
        ? 'Comisión'
        : settled
        ? 'Comisión liquidada'
        : 'Comisión estimada';
    final commission = refunded
        ? null
        : settled
        ? order['comision_real_centavos']
        : order['comision_estimada_centavos'];
    final tone = settled
        ? context.corte.success
        : refunded
        ? context.corte.danger
        : context.corte.muted;
    final balance = _OrderBalance(
      label: commissionLabel,
      amount: money(commission, decimals: true),
      settled: settled,
    );
    final metadata = Theme.of(context).textTheme.bodySmall;
    return DecoratedBox(
      decoration: BoxDecoration(
        border: Border(bottom: BorderSide(color: context.corte.line)),
      ),
      child: ExpansionTile(
        initiallyExpanded: initiallyExpanded,
        shape: const Border(),
        collapsedShape: const Border(),
        tilePadding: const EdgeInsets.symmetric(vertical: CorteSpace.medium),
        childrenPadding: const EdgeInsets.only(bottom: CorteSpace.large),
        title: LayoutBuilder(
          builder: (context, limits) {
            final wide =
                limits.maxWidth > 450 &&
                MediaQuery.textScalerOf(context).scale(CorteType.label) <= 20;
            return Row(
              crossAxisAlignment: CrossAxisAlignment.center,
              children: [
                _OrderPhoto(path: _image(primary), label: product),
                const SizedBox(width: CorteSpace.medium),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        product,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: Theme.of(context).textTheme.titleMedium,
                      ),
                      const SizedBox(height: CorteSpace.xs),
                      Wrap(
                        spacing: CorteSpace.small,
                        runSpacing: CorteSpace.xs,
                        children: [
                          if (id.isNotEmpty)
                            Text('Pedido ${shortOrderId(id)}', style: metadata),
                          if (lines.length > 1)
                            Text(
                              '+${lines.length - 1} productos',
                              style: metadata,
                            ),
                        ],
                      ),
                      const SizedBox(height: CorteSpace.xs),
                      Wrap(
                        spacing: CorteSpace.small,
                        runSpacing: CorteSpace.xs,
                        children: [
                          DecoratedBox(
                            decoration: BoxDecoration(
                              color: tone.withValues(alpha: .10),
                              borderRadius: BorderRadius.circular(
                                CorteRadius.control,
                              ),
                            ),
                            child: Padding(
                              padding: const EdgeInsets.symmetric(
                                horizontal: CorteSpace.small,
                              ),
                              child: Text(
                                status,
                                style: metadata?.copyWith(
                                  color: tone,
                                  fontWeight: FontWeight.w700,
                                ),
                              ),
                            ),
                          ),
                          Text(displayDay, style: metadata),
                        ],
                      ),
                      if (!wide) ...[
                        const SizedBox(height: CorteSpace.small),
                        balance,
                      ],
                    ],
                  ),
                ),
                if (wide) ...[
                  const SizedBox(width: CorteSpace.medium),
                  balance,
                ],
              ],
            );
          },
        ),
        children: [
          CortePanel(
            padding: const EdgeInsets.all(CorteSpace.large),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                if (id.isNotEmpty) ...[
                  Text('ID completo del pedido', style: metadata),
                  const SizedBox(height: CorteSpace.xs),
                  SelectableText(
                    id,
                    style: Theme.of(context).textTheme.bodyMedium,
                  ),
                  Align(
                    alignment: AlignmentDirectional.centerStart,
                    child: TextButton.icon(
                      icon: const Icon(Icons.copy_outlined, size: 18),
                      label: const Text('Copiar ID'),
                      onPressed: () async {
                        try {
                          await Clipboard.setData(ClipboardData(text: id));
                          if (context.mounted)
                            toast(context, 'ID del pedido copiado');
                        } on PlatformException {
                          if (context.mounted)
                            toast(
                              context,
                              'No se pudo copiar. Selecciona el ID del pedido.',
                            );
                        }
                      },
                    ),
                  ),
                ],
                DefinitionRow(
                  'Total del pedido',
                  money(order['total_centavos'], decimals: true),
                ),
                if (settled)
                  DefinitionRow(
                    'Comisión estimada',
                    money(order['comision_estimada_centavos'], decimals: true),
                  ),
                if (!refunded &&
                    (settled || order['comision_real_centavos'] != null))
                  DefinitionRow(
                    'Comisión real',
                    money(order['comision_real_centavos'], decimals: true),
                  ),
                for (final (index, line) in lines.indexed) ...[
                  const Divider(),
                  Padding(
                    padding: const EdgeInsets.symmetric(
                      vertical: CorteSpace.small,
                    ),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        if (index > 0) ...[
                          _OrderPhoto(
                            path: _image(line),
                            label: orderProductLabel(line, catalog),
                            size: 48,
                          ),
                          const SizedBox(width: CorteSpace.small),
                        ],
                        Expanded(
                          child: Text(
                            orderProductLabel(line, catalog),
                            style: Theme.of(context).textTheme.titleMedium,
                          ),
                        ),
                        const SizedBox(width: CorteSpace.small),
                        Text('× ${integer(line['cantidad'])}'),
                      ],
                    ),
                  ),
                  if (line['isr_centavos'] != null)
                    DefinitionRow(
                      'ISR',
                      money(line['isr_centavos'], decimals: true),
                    ),
                  if (line['iva_centavos'] != null)
                    DefinitionRow(
                      'IVA',
                      money(line['iva_centavos'], decimals: true),
                    ),
                  if (line['es_carrusel'] == true)
                    const InlineNotice(
                      text: 'Video carrusel: puede tener una comisión menor.',
                    ),
                ],
                if (id.isNotEmpty) NotesPanel(entidad: 'orden', entidadId: id),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _OrderBalance extends StatelessWidget {
  const _OrderBalance({
    required this.label,
    required this.amount,
    required this.settled,
  });

  final String label;
  final String amount;
  final bool settled;

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Text(label, style: Theme.of(context).textTheme.bodySmall),
      Text(
        amount,
        style: Theme.of(context).textTheme.titleLarge?.copyWith(
          color: settled ? context.corte.success : context.corte.ink,
          fontFeatures: const [FontFeature.tabularFigures()],
          height: 1.1,
        ),
      ),
    ],
  );
}

class _OrderPhoto extends StatelessWidget {
  const _OrderPhoto({required this.path, required this.label, this.size = 76});

  final String? path;
  final String label;
  final double size;

  @override
  Widget build(BuildContext context) => CortePhoto(
    path,
    width: size,
    height: size * 1.2,
    radius: CorteRadius.control,
    label: 'Foto de $label',
    fallback: DecoratedBox(
      decoration: BoxDecoration(
        color: context.corte.soft,
        border: Border.all(color: context.corte.line),
        borderRadius: BorderRadius.circular(CorteRadius.control),
      ),
      child: CorteIcon(
        CorteIconName.package,
        size: 22,
        color: context.corte.muted,
      ),
    ),
  );
}
