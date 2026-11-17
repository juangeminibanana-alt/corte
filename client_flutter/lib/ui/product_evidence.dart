import 'dart:convert';

import 'package:flutter/material.dart';

import '../app.dart';
import '../domain/corte_models.dart';
import '../data/public_product_source.dart';
import 'format.dart';
import 'theme.dart';
import 'widgets.dart';

/// Only source-backed product evidence. Missing access never means zero reviews.
class ProductEvidence extends StatefulWidget {
  const ProductEvidence({
    super.key,
    required this.productId,
    required this.extended,
    this.openOriginal,
    this.captureFromDevice,
  });
  final String productId;
  final JsonMap extended;
  final VoidCallback? openOriginal;
  final Future<JsonMap> Function(String productId)? captureFromDevice;

  @override
  State<ProductEvidence> createState() => _ProductEvidenceState();
}

class _ProductEvidenceState extends State<ProductEvidence> {
  JsonMap? _loaded;
  String? _loadedIdentity, _identity, _error;
  bool _extracting = false;
  int _request = 0;

  @override
  void didUpdateWidget(covariant ProductEvidence oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.productId != widget.productId) {
      _request++;
      _loaded = null;
      _error = null;
      _extracting = false;
    } else if (_loaded != null &&
        (widget.extended['evidencia_rev'] as int? ?? 0) >=
            (_loaded!['evidencia_rev'] as int? ?? 0)) {
      _loaded = null;
    }
  }

  Future<void> _extract(JsonMap current) async {
    if (_extracting) return;
    final ui = CorteScope.of(context), repo = CorteScope.of(context).repo;
    final owner = repo.ownerScope,
        creator = repo.cacheScope,
        id = widget.productId;
    final request = ++_request;
    setState(() {
      _extracting = true;
      _error = null;
    });
    try {
      final native =
          !ui.auth.isWeb &&
          const {'android', 'windows'}.contains(ui.auth.runtime.platform);
      final capture =
          widget.captureFromDevice ??
          (native ? (String id) => CortePublicProductSource().read(id) : null);
      final JsonMap result;
      if (capture != null) {
        final blocks = await capture(id);
        if (!mounted ||
            request != _request ||
            repo.ownerScope != owner ||
            repo.cacheScope != creator)
          return;
        result = await repo.put(
          '/api/productos/${Uri.encodeComponent(id)}/evidencia',
          body: {'rev': current['evidencia_rev'] ?? 0, ...blocks},
        );
      } else {
        result = await repo.post(
          '/api/productos/${Uri.encodeComponent(id)}/extraer',
          body: {'rev': current['evidencia_rev'] ?? 0},
        );
      }
      if (!mounted ||
          request != _request ||
          repo.ownerScope != owner ||
          repo.cacheScope != creator)
        return;
      setState(() {
        _loadedIdentity = '$id:$owner:$creator';
        _loaded = {
          ...widget.extended,
          'evidencia_rev': result['rev'],
          'tabla_tallas': result['tabla_tallas'],
          'resenas': result['resenas'],
        };
      });
      ui.refresh();
    } catch (error) {
      if (mounted &&
          request == _request &&
          repo.ownerScope == owner &&
          repo.cacheScope == creator) {
        setState(
          () => _error = error is ErrorApi
              ? (ui.auth.isWeb &&
                        error.codigo == 'fuente_verificacion_requerida'
                    ? 'TikTok limita la consulta desde el servidor. Actualiza este producto desde la app Android o Windows; los cambios aparecerán aquí.'
                    : error.mensaje)
              : 'No pudimos consultar la ficha original. Conservamos la información guardada.',
        );
      }
    } finally {
      if (mounted &&
          request == _request &&
          repo.ownerScope == owner &&
          repo.cacheScope == creator) {
        setState(() => _extracting = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final repo = CorteScope.of(context).repo;
    final identity =
        '${widget.productId}:${repo.ownerScope}:${repo.cacheScope}';
    if (_identity != identity) {
      _identity = identity;
      _request++;
      _loaded = null;
      _error = null;
      _extracting = false;
    }
    final current = _loadedIdentity == identity && _loaded != null
        ? _loaded!
        : widget.extended;
    final data = ProductoExtendidoDto(current);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const SizedBox(height: 20),
        Align(
          alignment: Alignment.centerLeft,
          child: OutlinedButton.icon(
            onPressed: _extracting || repo.cacheScope == null
                ? null
                : () => _extract(current),
            icon: _extracting
                ? const SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.sync_rounded, size: 18),
            label: Text(
              _extracting ? 'Consultando TikTok…' : 'Obtener tallas y reseñas',
            ),
          ),
        ),
        if (_error != null) ...[
          const SizedBox(height: 10),
          InlineNotice(text: _error!, error: true),
        ],
        const SectionHeading('Tabla de tallas'),
        if (data.tablaTallas?.estado == 'disponible' &&
            data.tablaTallas?.tabla != null)
          _SizeChart(data.tablaTallas!)
        else
          _EvidenceStatus(
            state: data.tablaTallas?.estado,
            chart: true,
            openOriginal: widget.openOriginal,
          ),
        const SectionHeading('Reseñas y fotos de compradores'),
        if (data.resenas?.estado == 'disponible')
          _ProductReviews(
            key: ValueKey(
              '${widget.productId}:${repo.ownerScope}:${repo.cacheScope}',
            ),
            productId: widget.productId,
            initial: data.resenas!,
            revision: data.evidenciaRev,
            openOriginal: widget.openOriginal,
          )
        else
          _EvidenceStatus(
            state: data.resenas?.estado,
            chart: false,
            openOriginal: widget.openOriginal,
          ),
      ],
    );
  }
}

