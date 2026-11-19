part of 'catalog.dart';

const _salesPeriods = {
  '7d': '7 días',
  '30d': '30 días',
  '90d': '90 días',
  '12m': '12 meses',
  'todo': 'Todo',
};

String? _salesPeriod(String? value) {
  if (value == null) return null;
  if (_salesPeriods.containsKey(value)) return value;
  final match = RegExp(r'^(20\d\d|2100)-(0[1-9]|1[0-2])$').firstMatch(value);
  return match == null ? null : value;
}

const _salesMonthNames = [
  'ene',
  'feb',
  'mar',
  'abr',
  'may',
  'jun',
  'jul',
  'ago',
  'sep',
  'oct',
  'nov',
  'dic',
];

String _salesDate(String value, {bool monthOnly = false}) {
  final date = DateTime.tryParse(value.length == 7 ? '$value-01' : value);
  if (date == null) return value;
  final month = _salesMonthNames[date.month - 1];
  return monthOnly ? '$month ${date.year}' : '${date.day} $month';
}

String _salesMonthKey(DateTime date) =>
    '${date.year}-${date.month.toString().padLeft(2, '0')}';

DateTime _salesToday(Map<String, dynamic> data) {
  final today = mapOf(mapOf(data['actualidad'])['hoy'])['fecha'];
  final explicit = DateTime.tryParse(textOf(today));
  if (explicit != null) return explicit;
  final generated = data['generado_at'];
  final timestamp = generated is int
      ? DateTime.fromMillisecondsSinceEpoch(generated * 1000, isUtc: true)
      : DateTime.now().toUtc();
  // The clock of current Mexico City reporting is UTC−06. Historical dates
  // arrive already resolved by the server in periodo/serie.
  return timestamp.subtract(const Duration(hours: 6));
}

double? _salesNumber(Object? value) =>
    value is num && value.isFinite ? value.toDouble() : null;

String _salesInteger(Object? value) =>
    _salesNumber(value) == null ? '—' : integer(value);

String _salesMoney(Object? value, {bool approximate = false}) {
  if (_salesNumber(value) == null) return '—';
  final amount = money(value);
  return approximate ? '≈ $amount' : amount;
}

String _salesPercent(double? rate, {int digits = 1}) =>
    rate == null ? '—' : '${(rate * 100).toStringAsFixed(digits)} %';

class SalesPage extends StatefulWidget {
  const SalesPage({super.key});
  @override
  State<SalesPage> createState() => _SalesPageState();
}

class _SalesPageState extends State<SalesPage> {
  String _lastPeriod = '30d';
  bool _compare = true;

  @override
  Widget build(BuildContext context) {
    final ui = CorteScope.of(context);
    final route = Uri.tryParse(ui.location);
    final params = route?.queryParameters ?? const <String, String>{};
    final period = _salesPeriod(params['periodo']) ?? _lastPeriod;
    void selectPeriod(String value) {
      if (period == value) return;
      setState(() => _lastPeriod = value);
      final next = {...params, 'periodo': value}..remove('pedido');
      ui.replace(Uri(path: '/ventas', queryParameters: next).toString());
    }

    return ApiData(
      path: '/api/dashboard',
      query: {'periodo': period},
      errorBuilder: (context, _) => ListView(
        padding: pagePadding(context),
        children: [
          const PageTitle('Ventas'),
          _SalesPeriodControl(
            selected: period,
            now: _salesToday(const {}),
            onSelect: selectPeriod,
          ),
          EmptyState(
            'No pudimos cargar tus ventas',
            text: 'Conéctate para actualizar o elige otro periodo.',
            icon: Icons.bar_chart_rounded,
            action: OutlinedButton.icon(
              onPressed: ui.refresh,
              icon: const Icon(Icons.refresh_rounded),
              label: const Text('Reintentar'),
            ),
          ),
          TextButton(
            onPressed: () => ui.go('/ordenes'),
            child: const Text('Ver todos los pedidos'),
          ),
        ],
      ),
      builder: (context, data) {
        final range = mapOf(data['periodo']);
        final from = textOf(range['desde']);
        final to = textOf(range['hasta']);
        final validRange =
            DateTime.tryParse(from) != null && DateTime.tryParse(to) != null;
        final kpis = mapOf(data['kpis']);
        final previous = mapOf(data['kpis_anterior']);
        final periodLabel = _salesPeriods.containsKey(period)
            ? (period == 'todo' ? 'todo' : 'últimos ${_salesPeriods[period]}')
            : _salesDate(period, monthOnly: true);
        final dateRange = from == to
            ? _salesDate(from)
            : '${_salesDate(from)} – ${_salesDate(to)}';
        final metadata = [
          if (validRange) dateRange,
          'por fecha del pedido',
          'hora de la Ciudad de México',
          'montos en MXN',
        ].join(' · ');
        return ListView(
          padding: pagePadding(context),
          children: [
            PageTitle('Ventas', subtitle: metadata),
            _SalesPeriodControl(
              selected: period,
              now: _salesToday(data),
              onSelect: selectPeriod,
            ),
            if (previous.isNotEmpty)
              Align(
                alignment: Alignment.centerRight,
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 380),
                  child: SwitchListTile(
                    contentPadding: const EdgeInsets.symmetric(horizontal: 4),
                    title: const Text('Comparar con el periodo anterior'),
                    value: _compare,
                    onChanged: (value) => setState(() => _compare = value),
                  ),
                ),
              ),
            _SalesKpis(
              title: 'Tu dinero · $periodLabel',
              values: kpis,
              previous: _compare ? previous : const {},
            ),
            if (_salesNumber(kpis['pedidos']) == 0)
              EmptyState(
                'No hay pedidos en este periodo',
                icon: Icons.bar_chart_rounded,
                text: 'Prueba con un rango más amplio.',
                action: const {'90d', '12m', 'todo'}.contains(period)
                    ? null
                    : TextButton(
                        onPressed: () => selectPeriod('90d'),
                        child: const Text('Ver últimos 90 días'),
                      ),
              )
            else if (validRange)
              _SalesBreakdown(
                key: ValueKey('$period:$from:$to'),
                from: from,
                to: to,
                today: _salesToday(data),
                dashboard: data,
              ),
            if (validRange)
              _SalesOrders(
                key: ValueKey('$period:$from:$to'),
                from: period == 'todo' ? null : from,
                to: period == 'todo' ? null : to,
              ),
          ],
        );
      },
    );
  }
}

