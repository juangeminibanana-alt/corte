import 'dart:typed_data';
import 'package:flutter/material.dart';
import '../app.dart';
import '../data/corte_repository.dart';
import 'format.dart';
import 'theme.dart';
import 'desktop.dart';

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
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: error ? context.corte.rose : context.corte.soft,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(
            error ? Icons.error_outline_rounded : Icons.info_outline_rounded,
            size: 20,
            color: error ? context.corte.action : context.corte.cyanInk,
          ),
          const SizedBox(width: 10),
          Expanded(child: Text(text)),
          if (action != null) action!,
        ],
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
      final text = Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (back != null) ...[
            TextButton.icon(
              onPressed: back,
              icon: const Icon(Icons.chevron_left_rounded),
              label: const Text('Volver'),
            ),
            const SizedBox(height: 10),
          ],
          Text(
            title,
            style: useDesktopWorkspace(context) || limits.maxWidth > 650
                ? Theme.of(context).textTheme.headlineLarge
                : Theme.of(
                    context,
                  ).textTheme.headlineLarge?.copyWith(fontSize: 32),
          ),
          if (subtitle != null && subtitle!.isNotEmpty) ...[
            const SizedBox(height: 7),
            Text(subtitle!, style: TextStyle(color: context.corte.muted)),
          ],
        ],
      );
      return Padding(
        padding: const EdgeInsets.only(bottom: 24),
        child: limits.maxWidth > 650
            ? Row(
                crossAxisAlignment: CrossAxisAlignment.center,
                children: [
                  Expanded(child: text),
                  if (action != null) ...[const SizedBox(width: 24), action!],
                ],
              )
            : Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  text,
                  if (action != null) ...[
                    const SizedBox(height: 16),
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
    padding: EdgeInsets.only(
      top: useDesktopWorkspace(context) ? 18 : 26,
      bottom: useDesktopWorkspace(context) ? 10 : 16,
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Expanded(
              child: Text(title, style: Theme.of(context).textTheme.titleLarge),
            ),
            if (action != null) action!,
          ],
        ),
        if (subtitle != null) ...[
          const SizedBox(height: 6),
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
  });
  final String title;
  final String? text;
  final Widget? action;
  final IconData icon;
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 56, horizontal: 24),
    child: Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 38, color: context.corte.muted),
          const SizedBox(height: 18),
          Text(
            title,
            textAlign: TextAlign.center,
            style: Theme.of(context).textTheme.titleLarge,
          ),
          if (text != null) ...[
            const SizedBox(height: 9),
            ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 440),
              child: Text(
                text!,
                textAlign: TextAlign.center,
                style: TextStyle(color: context.corte.muted),
              ),
            ),
          ],
          if (action != null) ...[const SizedBox(height: 20), action!],
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
  });
  final String path;
  final Map<String, Object?> query;
  final Widget Function(BuildContext context, JsonMap data) builder;
  final EdgeInsets padding;
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
          return SingleChildScrollView(
            padding: widget.padding,
            child: EmptyState(
              'No pudimos cargar esta información',
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
  });
  final String? path;
  final double width, height, radius;
  final BoxFit fit;
  final String label;
  final bool video;
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
    final key =
        '${ui.repo.ownerScope}:${ui.repo.cacheScope}:$path:${widget.width > 160 ? 'md' : 'sm'}';
    if (_key != key) {
      _key = key;
      _future = path == null || path.isEmpty
          ? null
          : ui.repo.imagen(path, tamano: widget.width > 160 ? 'md' : 'sm');
    }
    final placeholder = ColoredBox(
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
        error is ErrorApi
            ? error.mensaje
            : 'No pudimos guardar. Conserva la información e inténtalo de nuevo.',
      );
  }
}
