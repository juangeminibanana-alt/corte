import 'package:flutter/material.dart';

import '../app.dart';
import '../domain/domain.dart';
import 'catalog.dart' show openPublicLink;
import 'format.dart';
import 'theme.dart';
import 'widgets.dart';
import 'work.dart' show pagePadding;

const _rangos = {
  'min_price': 'Precio mínimo',
  'max_price': 'Precio máximo',
  'min_commission': 'Comisión mínima (%)',
  'max_commission': 'Comisión máxima (%)',
};

const _ordenes = {
  '': 'Relevancia',
  'units_sold:DESC': 'Más vendidos',
  'commission_rate:DESC': 'Mayor comisión',
  'commission:DESC': 'Mayor importe de comisión',
  'product_sales_price:ASC': 'Precio de menor a mayor',
  'product_sales_price:DESC': 'Precio de mayor a menor',
};

class MarketplacePage extends StatefulWidget {
  const MarketplacePage({
    super.key,
    required this.available,
    required this.checkingAccess,
    required this.onRetryAccess,
    required this.onBack,
    this.error,
  });

  final bool available, checkingAccess;
  final VoidCallback onRetryAccess, onBack;
  final Object? error;

  @override
  State<MarketplacePage> createState() => _MarketplacePageState();
}

class _MarketplacePageState extends State<MarketplacePage> {
  final _texto = TextEditingController();
  final _filtros = {
    for (final campo in _rangos.keys) campo: TextEditingController(),
  };
  final _productos = <String, JsonMap>{};
  String _orden = '';
  ({String id, String nombre})? _categoria;
  Map<String, Object?> _consulta = const {};
  String? _cursor, _error;
  bool _cargando = false, _buscada = false;

  @override
  void dispose() {
    _texto.dispose();
    for (final campo in _filtros.values) {
      campo.dispose();
    }
    super.dispose();
  }

  Future<void> _buscar() async {
    if (_cargando || !widget.available) return;
    final texto = _texto.text.trim();
    final query = <String, Object?>{
      'limit': 20,
      if (texto.isNotEmpty) 'q': texto,
      if (_categoria case final categoria?) 'category_id': categoria.id,
    };
    for (final entry in _filtros.entries) {
      final value = entry.value.text.trim().replaceAll(',', '.');
      if (value.isNotEmpty) query[entry.key] = value;
    }
    if (_orden.isNotEmpty) {
      final parts = _orden.split(':');
      query['sort'] = parts[0];
      query['direction'] = parts[1];
    }
    setState(() {
      _consulta = query;
      _productos.clear();
      _buscada = false;
      _cursor = null;
    });
    await _cargar();
  }

  Future<void> _cargar({String? cursor}) async {
    if (_cargando || !widget.available) return;
    final repo = CorteScope.of(context).repo;
    final identity = (repo.ownerScope, repo.cacheScope);
    setState(() {
      _cargando = true;
      _error = null;
    });
    try {
      final datos = await repo.get(
        '/api/catalogo/marketplace',
        query: {..._consulta, if (cursor != null) 'cursor': cursor},
        permitirCacheSinRed: false,
      );
      if (datos['productos'] is! List) {
        throw const FormatException('Marketplace');
      }
      if (!mounted ||
          !widget.available ||
          identity != (repo.ownerScope, repo.cacheScope)) {
        return;
      }
      final siguiente = textOf(datos['cursor_siguiente']);
      setState(() {
        for (final producto in rowsOf(datos['productos'])) {
          final id = textOf(producto['product_id']);
          if (id.isNotEmpty) _productos[id] = producto;
        }
        _cursor = siguiente.isEmpty || siguiente == cursor ? null : siguiente;
        _buscada = true;
      });
    } on Exception catch (error) {
      if (!mounted ||
          !widget.available ||
          identity != (repo.ownerScope, repo.cacheScope)) {
        return;
      }
      final campo = error is ErrorApi
          ? _rangos[error.detalle?['parametro']]
          : null;
      setState(() {
        _error = switch (error) {
          ErrorApi(codigo: 'parametros_invalidos') when campo != null =>
            'Revisa el filtro «${campo.toLowerCase()}».',
          ErrorApi(:final mensaje) => mensaje,
          _ => 'No pudimos leer los productos de TikTok Shop.',
        };
      });
    } finally {
      if (mounted) setState(() => _cargando = false);
    }
  }

