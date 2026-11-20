import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../app.dart';
import '../domain/domain.dart';
import '../platform/android_startup.dart';
import 'corte_icons.dart';
import 'format.dart';
import 'home_sales.dart';
import 'home_tiktok.dart';
import 'order_tile.dart';
import 'studio_earnings.dart';
import 'theme.dart';
import 'video_catalog.dart' show videosTodos;
import 'widgets.dart';
import 'work.dart' show productName, samplePending;

const _sectionStyle = TextStyle(
  fontSize: CorteType.section,
  height: 1.35,
  fontWeight: FontWeight.w700,
  fontVariations: [FontVariation('wght', 720)],
  letterSpacing: -.4,
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
  bool _opened = false;
  bool _recoveryLoaded = false;
  bool _readyMarked = false;
  String? _notice;

  _HomeScope _scopeFor(CorteUiController ui) =>
      (ui, ui.repo.ownerScope, ui.repo.cacheScope);

  Future<MuestrasDto> _readSamples(CorteUiController ui) => ui.repo.muestras(
    query: ui.auth.runtime.platform == 'android'
        ? const {
            'grupo': ['vencida', 'por_vencer', 'pausada'],
            'orden': 'prioridad',
          }
        : const {},
  );

  Future<T> _trace<T>(Future<T> load, String resource, _HomeScope scope) async {
    try {
      final data = await load;
      if (mounted && _scope == scope) {
        CorteAndroidStartup.mark('home_${resource}_loaded');
      }
      return data;
    } catch (_) {
      if (mounted && _scope == scope) {
        CorteAndroidStartup.mark('home_${resource}_error');
      }
      rethrow;
    }
  }

  void _load(CorteUiController ui) {
    final scope = _scopeFor(ui);
    if (_scope != scope) {
      _scope = scope;
      _revision = null;
      _updating = false;
      _notice = null;
    }
    if (_revision == ui.revision) return;
    final firstLoad = _revision == null;
    _revision = ui.revision;
    _session = ui.repo.sesion();
    _dashboard = ui.repo.dashboard();
    _samples = _readSamples(ui);
    if (firstLoad) {
      _readyMarked = false;
      CorteAndroidStartup.mark('home_loading');
      _session = _trace(_session, 'session', scope);
      _dashboard = _trace(_dashboard, 'dashboard', scope);
      _samples = _trace(_samples, 'samples', scope);
    }
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
    if (!_opened) {
      _opened = true;
      CorteAndroidStartup.mark(
        ui.androidRecovery ? 'recovery_home' : 'home_open',
      );
    }
    if (ui.androidRecovery && !_recoveryLoaded) {
      return ListView(
        padding: const EdgeInsets.all(20),
        children: [
          const PageTitle(
            'Inicio ligero',
            subtitle:
                'Abre Prendas o Dinero desde el menú, o carga el resumen cuando lo necesites.',
          ),
          const SizedBox(height: 16),
          Align(
            alignment: Alignment.centerLeft,
            child: FilledButton(
              onPressed: () => setState(() => _recoveryLoaded = true),
              child: const Text('Cargar resultados'),
            ),
          ),
        ],
      );
    }
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
    if (!_readyMarked && dashboard.hasData && samples.hasData) {
      _readyMarked = true;
      final scope = _scope;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted && _scope == scope) CorteAndroidStartup.mark('home_ready');
      });
    }
    final compact = MediaQuery.sizeOf(context).width < 600;
    final updating = _updating || session.data?.sync?.enCurso == true;
    final sessionData = session.data?.datos;
    final showKpis =
        sessionData == null ||
        sessionData['hay_datos'] == true ||
        sessionData['ultima_sync_ok_at'] != null;
    final today =
        DateTime.tryParse(
          textOf(mapOf(dashboard.data?.actualidad?['hoy'])['fecha']),
        ) ??
        DateTime.now().toUtc().subtract(const Duration(hours: 6));
    final priorities = _HomePriorities(
      samples: samples,
      retry: () => setState(() => _samples = _readSamples(ui)),
    );
    final recentOrders = _HomeRecentOrders(
      catalog: orderCatalog(rowsOf(dashboard.data?.raw['top_productos'])),
      hasResults: showKpis && dashboard.hasData,
    );

    return RefreshIndicator(
      onRefresh: () => _update(ui, session.data),
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: EdgeInsets.fromLTRB(
          compact ? CorteSpace.large : CorteSpace.xxl,
          compact ? CorteSpace.large : CorteSpace.xxl,
          compact ? CorteSpace.large : CorteSpace.xxl,
          CorteSpace.block,
        ),
        children: [
          _HomeHeader(
            today: today,
            updating: updating,
            onRefresh: () => _update(ui, session.data),
          ),
          if (_notice case final notice?) ...[
            const SizedBox(height: CorteSpace.medium),
            InlineNotice(text: notice),
          ],
          if (session.data?.conexion != null &&
              session.data?.conectada == false) ...[
            const SizedBox(height: CorteSpace.large),
            const _ConnectShop(),
          ] else if (session.hasError) ...[
            const SizedBox(height: CorteSpace.large),
            const InlineNotice(
              text:
                  'No pudimos cargar tu cuenta. Usa Actualizar para volver a intentarlo.',
              error: true,
            ),
          ],
          const SizedBox(height: CorteSpace.xl),
          _HomeEarnings(dashboard: dashboard, showKpis: showKpis),
          const SizedBox(height: CorteSpace.xl),
          LayoutBuilder(
            builder: (context, limits) {
              final sideBySide =
                  limits.maxWidth >= 790 &&
                  MediaQuery.textScalerOf(context).scale(CorteType.label) <= 20;
              if (!sideBySide) {
                return Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    priorities,
                    const SizedBox(height: CorteSpace.xl),
                    recentOrders,
                  ],
                );
              }
              return Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(flex: 5, child: priorities),
                  const SizedBox(width: CorteSpace.xl),
                  Expanded(flex: 6, child: recentOrders),
                ],
              );
            },
          ),
          const SizedBox(height: CorteSpace.xl),
          const _HomeShortcuts(),
          if (dashboard.data case final data?) ...[
            const SizedBox(height: CorteSpace.xl),
            _NativeResults(dashboard: data),
          ],
        ],
      ),
    );
  }
}

