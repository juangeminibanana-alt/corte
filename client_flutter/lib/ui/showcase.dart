import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../app.dart';
import '../domain/domain.dart';
import 'catalog.dart' show openPublicLink;
import 'format.dart';
import 'theme.dart';
import 'widgets.dart';
import 'work.dart' show pagePadding;

const _route = '/api/catalogo/vitrina';
const _pageSize = 20;
final _productId = RegExp(r'^[1-9][0-9]{0,24}$');
final _publisherId = RegExp(r'^[A-Za-z0-9_-]{1,128}$');

class ShowcasePage extends StatefulWidget {
  const ShowcasePage({
    super.key,
    required this.available,
    required this.canWrite,
    required this.canGenerateLinks,
    required this.checkingAccess,
    required this.accessError,
    required this.onRetryAccess,
    required this.onBack,
  });

  final bool available, canWrite, canGenerateLinks, checkingAccess;
  final Object? accessError;
  final VoidCallback onRetryAccess, onBack;

  @override
  State<ShowcasePage> createState() => _ShowcasePageState();
}

class _ShowcasePageState extends State<ShowcasePage> {
  final _products = <String, JsonMap>{};
  List<({String id, bool ok, String message})> _results = [];
  bool _reading = false, _writing = false, _requested = false;
  String? _cursor, _loadError, _writeError, _loadedScope, _generatedLink;