class _EvidenceStatus extends StatelessWidget {
  const _EvidenceStatus({
    required this.state,
    required this.chart,
    this.openOriginal,
  });
  final String? state;
  final bool chart;
  final VoidCallback? openOriginal;

  @override
  Widget build(BuildContext context) {
    final message = switch (state) {
      'no_aplica' =>
        chart
            ? 'Este producto no requiere una tabla de tallas, según la fuente.'
            : 'La fuente no ofrece reseñas para este producto.',
      'error' =>
        'No pudimos actualizar esta información. Vuelve a intentarlo más tarde.',
      'no_disponible' =>
        chart
            ? 'La fuente consultada no proporcionó la tabla de medidas de este producto.'
            : 'No tenemos acceso a las reseñas de este producto en la fuente consultada.',
      _ =>
        chart
            ? 'Todavía no se ha obtenido la tabla de medidas de este producto.'
            : 'Todavía no se han obtenido las opiniones ni las fotos de compradores.',
    };
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: context.corte.soft,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(message, style: TextStyle(color: context.corte.muted)),
          if (openOriginal != null && state != 'no_aplica') ...[
            const SizedBox(height: 8),
            TextButton.icon(
              onPressed: openOriginal,
              icon: const Icon(Icons.open_in_new_rounded, size: 18),
              label: const Text('Consultar producto en TikTok Shop'),
            ),
          ],
        ],
      ),
    );
  }
}

class _SourceLine extends StatelessWidget {
  const _SourceLine(this.data);
  final EvidenciaBloqueDto data;
  @override
  Widget build(BuildContext context) {
    final source = data.fuente;
    final label = source?.nombre?.trim();
    return Padding(
      padding: const EdgeInsets.only(top: 12),
      child: Text(
        [
          if (label != null && label.isNotEmpty) 'Fuente: $label',
          if (source?.tipo == 'captura_tiktok') 'Captura de la ficha original',
          if (source?.tipo == 'vendedor')
            'Información compartida por el vendedor',
          if (data.consultadoAt != null)
            'Consultado el ${date(data.consultadoAt)}',
        ].join(' · '),
        style: TextStyle(fontSize: 12, color: context.corte.muted),
      ),
    );
  }
}

class _SizeChart extends StatelessWidget {
  const _SizeChart(this.data);
  final TablaTallasDto data;

  @override
  Widget build(BuildContext context) {
    final table = data.tabla!;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (table.unidad?.isNotEmpty == true)
          Padding(
            padding: const EdgeInsets.only(bottom: 10),
            child: Text(
              'Unidad: ${table.unidad}',
              style: TextStyle(color: context.corte.muted),
            ),
          ),
        if (table.columnas.isNotEmpty && table.filas.isNotEmpty)
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: DataTable(
              headingRowColor: WidgetStatePropertyAll(context.corte.soft),
              horizontalMargin: 16,
              columnSpacing: 28,
              dataRowMinHeight: 48,
              dataRowMaxHeight: double.infinity,
              columns: [
                for (final column in table.columnas)
                  DataColumn(label: Text(column)),
              ],
              rows: [
                for (final row in table.filas)
                  DataRow(
                    cells: [
                      for (var i = 0; i < table.columnas.length; i++)
                        DataCell(SelectableText(i < row.length ? row[i] : '—')),
                    ],
                  ),
              ],
            ),
          ),
        for (var i = 0; i < table.imagenes.length; i++)
          Padding(
            padding: const EdgeInsets.only(top: 12),
            child: _EvidencePhoto(
              path: table.imagenes[i],
              label: 'Tabla de tallas del producto, imagen ${i + 1}',
              chart: true,
            ),
          ),
        _SourceLine(data),
      ],
    );
  }
}

