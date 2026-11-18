// Catálogo de videos (contrato rev. 6): pestañas «Con ventas | Todos», la lista «Todos» con los videos publicados en la
// cuenta de TikTok (Display API) y los que tienen ventas, y el detalle de un video sin ventas. Nunca se inventa una
// cifra: un video sin pedidos dice «Sin ventas» y desde cuándo se puede afirmar, nunca «$0 · 0 pedidos».
import 'package:flutter/material.dart';
import '../app.dart';
import '../domain/domain.dart';
import 'catalog.dart';
import 'desktop.dart';
import 'editors.dart';
import 'format.dart';
import 'theme.dart';
import 'widgets.dart';
import 'work.dart';

const videosConVentas = '/videos';
const videosTodos = '/videos?segmento=todos';

/// Día de México (UTC−6, sin horario de verano) de un instante en segundos.
DateTime _diaMexico(num segundos) => DateTime.fromMillisecondsSinceEpoch(
  (segundos.round() - 21600) * 1000,
  isUtc: true,
);

/// Fecha 'YYYY-MM-DD' en hora de México de un instante en segundos.
String fechaMexico(num segundos) {
  final d = _diaMexico(segundos);
  String dos(int x) => x.toString().padLeft(2, '0');
  return '${d.year}-${dos(d.month)}-${dos(d.day)}';
}