class _HomeHeader extends StatelessWidget {
  const _HomeHeader({
    required this.today,
    required this.updating,
    required this.onRefresh,
  });

  final DateTime today;
  final bool updating;
  final VoidCallback onRefresh;

  @override
  Widget build(BuildContext context) {
    final wide = MediaQuery.sizeOf(context).width >= 600;
    return Wrap(
      alignment: WrapAlignment.spaceBetween,
      crossAxisAlignment: WrapCrossAlignment.center,
      spacing: CorteSpace.large,
      runSpacing: CorteSpace.small,
      children: [
        Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Semantics(
              header: true,
              child: Text(
                'Hoy',
                style: studioDisplay(
                  context,
                  size: wide ? CorteType.display : CorteType.page,
                ),
              ),
            ),
            const SizedBox(height: CorteSpace.xs),
            Text(
              MaterialLocalizations.of(context).formatFullDate(today),
              style: Theme.of(
                context,
              ).textTheme.bodyMedium?.copyWith(color: context.corte.muted),
            ),
          ],
        ),
        OutlinedButton.icon(
          style: OutlinedButton.styleFrom(
            foregroundColor: context.corte.ink,
            side: BorderSide(color: context.corte.inputBorder),
          ),
          onPressed: updating ? null : onRefresh,
          icon: const CorteIcon(CorteIconName.refreshCw, size: 18),
          label: Text(updating ? 'Actualizando…' : 'Actualizar'),
        ),
      ],
    );
  }
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

class _HomeEarnings extends StatelessWidget {
  const _HomeEarnings({required this.dashboard, required this.showKpis});

  final AsyncSnapshot<DashboardDto> dashboard;
  final bool showKpis;

