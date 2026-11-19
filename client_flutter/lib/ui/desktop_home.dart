import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../app.dart';
import '../domain/domain.dart';
import 'corte_icons.dart';
import 'format.dart';
import 'home_sales.dart';
import 'home_tiktok.dart';
import 'theme.dart';
import 'widgets.dart';
import 'work.dart' show productName, samplePending;

const _sectionStyle = TextStyle(
  fontSize: 21,
  height: 1.35,
  fontWeight: FontWeight.w700,
  fontVariations: [FontVariation('wght', 720)],
  letterSpacing: -.4,
);

const _amountStyle = TextStyle(
  fontWeight: FontWeight.w700,
  fontVariations: [FontVariation('wght', 720)],
  fontFeatures: [FontFeature.tabularFigures()],
  height: 1.2,
  letterSpacing: -.9,
);

double _panelPadding(BuildContext context) =>
    switch (MediaQuery.sizeOf(context).width) {
      <= 599 => 16,
      <= 1100 => 18,
      _ => 22,
    };
typedef _HomeScope = (CorteUiController, String?, String?);

/// The hierarchy of the web home, backed by the native scoped repository.
class DesktopHomePage extends StatefulWidget {
  const DesktopHomePage({super.key});

  @override
  State<DesktopHomePage> createState() => _HomeState();
}

class _HomeState extends State<DesktopHomePage> {
  _HomeScope? _scope;
  int? _revision;
  late Future<SesionDto> _session;
  late Future<DashboardDto> _dashboard;
  late Future<MuestrasDto> _samples;
  bool _updating = false;
  String? _notice;

  _HomeScope _scopeFor(CorteUiController ui) =>
      (ui, ui.repo.ownerScope, ui.repo.cacheScope);

  void _load(CorteUiController ui) {
    final scope = _scopeFor(ui);
    if (_scope != scope) {
      _scope = scope;
      _revision = null;
      _updating = false;
      _notice = null;
    }
    if (_revision == ui.revision) return;
    _revision = ui.revision;
    _session = ui.repo.sesion();
    _dashboard = ui.repo.dashboard();
    _samples = ui.repo.muestras();
  }