  bool get _busy => _reading || _writing;
  bool get _ready => _loadedScope != null && !_busy && _loadError == null;
  bool get _canEdit => widget.canWrite && _ready;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (widget.available && !_requested) {
      _requested = true;
      unawaited(_load());
    }
  }

  Future<void> _load({String? cursor}) async {
    if (_reading) return;
    final repo = CorteScope.of(context).repo;
    if (cursor != null && repo.cacheScope != _loadedScope) {
      _verifyScope(_loadedScope);
      return;
    }
    final scope = repo.cacheScope;
    setState(() {
      _reading = true;
      _loadError = null;
      if (scope != _loadedScope) {
        _products.clear();
        _cursor = null;
        _writeError = null;
        _results = [];
        _generatedLink = null;
      }
    });
    try {
      final response = await repo.get(
        _route,
        query: {'limit': _pageSize, if (cursor != null) 'cursor': cursor},
        force: true,
        permitirCacheSinRed: false,
      );
      if (!mounted) return;
      if (response['productos'] is! List) {
        throw const FormatException('Respuesta de productos incompleta');
      }
      final next = textOf(response['cursor_siguiente']);
      setState(() {
        _loadedScope = scope;
        if (cursor == null) _products.clear();
        for (final product in rowsOf(response['productos'])) {
          final id = textOf(product['product_id']);
          if (_productId.hasMatch(id)) _products[id] = product;
        }
        _cursor = next.isEmpty || next == cursor ? null : next;
      });
    } on Exception catch (error) {
      if (!mounted) return;
      setState(() {
        _loadError = error is ErrorApi
            ? error.mensaje
            : 'No pudimos cargar la vitrina.';
      });
    } finally {
      if (mounted) setState(() => _reading = false);
    }
  }

  Future<JsonMap> _post(String path, Map<String, Object?> body, String scope) {
    return CorteScope.of(context).repo.write(
      'POST',
      path,
      headers: {'X-Corte-Cache-Scope': scope},
      body: body,
    );
  }

  bool _verifyScope(String? scope) {
    final repo = CorteScope.of(context).repo;
    if (scope != null && scope == repo.cacheScope && scope == _loadedScope) {
      return true;
    }
    setState(() {
      _writeError = 'La cuenta cambió. Actualiza la vitrina y vuelve a elegir.';
      _results = [];
      _generatedLink = null;
    });
    return false;
  }

  Future<void> _write(String action, List<String> ids, String? scope) async {
    if (!_canEdit || !_verifyScope(scope)) return;
    setState(() {
      _writing = true;
      _writeError = null;
      _results = [];
      _generatedLink = null;
    });
    try {
      final response = await _post('$_route/$action', {
        'product_ids': ids,
      }, scope!);
      if (!mounted) return;
      final results = {
        for (final row in rowsOf(response['resultados']))
          textOf(row['product_id']): row,
      };
      setState(() {
        _results = [
          for (final id in ids)
            (
              id: id,
              ok: results[id]?['ok'] == true,
              message: textOf(
                results[id]?['mensaje'],
                results[id]?['ok'] == true
                    ? 'Cambio aplicado.'
                    : 'TikTok no confirmó el cambio.',
              ),
            ),
        ];
      });
    } on Exception catch (error) {
      if (!mounted) return;
      setState(() {
        _writeError = error is ErrorApi
            ? error.mensaje
            : 'No pudimos confirmar el cambio con TikTok.';
      });
    } finally {
      if (mounted) {
        // Refresh the live list after partial results or an uncertain response.
        await _load();
        if (mounted) setState(() => _writing = false);
      }
    }
  }

  Future<void> _add() async {
    final scope = _loadedScope;
    final ids = await showDialog<List<String>>(
      context: context,
      builder: (_) => const _AddProductsDialog(),
    );
    if (mounted && ids != null) await _write('agregar', ids, scope);
  }

  Future<void> _confirm(String action, String id, String name) async {
    final scope = _loadedScope;
    final removing = action == 'quitar';
    final approved = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(
          removing ? 'Quitar de la vitrina' : 'Mover al inicio de la vitrina',
        ),
        content: Text(name),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancelar'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: Text(removing ? 'Quitar producto' : 'Fijar producto'),
          ),
        ],
      ),
    );
    if (mounted && approved == true) await _write(action, [id], scope);
  }

  Future<void> _generateLink(String id) async {
    final scope = _loadedScope;
    final options = await showDialog<Map<String, Object?>>(
      context: context,
      builder: (_) => const _AffiliateLinkDialog(),
    );
    if (!mounted ||
        options == null ||
        !_ready ||
        !widget.canGenerateLinks ||
        !_verifyScope(scope)) {
      return;
    }
    setState(() {
      _writing = true;
      _writeError = null;
      _results = [];
      _generatedLink = null;
    });
    try {
      final response = await _post('/api/catalogo/enlaces-afiliado', {
        'product_ids': [id],
        ...options,
      }, scope!);
      if (!mounted) return;
      final result = rowsOf(
        response['resultados'],
      ).where((row) => row['product_id'] == id).firstOrNull;
      final link = _safeAffiliateLink(result?['enlace']);
      setState(() {
        _generatedLink = link;
        if (link == null) {
          _writeError = textOf(
            result?['mensaje'],
            'TikTok no devolvió un enlace de afiliado válido.',
          );
        }
      });
    } on Exception catch (error) {
      if (!mounted) return;
      setState(() {
        _writeError = error is ErrorApi
            ? error.mensaje
            : 'No pudimos generar el enlace de afiliado.';
      });
    } finally {
      if (mounted) setState(() => _writing = false);
    }
  }

  Future<void> _copy(String link) async {
    if (!_verifyScope(_loadedScope)) return;
    try {
      await Clipboard.setData(ClipboardData(text: link));
      if (mounted) toast(context, 'Enlace copiado.');
    } on Exception {
      if (mounted) toast(context, 'No pudimos copiar el enlace.');
    }
  }

  @override
  Widget build(BuildContext context) {
    if (!widget.available) {
      return ListView(
        padding: pagePadding(context),
        children: [
          PageTitle('Vitrina', back: widget.onBack),
          if (widget.checkingAccess)
            const Center(
              child: CircularProgressIndicator(
                semanticsLabel: 'Verificando acceso a la vitrina',
              ),
            )
          else
            EmptyState(
              'Vitrina no disponible',
              text: widget.accessError == null
                  ? 'Conecta TikTok Shop y autoriza el acceso a tu vitrina.'
                  : 'No pudimos comprobar el acceso.',
              action: widget.accessError == null
                  ? null
                  : OutlinedButton(
                      onPressed: widget.onRetryAccess,
                      child: const Text('Reintentar'),
                    ),
            ),
        ],
      );
    }
    return ListView(
      padding: pagePadding(context),
      children: [
        PageTitle(
          'Vitrina',
          subtitle: 'Productos de tu vitrina de TikTok Shop.',
          back: widget.onBack,
          action: Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              OutlinedButton.icon(
                onPressed: _busy ? null : () => _load(),
                icon: const Icon(Icons.refresh_rounded),
                label: const Text('Actualizar'),
              ),
              if (widget.canWrite)
                FilledButton.icon(
                  onPressed: _canEdit ? _add : null,
                  icon: const Icon(Icons.add_rounded),
                  label: const Text('Agregar productos'),
                ),
            ],
          ),
        ),
        if (_busy)
          const Padding(
            padding: EdgeInsets.only(bottom: 16),
            child: LinearProgressIndicator(
              semanticsLabel: 'Actualizando vitrina',
            ),
          ),
        if (_loadError != null) InlineNotice(text: _loadError!, error: true),
        if (_writeError != null) InlineNotice(text: _writeError!, error: true),
        if (_generatedLink case final link?) ...[
          const SectionHeading('Enlace de afiliado'),
          SelectableText(link),
          Wrap(
            spacing: 8,
            children: [
              TextButton.icon(
                onPressed: () => _copy(link),
                icon: const Icon(Icons.copy_outlined),
                label: const Text('Copiar enlace'),
              ),
              TextButton.icon(
                onPressed: () {
                  if (_verifyScope(_loadedScope)) openPublicLink(context, link);
                },
                icon: const Icon(Icons.open_in_new_rounded),
                label: const Text('Abrir enlace'),
              ),
            ],
          ),
        ],
        if (!_busy &&
            _loadedScope == null &&
            _loadError == null &&
            (widget.canWrite || widget.canGenerateLinks))
          const InlineNotice(
            text:
                'Vuelve a iniciar sesión para usar las acciones de la vitrina.',
          ),
        if (_results.isNotEmpty) ...[
          const SectionHeading('Resultado por producto'),
          for (final result in _results)
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: InlineNotice(
                text: '${result.id} · ${result.message}',
                error: !result.ok,
              ),
            ),
        ],
        if (_products.isEmpty && !_busy && _loadError == null)
          const EmptyState(
            'Tu vitrina está vacía',
            icon: Icons.storefront_outlined,
          ),
        for (final product in _products.entries)
          _ShowcaseProduct(
            id: product.key,
            product: product.value,
            canWrite: widget.canWrite,
            canGenerateLinks: widget.canGenerateLinks,
            onAction: _canEdit ? _confirm : null,
            onGenerateLink: _ready && widget.canGenerateLinks
                ? () => _generateLink(product.key)
                : null,
          ),
        if (_cursor case final cursor?)
          Padding(
            padding: const EdgeInsets.only(top: 16),
            child: Align(
              alignment: Alignment.centerLeft,
              child: OutlinedButton(
                onPressed: _busy ? null : () => _load(cursor: cursor),
                child: const Text('Cargar más'),
              ),
            ),
          ),
      ],
    );
  }
}

