import 'dart:collection';
import 'dart:convert';
import 'dart:math';
import 'dart:typed_data';

import '../domain/corte_models.dart';
import 'http_adapter.dart';
import 'corte_store.dart';
import 'corte_journal.dart';
import 'image_cache.dart';
import 'snapshot_projection.dart';

export '../domain/corte_models.dart';
export 'http_adapter.dart';
export 'corte_store.dart';
export 'corte_journal.dart';

enum FuenteLectura { servidor, cache }

class EstadoLectura {
  const EstadoLectura(this.path, this.fuente, this.guardadaAt);
  final String path;
  final FuenteLectura fuente;
  final DateTime guardadaAt;
}

class _Entrada {
  _Entrada(this.data, this.etag, this.at);
  final JsonMap data;
  final String? etag;
  final DateTime at;
}

/// Owner-scoped application state, not a shared HTTP cache. Native secrets stay
/// in the platform adapter. Failed mutations are never automatically replayed.
class CorteRepository {
  CorteRepository({
    required CorteHttpAdapter adapter,
    String? ownerScope,
    String? cacheScope,
    CorteDataStore? store,
    int maxCacheEntries = 80,
  }) : _adapter = adapter,
       _ownerScope = ownerScope,
       _cacheScope = cacheScope,
       _store = store,
       _maxCacheEntries = maxCacheEntries {
    if (maxCacheEntries < 1) throw ArgumentError.value(maxCacheEntries);
    _validateScope(cacheScope);
  }

  final CorteHttpAdapter _adapter;
  final int _maxCacheEntries;
  final _cache = LinkedHashMap<String, _Entrada>();
  final _pending = <String, Future<JsonMap>>{};
  final _journals = <String, CorteJournal>{};
  CorteImageCache? _images;
  String? _ownerScope;
  String? _cacheScope;
  CorteDataStore? _store;
  int _generation = 0;
  int _cacheEpoch = 0;
  bool _closed = false;
  EstadoLectura? ultimaLectura;
  ErrorApi? ultimoErrorCopia;

  String? get ownerScope => _ownerScope;
  String? get cacheScope => _cacheScope;
  bool get copiaPersistenteDisponible => _cacheScope != null && _store != null;
  bool get sinConexion => ultimaLectura?.fuente == FuenteLectura.cache;
  void attachStore(CorteDataStore store) {
    _ensureOpen();
    if (_store != null && !identical(_store, store)) {
      throw StateError('El repositorio ya tiene almacenamiento vinculado.');
    }
    _store = store;
    _images ??= CorteImageCache(store);
  }

  CorteJournal? get _journal {
    final scope = _cacheScope;
    final store = _store;
    if (scope == null || store == null) return null;
    return _journals.putIfAbsent(scope, () => CorteJournal(store, scope));
  }

  Future<JsonMap> _overlay(String url, JsonMap data, int generation) async {
    final journal = _journal;
    if (journal == null) return data;
    try {
      final ops = await journal.leerOps();
      _ensureGeneration(generation);
      return aplicarPendientes(url, data, ops);
    } on ErrorApi catch (error) {
      if (error.codigo == 'sesion_cambiada') rethrow;
      ultimoErrorCopia = error;
      return data;
    } on Exception {
      return data;
    }
  }

  Future<JsonMap?> _project(String url, int generation) async {
    final journal = _journal;
    if (journal == null) return null;
    try {
      final saved = await journal.leerSnapshot();
      final ops = await journal.leerOps();
      _ensureGeneration(generation);
      if (saved == null) return null;
      final projected = proyectarSnapshot(
        url,
        jsonMap(saved['snapshot']),
        outbox: ops,
      );
      if (projected == null) return null;
      final at = saved['guardada_at'];
      ultimaLectura = EstadoLectura(
        url,
        FuenteLectura.cache,
        DateTime.fromMillisecondsSinceEpoch(
          (at is int ? at : 0) * 1000,
          isUtc: true,
        ),
      );
      return projected;
    } on ErrorApi catch (error) {
      if (error.codigo == 'sesion_cambiada') rethrow;
      ultimoErrorCopia = error;
      return null;
    } on Exception {
      return null;
    }
  }