  Future<void> _update(CorteUiController ui, SesionDto? session) async {
    if (_updating || session?.sync?.enCurso == true) return;
    final scope = _scopeFor(ui);
    setState(() {
      _updating = true;
      _notice = null;
    });
    try {
      if (session?.conectada == true &&
          session?.capacidades?['sincronizar'] == true) {
        await ui.synchronize();
      } else {
        ui.refresh();
      }
      if (!mounted || scope != _scopeFor(ui)) return;
      _load(ui);
      await Future.wait<Object>([_session, _dashboard, _samples]);
      if (!mounted || scope != _scopeFor(ui)) return;
      setState(() {
        _notice = session?.conectada == true
            ? 'Actualización solicitada. Tus datos aparecerán al terminar la sincronización.'
            : 'Actualización solicitada.';
      });
    } catch (_) {
      if (mounted && scope == _scopeFor(ui)) {
        setState(() {
          _notice =
              'No pudimos actualizar. Revisa tu conexión e inténtalo de nuevo.';
        });
      }
    } finally {
      if (mounted && scope == _scopeFor(ui)) {
        setState(() => _updating = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final ui = CorteScope.of(context);
    _load(ui);
    // The session request is not cached. An offline failure here must not
    // prevent cached sample work or results from rendering.
    return FutureBuilder<SesionDto>(
      key: ValueKey(_scope),
      future: _session,
      builder: (context, session) => FutureBuilder<DashboardDto>(
        future: _dashboard,
        builder: (context, dashboard) => FutureBuilder<MuestrasDto>(
          future: _samples,
          builder: (context, samples) =>
              _body(context, ui, session, dashboard, samples),
        ),
      ),
    );
  }

  Widget _body(
    BuildContext context,
    CorteUiController ui,
    AsyncSnapshot<SesionDto> session,
    AsyncSnapshot<DashboardDto> dashboard,
    AsyncSnapshot<MuestrasDto> samples,
  ) {
    final viewport = MediaQuery.sizeOf(context).width;
    final compact = viewport < 600;
    final gap = compact ? 24.0 : 28.0;
    final updating = _updating || session.data?.sync?.enCurso == true;
    final sessionData = session.data?.datos;
    final showKpis =
        sessionData == null ||
        sessionData['hay_datos'] == true ||
        sessionData['ultima_sync_ok_at'] != null;
    return RefreshIndicator(
      onRefresh: () => _update(ui, session.data),
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: EdgeInsets.fromLTRB(
          compact ? 16 : 32,
          compact ? 40 : 30,
          compact ? 16 : 32,
          48,
        ),
        children: [
          Padding(
            padding: EdgeInsets.fromLTRB(
              viewport > 1100 ? 16 : 0,
              0,
              viewport > 1100 ? 16 : 0,
              4,
            ),
            child: _HomeHeader(
              updating: updating,
              onRefresh: () => _update(ui, session.data),
            ),
          ),
          if (_notice case final notice?) ...[
            const SizedBox(height: 12),
            Semantics(
              liveRegion: true,
              child: Text(
                notice,
                style: TextStyle(fontSize: 13, color: context.corte.muted),
              ),
            ),
          ],
          if (session.data?.conexion != null &&
              session.data?.conectada == false) ...[
            const SizedBox(height: 24),
            const _ConnectShop(),
          ] else if (session.hasError) ...[
            const SizedBox(height: 24),
            const InlineNotice(
              text:
                  'No pudimos cargar tu cuenta. Usa Actualizar para volver a intentarlo.',
              error: true,
            ),
          ],
          SizedBox(height: gap),
          _HomeResults(dashboard: dashboard, showKpis: showKpis),
          SizedBox(height: gap),
          LayoutBuilder(
            builder: (context, limits) {
              final scale = MediaQuery.textScalerOf(context).scale(14) / 14;
              final priorities = _HomePriorities(
                samples: samples,
                retry: () => setState(() => _samples = ui.repo.muestras()),
              );
              const shortcuts = _HomeShortcuts();
              final compactPanels = viewport <= 1100;
              final panelGap = compactPanels ? 16.0 : 20.0;
              final usableWidth = limits.maxWidth - panelGap;
              final shortcutsWidth = math.max(
                math.max(compactPanels ? 275.0 : 300.0, 210 * scale),
                usableWidth / (compactPanels ? 2.4 : 2.65),
              );
              final prioritiesWidth = usableWidth - shortcutsWidth;
              if (viewport <= 850 || prioritiesWidth < 250 * scale) {
                return Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    priorities,
                    SizedBox(height: panelGap),
                    shortcuts,
                  ],
                );
              }
              return Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(child: priorities),
                  SizedBox(width: panelGap),
                  SizedBox(width: shortcutsWidth, child: shortcuts),
                ],
              );
            },
          ),
          if (dashboard.data case final data?) ...[
            const SizedBox(height: 32),
            _NativeResults(dashboard: data),
          ],
          const SizedBox(height: 26),
          Text(
            'CUTGC · Tu espacio para crear y crecer',
            style: TextStyle(fontSize: 13, color: context.corte.muted),
          ),
        ],
      ),
    );
  }
}

class _HomeHeader extends StatelessWidget {
  const _HomeHeader({required this.updating, required this.onRefresh});
  final bool updating;
  final VoidCallback onRefresh;

  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, limits) {
      final viewport = MediaQuery.sizeOf(context).width;
      final wide =
          viewport >= 600 &&
          limits.maxWidth >= 380 &&
          MediaQuery.textScalerOf(context).scale(14) <= 22;
      final heading = Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Semantics(
            header: true,
            child: Text(
              'Tu negocio, en orden',
              style: TextStyle(
                fontSize: (viewport * .028).clamp(30, 40).toDouble(),
                height: 1.2,
                fontWeight: FontWeight.w700,
                fontVariations: const [FontVariation('wght', 750)],
                letterSpacing: viewport < 600 ? -.9 : -1.1,
              ),
            ),
          ),
          const SizedBox(height: 7),
          Text(
            'Tus resultados y próximos pasos, en un solo lugar.',
            style: TextStyle(
              fontSize: viewport < 600 ? 15 : 17,
              height: 1.5,
              color: context.corte.muted,
            ),
          ),
        ],
      );
      final action = OutlinedButton(
        style: OutlinedButton.styleFrom(
          foregroundColor: context.corte.ink,
          backgroundColor: context.corte.soft,
          side: BorderSide(color: context.corte.line),
          minimumSize: Size(wide ? 120 : 105, 44),
        ),
        onPressed: updating ? null : onRefresh,
        child: Text(updating ? 'Actualizando…' : 'Actualizar'),
      );
      return wide
          ? Row(
              children: [
                Expanded(child: heading),
                const SizedBox(width: 24),
                action,
              ],
            )
          : Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [heading, const SizedBox(height: 14), action],
            );
    },
  );
}

