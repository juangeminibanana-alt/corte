import 'dart:typed_data';

import 'package:flutter/material.dart';

import '../app.dart';
import '../data/corte_repository.dart';
import 'corte_icons.dart';
import 'format.dart';
import 'theme.dart';
import 'desktop.dart';

class CortePanel extends StatelessWidget {
  const CortePanel({
    super.key,
    this.padding = EdgeInsets.zero,
    required this.child,
  });

  final EdgeInsetsGeometry padding;
  final Widget child;

  @override
  Widget build(BuildContext context) => Material(
    color: context.corte.surface,
    clipBehavior: Clip.antiAlias,
    shape: RoundedRectangleBorder(
      side: BorderSide(color: context.corte.line),
      borderRadius: BorderRadius.circular(CorteRadius.panel),
    ),
    child: Padding(padding: padding, child: child),
  );
}

class CorteRouteTabs extends StatelessWidget {
  const CorteRouteTabs({super.key, required this.children});

  final List<CorteRouteTab> children;

  @override
  Widget build(BuildContext context) => SizedBox(
    width: double.infinity,
    child: DecoratedBox(
      decoration: BoxDecoration(
        border: Border(bottom: BorderSide(color: context.corte.line)),
      ),
      child: Wrap(children: children),
    ),
  );
}

class CorteRouteTab extends StatelessWidget {
  const CorteRouteTab(
    this.label, {
    super.key,
    required this.selected,
    required this.onPressed,
    this.count,
  });

  final String label;
  final bool selected;
  final VoidCallback? onPressed;
  final int? count;

  @override
  Widget build(BuildContext context) => Semantics(
    selected: selected,
    child: DecoratedBox(
      decoration: BoxDecoration(
        border: Border(
          bottom: BorderSide(
            color: selected ? context.corte.action : Colors.transparent,
            width: 2,
          ),
        ),
      ),
      child: TextButton(
        onPressed: onPressed,
        style: TextButton.styleFrom(
          foregroundColor: selected ? context.corte.action : context.corte.ink,
          disabledForegroundColor: selected
              ? context.corte.action
              : context.corte.muted,
          minimumSize: const Size(44, 48),
          padding: const EdgeInsets.symmetric(horizontal: CorteSpace.medium),
          textStyle: TextStyle(
            fontSize: CorteType.label,
            fontWeight: selected ? FontWeight.w700 : FontWeight.w500,
          ),
        ),
        child: Wrap(
          alignment: WrapAlignment.center,
          crossAxisAlignment: WrapCrossAlignment.center,
          spacing: CorteSpace.small,
          children: [
            Text(label, textAlign: TextAlign.center),
            if (count case final value?)
              Text(
                integer(value),
                style: Theme.of(context).textTheme.bodySmall,
              ),
          ],
        ),
      ),
    ),
  );
}

class InlineNotice extends StatelessWidget {
  const InlineNotice({
    super.key,
    required this.text,
    this.error = false,
    this.action,
  });
  final String text;
  final bool error;
  final Widget? action;
  @override
  Widget build(BuildContext context) => Semantics(
    liveRegion: true,
    child: Container(
      width: double.infinity,
      padding: const EdgeInsets.all(CorteSpace.medium),
      decoration: BoxDecoration(
        color: error ? context.corte.rose : context.corte.soft,
        border: Border.all(color: context.corte.line),
        borderRadius: BorderRadius.circular(CorteRadius.control),
      ),
      child: LayoutBuilder(
        builder: (context, limits) {
          final message = Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              CorteIcon(
                error ? CorteIconName.circleAlert : CorteIconName.circleHelp,
                color: error ? context.corte.danger : context.corte.cyanInk,
              ),
              const SizedBox(width: CorteSpace.small),
              Expanded(child: Text(text)),
            ],
          );
          final trailing = action;
          if (trailing == null) return message;
          final wide =
              limits.maxWidth >= 420 &&
              MediaQuery.textScalerOf(context).scale(14) <= 20;
          return wide
              ? Row(
                  children: [
                    Expanded(child: message),
                    const SizedBox(width: CorteSpace.medium),
                    trailing,
                  ],
                )
              : Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    message,
                    const SizedBox(height: CorteSpace.small),
                    trailing,
                  ],
                );
        },
      ),
    ),
  );
}

