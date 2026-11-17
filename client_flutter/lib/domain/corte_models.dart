import 'corte_json.dart';

export 'api_error.dart';
export 'corte_json.dart';

class RespuestaDto extends JsonDto {
  RespuestaDto(super.value);

  int? get dataVersion => integer('data_version');
  int? get localRev => integer('local_rev');
  int? get imgRev => integer('img_rev');

  Map<String, ImagenMetaDto> get metaImagenes => Map.unmodifiable({
    for (final entry in (object('meta_imagenes') ?? {}).entries)
      entry.key: ImagenMetaDto(jsonMap(entry.value)),
  });
}

class ImagenMetaDto extends JsonDto {
  ImagenMetaDto(super.value);
  int? get ancho => integer('w');
  int? get alto => integer('h');
  String? get lqip => text('lqip');
  String? get color => text('color');
}

class ListaDto<T> extends RespuestaDto {
  ListaDto(super.value, this._decode);
  final T Function(JsonMap) _decode;

  late final List<T> items = List.unmodifiable(objects('items').map(_decode));
  int? get total => integer('total');
  int? get pagina => integer('pagina');
  int? get porPagina => integer('por_pagina');
}

class SesionDto extends RespuestaDto {
  SesionDto(super.value);
  JsonMap? get cuenta => object('cuenta');
  JsonMap? get conexion => object('conexion');
  JsonMap? get capacidades => object('capacidades');
  JsonMap? get datos => object('datos');
  bool get conectada => conexion?['estado'] == 'conectada';
  SyncDto? get sync {
    final value = object('sync');
    return value == null ? null : SyncDto(value);
  }
}

class SyncDto extends JsonDto {
  SyncDto(super.value);
  bool? get enCurso => flag('en_curso');
  num? get progreso => number('progreso');
  String? get texto => text('texto');
  String? get pasoActual => text('paso_actual');
  List<JsonMap> get pasos => objects('pasos');
  int? get ultimaOkAt => integer('ultima_ok_at');
}

class DashboardDto extends RespuestaDto {
  DashboardDto(super.value);
  JsonMap? get periodo => object('periodo');
  JsonMap? get kpis => object('kpis');
  JsonMap? get kpisAnterior => object('kpis_anterior');
  JsonMap? get muestras => object('muestras');
  JsonMap? get serie => object('serie');
  JsonMap? get perfilTikTok => object('perfil_tiktok');
  List<JsonMap> get alertas => objects('alertas');
  List<TiendaDto> get topTiendas =>
      List.unmodifiable(objects('top_tiendas').map(TiendaDto.new));
  List<VideoDto> get topVideos =>
      List.unmodifiable(objects('top_videos').map(VideoDto.new));
  List<ProductoDto> get topProductos =>
      List.unmodifiable(objects('top_productos').map(ProductoDto.new));
}

class ProductoResumenDto extends JsonDto {
  ProductoResumenDto(super.value);
  String get productId => requiredText('product_id');
  String? get titulo => text('titulo');
  String? get tituloCorto => text('titulo_corto');
  String? get imagen => text('imagen');
  String? get enlace => text('enlace');
  String? get categoria => text('categoria');
  int? get precioMinCentavos => integer('precio_min_centavos');
  int? get precioMaxCentavos => integer('precio_max_centavos');
  int? get precioVentaMinCentavos => integer('precio_venta_min_centavos');
  int? get precioVentaMaxCentavos => integer('precio_venta_max_centavos');
  int? get comisionBp => integer('comision_bp');
}

class MuestraDto extends JsonDto {
  MuestraDto(super.value);
  String get applicationId => requiredText('application_id');
  String? get grupo => text('grupo');
  String? get etiqueta => text('etiqueta');
  String? get motivo => text('motivo');
  String? get variante => text('variante');
  String? get prioridad => text('prioridad');
  int? get diasRestantes => integer('dias_restantes');
  int? get fechaLimiteAt => integer('fecha_limite_at');
  int? get solicitadaAt => integer('solicitada_at');
  bool? get recibida => flag('recibida');
  List<String> get razones => strings('razones');
  ProductoResumenDto get producto => ProductoResumenDto(
    object('producto') ?? (throw const FormatException('Falta producto.')),
  );
  JsonMap? get tienda => object('tienda');
  JsonMap? get avance => object('avance');
  JsonMap? get avisos => object('avisos');
  JsonMap? get ventasProducto => object('ventas_producto');
}

