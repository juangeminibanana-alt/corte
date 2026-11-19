import 'package:flutter/material.dart';
import '../app.dart';
import 'editors.dart';
import 'format.dart';
import 'theme.dart';
import 'widgets.dart';
import 'catalog.dart';
import 'product_evidence.dart';
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
  Widget build(BuildContext context) => const DesktopHomePage();
}

class SamplesPage extends StatefulWidget {
  const SamplesPage({super.key, this.all = false, this.initialSearch = ''});
  final bool all;
  final String initialSearch;
  @override
  State<SamplesPage> createState() => _SamplesPageState();
}

typedef _SampleRow = Map<String, dynamic>;

const _sampleGroups = {'por_vencer', 'vencida', 'pausada', 'en_revision'};

const _sampleSectionTitles = {
  'vencen_pronto': 'Vencen pronto · todavía cuentan para TikTok',
  'promesas_vencidas': 'Promesas vencidas',
  'en_revision': 'En revisión de TikTok',
  'alta': 'Prioridad alta',
  'media': 'Prioridad media',
  'baja': 'Prioridad baja',
  'falta_avisar': 'Falta avisar a la tienda',
  'no_etiquetar': 'No se pueden etiquetar',
  'pausadas': 'Pausadas',
  'no_hacer': 'Decidiste no hacerlas',
};

const _sampleGroupingLabels = {
  'prioridad': 'Prioridad',
  'tienda': 'Tienda',
  'tipo': 'Tipo de prenda',
  'etapa': 'Etapa',
  'mes': 'Mes de solicitud',
};

const _sampleOrderLabels = {
  'sugerido': 'Sugerido',
  'antiguas': 'Más antiguas primero',
  'recientes': 'Recientes',
  'comision': 'Más comisión por venta',
  'vendidas': 'Más vendidas en TikTok Shop',
  'precio': 'Precio de venta (≈)',
  'tienda': 'Tienda A–Z',
};

String _sampleSearchText(Object? value) {
  var text = textOf(value).toLowerCase();
  const letters = {'á': 'a', 'é': 'e', 'í': 'i', 'ó': 'o', 'ú': 'u', 'ü': 'u'};
  for (final entry in letters.entries) {
    text = text.replaceAll(entry.key, entry.value);
  }
  return text;
}

bool _sampleNeedsPublishedNotice(_SampleRow sample) {
  final advance = mapOf(sample['avance']);
  if (advance['etapa'] != 'publicada') return false;
  final sent = mapOf(sample['avisos'])['ultimo_enviado_at'];
  if (sent == null) return true;
  final day = textOf(advance['fecha_publicada']);
  final published = DateTime.tryParse('${day}T00:00:00-06:00');
  return published != null &&
      intOf(sent) * 1000 < published.millisecondsSinceEpoch;
}

String? _samplePrioritySection(_SampleRow sample) {
  final stage = mapOf(sample['avance'])['etapa'];
  if (stage == 'no_se_puede') return 'no_hacer';
  if (_sampleNeedsPublishedNotice(sample)) return 'falta_avisar';
  if (sample['grupo'] == 'en_revision') return 'en_revision';
  if (!samplePending(sample)) return null;
  if (sample['grupo'] == 'por_vencer') return 'vencen_pronto';
  if (mapOf(sample['avisos'])['promesa_vencida'] == true) {
    return 'promesas_vencidas';
  }
  if (sample['grupo'] == 'pausada') return 'pausadas';
  return switch (sample['prioridad']) {
    'no_se_puede_etiquetar' => 'no_etiquetar',
    'media' => 'media',
    'baja' => 'baja',
    _ => 'alta',
  };
}

Map<String, List<_SampleRow>> _pendingSamplesByStore(List<_SampleRow> samples) {
  final stores = <String, List<_SampleRow>>{};
  for (final sample in samples.where(samplePending)) {
    final key = textOf(mapOf(sample['tienda'])['tienda_key']);
    if (key.isNotEmpty) (stores[key] ??= []).add(sample);
  }
  return stores;
}

bool _sampleNoticeSent(_SampleRow sample) =>
    mapOf(sample['avisos'])['ultimo_enviado_at'] != null;

DateTime? _sampleLocalDate(Object? value) {
  final date = textOf(value);
  if (!RegExp(r'^\d{4}-\d{2}-\d{2}$').hasMatch(date)) return null;
  return DateTime.tryParse('${date}T00:00:00Z');
}

String _sampleDateLabel(DateTime value) =>
    date(value.millisecondsSinceEpoch ~/ 1000, utc: true);

class _SampleSection {
  const _SampleSection(this.key, this.title, this.samples);

  final String key;
  final String title;
  final List<_SampleRow> samples;
}