class _SalesPeriodControl extends StatelessWidget {
  const _SalesPeriodControl({
    required this.selected,
    required this.now,
    required this.onSelect,
  });

  final String selected;
  final DateTime now;
  final ValueChanged<String> onSelect;

  @override
  Widget build(BuildContext context) {
    final currentMonth = _salesMonthKey(now);
    final previousMonth = _salesMonthKey(DateTime(now.year, now.month - 1));
    return Semantics(
      container: true,
      label: 'Periodo',
      child: Wrap(
        crossAxisAlignment: WrapCrossAlignment.center,
        spacing: 8,
        runSpacing: 5,
        children: [
          for (final item in _salesPeriods.entries)
            ChoiceChip(
              label: Text(item.value),
              selected: selected == item.key,
              onSelected: (_) => onSelect(item.key),
            ),
          PopupMenuButton<String>(
            tooltip: 'Otro periodo',
            onSelected: onSelect,
            initialValue: _salesPeriods.containsKey(selected) ? null : selected,
            itemBuilder: (context) => [
              PopupMenuItem(
                value: currentMonth,
                child: Text(
                  'Este mes (${_salesDate(currentMonth, monthOnly: true)})',
                ),
              ),
              PopupMenuItem(
                value: previousMonth,
                child: Text(
                  'Mes pasado (${_salesDate(previousMonth, monthOnly: true)})',
                ),
              ),
            ],
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Icon(Icons.calendar_today_outlined, size: 17),
                  const SizedBox(width: 8),
                  Flexible(
                    child: Text(
                      _salesPeriods.containsKey(selected)
                          ? 'Otro periodo'
                          : _salesDate(selected, monthOnly: true),
                    ),
                  ),
                  const SizedBox(width: 4),
                  const Icon(Icons.expand_more, size: 18),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

enum _SalesValue { currency, integer, rate, approximate }

String _formatSalesValue(Object? value, _SalesValue kind) => switch (kind) {
  _SalesValue.currency => _salesMoney(value),
  _SalesValue.approximate => _salesMoney(value, approximate: true),
  _SalesValue.integer => _salesInteger(value),
  _SalesValue.rate => _salesPercent(_salesNumber(value)),
};

const _salesKpiItems = [
  (
    'Comisión estimada',
    'comision_total_centavos',
    _SalesValue.currency,
    true,
    false,
  ),
  (
    'Liquidada',
    'comision_liquidada_centavos',
    _SalesValue.currency,
    false,
    false,
  ),
  (
    'Por liquidar',
    'comision_por_liquidar_centavos',
    _SalesValue.currency,
    false,
    false,
  ),
  (
    'Perdida (reembolsos)',
    'comision_perdida_reembolsos_centavos',
    _SalesValue.currency,
    true,
    true,
  ),
  ('Pedidos', 'pedidos', _SalesValue.integer, true, false),
  ('Tasa de reembolso', 'tasa_reembolso', _SalesValue.rate, true, true),
  ('Unidades vendidas', 'unidades', _SalesValue.integer, true, false),
  ('Ventas generadas', 'ventas_centavos', _SalesValue.approximate, true, false),
];

class _SalesKpis extends StatelessWidget {
  const _SalesKpis({
    required this.title,
    required this.values,
    required this.previous,
  });

  final String title;
  final Map<String, dynamic> values, previous;

  @override
  Widget build(BuildContext context) {
    final items = [..._salesKpiItems];
    if ((_salesNumber(values['comision_retenida_centavos']) ?? 0) > 0) {
      items.insert(3, (
        'Congelada',
        'comision_retenida_centavos',
        _SalesValue.currency,
        false,
        false,
      ));
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        SectionHeading(title),
        LayoutBuilder(
          builder: (context, limits) {
            final scale = MediaQuery.textScalerOf(context).scale(14) / 14;
            final width = limits.maxWidth;
            final columns = width >= 630 * scale
                ? 4
                : width >= 250 * scale
                ? 2
                : 1;
            const gap = 12.0;
            return Wrap(
              spacing: gap,
              runSpacing: gap,
              children: [
                for (final (label, key, kind, compare, lowerIsBetter) in items)
                  SizedBox(
                    width: (width - (columns - 1) * gap) / columns,
                    child: _SalesKpiCard(
                      label: label,
                      value: _formatSalesValue(values[key], kind),
                      delta: compare
                          ? _SalesTrend.of(
                              _salesNumber(values[key]),
                              _salesNumber(previous[key]),
                              lowerIsBetter: lowerIsBetter,
                              percentagePoints: kind == _SalesValue.rate,
                            )
                          : null,
                      note: switch (key) {
                        'comision_liquidada_centavos' ||
                        'comision_por_liquidar_centavos' =>
                          'De pedidos hechos en este periodo',
                        'comision_retenida_centavos' => 'En revisión de TikTok',
                        'comision_total_centavos' when previous.isEmpty =>
                          'Sin contar reembolsos',
                        'tasa_reembolso'
                            when values['pedidos_reembolsados'] != null =>
                          '${_salesInteger(values['pedidos_reembolsados'])} pedidos reembolsados',
                        'ventas_centavos' when previous.isEmpty =>
                          'Con el precio de venta',
                        _ => null,
                      },
                    ),
                  ),
              ],
            );
          },
        ),
      ],
    );
  }
}

class _SalesTrend {
  const _SalesTrend(this.text, this.direction, this.favorable);

  final String text;
  final int direction;
  final bool? favorable;

  static _SalesTrend? of(
    double? value,
    double? previous, {
    required bool lowerIsBetter,
    required bool percentagePoints,
  }) {
    if (value == null || previous == null) return null;
    if (previous == 0 && !percentagePoints) {
      return value > 0 ? _SalesTrend('Nuevo', 1, !lowerIsBetter) : null;
    }
    if (percentagePoints && value == 0 && previous == 0) return null;
    final difference = value - previous;
    final rounded = percentagePoints
        ? (difference * 1000).roundToDouble() / 10
        : (difference / previous * 100).roundToDouble();
    final direction = rounded.sign.toInt();
    final magnitude = rounded.abs();
    final label = percentagePoints
        ? '${magnitude.toStringAsFixed(1)} pts'
        : '${magnitude.toStringAsFixed(0)} %';
    return _SalesTrend(
      label,
      direction,
      direction == 0 ? null : (direction < 0) == lowerIsBetter,
    );
  }
}

class _SalesKpiCard extends StatelessWidget {
  const _SalesKpiCard({
    required this.label,
    required this.value,
    this.note,
    this.delta,
  });

  final String label, value;
  final String? note;
  final _SalesTrend? delta;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context).textTheme;
    final trend = delta;
    return _SalesPanel(
      padding: const EdgeInsets.all(14),
      child: ConstrainedBox(
        constraints: const BoxConstraints(minHeight: 80),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              label,
              style: theme.bodySmall?.copyWith(
                color: context.corte.muted,
                fontWeight: FontWeight.w600,
              ),
            ),
            const SizedBox(height: 5),
            Text(
              value,
              style: theme.titleLarge?.copyWith(
                fontWeight: FontWeight.w700,
                letterSpacing: -.3,
              ),
            ),
            if (trend != null) ...[
              const SizedBox(height: 4),
              Semantics(
                label:
                    'Variación respecto al periodo anterior: ${trend.direction < 0
                        ? 'bajó'
                        : trend.direction > 0
                        ? 'subió'
                        : 'sin cambio'} ${trend.text}',
                excludeSemantics: true,
                child: Text(
                  '${trend.direction < 0
                      ? '▼ '
                      : trend.direction > 0
                      ? '▲ '
                      : ''}${trend.text}',
                  style: theme.bodySmall?.copyWith(
                    color: switch (trend.favorable) {
                      true => context.corte.success,
                      false => context.corte.warning,
                      null => context.corte.muted,
                    },
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
            ],
            if (note != null) ...[
              const SizedBox(height: 4),
              Text(
                note!,
                style: theme.bodySmall?.copyWith(color: context.corte.muted),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _SalesPanel extends StatelessWidget {
  const _SalesPanel({
    required this.child,
    this.padding = const EdgeInsets.all(16),
  });

  final Widget child;
  final EdgeInsets padding;

  @override
  Widget build(BuildContext context) => Material(
    color: context.corte.soft,
    shape: RoundedRectangleBorder(
      borderRadius: BorderRadius.circular(9),
      side: BorderSide(color: context.corte.line),
    ),
    clipBehavior: Clip.antiAlias,
    child: Padding(padding: padding, child: child),
  );
}

enum _SalesGranularity {
  day('dia', 'Día', 'día'),
  week('semana', 'Semana', 'semana'),
  month('mes', 'Mes', 'mes');

  const _SalesGranularity(this.key, this.title, this.singular);
  final String key, title, singular;
}

enum _SalesMetric {
  commission('Comisión', _SalesValue.currency),
  orders('Pedidos', _SalesValue.integer),
  units('Unidades', _SalesValue.integer),
  refundRate('Tasa de reembolso', _SalesValue.rate);

  const _SalesMetric(this.title, this.kind);
  final String title;
  final _SalesValue kind;

  num? value(Map<String, dynamic> point) => switch (this) {
    _SalesMetric.commission => _salesNumber(
      point['comision_estimada_centavos'],
    ),
    _SalesMetric.orders => _salesNumber(point['pedidos']),
    _SalesMetric.units => _salesNumber(point['unidades']),
    _SalesMetric.refundRate => _salesRefundRate(point),
  };
}

double? _salesRefundRate(Map<String, dynamic> point) {
  final orders = _salesNumber(point['pedidos']);
  final refunds = _salesNumber(point['pedidos_reembolsados']);
  if (orders == null || refunds == null) return null;
  return orders > 0 ? refunds / orders : 0;
}

String _salesIsoDate(DateTime date) => date.toIso8601String().substring(0, 10);

List<Map<String, dynamic>> _sumDailySales(
  List<Map<String, dynamic>> points,
  _SalesGranularity granularity,
) {
  final result = <String, Map<String, dynamic>>{};
  for (final point in points) {
    final date = DateTime.tryParse(textOf(point['clave']));
    if (date == null) continue;
    final key = granularity == _SalesGranularity.month
        ? _salesMonthKey(date)
        : _salesIsoDate(date.subtract(Duration(days: date.weekday - 1)));
    final sum = result.putIfAbsent(key, () => {'clave': key});
    for (final field in [
      'pedidos',
      'pedidos_reembolsados',
      'unidades',
      'ventas_centavos',
      'comision_estimada_centavos',
      'comision_liquidada_centavos',
    ]) {
      final value = _salesNumber(point[field]);
      if (sum.containsKey(field)) {
        final previous = _salesNumber(sum[field]);
        sum[field] = value == null || previous == null
            ? null
            : previous + value;
      } else {
        sum[field] = value;
      }
    }
  }
  return result.values.toList()..sort(
    (left, right) => textOf(left['clave']).compareTo(textOf(right['clave'])),
  );
}

String _salesPointDate(
  Map<String, dynamic> point,
  _SalesGranularity granularity,
  String rangeStart, {
  bool long = false,
}) {
  final key = textOf(point['clave']);
  if (granularity == _SalesGranularity.month) {
    return long
        ? _salesDate(key, monthOnly: true)
        : _salesDate(key, monthOnly: true).split(' ').first;
  }
  if (granularity != _SalesGranularity.week) return _salesDate(key);
  final start = rangeStart.compareTo(key) > 0 ? rangeStart : key;
  final end = DateTime.tryParse(key)?.add(const Duration(days: 6));
  return long && end != null
      ? '${_salesDate(start)} – ${_salesDate(_salesIsoDate(end))}'
      : _salesDate(start);
}

class _SalesBreakdown extends StatefulWidget {
  const _SalesBreakdown({
    required this.from,
    required this.to,
    required this.today,
    required this.dashboard,
    super.key,
  });

  final String from, to;
  final DateTime today;
  final Map<String, dynamic> dashboard;

  @override
  State<_SalesBreakdown> createState() => _SalesBreakdownState();
}

class _SalesBreakdownState extends State<_SalesBreakdown> {
  _SalesMetric _metric = _SalesMetric.commission;
  _SalesGranularity? _manualGranularity;
  bool _table = false;

  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, limits) {
      final from = DateTime.parse(widget.from);
      final to = DateTime.parse(widget.to);
      final days = to.difference(from).inDays + 1;
      final permitted = [
        if (days <= 92) _SalesGranularity.day,
        if (days >= 14 && days <= 400) _SalesGranularity.week,
        if (days >= 45) _SalesGranularity.month,
      ];
      final source = mapOf(widget.dashboard['serie']);
      final sourceGranularity = _SalesGranularity.values.firstWhere(
        (value) => value.key == source['granularidad'],
        orElse: () => _SalesGranularity.day,
      );
      final automatic =
          limits.maxWidth < 580 &&
              days > 12 &&
              sourceGranularity == _SalesGranularity.day &&
              permitted.contains(_SalesGranularity.week)
          ? _SalesGranularity.week
          : sourceGranularity;
      final granularity =
          _manualGranularity ??
          (permitted.contains(automatic) ? automatic : permitted.first);
      final points = rowsOf(source['puntos']);

      Widget chart(
        List<Map<String, dynamic>> series,
        _SalesGranularity grouping,
      ) => _SalesChart(
        metric: _metric,
        grouping: grouping,
        points: series,
        rangeStart: widget.from,
        today: widget.today,
        table: _table,
        onToggleTable: () => setState(() => _table = !_table),
      );

      final chartPanel = _SalesPanel(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            _SalesChoices<_SalesMetric>(
              label: 'Métrica',
              values: _SalesMetric.values,
              selected: _metric,
              name: (value) => value.title,
              onSelect: (value) => setState(() => _metric = value),
            ),
            const SizedBox(height: 8),
            if (permitted.length > 1) ...[
              _SalesChoices<_SalesGranularity>(
                label: 'Agrupar por',
                values: permitted,
                selected: granularity,
                name: (value) => value.title,
                onSelect: (value) => setState(() => _manualGranularity = value),
              ),
              const SizedBox(height: 14),
            ],
            if (granularity == sourceGranularity)
              chart(points, granularity)
            else if (sourceGranularity == _SalesGranularity.day)
              chart(_sumDailySales(points, granularity), granularity)
            else
              ApiData(
                path: '/api/analitica/serie',
                query: {
                  'desde': widget.from,
                  'hasta': widget.to,
                  'granularidad': granularity.key,
                },
                builder: (context, data) =>
                    chart(rowsOf(data['puntos']), granularity),
                errorBuilder: (context, _) => Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    const InlineNotice(
                      text:
                          'Esta agrupación no está disponible. Se muestra la serie del tablero.',
                    ),
                    const SizedBox(height: 12),
                    chart(points, sourceGranularity),
                  ],
                ),
              ),
          ],
        ),
      );

      final rangeQuery = {'desde': widget.from, 'hasta': widget.to};
      return Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const SizedBox(height: 16),
          chartPanel,
          const SizedBox(height: 16),
          _SalesPanelPair(
            first: _SalesMoneyBreakdown(mapOf(widget.dashboard['kpis'])),
            second: _SalesPanel(
              child: ApiData(
                path: '/api/tiendas',
                query: {...rangeQuery, 'orden': 'comision'},
                builder: (context, data) => _SalesShopBreakdown(
                  rowsOf(data['items']),
                  mapOf(widget.dashboard['kpis']),
                ),
                errorBuilder: (context, _) {
                  final available = rowsOf(widget.dashboard['top_tiendas']);
                  return available.isEmpty
                      ? const _SalesUnavailable('De quién depende tu comisión')
                      : _SalesShopBreakdown(
                          available,
                          mapOf(widget.dashboard['kpis']),
                        );
                },
              ),
            ),
          ),
          const SizedBox(height: 16),
          if (sourceGranularity == _SalesGranularity.month)
            _SalesInformation(
              months: points,
              rangeQuery: rangeQuery,
              dashboard: widget.dashboard,
            )
          else if (sourceGranularity == _SalesGranularity.day)
            _SalesInformation(
              months: _sumDailySales(points, _SalesGranularity.month),
              rangeQuery: rangeQuery,
              dashboard: widget.dashboard,
            )
          else
            ApiData(
              path: '/api/analitica/serie',
              query: {...rangeQuery, 'granularidad': 'mes'},
              builder: (context, data) => _SalesInformation(
                months: rowsOf(data['puntos']),
                rangeQuery: rangeQuery,
                dashboard: widget.dashboard,
              ),
              errorBuilder: (context, _) => _SalesInformation(
                months: null,
                rangeQuery: rangeQuery,
                dashboard: widget.dashboard,
              ),
            ),
        ],
      );
    },
  );
}

class _SalesChoices<T> extends StatelessWidget {
  const _SalesChoices({
    required this.label,
    required this.values,
    required this.selected,
    required this.name,
    required this.onSelect,
  });