class _ConnectShop extends StatelessWidget {
  const _ConnectShop();

  @override
  Widget build(BuildContext context) => _HomePanel(
    child: Padding(
      padding: const EdgeInsets.all(20),
      child: LayoutBuilder(
        builder: (context, limits) {
          final wide =
              limits.maxWidth >= 700 &&
              MediaQuery.textScalerOf(context).scale(14) <= 20;
          final details = Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Semantics(
                header: true,
                child: const Text(
                  'Conecta tu cuenta de TikTok Shop',
                  style: _sectionStyle,
                ),
              ),
              const SizedBox(height: 5),
              Text(
                'Consulta tus comisiones y organiza tus muestras.\nTus datos aparecerán después de la primera sincronización.',
                style: TextStyle(
                  fontSize: 15,
                  height: 1.5,
                  color: context.corte.muted,
                ),
              ),
            ],
          );
          final button = FilledButton.icon(
            onPressed: () => CorteScope.of(context).go('/ajustes/tiktok'),
            icon: const CorteIcon(CorteIconName.arrowRight, size: 18),
            iconAlignment: IconAlignment.end,
            label: const Text('Conectar cuenta'),
          );
          return wide
              ? Row(
                  children: [
                    const CorteIcon(CorteIconName.store, size: 44),
                    const SizedBox(width: 20),
                    Expanded(child: details),
                    const SizedBox(width: 20),
                    button,
                  ],
                )
              : Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [details, const SizedBox(height: 16), button],
                );
        },
      ),
    ),
  );
}

class _HomeResults extends StatelessWidget {
  const _HomeResults({required this.dashboard, required this.showKpis});
  final AsyncSnapshot<DashboardDto> dashboard;
  final bool showKpis;

  @override
  Widget build(BuildContext context) {
    final kpis = showKpis ? dashboard.data?.kpis : null;
    final orders = kpis?['pedidos'];
    final unavailable = dashboard.hasError
        ? 'No disponible'
        : dashboard.connectionState == ConnectionState.waiting
        ? 'Cargando resultados…'
        : 'Sin datos todavía';
    final metrics = [
      (
        'Ventas generadas',
        money(kpis?['ventas_centavos']),
        'Ventas atribuidas a tu contenido',
      ),
      (
        'Comisión estimada',
        money(kpis?['comision_estimada_centavos']),
        'Estimación de TikTok Shop',
      ),
      (
        'Pedidos',
        orders is num ? integer(orders) : '—',
        'Pedidos de los últimos 30 días',
      ),
    ];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Wrap(
          alignment: WrapAlignment.spaceBetween,
          crossAxisAlignment: WrapCrossAlignment.center,
          spacing: 16,
          runSpacing: 6,
          children: [
            Semantics(
              header: true,
              child: Text(
                'Resultados',
                style: _sectionStyle.copyWith(
                  fontSize: MediaQuery.sizeOf(context).width < 600 ? 23 : 25,
                  height: 1.3,
                  letterSpacing: -.6,
                ),
              ),
            ),
            Text(
              'Últimos 30 días',
              style: TextStyle(
                fontSize: MediaQuery.sizeOf(context).width < 600 ? 13 : 14,
                color: context.corte.muted,
              ),
            ),
          ],
        ),
        const SizedBox(height: 14),
        _HomePanel(
          key: const ValueKey('home-history-metrics'),
          child: LayoutBuilder(
            builder: (context, limits) {
              final width = limits.maxWidth;
              final values = [for (final (_, amount, _) in metrics) amount];
              final columnAmountSize = (width * .036).clamp(24, 36).toDouble();
              final wide =
                  width > 720 &&
                  _amountsFit(
                    context,
                    values,
                    columnAmountSize,
                    (width - 2) / 3 - 56,
                  );
              final amountSize = wide
                  ? columnAmountSize
                  : (width * .06).clamp(24, 32).toDouble();
              final inlineValues =
                  !wide &&
                  width > 360 &&
                  _amountsFit(context, values, amountSize, (width - 54) / 2);
              final tiles = [
                for (final (label, value, subtitle) in metrics)
                  _HomeMetric(
                    label: label,
                    value: value,
                    detail: value == '—' ? unavailable : subtitle,
                    amountSize: amountSize,
                    sideBySide: inlineValues,
                    wide: wide,
                    padding: EdgeInsets.symmetric(
                      horizontal: wide ? 28 : 20,
                      vertical: wide ? 0 : 18,
                    ),
                  ),
              ];
              if (wide) {
                return Padding(
                  padding: const EdgeInsets.symmetric(vertical: 20),
                  child: IntrinsicHeight(
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        for (var i = 0; i < tiles.length; i++) ...[
                          if (i > 0) const VerticalDivider(width: 1),
                          Expanded(child: tiles[i]),
                        ],
                      ],
                    ),
                  ),
                );
              }
              return Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  for (var i = 0; i < tiles.length; i++) ...[
                    if (i > 0) const Divider(indent: 20, endIndent: 20),
                    tiles[i],
                  ],
                ],
              );
            },
          ),
        ),
        if (dashboard.hasError) ...[
          const SizedBox(height: 10),
          Semantics(
            liveRegion: true,
            child: Text(
              'No pudimos cargar tus resultados. Usa Actualizar para volver a intentarlo.',
              style: TextStyle(fontSize: 13, color: context.corte.danger),
            ),
          ),
        ],
      ],
    );
  }
}