class PageTitle extends StatelessWidget {
  const PageTitle(
    this.title, {
    super.key,
    this.subtitle,
    this.action,
    this.back,
  });
  final String title;
  final String? subtitle;
  final Widget? action;
  final VoidCallback? back;
  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, limits) {
      final wide =
          limits.maxWidth > 720 &&
          MediaQuery.textScalerOf(context).scale(14) <= 20;
      final text = Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (back != null) ...[
            TextButton.icon(
              onPressed: back,
              icon: const CorteIcon(CorteIconName.chevronLeft),
              label: const Text('Volver'),
            ),
            const SizedBox(height: CorteSpace.small),
          ],
          Semantics(
            header: true,
            child: Text(
              title,
              style: Theme.of(context).textTheme.headlineLarge,
            ),
          ),
          if (subtitle != null && subtitle!.isNotEmpty) ...[
            const SizedBox(height: CorteSpace.small),
            Text(
              subtitle!,
              style: Theme.of(context).textTheme.bodyLarge
                  ?.copyWith(color: context.corte.muted),
            ),
          ],
        ],
      );
      return Padding(
        padding: const EdgeInsets.only(bottom: CorteSpace.xl),
        child: wide
            ? Row(
                crossAxisAlignment: CrossAxisAlignment.center,
                children: [
                  Expanded(child: text),
                  if (action != null) ...[
                    const SizedBox(width: CorteSpace.xl),
                    ConstrainedBox(
                      constraints: BoxConstraints(
                        maxWidth: limits.maxWidth / 2,
                      ),
                      child: action!,
                    ),
                  ],
                ],
              )
            : Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  text,
                  if (action != null) ...[
                    const SizedBox(height: CorteSpace.large),
                    SizedBox(width: double.infinity, child: action!),
                  ],
                ],
              ),
      );
    },
  );
}

class SectionHeading extends StatelessWidget {
  const SectionHeading(this.title, {super.key, this.action, this.subtitle});
  final String title;
  final Widget? action;
  final String? subtitle;
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(
      top: CorteSpace.xl,
      bottom: CorteSpace.medium,
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Wrap(
          crossAxisAlignment: WrapCrossAlignment.center,
          spacing: CorteSpace.medium,
          runSpacing: CorteSpace.small,
          children: [
            Semantics(
              header: true,
              child: Text(
                title,
                style: Theme.of(context).textTheme.headlineMedium,
              ),
            ),
            if (action != null) action!,
          ],
        ),
        if (subtitle != null) ...[
          const SizedBox(height: CorteSpace.xs),
          Text(subtitle!, style: TextStyle(color: context.corte.muted)),
        ],
      ],
    ),
  );
}

class EmptyState extends StatelessWidget {
  const EmptyState(
    this.title, {
    super.key,
    this.text,
    this.action,
    this.icon = Icons.inbox_outlined,
    this.error = false,
  });
  final String title;
  final String? text;
  final Widget? action;
  final IconData icon;
  final bool error;
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(
      vertical: CorteSpace.xxl,
      horizontal: CorteSpace.xl,
    ),
    child: Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: CorteSpace.block,
            height: CorteSpace.block,
            decoration: BoxDecoration(
              color: error ? context.corte.rose : context.corte.soft,
              border: Border.all(color: context.corte.line),
              borderRadius: BorderRadius.circular(CorteRadius.panel),
            ),
            child: error
                ? CorteIcon(
                    CorteIconName.circleAlert,
                    color: context.corte.danger,
                    size: 24,
                  )
                : Icon(icon, size: 24, color: context.corte.cyanInk),
          ),
          const SizedBox(height: CorteSpace.medium),
          Semantics(
            header: true,
            liveRegion: error,
            child: Text(
              title,
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.headlineMedium,
            ),
          ),
          if (text != null) ...[
            const SizedBox(height: CorteSpace.small),
            ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 440),
              child: Text(
                text!,
                textAlign: TextAlign.center,
                style: TextStyle(color: context.corte.muted),
              ),
            ),
          ],
          if (action != null) ...[
            const SizedBox(height: CorteSpace.large),
            action!,
          ],
        ],
      ),
    ),
  );
}

class ApiData extends StatefulWidget {
  const ApiData({
    super.key,
    required this.path,
    required this.builder,
    this.query = const {},
    this.padding = const EdgeInsets.all(24),
    this.errorBuilder,
  });
  final String path;
  final Map<String, Object?> query;
  final Widget Function(BuildContext context, JsonMap data) builder;
  final EdgeInsets padding;