  /// Call on every authenticated-owner change, including logout. Old in-flight
  /// responses cannot publish data into the new session.
  void setOwnerScope(String? value) {
    setScopes(ownerScope: value);
  }

  void setScopes({String? ownerScope, String? cacheScope}) {
    _validateScope(cacheScope);
    if (ownerScope == _ownerScope && cacheScope == _cacheScope) return;
    _ownerScope = ownerScope;
    _cacheScope = cacheScope;
    _generation++;
    _pending.clear();
    invalidar();
    ultimaLectura = null;
  }

  void invalidar() {
    _cacheEpoch++;
    _cache.clear();
  }

  Future<JsonMap> get(
    String path, {
    Map<String, Object?> query = const {},
    bool force = false,
    bool permitirCacheSinRed = true,
  }) {
    _ensureOpen();
    if (path.startsWith('/api/push/')) {
      force = true;
      permitirCacheSinRed = false;
    }
    final url = rutaCanonica(path, query);
    final key = '$_generation|$url|force=$force|stale=$permitirCacheSinRed';
    final pending = _pending[key];
    if (pending != null) return pending;
    final generation = _generation;
    final cacheEpoch = _cacheEpoch;
    late final Future<JsonMap> request;
    request = _read(url, generation, cacheEpoch, force, permitirCacheSinRed)
        .whenComplete(() {
          if (identical(_pending[key], request)) _pending.remove(key);
        });
    _pending[key] = request;
    return request;
  }

  Future<JsonMap> _read(
    String url,
    int generation,
    int cacheEpoch,
    bool force,
    bool allowStale,
  ) async {
    var cached = _cache[url];
    final journal = _journal;
    if (cached == null && url == '/api/snapshot' && journal != null) {
      try {
        final saved = await journal.leerSnapshot();
        _ensureGeneration(generation);
        if (saved != null) {
          final at = saved['guardada_at'];
          cached = _Entrada(
            immutableJson(jsonMap(saved['snapshot'])),
            saved['etag'] is String ? saved['etag'] as String : null,
            at is int
                ? DateTime.fromMillisecondsSinceEpoch(at * 1000, isUtc: true)
                : DateTime.fromMillisecondsSinceEpoch(0, isUtc: true),
          );
        }
      } on ErrorApi catch (error) {
        if (error.codigo == 'sesion_cambiada') rethrow;
        ultimoErrorCopia = error;
      } on Exception {
        ultimoErrorCopia = ErrorApi(
          codigo: 'copia_no_disponible',
          mensaje:
              'No pudimos abrir la copia local. Los datos se consultarán en línea.',
        );
      }
    }
    final headers = <String, String>{'Accept': 'application/json'};
    if (Uri.parse(url).path.startsWith('/api/push/')) {
      if (_cacheScope == null) {
        throw ErrorApi(
          codigo: 'sesion_cambiada',
          mensaje: 'Actualiza tu conexión con Google.',
        );
      }
      headers['X-Corte-Cache-Scope'] = _cacheScope!;
    }
    if (!force && cached?.etag != null)
      headers['If-None-Match'] = cached!.etag!;
    late final CorteResponse response;
    try {
      response = await _adapter.request('GET', url, headers: headers);
    } on CorteTransportException catch (error) {
      _ensureGeneration(generation);
      if (allowStale &&
          cached != null &&
          cacheEpoch == _cacheEpoch &&
          _isNetworkFailure(error.codigo)) {
        return _overlay(url, _fromCache(url, cached), generation);
      }
      if (allowStale &&
          cacheEpoch == _cacheEpoch &&
          _isNetworkFailure(error.codigo)) {
        final projected = await _project(url, generation);
        if (projected != null) return projected;
      }
      throw ErrorApi(codigo: error.codigo, mensaje: error.mensaje);
    }
    _ensureGeneration(generation);
    if (response.statusCode == 304) {
      if (cached == null) {
        throw ErrorApi(
          codigo: 'cache_invalida',
          mensaje: 'No hay una copia válida. Vuelve a actualizar.',
          http: 304,
        );
      }
      ultimaLectura = EstadoLectura(url, FuenteLectura.servidor, cached.at);
      return _overlay(url, cached.data, generation);
    }
    if (response.statusCode >= 400) {
      if (allowStale &&
          cached != null &&
          cacheEpoch == _cacheEpoch &&
          const [502, 503, 504].contains(response.statusCode)) {
        return _overlay(url, _fromCache(url, cached), generation);
      }
      if (allowStale &&
          cacheEpoch == _cacheEpoch &&
          const [502, 503, 504].contains(response.statusCode)) {
        final projected = await _project(url, generation);
        if (projected != null) return projected;
      }
      if (response.statusCode == 401) invalidar();
      throw _error(response);
    }
    final data = _decode(response);
    final now = DateTime.now().toUtc();
    if (_cacheScope != null && cacheEpoch == _cacheEpoch && _cacheable(url)) {
      _cache.remove(url);
      _cache[url] = _Entrada(data, response.headers['etag'], now);
      while (_cache.length > _maxCacheEntries) {
        _cache.remove(_cache.keys.first);
      }
    }
    ultimaLectura = EstadoLectura(url, FuenteLectura.servidor, now);
    if (url == '/api/snapshot' &&
        journal != null &&
        cacheEpoch == _cacheEpoch) {
      try {
        await journal.guardarSnapshot(data, response.headers['etag']);
        _ensureGeneration(generation);
        ultimoErrorCopia = null;
      } on ErrorApi catch (error) {
        if (error.codigo == 'sesion_cambiada') rethrow;
        ultimoErrorCopia = error;
      } on Exception {
        ultimoErrorCopia = ErrorApi(
          codigo: 'copia_no_guardada',
          mensaje:
              'Los datos están actualizados, pero no pudimos guardar la copia sin conexión.',
        );
      }
    }
    return _overlay(url, data, generation);
  }