List<_SampleSection> _groupSamples(List<_SampleRow> samples, String grouping) {
  if (grouping == 'prioridad') {
    final sections = <String, List<_SampleRow>>{};
    for (final sample in samples) {
      final id = _samplePrioritySection(sample);
      if (id != null) (sections[id] ??= []).add(sample);
    }
    return [
      for (final label in _sampleSectionTitles.entries)
        if (sections[label.key] case final items?)
          _SampleSection(label.key, label.value, items),
    ];
  }

  final sections = <String, List<_SampleRow>>{};
  final endings = <_SampleRow>[];
  for (final sample in samples) {
    if (!samplePending(sample) && sample['grupo'] != 'en_revision') {
      endings.add(sample);
      continue;
    }
    final group = switch (grouping) {
      'tienda' => textOf(mapOf(sample['tienda'])['nombre'], 'Sin tienda'),
      'tipo' => textOf(
        textOf(mapOf(sample['producto'])['categoria']).split('>').last.trim(),
        'Sin tipo de prenda',
      ),
      'etapa' => stageLabel(mapOf(sample['avance'])['etapa'] ?? 'por_planear'),
      'mes' =>
        sample['solicitada_at'] == null
            ? 'Sin fecha de solicitud'
            : _sampleRequestMonth(intOf(sample['solicitada_at'])),
      _ => grouping,
    };
    (sections[group] ??= []).add(sample);
  }
  return [
    for (final group in sections.entries)
      _SampleSection('$grouping:${group.key}', group.key, group.value),
    ..._groupSamples(endings, 'prioridad'),
  ];
}

String _sampleRequestMonth(int seconds) {
  final day = DateTime.fromMillisecondsSinceEpoch(
    seconds * 1000,
    isUtc: true,
  ).subtract(const Duration(hours: 6));
  const months = [
    'Enero',
    'Febrero',
    'Marzo',
    'Abril',
    'Mayo',
    'Junio',
    'Julio',
    'Agosto',
    'Septiembre',
    'Octubre',
    'Noviembre',
    'Diciembre',
  ];
  return '${months[day.month - 1]} ${day.year}';
}

class _SamplesPageState extends State<SamplesPage> {
  late final TextEditingController _query;
  String _store = '', _order = 'sugerido', _grouping = 'prioridad';
  final _stages = <String>{};
  final _collapsed = <String, bool>{};
  String _view = 'lista';
  final _selected = <String>{};
  bool _filters = false, _selecting = false;
  bool _onlyReceived = false, _onlyPinned = false, _selling = false;
  bool _taggable = false, _withPromise = false;

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

  int get _filterCount =>
      (_query.text.trim().isNotEmpty ? 1 : 0) +
      (_store.isNotEmpty ? 1 : 0) +
      (_stages.isNotEmpty ? 1 : 0) +
      [
        _onlyReceived,
        _onlyPinned,
        _selling,
        _taggable,
        _withPromise,
      ].where((active) => active).length;

  void _clearFilters() => setState(() {
    _query.clear();
    _store = '';
    _stages.clear();
    _onlyReceived = false;
    _onlyPinned = false;
    _selling = false;
    _taggable = false;
    _withPromise = false;
  });

  List<_SampleRow> _visibleSamples(List<_SampleRow> source) {
    final terms = _sampleSearchText(_query.text)
        .trim()
        .split(RegExp(r'\s+'))
        .where((term) => term.isNotEmpty)
        .toList();
    final filtered = source
        .where((sample) {
          final product = mapOf(sample['producto']);
          final shop = mapOf(sample['tienda']);
          final words = _sampleSearchText(
            '${productName(product)} ${textOf(product['titulo'])} '
            '${textOf(shop['nombre'])} ${textOf(sample['variante'])}',
          );
          return (_store.isEmpty || shop['tienda_key'] == _store) &&
              (_stages.isEmpty || _stages.contains(sample['grupo'])) &&
              (!_onlyReceived || sample['recibida'] == true) &&
              (!_onlyPinned || mapOf(sample['avance'])['fijada'] == true) &&
              (!_selling ||
                  stringsOf(sample['razones']).contains('ya_lo_vendes') ||
                  intOf(mapOf(sample['ventas_producto'])['pedidos_validos']) >
                      0) &&
              (!_taggable || sample['prioridad'] != 'no_se_puede_etiquetar') &&
              (!_withPromise || mapOf(sample['avisos'])['promesa'] != null) &&
              terms.every(words.contains);
        })
        .indexed
        .toList();

    int byProductNumber(_SampleRow a, _SampleRow b, String key) {
      final first = mapOf(a['producto'])[key];
      final second = mapOf(b['producto'])[key];
      if (first == null) return second == null ? 0 : 1;
      if (second == null) return -1;
      return intOf(second).compareTo(intOf(first));
    }

    filtered.sort((left, right) {
      final a = left.$2;
      final b = right.$2;
      final result = switch (_order) {
        'antiguas' => intOf(
          a['solicitada_at'],
        ).compareTo(intOf(b['solicitada_at'])),
        'recientes' => intOf(
          b['solicitada_at'],
        ).compareTo(intOf(a['solicitada_at'])),
        'comision' => byProductNumber(a, b, 'comision_por_venta_centavos'),
        'vendidas' => byProductNumber(a, b, 'unidades_vendidas_global'),
        'precio' => byProductNumber(a, b, 'precio_venta_min_centavos'),
        'tienda' => _sampleSearchText(
          mapOf(a['tienda'])['nombre'],
        ).compareTo(_sampleSearchText(mapOf(b['tienda'])['nombre'])),
        _ => (mapOf(b['avance'])['fijada'] == true ? 1 : 0).compareTo(
          mapOf(a['avance'])['fijada'] == true ? 1 : 0,
        ),
      };
      return result == 0 ? left.$1.compareTo(right.$1) : result;
    });
    return filtered.map((entry) => entry.$2).toList();
  }

