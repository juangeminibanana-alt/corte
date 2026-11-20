import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../app.dart';
import 'corte_icons.dart';
import 'theme.dart';
import 'widgets.dart';
import 'work.dart';
import 'catalog.dart';
import 'settings.dart';
import 'planner.dart';
import 'desktop_shell.dart';
import 'navigation.dart';
import 'shop_publisher.dart';

class CorteShell extends StatefulWidget {
  const CorteShell({super.key});
  @override
  State<CorteShell> createState() => _CorteShellState();
}

class _CorteShellState extends State<CorteShell> {
  bool _syncing = false;
  Widget _screen(Uri uri) {
    final parts = uri.pathSegments;
    if (parts.isEmpty || parts[0] == 'inicio') return const HomePage();
    if (parts[0] == 'muestras') {
      if (parts.length > 2 && parts[1] == 'm')
        return SampleDetailPage(id: parts[2]);
      if (parts.length > 1 && parts[1] == 'plan')
        return const BatchPlannerPage();
      if (parts.length > 1 && parts[1] == 'agenda') return const AgendaPage();
      if (parts.length > 1 && parts[1] == 'avisos') {
        return SampleStoreNoticesPage(
          storeKeys: uri.queryParameters['tiendas']
              ?.split(',')
              .where((key) => key.isNotEmpty)
              .toSet(),
        );
      }
      return SamplesPage(
        all: parts.length > 1 && parts[1] == 'todas',
        initialSearch: uri.queryParameters['q'] ?? '',
      );
    }
    if (parts[0] == 'tiendas')
      return parts.length > 1
          ? StoreDetailPage(id: parts[1])
          : const StoresPage();
    if (parts[0] == 'productos')
      return parts.length > 1
          ? ProductDetailPage(id: parts[1])
          : const ProductsPage();
    if (uri.path == shopPublisherRoute) {
      final ui = CorteScope.of(context);
      return ShopPublisherPage(
        key: ValueKey(
          '${ui.repo.ownerScope}:${ui.repo.cacheScope}:${uri.query}',
        ),
        initialProduct: uri.queryParameters['producto'],
      );
    }
    if (parts[0] == 'videos')
      return parts.length > 1
          ? VideoDetailPage(
              id: parts[1],
              desdeTodos: uri.queryParameters['desde'] == 'todos',
            )
          : VideosPage(todos: uri.queryParameters['segmento'] == 'todos');
    if (parts[0] == 'ventas') return const SalesPage();
    if (parts[0] == 'ordenes') return const OrdersPage();
    if (parts[0] == 'ajustes') {
      return SettingsPage(openTikTok: parts.length > 1 && parts[1] == 'tiktok');
    }
    if (parts[0] == 'notas') return const NotesPage();
    if (parts[0] == 'recordatorios') return const RemindersPage();
    return EmptyState(
      'Esta página no está disponible',
      action: TextButton(
        onPressed: () => CorteScope.of(context).go('/inicio'),
        child: const Text('Ir a Inicio'),
      ),
    );
  }