  JsonMap _fromCache(String url, _Entrada entry) {
    ultimaLectura = EstadoLectura(url, FuenteLectura.cache, entry.at);
    return entry.data;
  }

  Future<JsonMap> post(String path, {Object? body}) =>
      write('POST', path, body: body);
  Future<JsonMap> patch(String path, {Object? body}) =>
      write('PATCH', path, body: body);
  Future<JsonMap> put(String path, {Object? body}) =>
      write('PUT', path, body: body);
  Future<JsonMap> delete(
    String path, {
    Map<String, Object?> query = const {},
    Object? body,
  }) => write('DELETE', path, query: query, body: body);

  Future<JsonMap> write(
    String method,
    String path, {
    Map<String, Object?> query = const {},
    Object? body,
    Map<String, String> headers = const {},
  }) async {
    _ensureOpen();
    final verb = method.toUpperCase();
    if (!const ['POST', 'PUT', 'PATCH', 'DELETE'].contains(verb)) {
      throw ArgumentError.value(method, 'method');
    }
    final url = rutaCanonica(path, query);
    final generation = _generation;
    final payload = body is Map ? immutableJson(jsonMap(body)) : body;
    final evidenceWrite =
        path.startsWith('/api/push/') ||
        (verb == 'PUT' &&
            RegExp(r'^/api/productos/[0-9]{1,25}/evidencia$').hasMatch(path)) ||
        (verb == 'POST' &&
            RegExp(r'^/api/productos/[0-9]{1,25}/extraer$').hasMatch(path));
    final scope = _cacheScope;
    if (evidenceWrite && scope == null) {
      throw ErrorApi(
        codigo: 'sesion_cambiada',
        mensaje:
            'Actualiza la conexión antes de guardar información del producto.',
      );
    }
    late final CorteResponse response;
    try {
      response = await _adapter.request(
        verb,
        url,
        headers: {
          'Accept': 'application/json',
          ...headers,
          if (evidenceWrite) 'X-Corte-Cache-Scope': scope!,
        },
        body: payload,
      );
    } on CorteTransportException catch (error) {
      _ensureGeneration(generation);
      throw ErrorApi(codigo: error.codigo, mensaje: error.mensaje);
    }
    _ensureGeneration(generation);
    if (response.statusCode >= 400) throw _error(response);
    final data = _decode(response);
    if (!path.startsWith('/api/push/')) invalidar();
    return data;
  }

