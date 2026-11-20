import 'package:flutter/material.dart';

import '../app.dart';
import '../domain/domain.dart';
import 'corte_icons.dart';
import 'navigation.dart';
import 'theme.dart';
import 'widgets.dart';

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
    final selected = sectionFor(root);
    final rail = MediaQuery.sizeOf(context).width < 1180;
    return Scaffold(
      backgroundColor: context.corte.canvas,
      body: Row(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          SizedBox(
            width: rail ? 80 : 248,
            child: DecoratedBox(
              decoration: const BoxDecoration(
                color: CorteColors.chrome,
                border: Border(
                  right: BorderSide(color: CorteColors.chromeLine),
                ),
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
                            for (final destination in CorteSection.values)
                              FutureBuilder<DashboardDto>(
                                key: ValueKey((_scope, destination)),
                                future: destination == CorteSection.clothes
                                    ? _dashboard
                                    : null,
                                builder: (context, snapshot) {
                                  final count =
                                      snapshot.data?.muestras?['pendientes'];
                                  return _DesktopDestination(
                                    destination: destination,
                                    selected: selected == destination,
                                    count: count is int && count > 0
                                        ? count
                                        : null,
                                    rail: rail,
                                    onTap: () => ui.go(destination.path),
                                  );
                                },
                              ),
                            const SizedBox(height: 24),
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
                  onSync: widget.syncing ? null : widget.onSync,
                  syncing: widget.syncing,
                  onSettings: () => ui.go('/ajustes'),
                  account: FutureBuilder<SesionDto>(
                    key: ValueKey(_scope),
                    future: _session,
                    builder: (context, snapshot) =>
                        _AccountIcon(account: snapshot.data?.cuenta),
                  ),
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
                CorteSectionLinks(uri: uri),
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
  });

  final CorteSection destination;
  final bool selected, rail;
  final VoidCallback onTap;
  final int? count;

  @override
  Widget build(BuildContext context) => Padding(
    padding: EdgeInsets.symmetric(horizontal: rail ? 8 : 12, vertical: 1),
    child: Tooltip(
      message: destination.label,
      excludeFromSemantics: true,
      child: Semantics(
        button: true,
        selected: selected,
        label: count == null
            ? destination.label
            : '${destination.label}, $count',
        child: AnimatedContainer(
          duration: CorteMotion.reducedOf(context)
              ? Duration.zero
              : CorteMotion.micro,
          curve: CorteMotion.enter,
          decoration: BoxDecoration(
            color: selected ? CorteColors.action : Colors.transparent,
            borderRadius: BorderRadius.circular(CorteRadius.control),
          ),
          child: Material(
            type: MaterialType.transparency,
            child: InkWell(
              onTap: onTap,
              borderRadius: BorderRadius.circular(CorteRadius.control),
              hoverColor: CorteColors.chromeInk.withValues(alpha: .08),
              focusColor: CorteColors.cyan.withValues(alpha: .22),
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
                              const SizedBox(height: 3),
                              Text(
                                destination.label,
                                textAlign: TextAlign.center,
                                style: TextStyle(
                                  color: selected
                                      ? CorteColors.onAction
                                      : CorteColors.chromeMuted,
                                  fontWeight: selected
                                      ? FontWeight.w600
                                      : FontWeight.w500,
                                  fontSize: CorteType.meta,
                                ),
                              ),
                            ],
                          )
                        : Row(
                            children: [
                              _glyph(),
                              const SizedBox(width: 12),
                              Expanded(
                                child: Text(
                                  destination.label,
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                  style: TextStyle(
                                    color: selected
                                        ? CorteColors.onAction
                                        : CorteColors.chromeMuted,
                                    fontSize: CorteType.label,
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

  Widget _glyph() => Stack(
    clipBehavior: Clip.none,
    children: [
      CorteIcon(
        destination.icon,
        size: 20,
        color: selected ? CorteColors.onAction : CorteColors.chromeMuted,
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
      color: CorteColors.chromeSoft,
      shape: StadiumBorder(side: BorderSide(color: CorteColors.chrome)),
    ),
    child: Padding(
      padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 1),
      child: Text(
        count > 99 ? '99+' : '$count',
        textScaler: TextScaler.noScaling,
        style: const TextStyle(
          color: CorteColors.chromeInk,
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
        color: CorteColors.chromeInk,
      );
    }
    final initial = Center(
      child: Text(
        name.characters.first.toUpperCase(),
        style: const TextStyle(color: CorteColors.chromeInk),
      ),
    );
    return Container(
      width: 32,
      height: 32,
      clipBehavior: Clip.antiAlias,
      decoration: BoxDecoration(
        color: CorteColors.chromeSoft,
        shape: BoxShape.circle,
        border: Border.all(color: CorteColors.chromeLine),
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

class _DesktopToolbar extends StatelessWidget {
  const _DesktopToolbar({
    required this.onSearch,
    required this.onSync,
    required this.syncing,
    required this.onSettings,
    required this.account,
  });

  final VoidCallback onSearch, onSettings;
  final VoidCallback? onSync;
  final bool syncing;
  final Widget account;

  @override
  Widget build(BuildContext context) => SafeArea(
    bottom: false,
    left: false,
    child: Container(
      constraints: const BoxConstraints(minHeight: 56),
      decoration: const BoxDecoration(
        color: CorteColors.chrome,
        border: Border(bottom: BorderSide(color: CorteColors.chromeLine)),
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
                  foregroundColor: CorteColors.chromeInk,
                  backgroundColor: CorteColors.chromeSoft,
                  side: const BorderSide(color: CorteColors.chromeLine),
                  minimumSize: const Size(0, 40),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(CorteRadius.control),
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
                      color: CorteColors.chromeInk,
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
                        fontSize: CorteType.meta,
                        color: CorteColors.chromeMuted,
                        fontWeight: FontWeight.w400,
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
          const SizedBox(width: 8),
          IconButton(
            onPressed: onSync,
            tooltip: syncing ? 'Sincronizando' : 'Actualizar datos',
            icon: syncing
                ? const SizedBox.square(
                    dimension: 19,
                    child: CircularProgressIndicator(
                      strokeWidth: 2,
                      color: CorteColors.cyan,
                    ),
                  )
                : const CorteIcon(
                    CorteIconName.refreshCw,
                    size: 20,
                    color: CorteColors.chromeInk,
                  ),
          ),
          IconButton(onPressed: onSettings, tooltip: 'Ajustes', icon: account),
        ],
      ),
    ),
  );
}
