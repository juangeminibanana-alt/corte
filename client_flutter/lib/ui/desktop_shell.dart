import 'package:flutter/material.dart';

import '../app.dart';
import 'theme.dart';
import 'widgets.dart';

const _desktopDestinations = <(String, String, IconData)>[
  ('/inicio', 'Inicio', Icons.home_outlined),
  ('/muestras', 'Muestras', Icons.inventory_2_outlined),
  ('/tiendas', 'Tiendas', Icons.storefront_outlined),
  ('/ventas', 'Ventas', Icons.bar_chart_rounded),
  ('/videos', 'Videos', Icons.smart_display_outlined),
  ('/productos', 'Productos', Icons.sell_outlined),
];

/// A desktop frame with independent density, while keeping the phone shell and
/// the user's system text scaling unchanged.
class DesktopShell extends StatelessWidget {
  const DesktopShell({
    super.key,
    required this.body,
    required this.onSearch,
    required this.onSync,
    required this.syncing,
  });

  final Widget body;
  final VoidCallback onSearch, onSync;
  final bool syncing;

  @override
  Widget build(BuildContext context) {
    final ui = CorteScope.of(context);
    final uri = Uri.parse(ui.location);
    final root = uri.pathSegments.isEmpty ? 'inicio' : uri.pathSegments.first;
    final selected = root == 'ordenes' ? 'ventas' : root;
    final title =
        const {
          'inicio': 'Inicio',
          'muestras': 'Muestras',
          'tiendas': 'Tiendas',
          'ventas': 'Ventas',
          'ordenes': 'Pedidos',
          'videos': 'Videos',
          'productos': 'Productos',
          'ajustes': 'Ajustes',
          'notas': 'Notas',
          'recordatorios': 'Recordatorios',
        }[root] ??
        'Corte';
    final rail = MediaQuery.sizeOf(context).width < 1120;
    return Scaffold(
      backgroundColor: context.corte.surface,
      body: Row(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          SizedBox(
            width: rail ? 72 : 196,
            child: DecoratedBox(
              decoration: const BoxDecoration(
                color: CorteColors.chrome,
                border: Border(right: BorderSide(color: Color(0xFF24262D))),
              ),
              child: SafeArea(
                right: false,
                child: LayoutBuilder(
                  builder: (context, limits) => SingleChildScrollView(
                    child: ConstrainedBox(
                      constraints: BoxConstraints(minHeight: limits.maxHeight),
                      child: IntrinsicHeight(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.stretch,
                          children: [
                            Padding(
                              padding: EdgeInsets.fromLTRB(
                                rail ? 22 : 20,
                                23,
                                rail ? 22 : 20,
                                27,
                              ),
                              child: Row(
                                children: [
                                  const CorteMark(size: 26),
                                  if (!rail) ...[
                                    const SizedBox(width: 9),
                                    const Flexible(
                                      child: Text(
                                        'Corte',
                                        maxLines: 1,
                                        overflow: TextOverflow.ellipsis,
                                        style: TextStyle(
                                          fontSize: 22,
                                          height: 1.2,
                                          fontWeight: FontWeight.w700,
                                          letterSpacing: -.6,
                                          color: Colors.white,
                                        ),
                                      ),
                                    ),
                                  ],
                                ],
                              ),
                            ),
                            for (
                              var i = 0;
                              i < _desktopDestinations.length;
                              i++
                            ) ...[
                              if (i == 3)
                                const Padding(
                                  padding: EdgeInsets.symmetric(
                                    horizontal: 20,
                                    vertical: 16,
                                  ),
                                  child: Divider(color: Color(0xFF292B32)),
                                ),
                              _DesktopDestination(
                                destination: _desktopDestinations[i],
                                selected:
                                    selected ==
                                    _desktopDestinations[i].$1.substring(1),
                                rail: rail,
                                onTap: () => ui.go(_desktopDestinations[i].$1),
                              ),
                            ],
                            const SizedBox(height: 24),
                            const Spacer(),
                            const Padding(
                              padding: EdgeInsets.fromLTRB(20, 0, 20, 12),
                              child: Divider(color: Color(0xFF292B32)),
                            ),
                            _DesktopDestination(
                              destination: (
                                '/ajustes',
                                'Ajustes',
                                Icons.settings_outlined,
                              ),
                              selected: const {
                                'ajustes',
                                'notas',
                                'recordatorios',
                              }.contains(root),
                              rail: rail,
                              onTap: () => ui.go('/ajustes'),
                            ),
                            _DesktopConnection(
                              offline: ui.auth.state.offline,
                              rail: rail,
                            ),
                          ],
                        ),
                      ),
                    ),
                  ),
                ),
              ),
            ),
          ),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                _DesktopToolbar(
                  title: title,
                  onSearch: onSearch,
                  onSync: onSync,
                  syncing: syncing,
                ),
                if (ui.auth.state.offline)
                  const InlineNotice(
                    text:
                        'Sin conexión. Corte mostrará la información que ya esté guardada en este dispositivo.',
                  ),
                if (!ui.storageAvailable)
                  const InlineNotice(
                    text:
                        'No está disponible la copia local. Mantén conexión para guardar cambios.',
                  ),
                Expanded(child: body),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _DesktopDestination extends StatelessWidget {
  const _DesktopDestination({
    required this.destination,
    required this.selected,
    required this.rail,
    required this.onTap,
  });

  final (String, String, IconData) destination;
  final bool selected, rail;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
    child: Tooltip(
      message: destination.$2,
      excludeFromSemantics: true,
      child: Semantics(
        button: true,
        selected: selected,
        label: destination.$2,
        child: Material(
          color: selected
              ? CorteColors.coral.withValues(alpha: .12)
              : Colors.transparent,
          borderRadius: BorderRadius.circular(6),
          child: InkWell(
            onTap: onTap,
            borderRadius: BorderRadius.circular(6),
            hoverColor: Colors.white.withValues(alpha: .045),
            focusColor: CorteColors.cyan.withValues(alpha: .12),
            child: Stack(
              children: [
                if (selected)
                  Positioned(
                    left: 0,
                    top: 8,
                    bottom: 8,
                    child: Container(
                      width: 3,
                      decoration: BoxDecoration(
                        color: CorteColors.coral,
                        borderRadius: BorderRadius.circular(3),
                      ),
                    ),
                  ),
                ExcludeSemantics(
                  child: ConstrainedBox(
                    constraints: const BoxConstraints(minHeight: 42),
                    child: Padding(
                      padding: EdgeInsets.symmetric(
                        horizontal: rail ? 18 : 15,
                        vertical: 10,
                      ),
                      child: Row(
                        children: [
                          Icon(
                            destination.$3,
                            size: 20,
                            color: selected
                                ? Colors.white
                                : CorteColors.chromeMuted,
                          ),
                          if (!rail) ...[
                            const SizedBox(width: 12),
                            Expanded(
                              child: Text(
                                destination.$2,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: TextStyle(
                                  fontSize: 13,
                                  height: 1.4,
                                  fontWeight: selected
                                      ? FontWeight.w600
                                      : FontWeight.w500,
                                  color: selected
                                      ? Colors.white
                                      : CorteColors.chromeMuted,
                                ),
                              ),
                            ),
                          ],
                        ],
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
  );
}

class _DesktopConnection extends StatelessWidget {
  const _DesktopConnection({required this.offline, required this.rail});
  final bool offline, rail;

  @override
  Widget build(BuildContext context) {
    final label = offline ? 'Copia sin conexión' : 'Conectado a Google';
    return Padding(
      padding: EdgeInsets.fromLTRB(rail ? 31 : 23, 13, rail ? 31 : 18, 20),
      child: Tooltip(
        message: label,
        excludeFromSemantics: true,
        child: Semantics(
          label: label,
          child: ExcludeSemantics(
            child: Row(
              children: [
                Container(
                  width: 7,
                  height: 7,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    color: offline ? CorteColors.chromeMuted : CorteColors.cyan,
                  ),
                ),
                if (!rail) ...[
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      label,
                      style: const TextStyle(
                        fontSize: 11,
                        height: 1.4,
                        color: CorteColors.chromeMuted,
                      ),
                    ),
                  ),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _DesktopToolbar extends StatelessWidget {
  const _DesktopToolbar({
    required this.title,
    required this.onSearch,
    required this.onSync,
    required this.syncing,
  });
  final String title;
  final VoidCallback onSearch, onSync;
  final bool syncing;

  @override
  Widget build(BuildContext context) => SafeArea(
    bottom: false,
    left: false,
    child: Container(
      constraints: const BoxConstraints(minHeight: 52),
      decoration: BoxDecoration(
        color: context.corte.surface,
        border: Border(bottom: BorderSide(color: context.corte.line)),
      ),
      child: LayoutBuilder(
        builder: (context, limits) => Padding(
          padding: EdgeInsets.symmetric(
            horizontal: limits.maxWidth < 600 ? 16 : 24,
            vertical: 4,
          ),
          child: Row(
            children: [
              Expanded(
                child: Text(
                  title,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    fontSize: 13,
                    height: 1.4,
                    fontWeight: FontWeight.w600,
                    color: context.corte.muted,
                  ),
                ),
              ),
              const SizedBox(width: 8),
              IconButton(
                onPressed: onSearch,
                tooltip: 'Buscar en Corte',
                constraints: const BoxConstraints(minWidth: 40, minHeight: 40),
                icon: Icon(
                  Icons.search_rounded,
                  size: 20,
                  color: context.corte.muted,
                ),
              ),
              const SizedBox(width: 4),
              if (limits.maxWidth >= 700)
                TextButton.icon(
                  onPressed: syncing ? null : onSync,
                  style: TextButton.styleFrom(
                    foregroundColor: context.corte.muted,
                    textStyle: const TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w500,
                    ),
                  ),
                  icon: _SyncIcon(syncing: syncing),
                  label: Text(syncing ? 'Actualizando' : 'Actualizar'),
                )
              else
                IconButton(
                  onPressed: syncing ? null : onSync,
                  tooltip: syncing ? 'Sincronizando' : 'Actualizar datos',
                  constraints: const BoxConstraints(
                    minWidth: 40,
                    minHeight: 40,
                  ),
                  icon: _SyncIcon(syncing: syncing),
                ),
            ],
          ),
        ),
      ),
    ),
  );
}

class _SyncIcon extends StatelessWidget {
  const _SyncIcon({required this.syncing});
  final bool syncing;

  @override
  Widget build(BuildContext context) => syncing
      ? SizedBox.square(
          dimension: 18,
          child: CircularProgressIndicator(
            strokeWidth: 2,
            color: context.corte.cyanInk,
          ),
        )
      : Icon(Icons.sync_rounded, size: 20, color: context.corte.muted);
}