  Future<SesionDto> sesion({bool force = false}) async =>
      SesionDto(await get('/api/session', force: force));
  Future<DashboardDto> dashboard({String periodo = '30d'}) async =>
      DashboardDto(await get('/api/dashboard', query: {'periodo': periodo}));
  Future<MuestrasDto> muestras({Map<String, Object?> query = const {}}) async =>
      MuestrasDto(await get('/api/muestras', query: query));
  Future<DetalleMuestraDto> muestra(String id) async =>
      DetalleMuestraDto(await get('/api/muestras/${Uri.encodeComponent(id)}'));
  Future<ListaDto<TiendaDto>> tiendas({
    Map<String, Object?> query = const {},
  }) async => ListaDto(await get('/api/tiendas', query: query), TiendaDto.new);
  Future<DetalleTiendaDto> tienda(String key) async =>
      DetalleTiendaDto(await get('/api/tiendas/${Uri.encodeComponent(key)}'));
  Future<ListaDto<ProductoDto>> productos({
    Map<String, Object?> query = const {},
  }) async => ListaDto(
    await get('/api/analitica/productos', query: query),
    ProductoDto.new,
  );
  Future<DetalleProductoDto> producto(String id) async => DetalleProductoDto(
    await get('/api/productos/${Uri.encodeComponent(id)}'),
  );
  Future<ListaDto<VideoDto>> videos({
    Map<String, Object?> query = const {},
  }) async =>
      ListaDto(await get('/api/analitica/videos', query: query), VideoDto.new);
  Future<DetalleVideoDto> video(String id) async =>
      DetalleVideoDto(await get('/api/videos/${Uri.encodeComponent(id)}'));
  Future<ListaDto<OrdenDto>> ordenes({
    Map<String, Object?> query = const {},
  }) async => ListaDto(await get('/api/ordenes', query: query), OrdenDto.new);
  Future<SnapshotDto> snapshot({bool force = false}) async =>
      SnapshotDto(await get('/api/snapshot', force: force));
  Future<PreferenciasDto> preferencias() async =>
      PreferenciasDto(await get('/api/preferencias'));
  Future<SyncDto> syncEstado() async => SyncDto(await get('/api/sync/estado'));
  Future<JsonMap> sincronizar({String tipo = 'incremental'}) =>
      post('/api/sync', body: {'tipo': tipo});
  Future<ListaDto<PlanDto>> planes() async =>
      ListaDto(await get('/api/plan'), PlanDto.new);
  Future<ListaDto<NotaDto>> notas({String? entidad, String? entidadId}) async =>
      ListaDto(
        await get(
          '/api/notas',
          query: {'entidad': entidad, 'entidad_id': entidadId},
        ),
        NotaDto.new,
      );
  Future<ListaDto<RecordatorioDto>> recordatorios({String? estado}) async =>
      ListaDto(
        await get('/api/recordatorios', query: {'estado': estado}),
        RecordatorioDto.new,
      );
  Future<ListaDto<AvisoDto>> avisos({
    String? tienda,
    String? solicitud,
  }) async => ListaDto(
    await get('/api/avisos', query: {'tienda': tienda, 'solicitud': solicitud}),
    AvisoDto.new,
  );

