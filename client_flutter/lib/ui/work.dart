import 'package:flutter/material.dart';
import '../app.dart';
import 'editors.dart';
import 'format.dart';
import 'theme.dart';
import 'widgets.dart';
import 'catalog.dart';
import 'desktop.dart';
import 'desktop_home.dart';

EdgeInsets pagePadding(BuildContext context) => useDesktopWorkspace(context)
    ? const EdgeInsets.fromLTRB(24, 20, 24, 32)
    : EdgeInsets.fromLTRB(
        MediaQuery.sizeOf(context).width < 700 ? 20 : 32,
        24,
        MediaQuery.sizeOf(context).width < 700 ? 20 : 32,
        40,
      );
String productName(Map<String, dynamic> p) =>
    textOf(p['titulo_corto'], textOf(p['titulo'], 'Producto'));
bool samplePending(Map<String, dynamic> m) {
  if (!{'vencida', 'por_vencer', 'pausada'}.contains(m['grupo'])) return false;
  final a = mapOf(m['avance']);
  return a['etapa'] != 'no_se_puede' &&
      !(a['etapa'] == 'publicada' && a['vinculo_origen'] != 'video_previo');
}

String salePrice(Map<String, dynamic> p) {
  final minimum = p['precio_venta_min_centavos'];
  if (minimum == null || p['precio_fuente'] == 'lista') return '—';
  final maximum = p['precio_venta_max_centavos'];
  return '${p['precio_fuente'] == 'comision' ? '≈ ' : ''}${money(minimum)}${maximum != null && intOf(maximum) != intOf(minimum) ? ' – ${money(maximum)}' : ''}';
}

class HomePage extends StatelessWidget {
  const HomePage({super.key});
  @override
  Widget build(BuildContext context) => useDesktopWorkspace(context)
      ? const DesktopHomePage()
      : const _PhoneHomePage();
}

class _PhoneHomePage extends StatelessWidget {
  const _PhoneHomePage();
  @override
  Widget build(BuildContext context) => ApiData(
    path: '/api/dashboard',
    query: const {'periodo': '30d'},
    builder: (context, data) {
      final ui = CorteScope.of(context), kpis = mapOf(data['kpis']);
      return RefreshIndicator(
        onRefresh: () async => ui.refresh(),
        child: ListView(
          padding: pagePadding(context),
          children: [
            PageTitle(
              'Inicio',
              subtitle: 'Tus resultados y próximos pasos',
              action: OutlinedButton.icon(
                onPressed: () => ui.go('/muestras'),
                icon: const Icon(Icons.inventory_2_outlined, size: 19),
                label: const Text('Ver muestras'),
              ),
            ),
            MetricStrip([
              (
                'Comisión · últimos 30 días',
                money(kpis['comision_total_centavos']),
              ),
              ('Ventas', money(kpis['ventas_centavos'])),
              ('Pedidos válidos', integer(kpis['pedidos_validos'])),
              ('Unidades', integer(kpis['unidades'])),
            ]),
            const SizedBox(height: 28),
            const Divider(),
            SectionHeading(
              'Tu próximo video',
              action: TextButton(
                onPressed: () => ui.go('/muestras'),
                child: const Text('Ver todas'),
              ),
            ),
            ApiData(
              path: '/api/muestras',
              builder: (context, response) {
                final pending = rowsOf(
                  response['items'],
                ).where(samplePending).take(5).toList();
                return pending.isEmpty
                    ? const EmptyState(
                        'Estás al día',
                        text: 'Tus muestras pendientes aparecerán aquí.',
                      )
                    : Column(
                        children: pending
                            .map((m) => SampleTile(muestra: m))
                            .toList(),
                      );
              },
            ),
            const SectionHeading('Comisión estimada por mes'),
            MiniBars(rowsOf(mapOf(data['serie'])['puntos'])),
            SectionHeading(
              'Tiendas con mejores resultados',
              action: TextButton(
                onPressed: () => ui.go('/tiendas'),
                child: const Text('Ver tiendas'),
              ),
            ),
            for (final shop in rowsOf(data['top_tiendas']).take(5))
              ListTile(
                contentPadding: EdgeInsets.zero,
                leading: CortePhoto(
                  textOf(shop['imagen']).isEmpty
                      ? null
                      : textOf(shop['imagen']),
                  width: 48,
                  height: 48,
                ),
                title: Text(
                  textOf(shop['nombre']),
                  style: const TextStyle(fontWeight: FontWeight.w700),
                ),
                subtitle: Text(textOf(shop['salud_porque'])),
                onTap: () => ui.go(
                  '/tiendas/${Uri.encodeComponent(textOf(shop['tienda_key']))}',
                ),
                trailing: const Icon(Icons.chevron_right_rounded),
              ),
          ],
        ),
      );
    },
  );
}

class SamplesPage extends StatefulWidget {
  const SamplesPage({super.key, this.all = false, this.initialSearch = ''});
  final bool all;
  final String initialSearch;
  @override
  State<SamplesPage> createState() => _SamplesPageState();
}

class _SamplesPageState extends State<SamplesPage> {
  late final TextEditingController _query;
  String _store = '', _stage = '', _order = 'prioridad';
  bool _filters = false, _onlyReceived = false, _onlyPinned = false;
  @override
  void initState() {
    super.initState();
    _query = TextEditingController(text: widget.initialSearch);
  }

  @override
  void dispose() {
    _query.dispose();
    super.dispose();
  }