class _EvidencePhoto extends StatelessWidget {
  const _EvidencePhoto({
    required this.path,
    required this.label,
    this.chart = false,
  });
  final String path, label;
  final bool chart;

  Future<void> _enlarge(BuildContext context) => showDialog<void>(
    context: context,
    builder: (dialogContext) => Dialog(
      insetPadding: const EdgeInsets.all(16),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 1000),
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Text(
                      label,
                      style: Theme.of(context).textTheme.titleMedium,
                    ),
                  ),
                  IconButton(
                    tooltip: 'Cerrar imagen',
                    onPressed: () => Navigator.of(dialogContext).pop(),
                    icon: const Icon(Icons.close_rounded),
                  ),
                ],
              ),
              const SizedBox(height: 8),
              Flexible(
                child: LayoutBuilder(
                  builder: (context, limits) {
                    final height = MediaQuery.sizeOf(context).height * .65;
                    return InteractiveViewer(
                      minScale: 1,
                      maxScale: 5,
                      child: CortePhoto(
                        path,
                        original: true,
                        width: limits.maxWidth,
                        height: height,
                        fit: BoxFit.contain,
                        label: label,
                      ),
                    );
                  },
                ),
              ),
              const SizedBox(height: 8),
              const Text('Amplía con dos dedos o con la rueda del ratón.'),
            ],
          ),
        ),
      ),
    ),
  );

  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, limits) => Semantics(
      button: true,
      label: 'Ampliar $label',
      child: InkWell(
        onTap: () => _enlarge(context),
        borderRadius: BorderRadius.circular(8),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            CortePhoto(
              path,
              width: chart ? limits.maxWidth.clamp(0, 680).toDouble() : 104,
              height: chart ? 240 : 112,
              fit: chart ? BoxFit.contain : BoxFit.cover,
              label: label,
            ),
            if (chart) ...[
              const SizedBox(height: 8),
              Text(
                'Ampliar tabla',
                style: TextStyle(color: context.corte.action),
              ),
            ],
          ],
        ),
      ),
    ),
  );
}

class _ProductReviews extends StatefulWidget {
  const _ProductReviews({
    super.key,
    required this.productId,
    required this.initial,
    required this.revision,
    this.openOriginal,
  });
  final String productId;
  final ResenasProductoDto initial;
  final int? revision;
  final VoidCallback? openOriginal;
  @override
  State<_ProductReviews> createState() => _ProductReviewsState();
}

class _ProductReviewsState extends State<_ProductReviews> {
  late List<ResenaProductoDto> _items;
  late ResenasProductoDto _summary;
  int? _revision;
  String? _next, _error;
  bool _loading = false;
  int _request = 0;
  @override
  void initState() {
    super.initState();
    _reset();
  }

  void _reset() {
    _request++;
    _items = widget.initial.items.toList();
    _summary = widget.initial;
    _revision = widget.revision;
    _next = widget.initial.siguienteCursor;
    _error = null;
    _loading = false;
  }

