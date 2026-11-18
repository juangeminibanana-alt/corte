import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';
import '../app.dart';
import '../domain/domain.dart';
import 'editors.dart';
import 'format.dart';
import 'theme.dart';
import 'widgets.dart';
import 'desktop.dart';
import 'work.dart';
import 'product_evidence.dart';
import 'video_catalog.dart';

Future<void> openPublicLink(BuildContext context, String? value) async {
  final url = Uri.tryParse(value ?? '');
  final host = url?.host.toLowerCase() ?? '';
  if (url == null ||
      url.scheme != 'https' ||
      url.userInfo.isNotEmpty ||
      !(host == 'tiktok.com' ||
          host.endsWith('.tiktok.com') ||
          host == 'tiktokglobalshop.com' ||
          host.endsWith('.tiktokglobalshop.com'))) {
    toast(context, 'Este enlace no está disponible.');
    return;
  }
  try {
    if (!await launchUrl(url, mode: LaunchMode.externalApplication) &&
        context.mounted) {
      toast(context, 'No pudimos abrir TikTok.');
    }
  } catch (_) {
    if (context.mounted) toast(context, 'No pudimos abrir TikTok.');
  }
}

class ProductGallery extends StatefulWidget {
  const ProductGallery({
    super.key,
    required this.photos,
    required this.productId,
    this.label = 'Fotos del producto',
    this.mainHeight,
  });
  final List<String> photos;
  final String productId, label;
  final double? mainHeight;
  @override
  State<ProductGallery> createState() => _ProductGalleryState();
}

class _ProductGalleryState extends State<ProductGallery> {
  int _index = 0;
  @override
  void didUpdateWidget(ProductGallery oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.productId != widget.productId ||
        _index >= widget.photos.length) {
      _index = 0;
    }
  }

  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, limits) {
      final height =
          widget.mainHeight ?? (limits.maxWidth < 500 ? 340.0 : 430.0);
      return Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Stack(
            children: [
              Center(
                child: CortePhoto(
                  widget.photos.isEmpty ? null : widget.photos[_index],
                  width: limits.maxWidth,
                  height: height,
                  fit: BoxFit.contain,
                  radius: 12,
                  label:
                      '${widget.label}, ${widget.photos.isEmpty ? 0 : _index + 1} de ${widget.photos.length}',
                ),
              ),
              if (widget.photos.length > 1)
                Positioned(
                  right: 12,
                  bottom: 12,
                  child: Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 10,
                      vertical: 5,
                    ),
                    decoration: BoxDecoration(
                      color: CorteColors.ink,
                      borderRadius: BorderRadius.circular(30),
                    ),
                    child: Text(
                      '${_index + 1} / ${widget.photos.length}',
                      style: const TextStyle(color: Colors.white, fontSize: 12),
                    ),
                  ),
                ),
            ],
          ),
          if (widget.photos.length > 1) ...[
            const SizedBox(height: 12),
            SizedBox(
              height: 68,
              child: ListView.separated(
                scrollDirection: Axis.horizontal,
                itemCount: widget.photos.length,
                separatorBuilder: (_, _) => const SizedBox(width: 8),
                itemBuilder: (context, i) => Semantics(
                  selected: _index == i,
                  button: true,
                  label: 'Ver foto ${i + 1} de ${widget.photos.length}',
                  child: InkWell(
                    onTap: () => setState(() => _index = i),
                    borderRadius: BorderRadius.circular(7),
                    child: Container(
                      padding: const EdgeInsets.all(3),
                      decoration: BoxDecoration(
                        border: Border.all(
                          color: _index == i
                              ? context.corte.action
                              : context.corte.line,
                          width: _index == i ? 2 : 1,
                        ),
                        borderRadius: BorderRadius.circular(7),
                      ),
                      child: ExcludeSemantics(
                        child: CortePhoto(
                          widget.photos[i],
                          width: 56,
                          height: 58,
                          radius: 4,
                          fit: BoxFit.contain,
                        ),
                      ),
                    ),
                  ),
                ),
              ),
            ),
          ],
          if (widget.photos.isEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Text(
                'TikTok todavía no proporcionó fotografías de este producto.',
                style: TextStyle(color: context.corte.muted, fontSize: 12),
              ),
            ),
        ],
      );
    },
  );
}

List<String> productPhotos(Map<String, dynamic> data) {
  final gallery = stringsOf(mapOf(data['extendido'])['galeria']);
  if (gallery.isNotEmpty) return gallery;
  final image = textOf(
    mapOf(data['ficha'])['imagen'],
    textOf(mapOf(data['fila'])['imagen']),
  );
  return image.isEmpty ? const [] : [image];
}

class ProductsPage extends StatefulWidget {
  const ProductsPage({super.key});
  @override
  State<ProductsPage> createState() => _ProductsPageState();
}