  final String label;
  final List<T> values;
  final T selected;
  final String Function(T) name;
  final ValueChanged<T> onSelect;

  @override
  Widget build(BuildContext context) => Semantics(
    container: true,
    label: label,
    child: Wrap(
      spacing: 7,
      runSpacing: 5,
      children: [
        for (final value in values)
          ChoiceChip(
            label: Text(name(value)),
            selected: selected == value,
            onSelected: (_) => onSelect(value),
          ),
      ],
    ),
  );
}

class _SalesChart extends StatelessWidget {
  const _SalesChart({
    required this.metric,
    required this.grouping,
    required this.points,
    required this.rangeStart,
    required this.today,
    required this.table,
    required this.onToggleTable,
  });

  final _SalesMetric metric;
  final _SalesGranularity grouping;
  final List<Map<String, dynamic>> points;
  final String rangeStart;
  final DateTime today;
  final bool table;
  final VoidCallback onToggleTable;

  bool _inProgress(Map<String, dynamic> point) {
    final key = textOf(point['clave']);
    return switch (grouping) {
      _SalesGranularity.day => key == _salesIsoDate(today),
      _SalesGranularity.week => _weekInProgress(key),
      _SalesGranularity.month =>
        key == _salesMonthKey(today) &&
            _salesMonthKey(today.add(const Duration(days: 1))) == key,
    };
  }