class _ShowcaseProduct extends StatelessWidget {
  const _ShowcaseProduct({
    required this.id,
    required this.product,
    required this.canWrite,
    required this.canGenerateLinks,
    required this.onAction,
    required this.onGenerateLink,
  });

  final String id;
  final JsonMap product;
  final bool canWrite, canGenerateLinks;
  final void Function(String, String, String)? onAction;
  final VoidCallback? onGenerateLink;

  @override
  Widget build(BuildContext context) {
    final name = textOf(product['titulo'], 'Producto $id');
    final image = textOf(product['imagen_url']);
    final store = textOf(product['tienda']);
    final prices = [product['precio_min'], product['precio_max']]
        .map((value) => num.tryParse(textOf(value)))
        .whereType<num>()
        .where((value) => value.isFinite)
        .toSet()
        .map((value) => money((value * 100).round(), decimals: true));
    final currency = textOf(product['moneda']);
    final state = switch (product['estado']) {
      'SOLD_OUT' => 'Agotado',
      'HIDDEN' => 'Oculto',
      'UNDER_REVIEW' => 'En revisión',
      'REJECTED' => 'Rechazado',
      _ => null,
    };
    return Container(
      decoration: BoxDecoration(
        border: Border(bottom: BorderSide(color: context.corte.line)),
      ),
      padding: const EdgeInsets.symmetric(vertical: 12),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (image.startsWith('/img/')) ...[
            CortePhoto(image, width: 56, height: 64),
            const SizedBox(width: 12),
          ],
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(name, style: Theme.of(context).textTheme.titleMedium),
                const SizedBox(height: 4),
                Text(
                  [if (store.isNotEmpty) store, 'ID: $id'].join(' · '),
                  style: TextStyle(color: context.corte.muted),
                ),
                if (prices.isNotEmpty || state != null)
                  Text(
                    [
                      if (prices.isNotEmpty)
                        '${prices.join(' – ')} $currency'.trim(),
                      if (state != null) state,
                    ].join(' · '),
                  ),
                if (canWrite || canGenerateLinks)
                  Wrap(
                    spacing: 8,
                    children: [
                      if (canWrite)
                        TextButton.icon(
                          onPressed: onAction == null
                              ? null
                              : () => onAction!('fijar', id, name),
                          icon: const Icon(Icons.vertical_align_top_rounded),
                          label: const Text('Fijar arriba'),
                        ),
                      if (canWrite)
                        TextButton.icon(
                          onPressed: onAction == null
                              ? null
                              : () => onAction!('quitar', id, name),
                          icon: const Icon(Icons.remove_circle_outline_rounded),
                          label: const Text('Quitar'),
                        ),
                      if (canGenerateLinks)
                        TextButton.icon(
                          onPressed: onGenerateLink,
                          icon: const Icon(Icons.link_rounded),
                          label: const Text('Generar enlace'),
                        ),
                    ],
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

String? _safeAffiliateLink(Object? value) {
  final url = Uri.tryParse(textOf(value));
  if (url == null ||
      url.scheme != 'https' ||
      url.userInfo.isNotEmpty ||
      (url.hasPort && url.port != 443)) {
    return null;
  }
  final host = url.host.toLowerCase();
  if (!const {
    'tiktok.com',
    'www.tiktok.com',
    'shop.tiktok.com',
    'vt.tiktok.com',
    'vm.tiktok.com',
  }.contains(host)) {
    return null;
  }
  return url.toString();
}

class _AffiliateLinkDialog extends StatefulWidget {
  const _AffiliateLinkDialog();

  @override
  State<_AffiliateLinkDialog> createState() => _AffiliateLinkDialogState();
}

class _AffiliateLinkDialogState extends State<_AffiliateLinkDialog> {
  final _form = GlobalKey<FormState>();
  final _publisher = TextEditingController();
  final _campaign = TextEditingController();

  @override
  void dispose() {
    _publisher.dispose();
    _campaign.dispose();
    super.dispose();
  }

  void _generate() {
    if (!_form.currentState!.validate()) return;
    final publisher = _publisher.text.trim();
    final campaign = _campaign.text.trim();
    Navigator.pop(context, <String, Object?>{
      if (publisher.isNotEmpty) 'publisher_id': publisher,
      if (campaign.isNotEmpty) 'campaign_id': campaign,
    });
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    title: const Text('Generar enlace de afiliado'),
    scrollable: true,
    content: Form(
      key: _form,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          TextFormField(
            controller: _publisher,
            decoration: const InputDecoration(
              labelText: 'ID de publisher (opcional)',
            ),
            validator: (value) {
              final id = value?.trim() ?? '';
              return id.isEmpty || _publisherId.hasMatch(id)
                  ? null
                  : 'Utiliza letras, números, guiones o guiones bajos.';
            },
          ),
          const SizedBox(height: 12),
          TextFormField(
            controller: _campaign,
            decoration: const InputDecoration(
              labelText: 'ID de campaña (opcional)',
            ),
            validator: (value) {
              final id = value?.trim() ?? '';
              return id.isEmpty || _productId.hasMatch(id)
                  ? null
                  : 'Revisa el ID de campaña.';
            },
          ),
        ],
      ),
    ),
    actions: [
      TextButton(
        onPressed: () => Navigator.pop(context),
        child: const Text('Cancelar'),
      ),
      FilledButton(onPressed: _generate, child: const Text('Generar enlace')),
    ],
  );
}

class _AddProductsDialog extends StatefulWidget {
  const _AddProductsDialog();

  @override
  State<_AddProductsDialog> createState() => _AddProductsDialogState();
}

class _AddProductsDialogState extends State<_AddProductsDialog> {
  final _form = GlobalKey<FormState>();
  final _ids = TextEditingController();

  List<String> get _products => _ids.text
      .split(RegExp(r'[,\s]+'))
      .where((id) => id.isNotEmpty)
      .toSet()
      .toList();

  @override
  void dispose() {
    _ids.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    title: const Text('Agregar productos a la vitrina'),
    content: Form(
      key: _form,
      child: TextFormField(
        controller: _ids,
        autofocus: true,
        minLines: 2,
        maxLines: 4,
        decoration: const InputDecoration(
          labelText: 'IDs de producto',
          helperText: 'Separa hasta 20 IDs por coma o por línea.',
          helperMaxLines: 2,
        ),
        validator: (_) {
          final ids = _products;
          if (ids.isEmpty || ids.length > 20) return 'Ingresa de 1 a 20 IDs.';
          if (!ids.every(_productId.hasMatch))
            return 'Los IDs solo llevan números.';
          return null;
        },
      ),
    ),
    actions: [
      TextButton(
        onPressed: () => Navigator.pop(context),
        child: const Text('Cancelar'),
      ),
      FilledButton(
        onPressed: () {
          if (_form.currentState!.validate()) Navigator.pop(context, _products);
        },
        child: const Text('Agregar a la vitrina'),
      ),
    ],
  );
}