class _ProductsPageState extends State<ProductsPage> {
  String _search = '', _order = 'comision';
  bool _samples = false;
  @override
  Widget build(BuildContext context) => ApiData(
    path: '/api/analitica/productos',
    query: const {'limite': 1000},
    builder: (context, data) {
      final products = rowsOf(data['items'])
          .where(
            (p) =>
                (!_samples || p['es_muestra'] == true) &&
                '${productName(p)} ${p['tienda_nombre']}'
                    .toLowerCase()
                    .contains(_search.toLowerCase()),
          )
          .toList();
      products.sort(
        (a, b) => _order == 'nombre'
            ? productName(a).compareTo(productName(b))
            : intOf(
                b[_order == 'ventas'
                    ? 'ventas_centavos'
                    : 'comision_estimada_centavos'],
              ).compareTo(
                intOf(
                  a[_order == 'ventas'
                      ? 'ventas_centavos'
                      : 'comision_estimada_centavos'],
                ),
              ),
      );
      return ListView.builder(
        padding: pagePadding(context),
        itemCount: products.length + 1,
        itemBuilder: (context, i) {
          if (i > 0) return ProductRow(product: products[i - 1]);
          return Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              PageTitle(
                'Productos',
                subtitle:
                    '${data['total'] ?? rowsOf(data['items']).length} productos de tus ventas',
              ),
              const SalesNavigation(selected: 'productos'),
              const SizedBox(height: 20),
              TextField(
                decoration: const InputDecoration(
                  labelText: 'Buscar producto o tienda',
                  prefixIcon: Icon(Icons.search_rounded),
                ),
                onChanged: (v) => setState(() => _search = v),
              ),
              const SizedBox(height: 12),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  for (final order in [
                    ('comision', 'Comisión'),
                    ('ventas', 'Ventas'),
                    ('nombre', 'Nombre'),
                  ])
                    ChoiceChip(
                      label: Text(order.$2),
                      selected: _order == order.$1,
                      onSelected: (_) => setState(() => _order = order.$1),
                    ),
                  FilterChip(
                    label: const Text('Mis muestras'),
                    selected: _samples,
                    onSelected: (v) => setState(() => _samples = v),
                  ),
                ],
              ),
              const SizedBox(height: 16),
              if (products.isEmpty)
                const EmptyState(
                  'No encontramos productos',
                  text: 'Prueba otra búsqueda o actualiza tus datos.',
                ),
            ],
          );
        },
      );
    },
  );
}

