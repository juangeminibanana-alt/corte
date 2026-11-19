import 'package:flutter/material.dart';

import '../app.dart';
import '../domain/domain.dart';
import 'corte_icons.dart';
import 'settings.dart' show confirmCorteSignOut;
import 'theme.dart';
import 'widgets.dart';

const corteDestinations = <(String, String, CorteIconName)>[
  ('/inicio', 'Inicio', CorteIconName.house),
  ('/muestras', 'Muestras', CorteIconName.package),
  ('/tiendas', 'Tiendas', CorteIconName.store),
  ('/ventas', 'Ventas', CorteIconName.chartColumn),
  ('/videos', 'Videos', CorteIconName.squarePlay),
  ('/productos', 'Productos', CorteIconName.shirt),
];

class DesktopShell extends StatefulWidget {
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
  State<DesktopShell> createState() => _DesktopShellState();
}

class _DesktopShellState extends State<DesktopShell> {
  (CorteUiController, String?, String?)? _scope;
  int? _revision;
  Future<DashboardDto>? _dashboard;
  Future<SesionDto>? _session;

  void _loadNavigation(CorteUiController ui) {
    final scope = (ui, ui.repo.ownerScope, ui.repo.cacheScope);
    if (_scope == scope && _revision == ui.revision) return;
    _scope = scope;
    _revision = ui.revision;
    final load = scope.$2 != null && !ui.androidRecovery;
    _dashboard = load ? ui.repo.dashboard() : null;
    _session = load ? ui.repo.sesion() : null;
  }