  Widget _tools(Map<String, String> shops, Set<String> groups, bool desktop) =>
      LayoutBuilder(
        builder: (context, limits) {
          final search = TextField(
            controller: _query,
            onChanged: (_) => setState(() {}),
            decoration: const InputDecoration(
              labelText: 'Buscar por producto, tienda o variante',
              floatingLabelBehavior: FloatingLabelBehavior.never,
              prefixIcon: Icon(Icons.search_rounded, size: 18),
            ),
          );
          final tools = Wrap(
            spacing: 8,
            runSpacing: 8,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              OutlinedButton.icon(
                onPressed: () => setState(() => _filters = !_filters),
                icon: const Icon(Icons.tune_rounded, size: 18),
                label: Text(
                  _filterCount == 0 ? 'Filtros' : 'Filtros ($_filterCount)',
                ),
              ),
              if (!widget.all)
                _SampleMenu(
                  label: 'Agrupar por',
                  values: _sampleGroupingLabels,
                  value: _grouping,
                  onChanged: (value) => setState(() => _grouping = value),
                ),
              _SampleMenu(
                label: 'Ordenar',
                values: _sampleOrderLabels,
                value: _order,
                onChanged: (value) => setState(() => _order = value),
              ),
              if (desktop || !widget.all)
                _SampleMenu(
                  label: 'Vista',
                  values: {
                    'lista': 'Lista',
                    if (desktop) 'tabla': 'Tabla',
                    if (!widget.all) 'tablero': 'Tablero',
                  },
                  value: _view,
                  onChanged: (value) => setState(() => _view = value),
                ),
              if (!widget.all && !_selecting)
                OutlinedButton.icon(
                  onPressed: () => setState(() => _selecting = true),
                  icon: const Icon(Icons.check_box_outlined, size: 18),
                  label: const Text('Seleccionar'),
                ),
            ],
          );
          final scale = MediaQuery.textScalerOf(context).scale(13) / 13;
          return Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              if (limits.maxWidth > 870 * scale)
                Row(
                  children: [
                    Expanded(child: search),
                    const SizedBox(width: 12),
                    Flexible(flex: 2, child: tools),
                  ],
                )
              else ...[
                search,
                const SizedBox(height: 10),
                tools,
              ],
              if (_filters) ...[
                const SizedBox(height: 12),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  crossAxisAlignment: WrapCrossAlignment.center,
                  children: [
                    if (shops.isNotEmpty)
                      _SampleMenu(
                        label: 'Tienda',
                        values: {'': 'Todas las tiendas', ...shops},
                        value: shops.containsKey(_store) ? _store : '',
                        onChanged: (value) => setState(() => _store = value),
                        showValue: true,
                      ),
                    for (final group in groups)
                      FilterChip(
                        label: Text(
                          group == 'en_revision'
                              ? 'En revisión'
                              : stageLabel(group),
                        ),
                        selected: _stages.contains(group),
                        onSelected: (selected) => setState(() {
                          if (selected) {
                            _stages.add(group);
                          } else {
                            _stages.remove(group);
                          }
                        }),
                      ),
                    FilterChip(
                      label: const Text('Ya lo vendo'),
                      selected: _selling,
                      onSelected: (value) => setState(() => _selling = value),
                    ),
                    FilterChip(
                      label: const Text('Se puede etiquetar'),
                      selected: _taggable,
                      onSelected: (value) => setState(() => _taggable = value),
                    ),
                    FilterChip(
                      label: const Text('Con promesa'),
                      selected: _withPromise,
                      onSelected: (value) =>
                          setState(() => _withPromise = value),
                    ),
                    FilterChip(
                      label: const Text('Recibidas'),
                      selected: _onlyReceived,
                      onSelected: (value) =>
                          setState(() => _onlyReceived = value),
                    ),
                    FilterChip(
                      label: const Text('Fijadas'),
                      selected: _onlyPinned,
                      onSelected: (value) =>
                          setState(() => _onlyPinned = value),
                    ),
                  ],
                ),
              ],
            ],
          );
        },
      );

  Widget _tile(_SampleRow sample, String? section, {required bool table}) {
    final id = textOf(sample['application_id']);
    void toggleSelection() {
      setState(() {
        if (!_selected.remove(id)) _selected.add(id);
      });
    }

    final canSelect = !widget.all && id.isNotEmpty;
    final selection = _selecting && canSelect;
    final tile = SampleTile(
      muestra: sample,
      compact: true,
      queueSection: section,
      table: table,
      onOpen: selection ? toggleSelection : null,
    );
    if (selection) {
      return Row(
        children: [
          Semantics(
            label: 'Seleccionar ${productName(mapOf(sample['producto']))}',
            child: Checkbox(
              value: _selected.contains(id),
              onChanged: (_) => toggleSelection(),
            ),
          ),
          Expanded(child: tile),
        ],
      );
    }
    if (!canSelect) return tile;
    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      onLongPress: () => setState(() {
        _selecting = true;
        _selected.add(id);
      }),
      child: tile,
    );
  }

  Widget _selectionBar(BuildContext context, List<_SampleRow> pending) {
    final selected = pending
        .where((sample) => _selected.contains(textOf(sample['application_id'])))
        .toList();
    final stores = _pendingSamplesByStore(selected).keys.toList();
    return SafeArea(
      top: false,
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
        decoration: BoxDecoration(
          color: context.corte.surface,
          border: Border(top: BorderSide(color: context.corte.line)),
        ),
        child: Wrap(
          spacing: 12,
          runSpacing: 6,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            Text(
              '${integer(_selected.length)} '
              '${_selected.length == 1 ? 'seleccionada' : 'seleccionadas'}',
            ),
            FilledButton(
              onPressed: stores.isEmpty
                  ? null
                  : () => CorteScope.of(context).go(
                      Uri(
                        path: '/muestras/avisos',
                        queryParameters: {'tiendas': stores.join(',')},
                      ).toString(),
                    ),
              child: const Text('Avisar a estas tiendas'),
            ),
            TextButton(
              onPressed: () => setState(() {
                _selecting = false;
                _selected.clear();
              }),
              child: const Text('Quitar selección'),
            ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) => ApiData(
    path: '/api/muestras',
    query: const {'orden': 'prioridad'},
    builder: (context, data) {
      final ui = CorteScope.of(context);
      final desktop = useDesktopWorkspace(context);
      final all = rowsOf(data['items']);
      final queue = all
          .where((sample) => _sampleGroups.contains(sample['grupo']))
          .toList();
      final pending = queue.where(samplePending).toList();
      final source = widget.all
          ? all
          : queue
                .where((sample) => _samplePrioritySection(sample) != null)
                .toList();
      final shops = <String, String>{};
      final groups = <String>{};
      for (final sample in source) {
        final shop = mapOf(sample['tienda']);
        final key = textOf(shop['tienda_key']);
        final group = textOf(sample['grupo']);
        if (key.isNotEmpty) shops[key] = textOf(shop['nombre'], 'Tienda');
        if (group.isNotEmpty) groups.add(group);
      }
      final stores = _pendingSamplesByStore(pending);
      final announced = stores.values
          .where((items) => items.every(_sampleNoticeSent))
          .length;
      final plan =
          pending
              .map(
                (sample) =>
                    _sampleLocalDate(mapOf(sample['avance'])['fecha_planeada']),
              )
              .nonNulls
              .toList()
            ..sort();
      final hasPlan = pending.any(
        (sample) =>
            textOf(mapOf(sample['avance'])['etapa'], 'por_planear') !=
            'por_planear',
      );
      final notices = hasPlan && announced < stores.length;
      final filtered = _visibleSamples(source);
      final board = !widget.all && _view == 'tablero';
      final table = desktop && _view == 'tabla';
      final sections = board
          ? const <_SampleSection>[]
          : widget.all
          ? <_SampleSection>[_SampleSection('todas', '', filtered)]
          : _groupSamples(filtered, _grouping);
      final rows = <(Widget?, _SampleRow?, String?)>[];
      if (board && filtered.isNotEmpty) {
        rows.add((
          _SampleBoard(
            samples: filtered,
            buildTile: (sample) =>
                _tile(sample, _samplePrioritySection(sample), table: false),
          ),
          null,
          null,
        ));
      }
      for (final section in sections) {
        final collapsed = _collapsed[section.key] ?? section.key == 'no_hacer';
        if (!widget.all) {
          rows.add((
            _SampleQueueHeading(
              title: section.title,
              count: section.samples.length,
              collapsed: collapsed,
              onPressed: () =>
                  setState(() => _collapsed[section.key] = !collapsed),
            ),
            null,
            null,
          ));
        }
        if (collapsed || section.samples.isEmpty) continue;
        if (table) {
          rows.add((const _SampleTableHeader(), null, null));
        }
        for (final sample in section.samples) {
          rows.add((
            null,
            sample,
            widget.all ? null : _samplePrioritySection(sample),
          ));
        }
      }
      final count = widget.all
          ? intOf(data['total'], all.length)
          : pending.length;
      final titleCount = integer(count);
      final subtitle = widget.all
          ? '$titleCount ${count == 1 ? 'muestra' : 'muestras'}'
          : '$titleCount ${count == 1 ? 'pendiente' : 'pendientes'}';
      final planLabel = hasPlan ? 'Rehacer mi plan' : 'Armar mi plan';

      final list = RefreshIndicator(
        onRefresh: () async => ui.refresh(),
        child: ListView.builder(
          key: PageStorageKey(widget.all ? 'todas' : 'pendientes'),
          padding: pagePadding(context),
          itemCount: rows.length + 1,
          itemBuilder: (context, index) {
            if (index > 0) {
              final row = rows[index - 1];
              if (row.$1 case final heading?) return heading;
              return _tile(row.$2!, row.$3, table: table);
            }
            return Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                PageTitle(
                  'Muestras',
                  subtitle: subtitle,
                  action: Wrap(
                    spacing: 8,
                    crossAxisAlignment: WrapCrossAlignment.center,
                    children: [
                      if (pending.isNotEmpty)
                        FilledButton.icon(
                          onPressed: () => ui.go(
                            notices ? '/muestras/avisos' : '/muestras/plan',
                          ),
                          icon: Icon(
                            notices
                                ? Icons.chat_bubble_outline_rounded
                                : Icons.calendar_month_outlined,
                            size: 18,
                          ),
                          label: Text(
                            notices ? 'Avisar a mis tiendas' : planLabel,
                          ),
                        ),
                      PopupMenuButton<String>(
                        tooltip: 'Más acciones de muestras',
                        onSelected: ui.go,
                        itemBuilder: (_) => [
                          if (notices)
                            PopupMenuItem(
                              value: '/muestras/plan',
                              child: Text(planLabel),
                            )
                          else
                            const PopupMenuItem(
                              value: '/muestras/avisos',
                              child: Text('Avisar a mis tiendas'),
                            ),
                        ],
                      ),
                    ],
                  ),
                ),
                _SampleTabs(
                  current: widget.all ? '/muestras/todas' : '/muestras',
                  total: intOf(data['total'], all.length),
                  pending: pending.length,
                ),
                if (!widget.all && pending.isNotEmpty) ...[
                  const SizedBox(height: 12),
                  _SampleProgress(
                    queue: queue,
                    pending: pending,
                    storeCount: stores.length,
                    announced: announced,
                    finish: plan.lastOrNull,
                  ),
                ],
                const SizedBox(height: 16),
                if (source.isNotEmpty || _filterCount > 0)
                  _tools(shops, groups, desktop),
                if (_filterCount > 0)
                  Wrap(
                    spacing: 16,
                    crossAxisAlignment: WrapCrossAlignment.center,
                    children: [
                      Text(
                        '${integer(filtered.length)} '
                        '${filtered.length == 1 ? 'resultado' : 'resultados'}',
                      ),
                      TextButton(
                        onPressed: _clearFilters,
                        child: const Text('Limpiar filtros'),
                      ),
                    ],
                  ),
                if (filtered.isEmpty)
                  EmptyState(
                    source.isEmpty
                        ? (widget.all
                              ? 'Todavía no hay muestras'
                              : 'No hay muestras pendientes')
                        : 'Ninguna muestra coincide con estos filtros',
                    text: source.isEmpty
                        ? 'Las solicitudes de tu cuenta aparecerán aquí al sincronizar.'
                        : 'Cambia la búsqueda o los filtros.',
                  )
                else
                  const SizedBox(height: 14),
              ],
            );
          },
        ),
      );
      if (!_selecting) return list;
      return Column(
        children: [
          Expanded(child: list),
          _selectionBar(context, pending),
        ],
      );
    },
  );
}