class ProductRow extends StatelessWidget {
  const ProductRow({super.key, required this.product});
  final Map<String, dynamic> product;
  @override
  Widget build(BuildContext context) {
    final ui = CorteScope.of(context);
    return InkWell(
      onTap: () => ui.go(
        '/productos/${Uri.encodeComponent(textOf(product['product_id']))}',
      ),
      child: Container(
        padding: EdgeInsets.symmetric(
          vertical: useDesktopWorkspace(context) ? 12 : 17,
        ),
        decoration: BoxDecoration(
          border: Border(bottom: BorderSide(color: context.corte.line)),
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            CortePhoto(
              textOf(product['imagen']),
              width: useDesktopWorkspace(context) ? 56 : 76,
              height: useDesktopWorkspace(context) ? 64 : 82,
            ),
            const SizedBox(width: 16),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    productName(product),
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                      fontWeight: useDesktopWorkspace(context)
                          ? FontWeight.w600
                          : FontWeight.w700,
                      fontSize: useDesktopWorkspace(context) ? 14 : 15,
                    ),
                  ),
                  const SizedBox(height: 6),
                  Text(
                    textOf(product['tienda_nombre']),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(color: context.corte.muted, fontSize: 12),
                  ),
                  const SizedBox(height: 7),
                  Text(
                    '${integer(product['pedidos_validos'])} pedidos · ${integer(product['unidades'])} unidades',
                    style: TextStyle(color: context.corte.muted, fontSize: 12),
                  ),
                ],
              ),
            ),
            const SizedBox(width: 12),
            Column(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Text(
                  money(product['comision_estimada_centavos']),
                  style: const TextStyle(fontWeight: FontWeight.w800),
                ),
                Text(
                  'Comisión est.',
                  style: TextStyle(color: context.corte.muted, fontSize: 11),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class ProductDetailPage extends StatelessWidget {
  const ProductDetailPage({super.key, required this.id});
  final String id;
  @override
  Widget build(BuildContext context) => ApiData(
    path: '/api/productos/${Uri.encodeComponent(id)}',
    builder: (context, data) {
      final ui = CorteScope.of(context),
          p = mapOf(data['ficha']),
          row = mapOf(data['fila']),
          extended = mapOf(data['extendido']);
      final samples = rowsOf(data['muestras']),
          eligibility = mapOf(extended['muestra']);
      final info = Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(
            productName(p.isEmpty ? row : p),
            style: Theme.of(context).textTheme.headlineMedium,
          ),
          const SizedBox(height: 14),
          if (textOf(row['tienda_nombre']).isNotEmpty)
            TextButton.icon(
              onPressed: textOf(row['tienda_key']).isEmpty
                  ? null
                  : () => ui.go(
                      '/tiendas/${Uri.encodeComponent(textOf(row['tienda_key']))}',
                    ),
              icon: const Icon(Icons.storefront_outlined, size: 18),
              label: Text(textOf(row['tienda_nombre'])),
            ),
          if (p.isNotEmpty) ...[
            const SizedBox(height: 15),
            Text(
              salePrice(p),
              style: TextStyle(
                fontSize: useDesktopWorkspace(context) ? 26 : 30,
                fontWeight: useDesktopWorkspace(context)
                    ? FontWeight.w700
                    : FontWeight.w800,
                letterSpacing: -.7,
              ),
            ),
            const SizedBox(height: 3),
            Text(
              'Precio de venta',
              style: TextStyle(color: context.corte.muted, fontSize: 12),
            ),
            const SizedBox(height: 18),
            DefinitionRow(
              'Comisión del plan actual',
              percent(p['comision_bp']),
            ),
            DefinitionRow(
              'Comisión por venta',
              p['comision_por_venta_centavos'] == null
                  ? '—'
                  : money(p['comision_por_venta_centavos'], decimals: true),
            ),
          ],
          if (samples.isNotEmpty) ...[
            const SizedBox(height: 10),
            Container(
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                color: context.corte.rose,
                borderRadius: BorderRadius.circular(8),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'TU MUESTRA',
                    style: TextStyle(
                      fontSize: 11,
                      fontWeight: FontWeight.w800,
                      color: context.corte.action,
                      letterSpacing: 1,
                    ),
                  ),
                  const SizedBox(height: 7),
                  Text(
                    textOf(samples.first['variante'], 'Variante no informada'),
                    style: const TextStyle(fontWeight: FontWeight.w700),
                  ),
                  const SizedBox(height: 8),
                  TextButton(
                    onPressed: () => ui.go(
                      '/muestras/m/${Uri.encodeComponent(textOf(samples.first['application_id']))}',
                    ),
                    child: const Text('Ver muestra y avance'),
                  ),
                ],
              ),
            ),
          ],
          if (textOf(data['categoria_ruta']).isNotEmpty) ...[
            const SizedBox(height: 18),
            Text(
              textOf(data['categoria_ruta']),
              style: TextStyle(color: context.corte.muted, fontSize: 12),
            ),
          ],
          if (textOf(p['enlace']).isNotEmpty) ...[
            const SizedBox(height: 20),
            OutlinedButton.icon(
              onPressed: () => openPublicLink(context, textOf(p['enlace'])),
              icon: const Icon(Icons.open_in_new_rounded, size: 18),
              label: const Text('Abrir en TikTok Shop'),
            ),
          ],
        ],
      );
      return ListView(
        padding: pagePadding(context),
        children: [
          PageTitle(
            'Ficha del producto',
            back: () {
              if (!ui.back()) ui.go('/productos');
            },
          ),
          LayoutBuilder(
            builder: (context, limits) {
              final gallery = ProductGallery(
                productId: id,
                photos: productPhotos(data),
              );
              return limits.maxWidth > 850
                  ? Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Expanded(flex: 5, child: gallery),
                        const SizedBox(width: 40),
                        Expanded(flex: 5, child: info),
                      ],
                    )
                  : Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [gallery, const SizedBox(height: 24), info],
                    );
            },
          ),
          if (eligibility.isNotEmpty) ...[
            const SectionHeading(
              'Colores y tallas',
              subtitle:
                  'Variantes informadas por TikTok. Tu muestra recibida conserva su variante.',
            ),
            _SkuExplorer(key: ValueKey(id), eligibility: eligibility),
          ],
          ProductEvidence(
            productId: id,
            extended: extended,
            openOriginal: textOf(p['enlace']).isEmpty
                ? null
                : () => openPublicLink(context, textOf(p['enlace'])),
          ),
          if (row.isNotEmpty) ...[
            const SectionHeading('Tus resultados con este producto'),
            MetricStrip([
              ('Comisión estimada', money(row['comision_estimada_centavos'])),
              ('Ventas generadas', money(row['ventas_centavos'])),
              ('Pedidos válidos', integer(row['pedidos_validos'])),
              ('Unidades', integer(row['unidades'])),
            ]),
          ],
          if (rowsOf(data['serie']).isNotEmpty) ...[
            const SectionHeading('Comisión estimada por mes'),
            MiniBars(rowsOf(data['serie'])),
          ],
          const SectionHeading('Videos de este producto'),
          if (rowsOf(data['videos']).isEmpty)
            const EmptyState('Aún no hay videos vinculados')
          else
            for (final v in rowsOf(data['videos'])) VideoRow(video: v),
          if (extended.isNotEmpty) _ExtendedProduct(extended: extended),
          NotesPanel(entidad: 'producto', entidadId: id),
        ],
      );
    },
  );
}