  /// Existing idempotent batch endpoint. Keep op_id unchanged when retrying a
  /// queued operation; the server returns conflicts individually in resultados.
  Future<ResultadoOpsDto> aplicarOps(List<JsonMap> ops) async {
    if (ops.isEmpty || ops.length > 200) {
      throw ArgumentError('El lote debe contener de 1 a 200 operaciones.');
    }
    return ResultadoOpsDto(
      await write(
        'POST',
        '/api/local/ops',
        body: {'ops': ops},
        headers: {if (_cacheScope != null) 'X-Corte-Cache-Scope': _cacheScope!},
      ),
    );
  }

  Future<List<JsonMap>> opsPendientes({bool incluirConflictos = false}) async {
    _ensureOpen();
    final generation = _generation;
    final items = await _journal?.leerOps() ?? const <JsonMap>[];
    _ensureGeneration(generation);
    return List.unmodifiable(
      items.where((item) => incluirConflictos || item['estado'] == 'pendiente'),
    );
  }

  Future<void> encolarOps(List<JsonMap> ops) async {
    _ensureOpen();
    final journal = _journal;
    if (journal == null) {
      throw ErrorApi(
        codigo: 'copia_no_disponible',
        mensaje:
            'Conecta Corte para guardar este cambio. No hay una copia local vinculada.',
      );
    }
    final generation = _generation;
    try {
      await journal.encolar(ops);
    } on ErrorApi {
      rethrow;
    } catch (_) {
      throw ErrorApi(
        codigo: 'copia_no_guardada',
        mensaje:
            'No pudimos guardar este cambio en el equipo. Conservamos los cambios anteriores.',
      );
    }
    _ensureGeneration(generation);
  }

  Future<void> descartarOperacion(String opId) async {
    _ensureOpen();
    final generation = _generation;
    final journal = _journal;
    if (journal == null)
      throw ErrorApi(
        codigo: 'copia_no_disponible',
        mensaje: 'La cola local no está disponible.',
      );
    await journal.descartar(opId);
    _ensureGeneration(generation);
    invalidar();
  }

  Future<GuardadoDto> resolverOperacion(
    String opId,
    JsonMap replacement,
  ) async {
    _ensureOpen();
    final generation = _generation;
    final journal = _journal;
    if (journal == null)
      throw ErrorApi(
        codigo: 'copia_no_disponible',
        mensaje: 'La cola local no está disponible.',
      );
    await journal.reemplazar(opId, replacement);
    _ensureGeneration(generation);
    invalidar();
    return guardarOps([replacement]);
  }

  /// No scope means no durable replay. Each batch rechecks the current creator;
  /// the server atomically validates X-Corte-Cache-Scope before applying it.
  Future<ResultadoOpsDto> flushOps() async {
    _ensureOpen();
    final journal = _journal;
    final scope = _cacheScope;
    if (journal == null || scope == null) {
      return ResultadoOpsDto({'resultados': <JsonMap>[]});
    }
    final generation = _generation;
    final pending = (await journal.leerOps())
        .where((item) => item['estado'] == 'pendiente')
        .toList();
    _ensureGeneration(generation);
    if (pending.isEmpty) return ResultadoOpsDto({'resultados': <JsonMap>[]});
    final revision = await get(
      '/api/cloud/revision',
      force: true,
      permitirCacheSinRed: false,
    );
    _ensureGeneration(generation);
    if (revision['cache_scope'] != scope) {
      setScopes(
        ownerScope: revision['owner_scope'] is String
            ? revision['owner_scope'] as String
            : null,
        cacheScope: revision['cache_scope'] is String
            ? revision['cache_scope'] as String
            : null,
      );
      throw ErrorApi(
        codigo: 'cuenta_cambiada',
        mensaje:
            'La cuenta conectada cambió. Conservamos sus cambios anteriores sin enviarlos.',
      );
    }
    final batch = <JsonMap>[];
    for (final item in pending.take(200)) {
      final operation = jsonMap(item['op']);
      final size = utf8
          .encode(
            jsonEncode({
              'ops': [...batch, operation],
            }),
          )
          .length;
      if (size > 200 * 1024) break;
      batch.add(operation);
    }
    if (batch.isEmpty) {
      throw ErrorApi(
        codigo: 'cambio_demasiado_grande',
        mensaje:
            'Un cambio pendiente es demasiado grande para enviarlo. Conservamos su copia.',
      );
    }
    _ensureGeneration(generation);
    final result = await aplicarOps(batch);
    _ensureGeneration(generation);
    await journal.confirmar(
      result.resultados,
      batch.map((op) => op['op_id'] as String).toSet(),
    );
    _ensureGeneration(generation);
    return result;
  }