class _SampleBoard extends StatelessWidget {
  const _SampleBoard({required this.samples, required this.buildTile});

  final List<_SampleRow> samples;
  final Widget Function(_SampleRow sample) buildTile;

  @override
  Widget build(BuildContext context) {
    final stages = <String, List<_SampleRow>>{};
    for (final sample in samples) {
      final stage = textOf(mapOf(sample['avance'])['etapa'], 'por_planear');
      if (samplePending(sample) ||
          (stage == 'publicada' && sample['grupo'] != 'en_revision')) {
        (stages[stage] ??= []).add(sample);
      }
    }
    return Semantics(
      label: 'Tablero de muestras por etapa',
      child: LayoutBuilder(
        builder: (context, limits) {
          final columnWidth = limits.maxWidth >= 1080
              ? 300.0
              : (limits.maxWidth - 14).clamp(0.0, 290.0).toDouble();
          return SingleChildScrollView(
            key: const PageStorageKey('muestras-tablero'),
            scrollDirection: Axis.horizontal,
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                for (final stage in [
                  'por_planear',
                  'planeada',
                  'video_listo',
                  if (stages.containsKey('programada')) 'programada',
                  'publicada',
                ])
                  Container(
                    width: columnWidth,
                    margin: const EdgeInsets.only(right: 12),
                    decoration: BoxDecoration(
                      color: context.corte.soft,
                      border: Border.all(color: context.corte.line),
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        Padding(
                          padding: const EdgeInsets.all(12),
                          child: Wrap(
                            spacing: 8,
                            runSpacing: 4,
                            children: [
                              Semantics(
                                header: true,
                                child: Text(
                                  stageLabel(stage),
                                  style: Theme.of(context)
                                      .textTheme
                                      .titleMedium,
                                ),
                              ),
                              Text(
                                integer(stages[stage]?.length ?? 0),
                                style: TextStyle(color: context.corte.muted),
                              ),
                            ],
                          ),
                        ),
                        if (stages[stage] case final lane?)
                          for (final sample in lane) buildTile(sample)
                        else
                          Padding(
                            padding: const EdgeInsets.fromLTRB(12, 0, 12, 14),
                            child: Text(
                              'Nada aquí todavía',
                              style: TextStyle(color: context.corte.muted),
                            ),
                          ),
                      ],
                    ),
                  ),
              ],
            ),
          );
        },
      ),
    );
  }
}