  bool _weekInProgress(String key) {
    final start = DateTime.tryParse(key);
    if (start == null) return false;
    final currentDay = _salesIsoDate(today);
    return key.compareTo(currentDay) <= 0 &&
        _salesIsoDate(
              start.add(const Duration(days: 6)),
            ).compareTo(currentDay) >
            0;
  }

  String _pointTitle(Map<String, dynamic> point) {
    final title = _salesPointDate(point, grouping, rangeStart, long: true);
    return _inProgress(point) ? '$title (en curso)' : title;
  }

  num? _unsettled(Map<String, dynamic> point) {
    final settled = _salesNumber(point['comision_liquidada_centavos']);
    final estimate = _salesNumber(point['comision_estimada_centavos']);
    if (settled == null || estimate == null) return null;
    return (estimate - settled).clamp(0, double.infinity);
  }

  @override
  Widget build(BuildContext context) {
    final labels = switch (metric) {
      _SalesMetric.commission => [
        'Periodo',
        'Liquidada',
        'Por liquidar',
        'Comisión estimada',
        'Pedidos',
        'Reembolsados',
      ],
      _SalesMetric.refundRate => [
        'Periodo',
        'Tasa de reembolso',
        'Reembolsados',
        'Pedidos',
      ],
      _ => ['Periodo', metric.title],
    };
    final title = '${metric.title} por ${grouping.singular}';
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _SalesPanelHeading(
          title,
          action: TextButton.icon(
            onPressed: onToggleTable,
            icon: Icon(
              table ? Icons.bar_chart_rounded : Icons.table_rows_outlined,
              size: 18,
            ),
            label: Text(table ? 'Ver como gráfica' : 'Ver como tabla'),
          ),
        ),
        if (points.isEmpty ||
            points.every((point) => metric.value(point) == null))
          const Padding(
            padding: EdgeInsets.symmetric(vertical: 24),
            child: Text('No hay datos para esta gráfica.'),
          )
        else if (table)
          _SalesTable(
            columns: labels,
            rows: [
              for (final point in points)
                [
                  _pointTitle(point),
                  if (metric == _SalesMetric.commission) ...[
                    _salesMoney(point['comision_liquidada_centavos']),
                    _salesMoney(_unsettled(point)),
                  ],
                  _formatSalesValue(metric.value(point), metric.kind),
                  if (metric == _SalesMetric.commission) ...[
                    _salesInteger(point['pedidos']),
                    _salesInteger(point['pedidos_reembolsados']),
                  ],
                  if (metric == _SalesMetric.refundRate) ...[
                    _salesInteger(point['pedidos_reembolsados']),
                    _salesInteger(point['pedidos']),
                  ],
                ],
            ],
          )
        else ...[
          if (metric == _SalesMetric.commission)
            Wrap(
              spacing: 14,
              runSpacing: 6,
              children: [
                _SalesLegend('Liquidada', context.corte.action),
                _SalesLegend(
                  'Por liquidar',
                  context.corte.action.withValues(alpha: .38),
                ),
              ],
            ),
          const SizedBox(height: 12),
          _SalesBars(
            points: [
              for (final point in points)
                (
                  title: _pointTitle(point),
                  label: _salesPointDate(point, grouping, rangeStart),
                  value: metric.value(point),
                  settled: metric == _SalesMetric.commission
                      ? _salesNumber(point['comision_liquidada_centavos'])
                      : null,
                  inProgress: _inProgress(point),
                ),
            ],
            kind: metric.kind,
          ),
        ],
      ],
    );
  }
}