  Widget _desktopTools(Map<String, String> shops) => LayoutBuilder(
    builder: (context, limits) {
      final scale = (MediaQuery.textScalerOf(context).scale(13) / 13).clamp(
        1.0,
        1.5,
      );
      final storeWidth = 170 * scale;
      final orderWidth = 150 * scale;
      final filterWidth = 108 * scale;
      final search = TextField(
        controller: _query,
        onChanged: (_) => setState(() {}),
        decoration: const InputDecoration(
          labelText: 'Buscar muestras',
          floatingLabelBehavior: FloatingLabelBehavior.never,
          prefixIcon: Icon(Icons.search_rounded, size: 18),
        ),
      );
      final store = DropdownButtonFormField<String>(
        initialValue: shops.containsKey(_store) ? _store : '',
        isExpanded: true,
        decoration: const InputDecoration(
          contentPadding: EdgeInsets.symmetric(horizontal: 12, vertical: 10),
        ),
        items: [
          const DropdownMenuItem(value: '', child: Text('Tiendas')),
          ...shops.entries.map(
            (entry) => DropdownMenuItem(
              value: entry.key,
              child: Text(
                entry.value,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
              ),
            ),
          ),
        ],
        onChanged: (value) => setState(() => _store = value ?? ''),
      );
      final order = DropdownButtonFormField<String>(
        initialValue: _order,
        isExpanded: true,
        decoration: const InputDecoration(
          contentPadding: EdgeInsets.symmetric(horizontal: 12, vertical: 10),
        ),
        items: const [
          DropdownMenuItem(value: 'prioridad', child: Text('Sugerido')),
          DropdownMenuItem(value: 'antiguas', child: Text('Más antiguas')),
          DropdownMenuItem(value: 'recientes', child: Text('Recientes')),
          DropdownMenuItem(value: 'tienda', child: Text('Por tienda')),
        ],
        onChanged: (value) => setState(() => _order = value ?? 'prioridad'),
      );
      final filters = OutlinedButton.icon(
        onPressed: () => setState(() => _filters = !_filters),
        icon: const Icon(Icons.tune_rounded, size: 18),
        label: const Text('Filtros'),
      );
      if (limits.maxWidth >=
          storeWidth + orderWidth + filterWidth + 30 + 220 * scale) {
        return Row(
          children: [
            Expanded(child: search),
            const SizedBox(width: 10),
            SizedBox(width: storeWidth, child: store),
            const SizedBox(width: 10),
            SizedBox(width: orderWidth, child: order),
            const SizedBox(width: 10),
            SizedBox(width: filterWidth, child: filters),
          ],
        );
      }
      final half = (limits.maxWidth - 10) / 2;
      return Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          search,
          const SizedBox(height: 10),
          Wrap(
            spacing: 10,
            runSpacing: 10,
            children: [
              SizedBox(width: storeWidth.clamp(0, half), child: store),
              SizedBox(width: orderWidth.clamp(0, half), child: order),
              SizedBox(
                width: filterWidth.clamp(0, limits.maxWidth),
                child: filters,
              ),
            ],
          ),
        ],
      );
    },
  );

  @override
  Widget build(BuildContext context) => ApiData(
    path: '/api/muestras',
    query: const {'orden': 'prioridad'},
    builder: (context, data) {
      final ui = CorteScope.of(context);
      final desktop = useDesktopWorkspace(context);
      final all = rowsOf(data['items']);
      final pending = all.where(samplePending).toList();
      final source = widget.all ? all : pending;
      final shops = <String, String>{
        for (final m in source)
          textOf(mapOf(m['tienda'])['tienda_key']): textOf(
            mapOf(m['tienda'])['nombre'],
          ),
      };
      final stages = <String>{
        for (final m in source) textOf(m['grupo']),
      }.where((e) => e.isNotEmpty).toList();
      final q = _query.text.trim().toLowerCase();
      final hasFilters =
          q.isNotEmpty ||
          _store.isNotEmpty ||
          _stage.isNotEmpty ||
          _onlyPinned ||
          _onlyReceived;
      final filtered = source.where((m) {
        final p = mapOf(m['producto']),
            a = mapOf(m['avance']),
            shop = mapOf(m['tienda']);
        return (_store.isEmpty || shop['tienda_key'] == _store) &&
            (_stage.isEmpty || m['grupo'] == _stage) &&
            (!_onlyReceived || m['recibida'] == true) &&
            (!_onlyPinned || a['fijada'] == true) &&
            (q.isEmpty ||
                '${productName(p)} ${shop['nombre']} ${m['variante']}'
                    .toLowerCase()
                    .contains(q));
      }).toList();
      if (_order == 'tienda')
        filtered.sort(
          (a, b) => textOf(
            mapOf(a['tienda'])['nombre'],
          ).compareTo(textOf(mapOf(b['tienda'])['nombre'])),
        );
      if (_order == 'antiguas')
        filtered.sort(
          (a, b) =>
              intOf(a['solicitada_at']).compareTo(intOf(b['solicitada_at'])),
        );
      if (_order == 'recientes')
        filtered.sort(
          (a, b) =>
              intOf(b['solicitada_at']).compareTo(intOf(a['solicitada_at'])),
        );
      return RefreshIndicator(
        onRefresh: () async => ui.refresh(),
        child: ListView.builder(
          key: PageStorageKey(widget.all ? 'todas' : 'pendientes'),
          padding: pagePadding(context),
          itemCount: filtered.length + 1,
          itemBuilder: (context, index) {
            if (index > 0) return SampleTile(muestra: filtered[index - 1]);
            return Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                PageTitle(
                  'Muestras',
                  subtitle: desktop && widget.all
                      ? '${all.length} muestras'
                      : '${pending.length} pendientes',
                  action: FilledButton.icon(
                    onPressed: () => ui.go('/muestras/plan'),
                    icon: const Icon(Icons.calendar_month_outlined, size: 18),
                    label: const Text('Armar mi plan'),
                  ),
                ),
                _SampleTabs(
                  all: widget.all,
                  total: all.length,
                  pending: pending.length,
                ),
                SizedBox(height: desktop ? 16 : 18),
                if (desktop)
                  _desktopTools(shops)
                else ...[
                  TextField(
                    controller: _query,
                    onChanged: (_) => setState(() {}),
                    decoration: InputDecoration(
                      hintText: 'Buscar muestra o tienda',
                      labelText: 'Buscar muestras',
                      floatingLabelBehavior: FloatingLabelBehavior.never,
                      prefixIcon: const Icon(Icons.search_rounded, size: 20),
                      suffixIcon: TextButton.icon(
                        onPressed: () => setState(() => _filters = !_filters),
                        icon: const Icon(Icons.tune_rounded, size: 20),
                        label: const Text('Filtros'),
                      ),
                    ),
                  ),
                  if (MediaQuery.sizeOf(context).width >= 700 || _filters)
                    const SizedBox(height: 12),
                  if (MediaQuery.sizeOf(context).width >= 700 || _filters)
                    LayoutBuilder(
                      builder: (context, limits) => Wrap(
                        spacing: 10,
                        runSpacing: 10,
                        children: [
                          SizedBox(
                            width: (limits.maxWidth < 600
                                ? limits.maxWidth / 2 - 5
                                : 210),
                            child: DropdownButtonFormField<String>(
                              initialValue: shops.containsKey(_store)
                                  ? _store
                                  : '',
                              isExpanded: true,
                              decoration: const InputDecoration(
                                contentPadding: EdgeInsets.symmetric(
                                  horizontal: 12,
                                  vertical: 10,
                                ),
                              ),
                              items: [
                                const DropdownMenuItem(
                                  value: '',
                                  child: Text('Tiendas'),
                                ),
                                ...shops.entries.map(
                                  (e) => DropdownMenuItem(
                                    value: e.key,
                                    child: Text(
                                      e.value,
                                      maxLines: 1,
                                      overflow: TextOverflow.ellipsis,
                                    ),
                                  ),
                                ),
                              ],
                              onChanged: (v) =>
                                  setState(() => _store = v ?? ''),
                            ),
                          ),
                          SizedBox(
                            width: limits.maxWidth < 600
                                ? limits.maxWidth / 2 - 5
                                : 180,
                            child: DropdownButtonFormField<String>(
                              initialValue: _order,
                              decoration: const InputDecoration(
                                contentPadding: EdgeInsets.symmetric(
                                  horizontal: 12,
                                  vertical: 10,
                                ),
                              ),
                              isExpanded: true,
                              items: const [
                                DropdownMenuItem(
                                  value: 'prioridad',
                                  child: Text('Sugerido'),
                                ),
                                DropdownMenuItem(
                                  value: 'antiguas',
                                  child: Text('Más antiguas'),
                                ),
                                DropdownMenuItem(
                                  value: 'recientes',
                                  child: Text('Recientes'),
                                ),
                                DropdownMenuItem(
                                  value: 'tienda',
                                  child: Text('Por tienda'),
                                ),
                              ],
                              onChanged: (v) =>
                                  setState(() => _order = v ?? 'prioridad'),
                            ),
                          ),
                        ],
                      ),
                    ),
                ],
                if (_filters) ...[
                  const SizedBox(height: 14),
                  Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    children: [
                      ChoiceChip(
                        label: const Text('Todos los estados'),
                        selected: _stage.isEmpty,
                        onSelected: (_) => setState(() => _stage = ''),
                      ),
                      for (final s in stages)
                        ChoiceChip(
                          label: Text(stageLabel(s)),
                          selected: _stage == s,
                          onSelected: (v) =>
                              setState(() => _stage = v ? s : ''),
                        ),
                      FilterChip(
                        label: const Text('Recibidas'),
                        selected: _onlyReceived,
                        onSelected: (v) => setState(() => _onlyReceived = v),
                      ),
                      FilterChip(
                        label: const Text('Fijadas'),
                        selected: _onlyPinned,
                        onSelected: (v) => setState(() => _onlyPinned = v),
                      ),
                    ],
                  ),
                ],
                SizedBox(height: desktop ? 14 : 20),
                if (!desktop || hasFilters)
                  Row(
                    children: [
                      Expanded(
                        child: Text(
                          desktop
                              ? '${filtered.length} resultados'
                              : '${filtered.length} ${widget.all ? 'muestras' : 'por hacer'}',
                          style: const TextStyle(
                            fontSize: 13,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                      ),
                      if (hasFilters)
                        TextButton(
                          onPressed: () => setState(() {
                            _query.clear();
                            _store = '';
                            _stage = '';
                            _onlyPinned = false;
                            _onlyReceived = false;
                          }),
                          child: const Text('Limpiar'),
                        ),
                    ],
                  ),
                const SizedBox(height: 8),
                if (desktop) const _SampleTableHeader() else const Divider(),
                if (filtered.isEmpty)
                  EmptyState(
                    source.isEmpty
                        ? 'No hay muestras pendientes'
                        : 'No encontramos coincidencias',
                    text: source.isEmpty
                        ? 'Las solicitudes de tu cuenta aparecerán aquí al sincronizar.'
                        : 'Cambia la búsqueda o los filtros.',
                  ),
              ],
            );
          },
        ),
      );
    },
  );
}