class _SampleMenu extends StatelessWidget {
  const _SampleMenu({
    required this.label,
    required this.values,
    required this.value,
    required this.onChanged,
    this.showValue = false,
  });

  final String label;
  final Map<String, String> values;
  final String value;
  final ValueChanged<String> onChanged;
  final bool showValue;

  @override
  Widget build(BuildContext context) => MenuAnchor(
    key: PageStorageKey('muestras-menu-$label'),
    builder: (context, controller, _) => OutlinedButton.icon(
      onPressed: () =>
          controller.isOpen ? controller.close() : controller.open(),
      icon: const Icon(Icons.expand_more_rounded, size: 18),
      label: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 170),
        child: Text(
          showValue
              ? values[value] ?? label
              : '$label: ${values[value] ?? label}',
          maxLines: 2,
          overflow: TextOverflow.ellipsis,
        ),
      ),
    ),
    menuChildren: [
      for (final option in values.entries)
        MenuItemButton(
          onPressed: () => onChanged(option.key),
          leadingIcon: option.key == value
              ? const Icon(Icons.check_rounded, size: 16)
              : const SizedBox(width: 16),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 280),
            child: Text(option.value),
          ),
        ),
    ],
  );
}

class _SampleQueueHeading extends StatelessWidget {
  const _SampleQueueHeading({
    required this.title,
    required this.count,
    required this.collapsed,
    required this.onPressed,
  });

