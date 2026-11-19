import 'package:flutter/material.dart';
import '../app.dart';
import 'theme.dart';
import 'widgets.dart';
import 'work.dart';
import 'catalog.dart';
import 'settings.dart';
import 'planner.dart';
import 'desktop_shell.dart';

const _salesDestinations = <(String, String)>[
  ('ventas', 'Resumen'),
  ('videos', 'Videos'),
  ('productos', 'Productos'),
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
    final mobile = MediaQuery.sizeOf(context).width < 600;
    final uri = Uri.parse(ui.location);
    final root = uri.pathSegments.isEmpty ? 'inicio' : uri.pathSegments.first;
    final active = {'videos', 'productos', 'ordenes'}.contains(root)
        ? 'ventas'
        : root;
    if (!mobile) {
      return DesktopShell(
        body: KeyedSubtree(key: ValueKey(ui.location), child: _screen(uri)),
        onSearch: _search,
        onSync: _sync,
        syncing: _syncing,
      );
    }
    return Scaffold(
      body: Column(
        children: [
          ColoredBox(
            color: CorteColors.chrome,
            child: SafeArea(
              bottom: false,
              child: SizedBox(
                height: 56,
                child: Padding(
                  padding: EdgeInsets.symmetric(horizontal: 20),
                  child: Row(
                    children: [
                      const Expanded(
                        child: CorteWordmark(markSize: 25, gap: 8),
                      ),
                      IconButton(
                        onPressed: _search,
                        tooltip: 'Buscar en CUTGC',
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
                  'Sin conexión. CUTGC mostrará la información que ya esté guardada en este dispositivo.',
            ),
          if (!ui.storageAvailable)
            const InlineNotice(
              text:
                  'No está disponible la copia local. Mantén conexión para guardar cambios.',
            ),
          if (active == 'ventas')
            _MobileSalesTabs(
              selected: root == 'ordenes' ? 'ventas' : root,
              onSelect: (id) => ui.go('/$id'),
            ),
          Expanded(
            child: KeyedSubtree(
              key: ValueKey(ui.location),
              child: _screen(uri),
            ),
          ),
        ],
      ),
      bottomNavigationBar: ColoredBox(
        color: CorteColors.chrome,
        child: SafeArea(
          top: false,
          child: ConstrainedBox(
            constraints: const BoxConstraints(minHeight: 68),
            child: IntrinsicHeight(
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  for (final item in [
                    corteDestinations[0],
                    corteDestinations[1],
                    corteDestinations[2],
                    corteDestinations[3],
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
                                textAlign: TextAlign.center,
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
        ),
      ),
    );
  }
}

class _MobileSalesTabs extends StatelessWidget {
  const _MobileSalesTabs({required this.selected, required this.onSelect});

  final String selected;
  final ValueChanged<String> onSelect;

  @override
  Widget build(BuildContext context) => Material(
    color: CorteColors.chrome,
    child: Row(
      children: [
        for (final (id, label) in _salesDestinations)
          Expanded(
            child: Semantics(
              button: true,
              selected: selected == id,
              child: InkWell(
                onTap: () => onSelect(id),
                child: Container(
                  alignment: Alignment.center,
                  constraints: const BoxConstraints(minHeight: 44),
                  padding: const EdgeInsets.symmetric(
                    horizontal: 4,
                    vertical: 8,
                  ),
                  decoration: BoxDecoration(
                    border: Border(
                      bottom: BorderSide(
                        width: 2,
                        color: selected == id
                            ? CorteColors.coral
                            : Colors.transparent,
                      ),
                    ),
                  ),
                  child: Text(
                    label,
                    textAlign: TextAlign.center,
                    style: TextStyle(
                      color: selected == id
                          ? Colors.white
                          : CorteColors.chromeMuted,
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
              ),
            ),
          ),
      ],
    ),
  );
}
