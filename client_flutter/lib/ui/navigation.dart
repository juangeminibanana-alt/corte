import 'package:flutter/material.dart';

import '../app.dart';
import 'corte_icons.dart';
import 'theme.dart';
import 'video_catalog.dart' show videosTodos;
import 'widgets.dart';

enum CorteSection {
  today('/inicio', 'Hoy', CorteIconName.house),
  clothes('/muestras', 'Prendas', CorteIconName.shirt),
  money('/ventas', 'Dinero', CorteIconName.chartColumn);

  const CorteSection(this.path, this.label, this.icon);

  final String path, label;
  final CorteIconName icon;
}

CorteSection? sectionFor(String root) => switch (root) {
  'inicio' || 'notas' || 'recordatorios' => CorteSection.today,
  'muestras' || 'tiendas' || 'productos' => CorteSection.clothes,
  'ventas' || 'ordenes' || 'videos' => CorteSection.money,
  _ => null,
};

class CorteSectionLinks extends StatelessWidget {
  const CorteSectionLinks({super.key, required this.uri});

  final Uri uri;

  static const _clothes = [
    ('muestras', '/muestras', 'Muestras'),
    ('tiendas', '/tiendas', 'Por tienda'),
    ('productos', '/productos', 'Productos'),
  ];
  static const _money = [
    ('ventas', '/ventas', 'Resumen'),
    ('ordenes', '/ordenes', 'Pedidos'),
    ('videos', videosTodos, 'Videos'),
  ];

  @override
  Widget build(BuildContext context) {
    final parts = uri.pathSegments;
    if (parts.isEmpty) return const SizedBox.shrink();
    final root = parts.first;
    // Keep the section links on the list views and their filters.
    final isSampleList =
        root == 'muestras' && parts.length == 2 && parts[1] == 'todas';
    if (parts.length != 1 && !isSampleList ||
        root == 'productos' && uri.queryParameters.containsKey('segmento')) {
      return const SizedBox.shrink();
    }
    final links = switch (sectionFor(root)) {
      CorteSection.clothes => _clothes,
      CorteSection.money => _money,
      _ => null,
    };
    if (links == null) return const SizedBox.shrink();

    final ui = CorteScope.of(context);
    return Material(
      color: context.corte.surface,
      child: Padding(
        padding: EdgeInsets.symmetric(
          horizontal: MediaQuery.sizeOf(context).width < 600
              ? CorteSpace.medium
              : CorteSpace.xxl,
        ),
        child: CorteRouteTabs(
          children: [
            for (final (id, path, label) in links)
              CorteRouteTab(
                label,
                key: ValueKey('section-link-$id'),
                selected: root == id,
                onPressed: root == id ? null : () => ui.go(path),
              ),
          ],
        ),
      ),
    );
  }
}