class _SkuExplorer extends StatefulWidget {
  const _SkuExplorer({super.key, required this.eligibility});
  final Map<String, dynamic> eligibility;
  @override
  State<_SkuExplorer> createState() => _SkuExplorerState();
}

class _SkuExplorerState extends State<_SkuExplorer> {
  String? _color;
  @override
  Widget build(BuildContext context) {
    final skus = rowsOf(widget.eligibility['skus']);
    String? colorOf(Map<String, dynamic> sku) {
      for (final p in rowsOf(sku['propiedades'])) {
        if (textOf(p['nombre']).toLowerCase() == 'color') {
          return textOf(p['valor']);
        }
      }
      return null;
    }

    final colors = skus
        .map(colorOf)
        .whereType<String>()
        .where((v) => v.isNotEmpty)
        .toSet()
        .toList();
    final filtered = skus
        .where((s) => _color == null || colorOf(s) == _color)
        .toList();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          textOf(widget.eligibility['estado_texto']),
          style: TextStyle(color: context.corte.muted),
        ),
        if (colors.isNotEmpty) ...[
          const SizedBox(height: 12),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              ChoiceChip(
                label: const Text('Todos los colores'),
                selected: _color == null,
                onSelected: (_) => setState(() => _color = null),
              ),
              for (final c in colors)
                ChoiceChip(
                  label: Text(c),
                  selected: _color == c,
                  onSelected: (_) => setState(() => _color = c),
                ),
            ],
          ),
        ],
        const SizedBox(height: 10),
        for (final s in filtered)
          Container(
            padding: const EdgeInsets.symmetric(vertical: 12),
            decoration: BoxDecoration(
              border: Border(bottom: BorderSide(color: context.corte.line)),
            ),
            child: Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        textOf(
                          s['variante'],
                          'Variante ${textOf(s['sku_id'])}',
                        ),
                        style: const TextStyle(fontWeight: FontWeight.w600),
                      ),
                      if (s['disponible'] == false &&
                          textOf(s['motivo_texto']).isNotEmpty)
                        Text(
                          textOf(s['motivo_texto']),
                          style: TextStyle(
                            color: context.corte.muted,
                            fontSize: 12,
                          ),
                        ),
                    ],
                  ),
                ),
                const SizedBox(width: 14),
                Text(
                  s['precio_centavos'] == null
                      ? '—'
                      : money(s['precio_centavos'], decimals: true),
                ),
              ],
            ),
          ),
        if (skus.isEmpty)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 18),
            child: Text(
              'No hay variantes disponibles en esta respuesta de TikTok.',
              style: TextStyle(color: context.corte.muted),
            ),
          ),
      ],
    );
  }
}

class _ExtendedProduct extends StatelessWidget {
  const _ExtendedProduct({required this.extended});
  final Map<String, dynamic> extended;
  @override
  Widget build(BuildContext context) {
    final vitr = mapOf(extended['vitrina']),
        commission = mapOf(extended['comision_real']),
        origin = mapOf(extended['origen_ventas']);
    return Padding(
      padding: const EdgeInsets.only(top: 24),
      child: Column(
        children: [
          if (vitr.isNotEmpty)
            ExpansionTile(
              title: const Text('Información de tu vitrina'),
              tilePadding: EdgeInsets.zero,
              children: [
                DefinitionRow(
                  'Inventario',
                  vitr['con_existencias'] == null
                      ? 'No informado'
                      : vitr['con_existencias'] == true
                      ? 'Con existencias'
                      : 'Sin existencias',
                ),
                if (vitr['precio_venta_min_centavos'] != null)
                  DefinitionRow(
                    'Precio del vendedor',
                    money(vitr['precio_venta_min_centavos'], decimals: true),
                  ),
                if (vitr['precio_plataforma_min_centavos'] != null)
                  DefinitionRow(
                    'Precio con descuento de plataforma',
                    money(
                      vitr['precio_plataforma_min_centavos'],
                      decimals: true,
                    ),
                  ),
                if (vitr['precio_lista_min_centavos'] != null)
                  DefinitionRow(
                    'Precio de lista',
                    money(vitr['precio_lista_min_centavos'], decimals: true),
                  ),
              ],
            ),
          if (commission.isNotEmpty)
            ExpansionTile(
              title: const Text('Comisiones en tus ventas'),
              tilePadding: EdgeInsets.zero,
              children: [
                for (final c in rowsOf(commission['por_tasa']))
                  DefinitionRow(
                    '${percent(c['comision_bp'])} · ${integer(c['lineas'])} líneas',
                    money(c['comision_estimada_centavos']),
                  ),
              ],
            ),
          if (rowsOf(extended['planes_dirigidos']).isNotEmpty)
            ExpansionTile(
              title: const Text('Colaboraciones dirigidas'),
              tilePadding: EdgeInsets.zero,
              children: [
                for (final c in rowsOf(extended['planes_dirigidos']))
                  ListTile(
                    contentPadding: EdgeInsets.zero,
                    title: Text(textOf(c['nombre'], 'Colaboración')),
                    subtitle: Text(
                      '${textOf(c['tienda_nombre'])} · ${textOf(c['estado_texto'])}',
                    ),
                    trailing: Text(percent(c['comision_bp'])),
                  ),
              ],
            ),
          if (origin.isNotEmpty || extended['origen_ventas_aviso'] != null)
            ExpansionTile(
              title: const Text('Origen de tus ventas'),
              tilePadding: EdgeInsets.zero,
              children: [
                if (extended['origen_ventas_aviso'] == 'sin_permiso')
                  const InlineNotice(
                    text:
                        'Origen de cada venta: requiere un permiso extra en Partner Center.',
                  ),
                for (final o in rowsOf(origin['por_tipo_contenido']))
                  DefinitionRow(
                    textOf(o['texto']),
                    '${integer(o['lineas'])} líneas',
                  ),
                for (final o in rowsOf(origin['por_tipo_enlace']))
                  DefinitionRow(
                    textOf(o['texto']),
                    '${integer(o['lineas'])} líneas',
                  ),
              ],
            ),
          if (rowsOf(mapOf(extended['parecidos'])['items']).isNotEmpty)
            ExpansionTile(
              title: const Text('Parecidos por palabras del título'),
              tilePadding: EdgeInsets.zero,
              children: [
                for (final p in rowsOf(mapOf(extended['parecidos'])['items']))
                  ListTile(
                    contentPadding: EdgeInsets.zero,
                    leading: CortePhoto(
                      textOf(p['imagen']),
                      width: 48,
                      height: 52,
                    ),
                    title: Text(
                      productName(p),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                    ),
                    subtitle: Text(salePrice(p)),
                    onTap: p['tiene_ficha'] == true
                        ? () => CorteScope.of(context).go(
                            '/productos/${Uri.encodeComponent(textOf(p['product_id']))}',
                          )
                        : textOf(p['enlace']).isEmpty
                        ? null
                        : () => openPublicLink(context, textOf(p['enlace'])),
                  ),
              ],
            ),
        ],
      ),
    );
  }
}