const _meses = [
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

/// '14 oct' en el año en curso (México) y '14 oct 2025' en otro, como la web.
String _corta(DateTime d, DateTime? ahora) {
  final hoy = _diaMexico((ahora ?? DateTime.now()).millisecondsSinceEpoch / 1000);
  return '${d.day} ${_meses[d.month - 1]}${d.year == hoy.year ? '' : ' ${d.year}'}';
}

/// '2026-03-01' → '1 mar' (con el año si no es el actual).
String fechaCortaDe(String fecha, {DateTime? ahora}) {
  final d = DateTime.tryParse(fecha);
  return d == null ? fecha : _corta(d, ahora);
}

/// Instante en segundos → '1 mar' en hora de México (con el año si no es el actual).
String fechaDeInstante(num segundos, {DateTime? ahora}) =>
    _corta(_diaMexico(segundos), ahora);

/// Nombre de un video del catálogo con la misma regla que la lista con ventas.
String catalogTitle(Map<String, dynamic> v) {
  final ventas = mapOf(v['ventas']);
  return videoTitle({
    'content_id': v['content_id'],
    'descripcion': v['descripcion'] ?? ventas['descripcion'],
    'titulo': ventas['titulo'],
  });
}

bool tieneVentas(Map<String, dynamic> v) => v['ventas'] is Map;

/// '1 pedido' · '2 pedidos' (pedidos válidos de toda la vida del video).
String pedidosTexto(Object? n) =>
    '${integer(n)} ${intOf(n) == 1 ? 'pedido' : 'pedidos'}';

/// El mismo orden que el hub: sin el dato, al final; empates por ID.
List<Map<String, dynamic>> sortCatalog(
  List<Map<String, dynamic>> rows,
  String order,
) {
  int porId(Map<String, dynamic> a, Map<String, dynamic> b) =>
      textOf(a['content_id']).compareTo(textOf(b['content_id']));
  int ultimaVenta(Map<String, dynamic> v) {
    if (!tieneVentas(v)) return -1;
    final d = DateTime.tryParse(textOf(mapOf(v['ventas'])['ultima_venta']));
    return d == null ? 0 : d.millisecondsSinceEpoch ~/ 1000;
  }

  int sinDato(Object? a, Object? b) =>
      (a == null ? 1 : 0) - (b == null ? 1 : 0);
  int comision(Map<String, dynamic> v) =>
      intOf(mapOf(v['ventas'])['comision_estimada_centavos']);
  int porVistas(Map<String, dynamic> a, Map<String, dynamic> b) {
    final vacio = sinDato(a['vistas'], b['vistas']);
    if (vacio != 0) return vacio;
    final cifra = intOf(b['vistas']).compareTo(intOf(a['vistas']));
    return cifra != 0 ? cifra : porId(a, b);
  }

  int porComision(Map<String, dynamic> a, Map<String, dynamic> b) {
    final vacio = (tieneVentas(a) ? 0 : 1) - (tieneVentas(b) ? 0 : 1);
    if (vacio != 0) return vacio;
    final cifra = comision(b).compareTo(comision(a));
    return cifra != 0 ? cifra : porId(a, b);
  }

  int porPublicado(Map<String, dynamic> a, Map<String, dynamic> b) {
    final vacio = sinDato(a['publicado_at'], b['publicado_at']);
    if (vacio != 0) return vacio;
    final fecha = intOf(b['publicado_at']).compareTo(intOf(a['publicado_at']));
    if (fecha != 0) return fecha;
    final venta = ultimaVenta(b).compareTo(ultimaVenta(a));
    return venta != 0 ? venta : porId(a, b);
  }

  final copia = [...rows];
  copia.sort(
    order == 'vistas'
        ? porVistas
        : order == 'comision'
        ? porComision
        : porPublicado,
  );
  return copia;
}

/// Qué se puede afirmar de un video sin pedidos; null si tiene ventas. Los pedidos guardados empiezan en [pedidosDesde].
(String, String)? noSalesText(
  Map<String, dynamic> v,
  String? pedidosDesde, {
  DateTime? ahora,
}) {
  if (tieneVentas(v)) return null;
  if (pedidosDesde == null || pedidosDesde.isEmpty) {
    return ('Sin ventas', 'registradas');
  }
  final publicado = v['publicado_at'];
  if (publicado is! num || fechaMexico(publicado).compareTo(pedidosDesde) < 0) {
    return ('Sin ventas', 'desde el ${fechaCortaDe(pedidosDesde, ahora: ahora)}');
  }
  return ('Sin ventas', 'desde que se publicó');
}

/// Texto de «Ventas» en el detalle de un video sin pedidos.
String noSalesDetail(
  Map<String, dynamic> v,
  String? pedidosDesde, {
  DateTime? ahora,
}) {
  final t = noSalesText(v, pedidosDesde, ahora: ahora);
  if (t == null) return '';
  if (t.$2 == 'registradas') {
    return 'Corte todavía no tiene pedidos guardados, así que este video no tiene ventas registradas.';
  }
  if (t.$2 == 'desde que se publicó') {
    return 'Este video aún no tiene ventas desde que se publicó.';
  }
  return 'Sin ventas desde el ${fechaCortaDe(pedidosDesde!, ahora: ahora)}. Corte guarda tus pedidos desde ese día: de antes no se puede saber.';
}

/// Aviso de «Todos» cuando el hub solo puede listar los videos con ventas.
String? catalogNotice(Object? display) {
  if (display is! Map) {
    return 'Conecta las métricas de TikTok para ver también los videos que todavía no venden.';
  }
  final misma = display['misma_cuenta'];
  if (misma == false) {
    return 'La cuenta de las métricas de TikTok no es la de tu tienda: solo se muestran tus videos con ventas.';
  }
  if (misma == null) {
    return 'Aún no se puede comprobar que la cuenta de las métricas de TikTok sea la de tu tienda: por ahora solo se muestran tus videos con ventas.';
  }
  return null;
}

/// Estado de publicación que se rotula ('Ya no es público' / 'Sin confirmar'); null si no hace falta.
String? publicationLabel(Object? publicacion) => switch (publicacion) {
  'no_publico' => 'Ya no es público',
  'no_confirmado' => 'Sin confirmar',
  _ => null,
};

/// Pestañas «Con ventas | Todos» con el subrayado coral de Muestras. Cambiar no apila historial.
class VideoTabs extends StatelessWidget {
  const VideoTabs({super.key, required this.todos});
  final bool todos;
  @override
  Widget build(BuildContext context) {
    final escritorio = useDesktopWorkspace(context);
    Widget pestana((String, String, bool) tab) => Semantics(
      selected: tab.$3,
      button: true,
      child: InkWell(
        onTap: tab.$3 ? null : () => CorteScope.of(context).replace(tab.$1),
        child: Container(
          constraints: const BoxConstraints(minHeight: 48),
          alignment: Alignment.center,
          padding: const EdgeInsets.symmetric(horizontal: 12),
          margin: EdgeInsets.only(right: escritorio ? 12 : 0),
          decoration: BoxDecoration(
            border: Border(
              bottom: BorderSide(
                color: tab.$3 ? CorteColors.coral : Colors.transparent,
                width: 3,
              ),
            ),
          ),
          child: Text(
            tab.$2,
            style: TextStyle(
              fontWeight: tab.$3 ? FontWeight.w600 : FontWeight.w500,
              color: tab.$3 ? context.corte.ink : context.corte.muted,
            ),
          ),
        ),
      ),
    );
    final tabs = [
      (videosConVentas, 'Con ventas', !todos),
      (videosTodos, 'Todos', todos),
    ];
    return Container(
      decoration: BoxDecoration(
        border: Border(bottom: BorderSide(color: context.corte.line)),
      ),
      child: Row(
        children: [
          for (final tab in tabs)
            escritorio ? pestana(tab) : Expanded(child: pestana(tab)),
        ],
      ),
    );
  }
}

/// Pestañas en «Con ventas» solo si el hub anuncia el catálogo. No retrasa la lista: la sesión se lee una vez por
/// cuenta y, mientras llega (o si falla), no se pinta nada.
class VideoTabsSiHayCatalogo extends StatefulWidget {
  const VideoTabsSiHayCatalogo({super.key});
  @override
  State<VideoTabsSiHayCatalogo> createState() => _VideoTabsSiHayCatalogoState();
}

class _VideoTabsSiHayCatalogoState extends State<VideoTabsSiHayCatalogo> {
  String? _cuenta;
  Future<JsonMap>? _sesion;
  @override
  Widget build(BuildContext context) {
    final repo = CorteScope.of(context).repo;
    final cuenta = '${repo.ownerScope}:${repo.cacheScope}';
    if (cuenta != _cuenta) {
      _cuenta = cuenta;
      _sesion = repo.get('/api/session');
    }
    return FutureBuilder<JsonMap>(
      future: _sesion,
      builder: (context, snapshot) {
        final conCatalogo =
            snapshot.hasData &&
            mapOf(snapshot.data!['capacidades'])['catalogo_videos'] == true;
        return conCatalogo
            ? const Padding(
                padding: EdgeInsets.only(top: 12),
                child: VideoTabs(todos: false),
              )
            : const SizedBox.shrink();
      },
    );
  }
}

class CatalogVideoRow extends StatelessWidget {
  const CatalogVideoRow({
    super.key,
    required this.video,
    this.pedidosDesde,
    this.conMetricas = false,
  });
  final Map<String, dynamic> video;
  final String? pedidosDesde;
  final bool conMetricas;
  @override
  Widget build(BuildContext context) {
    final v = video;
    final ventas = mapOf(v['ventas']);
    final sinVentas = noSalesText(v, pedidosDesde);
    final estado = publicationLabel(v['publicacion']);
    final muted = TextStyle(color: context.corte.muted, fontSize: 12);
    return InkWell(
      onTap: () => CorteScope.of(context).go(
        '/videos/${Uri.encodeComponent(textOf(v['content_id']))}?desde=todos',
      ),
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
              videoCover(v),
              width: useDesktopWorkspace(context) ? 56 : 70,
              height: useDesktopWorkspace(context) ? 76 : 96,
              video: true,
              label: 'Portada de ${catalogTitle(v)}',
            ),
            const SizedBox(width: 16),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    catalogTitle(v),
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(fontWeight: FontWeight.w700),
                  ),
                  const SizedBox(height: 8),
                  // «Sin confirmar» / «Ya no es público»: sus cifras son de antes de la última lectura y llevan su fecha.
                  if (v['vistas'] != null)
                    Text(
                      '${integer(v['vistas'])} vistas${estado != null && v['metricas_at'] is num ? ' al ${fechaDeInstante(v['metricas_at'] as num)}' : ''}',
                      style: muted,
                    )
                  else if (conMetricas)
                    Text('Sin cifras de TikTok', style: muted),
                  if (v['publicado_at'] is num) ...[
                    const SizedBox(height: 4),
                    Text(
                      'Publicado el ${fechaDeInstante(v['publicado_at'] as num)}',
                      style: muted,
                    ),
                  ],
                  if (estado != null) ...[
                    const SizedBox(height: 6),
                    StatusTag(estado, urgent: v['publicacion'] == 'no_publico'),
                  ],
                ],
              ),
            ),
            const SizedBox(width: 12),
            if (sinVentas == null)
              Column(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  Text(
                    money(ventas['comision_estimada_centavos']),
                    style: const TextStyle(fontWeight: FontWeight.w800),
                  ),
                  const SizedBox(height: 4),
                  Text(pedidosTexto(ventas['pedidos_validos']), style: muted),
                ],
              )
            else
              Column(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  Text(
                    sinVentas.$1,
                    style: TextStyle(
                      fontWeight: FontWeight.w700,
                      color: context.corte.muted,
                    ),
                  ),
                  const SizedBox(height: 4),
                  Text(sinVentas.$2, style: muted),
                ],
              ),
          ],
        ),
      ),
    );
  }
}