class _SampleTabs extends StatelessWidget {
  const _SampleTabs({
    required this.all,
    required this.total,
    required this.pending,
  });
  final bool all;
  final int total, pending;
  @override
  Widget build(BuildContext context) {
    if (useDesktopWorkspace(context)) {
      return Container(
        decoration: BoxDecoration(
          border: Border(bottom: BorderSide(color: context.corte.line)),
        ),
        child: SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              for (final tab in [
                ('/muestras', 'Pendientes', !all, '$pending'),
                ('/muestras/agenda', 'Agenda', false, ''),
                ('/muestras/todas', 'Todas', all, '$total'),
              ])
                Semantics(
                  selected: tab.$3,
                  child: InkWell(
                    onTap: () => CorteScope.of(context).go(tab.$1),
                    child: Container(
                      padding: const EdgeInsets.fromLTRB(12, 9, 12, 12),
                      margin: const EdgeInsets.only(right: 12),
                      decoration: BoxDecoration(
                        border: Border(
                          bottom: BorderSide(
                            color: tab.$3
                                ? CorteColors.coral
                                : Colors.transparent,
                            width: 3,
                          ),
                        ),
                      ),
                      child: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Text(
                            tab.$2,
                            style: TextStyle(
                              fontWeight: tab.$3
                                  ? FontWeight.w600
                                  : FontWeight.w500,
                            ),
                          ),
                          if (tab.$4.isNotEmpty) ...[
                            const SizedBox(width: 7),
                            Text(
                              tab.$4,
                              style: TextStyle(
                                fontSize: 12,
                                color: context.corte.muted,
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
      );
    }
    return Container(
      decoration: BoxDecoration(
        border: Border(bottom: BorderSide(color: context.corte.line)),
      ),
      child: Row(
        children: [
          for (final tab in [
            ('/muestras', 'Pendientes', !all, '$pending'),
            ('/muestras/agenda', 'Agenda', false, ''),
            ('/muestras/todas', 'Todas', all, '$total'),
          ])
            Expanded(
              child: InkWell(
                onTap: () => CorteScope.of(context).go(tab.$1),
                child: Container(
                  padding: const EdgeInsets.only(top: 9, bottom: 14),
                  decoration: BoxDecoration(
                    border: Border(
                      bottom: BorderSide(
                        color: tab.$3 ? CorteColors.coral : Colors.transparent,
                        width: 3,
                      ),
                    ),
                  ),
                  child: Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Text(
                        tab.$2,
                        style: TextStyle(
                          fontWeight: tab.$3
                              ? FontWeight.w800
                              : FontWeight.w500,
                        ),
                      ),
                      if (tab.$4.isNotEmpty) ...[
                        const SizedBox(width: 7),
                        Text(
                          tab.$4,
                          style: TextStyle(
                            color: context.corte.muted,
                            fontSize: 12,
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
    );
  }
}

bool _sampleColumnsFit(BuildContext context, double width) {
  final scale = MediaQuery.textScalerOf(context).scale(13) / 13;
  return width >= 800 && width >= 640 * scale;
}

class _SampleColumnWidths {
  _SampleColumnWidths(BuildContext context)
    : scale = (MediaQuery.textScalerOf(context).scale(13) / 13).clamp(
        1.0,
        double.infinity,
      );
  final double scale;
  double get variant => 150 * scale.clamp(1.0, 1.6);
  double get status => 146 * scale.clamp(1.0, 1.6);
  double get action => 76 * scale;
}

class _SampleTableHeader extends StatelessWidget {
  const _SampleTableHeader();

  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, limits) {
      final columns = _SampleColumnWidths(context);
      final wide = _sampleColumnsFit(context, limits.maxWidth);
      Widget heading(String text) => Semantics(
        header: true,
        child: Text(
          text,
          style: TextStyle(
            color: context.corte.muted,
            fontSize: 12,
            fontWeight: FontWeight.w500,
          ),
        ),
      );
      return Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
        decoration: BoxDecoration(
          color: context.corte.soft,
          borderRadius: const BorderRadius.vertical(top: Radius.circular(7)),
          border: Border.all(color: context.corte.line),
        ),
        child: Row(
          children: [
            Expanded(child: heading('Producto')),
            if (wide) ...[
              const SizedBox(width: 16),
              SizedBox(width: columns.variant, child: heading('Variante')),
              const SizedBox(width: 16),
              SizedBox(width: columns.status, child: heading('Estado')),
            ],
            const SizedBox(width: 16),
            SizedBox(
              width: columns.action,
              child: Align(
                alignment: Alignment.centerRight,
                child: heading('Acción'),
              ),
            ),
          ],
        ),
      );
    },
  );
}

class _CompactSampleTile extends StatelessWidget {
  const _CompactSampleTile({required this.muestra});
  final Map<String, dynamic> muestra;

  @override
  Widget build(BuildContext context) {
    final product = mapOf(muestra['producto']);
    final shop = mapOf(muestra['tienda']);
    final advance = mapOf(muestra['avance']);
    final stage = textOf(advance['etapa']);
    final variant = textOf(muestra['variante'], 'Sin variante informada');
    final urgent =
        {'vencida', 'por_vencer'}.contains(muestra['grupo']) ||
        mapOf(muestra['avisos'])['promesa_vencida'] == true;
    final status = urgent
        ? textOf(muestra['etiqueta'], stageLabel(muestra['grupo']))
        : stageLabel(advance['etapa']);
    final buttonLabel = stage == 'por_planear' || stage.isEmpty
        ? 'Planear'
        : 'Avance';
    void openDetail() => CorteScope.of(context).go(
      '/muestras/m/${Uri.encodeComponent(textOf(muestra['application_id']))}',
    );
    return LayoutBuilder(
      builder: (context, limits) {
        final wide = _sampleColumnsFit(context, limits.maxWidth);
        final columns = _SampleColumnWidths(context);
        final button = OutlinedButton(
          onPressed: () => showPlanEditor(context, muestra),
          style: OutlinedButton.styleFrom(
            minimumSize: const Size(44, 34),
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
            textStyle: const TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w500,
            ),
          ),
          child: Text(buttonLabel),
        );
        final photo = ExcludeSemantics(
          child: CortePhoto(
            textOf(product['imagen']).isEmpty
                ? null
                : textOf(product['imagen']),
            width: 52,
            height: 58,
            radius: 5,
            label: productName(product),
          ),
        );
        final identity = ExcludeSemantics(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                productName(product),
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                  fontSize: 14,
                  height: 1.3,
                  fontWeight: FontWeight.w600,
                ),
              ),
              const SizedBox(height: 4),
              Row(
                children: [
                  Icon(
                    Icons.storefront_outlined,
                    size: 13,
                    color: context.corte.muted,
                  ),
                  const SizedBox(width: 4),
                  Expanded(
                    child: Text(
                      textOf(shop['nombre']),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                        fontSize: 12,
                        height: 1.3,
                        color: context.corte.muted,
                      ),
                    ),
                  ),
                ],
              ),
              if (!wide) ...[
                const SizedBox(height: 5),
                Wrap(
                  spacing: 12,
                  runSpacing: 4,
                  children: [
                    Text(
                      variant,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                        fontSize: 12,
                        height: 1.3,
                        color: context.corte.muted,
                      ),
                    ),
                    StatusTag(status, urgent: urgent),
                  ],
                ),
              ],
            ],
          ),
        );
        return Semantics(
          container: true,
          explicitChildNodes: true,
          button: true,
          onTap: openDetail,
          label:
              'Producto: ${productName(product)}. Tienda: ${textOf(shop['nombre'])}. '
              'Variante: $variant. Estado: $status. '
              '${muestra['recibida'] == true ? 'Muestra recibida.' : ''}',
          child: Material(
            color: context.corte.surface,
            child: InkWell(
              excludeFromSemantics: true,
              onTap: openDetail,
              child: Container(
                constraints: const BoxConstraints(minHeight: 80),
                padding: const EdgeInsets.symmetric(
                  horizontal: 12,
                  vertical: 10,
                ),
                decoration: BoxDecoration(
                  border: Border(
                    left: BorderSide(color: context.corte.line),
                    right: BorderSide(color: context.corte.line),
                    bottom: BorderSide(color: context.corte.line),
                  ),
                ),
                child: Row(
                  children: [
                    photo,
                    const SizedBox(width: 12),
                    Expanded(child: identity),
                    if (wide) ...[
                      const SizedBox(width: 16),
                      SizedBox(
                        width: columns.variant,
                        child: ExcludeSemantics(
                          child: Text(
                            variant,
                            maxLines: 2,
                            overflow: TextOverflow.ellipsis,
                            style: const TextStyle(fontSize: 13, height: 1.4),
                          ),
                        ),
                      ),
                      const SizedBox(width: 16),
                      SizedBox(
                        width: columns.status,
                        child: ExcludeSemantics(
                          child: StatusTag(status, urgent: urgent),
                        ),
                      ),
                    ],
                    const SizedBox(width: 16),
                    if (wide)
                      SizedBox(
                        width: columns.action,
                        child: Align(
                          alignment: Alignment.centerRight,
                          child: button,
                        ),
                      )
                    else
                      button,
                  ],
                ),
              ),
            ),
          ),
        );
      },
    );
  }
}

class SampleTile extends StatelessWidget {
  const SampleTile({super.key, required this.muestra, this.compact = false});
  final Map<String, dynamic> muestra;
  final bool compact;
  @override
  Widget build(BuildContext context) {
    if (compact || useDesktopWorkspace(context)) {
      return _CompactSampleTile(muestra: muestra);
    }
    final m = muestra,
        p = mapOf(muestra['producto']),
        shop = mapOf(muestra['tienda']),
        a = mapOf(muestra['avance']);
    final ui = CorteScope.of(context);
    final stage = textOf(a['etapa']);
    final urgent =
        {'vencida', 'por_vencer'}.contains(m['grupo']) ||
        mapOf(m['avisos'])['promesa_vencida'] == true;
    final status = urgent
        ? textOf(m['etiqueta'], stageLabel(m['grupo']))
        : stageLabel(a['etapa']);
    return LayoutBuilder(
      builder: (context, limits) {
        final wide = limits.maxWidth >= 820;
        final photo = CortePhoto(
          textOf(p['imagen']).isEmpty ? null : textOf(p['imagen']),
          width: wide ? 100 : 96,
          height: wide ? 108 : 102,
          label: productName(p),
        );
        final identity = Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              productName(p),
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(
                fontSize: wide ? 18 : 15,
                height: 1.25,
                fontWeight: FontWeight.w800,
                letterSpacing: -.35,
              ),
            ),
            const SizedBox(height: 6),
            Row(
              children: [
                Icon(
                  Icons.storefront_outlined,
                  size: 15,
                  color: context.corte.muted,
                ),
                const SizedBox(width: 5),
                Expanded(
                  child: Text(
                    textOf(shop['nombre']),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(fontSize: 12, color: context.corte.muted),
                  ),
                ),
              ],
            ),
          ],
        );
        final button = OutlinedButton(
          onPressed: () => showPlanEditor(context, m),
          style: OutlinedButton.styleFrom(
            minimumSize: const Size(44, 38),
            padding: const EdgeInsets.symmetric(horizontal: 12),
            textStyle: const TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w600,
            ),
          ),
          child: Text(
            stage == 'por_planear' || stage.isEmpty ? 'Planear' : 'Avance',
          ),
        );
        return Material(
          color: context.corte.surface,
          child: InkWell(
            onTap: () => ui.go(
              '/muestras/m/${Uri.encodeComponent(textOf(m['application_id']))}',
            ),
            child: Container(
              constraints: const BoxConstraints(minHeight: 126),
              padding: const EdgeInsets.symmetric(vertical: 14),
              decoration: BoxDecoration(
                border: Border(bottom: BorderSide(color: context.corte.line)),
              ),
              child: wide
                  ? Row(
                      children: [
                        photo,
                        const SizedBox(width: 22),
                        Expanded(flex: 4, child: identity),
                        const SizedBox(width: 24),
                        Expanded(
                          flex: 2,
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                m['recibida'] == true
                                    ? 'Recibida'
                                    : textOf(m['etiqueta']),
                                style: const TextStyle(fontSize: 13),
                              ),
                              const SizedBox(height: 5),
                              Text(
                                textOf(m['variante'], 'Sin variante informada'),
                                style: TextStyle(
                                  fontSize: 13,
                                  color: context.corte.muted,
                                ),
                              ),
                            ],
                          ),
                        ),
                        const SizedBox(width: 20),
                        Expanded(
                          flex: 2,
                          child: StatusTag(status, urgent: urgent),
                        ),
                        const SizedBox(width: 16),
                        button,
                      ],
                    )
                  : Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        photo,
                        const SizedBox(width: 12),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              identity,
                              const SizedBox(height: 7),
                              Row(
                                crossAxisAlignment: CrossAxisAlignment.end,
                                children: [
                                  Expanded(
                                    child: Column(
                                      crossAxisAlignment:
                                          CrossAxisAlignment.start,
                                      children: [
                                        Text(
                                          textOf(m['variante']),
                                          maxLines: 1,
                                          overflow: TextOverflow.ellipsis,
                                          style: TextStyle(
                                            fontSize: 12,
                                            color: context.corte.muted,
                                          ),
                                        ),
                                        const SizedBox(height: 5),
                                        StatusTag(status, urgent: urgent),
                                      ],
                                    ),
                                  ),
                                  const SizedBox(width: 8),
                                  button,
                                ],
                              ),
                            ],
                          ),
                        ),
                      ],
                    ),
            ),
          ),
        );
      },
    );
  }
}