String videoTitle(Map<String, dynamic> v) => textOf(
  v['descripcion'],
  textOf(v['titulo'], 'Video ${textOf(v['content_id'])}'),
);
String? videoCover(Map<String, dynamic> v) {
  final id = textOf(v['content_id']);
  for (final key in ['portada', 'miniatura']) {
    if (key == 'miniatura' && v['miniatura_origen'] == 'producto') continue;
    final value = textOf(v[key]), uri = Uri.tryParse(textOf(v[key]));
    if (value.isNotEmpty && uri != null && uri.path == '/img/v/$id') {
      return value;
    }
  }
  return null;
}

class VideoRow extends StatelessWidget {
  const VideoRow({super.key, required this.video});
  final Map<String, dynamic> video;
  @override
  Widget build(BuildContext context) => InkWell(
    onTap: () => CorteScope.of(
      context,
    ).go('/videos/${Uri.encodeComponent(textOf(video['content_id']))}'),
    child: Container(
      padding: EdgeInsets.symmetric(
        vertical: useDesktopWorkspace(context) ? 12 : 17,
      ),
      decoration: BoxDecoration(
        border: Border(bottom: BorderSide(color: context.corte.line)),
      ),
      child: Row(
        children: [
          CortePhoto(
            videoCover(video),
            width: useDesktopWorkspace(context) ? 56 : 70,
            height: useDesktopWorkspace(context) ? 76 : 96,
            video: true,
            label: 'Portada de ${videoTitle(video)}',
          ),
          const SizedBox(width: 16),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  videoTitle(video),
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(fontWeight: FontWeight.w700),
                ),
                const SizedBox(height: 8),
                Text(
                  video['vistas'] == null
                      ? 'Vistas no disponibles'
                      : '${integer(video['vistas'])} vistas',
                  style: TextStyle(color: context.corte.muted, fontSize: 12),
                ),
                const SizedBox(height: 6),
                if (video['pedidos_validos'] != null)
                  Text(
                    '${integer(video['pedidos_validos'])} pedidos válidos',
                    style: TextStyle(color: context.corte.muted, fontSize: 12),
                  ),
              ],
            ),
          ),
          const SizedBox(width: 12),
          Text(
            money(video['comision_estimada_centavos']),
            style: const TextStyle(fontWeight: FontWeight.w800),
          ),
        ],
      ),
    ),
  );
}

class VideosPage extends StatefulWidget {
  const VideosPage({super.key, this.todos = false});

  /// rev. 6 · `?segmento=todos`: la pestaña «Todos» (catálogo), si el hub la tiene.
  final bool todos;
  @override
  State<VideosPage> createState() => _VideosPageState();
}