bool _amountsFit(
  BuildContext context,
  List<String> values,
  double fontSize,
  double availableWidth,
) {
  final painter = TextPainter(
    textDirection: Directionality.of(context),
    textScaler: MediaQuery.textScalerOf(context),
    maxLines: 1,
  );
  final style = DefaultTextStyle.of(
    context,
  ).style.merge(_amountStyle.copyWith(fontSize: fontSize));
  try {
    for (final value in values) {
      painter.text = TextSpan(text: value, style: style);
      painter.layout();
      if (painter.width > availableWidth) return false;
    }
    return true;
  } finally {
    painter.dispose();
  }
}

class _HomeMetric extends StatelessWidget {
  const _HomeMetric({
    required this.label,
    required this.value,
    required this.detail,
    required this.amountSize,
    required this.sideBySide,
    required this.wide,
    required this.padding,
  });
  final String label, value, detail;
  final double amountSize;
  final bool sideBySide, wide;
  final EdgeInsets padding;

  @override
  Widget build(BuildContext context) {
    final title = Text(
      label,
      style: TextStyle(
        fontSize: wide ? 16 : 14,
        height: 1.4,
        fontWeight: FontWeight.w600,
        fontVariations: const [FontVariation('wght', 650)],
      ),
    );
    final amount = Text(
      value,
      style: _amountStyle.copyWith(fontSize: amountSize),
    );
    final description = Text(
      detail,
      style: TextStyle(
        fontSize: wide ? 13 : 12,
        height: 1.5,
        color: context.corte.muted,
      ),
    );
    return InkWell(
      onTap: () => CorteScope.of(context).go('/ventas?periodo=30d'),
      child: Padding(
        padding: padding,
        child: sideBySide
            ? Row(
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [title, const SizedBox(height: 4), description],
                    ),
                  ),
                  const SizedBox(width: 12),
                  Flexible(child: amount),
                ],
              )
            : Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  title,
                  const SizedBox(height: 7),
                  amount,
                  const SizedBox(height: 7),
                  description,
                ],
              ),
      ),
    );
  }
}

class _HomePanel extends StatelessWidget {
  const _HomePanel({super.key, this.title, this.action, required this.child});
  final String? title;
  final Widget? action;
  final Widget child;

  @override
  Widget build(BuildContext context) => Material(
    color: context.corte.isDark ? context.corte.soft : context.corte.surface,
    clipBehavior: Clip.antiAlias,
    shape: RoundedRectangleBorder(
      side: BorderSide(color: context.corte.line),
      borderRadius: BorderRadius.circular(8),
    ),
    child: title == null
        ? child
        : Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              ConstrainedBox(
                constraints: const BoxConstraints(minHeight: 62),
                child: Padding(
                  padding: EdgeInsets.symmetric(
                    horizontal: _panelPadding(context),
                    vertical: action == null ? 16 : 9,
                  ),
                  child: Wrap(
                    alignment: WrapAlignment.spaceBetween,
                    crossAxisAlignment: WrapCrossAlignment.center,
                    spacing: 12,
                    runSpacing: 4,
                    children: [
                      Semantics(
                        header: true,
                        child: Text(
                          title!,
                          style: _sectionStyle.copyWith(
                            fontSize: switch (MediaQuery.sizeOf(
                              context,
                            ).width) {
                              <= 599 => 20,
                              <= 1100 => 19,
                              _ => 21,
                            },
                          ),
                        ),
                      ),
                      ?action,
                    ],
                  ),
                ),
              ),
              const Divider(),
              child,
            ],
          ),
  );
}