typedef _SalesBar = ({
  String title,
  String label,
  num? value,
  num? settled,
  bool inProgress,
});

class _SalesBars extends StatelessWidget {
  const _SalesBars({required this.points, required this.kind});

  final List<_SalesBar> points;
  final _SalesValue kind;

  @override
  Widget build(BuildContext context) {
    final colors = context.corte;
    final theme = Theme.of(context).textTheme;
    final primary = kind == _SalesValue.currency
        ? colors.action
        : colors.cyanInk;
    final peak = points.fold<num>(0, (largest, point) {
      final total = point.value ?? 0;
      final settled = point.settled ?? 0;
      final value = total >= settled ? total : settled;
      return value > largest ? value : largest;
    });
    const height = 132.0;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Align(
          alignment: Alignment.centerLeft,
          child: Text(_formatSalesValue(peak, kind), style: theme.bodySmall),
        ),
        const SizedBox(height: 3),
        LayoutBuilder(
          builder: (context, limits) {
            final visibleCount = points.length < 12 ? points.length : 12;
            final barWidth = (limits.maxWidth / visibleCount).clamp(
              42.0,
              140.0,
            );
            return SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              child: SizedBox(
                width: barWidth * points.length,
                child: Stack(
                  children: [
                    for (final y in [0.0, height / 3, height / 3 * 2, height])
                      Positioned(
                        top: y,
                        left: 0,
                        right: 0,
                        child: ColoredBox(
                          color: colors.line,
                          child: const SizedBox(height: 1),
                        ),
                      ),
                    Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        for (final point in points)
                          SizedBox(
                            width: barWidth,
                            child: Tooltip(
                              message:
                                  '${point.title}: ${_formatSalesValue(point.value, kind)}',
                              child: Semantics(
                                label:
                                    '${point.title}: ${_formatSalesValue(point.value, kind)}',
                                excludeSemantics: true,
                                child: Column(
                                  children: [
                                    SizedBox(
                                      height: height,
                                      child: Align(
                                        alignment: Alignment.bottomCenter,
                                        child: ClipRRect(
                                          borderRadius:
                                              const BorderRadius.vertical(
                                                top: Radius.circular(3),
                                              ),
                                          child: SizedBox(
                                            width: (barWidth * .55).clamp(
                                              17.0,
                                              42.0,
                                            ),
                                            child: Column(
                                              mainAxisSize: MainAxisSize.min,
                                              children: [
                                                if (point.value != null &&
                                                    peak > 0)
                                                  for (final segment
                                                      in _segments(
                                                        point,
                                                        primary,
                                                      ))
                                                    SizedBox(
                                                      height:
                                                          (segment.$1 /
                                                                  peak *
                                                                  height)
                                                              .clamp(
                                                                0.0,
                                                                height,
                                                              )
                                                              .toDouble(),
                                                      width: double.infinity,
                                                      child: ColoredBox(
                                                        color: point.inProgress
                                                            ? segment.$2
                                                                  .withValues(
                                                                    alpha: .55,
                                                                  )
                                                            : segment.$2,
                                                      ),
                                                    ),
                                              ],
                                            ),
                                          ),
                                        ),
                                      ),
                                    ),
                                    const SizedBox(height: 6),
                                    Text(
                                      point.label,
                                      maxLines: 2,
                                      overflow: TextOverflow.ellipsis,
                                      textAlign: TextAlign.center,
                                      style: theme.bodySmall,
                                    ),
                                  ],
                                ),
                              ),
                            ),
                          ),
                      ],
                    ),
                  ],
                ),
              ),
            );
          },
        ),
      ],
    );
  }

  List<(num, Color)> _segments(_SalesBar point, Color color) {
    final value = point.value ?? 0;
    final settled = point.settled;
    if (settled == null) return [(value, color)];
    return [
      (
        (value - settled).clamp(0, double.infinity),
        color.withValues(alpha: .38),
      ),
      (settled, color),
    ];
  }
}