  /// Enqueue durably before networking. A lost response remains pending with its
  /// original op_id, so a later flush can receive the server's duplicate ack.
  Future<GuardadoDto> guardarOps(List<JsonMap> ops) async {
    if (ops.isEmpty || ops.length > 200) {
      throw ErrorApi(
        codigo: 'parametros_invalidos',
        mensaje: 'El lote debe contener de 1 a 200 cambios.',
      );
    }
    final ids = ops.map((op) => op['op_id']).toSet();
    if (!copiaPersistenteDisponible) {
      final result = await aplicarOps(ops);
      _throwRejected(result.resultados, ids);
      final ack = result.resultados
          .where(
            (item) => const ['aplicada', 'duplicada'].contains(item['estado']),
          )
          .map((item) => item['op_id'])
          .toSet();
      if (!ack.containsAll(ids)) {
        throw ErrorApi(
          codigo: 'respuesta_invalida',
          mensaje:
              'El servidor no confirmó todos los cambios. Vuelve a intentarlo.',
        );
      }
      return GuardadoDto({...result.raw, 'en_cola': false});
    }
    await encolarOps(ops);
    try {
      final result = await flushOps();
      final entries = await opsPendientes(incluirConflictos: true);
      _throwRejected(result.resultados, ids);
      for (final item in entries) {
        if (ids.contains(jsonMap(item['op'])['op_id']) &&
            item['resultado'] is Map) {
          _throwRejected([jsonMap(item['resultado'])], ids);
        }
      }
      return GuardadoDto({
        ...result.raw,
        'en_cola': entries.any(
          (item) =>
              item['estado'] == 'pendiente' &&
              ids.contains(jsonMap(item['op'])['op_id']),
        ),
      });
    } on ErrorApi catch (error) {
      if (!error.esTransitorio || error.codigo == 'sesion_cambiada') rethrow;
      return GuardadoDto({'resultados': <JsonMap>[], 'en_cola': true});
    }
  }