  final String title;
  final int count;
  final bool collapsed;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) => Semantics(
    header: true,
    expanded: !collapsed,
    child: Padding(
      padding: const EdgeInsets.only(bottom: 6, top: 4),
      child: TextButton(
        style: TextButton.styleFrom(
          foregroundColor: context.corte.ink,
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 10),
          minimumSize: const Size(44, 44),
        ),
        onPressed: onPressed,
        child: Row(
          children: [
            Icon(
              collapsed
                  ? Icons.chevron_right_rounded
                  : Icons.expand_more_rounded,
              size: 20,
            ),
            const SizedBox(width: 5),
            Flexible(
              child: Text(
                title,
                style: Theme.of(context).textTheme.titleMedium,
              ),
            ),
            const SizedBox(width: 8),
            Text(integer(count), style: TextStyle(color: context.corte.muted)),
          ],
        ),
      ),
    ),
  );
}

class _SampleProgress extends StatelessWidget {
  const _SampleProgress({
    required this.queue,
    required this.pending,
    required this.storeCount,
    required this.announced,
    this.finish,
  });

  final List<_SampleRow> queue;
  final List<_SampleRow> pending;
  final int storeCount;
  final int announced;
  final DateTime? finish;

  @override
  Widget build(BuildContext context) {
    final published = queue.where((sample) {
      final advance = mapOf(sample['avance']);
      if (advance['etapa'] == 'no_se_puede' || samplePending(sample)) {
        return false;
      }
      if (sample['grupo'] == 'en_revision') return advance['plan_id'] != null;
      return advance['etapa'] == 'publicada' &&
          advance['vinculo_origen'] != 'video_previo';
    }).length;
    final total = pending.length + published;
    int countStage(String stage) => pending
        .where((sample) => mapOf(sample['avance'])['etapa'] == stage)
        .length;
    final end = finish;
    final planText = end == null
        ? 'Plan: sin plan'
        : 'Plan: terminas el ${_sampleDateLabel(end)} · publicas a más tardar el '
              '${_sampleDateLabel(end.add(const Duration(days: 2)))}';
    return DecoratedBox(
      decoration: BoxDecoration(
        border: Border.all(color: context.corte.line),
        borderRadius: BorderRadius.circular(8),
      ),
      child: ExpansionTile(
        key: const PageStorageKey('muestras-avance'),
        tilePadding: const EdgeInsets.symmetric(horizontal: 14),
        childrenPadding: const EdgeInsets.fromLTRB(14, 2, 14, 16),
        shape: const Border(),
        collapsedShape: const Border(),
        title: Wrap(
          spacing: 12,
          runSpacing: 5,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            Text('Tu avance', style: Theme.of(context).textTheme.titleMedium),
            Text(
              '${integer(published)} videos publicados',
              style: TextStyle(color: context.corte.muted),
            ),
          ],
        ),
        expandedCrossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Te faltan ${integer(pending.length)} '
            '${pending.length == 1 ? 'video' : 'videos'}',
          ),
          const SizedBox(height: 8),
          LinearProgressIndicator(
            value: total == 0 ? 0 : published / total,
            minHeight: 5,
            semanticsLabel:
                '${integer(published)} de ${integer(total)} videos publicados',
          ),
          const SizedBox(height: 8),
          Wrap(
            spacing: 12,
            runSpacing: 6,
            children: [
              Text(
                '${integer(published)} de ${integer(total)} videos publicados',
              ),
              Text('Planeadas ${integer(countStage('planeada'))}'),
              Text('Video listo ${integer(countStage('video_listo'))}'),
              if (countStage('programada') > 0)
                Text('Programadas ${integer(countStage('programada'))}'),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            'Tiendas avisadas: ${integer(announced)} de ${integer(storeCount)}',
          ),
          const SizedBox(height: 4),
          Text(planText),
        ],
      ),
    );
  }
}