class _SalesLegend extends StatelessWidget {
  const _SalesLegend(this.text, this.color);

  final String text;
  final Color color;

  @override
  Widget build(BuildContext context) => Row(
    mainAxisSize: MainAxisSize.min,
    children: [
      DecoratedBox(
        decoration: BoxDecoration(
          color: color,
          borderRadius: BorderRadius.circular(3),
        ),
        child: const SizedBox.square(dimension: 10),
      ),
      const SizedBox(width: 6),
      Flexible(child: Text(text, style: Theme.of(context).textTheme.bodySmall)),
    ],
  );
}

class _SalesPanelHeading extends StatelessWidget {
  const _SalesPanelHeading(this.title, {this.action});

  final String title;
  final Widget? action;

  @override
  Widget build(BuildContext context) {
    final heading = Semantics(
      header: true,
      child: Text(title, style: Theme.of(context).textTheme.titleMedium),
    );
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: action == null
          ? heading
          : Wrap(
              alignment: WrapAlignment.spaceBetween,
              crossAxisAlignment: WrapCrossAlignment.center,
              spacing: 10,
              children: [heading, action!],
            ),
    );
  }
}

class _SalesPanelPair extends StatelessWidget {
  const _SalesPanelPair({required this.first, required this.second});

  final Widget first, second;

  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, limits) {
      final textScale = MediaQuery.textScalerOf(context).scale(14) / 14;
      return limits.maxWidth >= 700 * textScale
          ? Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(child: first),
                const SizedBox(width: 16),
                Expanded(child: second),
              ],
            )
          : Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [first, const SizedBox(height: 16), second],
            );
    },
  );
}

class _SalesTable extends StatelessWidget {
  const _SalesTable({required this.columns, required this.rows});

  final List<String> columns;
  final List<List<String>> rows;

  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, limits) => SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: ConstrainedBox(
        constraints: BoxConstraints(minWidth: limits.maxWidth),
        child: DataTable(
          horizontalMargin: 9,
          columnSpacing: 18,
          dataRowMinHeight: 42,
          dataRowMaxHeight: double.infinity,
          columns: [
            for (var i = 0; i < columns.length; i++)
              DataColumn(label: Text(columns[i]), numeric: i > 0),
          ],
          rows: [
            for (final row in rows)
              DataRow(cells: [for (final cell in row) DataCell(Text(cell))]),
          ],
        ),
      ),
    ),
  );
}

class _SalesUnavailable extends StatelessWidget {
  const _SalesUnavailable(this.title);

  final String title;

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      _SalesPanelHeading(title),
      const InlineNotice(text: 'Conéctate para cargar esta sección.'),
      Align(
        alignment: Alignment.centerLeft,
        child: TextButton(
          onPressed: CorteScope.of(context).refresh,
          child: const Text('Reintentar'),
        ),
      ),
    ],
  );
}

typedef _SalesPart = ({String label, double amount, Color color});

class _SalesShareBar extends StatelessWidget {
  const _SalesShareBar(this.parts);

  final List<_SalesPart> parts;

  @override
  Widget build(BuildContext context) {
    final total = parts.fold<double>(
      0,
      (sum, part) => sum + (part.amount > 0 ? part.amount : 0),
    );
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (total > 0)
          LayoutBuilder(
            builder: (context, limits) => Semantics(
              excludeSemantics: true,
              child: ClipRRect(
                borderRadius: BorderRadius.circular(4),
                child: Row(
                  children: [
                    for (final part in parts)
                      if (part.amount > 0)
                        SizedBox(
                          width: limits.maxWidth * (part.amount / total),
                          height: 14,
                          child: ColoredBox(color: part.color),
                        ),
                  ],
                ),
              ),
            ),
          ),
        const SizedBox(height: 10),
        for (final part in parts)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 3),
            child: Row(
              children: [
                Expanded(child: _SalesLegend(part.label, part.color)),
                const SizedBox(width: 10),
                Flexible(
                  child: Text(
                    total > 0
                        ? '${_salesMoney(part.amount)} · ${_salesPercent(part.amount / total, digits: 0)}'
                        : _salesMoney(part.amount),
                    textAlign: TextAlign.end,
                    style: const TextStyle(fontWeight: FontWeight.w600),
                  ),
                ),
              ],
            ),
          ),
      ],
    );
  }
}

class _SalesMoneyBreakdown extends StatelessWidget {
  const _SalesMoneyBreakdown(this.kpis);

  final Map<String, dynamic> kpis;

  @override
  Widget build(BuildContext context) {
    final colors = context.corte;
    final parts = <_SalesPart>[
      for (final (label, key, color) in [
        ('Liquidada', 'comision_liquidada_centavos', colors.action),
        (
          'Por liquidar',
          'comision_por_liquidar_centavos',
          colors.action.withValues(alpha: .38),
        ),
        ('Congelada', 'comision_retenida_centavos', colors.muted),
        (
          'Perdida por reembolsos',
          'comision_perdida_reembolsos_centavos',
          colors.warning,
        ),
      ])
        if (_salesNumber(kpis[key]) case final amount?)
          if (key != 'comision_retenida_centavos' || amount > 0)
            (label: label, amount: amount, color: color),
    ];
    final settled = _salesNumber(kpis['comision_liquidada_centavos']);
    final unsettled = _salesNumber(kpis['comision_por_liquidar_centavos']);
    final onHold = _salesNumber(kpis['comision_retenida_centavos']);
    final estimated = settled == null || unsettled == null || onHold == null
        ? null
        : settled + unsettled + onHold;
    return _SalesPanel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const _SalesPanelHeading('¿Dónde está tu dinero?'),
          if (parts.isEmpty)
            const Text('El tablero no tiene desglose para este periodo.')
          else ...[
            _SalesShareBar(parts),
            const SizedBox(height: 8),
            Text(
              'Tu corte: ${_salesMoney(estimated)} de comisión estimada',
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ],
        ],
      ),
    );
  }
}