  Widget _filtrosVista() => LayoutBuilder(
    builder: (context, limits) {
      final ancho = limits.maxWidth >= 520
          ? (limits.maxWidth - 12) / 2
          : limits.maxWidth;
      return Wrap(
        spacing: 12,
        runSpacing: 12,
        children: [
          SizedBox(
            width: ancho,
            child: TextField(
              controller: _texto,
              maxLength: 255,
              textInputAction: TextInputAction.search,
              enabled: !_cargando,
              decoration: const InputDecoration(
                labelText: 'Producto',
                prefixIcon: Icon(Icons.search_rounded),
                counterText: '',
              ),
              onSubmitted: (_) => _buscar(),
            ),
          ),
          SizedBox(
            width: ancho,
            child: DropdownButtonFormField<String>(
              decoration: const InputDecoration(labelText: 'Orden'),
              initialValue: _orden,
              isExpanded: true,
              items: [
                for (final entry in _ordenes.entries)
                  DropdownMenuItem(
                    value: entry.key,
                    child: Text(entry.value, overflow: TextOverflow.ellipsis),
                  ),
              ],
              onChanged: _cargando
                  ? null
                  : (value) => setState(() => _orden = value ?? ''),
            ),
          ),
          for (final entry in _rangos.entries)
            SizedBox(
              width: ancho,
              child: TextField(
                controller: _filtros[entry.key],
                enabled: !_cargando,
                keyboardType: const TextInputType.numberWithOptions(
                  decimal: true,
                ),
                decoration: InputDecoration(labelText: entry.value),
              ),
            ),
        ],
      );
    },
  );

  @override
  Widget build(BuildContext context) {
    final title = PageTitle(
      'Explorar TikTok Shop',
      subtitle: 'Busca productos de colaboración abierta.',
      back: widget.onBack,
    );
    if (!widget.available) {
      return ListView(
        padding: pagePadding(context),
        children: [
          title,
          if (widget.checkingAccess)
            const Center(
              child: CircularProgressIndicator(
                semanticsLabel: 'Verificando acceso',
              ),
            )
          else
            EmptyState(
              'Búsqueda de TikTok Shop no disponible',
              icon: Icons.storefront_outlined,
              text: widget.error == null
                  ? 'Revisa la conexión y el permiso de colaboraciones de creador en Ajustes.'
                  : 'No pudimos comprobar tu acceso. Revisa tu conexión.',
              action: widget.error == null
                  ? null
                  : OutlinedButton(
                      onPressed: widget.onRetryAccess,
                      child: const Text('Reintentar'),
                    ),
            ),
        ],
      );
    }

    final productos = _productos.values.toList(growable: false);
    return ListView.builder(
      padding: pagePadding(context),
      itemCount: productos.length + 2,
      itemBuilder: (context, index) {
        if (index == 0) {
          return Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              title,
              _filtrosVista(),
              if (_categoria case final categoria?) ...[
                const SizedBox(height: 12),
                InputChip(
                  label: Text('Categoría: ${categoria.nombre}'),
                  deleteButtonTooltipMessage: 'Quitar categoría',
                  onDeleted: _cargando
                      ? null
                      : () => setState(() => _categoria = null),
                ),
              ],
              const SizedBox(height: 16),
              FilledButton.icon(
                onPressed: _cargando ? null : _buscar,
                icon: const Icon(Icons.search_rounded),
                label: const Text('Buscar'),
              ),
              const SizedBox(height: 16),
              if (_buscada && productos.isEmpty && _error == null)
                const EmptyState(
                  'No encontramos productos',
                  text: 'Prueba otra búsqueda o cambia los filtros.',
                ),
            ],
          );
        }
        if (index <= productos.length) {
          return _MarketplaceProduct(
            producto: productos[index - 1],
            onCategory: _cargando
                ? null
                : (id, nombre) =>
                      setState(() => _categoria = (id: id, nombre: nombre)),
          );
        }
        return Padding(
          padding: const EdgeInsets.symmetric(vertical: 16),
          child: Wrap(
            spacing: 12,
            runSpacing: 12,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              if (_cargando) ...[
                const SizedBox.square(
                  dimension: 20,
                  child: CircularProgressIndicator(strokeWidth: 2),
                ),
                Semantics(
                  liveRegion: true,
                  child: const Text('Consultando TikTok Shop…'),
                ),
              ],
              if (_error case final error?)
                Semantics(
                  liveRegion: true,
                  child: Text(
                    error,
                    style: TextStyle(color: context.corte.danger),
                  ),
                ),
              if (_cursor case final cursor?)
                OutlinedButton(
                  onPressed: _cargando ? null : () => _cargar(cursor: cursor),
                  child: const Text('Cargar más productos'),
                ),
            ],
          ),
        );
      },
    );
  }
}