/// «Todos»: publicados en la cuenta de TikTok y con ventas (GET /api/catalogo/videos, una sola vez con todo).
class VideoCatalogView extends StatefulWidget {
  const VideoCatalogView({super.key, required this.onFallback});

  /// El hub anunció el catálogo pero respondió 404: la pantalla vuelve a «Con ventas».
  final VoidCallback onFallback;
  @override
  State<VideoCatalogView> createState() => _VideoCatalogViewState();
}

class _VideoCatalogViewState extends State<VideoCatalogView> {
  String _search = '', _order = 'publicado';
  bool _soloSinVentas = false;
  bool _avisado = false;
  int _intento = 0;
  final _busqueda = TextEditingController();

  @override
  void dispose() {
    _busqueda.dispose();
    super.dispose();
  }

  void _quitarFiltros() => setState(() {
    _busqueda.clear();
    _search = '';
    _soloSinVentas = false;
  });

  // `_intento` en la clave vuelve a pedir solo esta lista al reintentar (sin refrescar toda la app).
  @override
  Widget build(BuildContext context) => ApiData(
    key: ValueKey(_intento),
    path: '/api/catalogo/videos',
    query: const {'limite': 2000},
    errorBuilder: (context, error) {
      if (error is ErrorApi && error.codigo == 'no_encontrado') {
        // Una sola vez y sin tocar `widget` después: la pantalla cambia a «Con ventas» y esta vista se desmonta.
        if (!_avisado) {
          _avisado = true;
          final volver = widget.onFallback;
          WidgetsBinding.instance.addPostFrameCallback((_) => volver());
        }
        return const SizedBox.shrink();
      }
      return SingleChildScrollView(
        padding: pagePadding(context),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const PageTitle('Videos'),
            const SalesNavigation(selected: 'videos'),
            const SizedBox(height: 12),
            const VideoTabs(todos: true),
            EmptyState(
              'No pudimos mostrar todos tus videos',
              text: error is ErrorApi
                  ? error.mensaje
                  : 'Revisa tu conexión y vuelve a intentarlo.',
              action: Wrap(
                spacing: 12,
                runSpacing: 12,
                alignment: WrapAlignment.center,
                children: [
                  FilledButton.icon(
                    onPressed: () => setState(() => _intento++),
                    icon: const Icon(Icons.refresh_rounded),
                    label: const Text('Reintentar'),
                  ),
                  OutlinedButton(
                    onPressed: () =>
                        CorteScope.of(context).replace(videosConVentas),
                    child: const Text('Ver videos con ventas'),
                  ),
                ],
              ),
            ),
          ],
        ),
      );
    },
    builder: (context, data) {
      final todos = rowsOf(data['items']);
      final display = data['display'];
      final conMetricas = display is Map;
      final aviso = catalogNotice(display);
      final pedidosDesde = data['pedidos_desde'] is String
          ? data['pedidos_desde'] as String
          : null;
      final orden = _order == 'vistas' && !conMetricas ? 'publicado' : _order;
      final busqueda = _search.trim().toLowerCase();
      final sinVentas = todos.where((v) => !tieneVentas(v)).length;
      // Si ya no queda ninguno sin ventas (p. ej. otra cuenta en las métricas), el filtro deja de aplicar.
      final soloSinVentas = _soloSinVentas && sinVentas > 0;
      final videos = sortCatalog(
        todos
            .where((v) => !soloSinVentas || !tieneVentas(v))
            .where(
              (v) =>
                  busqueda.isEmpty ||
                  '${catalogTitle(v)} ${v['content_id']} ${mapOf(v['ventas'])['tienda_principal'] ?? ''}'
                      .toLowerCase()
                      .contains(busqueda),
            )
            .toList(),
        orden,
      );
      final total = intOf(data['total'], todos.length);
      return ListView.builder(
        padding: pagePadding(context),
        itemCount: videos.length + 1,
        itemBuilder: (context, i) => i > 0
            ? CatalogVideoRow(
                video: videos[i - 1],
                pedidosDesde: pedidosDesde,
                conMetricas: conMetricas,
              )
            : Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  PageTitle(
                    'Videos',
                    subtitle:
                        '${integer(total)} ${total == 1 ? 'video' : 'videos'} · ${aviso == null ? 'publicados y con ventas' : 'solo los que tienen ventas'}',
                  ),
                  const SalesNavigation(selected: 'videos'),
                  const SizedBox(height: 12),
                  const VideoTabs(todos: true),
                  if (aviso != null) ...[
                    const SizedBox(height: 16),
                    InlineNotice(text: aviso),
                  ],
                  const SizedBox(height: 20),
                  TextField(
                    controller: _busqueda,
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
                        ('publicado', 'Recientes'),
                        if (conMetricas) ('vistas', 'Vistas'),
                        ('comision', 'Comisión'),
                      ])
                        ChoiceChip(
                          label: Text(o.$2),
                          selected: orden == o.$1,
                          onSelected: (_) => setState(() => _order = o.$1),
                        ),
                      if (sinVentas > 0)
                        FilterChip(
                          label: Text('Sin ventas · ${integer(sinVentas)}'),
                          selected: soloSinVentas,
                          onSelected: (v) => setState(() => _soloSinVentas = v),
                        ),
                    ],
                  ),
                  if (todos.length < total) ...[
                    const SizedBox(height: 12),
                    Text(
                      'Se muestran los ${integer(todos.length)} videos más recientes de ${integer(total)}.',
                      style: TextStyle(color: context.corte.muted, fontSize: 12),
                    ),
                  ],
                  const SizedBox(height: 16),
                  if (todos.isEmpty)
                    EmptyState(
                      'Aún no hay videos',
                      text: display is! Map
                          ? 'Cuando un video venda, aparecerá aquí. Conecta las métricas de TikTok para ver también los que aún no venden.'
                          : aviso != null
                          ? 'Cuando un video venda, aparecerá aquí.'
                          : 'Cuando publiques un video o uno venda, aparecerá aquí.',
                    )
                  else if (videos.isEmpty)
                    EmptyState(
                      'No hay videos para esta búsqueda',
                      action: TextButton(
                        onPressed: _quitarFiltros,
                        child: const Text('Quitar filtros'),
                      ),
                    ),
                ],
              ),
      );
    },
  );
}