  Future<Uint8List> imagen(String path, {String? tamano}) async {
    _ensureOpen();
    final normalized = path.startsWith('/lan/v1/img/')
        ? path.substring('/lan/v1'.length)
        : path;
    final url = rutaCanonica(normalized, {'t': tamano}, imagen: true);
    final generation = _generation;
    final scope = _cacheScope;
    final images = _store == null
        ? null
        : (_images ??= CorteImageCache(_store!));
    Future<Uint8List?> local({bool small = false}) async {
      if (scope == null || images == null) return null;
      try {
        final bytes = await images.read(scope, url, allowSmFallback: small);
        _ensureGeneration(generation);
        return bytes;
      } on ErrorApi {
        rethrow;
      } on Exception {
        return null;
      }
    }

    final exact = await local();
    if (exact != null) return exact;
    for (var attempt = 0; attempt < 3; attempt++) {
      CorteResponse response;
      try {
        response = await _adapter.request(
          'GET',
          url,
          headers: const {'Accept': 'image/*'},
        );
      } on CorteTransportException catch (error) {
        _ensureGeneration(generation);
        if (!_isNetworkFailure(error.codigo))
          throw ErrorApi(codigo: error.codigo, mensaje: error.mensaje);
        if (attempt < 2) {
          await Future<void>.delayed(
            Duration(milliseconds: 150 * (attempt + 1)),
          );
          continue;
        }
        final fallback = await local(small: true);
        if (fallback != null) return fallback;
        throw ErrorApi(codigo: error.codigo, mensaje: error.mensaje);
      }
      _ensureGeneration(generation);
      if (response.statusCode == 200) {
        final mime = response.headers['content-type']?.toLowerCase() ?? '';
        if (!mime.startsWith('image/') || response.bodyBytes.isEmpty) {
          throw ErrorApi(
            codigo: 'imagen_invalida',
            mensaje: 'La foto recibida no es válida.',
          );
        }
        if (scope != null && images != null) {
          try {
            await images.put(scope, url, response.bodyBytes, response.headers);
          } on Exception {
            /* The online photo remains usable if storage is full. */
          }
          _ensureGeneration(generation);
        }
        return Uint8List.fromList(response.bodyBytes);
      }
      if (const [429, 500, 502, 503, 504].contains(response.statusCode) &&
          attempt < 2) {
        final retry = int.tryParse(response.headers['retry-after'] ?? '');
        await Future<void>.delayed(
          Duration(
            milliseconds: retry == null
                ? 150 * (attempt + 1)
                : retry.clamp(0, 3) * 1000,
          ),
        );
        _ensureGeneration(generation);
        continue;
      }
      if (const [404, 429, 500, 502, 503, 504].contains(response.statusCode)) {
        final fallback = await local(small: true);
        if (fallback != null) return fallback;
      }
      if (response.statusCode == 401) invalidar();
      throw _error(response);
    }
    throw StateError('Reintentos agotados.');
  }

  /// Only the backend's already-downloaded, versioned image manifest is used.
  /// A small pool keeps background precaching from blocking interactive work.
  Future<void> precargarImagenes(SnapshotDto snapshot) async {
    final generation = _generation;
    final urls = snapshot.strings('imagenes').toSet().toList();
    if (!copiaPersistenteDisponible) return;
    var index = 0;
    Future<void> worker() async {
      while (index < urls.length && generation == _generation && !_closed) {
        final url = urls[index++];
        try {
          await imagen(url);
        } on ErrorApi catch (error) {
          if (error.esAutenticacion || error.codigo == 'sesion_cambiada')
            return;
        } on Exception {
          /* Retry remaining files on the next snapshot. */
        }
      }
    }

    await Future.wait([worker(), worker()]);
  }

  void close() {
    if (_closed) return;
    _closed = true;
    _generation++;
    invalidar();
    _pending.clear();
    _journals.clear();
    _adapter.close();
  }

  void _ensureOpen() {
    if (_closed) throw StateError('El repositorio está cerrado.');
  }

  void _ensureGeneration(int generation) {
    if (_closed || generation != _generation) {
      throw ErrorApi(
        codigo: 'sesion_cambiada',
        mensaje: 'La sesión cambió. Vuelve a abrir esta vista.',
      );
    }
  }
}

bool _isNetworkFailure(String code) =>
    const ['red', 'sin_internet', 'timeout', 'tiempo_agotado'].contains(code);

void _validateScope(String? scope) {
  if (scope != null && !scopeValido(scope)) {
    throw ArgumentError(
      'El scope de la copia debe venir de la sesión del servidor.',
    );
  }
}

void _throwRejected(List<JsonMap> results, Set<dynamic> requested) {
  for (final result in results) {
    if (!requested.contains(result['op_id'])) continue;
    final state = result['estado'];
    if (state != 'conflicto' && state != 'invalida') continue;
    final error = result['error'];
    throw ErrorApi(
      codigo: state == 'conflicto' ? 'conflicto' : 'operacion_invalida',
      http: state == 'conflicto' ? 409 : 400,
      mensaje: error is String && error.isNotEmpty
          ? error
          : state == 'conflicto'
          ? 'Este dato cambió en otro dispositivo. Revisa la versión actual.'
          : 'No pudimos guardar este cambio. Revisa los datos.',
      vigente: result['objeto'] is Map ? jsonMap(result['objeto']) : null,
    );
  }
}