class MuestrasDto extends ListaDto<MuestraDto> {
  MuestrasDto(JsonMap value) : super(value, MuestraDto.new);
  JsonMap? get resumen => object('resumen');
}

class DetalleMuestraDto extends RespuestaDto {
  DetalleMuestraDto(super.value);
  MuestraDto get muestra => MuestraDto(
    object('muestra') ?? (throw const FormatException('Falta muestra.')),
  );
  List<JsonMap> get historial => objects('historial');
  List<NotaDto> get notas =>
      List.unmodifiable(objects('notas').map(NotaDto.new));
  List<PlanDto> get planes =>
      List.unmodifiable(objects('planes').map(PlanDto.new));
  List<RecordatorioDto> get recordatorios =>
      List.unmodifiable(objects('recordatorios').map(RecordatorioDto.new));
  List<AvisoDto> get avisos =>
      List.unmodifiable(objects('avisos').map(AvisoDto.new));
  List<JsonMap> get videosDelProducto => objects('videos_del_producto');
  List<JsonMap> get otrasDeLaTienda => objects('otras_de_la_tienda');
  String? get plantillaSugerida => text('plantilla_sugerida');
}

class PropiedadSkuDto extends JsonDto {
  PropiedadSkuDto(super.value);
  String? get nombre => text('nombre');
  String? get valor => text('valor');
}

class SkuDto extends JsonDto {
  SkuDto(super.value);
  String get skuId => requiredText('sku_id');
  String? get variante => text('variante');
  int? get precioCentavos => integer('precio_centavos');
  bool? get disponible => flag('disponible');
  String? get motivoNoDisponible => text('motivo_no_disponible');
  String? get motivoTexto => text('motivo_texto');
  List<PropiedadSkuDto> get propiedades =>
      List.unmodifiable(objects('propiedades').map(PropiedadSkuDto.new));
}

class ElegibilidadMuestraDto extends JsonDto {
  ElegibilidadMuestraDto(super.value);
  bool? get puedeSolicitar => flag('puede_solicitar');
  bool? get limiteAlcanzado => flag('limite_alcanzado');
  String? get estado => text('estado');
  String? get estadoTexto => text('estado_texto');
  List<SkuDto> get skus => List.unmodifiable(objects('skus').map(SkuDto.new));
}

class ProductoExtendidoDto extends JsonDto {
  ProductoExtendidoDto(super.value);
  int? get evidenciaRev => integer('evidencia_rev');
  TablaTallasDto? get tablaTallas {
    final value = object('tabla_tallas');
    return value == null ? null : TablaTallasDto(value);
  }

  ResenasProductoDto? get resenas {
    final value = object('resenas');
    return value == null ? null : ResenasProductoDto(value);
  }

  List<String> get galeria => strings('galeria');
  JsonMap? get vitrina => object('vitrina');
  ElegibilidadMuestraDto? get muestra {
    final value = object('muestra');
    return value == null ? null : ElegibilidadMuestraDto(value);
  }

  List<JsonMap> get solicitudesRecuperadas =>
      objects('solicitudes_recuperadas');
  List<JsonMap> get planesDirigidos => objects('planes_dirigidos');
  JsonMap? get comisionReal => object('comision_real');
  JsonMap? get parecidos => object('parecidos');
  JsonMap? get origenVentas => object('origen_ventas');
  String? get origenVentasAviso => text('origen_ventas_aviso');
}

class FuenteProductoDto extends JsonDto {
  FuenteProductoDto(super.value);
  String? get tipo => text('tipo');
  String? get nombre => text('nombre');
  String? get url => text('url');
}

class EvidenciaBloqueDto extends JsonDto {
  EvidenciaBloqueDto(super.value);
  String? get estado => text('estado');
  int? get consultadoAt => integer('consultado_at');
  FuenteProductoDto? get fuente {
    final value = object('fuente');
    return value == null ? null : FuenteProductoDto(value);
  }
}

class DatosTablaTallasDto extends JsonDto {
  DatosTablaTallasDto(super.value);
  List<String> get columnas => strings('columnas');
  String? get unidad => text('unidad');
  List<String> get imagenes => strings('imagenes');
  List<List<String>> get filas {
    final value = raw['filas'];
    if (value == null) return const [];
    if (value is! List ||
        value.any(
          (row) => row is! List || row.any((cell) => cell is! String),
        )) {
      throw const FormatException(
        'La tabla de tallas contiene una fila inválida.',
      );
    }
    return List.unmodifiable(
      value.map((row) => List<String>.unmodifiable(row as List)),
    );
  }
}