class _SalesShopBreakdown extends StatelessWidget {
  const _SalesShopBreakdown(this.shops, this.kpis);

  final List<Map<String, dynamic>> shops;
  final Map<String, dynamic> kpis;

  @override
  Widget build(BuildContext context) {
    final colors = context.corte;
    final palette = [
      colors.action,
      colors.cyanInk,
      colors.warning,
      colors.success,
      colors.danger,
    ];
    double amountOf(Map<String, dynamic> shop) =>
        _salesNumber(mapOf(shop['ventas'])['comision_estimada_centavos']) ?? 0;
    final ordered = shops.where((shop) => amountOf(shop) > 0).toList()
      ..sort((a, b) => amountOf(b).compareTo(amountOf(a)));
    final top = ordered.take(5).toList();
    final sum = top.fold<double>(0, (acc, shop) => acc + amountOf(shop));
    final other = (_salesNumber(kpis['comision_total_centavos']) ?? sum) - sum;
    final parts = <_SalesPart>[
      for (var i = 0; i < top.length; i++)
        (
          label: textOf(top[i]['nombre'], 'Tienda'),
          amount: amountOf(top[i]),
          color: palette[i],
        ),
      if (other > 0 && top.isNotEmpty)
        (label: 'Otras', amount: other, color: colors.muted),
    ];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const _SalesPanelHeading('De quién depende tu comisión'),
        if (parts.isEmpty)
          const Text('Sin comisión por tienda en este periodo.')
        else ...[
          _SalesShareBar(parts),
          const SizedBox(height: 8),
          Text(
            '${parts.first.label} genera el ${_salesPercent(parts.first.amount / (other > 0 ? sum + other : sum), digits: 0)} de tu comisión.',
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ],
      ],
    );
  }
}

class _SalesInformation extends StatelessWidget {
  const _SalesInformation({
    required this.months,
    required this.rangeQuery,
    required this.dashboard,
  });

  final List<Map<String, dynamic>>? months;
  final Map<String, String> rangeQuery;
  final Map<String, dynamic> dashboard;

  @override
  Widget build(BuildContext context) {
    final ui = CorteScope.of(context);
    final kpis = mapOf(dashboard['kpis']);
    final period = textOf(mapOf(dashboard['periodo'])['clave'], '30d');
    final periodQuery = Uri(path: '/productos', queryParameters: rangeQuery);
    final monthRows = months;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _SalesPanelPair(
          first: _SalesPanel(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const _SalesPanelHeading('Reembolsos'),
                Text(
                  '${_salesMoney(kpis['comision_perdida_reembolsos_centavos'])} de comisión perdida por reembolsos.',
                ),
                const SizedBox(height: 5),
                Text(
                  '${_salesInteger(kpis['pedidos_reembolsados'])} de ${_salesInteger(kpis['pedidos'])} pedidos (${_salesPercent(_salesNumber(kpis['tasa_reembolso']))})',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
                if (monthRows != null && monthRows.isNotEmpty) ...[
                  const SizedBox(height: 14),
                  const Text('Tasa de reembolso por mes'),
                  const SizedBox(height: 6),
                  _SalesBars(
                    points: [
                      for (final point in monthRows)
                        (
                          title: _salesDate(
                            textOf(point['clave']),
                            monthOnly: true,
                          ),
                          label: _salesDate(
                            textOf(point['clave']),
                            monthOnly: true,
                          ).split(' ').first,
                          value: _salesRefundRate(point),
                          settled: null,
                          inProgress: false,
                        ),
                    ],
                    kind: _SalesValue.rate,
                  ),
                ],
              ],
            ),
          ),
          second: _SalesPanel(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                _SalesPanelHeading(
                  'Productos que más venden',
                  action: TextButton(
                    onPressed: () => ui.go(periodQuery.toString()),
                    child: const Text('Ver productos'),
                  ),
                ),
                ApiData(
                  path: '/api/analitica/productos',
                  query: rangeQuery,
                  builder: (context, data) =>
                      _SalesTopProducts(rowsOf(data['items'])),
                  errorBuilder: (context, _) {
                    final available = rowsOf(dashboard['top_productos']);
                    return available.isEmpty
                        ? const InlineNotice(
                            text: 'Conéctate para actualizar los productos.',
                          )
                        : _SalesTopProducts(available);
                  },
                ),
              ],
            ),
          ),
        ),
        const SizedBox(height: 16),
        _SalesPanel(
          child: monthRows == null
              ? const _SalesUnavailable('Por mes')
              : Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    const _SalesPanelHeading('Por mes'),
                    if (monthRows.isEmpty)
                      const Text('No hay movimientos por mes en este periodo.')
                    else
                      _SalesTable(
                        columns: const [
                          'Mes',
                          'Pedidos',
                          'Reembolsados',
                          'Tasa',
                          'Comisión estimada',
                          'Liquidada',
                        ],
                        rows: [
                          for (final month in monthRows.reversed)
                            [
                              _salesDate(
                                textOf(month['clave']),
                                monthOnly: true,
                              ),
                              _salesInteger(month['pedidos']),
                              _salesInteger(month['pedidos_reembolsados']),
                              _salesPercent(_salesRefundRate(month)),
                              _salesMoney(month['comision_estimada_centavos']),
                              _salesMoney(month['comision_liquidada_centavos']),
                            ],
                        ],
                      ),
                  ],
                ),
        ),
        if (rowsOf(dashboard['top_videos']).isNotEmpty) ...[
          const SizedBox(height: 16),
          _SalesPanel(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: ExpansionTile(
              tilePadding: EdgeInsets.zero,
              title: const Text('Videos con mayor comisión'),
              children: [
                for (final video in rowsOf(dashboard['top_videos']).take(5))
                  VideoRow(video: video),
                TextButton(
                  onPressed: () => ui.go('/videos?periodo=$period'),
                  child: const Text('Ver videos'),
                ),
              ],
            ),
          ),
        ],
      ],
    );
  }
}