  @override
  void didUpdateWidget(covariant _ProductReviews oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.productId != widget.productId ||
        oldWidget.revision != widget.revision ||
        jsonEncode(oldWidget.initial.raw) != jsonEncode(widget.initial.raw)) {
      _reset();
    }
  }

  Future<void> _loadMore() async {
    if (_loading || _next == null) return;
    final repo = CorteScope.of(context).repo;
    final owner = repo.ownerScope,
        creator = repo.cacheScope,
        request = ++_request;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      var data = await repo.get(
        '/api/productos/${Uri.encodeComponent(widget.productId)}/resenas',
        query: {'cursor': _next},
      );
      if (!mounted ||
          request != _request ||
          repo.ownerScope != owner ||
          repo.cacheScope != creator)
        return;
      var refreshed = false;
      if (_revision != null && data['rev'] != _revision) {
        // A capture may be replaced while paging. Restart from a single new
        // revision rather than joining pages that describe different data.
        data = await repo.get(
          '/api/productos/${Uri.encodeComponent(widget.productId)}/resenas',
          query: {'cursor': '0'},
          force: true,
        );
        if (!mounted ||
            request != _request ||
            repo.ownerScope != owner ||
            repo.cacheScope != creator)
          return;
        refreshed = true;
      }
      final block = ResenasProductoDto(jsonMap(data['resenas']));
      if (block.estado != 'disponible') {
        throw const FormatException('La fuente ya no aporta estas reseñas.');
      }
      final known = _items.map((review) => review.id).toSet();
      setState(() {
        if (refreshed) {
          _items = block.items.toList();
          _summary = block;
        } else {
          _items.addAll(block.items.where((review) => known.add(review.id)));
        }
        _revision = data['rev'] as int?;
        _next = block.siguienteCursor;
      });
    } catch (_) {
      if (mounted &&
          request == _request &&
          repo.ownerScope == owner &&
          repo.cacheScope == creator) {
        setState(
          () => _error =
              'No pudimos cargar más reseñas. Conservamos las que ya estás viendo.',
        );
      }
    } finally {
      if (mounted &&
          request == _request &&
          repo.ownerScope == owner &&
          repo.cacheScope == creator) {
        setState(() => _loading = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      Wrap(
        spacing: 16,
        runSpacing: 8,
        crossAxisAlignment: WrapCrossAlignment.center,
        children: [
          if (_summary.promedio != null)
            Semantics(
              label: 'Calificación ${_summary.promedio} de 5',
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(
                    Icons.star_rounded,
                    size: 24,
                    color: context.corte.action,
                  ),
                  const SizedBox(width: 5),
                  Text(
                    '${_summary.promedio} / 5',
                    style: Theme.of(context).textTheme.titleLarge,
                  ),
                ],
              ),
            ),
          if (_summary.total != null)
            Text('${integer(_summary.total)} reseñas en la fuente'),
        ],
      ),
      if (_items.isEmpty)
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 16),
          child: Text(
            _summary.total == 0
                ? 'Esta fuente confirma que todavía no hay reseñas publicadas.'
                : 'Todavía no se han cargado los comentarios de esta fuente.',
            style: TextStyle(color: context.corte.muted),
          ),
        ),
      for (final review in _items) _ReviewItem(review),
      if (_summary.total != null &&
          _summary.cargadas != null &&
          _summary.total! > _summary.cargadas!) ...[
        const SizedBox(height: 12),
        Text(
          'Vista previa de ${_summary.cargadas} de ${_summary.total} reseñas. La ficha pública entrega una parte de las opiniones.',
          style: TextStyle(color: context.corte.muted, fontSize: 12),
        ),
        if (widget.openOriginal != null)
          Align(
            alignment: Alignment.centerLeft,
            child: TextButton.icon(
              onPressed: widget.openOriginal,
              icon: const Icon(Icons.open_in_new_rounded, size: 18),
              label: const Text('Ver todas en TikTok Shop'),
            ),
          ),
      ],
      if (_error != null) InlineNotice(text: _error!, error: true),
      if (_next != null) ...[
        const SizedBox(height: 12),
        Align(
          alignment: Alignment.centerLeft,
          child: OutlinedButton.icon(
            onPressed: _loading ? null : _loadMore,
            icon: _loading
                ? const SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.expand_more_rounded),
            label: Text(_loading ? 'Cargando reseñas…' : 'Ver más reseñas'),
          ),
        ),
      ],
      _SourceLine(_summary),
    ],
  );
}

class _ReviewItem extends StatelessWidget {
  const _ReviewItem(this.review);
  final ResenaProductoDto review;

  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(vertical: 18),
    decoration: BoxDecoration(
      border: Border(bottom: BorderSide(color: context.corte.line)),
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Wrap(
          spacing: 12,
          runSpacing: 8,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            if (review.estrellas != null)
              Semantics(
                label: '${review.estrellas} de 5 estrellas',
                child: Text(
                  '${review.estrellas} ★',
                  style: TextStyle(
                    color: context.corte.action,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
            if (review.compraVerificada == true)
              const Text(
                'Compra verificada por la fuente',
                style: TextStyle(fontSize: 12),
              ),
            if (review.fecha != null)
              Text(
                date(review.fecha, utc: true),
                style: TextStyle(fontSize: 12, color: context.corte.muted),
              ),
          ],
        ),
        if (review.variante?.isNotEmpty == true) ...[
          const SizedBox(height: 8),
          Text(
            review.variante!,
            style: TextStyle(fontSize: 12, color: context.corte.muted),
          ),
        ],
        if (review.texto?.isNotEmpty == true) ...[
          const SizedBox(height: 10),
          SelectableText(review.texto!),
        ],
        if (review.imagenes.isNotEmpty) ...[
          const SizedBox(height: 12),
          Wrap(
            spacing: 10,
            runSpacing: 10,
            children: [
              for (var i = 0; i < review.imagenes.length; i++)
                SizedBox(
                  width: 104,
                  child: _EvidencePhoto(
                    path: review.imagenes[i],
                    label: 'Foto ${i + 1} de la reseña del comprador',
                  ),
                ),
            ],
          ),
        ],
      ],
    ),
  );
}