  /// Vista propia para un error (p. ej. un 404 que tiene otra fuente). Si devuelve null, se muestra el aviso de siempre.
  final Widget? Function(BuildContext context, Object error)? errorBuilder;
  @override
  State<ApiData> createState() => _ApiDataState();
}

class _ApiDataState extends State<ApiData> {
  String? _key;
  String? _identity;
  JsonMap? _lastData;
  Future<JsonMap>? _future;
  @override
  Widget build(BuildContext context) {
    final ui = CorteScope.of(context);
    final identity =
        '${ui.repo.ownerScope}:${ui.repo.cacheScope}:${widget.path}:${widget.query}';
    if (_identity != identity) {
      _identity = identity;
      _lastData = null;
    }
    final key = '${ui.revision}:$identity';
    if (key != _key) {
      _key = key;
      _future = ui.repo.get(widget.path, query: widget.query);
    }
    return FutureBuilder<JsonMap>(
      // A refresh of the same account and resource must preserve form drafts.
      // Changing identity still discards both the old data and widget state.
      key: ValueKey(identity),
      future: _future,
      builder: (context, snapshot) {
        if (snapshot.hasError) {
          final error = snapshot.error;
          final propia = error == null
              ? null
              : widget.errorBuilder?.call(context, error);
          if (propia != null) return propia;
          return SingleChildScrollView(
            padding: widget.padding,
            child: EmptyState(
              'No pudimos cargar esta información',
              error: true,
              text: error is ErrorApi
                  ? error.mensaje
                  : 'Revisa tu conexión y vuelve a intentarlo.',
              action: FilledButton.icon(
                onPressed: () => setState(() {
                  _key = null;
                }),
                icon: const Icon(Icons.refresh_rounded),
                label: const Text('Reintentar'),
              ),
            ),
          );
        }
        if (snapshot.hasData) _lastData = snapshot.data;
        if (_lastData == null)
          return Center(
            child: Semantics(
              label: 'Cargando información',
              child: const CircularProgressIndicator(),
            ),
          );
        return widget.builder(context, _lastData!);
      },
    );
  }
}

class CortePhoto extends StatefulWidget {
  const CortePhoto(
    this.path, {
    super.key,
    this.width = 96,
    this.height = 100,
    this.fit = BoxFit.cover,
    this.radius = 9,
    this.label = 'Foto del producto',
    this.video = false,
    this.original = false,
    this.fallback,
  });
  final String? path;
  final double width, height, radius;
  final BoxFit fit;
  final String label;
  final bool video;
  final bool original;
  final Widget? fallback;
  @override
  State<CortePhoto> createState() => _CortePhotoState();
}

class _CortePhotoState extends State<CortePhoto> {
  String? _key;
  Future<Uint8List>? _future;
  @override
  Widget build(BuildContext context) {
    final ui = CorteScope.of(context);
    final path = widget.path;
    final size = widget.original ? null : (widget.width > 160 ? 'md' : 'sm');
    final key = '${ui.repo.ownerScope}:${ui.repo.cacheScope}:$path:$size';
    if (_key != key) {
      _key = key;
      _future = path == null || path.isEmpty
          ? null
          : ui.repo.imagen(path, tamano: size);
    }
    final placeholder =
        widget.fallback ??
        ColoredBox(
          color: context.corte.soft,
          child: Center(
            child: Icon(
              widget.video ? Icons.videocam_off_outlined : Icons.image_outlined,
              color: context.corte.muted,
              size: widget.width < 60 ? 20 : 29,
            ),
          ),
        );
    return Semantics(
      image: true,
      label: widget.label,
      child: ClipRRect(
        borderRadius: BorderRadius.circular(widget.radius),
        child: SizedBox(
          width: widget.width,
          height: widget.height,
          child: _future == null
              ? placeholder
              : FutureBuilder<Uint8List>(
                  key: ValueKey(key),
                  future: _future,
                  builder: (context, snap) {
                    if (!snap.hasData) return placeholder;
                    return Image.memory(
                      snap.data!,
                      fit: widget.fit,
                      cacheWidth: widget.original
                          ? null
                          : (widget.width *
                                    MediaQuery.devicePixelRatioOf(context))
                                .ceil()
                                .clamp(1, 2048)
                                .toInt(),
                      gaplessPlayback: false,
                      errorBuilder: (_, __, ___) => placeholder,
                      excludeFromSemantics: true,
                    );
                  },
                ),
        ),
      ),
    );
  }
}