class TablaTallasDto extends EvidenciaBloqueDto {
  TablaTallasDto(super.value);
  DatosTablaTallasDto? get tabla {
    final value = object('tabla');
    return value == null ? null : DatosTablaTallasDto(value);
  }
}

class ResenaProductoDto extends JsonDto {
  ResenaProductoDto(super.value);
  String get id => requiredText('id');
  String? get texto => text('texto');
  num? get estrellas => number('estrellas');
  int? get fecha => integer('fecha');
  String? get variante => text('variante');
  bool? get compraVerificada => flag('compra_verificada');
  List<String> get imagenes => strings('imagenes');
}

class ResenasProductoDto extends EvidenciaBloqueDto {
  ResenasProductoDto(super.value);
  num? get promedio => number('promedio');
  int? get total => integer('total');
  int? get cargadas => integer('cargadas');
  String? get siguienteCursor => text('siguiente_cursor');
  List<ResenaProductoDto> get items =>
      List.unmodifiable(objects('items').map(ResenaProductoDto.new));
}

class ProductoDto extends ProductoResumenDto {
  ProductoDto(super.value);
  String? get tiendaKey => text('tienda_key');
  int? get pedidosValidos => integer('pedidos_validos');
  int? get comisionEstimadaCentavos => integer('comision_estimada_centavos');
}

class DetalleProductoDto extends RespuestaDto {
  DetalleProductoDto(super.value);
  String get productId => requiredText('product_id');
  ProductoResumenDto? get ficha {
    final value = object('ficha');
    return value == null ? null : ProductoResumenDto(value);
  }

  ProductoExtendidoDto? get extendido {
    final value = object('extendido');
    return value == null ? null : ProductoExtendidoDto(value);
  }

  List<MuestraDto> get muestras =>
      List.unmodifiable(objects('muestras').map(MuestraDto.new));
  List<VideoDto> get videos =>
      List.unmodifiable(objects('videos').map(VideoDto.new));
  List<NotaDto> get notas =>
      List.unmodifiable(objects('notas').map(NotaDto.new));
  List<JsonMap> get serie => objects('serie');
  JsonMap? get fila => object('fila');
}

class TiendaDto extends JsonDto {
  TiendaDto(super.value);
  String get tiendaKey => requiredText('tienda_key');
  String? get nombre => text('nombre');
  String? get salud => text('salud');
  int? get pendientes => integer('pendientes');
  int? get comisionEstimadaCentavos => integer('comision_estimada_centavos');
}

class DetalleTiendaDto extends RespuestaDto {
  DetalleTiendaDto(super.value);
  JsonMap? get tienda => object('tienda');
  List<MuestraDto> get muestras =>
      List.unmodifiable(objects('muestras').map(MuestraDto.new));
  List<ProductoDto> get productos =>
      List.unmodifiable(objects('productos').map(ProductoDto.new));
  List<NotaDto> get notas =>
      List.unmodifiable(objects('notas').map(NotaDto.new));
  List<AvisoDto> get avisos =>
      List.unmodifiable(objects('avisos').map(AvisoDto.new));
  List<JsonMap> get serie => objects('serie');
  String? get plantillaSugerida => text('plantilla_sugerida');
}

class VideoDto extends JsonDto {
  VideoDto(super.value);
  String get contentId => requiredText('content_id');
  String? get descripcion => text('descripcion');
  String? get enlace => text('enlace');
  int? get vistas => integer('vistas');
  int? get likes => integer('likes');
  int? get comentarios => integer('comentarios');
  int? get compartidos => integer('compartidos');
  String? get productoPrincipalId => text('producto_principal_id');

  /// Legacy product photos must never become video covers.
  String? get portada {
    for (final candidate in [text('portada'), text('miniatura')]) {
      if (candidate == null) continue;
      final uri = Uri.tryParse(candidate);
      if (uri == null || uri.hasScheme || uri.hasAuthority) continue;
      if (uri.path == '/img/v/$contentId' ||
          uri.path == '/lan/v1/img/v/$contentId') {
        return candidate;
      }
    }
    return null;
  }
}

