import 'package:flutter/material.dart';
import '../app.dart';
import 'theme.dart';
import 'widgets.dart';
import 'work.dart';
import 'catalog.dart';
import 'settings.dart';
import 'planner.dart';
import 'desktop.dart';
import 'desktop_shell.dart';

const _destinations = <(String, String, IconData)>[
  ('/inicio', 'Inicio', Icons.home_outlined),
  ('/muestras', 'Muestras', Icons.inventory_2_outlined),
  ('/tiendas', 'Tiendas', Icons.storefront_outlined),
  ('/ventas', 'Ventas', Icons.bar_chart_rounded),
  ('/videos', 'Videos', Icons.smart_display_outlined),
  ('/productos', 'Productos', Icons.sell_outlined),
];

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
    if (parts[0] == 'videos')
      return parts.length > 1
          ? VideoDetailPage(
              id: parts[1],
              desdeTodos: uri.queryParameters['desde'] == 'todos',
            )
          : VideosPage(todos: uri.queryParameters['segmento'] == 'todos');
    if (parts[0] == 'ventas') return const SalesPage();
    if (parts[0] == 'ordenes') return const OrdersPage();
    if (parts[0] == 'ajustes') return const SettingsPage();
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
        title: const Text('Buscar en Corte'),
        content: SizedBox(
          width: 440,
          child: TextField(
            controller: controller,
            autofocus: true,
            decoration: const InputDecoration(
              labelText: 'Producto, tienda o variante',
              prefixIcon: Icon(Icons.search_rounded),
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
    final size = MediaQuery.sizeOf(context);
    final mobile = size.width < 700;
    final rail = size.width >= 700 && size.width < 1180;
    final uri = Uri.parse(ui.location);
    final root = uri.pathSegments.isEmpty ? 'inicio' : uri.pathSegments.first;
    final active = mobile && {'videos', 'productos', 'ordenes'}.contains(root)
        ? 'ventas'
        : root;
    if (useDesktopWorkspace(context)) {
      return DesktopShell(
        body: KeyedSubtree(key: ValueKey(ui.location), child: _screen(uri)),
        onSearch: _search,
        onSync: _sync,
        syncing: _syncing,
      );
    }
    return Scaffold(
      body: Row(
        children: [
          if (!mobile)
            Container(
              width: rail ? 82 : 224,
              color: CorteColors.chrome,
              child: SafeArea(
                child: Column(
                  children: [
                    Padding(
                      padding: EdgeInsets.fromLTRB(
                        rail ? 20 : 24,
                        27,
                        rail ? 20 : 24,
                        34,
                      ),
                      child: Row(
                        children: [
                          const CorteMark(size: 29),
                          if (!rail) ...[
                            const SizedBox(width: 10),
                            const Text(
                              'Corte',
                              style: TextStyle(
                                color: Colors.white,
                                fontSize: 30,
                                fontWeight: FontWeight.w800,
                                letterSpacing: -1,
                              ),
                            ),
                          ],
                        ],
                      ),
                    ),
                    for (var i = 0; i < _destinations.length; i++) ...[
                      if (i == 3)
                        const Padding(
                          padding: EdgeInsets.symmetric(
                            horizontal: 18,
                            vertical: 17,
                          ),
                          child: Divider(color: Color(0xFF292A30)),
                        ),
                      _SidebarItem(
                        destination: _destinations[i],
                        active: root == _destinations[i].$1.substring(1),
                        rail: rail,
                        onTap: () => ui.go(_destinations[i].$1),
                      ),
                    ],
                    const Spacer(),
                    _SidebarItem(
                      destination: (
                        '/ajustes',
                        'Ajustes',
                        Icons.settings_outlined,
                      ),
                      active: root == 'ajustes',
                      rail: rail,
                      onTap: () => ui.go('/ajustes'),
                    ),
                    Padding(
                      padding: const EdgeInsets.all(18),
                      child: Text(
                        ui.auth.state.offline
                            ? 'Copia sin conexión'
                            : 'Conectado a Google',
                        textAlign: TextAlign.center,
                        style: const TextStyle(
                          fontSize: 11,
                          color: CorteColors.chromeMuted,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          Expanded(
            child: Column(
              children: [
                ColoredBox(
                  color: CorteColors.chrome,
                  child: SafeArea(
                    bottom: false,
                    child: SizedBox(
                      height: 56,
                      child: Padding(
                        padding: EdgeInsets.symmetric(
                          horizontal: mobile ? 20 : 28,
                        ),
                        child: Row(
                          children: [
                            if (mobile)
                              const Row(
                                children: [
                                  CorteMark(size: 25),
                                  SizedBox(width: 8),
                                  Text(
                                    'Corte',
                                    style: TextStyle(
                                      color: Colors.white,
                                      fontSize: 25,
                                      fontWeight: FontWeight.w800,
                                    ),
                                  ),
                                ],
                              ),
                            const Spacer(),
                            IconButton(
                              onPressed: _search,
                              tooltip: 'Buscar en Corte',
                              icon: const Icon(
                                Icons.search_rounded,
                                color: Colors.white,
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
                                  : const Icon(
                                      Icons.sync_rounded,
                                      color: CorteColors.chromeMuted,
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
                        'Sin conexión. Corte mostrará la información que ya esté guardada en este dispositivo.',
                  ),
                if (!ui.storageAvailable)
                  const InlineNotice(
                    text:
                        'No está disponible la copia local. Mantén conexión para guardar cambios.',
                  ),
                Expanded(
                  child: KeyedSubtree(
                    key: ValueKey(ui.location),
                    child: _screen(uri),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
      bottomNavigationBar: mobile
          ? ColoredBox(
              color: CorteColors.chrome,
              child: SafeArea(
                top: false,
                child: SizedBox(
                  height: 68,
                  child: Row(
                    children: [
                      for (final item in [
                        _destinations[0],
                        _destinations[1],
                        _destinations[2],
                        _destinations[3],
                        ('/ajustes', 'Más', Icons.more_horiz_rounded),
                      ])
                        Expanded(
                          child: Semantics(
                            selected: active == item.$1.substring(1),
                            child: InkWell(
                              onTap: () => ui.go(item.$1),
                              child: Column(
                                mainAxisAlignment: MainAxisAlignment.center,
                                children: [
                                  Icon(
                                    item.$3,
                                    size: 24,
                                    color: active == item.$1.substring(1)
                                        ? CorteColors.coral
                                        : Colors.white,
                                  ),
                                  const SizedBox(height: 5),
                                  Text(
                                    item.$2,
                                    style: TextStyle(
                                      fontSize: 11,
                                      fontWeight: FontWeight.w600,
                                      color: active == item.$1.substring(1)
                                          ? const Color(0xFFFF5275)
                                          : Colors.white,
                                    ),
                                  ),
                                  const SizedBox(height: 5),
                                  Container(
                                    height: 3,
                                    width: 26,
                                    decoration: BoxDecoration(
                                      color: active == item.$1.substring(1)
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
            )
          : null,
    );
  }
}

class _SidebarItem extends StatelessWidget {
  const _SidebarItem({
    required this.destination,
    required this.active,
    required this.rail,
    required this.onTap,
  });
  final (String, String, IconData) destination;
  final bool active, rail;
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 3),
    child: Material(
      color: active ? CorteColors.action : Colors.transparent,
      borderRadius: BorderRadius.circular(8),
      child: Semantics(
        selected: active,
        child: InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(8),
          child: Padding(
            padding: EdgeInsets.symmetric(
              horizontal: rail ? 4 : 12,
              vertical: 13,
            ),
            child: rail
                ? Tooltip(
                    message: destination.$2,
                    child: Column(
                      children: [
                        Icon(destination.$3, size: 22, color: Colors.white),
                        const SizedBox(height: 6),
                        Text(
                          destination.$2,
                          maxLines: 1,
                          style: const TextStyle(
                            color: Colors.white,
                            fontSize: 9,
                          ),
                        ),
                      ],
                    ),
                  )
                : Row(
                    children: [
                      Icon(destination.$3, size: 22, color: Colors.white),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Text(
                          destination.$2,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                            color: Colors.white,
                            fontSize: 15,
                            fontWeight: FontWeight.w600,
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