class _VideosPageState extends State<VideosPage> {
  String _search = '', _order = 'comision_estimada_centavos';
  bool _sinCatalogo = false;

  // «Con ventas» abre como siempre, sin esperar a nadie: la sesión solo decide si se pintan las pestañas
  // (VideoTabsSiHayCatalogo). «Todos» pide el catálogo directamente; un hub sin él responde 404 y se vuelve aquí.
  @override
  Widget build(BuildContext context) {
    if (widget.todos && !_sinCatalogo) {
      return VideoCatalogView(
        onFallback: () {
          if (mounted) setState(() => _sinCatalogo = true);
        },
      );
    }
    return _conVentas(context, !_sinCatalogo);
  }

  Widget _conVentas(BuildContext context, bool pestanas) => ApiData(
    path: '/api/analitica/videos',
    query: const {'limite': 1000},
    builder: (context, data) {
      final videos = rowsOf(data['items'])
          .where(
            (v) => '${videoTitle(v)} ${v['content_id']}'.toLowerCase().contains(
              _search.toLowerCase(),
            ),
          )
          .toList();
      videos.sort((a, b) => intOf(b[_order]).compareTo(intOf(a[_order])));
      return ListView.builder(
        padding: pagePadding(context),
        itemCount: videos.length + 1,
        itemBuilder: (context, i) => i > 0
            ? VideoRow(video: videos[i - 1])
            : Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  PageTitle(
                    'Videos',
                    subtitle:
                        '${data['total'] ?? rowsOf(data['items']).length} videos de tu cuenta',
                  ),
                  const SalesNavigation(selected: 'videos'),
                  if (pestanas) const VideoTabsSiHayCatalogo(),
                  const SizedBox(height: 20),
                  TextField(
                    decoration: const InputDecoration(
                      labelText: 'Buscar video',
                      prefixIcon: Icon(Icons.search_rounded),
                    ),
                    onChanged: (v) => setState(() => _search = v),
                  ),
                  const SizedBox(height: 12),
                  Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    children: [
                      for (final o in [
                        ('comision_estimada_centavos', 'Comisión'),
                        ('vistas', 'Vistas'),
                        ('publicado_at', 'Recientes'),
                        ('pedidos_validos', 'Pedidos'),
                      ])
                        ChoiceChip(
                          label: Text(o.$2),
                          selected: _order == o.$1,
                          onSelected: (_) => setState(() => _order = o.$1),
                        ),
                    ],
                  ),
                  const SizedBox(height: 16),
                  if (videos.isEmpty)
                    const EmptyState('No hay videos para esta búsqueda'),
                ],
              ),
      );
    },
  );
}

class VideoDetailPage extends StatelessWidget {
  const VideoDetailPage({super.key, required this.id, this.desdeTodos = false});
  final String id;

  /// rev. 6 · Abierto desde «Todos»: sin historial, «Volver» lleva a esa pestaña.
  final bool desdeTodos;

  void _volver(BuildContext context) {
    final ui = CorteScope.of(context);
    if (!ui.back()) ui.go(desdeTodos ? videosTodos : videosConVentas);
  }

  // rev. 6 · Un video sin ventas no está en /api/videos (404): el detalle sale del catálogo. Un hub sin catálogo
  // también responde 404 ahí y queda el «No encontramos este video» de siempre.
  @override
  Widget build(BuildContext context) => ApiData(
    path: '/api/videos/${Uri.encodeComponent(id)}',
    errorBuilder: (context, error) =>
        error is ErrorApi && error.codigo == 'no_encontrado'
        ? CatalogVideoDetail(id: id, onBack: () => _volver(context))
        : null,
    builder: (context, data) =>
        VideoSalesDetail(data: data, id: id, onBack: () => _volver(context)),
  );
}