class DetalleVideoDto extends RespuestaDto {
  DetalleVideoDto(super.value);
  VideoDto? get video {
    final value = object('video');
    return value == null ? null : VideoDto(value);
  }

  List<ProductoDto> get productos =>
      List.unmodifiable(objects('productos').map(ProductoDto.new));
  List<JsonMap> get serie => objects('serie');
  List<JsonMap> get tendencia => objects('tendencia');
}

class OrdenDto extends JsonDto {
  OrdenDto(super.value);
  String get orderId => requiredText('order_id');
  String? get estado => text('estado');
  String? get fecha => text('fecha');
  int? get creadaAt => integer('creada_at');
  List<JsonMap> get lineas => objects('lineas');
}

class VersionadoDto extends JsonDto {
  VersionadoDto(super.value);
  String get id => requiredText('id');
  int get rev => integer('rev') ?? (throw const FormatException('Falta rev.'));
  int? get creadoAt => integer('creado_at');
  int? get actualizadoAt => integer('actualizado_at');
}

class PlanDto extends VersionadoDto {
  PlanDto(super.value);
  String? get applicationId => text('application_id');
  String? get productId => text('product_id');
  String? get tiendaKey => text('tienda_key');
  String? get titulo => text('titulo');
  String? get estado => text('estado');
  String? get fechaPlan => text('fecha_plan');
  String? get fechaPublicada => text('fecha_publicada');
  String? get contentId => text('content_id');
  int? get programadaParaAt => integer('programada_para_at');
  String? get notas => text('notas');
}

class NotaDto extends VersionadoDto {
  NotaDto(super.value);
  String? get entidad => text('entidad');
  String? get entidadId => text('entidad_id');
  String? get texto => text('texto');
  bool? get fijada => flag('fijada');
}

class RecordatorioDto extends VersionadoDto {
  RecordatorioDto(super.value);
  String? get entidad => text('entidad');
  String? get entidadId => text('entidad_id');
  String? get titulo => text('titulo');
  String? get estado => text('estado');
  int? get venceAt => integer('vence_at');
  int? get pospuestoHasta => integer('pospuesto_hasta');
  String? get repetir => text('repetir');
}

class AvisoDto extends VersionadoDto {
  AvisoDto(super.value);
  String? get tiendaKey => text('tienda_key');
  String? get texto => text('texto');
  List<String> get solicitudIds => strings('solicitud_ids');
  JsonMap? get compromisos => object('compromisos');
  int? get marcadoEnviadoAt => integer('marcado_enviado_at');
  int? get quitadoAt => integer('quitado_at');
}

class PreferenciasDto extends JsonDto {
  PreferenciasDto(super.value);
  int get rev => integer('rev') ?? (throw const FormatException('Falta rev.'));
  String? get tema => text('tema');
  String? get firma => text('firma');
  int? get capacidadVideosDia => integer('capacidad_videos_dia');
}

class SnapshotDto extends RespuestaDto {
  SnapshotDto(super.value);
  int? get generadoAt => integer('generado_at');
  List<MuestraDto> get muestras =>
      List.unmodifiable(objects('muestras').map(MuestraDto.new));
  List<ProductoDto> get productos =>
      List.unmodifiable(objects('productos').map(ProductoDto.new));
  List<VideoDto> get videos =>
      List.unmodifiable(objects('videos').map(VideoDto.new));
  List<TiendaDto> get tiendas =>
      List.unmodifiable(objects('tiendas').map(TiendaDto.new));
  List<OrdenDto> get ordenesRecientes =>
      List.unmodifiable(objects('ordenes_recientes').map(OrdenDto.new));
  JsonMap? get local => object('local');
  JsonMap? get extras => object('extras');
  List<String> get imagenes => strings('imagenes');

  ProductoExtendidoDto? productoExtendido(String productId) {
    final products = extras?['productos'];
    if (products is! Map || products[productId] == null) return null;
    return ProductoExtendidoDto(jsonMap(products[productId]));
  }
}

class ResultadoOpsDto extends RespuestaDto {
  ResultadoOpsDto(super.value);
  List<JsonMap> get resultados => objects('resultados');
  bool get tieneConflictos =>
      resultados.any((item) => item['estado'] == 'conflicto');
}

/// Client outcome, distinct from a server acknowledgement of an applied op.
class GuardadoDto extends ResultadoOpsDto {
  GuardadoDto(super.value);
  bool get enCola => flag('en_cola') == true;
}