String _precio(JsonMap producto) {
  final moneda = textOf(producto['moneda']);
  if (!RegExp(r'^[A-Z]{3}$').hasMatch(moneda)) return '';
  String importe(Object? valor) {
    final number = double.tryParse(textOf(valor));
    if (number == null || !number.isFinite || number < 0) return '';
    final formatted = money((number * 100).round(), decimals: true);
    return '$moneda ${formatted.substring(1)}';
  }

  final minimo = importe(producto['precio_min']);
  final maximo = importe(producto['precio_max']);
  if (minimo.isEmpty || minimo == maximo) return maximo;
  if (maximo.isEmpty) return minimo;
  return '$minimo a $maximo';
}

class _MarketplaceProduct extends StatelessWidget {
  const _MarketplaceProduct({required this.producto, this.onCategory});

  final JsonMap producto;
  final void Function(String, String)? onCategory;

  @override
  Widget build(BuildContext context) {
    final price = _precio(producto);
    final comision = producto['comision_porcentaje'];
    final vendidos = producto['unidades_vendidas'];
    final tienda = textOf(producto['tienda']);
    final enlace = textOf(producto['enlace']);
    final categorias = rowsOf(producto['categorias']);
    final detalles = [
      if (tienda.isNotEmpty) tienda,
      if (comision is num) '${(comision * 100).round() / 100} % de comisión',
      if (vendidos is num) '${integer(vendidos)} vendidos',
    ];
    return DecoratedBox(
      decoration: BoxDecoration(
        border: Border(bottom: BorderSide(color: context.corte.line)),
      ),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Semantics(
              header: true,
              child: Text(
                textOf(producto['titulo'], 'Producto de TikTok Shop'),
                style: Theme.of(context).textTheme.titleMedium,
              ),
            ),
            if (price.isNotEmpty) ...[
              const SizedBox(height: 6),
              Text(price, style: const TextStyle(fontWeight: FontWeight.w700)),
            ],
            if (detalles.isNotEmpty) ...[
              const SizedBox(height: 6),
              Text(
                detalles.join(' · '),
                style: TextStyle(color: context.corte.muted),
              ),
            ],
            if (categorias.isNotEmpty || enlace.isNotEmpty)
              Wrap(
                spacing: 12,
                crossAxisAlignment: WrapCrossAlignment.center,
                children: [
                  for (final categoria in categorias)
                    if (categoria['id'] is String &&
                        categoria['nombre'] is String)
                      ActionChip(
                        tooltip: 'Seleccionar categoría ${categoria['nombre']}',
                        label: Text(categoria['nombre'] as String),
                        onPressed: onCategory == null
                            ? null
                            : () => onCategory!(
                                categoria['id'] as String,
                                categoria['nombre'] as String,
                              ),
                      ),
                  if (enlace.isNotEmpty)
                    TextButton.icon(
                      onPressed: () => openPublicLink(context, enlace),
                      icon: const Icon(Icons.open_in_new_rounded, size: 16),
                      label: const Text('Ver en TikTok'),
                    ),
                ],
              ),
          ],
        ),
      ),
    );
  }
}