class _SampleTabs extends StatelessWidget {
  const _SampleTabs({required this.current, this.total, this.pending});

  final String current;
  final int? total, pending;

  @override
  Widget build(BuildContext context) => Container(
    decoration: BoxDecoration(
      border: Border(bottom: BorderSide(color: context.corte.line)),
    ),
    child: LayoutBuilder(
      builder: (context, constraints) => SingleChildScrollView(
        key: const PageStorageKey('muestras-pestanas'),
        scrollDirection: Axis.horizontal,
        child: ConstrainedBox(
          constraints: BoxConstraints(minWidth: constraints.maxWidth),
          child: Row(
            mainAxisAlignment: useDesktopWorkspace(context)
                ? MainAxisAlignment.start
                : MainAxisAlignment.spaceBetween,
            children: [
              for (final tab in [
                ('/muestras', 'Pendientes', pending),
                ('/muestras/agenda', 'Agenda', null),
                ('/muestras/todas', 'Todas', total),
              ])
                Semantics(
                  selected: tab.$1 == current,
                  child: InkWell(
                    onTap: () => CorteScope.of(context).go(tab.$1),
                    child: Container(
                      constraints: const BoxConstraints(minHeight: 44),
                      alignment: Alignment.center,
                      padding: const EdgeInsets.symmetric(
                        horizontal: 10,
                        vertical: 9,
                      ),
                      decoration: BoxDecoration(
                        border: Border(
                          bottom: BorderSide(
                            color: tab.$1 == current
                                ? CorteColors.coral
                                : Colors.transparent,
                            width: 3,
                          ),
                        ),
                      ),
                      child: Row(
                        children: [
                          Text(
                            tab.$2,
                            style: TextStyle(
                              fontWeight: tab.$1 == current
                                  ? FontWeight.w700
                                  : FontWeight.w500,
                            ),
                          ),
                          if (tab.$3 case final count?) ...[
                            const SizedBox(width: 6),
                            Text(
                              integer(count),
                              style: TextStyle(color: context.corte.muted),
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
  );
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
  const _CompactSampleTile({
    required this.muestra,
    this.queueSection,
    required this.table,
    this.onOpen,
  });
  final Map<String, dynamic> muestra;
  final String? queueSection;
  final bool table;
  final VoidCallback? onOpen;

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
    final wantsNotice =
        queueSection == 'falta_avisar' || queueSection == 'no_etiquetar';
    final canAct =
        onOpen == null &&
        queueSection != 'en_revision' &&
        queueSection != 'no_hacer';
    final buttonLabel = wantsNotice
        ? 'Avisar'
        : stage == 'por_planear' || stage.isEmpty
        ? 'Planear'
        : 'Avance';
    final queueNumber = intOf(muestra['posicion_cola']);
    void openDetail() => CorteScope.of(context).go(
      '/muestras/m/${Uri.encodeComponent(textOf(muestra['application_id']))}',
    );
    return LayoutBuilder(
      builder: (context, limits) {
        final wide = table && _sampleColumnsFit(context, limits.maxWidth);
        final columns = _SampleColumnWidths(context);
        final stackAction = !wide && limits.maxWidth < 560 * columns.scale;
        final button = canAct
            ? OutlinedButton(
                onPressed: () {
                  if (wantsNotice) {
                    showMessageEditor(
                      context,
                      tienda: shop,
                      muestras: [muestra],
                    );
                  } else {
                    showPlanEditor(context, muestra);
                  }
                },
                style: OutlinedButton.styleFrom(
                  minimumSize: const Size(44, 34),
                  padding: const EdgeInsets.symmetric(
                    horizontal: 10,
                    vertical: 6,
                  ),
                  textStyle: const TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w500,
                  ),
                ),
                child: Text(buttonLabel),
              )
            : null;
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
              if (queueSection != null && queueNumber > 0) ...[
                Text(
                  'Nº ${integer(queueNumber)} en tu cola',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
                const SizedBox(height: 3),
              ],
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
          onTap: onOpen ?? openDetail,
          label:
              'Producto: ${productName(product)}. Tienda: ${textOf(shop['nombre'])}. '
              'Variante: $variant. Estado: $status. '
              '${muestra['recibida'] == true ? 'Muestra recibida.' : ''}',
          child: Material(
            color: context.corte.surface,
            child: InkWell(
              excludeFromSemantics: true,
              onTap: onOpen ?? openDetail,
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
                    Expanded(
                      child: stackAction && button != null
                          ? Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                identity,
                                const SizedBox(height: 6),
                                button,
                              ],
                            )
                          : identity,
                    ),
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
                    if (wide) ...[
                      const SizedBox(width: 16),
                      SizedBox(
                        width: columns.action,
                        child: Align(
                          alignment: Alignment.centerRight,
                          child: button,
                        ),
                      ),
                    ] else if (!stackAction && button != null) ...[
                      const SizedBox(width: 16),
                      button,
                    ],
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
  const SampleTile({
    super.key,
    required this.muestra,
    this.compact = false,
    this.queueSection,
    this.table = true,
    this.onOpen,
  });
  final Map<String, dynamic> muestra;
  final bool compact;
  final String? queueSection;
  final bool table;
  final VoidCallback? onOpen;
  @override
  Widget build(BuildContext context) {
    if (compact || useDesktopWorkspace(context)) {
      return _CompactSampleTile(
        muestra: muestra,
        queueSection: queueSection,
        table: table,
        onOpen: onOpen,
      );
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
                const SizedBox(height: 12),
                ExpansionTile(
                  tilePadding: EdgeInsets.zero,
                  title: const Text('Tallas, reseñas y fotos de compradores'),
                  children: [
                    ProductEvidence(
                      productId: textOf(p['product_id']),
                      extended: mapOf(product['extendido']),
                      openOriginal: textOf(p['enlace']).isEmpty
                          ? null
                          : () => openPublicLink(context, textOf(p['enlace'])),
                    ),
                  ],
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
          const _SampleTabs(current: '/muestras/agenda'),
          const SizedBox(height: 12),
          if (plans.isEmpty)
            EmptyState(
              'Tu siguiente video empieza aquí',
              text: 'Elige una muestra y asígnale una fecha para armar tu agenda.',
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

class SampleStoreNoticesPage extends StatelessWidget {
  const SampleStoreNoticesPage({super.key, this.storeKeys});

  final Set<String>? storeKeys;

  @override
  Widget build(BuildContext context) => ApiData(
    path: '/api/muestras',
    query: const {'orden': 'prioridad'},
    builder: (context, data) {
      final stores = _pendingSamplesByStore(rowsOf(data['items']));
      final allowed = storeKeys;
      if (allowed != null) {
        stores.removeWhere((key, _) => !allowed.contains(key));
      }
      final remaining = stores.values
          .where((list) => !list.every(_sampleNoticeSent))
          .toList();
      return ListView(
        padding: pagePadding(context),
        children: [
          PageTitle(
            'Avisar a mis tiendas',
            subtitle:
                '${integer(stores.length - remaining.length)} de '
                '${integer(stores.length)} tiendas avisadas',
            back: () => CorteScope.of(context).go('/muestras'),
          ),
          if (remaining.isEmpty)
            const EmptyState('Ya estás al día con tus tiendas')
          else ...[
            Text(
              'Prepara el mensaje de cada tienda y confirma en CUTGC cuando lo hayas enviado.',
              style: TextStyle(color: context.corte.muted),
            ),
            const SizedBox(height: 16),
            for (final samples in remaining)
              _SampleStoreNoticeRow(samples: samples),
          ],
        ],
      );
    },
  );
}

class _SampleStoreNoticeRow extends StatelessWidget {
  const _SampleStoreNoticeRow({required this.samples});

  final List<_SampleRow> samples;

  @override
  Widget build(BuildContext context) {
    final store = mapOf(samples.first['tienda']);
    final pending = samples
        .where((sample) => !_sampleNoticeSent(sample))
        .toList();
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Card(
        margin: EdgeInsets.zero,
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: () =>
              showMessageEditor(context, tienda: store, muestras: pending),
          child: Padding(
            padding: const EdgeInsets.all(14),
            child: Row(
              children: [
                Icon(
                  Icons.chat_bubble_outline_rounded,
                  color: context.corte.action,
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        textOf(store['nombre'], 'Tienda'),
                        style: Theme.of(context).textTheme.titleMedium,
                      ),
                      const SizedBox(height: 4),
                      Text(
                        '${integer(pending.length)} '
                        '${pending.length == 1 ? 'muestra por avisar' : 'muestras por avisar'}',
                        style: TextStyle(color: context.corte.muted),
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
      ),
    );
  }
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