  @override
  Widget build(BuildContext context) {
    final kpis = showKpis ? dashboard.data?.kpis : null;
    final total = kpis?['comision_total_centavos'];
    final principal = studioCommissionAmount(
      total ?? kpis?['comision_estimada_centavos'],
    );
    final headline = total == null
        ? 'Comisión estimada'
        : 'Comisión del período';
    final state = dashboard.hasError
        ? 'No disponible'
        : dashboard.connectionState == ConnectionState.waiting
        ? 'Cargando resultados…'
        : 'Sin datos todavía';
    void openSales() => CorteScope.of(context).go('/ventas?periodo=30d');

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        StudioEarningsBand(
          label: headline,
          amount: principal,
          detail: Text(principal == '—' ? state : 'Últimos 30 días'),
          onPressed: openSales,
          breakdown:
              kpis?['comision_liquidada_centavos'] == null &&
                  kpis?['comision_por_liquidar_centavos'] == null
              ? null
              : Wrap(
                  spacing: CorteSpace.xl,
                  runSpacing: CorteSpace.small,
                  children: [
                    if (kpis?['comision_liquidada_centavos'] case final amount?)
                      _HomeBreakdown(
                        'Liquidada',
                        money(amount, decimals: true),
                      ),
                    if (kpis?['comision_por_liquidar_centavos']
                        case final amount?)
                      _HomeBreakdown(
                        'Por liquidar',
                        money(amount, decimals: true),
                      ),
                  ],
                ),
        ),
        Padding(
          key: const ValueKey('home-history-metrics'),
          padding: const EdgeInsets.symmetric(vertical: CorteSpace.small),
          child: Wrap(
            runSpacing: CorteSpace.xs,
            spacing: CorteSpace.large,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              _HomeMeasure(
                'Ventas generadas',
                money(kpis?['ventas_centavos']),
                openSales,
              ),
              _HomeMeasure(
                'Pedidos',
                kpis?['pedidos'] is num ? integer(kpis?['pedidos']) : '—',
                openSales,
              ),
              if (kpis?['comision_estimada_centavos'] != null && total != null)
                _HomeMeasure(
                  'Comisión estimada',
                  money(kpis?['comision_estimada_centavos']),
                  openSales,
                ),
            ],
          ),
        ),
        if (dashboard.hasError)
          const InlineNotice(
            error: true,
            text:
                'No pudimos cargar tus resultados. Usa Actualizar para volver a intentarlo.',
          ),
      ],
    );
  }
}

class _HomeBreakdown extends StatelessWidget {
  const _HomeBreakdown(this.label, this.amount);
  final String label, amount;

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Text(
        label,
        style: const TextStyle(
          color: CorteColors.chromeMuted,
          fontSize: CorteType.meta,
        ),
      ),
      Text(
        amount,
        style: Theme.of(context).textTheme.titleMedium?.copyWith(
          color: CorteColors.chromeInk,
          fontFeatures: const [FontFeature.tabularFigures()],
        ),
      ),
    ],
  );
}

class _HomeMeasure extends StatelessWidget {
  const _HomeMeasure(this.label, this.value, this.onTap);
  final String label, value;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => TextButton(
    onPressed: onTap,
    style: TextButton.styleFrom(
      alignment: AlignmentDirectional.centerStart,
      foregroundColor: context.corte.ink,
      padding: EdgeInsets.zero,
    ),
    child: Wrap(
      spacing: CorteSpace.small,
      crossAxisAlignment: WrapCrossAlignment.center,
      children: [
        Text(
          label,
          style: Theme.of(
            context,
          ).textTheme.bodyMedium?.copyWith(color: context.corte.muted),
        ),
        Text(value, style: studioDisplay(context, size: 22)),
      ],
    ),
  );
}

class _HomeRecentOrders extends StatelessWidget {
  const _HomeRecentOrders({required this.catalog, required this.hasResults});

  final Map<String, Map<String, dynamic>> catalog;
  final bool hasResults;

  @override
  Widget build(BuildContext context) {
    final ui = CorteScope.of(context);
    return _HomePanel(
      title: 'Pedidos recientes',
      action: TextButton.icon(
        onPressed: () => ui.go('/ordenes'),
        icon: const CorteIcon(CorteIconName.arrowRight, size: 18),
        iconAlignment: IconAlignment.end,
        label: const Text('Ver todos'),
      ),
      child: Padding(
        padding: EdgeInsets.symmetric(horizontal: _panelPadding(context)),
        child: hasResults
            ? ApiData(
                path: '/api/ordenes',
                query: const {'pagina': 1, 'por_pagina': 3},
                padding: EdgeInsets.zero,
                builder: (context, data) {
                  final orders = rowsOf(data['items']);
                  if (orders.isEmpty) {
                    return const Padding(
                      padding: EdgeInsets.symmetric(vertical: CorteSpace.xl),
                      child: Text('Los pedidos de tu tienda aparecerán aquí.'),
                    );
                  }
                  return Column(
                    children: [
                      for (final order in orders.take(3))
                        OrderTile(
                          key: ValueKey(order['order_id']),
                          order: order,
                          catalog: catalog,
                        ),
                    ],
                  );
                },
              )
            : const Padding(
                padding: EdgeInsets.symmetric(vertical: CorteSpace.xl),
                child: Text('Los pedidos de tu tienda aparecerán aquí.'),
              ),
      ),
    );
  }
}

class _HomePanel extends StatelessWidget {
  const _HomePanel({this.title, this.action, required this.child});
  final String? title;
  final Widget? action;
  final Widget child;