class MetricStrip extends StatelessWidget {
  const MetricStrip(this.metrics, {super.key});
  final List<(String, String)> metrics;
  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, limits) => Wrap(
      spacing: 24,
      runSpacing: 22,
      children: metrics
          .map(
            (m) => SizedBox(
              width: limits.maxWidth < 500
                  ? (limits.maxWidth - 24) / 2
                  : (limits.maxWidth - 72) / 4,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    m.$1,
                    style: TextStyle(fontSize: 13, color: context.corte.muted),
                  ),
                  const SizedBox(height: 7),
                  Text(
                    m.$2,
                    style: TextStyle(
                      fontSize: useDesktopWorkspace(context) ? 24 : 26,
                      fontWeight: useDesktopWorkspace(context)
                          ? FontWeight.w600
                          : FontWeight.w800,
                      letterSpacing: -.8,
                    ),
                  ),
                ],
              ),
            ),
          )
          .toList(),
    ),
  );
}

class StatusTag extends StatelessWidget {
  const StatusTag(this.label, {super.key, this.urgent = false});
  final String label;
  final bool urgent;
  @override
  Widget build(BuildContext context) => Row(
    mainAxisSize: MainAxisSize.min,
    children: [
      Container(
        width: 7,
        height: 7,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: urgent ? CorteColors.coral : context.corte.cyanInk,
        ),
      ),
      const SizedBox(width: 7),
      Flexible(
        child: Text(
          label,
          style: TextStyle(
            fontWeight: FontWeight.w600,
            fontSize: 12,
            color: urgent ? context.corte.action : context.corte.ink,
          ),
        ),
      ),
    ],
  );
}

class DefinitionRow extends StatelessWidget {
  const DefinitionRow(this.label, this.value, {super.key});
  final String label, value;
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 10),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Expanded(
          child: Text(label, style: TextStyle(color: context.corte.muted)),
        ),
        const SizedBox(width: 18),
        Flexible(child: SelectableText(value, textAlign: TextAlign.right)),
      ],
    ),
  );
}

class MiniBars extends StatelessWidget {
  const MiniBars(this.points, {super.key});
  final List<Map<String, dynamic>> points;
  @override
  Widget build(BuildContext context) {
    if (points.isEmpty)
      return const EmptyState('Todavía no hay datos para esta gráfica');
    final values = points
        .map((p) => intOf(p['comision_estimada_centavos']))
        .toList();
    final maximum = values.fold<int>(0, (a, b) => a > b ? a : b);
    return SizedBox(
      height: 190,
      child: LayoutBuilder(
        builder: (context, limits) => Row(
          crossAxisAlignment: CrossAxisAlignment.end,
          children: List.generate(
            points.length,
            (i) => Expanded(
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 3),
                child: Tooltip(
                  message:
                      '${textOf(points[i]['etiqueta'])}: ${money(values[i])}',
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.end,
                    children: [
                      Container(
                        height: maximum == 0
                            ? 2
                            : (values[i] / maximum * 145).clamp(2.0, 145.0),
                        decoration: BoxDecoration(
                          color: i == points.length - 1
                              ? context.corte.cyanInk
                              : context.corte.action,
                          borderRadius: const BorderRadius.vertical(
                            top: Radius.circular(4),
                          ),
                        ),
                      ),
                      const SizedBox(height: 10),
                      Text(
                        textOf(points[i]['etiqueta']),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(
                          fontSize: 10,
                          color: context.corte.muted,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

void toast(BuildContext context, String text) =>
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(text)));

Future<void> runAction(
  BuildContext context,
  Future<void> Function() action, {
  String success = 'Guardado',
}) async {
  try {
    await action();
    if (!context.mounted) return;
    CorteScope.of(context).refresh();
    toast(context, success);
  } catch (error) {
    if (context.mounted)
      toast(
        context,
        error is ErrorApi ? error.mensaje : 'No pudimos guardar. Conserva la información e inténtalo de nuevo.',
      );
  }
}