class _SalesTopProducts extends StatelessWidget {
  const _SalesTopProducts(this.products);

  final List<Map<String, dynamic>> products;

  @override
  Widget build(BuildContext context) {
    final ordered =
        products.where((p) => (_salesNumber(p['unidades']) ?? 0) > 0).toList()
          ..sort((a, b) {
            final units = intOf(b['unidades']).compareTo(intOf(a['unidades']));
            return units != 0
                ? units
                : intOf(
                    b['comision_estimada_centavos'],
                  ).compareTo(intOf(a['comision_estimada_centavos']));
          });
    if (ordered.isEmpty) {
      return const Text('Ningún producto vendió en este periodo.');
    }
    return Column(
      children: [
        for (final product in ordered.take(5))
          ListTile(
            contentPadding: EdgeInsets.zero,
            leading: CortePhoto(
              textOf(product['imagen']),
              width: 44,
              height: 48,
            ),
            title: Text(productName(product)),
            subtitle: Text(
              [
                if (textOf(product['tienda_nombre']).isNotEmpty)
                  textOf(product['tienda_nombre']),
                '${_salesInteger(product['unidades'])} unidades',
                '${_salesMoney(product['comision_estimada_centavos'])} de comisión',
              ].join(' · '),
            ),
            onTap: textOf(product['product_id']).isEmpty
                ? null
                : () => CorteScope.of(context).go(
                    '/productos/${Uri.encodeComponent(textOf(product['product_id']))}',
                  ),
          ),
      ],
    );
  }
}

const _salesOrderFilters = [
  ('todos', 'Todos', <String>[]),
  ('liquidados', 'Liquidados', ['SETTLED']),
  ('por_liquidar', 'Por liquidar', ['AWAITING PAYMENT', 'To-SETTLE']),
  ('reembolsados', 'Reembolsados', ['REFUNDED']),
];

class _SalesOrders extends StatefulWidget {
  const _SalesOrders({required this.from, required this.to, super.key});

  final String? from, to;

  @override
  State<_SalesOrders> createState() => _SalesOrdersState();
}

class _SalesOrdersState extends State<_SalesOrders> {
  static const _pageSize = 50;
  int _page = 1;
  String? _lastSelected;

  @override
  Widget build(BuildContext context) {
    final ui = CorteScope.of(context);
    final params =
        Uri.tryParse(ui.location)?.queryParameters ?? const <String, String>{};
    final filter = _salesOrderFilters.firstWhere(
      (value) => value.$1 == params['estado'],
      orElse: () => _salesOrderFilters.first,
    );
    if (_lastSelected != filter.$1) {
      _lastSelected = filter.$1;
      _page = 1;
    }
    return Padding(
      padding: const EdgeInsets.only(top: 16),
      child: _SalesPanel(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            _SalesPanelHeading(
              'Pedidos',
              action: TextButton(
                onPressed: () => ui.go('/ordenes'),
                child: const Text('Ver todos los pedidos'),
              ),
            ),
            _SalesChoices<String>(
              label: 'Filtrar pedidos por estado',
              values: _salesOrderFilters.map((value) => value.$1).toList(),
              selected: filter.$1,
              name: (value) =>
                  _salesOrderFilters.firstWhere((item) => item.$1 == value).$2,
              onSelect: (value) {
                if (value == filter.$1) return;
                final next = {...params}..remove('pedido');
                if (value == 'todos') {
                  next.remove('estado');
                } else {
                  next['estado'] = value;
                }
                ui.replace(
                  Uri(path: '/ventas', queryParameters: next).toString(),
                );
              },
            ),
            const SizedBox(height: 12),
            ApiData(
              path: '/api/ordenes',
              query: {
                'desde': widget.from,
                'hasta': widget.to,
                'estado': filter.$3,
                'pagina': _page,
                'por_pagina': _pageSize,
              },
              builder: (context, data) {
                final orders = rowsOf(data['items']).where((order) {
                  final date = textOf(order['fecha']);
                  return (filter.$3.isEmpty ||
                          filter.$3.contains(order['estado'])) &&
                      (widget.from == null ||
                          date.compareTo(widget.from!) >= 0) &&
                      (widget.to == null || date.compareTo(widget.to!) <= 0);
                }).toList();
                final total = intOf(data['total']);
                final pages = (total / _pageSize).ceil().clamp(1, 1000000);
                return Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    if (orders.isEmpty)
                      const Padding(
                        padding: EdgeInsets.symmetric(vertical: 16),
                        child: Text(
                          'No hay pedidos con este filtro. Prueba con otro estado o periodo.',
                        ),
                      ),
                    for (final order in orders)
                      _OrderTile(
                        key: ValueKey(textOf(order['order_id'])),
                        order: order,
                        embedded: true,
                        initiallyExpanded:
                            params['pedido'] == order['order_id'],
                      ),
                    if (total > 0) ...[
                      const SizedBox(height: 12),
                      Wrap(
                        alignment: WrapAlignment.spaceBetween,
                        crossAxisAlignment: WrapCrossAlignment.center,
                        spacing: 8,
                        runSpacing: 6,
                        children: [
                          Text(
                            'Página $_page de $pages · ${integer(total)} pedidos',
                          ),
                          Wrap(
                            spacing: 8,
                            runSpacing: 4,
                            children: [
                              OutlinedButton.icon(
                                onPressed: _page > 1
                                    ? () => setState(() => _page--)
                                    : null,
                                icon: const Icon(
                                  Icons.chevron_left_rounded,
                                  size: 18,
                                ),
                                label: const Text('Anterior'),
                              ),
                              OutlinedButton.icon(
                                onPressed: _page < pages
                                    ? () => setState(() => _page++)
                                    : null,
                                icon: const Icon(
                                  Icons.chevron_right_rounded,
                                  size: 18,
                                ),
                                label: const Text('Siguiente'),
                              ),
                            ],
                          ),
                        ],
                      ),
                    ],
                  ],
                );
              },
              errorBuilder: (context, _) =>
                  const _SalesUnavailable('Pedidos del periodo'),
            ),
          ],
        ),
      ),
    );
  }
}