  @override
  Widget build(BuildContext context) {
    final ui = CorteScope.of(context);
    _loadNavigation(ui);
    final uri = Uri.parse(ui.location);
    final root = uri.pathSegments.isEmpty ? 'inicio' : uri.pathSegments.first;
    final selected = root == 'ordenes' ? 'ventas' : root;
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
                border: Border(right: BorderSide(color: Color(0xFF292A30))),
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
                                rail ? 16 : 28,
                                rail ? 24 : 22,
                                rail ? 15 : 38,
                              ),
                              child: CorteWordmark(
                                markSize: rail ? 32 : 30,
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
                                    horizontal: 18,
                                    vertical: 14,
                                  ),
                                  child: Divider(color: Color(0xFF292A30)),
                                ),
                              FutureBuilder<DashboardDto>(
                                key: ValueKey((_scope, i)),
                                future: i == 1 || i == 2 ? _dashboard : null,
                                builder: (context, snapshot) {
                                  final counts = snapshot.data?.muestras;
                                  final stores = counts?['tiendas_por_avisar'];
                                  final count = switch (i) {
                                    1 => counts?['pendientes'],
                                    2 =>
                                      stores is int && stores > 0
                                          ? stores
                                          : counts?['promesas_vencidas'],
                                    _ => null,
                                  };
                                  return _DesktopDestination(
                                    destination: corteDestinations[i],
                                    selected:
                                        selected ==
                                        corteDestinations[i].$1.substring(1),
                                    count: count is int && count > 0
                                        ? count
                                        : null,
                                    rail: rail,
                                    onTap: () => ui.go(corteDestinations[i].$1),
                                  );
                                },
                              ),
                            ],
                            const SizedBox(height: 24),
                            const Spacer(),
                            _DesktopConnection(
                              offline: ui.auth.state.offline,
                              rail: rail,
                              onSync: widget.syncing ? null : widget.onSync,
                              syncing: widget.syncing,
                            ),
                            _DesktopDestination(
                              destination: (
                                '/ajustes',
                                'Configuración',
                                CorteIconName.settings,
                              ),
                              avatar: FutureBuilder<SesionDto>(
                                key: ValueKey(_scope),
                                future: _session,
                                builder: (context, snapshot) => _AccountIcon(
                                  account: snapshot.data?.cuenta,
                                ),
                              ),
                              selected: const {
                                'ajustes',
                                'notas',
                                'recordatorios',
                              }.contains(root),
                              rail: rail,
                              onTap: () => ui.go('/ajustes'),
                            ),
                            const SizedBox(height: 8),
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
                  onSearch: widget.onSearch,
                  onExit: ui.auth.state.authenticated
                      ? () => confirmCorteSignOut(context)
                      : null,
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
                Expanded(child: widget.body),
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
    this.count,
    this.avatar,
  });

  final (String, String, CorteIconName) destination;
  final bool selected, rail;
  final VoidCallback onTap;
  final int? count;
  final Widget? avatar;

  @override
  Widget build(BuildContext context) => Padding(
    padding: EdgeInsets.symmetric(horizontal: rail ? 8 : 12, vertical: 1),
    child: Tooltip(
      message: destination.$2,
      excludeFromSemantics: true,
      child: Semantics(
        button: true,
        selected: selected,
        label: count == null ? destination.$2 : '${destination.$2}, $count',
        child: AnimatedContainer(
          duration: MediaQuery.disableAnimationsOf(context)
              ? Duration.zero
              : const Duration(milliseconds: 80),
          curve: const Cubic(.2, 0, 0, 1),
          decoration: BoxDecoration(
            color: selected ? CorteColors.coral : Colors.transparent,
            borderRadius: BorderRadius.circular(8),
          ),
          child: Material(
            type: MaterialType.transparency,
            child: InkWell(
              onTap: onTap,
              borderRadius: BorderRadius.circular(8),
              hoverColor: Colors.white.withValues(alpha: .07),
              focusColor: CorteColors.cyan.withValues(alpha: .14),
              child: ExcludeSemantics(
                child: ConstrainedBox(
                  constraints: BoxConstraints(minHeight: rail ? 52 : 44),
                  child: Padding(
                    padding: EdgeInsets.symmetric(
                      horizontal: rail ? 0 : 12,
                      vertical: rail ? 6 : 8,
                    ),
                    child: rail
                        ? Column(
                            mainAxisSize: MainAxisSize.min,
                            mainAxisAlignment: MainAxisAlignment.center,
                            children: [
                              _glyph(),
                              if (avatar == null) ...[
                                const SizedBox(height: 3),
                                Text(
                                  destination.$2,
                                  textAlign: TextAlign.center,
                                  style: TextStyle(
                                    color: selected
                                        ? Colors.white
                                        : const Color(0xFFE0E0E6),
                                    fontWeight: selected
                                        ? FontWeight.w600
                                        : FontWeight.w500,
                                    fontSize: 11,
                                    height: 14 / 11,
                                  ),
                                ),
                              ],
                            ],
                          )
                        : Row(
                            children: [
                              _glyph(),
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
                                    fontSize: 15,
                                    height: 1.35,
                                    fontWeight: selected
                                        ? FontWeight.w700
                                        : FontWeight.w500,
                                  ),
                                ),
                              ),
                              if (count case final amount?) _NavBadge(amount),
                            ],
                          ),
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    ),
  );

  Widget _glyph() =>
      avatar ??
      Stack(
        clipBehavior: Clip.none,
        children: [
          CorteIcon(
            destination.$3,
            size: 20,
            color: selected ? Colors.white : const Color(0xFFE0E0E6),
          ),
          if (rail)
            if (count case final amount?)
              Positioned(top: -8, left: 12, child: _NavBadge(amount)),
        ],
      );
}

class _NavBadge extends StatelessWidget {
  const _NavBadge(this.count);
  final int count;

  @override
  Widget build(BuildContext context) => DecoratedBox(
    decoration: const ShapeDecoration(
      color: Color(0xFF35363E),
      shape: StadiumBorder(side: BorderSide(color: CorteColors.chrome)),
    ),
    child: Padding(
      padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 1),
      child: Text(
        count > 99 ? '99+' : '$count',
        textScaler: TextScaler.noScaling,
        style: const TextStyle(
          color: Colors.white,
          fontWeight: FontWeight.w600,
          fontSize: 11,
          height: 1.3,
        ),
      ),
    ),
  );
}

class _AccountIcon extends StatelessWidget {
  const _AccountIcon({required this.account});
  final JsonMap? account;

  @override
  Widget build(BuildContext context) {
    final photo = account?['avatar'];
    final url = photo is String ? Uri.tryParse(photo) : null;
    final name = account?['username'];
    if (name is! String || name.isEmpty) {
      return const CorteIcon(
        CorteIconName.settings,
        size: 20,
        color: Colors.white,
      );
    }
    final initial = Center(
      child: Text(
        name.characters.first.toUpperCase(),
        style: const TextStyle(color: Colors.white),
      ),
    );
    return Container(
      width: 32,
      height: 32,
      clipBehavior: Clip.antiAlias,
      decoration: BoxDecoration(
        color: const Color(0xFF292B35),
        shape: BoxShape.circle,
        border: Border.all(color: const Color(0xFF3A3C48)),
      ),
      child: url?.scheme == 'https'
          ? Image.network(
              url.toString(),
              fit: BoxFit.cover,
              errorBuilder: (_, _, _) => initial,
            )
          : initial,
    );
  }
}

class _DesktopConnection extends StatelessWidget {
  const _DesktopConnection({
    required this.offline,
    required this.rail,
    required this.onSync,
    required this.syncing,
  });
  final bool offline, rail, syncing;
  final VoidCallback? onSync;

  @override
  Widget build(BuildContext context) {
    final label = offline ? 'Copia sin conexión' : 'En línea';
    final glyph = SizedBox.square(
      dimension: 23,
      child: Stack(
        children: [
          if (syncing)
            const Center(
              child: SizedBox.square(
                dimension: 19,
                child: CircularProgressIndicator(
                  strokeWidth: 2,
                  color: CorteColors.cyan,
                ),
              ),
            )
          else
            const Center(
              child: CorteIcon(
                CorteIconName.refreshCw,
                size: 18,
                color: Colors.white,
              ),
            ),
          if (!syncing)
            Positioned(
              right: 0,
              top: 1,
              child: DecoratedBox(
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: offline
                      ? CorteColors.chromeMuted
                      : const Color(0xFF51D8A6),
                  border: Border.all(color: CorteColors.chrome, width: 2),
                ),
                child: const SizedBox.square(dimension: 11),
              ),
            ),
        ],
      ),
    );
    final tooltip = syncing ? 'Sincronizando' : 'Actualizar datos';
    return Padding(
      padding: EdgeInsets.symmetric(horizontal: rail ? 8 : 12),
      child: rail
          ? Center(
              child: IconButton(
                tooltip: tooltip,
                onPressed: onSync,
                icon: glyph,
              ),
            )
          : Tooltip(
              message: tooltip,
              child: TextButton(
                onPressed: onSync,
                style: TextButton.styleFrom(
                  alignment: Alignment.centerLeft,
                  foregroundColor: CorteColors.chromeMuted,
                  minimumSize: const Size(0, 44),
                ),
                child: Row(
                  children: [
                    glyph,
                    const SizedBox(width: 12),
                    Expanded(child: Text(label)),
                  ],
                ),
              ),
            ),
    );
  }
}

class _DesktopToolbar extends StatelessWidget {
  const _DesktopToolbar({required this.onSearch, required this.onExit});
  final VoidCallback onSearch;
  final VoidCallback? onExit;

  @override
  Widget build(BuildContext context) => SafeArea(
    bottom: false,
    left: false,
    child: Container(
      constraints: const BoxConstraints(minHeight: 56),
      decoration: const BoxDecoration(
        color: CorteColors.chrome,
        border: Border(bottom: BorderSide(color: Color(0xFF292A30))),
      ),
      padding: const EdgeInsets.symmetric(horizontal: 32, vertical: 6),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.end,
        children: [
          Tooltip(
            message: 'Buscar en CUTGC',
            child: SizedBox(
              width: 216,
              child: OutlinedButton(
                onPressed: onSearch,
                style: OutlinedButton.styleFrom(
                  foregroundColor: Colors.white,
                  backgroundColor: const Color(0xFF1C1D23),
                  side: const BorderSide(color: Color(0xFF292A30)),
                  minimumSize: const Size(0, 40),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(6),
                  ),
                  padding: const EdgeInsets.symmetric(
                    horizontal: 12,
                    vertical: 8,
                  ),
                ),
                child: const Row(
                  children: [
                    CorteIcon(
                      CorteIconName.search,
                      size: 18,
                      color: Colors.white,
                    ),
                    SizedBox(width: 10),
                    Expanded(
                      child: Text(
                        'Buscar',
                        style: TextStyle(
                          fontSize: 14,
                          fontWeight: FontWeight.w500,
                        ),
                      ),
                    ),
                    Text(
                      'Ctrl K',
                      style: TextStyle(
                        fontSize: 12,
                        color: CorteColors.chromeMuted,
                        fontWeight: FontWeight.w400,
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
          if (onExit != null) ...[
            const SizedBox(width: 12),
            IconButton(
              onPressed: onExit,
              tooltip: 'Salir de esta cuenta',
              icon: const CorteIcon(
                CorteIconName.logOut,
                size: 18,
                color: Colors.white,
              ),
            ),
          ],
        ],
      ),
    ),
  );
}
