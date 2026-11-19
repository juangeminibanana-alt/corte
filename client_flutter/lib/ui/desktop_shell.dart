import 'package:flutter/material.dart';

import '../app.dart';
import 'theme.dart';
import 'widgets.dart';

const corteDestinations = <(String, String, IconData)>[
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
    final title = const {
      'tiendas': 'Tiendas',
      'ordenes': 'Pedidos',
      'videos': 'Videos',
      'productos': 'Productos',
      'ajustes': 'Configuración',
      'notas': 'Notas',
      'recordatorios': 'Recordatorios',
    }[root];
    final rail = MediaQuery.sizeOf(context).width < 1180;
    return Scaffold(
      backgroundColor: context.corte.surface,
      body: Row(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          SizedBox(
            width: rail ? 80 : 248,
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
                                rail ? 24 : 22,
                                rail ? 15 : 26,
                                rail ? 24 : 22,
                                rail ? 18 : 30,
                              ),
                              child: CorteWordmark(
                                markSize: 30,
                                showLabel: !rail,
                              ),
                            ),
                            for (
                              var i = 0;
                              i < corteDestinations.length;
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
                                destination: corteDestinations[i],
                                selected:
                                    selected ==
                                    corteDestinations[i].$1.substring(1),
                                rail: rail,
                                onTap: () => ui.go(corteDestinations[i].$1),
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
                                'Configuración',
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
                        'Sin conexión. CUTGC mostrará la información que ya esté guardada en este dispositivo.',
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
          color: selected ? CorteColors.action : Colors.transparent,
          borderRadius: BorderRadius.circular(8),
          child: InkWell(
            onTap: onTap,
            borderRadius: BorderRadius.circular(8),
            hoverColor: Colors.white.withValues(alpha: .07),
            focusColor: CorteColors.cyan.withValues(alpha: .14),
            child: ExcludeSemantics(
              child: ConstrainedBox(
                constraints: BoxConstraints(minHeight: rail ? 48 : 42),
                child: Padding(
                  padding: EdgeInsets.symmetric(
                    horizontal: rail ? 4 : 13,
                    vertical: rail ? 6 : 10,
                  ),
                  child: rail
                      ? Column(
                          mainAxisSize: MainAxisSize.min,
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [
                            Icon(destination.$3, size: 20, color: Colors.white),
                            const SizedBox(height: 4),
                            Text(
                              destination.$2,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: const TextStyle(
                                color: Colors.white,
                                fontWeight: FontWeight.w600,
                                fontSize: 10,
                                height: 1.1,
                              ),
                            ),
                          ],
                        )
                      : Row(
                          children: [
                            Icon(
                              destination.$3,
                              size: 20,
                              color: selected
                                  ? Colors.white
                                  : CorteColors.chromeMuted,
                            ),
                            const SizedBox(width: 12),
                            Expanded(
                              child: Text(
                                destination.$2,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: TextStyle(
                                  color: selected
                                      ? Colors.white
                                      : CorteColors.chromeMuted,
                                  fontSize: 14,
                                  height: 1.35,
                                  fontWeight: selected
                                      ? FontWeight.w700
                                      : FontWeight.w500,
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
      padding: EdgeInsets.fromLTRB(rail ? 36 : 23, 13, rail ? 36 : 18, 20),
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
  final String? title;
  final VoidCallback onSearch, onSync;
  final bool syncing;

  @override
  Widget build(BuildContext context) => SafeArea(
    bottom: false,
    left: false,
    child: Container(
      constraints: const BoxConstraints(minHeight: 56),
      decoration: const BoxDecoration(
        color: CorteColors.chrome,
        border: Border(bottom: BorderSide(color: Color(0xFF24262D))),
      ),
      child: LayoutBuilder(
        builder: (context, limits) => Padding(
          padding: EdgeInsets.symmetric(
            horizontal: limits.maxWidth < 600 ? 16 : 24,
            vertical: 4,
          ),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.end,
            children: [
              Expanded(
                child: title == null
                    ? const SizedBox.shrink()
                    : Text(
                        title!,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                          fontSize: 13,
                          fontWeight: FontWeight.w600,
                          color: CorteColors.chromeMuted,
                        ),
                      ),
              ),
              const SizedBox(width: 8),
              if (limits.maxWidth >= 550)
                Tooltip(
                  message: 'Buscar en CUTGC',
                  child: SizedBox(
                    width: 180,
                    child: OutlinedButton.icon(
                      onPressed: onSearch,
                      style: OutlinedButton.styleFrom(
                        foregroundColor: Colors.white,
                        backgroundColor: const Color(0xFF202229),
                        side: const BorderSide(color: Color(0xFF363842)),
                        alignment: Alignment.centerLeft,
                        padding: const EdgeInsets.symmetric(
                          horizontal: 14,
                          vertical: 8,
                        ),
                      ),
                      icon: const Icon(Icons.search_rounded, size: 20),
                      label: const Text(
                        'Buscar',
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                  ),
                )
              else
                IconButton(
                  onPressed: onSearch,
                  tooltip: 'Buscar en CUTGC',
                  color: Colors.white,
                  constraints: const BoxConstraints(
                    minWidth: 44,
                    minHeight: 44,
                  ),
                  icon: const Icon(Icons.search_rounded, size: 20),
                ),
              const SizedBox(width: 8),
              if (limits.maxWidth >= 700)
                TextButton.icon(
                  onPressed: syncing ? null : onSync,
                  style: TextButton.styleFrom(
                    foregroundColor: CorteColors.chromeMuted,
                    textStyle: const TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  icon: _SyncIcon(syncing: syncing),
                  label: Text(syncing ? 'Actualizando' : 'Actualizar'),
                )
              else
                IconButton(
                  onPressed: syncing ? null : onSync,
                  color: CorteColors.chromeMuted,
                  tooltip: syncing ? 'Sincronizando' : 'Actualizar datos',
                  constraints: const BoxConstraints(
                    minWidth: 44,
                    minHeight: 44,
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
            color: CorteColors.cyan,
          ),
        )
      : Icon(Icons.sync_rounded, size: 20, color: context.corte.muted);
}