/// Detalle de un video con ventas (GET /api/videos/{id}, o el bloque `ventas` del catálogo).
class VideoSalesDetail extends StatelessWidget {
  const VideoSalesDetail({
    super.key,
    required this.data,
    required this.id,
    required this.onBack,
  });
  final Map<String, dynamic> data;
  final String id;
  final VoidCallback onBack;
  @override
  Widget build(BuildContext context) {
    final v = mapOf(data['video']);
    return ListView(
      padding: pagePadding(context),
      children: [
        PageTitle('Detalle del video', back: onBack),
        LayoutBuilder(
          builder: (context, limits) {
            final cover = CortePhoto(
              videoCover(v),
              width: limits.maxWidth > 700 ? 235 : 200,
              height: 320,
              video: true,
              fit: BoxFit.contain,
              label: 'Portada real del video',
            );
            final info = Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text(
                  videoTitle(v),
                  style: Theme.of(context).textTheme.headlineMedium,
                ),
                const SizedBox(height: 12),
                if (v['publicado_at'] != null)
                  Text(
                    'Publicado el ${date(v['publicado_at'])}',
                    style: TextStyle(color: context.corte.muted),
                  ),
                const SizedBox(height: 18),
                MetricStrip([
                  (
                    'Vistas',
                    v['vistas'] == null ? '—' : integer(v['vistas']),
                  ),
                  (
                    'Me gusta',
                    v['me_gusta'] == null && v['likes'] == null
                        ? '—'
                        : integer(v['likes'] ?? v['me_gusta']),
                  ),
                  (
                    'Comentarios',
                    v['comentarios'] == null
                        ? '—'
                        : integer(v['comentarios']),
                  ),
                  (
                    'Compartidos',
                    v['compartidos'] == null
                        ? '—'
                        : integer(v['compartidos']),
                  ),
                ]),
                const SizedBox(height: 20),
                Align(
                  alignment: Alignment.centerLeft,
                  child: FilledButton.icon(
                    onPressed: textOf(v['enlace']).isEmpty
                        ? null
                        : () => openPublicLink(context, textOf(v['enlace'])),
                    icon: const Icon(Icons.play_arrow_rounded),
                    label: const Text('Ver video en TikTok'),
                  ),
                ),
              ],
            );
            return limits.maxWidth > 700
                ? Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      cover,
                      const SizedBox(width: 32),
                      Expanded(child: info),
                    ],
                  )
                : Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Center(child: cover),
                      const SizedBox(height: 24),
                      info,
                    ],
                  );
          },
        ),
        const SectionHeading('Resultados de ventas'),
        MetricStrip([
          ('Comisión estimada', money(v['comision_estimada_centavos'])),
          ('Ventas generadas', money(v['ventas_centavos'])),
          ('Pedidos válidos', integer(v['pedidos_validos'])),
          ('Unidades', integer(v['unidades'])),
        ]),
        if (rowsOf(data['serie']).isNotEmpty) ...[
          const SectionHeading('Comisión estimada por mes'),
          MiniBars(rowsOf(data['serie'])),
        ],
        const SectionHeading('Productos del video'),
        for (final p in rowsOf(data['productos'])) ProductRow(product: p),
        if (rowsOf(data['productos']).isEmpty)
          const EmptyState('Todavía no hay productos vinculados'),
        NotesPanel(entidad: 'video', entidadId: id),
      ],
    );
  }
}

class SalesNavigation extends StatelessWidget {
  const SalesNavigation({super.key, required this.selected});
  final String selected;
  @override
  Widget build(BuildContext context) => SingleChildScrollView(
    scrollDirection: Axis.horizontal,
    child: Row(
      children: [
        for (final item in [
          ('ventas', 'Resumen'),
          ('ordenes', 'Pedidos'),
          ('videos', 'Videos'),
          ('productos', 'Productos'),
        ])
          Padding(
            padding: const EdgeInsets.only(right: 8),
            child: ChoiceChip(
              label: Text(item.$2),
              selected: selected == item.$1,
              onSelected: (_) => CorteScope.of(context).go('/${item.$1}'),
            ),
          ),
      ],
    ),
  );
}

class SalesPage extends StatefulWidget {
  const SalesPage({super.key});
  @override
  State<SalesPage> createState() => _SalesPageState();
}

class _SalesPageState extends State<SalesPage> {
  String _period = '30d';
  @override
  Widget build(BuildContext context) => ApiData(
    path: '/api/dashboard',
    query: {'periodo': _period},
    builder: (context, data) {
      final k = mapOf(data['kpis']), period = mapOf(data['periodo']);
      return ListView(
        padding: pagePadding(context),
        children: [
          PageTitle(
            'Ventas',
            subtitle: '${textOf(period['desde'])} – ${textOf(period['hasta'])}',
          ),
          const SalesNavigation(selected: 'ventas'),
          const SizedBox(height: 20),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              for (final p in [
                ('7d', '7 días'),
                ('30d', '30 días'),
                ('90d', '90 días'),
                ('12m', '12 meses'),
                ('todo', 'Todo'),
              ])
                ChoiceChip(
                  label: Text(p.$2),
                  selected: _period == p.$1,
                  onSelected: (_) => setState(() => _period = p.$1),
                ),
            ],
          ),
          const SizedBox(height: 30),
          MetricStrip([
            ('Comisión total', money(k['comision_total_centavos'])),
            ('Ventas generadas', money(k['ventas_centavos'])),
            ('Pedidos válidos', integer(k['pedidos_validos'])),
            ('Unidades', integer(k['unidades'])),
          ]),
          const SizedBox(height: 24),
          DefinitionRow(
            'Comisión liquidada',
            money(k['comision_liquidada_centavos'], decimals: true),
          ),
          DefinitionRow(
            'Por liquidar',
            money(k['comision_por_liquidar_centavos'], decimals: true),
          ),
          DefinitionRow(
            'Comisión retenida',
            money(k['comision_retenida_centavos'], decimals: true),
          ),
          const SectionHeading(
            'Comisión estimada',
            subtitle:
                'Estimación por fecha de venta; la comisión liquidada puede cambiar.',
          ),
          MiniBars(rowsOf(mapOf(data['serie'])['puntos'])),
          const SectionHeading('Videos con mayor comisión'),
          for (final v in rowsOf(data['top_videos']).take(5))
            VideoRow(video: v),
          const SectionHeading('Productos con mayor comisión'),
          for (final p in rowsOf(data['top_productos']).take(5))
            ProductRow(product: p),
        ],
      );
    },
  );
}