class _HomePriorities extends StatelessWidget {
  const _HomePriorities({required this.samples, required this.retry});
  final AsyncSnapshot<MuestrasDto> samples;
  final VoidCallback retry;

  @override
  Widget build(BuildContext context) {
    final data = samples.data?.items ?? const <MuestraDto>[];
    final priorities = data.where((m) => samplePending(m.raw)).toList()
      ..sort(_priorityOrder);
    void openSamples() => CorteScope.of(context).go('/muestras');
    return _HomePanel(
      title: 'Tus prioridades',
      action: TextButton(
        onPressed: openSamples,
        style: TextButton.styleFrom(
          padding: EdgeInsets.zero,
          minimumSize: const Size(0, 44),
          tapTargetSize: MaterialTapTargetSize.shrinkWrap,
          textStyle: TextStyle(
            fontSize: MediaQuery.sizeOf(context).width < 600 ? 13 : 14,
            decoration: TextDecoration.underline,
            decorationThickness: .5,
          ),
        ),
        child: const Text('Ver muestras', textAlign: TextAlign.center),
      ),
      child: samples.hasError
          ? _PrioritiesMessage(
              title: 'No pudimos cargar tus muestras',
              text: 'Revisa tu conexión y vuelve a intentarlo.',
              icon: CorteIconName.circleAlert,
              action: OutlinedButton(
                onPressed: retry,
                child: const Text('Reintentar'),
              ),
            )
          : samples.connectionState == ConnectionState.waiting &&
                !samples.hasData
          ? Padding(
              padding: const EdgeInsets.all(24),
              child: Semantics(
                liveRegion: true,
                child: const Text('Cargando tus muestras…'),
              ),
            )
          : priorities.isEmpty
          ? _PrioritiesMessage(
              title: data.isEmpty
                  ? 'Todo empieza con tus muestras'
                  : 'Tus muestras están al día',
              text: data.isEmpty
                  ? 'Aquí verás qué productos necesitas grabar y cuándo publicarlos.'
                  : 'No tienes muestras pendientes de publicar. Puedes revisar todas en Muestras.',
              icon: data.isEmpty
                  ? CorteIconName.package
                  : CorteIconName.circleCheckBig,
              action: OutlinedButton(
                onPressed: openSamples,
                child: const Text('Ir a muestras'),
              ),
            )
          : Column(
              children: [
                for (final (index, item) in priorities.take(5).indexed) ...[
                  if (index > 0)
                    Divider(
                      indent: _panelPadding(context),
                      endIndent: _panelPadding(context),
                    ),
                  _PriorityRow(item.raw),
                ],
              ],
            ),
    );
  }
}

class _PrioritiesMessage extends StatelessWidget {
  const _PrioritiesMessage({
    required this.icon,
    required this.title,
    required this.text,
    required this.action,
  });

  final CorteIconName icon;
  final String title, text;
  final Widget action;

  @override
  Widget build(BuildContext context) {
    final compact = MediaQuery.sizeOf(context).width < 600;
    final error = icon == CorteIconName.circleAlert;
    Widget accent(Color color, double angle) => Transform.rotate(
      angle: angle,
      child: Container(
        width: 5,
        height: 15,
        decoration: BoxDecoration(
          color: color,
          borderRadius: BorderRadius.circular(3),
        ),
      ),
    );

    return ConstrainedBox(
      constraints: BoxConstraints(minHeight: compact ? 285 : 267),
      child: Padding(
        padding: EdgeInsets.symmetric(
          horizontal: compact ? 18 : 22,
          vertical: 24,
        ),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            if (error)
              CorteIcon(icon, size: 24, color: context.corte.danger)
            else
              SizedBox(
                width: 80,
                height: 70,
                child: Stack(
                  alignment: Alignment.center,
                  children: [
                    CorteIcon(icon, size: 60, color: context.corte.ink),
                    Positioned(
                      top: 0,
                      right: 10,
                      child: accent(CorteColors.coral, 22 * math.pi / 180),
                    ),
                    Positioned(
                      top: 9,
                      right: 0,
                      child: accent(context.corte.cyanInk, 55 * math.pi / 180),
                    ),
                  ],
                ),
              ),
            const SizedBox(height: 12),
            Text(
              title,
              textAlign: TextAlign.center,
              style: _sectionStyle.copyWith(
                fontSize: compact ? 20 : 21,
                fontVariations: const [FontVariation('wght', 700)],
              ),
            ),
            const SizedBox(height: 12),
            ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 500),
              child: Text(
                text,
                textAlign: TextAlign.center,
                style: TextStyle(
                  fontSize: 14,
                  height: 1.5,
                  color: context.corte.muted,
                ),
              ),
            ),
            const SizedBox(height: 15),
            ConstrainedBox(
              constraints: const BoxConstraints(minWidth: 152),
              child: action,
            ),
          ],
        ),
      ),
    );
  }
}