  Future<void> _search() async {
    final controller = TextEditingController();
    final route = DialogRoute<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Buscar en CUTGC'),
        content: SizedBox(
          width: 440,
          child: TextField(
            controller: controller,
            autofocus: true,
            decoration: const InputDecoration(
              labelText: 'Producto, tienda o variante',
              prefixIcon: CorteIcon(CorteIconName.search),
            ),
            onSubmitted: (v) => Navigator.pop(context, v),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Cancelar'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, controller.text),
            child: const Text('Buscar muestras'),
          ),
        ],
      ),
    );
    final value = await Navigator.of(context).push(route);
    await route.completed;
    controller.dispose();
    if (value != null && mounted)
      CorteScope.of(
        context,
      ).go('/muestras/todas?q=${Uri.encodeQueryComponent(value)}');
  }

  Future<void> _sync() async {
    if (_syncing) return;
    setState(() => _syncing = true);
    await runAction(
      context,
      () => CorteScope.of(context).synchronize(),
      success: 'Sincronización iniciada',
    );
    if (mounted) setState(() => _syncing = false);
  }

  @override
  Widget build(BuildContext context) {
    final ui = CorteScope.of(context);
    final mobile = MediaQuery.sizeOf(context).width < 600;
    final uri = Uri.parse(ui.location);
    final root = uri.pathSegments.isEmpty ? 'inicio' : uri.pathSegments.first;
    final active = sectionFor(root);
    final reducedMotion = CorteMotion.reducedOf(context) || ui.androidRecovery;
    final screen = TweenAnimationBuilder<double>(
      key: ValueKey(ui.location),
      tween: Tween(begin: reducedMotion ? 1 : .72, end: 1),
      duration: reducedMotion ? Duration.zero : CorteMotion.view,
      curve: CorteMotion.enter,
      builder: (context, progress, child) => Opacity(
        opacity: progress,
        child: Transform.translate(
          offset: Offset(0, reducedMotion ? 0 : 6 * (1 - progress) / .28),
          child: child,
        ),
      ),
      child: _screen(uri),
    );
    if (!mobile) {
      return CallbackShortcuts(
        bindings: {
          const SingleActivator(LogicalKeyboardKey.keyK, control: true):
              _search,
        },
        child: Focus(
          autofocus: true,
          child: DesktopShell(
            body: screen,
            onSearch: _search,
            onSync: _sync,
            syncing: _syncing,
          ),
        ),
      );
    }
    return Scaffold(
      body: Column(
        children: [
          Material(
            color: CorteColors.chrome,
            child: SafeArea(
              bottom: false,
              child: SizedBox(
                height: 56,
                child: Padding(
                  padding: const EdgeInsets.symmetric(
                    horizontal: CorteSpace.medium,
                  ),
                  child: Row(
                    children: [
                      const Expanded(
                        child: CorteWordmark(markSize: 25, gap: 8),
                      ),
                      IconButton(
                        onPressed: _search,
                        tooltip: 'Buscar en CUTGC',
                        icon: const CorteIcon(
                          CorteIconName.search,
                          color: CorteColors.chromeInk,
                          size: 22,
                        ),
                      ),
                      IconButton(
                        onPressed: _syncing ? null : _sync,
                        tooltip: _syncing
                            ? 'Sincronizando'
                            : 'Actualizar datos',
                        icon: _syncing
                            ? const SizedBox.square(
                                dimension: 19,
                                child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                  color: CorteColors.cyan,
                                ),
                              )
                            : const CorteIcon(
                                CorteIconName.refreshCw,
                                color: CorteColors.chromeMuted,
                                size: 22,
                              ),
                      ),
                      IconButton(
                        onPressed: () => ui.go('/ajustes'),
                        tooltip: 'Ajustes',
                        icon: const CorteIcon(
                          CorteIconName.settings,
                          color: CorteColors.chromeInk,
                          size: 22,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
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
          Expanded(child: screen),
        ],
      ),
      bottomNavigationBar: Material(
        color: CorteColors.chrome,
        shape: const Border(top: BorderSide(color: CorteColors.chromeLine)),
        child: SafeArea(
          top: false,
          child: ConstrainedBox(
            constraints: const BoxConstraints(minHeight: 68),
            child: IntrinsicHeight(
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  for (final item in CorteSection.values)
                    Expanded(
                      child: Semantics(
                        selected: active == item,
                        button: true,
                        child: InkWell(
                          onTap: () => ui.go(item.path),
                          focusColor: CorteColors.cyan.withValues(alpha: .22),
                          hoverColor: CorteColors.chromeSoft,
                          child: Column(
                            mainAxisAlignment: MainAxisAlignment.center,
                            children: [
                              TweenAnimationBuilder<double>(
                                key: ValueKey(active == item),
                                duration: reducedMotion
                                    ? Duration.zero
                                    : CorteMotion.micro,
                                curve: CorteMotion.enter,
                                tween: Tween(
                                  begin: active == item ? .9 : 1,
                                  end: 1,
                                ),
                                builder: (context, scale, child) =>
                                    Transform.scale(scale: scale, child: child),
                                child: CorteIcon(
                                  item.icon,
                                  size: 22,
                                  color: active == item
                                      ? CorteColors.coral
                                      : CorteColors.chromeMuted,
                                ),
                              ),
                              const SizedBox(height: CorteSpace.xs),
                              Text(
                                item.label,
                                textAlign: TextAlign.center,
                                style: TextStyle(
                                  fontSize: CorteType.meta,
                                  fontWeight: FontWeight.w600,
                                  color: active == item
                                      ? CorteColors.actionOnChrome
                                      : CorteColors.chromeInk,
                                ),
                              ),
                              const SizedBox(height: CorteSpace.xs),
                              Container(
                                height: 3,
                                width: 30,
                                decoration: BoxDecoration(
                                  color: active == item
                                      ? CorteColors.coral
                                      : Colors.transparent,
                                  borderRadius: BorderRadius.circular(2),
                                ),
                              ),
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
}