  @override
  Widget build(BuildContext context) => CortePanel(
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
                          style: studioDisplay(context, size: 29),
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
    final groupCounts = mapOf(samples.data?.raw['por_grupo']);
    final hasSamples =
        data.isNotEmpty ||
        groupCounts.values.any((count) => count is num && count > 0);
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
              title: hasSamples
                  ? 'Tus muestras están al día'
                  : 'Todo empieza con tus muestras',
              text: hasSamples
                  ? 'No tienes muestras pendientes de publicar. Puedes revisar todas en Muestras.'
                  : 'Aquí verás qué productos necesitas grabar y cuándo publicarlos.',
              icon: hasSamples
                  ? CorteIconName.circleCheckBig
                  : CorteIconName.package,
              action: OutlinedButton(
                onPressed: openSamples,
                child: const Text('Ir a muestras'),
              ),
            )
          : Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                _PriorityFeature(priorities.first.raw),
                for (final item in priorities.skip(1).take(4)) ...[
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
            Container(
              width: CorteSpace.block,
              height: CorteSpace.block,
              decoration: BoxDecoration(
                color: error ? context.corte.rose : context.corte.soft,
                border: Border.all(color: context.corte.line),
                borderRadius: BorderRadius.circular(CorteRadius.panel),
              ),
              child: CorteIcon(
                icon,
                size: 24,
                color: error ? context.corte.danger : context.corte.cyanInk,
              ),
            ),
            const SizedBox(height: CorteSpace.medium),
            Text(
              title,
              textAlign: TextAlign.center,
              style: _sectionStyle.copyWith(
                fontSize: CorteType.section,
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

class _PriorityFeature extends StatelessWidget {
  const _PriorityFeature(this.sample);

  final JsonMap sample;

  @override
  Widget build(BuildContext context) {
    final product = mapOf(sample['producto']);
    final title = orderProductLabel({
      'producto': productName(product),
    }, const {});
    final image = textOf(product['imagen']);
    final store = textOf(mapOf(sample['tienda'])['nombre']);
    final limit = sample['fecha_limite_at'];
    final overdue = sample['grupo'] == 'vencida';
    final deadline = overdue
        ? 'Plazo vencido'
        : limit is int
        ? 'Vence ${_dayLabel(limit, DateTime.now())}'
        : 'Por organizar';
    final id = textOf(sample['application_id']);
    void open() =>
        CorteScope.of(context).go('/muestras/m/${Uri.encodeComponent(id)}');
    return Padding(
      padding: EdgeInsets.all(_panelPadding(context)),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (image.isNotEmpty)
            LayoutBuilder(
              builder: (context, limits) => CortePhoto(
                image,
                label: 'Foto de $title',
                width: limits.maxWidth,
                height: (limits.maxWidth * .60).clamp(115.0, 280.0).toDouble(),
                radius: CorteRadius.control,
              ),
            )
          else
            Container(
              width: CorteSpace.section,
              height: CorteSpace.block,
              decoration: BoxDecoration(
                color: context.corte.soft,
                borderRadius: BorderRadius.circular(CorteRadius.control),
              ),
              child: CorteIcon(
                CorteIconName.shirt,
                size: 24,
                color: context.corte.muted,
              ),
            ),
          const SizedBox(height: CorteSpace.large),
          InkWell(
            onTap: id.isEmpty ? null : open,
            child: Text(
              title,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: studioDisplay(context, size: 33),
            ),
          ),
          const SizedBox(height: CorteSpace.small),
          Wrap(
            spacing: CorteSpace.small,
            runSpacing: CorteSpace.xs,
            children: [
              if (store.isNotEmpty)
                Text(store, style: Theme.of(context).textTheme.bodySmall),
              Text(
                deadline,
                style: TextStyle(
                  fontWeight: FontWeight.w700,
                  color: overdue ? context.corte.danger : context.corte.ink,
                ),
              ),
            ],
          ),
          const SizedBox(height: CorteSpace.medium),
          FilledButton.icon(
            onPressed: id.isEmpty ? null : open,
            icon: const CorteIcon(
              CorteIconName.arrowRight,
              color: CorteColors.onAction,
              size: 18,
            ),
            iconAlignment: IconAlignment.end,
            label: const Text('Ver muestra'),
          ),
        ],
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
      'Todos tus videos',
      'Revisa también los videos sin ventas',
      videosTodos,
      CorteIconName.squarePlay,
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
      borderRadius: BorderRadius.circular(CorteRadius.panel),
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