int _priorityOrder(MuestraDto a, MuestraDto b) {
  final overdue = (b.grupo == 'vencida' ? 1 : 0).compareTo(
    a.grupo == 'vencida' ? 1 : 0,
  );
  if (overdue != 0) return overdue;
  const last = 9007199254740991;
  final deadline = (a.fechaLimiteAt ?? last).compareTo(b.fechaLimiteAt ?? last);
  if (deadline != 0) return deadline;
  final position = intOf(
    a.raw['posicion_cola'],
    last,
  ).compareTo(intOf(b.raw['posicion_cola'], last));
  return position == 0 ? a.applicationId.compareTo(b.applicationId) : position;
}

class _PriorityRow extends StatelessWidget {
  const _PriorityRow(this.sample);
  final JsonMap sample;

  @override
  Widget build(BuildContext context) {
    final product = mapOf(sample['producto']);
    final name = textOf(mapOf(sample['tienda'])['nombre']);
    final limit = sample['fecha_limite_at'];
    final overdue = sample['grupo'] == 'vencida';
    final now = DateTime.now();
    final urgent =
        overdue ||
        (limit is int && limit * 1000 - now.millisecondsSinceEpoch < 172800000);
    final deadline = overdue
        ? 'Plazo vencido'
        : limit is int
        ? 'Vence ${_dayLabel(limit, now)}'
        : sample['grupo'] == 'pausada'
        ? 'Muestra pausada'
        : 'Por organizar';
    return ListTile(
      minTileHeight: 92,
      minVerticalPadding: 16,
      horizontalTitleGap: 14,
      contentPadding: EdgeInsets.symmetric(horizontal: _panelPadding(context)),
      leading: ExcludeSemantics(
        child: CortePhoto(
          product['imagen'] is String ? product['imagen'] as String : null,
          width: 48,
          height: 48,
          radius: 6,
        ),
      ),
      title: Text(
        productName(product),
        style: const TextStyle(
          fontSize: 14,
          height: 1.4,
          fontWeight: FontWeight.w600,
        ),
      ),
      subtitle: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (name.isNotEmpty) Text(name),
          Text(
            deadline,
            style: TextStyle(
              color: urgent ? context.corte.danger : context.corte.muted,
              fontWeight: urgent ? FontWeight.w600 : FontWeight.normal,
            ),
          ),
        ],
      ),
      trailing: const CorteIcon(CorteIconName.chevronRight, size: 18),
      onTap: () => CorteScope.of(context).go(
        '/muestras/m/${Uri.encodeComponent(textOf(sample['application_id']))}',
      ),
    );
  }
}

String _dayLabel(int seconds, DateTime now) {
  const weekdays = ['lun', 'mar', 'mié', 'jue', 'vie', 'sáb', 'dom'];
  const offset = Duration(hours: 6);
  final local = DateTime.fromMillisecondsSinceEpoch(
    seconds * 1000,
    isUtc: true,
  ).subtract(offset);
  final label =
      '${weekdays[local.weekday - 1]} ${date(seconds - offset.inSeconds, utc: true)}';
  return now.toUtc().subtract(offset).year == local.year
      ? label
      : '$label ${local.year}';
}

class _HomeShortcuts extends StatelessWidget {
  const _HomeShortcuts();