class SampleDetailPage extends StatelessWidget {
  const SampleDetailPage({super.key, required this.id});
  final String id;
  @override
  Widget build(BuildContext context) => ApiData(
    path: '/api/muestras/${Uri.encodeComponent(id)}',
    builder: (context, detail) {
      final ui = CorteScope.of(context),
          m = mapOf(detail['muestra']),
          p = mapOf(m['producto']),
          shop = mapOf(m['tienda']);
      final advance = mapOf(m['avance']);
      return ListView(
        padding: pagePadding(context),
        children: [
          TextButton.icon(
            onPressed: () {
              if (!ui.back()) ui.go('/muestras');
            },
            icon: const Icon(Icons.chevron_left_rounded),
            label: const Text('Muestras'),
            style: TextButton.styleFrom(
              alignment: Alignment.centerLeft,
              padding: EdgeInsets.zero,
              minimumSize: const Size(44, 44),
            ),
          ),
          const SizedBox(height: 12),
          SelectableText(
            productName(p),
            style: Theme.of(context).textTheme.headlineMedium,
          ),
          const SizedBox(height: 12),
          InkWell(
            onTap: () => ui.go(
              '/tiendas/${Uri.encodeComponent(textOf(shop['tienda_key']))}',
            ),
            child: Container(
              padding: const EdgeInsets.only(left: 12),
              decoration: const BoxDecoration(
                border: Border(
                  left: BorderSide(color: CorteColors.cyan, width: 3),
                ),
              ),
              child: Text(
                textOf(shop['nombre']),
                style: const TextStyle(
                  fontSize: 15,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ),
          ),
          const SizedBox(height: 18),
          ApiData(
            key: ValueKey('gallery-${p['product_id']}'),
            path:
                '/api/productos/${Uri.encodeComponent(textOf(p['product_id']))}',
            builder: (context, product) => Column(
              children: [
                ProductGallery(
                  productId: textOf(p['product_id']),
                  photos: productPhotos({
                    ...product,
                    'ficha': mapOf(product['ficha']).isEmpty
                        ? p
                        : product['ficha'],
                  }),
                  label: productName(p),
                  mainHeight: MediaQuery.sizeOf(context).width < 700
                      ? 220
                      : null,
                ),
              ],
            ),
          ),
          const SizedBox(height: 18),
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: context.corte.rose,
              borderRadius: BorderRadius.circular(12),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: Text(
                        m['recibida'] == true
                            ? 'Tu muestra recibida'
                            : 'Tu solicitud',
                        style: const TextStyle(
                          fontSize: 14,
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                    ),
                    if (p['comision_bp'] != null)
                      Text(
                        '${percent(p['comision_bp'])} de comisión',
                        style: TextStyle(
                          fontSize: 12,
                          color: context.corte.action,
                        ),
                      ),
                  ],
                ),
                const SizedBox(height: 8),
                Row(
                  children: [
                    const Icon(
                      Icons.checkroom_outlined,
                      color: CorteColors.coral,
                      size: 24,
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Text(
                        textOf(m['variante'], 'Variante no informada'),
                        style: const TextStyle(fontSize: 13),
                      ),
                    ),
                    const SizedBox(width: 10),
                    Flexible(
                      child: Text(
                        salePrice(p),
                        style: TextStyle(
                          fontSize: useDesktopWorkspace(context) ? 22 : 24,
                          fontWeight: useDesktopWorkspace(context)
                              ? FontWeight.w700
                              : FontWeight.w800,
                        ),
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),
          const SizedBox(height: 16),
          FilledButton.icon(
            onPressed: () => showPlanEditor(context, m),
            icon: const Icon(Icons.calendar_month_outlined),
            label: Text(
              advance['etapa'] == 'por_planear'
                  ? 'Planear video'
                  : 'Actualizar mi avance',
            ),
          ),
          TextButton.icon(
            onPressed: () => ui.go(
              '/productos/${Uri.encodeComponent(textOf(p['product_id']))}',
            ),
            iconAlignment: IconAlignment.end,
            icon: const Icon(Icons.chevron_right_rounded),
            label: const Text('Ver ficha completa'),
          ),
          const SizedBox(height: 8),
          const Divider(),
          OutlinedButton.icon(
            onPressed: () => showMessageEditor(
              context,
              tienda: shop,
              muestras: [m],
              plantillaId: textOf(detail['plantilla_sugerida']).isEmpty
                  ? null
                  : textOf(detail['plantilla_sugerida']),
            ),
            icon: const Icon(Icons.chat_bubble_outline_rounded),
            label: const Text('Preparar mensaje para la tienda'),
          ),
          const SectionHeading('Estado de la muestra'),
          DefinitionRow('TikTok', textOf(m['etiqueta'])),
          DefinitionRow('Tu avance', stageLabel(advance['etapa'])),
          if (advance['fecha_planeada'] != null)
            DefinitionRow('Planeada para', textOf(advance['fecha_planeada'])),
          if (m['fecha_limite_at'] != null)
            DefinitionRow('Fecha límite', date(m['fecha_limite_at'])),
          DefinitionRow('Solicitada', date(m['solicitada_at'])),
          if (textOf(p['titulo']).isNotEmpty)
            ExpansionTile(
              tilePadding: EdgeInsets.zero,
              title: const Text('Título completo del producto'),
              children: [
                Padding(
                  padding: const EdgeInsets.only(bottom: 16),
                  child: SelectableText(textOf(p['titulo'])),
                ),
              ],
            ),
          const SectionHeading('Videos que venden este producto'),
          for (final v in rowsOf(detail['videos_del_producto']).take(8))
            VideoRow(video: v),
          if (rowsOf(detail['videos_del_producto']).isEmpty)
            Text(
              'Todavía no hay un video con ventas registrado para este producto.',
              style: TextStyle(color: context.corte.muted),
            ),
          const SizedBox(height: 16),
          NotesPanel(entidad: 'muestra', entidadId: id),
          RemindersPanel(entidad: 'muestra', entidadId: id),
          const SectionHeading('Historial'),
          for (final item in rowsOf(detail['historial']))
            ListTile(
              contentPadding: EdgeInsets.zero,
              title: Text(
                '${textOf(item['antes'], 'Sin dato')} → ${textOf(item['despues'])}',
              ),
              subtitle: Text(date(item['at'], time: true)),
            ),
          if (rowsOf(detail['historial']).isEmpty)
            Text(
              'Sin cambios registrados.',
              style: TextStyle(color: context.corte.muted),
            ),
        ],
      );
    },
  );
}

class AgendaPage extends StatelessWidget {
  const AgendaPage({super.key});
  @override
  Widget build(BuildContext context) => ApiData(
    path: '/api/plan',
    builder: (context, data) {
      final ui = CorteScope.of(context), plans = rowsOf(data['items']);
      plans.sort(
        (a, b) => textOf(
          a['fecha_plan'],
          '9999',
        ).compareTo(textOf(b['fecha_plan'], '9999')),
      );
      return ListView(
        padding: pagePadding(context),
        children: [
          PageTitle(
            'Agenda de videos',
            subtitle: '${plans.length} videos en tu plan',
            action: FilledButton.icon(
              onPressed: () => ui.go('/muestras'),
              icon: const Icon(Icons.add_rounded),
              label: const Text('Elegir muestras'),
            ),
          ),
          if (plans.isEmpty)
            EmptyState(
              'Tu siguiente video empieza aquí',
              text:
                  'Elige una muestra y asígnale una fecha para armar tu agenda.',
              action: OutlinedButton(
                onPressed: () => ui.go('/muestras'),
                child: const Text('Ver muestras'),
              ),
            ),
          for (final p in plans)
            ListTile(
              contentPadding: const EdgeInsets.symmetric(vertical: 8),
              leading: Container(
                width: 48,
                height: 48,
                decoration: BoxDecoration(
                  color: context.corte.rose,
                  borderRadius: BorderRadius.circular(9),
                ),
                child: Icon(
                  Icons.movie_creation_outlined,
                  color: context.corte.action,
                ),
              ),
              title: Text(
                textOf(p['titulo']),
                style: const TextStyle(fontWeight: FontWeight.w700),
              ),
              subtitle: Text(
                '${textOf(p['fecha_plan'], 'Sin fecha')} · ${stageLabel(p['estado'])}',
              ),
              trailing: const Icon(Icons.chevron_right_rounded),
              onTap: p['application_id'] == null
                  ? () => showPlanEditor(context, const {}, plan: p)
                  : () => ui.go(
                      '/muestras/m/${Uri.encodeComponent(textOf(p['application_id']))}',
                    ),
            ),
        ],
      );
    },
  );
}

class StoresPage extends StatefulWidget {
  const StoresPage({super.key});
  @override
  State<StoresPage> createState() => _StoresPageState();
}

class _StoresPageState extends State<StoresPage> {
  String _search = '', _order = 'atencion';
  @override
  Widget build(BuildContext context) => ApiData(
    path: '/api/tiendas',
    query: {'orden': _order},
    builder: (context, data) {
      final ui = CorteScope.of(context);
      final shops = rowsOf(data['items'])
          .where(
            (s) => textOf(
              s['nombre'],
            ).toLowerCase().contains(_search.toLowerCase()),
          )
          .toList();
      return ListView(
        padding: pagePadding(context),
        children: [
          PageTitle(
            'Tiendas',
            subtitle: '${data['total'] ?? shops.length} colaboraciones',
          ),
          TextField(
            decoration: const InputDecoration(
              labelText: 'Buscar tienda',
              prefixIcon: Icon(Icons.search_rounded),
            ),
            onChanged: (v) => setState(() => _search = v),
          ),
          const SizedBox(height: 14),
          Wrap(
            spacing: 8,
            children: [
              for (final order in [
                ('atencion', 'Por atender'),
                ('comision', 'Comisión'),
                ('deuda', 'Muestras pendientes'),
                ('nombre', 'Nombre'),
              ])
                ChoiceChip(
                  label: Text(order.$2),
                  selected: _order == order.$1,
                  onSelected: (_) => setState(() => _order = order.$1),
                ),
            ],
          ),
          const SizedBox(height: 18),
          for (final s in shops)
            InkWell(
              onTap: () => ui.go(
                '/tiendas/${Uri.encodeComponent(textOf(s['tienda_key']))}',
              ),
              child: Container(
                padding: const EdgeInsets.symmetric(vertical: 18),
                decoration: BoxDecoration(
                  border: Border(bottom: BorderSide(color: context.corte.line)),
                ),
                child: Row(
                  children: [
                    CortePhoto(
                      textOf(s['imagen']).isEmpty ? null : textOf(s['imagen']),
                      width: 68,
                      height: 72,
                    ),
                    const SizedBox(width: 16),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            textOf(s['nombre']),
                            style: TextStyle(
                              fontSize: 16,
                              fontWeight: useDesktopWorkspace(context)
                                  ? FontWeight.w700
                                  : FontWeight.w800,
                            ),
                          ),
                          const SizedBox(height: 6),
                          Text(
                            textOf(s['salud_porque']),
                            style: TextStyle(
                              color: context.corte.muted,
                              fontSize: 13,
                            ),
                          ),
                          const SizedBox(height: 7),
                          StatusTag(
                            '${integer(mapOf(s['muestras'])['pendientes'])} muestras pendientes',
                            urgent: intOf(mapOf(s['promesas'])['vencidas']) > 0,
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(width: 12),
                    const Icon(Icons.chevron_right_rounded),
                  ],
                ),
              ),
            ),
          if (shops.isEmpty)
            const EmptyState('No encontramos tiendas con esta búsqueda'),
        ],
      );
    },
  );
}

class StoreDetailPage extends StatelessWidget {
  const StoreDetailPage({super.key, required this.id});
  final String id;
  @override
  Widget build(BuildContext context) => ApiData(
    path: '/api/tiendas/${Uri.encodeComponent(id)}',
    builder: (context, data) {
      final ui = CorteScope.of(context),
          shop = mapOf(data['tienda']),
          samples = rowsOf(data['muestras']);
      return ListView(
        padding: pagePadding(context),
        children: [
          PageTitle(
            textOf(shop['nombre'], 'Tienda'),
            subtitle: textOf(shop['salud_porque']),
            back: () => ui.go('/tiendas'),
            action: OutlinedButton.icon(
              onPressed: () => showMessageEditor(
                context,
                tienda: shop,
                muestras: samples,
                plantillaId: textOf(data['plantilla_sugerida']).isEmpty
                    ? null
                    : textOf(data['plantilla_sugerida']),
              ),
              icon: const Icon(Icons.chat_bubble_outline_rounded),
              label: const Text('Preparar mensaje'),
            ),
          ),
          MetricStrip([
            (
              'Muestras recibidas',
              integer(mapOf(shop['muestras'])['recibidas']),
            ),
            ('Por publicar', integer(mapOf(shop['muestras'])['pendientes'])),
            (
              'Comisión estimada',
              money(mapOf(shop['ventas'])['comision_estimada_centavos']),
            ),
            (
              'Pedidos válidos',
              integer(mapOf(shop['ventas'])['pedidos_validos']),
            ),
          ]),
          const SectionHeading('Muestras de esta tienda'),
          for (final m in samples) SampleTile(muestra: m),
          const SectionHeading('Comisión estimada por mes'),
          MiniBars(rowsOf(data['serie'])),
          const SectionHeading('Productos'),
          for (final p in rowsOf(data['productos']).take(12))
            ProductRow(product: p),
          NotesPanel(entidad: 'tienda', entidadId: id),
          RemindersPanel(entidad: 'tienda', entidadId: id),
        ],
      );
    },
  );
}