class OrdersPage extends StatefulWidget {
  const OrdersPage({super.key});
  @override
  State<OrdersPage> createState() => _OrdersPageState();
}

class _OrdersPageState extends State<OrdersPage> {
  int _page = 1;
  String _state = '', _search = '';
  late final String _since = DateTime.now()
      .subtract(const Duration(days: 29))
      .toIso8601String()
      .substring(0, 10);
  @override
  Widget build(BuildContext context) => ApiData(
    path: '/api/ordenes',
    query: {
      'desde': _since,
      'pagina': _page,
      'por_pagina': 30,
      if (_state.isNotEmpty) 'estado': _state,
      if (_search.isNotEmpty) 'q': _search,
    },
    builder: (context, data) {
      final orders = rowsOf(data['items']), total = intOf(data['total']);
      return ListView(
        padding: pagePadding(context),
        children: [
          PageTitle(
            'Pedidos',
            subtitle: 'Últimos 30 días · ${integer(total)} pedidos',
          ),
          const SalesNavigation(selected: 'ordenes'),
          const SizedBox(height: 20),
          TextField(
            decoration: const InputDecoration(
              labelText: 'Buscar pedido o producto',
              prefixIcon: Icon(Icons.search_rounded),
              hintText: 'Escribe y presiona Enter',
            ),
            onSubmitted: (v) => setState(() {
              _search = v.trim();
              _page = 1;
            }),
          ),
          const SizedBox(height: 12),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              for (final s in [
                ('', 'Todos'),
                ('SETTLED', 'Liquidados'),
                ('To-SETTLE', 'Por liquidar'),
                ('REFUNDED', 'Reembolsados'),
              ])
                ChoiceChip(
                  label: Text(s.$2),
                  selected: _state == s.$1,
                  onSelected: (_) => setState(() {
                    _state = s.$1;
                    _page = 1;
                  }),
                ),
            ],
          ),
          const SizedBox(height: 18),
          for (final order in orders) _OrderTile(order: order),
          if (orders.isEmpty)
            const EmptyState('No hay pedidos con estos filtros'),
          const SizedBox(height: 20),
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              OutlinedButton.icon(
                onPressed: _page > 1 ? () => setState(() => _page--) : null,
                icon: const Icon(Icons.chevron_left),
                label: const Text('Anterior'),
              ),
              Text('Página $_page'),
              OutlinedButton.icon(
                onPressed: _page * 30 < total
                    ? () => setState(() => _page++)
                    : null,
                icon: const Icon(Icons.chevron_right),
                label: const Text('Siguiente'),
              ),
            ],
          ),
        ],
      );
    },
  );
}

class _OrderTile extends StatelessWidget {
  const _OrderTile({required this.order});
  final Map<String, dynamic> order;
  @override
  Widget build(BuildContext context) => ExpansionTile(
    tilePadding: EdgeInsets.zero,
    childrenPadding: const EdgeInsets.only(bottom: 20),
    title: Text(
      'Pedido ${textOf(order['order_id'])}',
      style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700),
    ),
    subtitle: Padding(
      padding: const EdgeInsets.only(top: 6),
      child: Text(
        '${textOf(order['estado_etiqueta'])} · ${textOf(order['fecha'])}',
      ),
    ),
    children: [
      DefinitionRow('Total', money(order['total_centavos'], decimals: true)),
      DefinitionRow(
        'Comisión estimada',
        money(order['comision_estimada_centavos'], decimals: true),
      ),
      DefinitionRow(
        'Comisión real',
        money(order['comision_real_centavos'], decimals: true),
      ),
      for (final l in rowsOf(order['lineas']))
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 10),
          child: Column(
            children: [
              Row(
                children: [
                  CortePhoto(textOf(l['imagen']), width: 52, height: 58),
                  const SizedBox(width: 12),
                  Expanded(child: Text(textOf(l['producto'], 'Producto'))),
                  Text('× ${integer(l['cantidad'])}'),
                ],
              ),
              if (l['isr_centavos'] != null)
                DefinitionRow('ISR', money(l['isr_centavos'], decimals: true)),
              if (l['iva_centavos'] != null)
                DefinitionRow('IVA', money(l['iva_centavos'], decimals: true)),
              if (l['es_carrusel'] == true)
                const InlineNotice(
                  text: 'Video carrusel: puede tener una comisión menor.',
                ),
            ],
          ),
        ),
      NotesPanel(entidad: 'orden', entidadId: textOf(order['order_id'])),
    ],
  );
}