  static const _links = [
    (
      'Organizar muestras',
      'Planea tus próximas publicaciones',
      '/muestras',
      CorteIconName.package,
    ),
    (
      'Revisar ventas',
      'Consulta ingresos y comisiones',
      '/ventas',
      CorteIconName.chartColumn,
    ),
    (
      'Ver tus tiendas',
      'Da seguimiento a cada colaboración',
      '/tiendas',
      CorteIconName.store,
    ),
  ];

  @override
  Widget build(BuildContext context) {
    final ui = CorteScope.of(context);
    return _HomePanel(
      title: 'Accesos rápidos',
      child: Column(
        children: [
          for (final (index, (title, detail, route, icon))
              in _links.indexed) ...[
            if (index > 0)
              Divider(
                indent: _panelPadding(context),
                endIndent: _panelPadding(context),
              ),
            ListTile(
              minTileHeight: MediaQuery.sizeOf(context).width < 600 ? 86 : 88,
              minVerticalPadding: 18,
              horizontalTitleGap: MediaQuery.sizeOf(context).width <= 1100
                  ? 12
                  : 18,
              contentPadding: EdgeInsets.symmetric(
                horizontal: _panelPadding(context),
              ),
              leading: CorteIcon(icon, size: 24),
              title: Text(
                title,
                style: const TextStyle(
                  fontSize: 16,
                  fontWeight: FontWeight.w600,
                ),
              ),
              subtitle: Text(detail),
              trailing: const CorteIcon(CorteIconName.chevronRight, size: 18),
              onTap: () => ui.go(route),
            ),
          ],
        ],
      ),
    );
  }
}

class _NativeResults extends StatelessWidget {
  const _NativeResults({required this.dashboard});
  final DashboardDto dashboard;

  @override
  Widget build(BuildContext context) {
    final ui = CorteScope.of(context);
    final points = rowsOf(dashboard.serie?['puntos']);
    final stores = rowsOf(dashboard.raw['top_tiendas']);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const Divider(),
        const SizedBox(height: 20),
        HomeTikTokProfile(profile: dashboard.perfilTikTok),
        HomeSalesOverview(actualidad: dashboard.actualidad ?? const {}),
        const SizedBox(height: 20),
        _DesktopPanel(
          title: 'Comisión estimada por día',
          subtitle: 'Últimos 30 días',
          child: _DesktopCommissionChart(points),
        ),
        const SizedBox(height: 20),
        _DesktopPanel(
          title: 'Tiendas',
          action: TextButton(
            onPressed: () => ui.go('/tiendas'),
            child: const Text('Ver tiendas'),
          ),
          child: stores.isEmpty
              ? const EmptyState('Todavía no hay tiendas en este periodo')
              : Column(
                  children: [
                    for (final store in stores.take(3)) _DesktopStoreRow(store),
                  ],
                ),
        ),
      ],
    );
  }
}

class _DesktopPanel extends StatelessWidget {
  const _DesktopPanel({
    required this.title,
    required this.child,
    this.subtitle,
    this.action,
  });
  final String title;
  final String? subtitle;
  final Widget child;
  final Widget? action;

  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.fromLTRB(16, 12, 16, 16),
    decoration: BoxDecoration(
      color: context.corte.surface,
      border: Border.all(color: context.corte.line),
      borderRadius: BorderRadius.circular(8),
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          children: [
            Expanded(
              child: Semantics(
                header: true,
                child: Text(
                  title,
                  style: Theme.of(context).textTheme.titleLarge,
                ),
              ),
            ),
            if (action case final button?) ...[
              const SizedBox(width: 8),
              Flexible(child: button),
            ],
          ],
        ),
        if (subtitle != null) ...[
          const SizedBox(height: 2),
          Text(
            subtitle!,
            style: TextStyle(fontSize: 12, color: context.corte.muted),
          ),
        ],
        const SizedBox(height: 12),
        child,
      ],
    ),
  );
}

class _DesktopStoreRow extends StatelessWidget {
  const _DesktopStoreRow(this.shop);
  final Map<String, dynamic> shop;