/// Detalle de un video del catálogo (GET /api/catalogo/videos/{id}). Con ventas usa el detalle de siempre; si el hub
/// no lo tiene (o no tiene catálogo), «No encontramos este video» como antes.
class CatalogVideoDetail extends StatelessWidget {
  const CatalogVideoDetail({super.key, required this.id, required this.onBack});
  final String id;
  final VoidCallback onBack;
  @override
  Widget build(BuildContext context) => ApiData(
    path: '/api/catalogo/videos/${Uri.encodeComponent(id)}',
    errorBuilder: (context, error) =>
        error is ErrorApi && error.codigo == 'no_encontrado'
        ? ListView(
            padding: pagePadding(context),
            children: [
              PageTitle('Detalle del video', back: onBack),
              const EmptyState(
                'No encontramos este video',
                text: 'Puede que ya no tenga pedidos registrados.',
              ),
            ],
          )
        : null,
    builder: (context, data) {
      if (data['ventas'] is Map) {
        return VideoSalesDetail(data: mapOf(data['ventas']), id: id, onBack: onBack);
      }
      final v = mapOf(data['video']);
      final estado = publicationLabel(v['publicacion']);
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
                    catalogTitle(v),
                    style: Theme.of(context).textTheme.headlineMedium,
                  ),
                  const SizedBox(height: 12),
                  if (v['publicado_at'] is num)
                    Text(
                      'Publicado el ${fechaDeInstante(v['publicado_at'] as num)}',
                      style: TextStyle(color: context.corte.muted),
                    ),
                  if (estado != null) ...[
                    const SizedBox(height: 8),
                    StatusTag(estado, urgent: v['publicacion'] == 'no_publico'),
                  ],
                  const SizedBox(height: 18),
                  if (v['vistas'] == null)
                    Text(
                      'TikTok no da cifras de este video: puede ser privado o estar borrado.',
                      style: TextStyle(color: context.corte.muted),
                    )
                  else
                    MetricStrip([
                      ('Vistas', integer(v['vistas'])),
                      ('Me gusta', v['likes'] == null ? '—' : integer(v['likes'])),
                      (
                        'Comentarios',
                        v['comentarios'] == null ? '—' : integer(v['comentarios']),
                      ),
                      (
                        'Compartidos',
                        v['compartidos'] == null ? '—' : integer(v['compartidos']),
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
          const SectionHeading('Ventas'),
          // Desde cuándo hay pedidos guardados, de la MISMA lista que usa «Todos» (en caché si se viene de ahí).
          // Sin poder leerla solo se puede decir que no hay ventas registradas.
          ApiData(
            path: '/api/catalogo/videos',
            query: const {'limite': 2000},
            padding: EdgeInsets.zero,
            errorBuilder: (context, _) =>
                const Text('Este video no tiene ventas registradas en Corte.'),
            builder: (context, lista) => Text(
              noSalesDetail(
                v,
                lista['pedidos_desde'] is String
                    ? lista['pedidos_desde'] as String
                    : null,
              ),
            ),
          ),
          NotesPanel(entidad: 'video', entidadId: id),
        ],
      );
    },
  );
}