bool _cacheable(String url) => !const [
  '/api/push/',
  '/api/session',
  '/api/cloud/',
  '/api/auth/',
  '/api/credenciales/',
  '/api/display/',
  '/api/sync/',
  '/api/cambios',
].any((prefix) => Uri.parse(url).path.startsWith(prefix));

JsonMap _decode(CorteResponse response) {
  if (response.statusCode == 204 && response.bodyBytes.isEmpty)
    return immutableJson({});
  try {
    return immutableJson(jsonMap(jsonDecode(utf8.decode(response.bodyBytes))));
  } on FormatException {
    throw ErrorApi(
      codigo: 'respuesta_invalida',
      mensaje: 'El servidor devolvió una respuesta que no pudimos leer.',
      http: response.statusCode,
    );
  }
}

ErrorApi _error(CorteResponse response) {
  JsonMap error = {};
  try {
    final decoded = jsonMap(jsonDecode(utf8.decode(response.bodyBytes)));
    if (decoded['error'] is Map) error = jsonMap(decoded['error']);
  } on FormatException {
    // A proxy may return HTML. Never echo its body or request headers.
  }
  final code = error['codigo'];
  final message = error['mensaje'];
  final retry = error['reintentar_en_s'];
  return ErrorApi(
    codigo: code is String ? code : 'http_${response.statusCode}',
    mensaje: message is String && message.isNotEmpty
        ? message
        : 'No pudimos completar la solicitud. Inténtalo de nuevo.',
    http: response.statusCode,
    detalle: error['detalle'] is Map ? jsonMap(error['detalle']) : null,
    vigente: error['vigente'] is Map ? jsonMap(error['vigente']) : null,
    reintentarEnS: retry is int
        ? retry
        : int.tryParse(response.headers['retry-after'] ?? ''),
  );
}

/// Canonical query keys, CSV lists and 1/0 booleans match the existing backend.
String rutaCanonica(
  String path,
  Map<String, Object?> query, {
  bool imagen = false,
}) {
  final uri = Uri.tryParse(path);
  if (uri == null ||
      uri.hasScheme ||
      uri.hasAuthority ||
      uri.hasFragment ||
      !uri.path.startsWith(imagen ? '/img/' : '/api/') ||
      uri.path.startsWith('/api/native/') ||
      uri.pathSegments.any(
        (part) => part == '..' || part == '.' || part.contains('\\'),
      )) {
    throw ArgumentError('La ruta debe pertenecer a la API de Corte.');
  }
  final params = <String, String>{...uri.queryParameters};
  for (final entry in query.entries) {
    final value = entry.value;
    if (value == null || value == '') continue;
    if (value is List) {
      if (value.isEmpty) continue;
      params[entry.key] =
          (value.map((item) => item.toString()).toList()..sort()).join(',');
    } else if (value is bool) {
      params[entry.key] = value ? '1' : '0';
    } else if (value is String || value is num && value.isFinite) {
      params[entry.key] = value.toString();
    } else {
      throw ArgumentError('Parámetro de consulta inválido.');
    }
  }
  final sorted = SplayTreeMap<String, String>.from(params);
  return uri
      .replace(queryParameters: sorted.isEmpty ? null : sorted)
      .toString();
}

/// UUID v4 generated on the client for local objects and idempotent op_id.
String nuevoId() {
  final random = Random.secure();
  final bytes = List<int>.generate(16, (_) => random.nextInt(256));
  bytes[6] = (bytes[6] & 15) | 64;
  bytes[8] = (bytes[8] & 63) | 128;
  final hex = bytes
      .map((value) => value.toRadixString(16).padLeft(2, '0'))
      .join();
  return '${hex.substring(0, 8)}-${hex.substring(8, 12)}-${hex.substring(12, 16)}-${hex.substring(16, 20)}-${hex.substring(20)}';
}