  @override
  Widget build(BuildContext context) {
    final sales = mapOf(shop['ventas']);
    final commission = sales['comision_estimada_centavos'];
    final key = textOf(shop['tienda_key']);
    final image = textOf(shop['imagen']);
    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: key.isEmpty
            ? null
            : () => CorteScope.of(
                context,
              ).go('/tiendas/${Uri.encodeComponent(key)}'),
        child: Container(
          padding: const EdgeInsets.symmetric(vertical: 12),
          decoration: BoxDecoration(
            border: Border(top: BorderSide(color: context.corte.line)),
          ),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (image.isNotEmpty)
                CortePhoto(
                  image,
                  width: 30,
                  height: 30,
                  label: textOf(shop['nombre']),
                )
              else
                Padding(
                  padding: const EdgeInsets.only(top: 3),
                  child: CorteIcon(
                    CorteIconName.store,
                    size: 20,
                    color: context.corte.muted,
                  ),
                ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      textOf(shop['nombre']),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        fontSize: 13,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    if (commission is num) ...[
                      const SizedBox(height: 3),
                      Text(
                        '${money(commission)} · comisión estimada',
                        style: TextStyle(
                          fontSize: 12,
                          color: context.corte.muted,
                        ),
                      ),
                    ] else if (textOf(shop['salud_porque']).isNotEmpty) ...[
                      const SizedBox(height: 3),
                      Text(
                        textOf(shop['salud_porque']),
                        style: TextStyle(
                          fontSize: 12,
                          color: context.corte.muted,
                        ),
                      ),
                    ],
                  ],
                ),
              ),
              if (key.isNotEmpty) ...[
                const SizedBox(width: 8),
                CorteIcon(
                  CorteIconName.chevronRight,
                  size: 18,
                  color: context.corte.muted,
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

class _DesktopCommissionChart extends StatelessWidget {
  const _DesktopCommissionChart(this.points);
  final List<Map<String, dynamic>> points;

  @override
  Widget build(BuildContext context) {
    final valid = points
        .where((point) => point['comision_estimada_centavos'] is num)
        .toList();
    if (valid.isEmpty) {
      return const EmptyState('Todavía no hay datos para esta gráfica');
    }
    final values = valid
        .map((point) => intOf(point['comision_estimada_centavos']))
        .toList();
    final high = values.fold<int>(0, math.max);
    final low = values.fold<int>(0, math.min);
    final span = math.max(1, high - low);
    const plotHeight = 148.0;
    final zeroY = high / span * plotHeight;
    final ticks = <int>{0, (valid.length - 1) ~/ 2, valid.length - 1}.toList();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        SizedBox(
          height: plotHeight,
          child: Stack(
            children: [
              for (final y in [0.0, plotHeight / 2, plotHeight - 1])
                Positioned(
                  left: 0,
                  right: 0,
                  top: y,
                  child: Container(height: 1, color: context.corte.line),
                ),
              if (low < 0)
                Positioned(
                  left: 0,
                  right: 0,
                  top: zeroY,
                  child: Container(height: 1, color: context.corte.muted),
                ),
              Row(
                children: [
                  for (var i = 0; i < valid.length; i++)
                    Expanded(
                      child: Tooltip(
                        message:
                            '${textOf(valid[i]['etiqueta'])}: ${money(values[i])}',
                        child: Semantics(
                          label:
                              '${textOf(valid[i]['etiqueta'])}, comisión estimada ${money(values[i])}',
                          child: Padding(
                            padding: const EdgeInsets.symmetric(horizontal: 2),
                            child: SizedBox(
                              height: plotHeight,
                              child: Stack(
                                children: [
                                  if (values[i] != 0)
                                    Positioned(
                                      left: 0,
                                      right: 0,
                                      top: values[i] >= 0
                                          ? (high - values[i]) /
                                                span *
                                                plotHeight
                                          : zeroY,
                                      height: math.max(
                                        2.0,
                                        values[i].abs() / span * plotHeight,
                                      ),
                                      child: DecoratedBox(
                                        decoration: BoxDecoration(
                                          color: values[i] < 0
                                              ? context.corte.danger
                                              : i == valid.length - 1
                                              ? context.corte.cyanInk
                                              : context.corte.action,
                                          borderRadius:
                                              const BorderRadius.vertical(
                                                top: Radius.circular(2),
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
                    ),
                ],
              ),
            ],
          ),
        ),
        const SizedBox(height: 8),
        Row(
          children: [
            for (var i = 0; i < ticks.length; i++)
              Expanded(
                child: Text(
                  textOf(valid[ticks[i]]['etiqueta']),
                  textAlign: i == 0
                      ? TextAlign.left
                      : i == ticks.length - 1
                      ? TextAlign.right
                      : TextAlign.center,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(fontSize: 12, color: context.corte.muted),
                ),
              ),
          ],
        ),
      ],
    );
  }
}
