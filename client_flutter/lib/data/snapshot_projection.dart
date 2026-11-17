import 'dart:convert';
import '../domain/corte_models.dart';

/// Private offline views. The complete snapshot remains unchanged; only pending
/// user operations are overlaid. Rejected/conflicting operations never overlay.
JsonMap? proyectarSnapshot(
  String canonicalUrl,
  JsonMap snapshot, {
  List<JsonMap> outbox = const [],
}) {
  if (snapshot['version_esquema'] != 1 || snapshot['local'] is! Map)
    return null;
  final uri = Uri.tryParse(canonicalUrl);
  if (uri == null) return null;
  final path = uri.path;
  final query = uri.queryParameters;
  final local = _localConOps(jsonMap(snapshot['local']), outbox);
  final samples = jsonObjects(
    snapshot['muestras'],
  ).map((sample) => _muestraConLocal(sample, local)).toList();
  final extras = snapshot['extras'] is Map
      ? jsonMap(snapshot['extras'])
      : <String, dynamic>{};
  final meta = {
    'data_version': snapshot['data_version'],
    'local_rev': snapshot['local_rev'],
    'img_rev': snapshot['img_rev'],
    'meta_imagenes': snapshot['meta_imagenes'] ?? <String, dynamic>{},
  };
  JsonMap result(JsonMap value) => immutableJson({...meta, ...value});
  List<JsonMap> list(String key) => jsonObjects(local[key]);
  List<JsonMap> notes(String entity, String id) => list('notas')
      .where((item) => item['entidad'] == entity && item['entidad_id'] == id)
      .toList();
  if (path == '/api/snapshot')
    return immutableJson({...snapshot, 'local': local, 'muestras': samples});
  if (path == '/api/preferencias')
    return immutableJson(jsonMap(local['preferencias'] ?? {}));
  if (path == '/api/dashboard' ||
      path == '/api/analitica/productos' ||
      path == '/api/analitica/videos' ||
      path == '/api/tiendas' ||
      path.startsWith('/api/tiendas/') ||
      path.startsWith('/api/videos/') ||
      path == '/api/ordenes') {
    final business = _vistasNegocio(uri, snapshot, samples, local);
    return business == null ? null : result(business);
  }
  final localLists = {
    '/api/plan': 'planes',
    '/api/notas': 'notas',
    '/api/recordatorios': 'recordatorios',
    '/api/avisos': 'avisos',
    '/api/plantillas': 'plantillas',
  };
  if (localLists.containsKey(path)) {
    var items = list(localLists[path]!);
    if (path == '/api/plan') {
      items = items.where((item) {
        final day = item['fecha_plan'];
        return (query['desde'] == null ||
                day is String && day.compareTo(query['desde']!) >= 0) &&
            (query['hasta'] == null ||
                day is String && day.compareTo(query['hasta']!) <= 0);
      }).toList();
    } else if (path == '/api/notas') {
      items = items
          .where(
            (item) =>
                (query['entidad'] == null ||
                    item['entidad'] == query['entidad']) &&
                (query['entidad_id'] == null ||
                    item['entidad_id'] == query['entidad_id']),
          )
          .toList();
    } else if (path == '/api/recordatorios') {
      items = items
          .where(
            (item) =>
                query['estado'] == null || item['estado'] == query['estado'],
          )
          .toList();
    } else if (path == '/api/avisos') {
      items = items
          .where(
            (item) =>
                (query['tienda'] == null ||
                    item['tienda_key'] == query['tienda']) &&
                (query['solicitud'] == null ||
                    (item['solicitud_ids'] as List? ?? []).contains(
                      query['solicitud'],
                    )),
          )
          .toList();
    }
    return result({'items': items});
  }
  if (path == '/api/muestras') {
    final counts = <String, int>{}, groups = <String, int>{};
    for (final item in samples) {
      final type = item['clase'];
      final group = item['grupo'];
      if (type is String) counts[type] = (counts[type] ?? 0) + 1;
      if (group is String) groups[group] = (groups[group] ?? 0) + 1;
    }
    var items = samples.where((item) {
      final store = item['tienda'] is Map
          ? jsonMap(item['tienda'])
          : <String, dynamic>{};
      final product = item['producto'] is Map
          ? jsonMap(item['producto'])
          : <String, dynamic>{};
      final search = query['q']?.trim().toLowerCase();
      return (query['grupo'] == null ||
              query['grupo']!.split(',').contains(item['grupo'])) &&
          (query['clase'] == null ||
              query['clase']!.split(',').contains(item['clase'])) &&
          (query['tienda'] == null || store['tienda_key'] == query['tienda']) &&
          (query['recibidas'] == null ||
              item['recibida'] == (query['recibidas'] == '1')) &&
          (search == null ||
              search.isEmpty ||
              '${product['titulo'] ?? ''} ${product['titulo_corto'] ?? ''} ${store['nombre'] ?? ''} ${item['variante'] ?? ''}'
                  .toLowerCase()
                  .contains(search));
    }).toList();
    final order = query['orden'];
    if (order == 'solicitud_asc' || order == 'solicitud_desc') {
      items.sort(
        (a, b) =>
            ((a['solicitada_at'] as int? ?? 0) -
                (b['solicitada_at'] as int? ?? 0)) *
            (order == 'solicitud_desc' ? -1 : 1),
      );
    } else if (order == 'tienda') {
      items.sort(
        (a, b) => '${(a['tienda'] as Map?)?['nombre'] ?? ''}'.compareTo(
          '${(b['tienda'] as Map?)?['nombre'] ?? ''}',
        ),
      );
    } else if (order == 'valor_desc') {
      items.sort(
        (a, b) =>
            (((b['producto'] as Map?)?['precio_venta_min_centavos'] as int?) ??
                    0)
                .compareTo(
                  ((a['producto'] as Map?)?['precio_venta_min_centavos']
                          as int?) ??
                      0,
                ),
      );
    }
    return result({
      'items': items,
      'total': items.length,
      'conteos': counts,
      'por_grupo': groups,
    });
  }
  if (uri.pathSegments.length == 3 && path.startsWith('/api/muestras/')) {
    final id = uri.pathSegments.last;
    final matching = samples.where((item) => item['application_id'] == id);
    if (matching.isEmpty) return null;
    final sample = matching.first;
    final extra = (extras['muestras'] as Map?)?[id];
    if (extra is! Map)
      return null; // Missing history is incomplete, not an empty history.
    final store = (sample['tienda'] as Map?)?['tienda_key'];
    return result({
      'muestra': sample,
      'historial': extra['historial'] ?? [],
      'plantilla_sugerida': extra['plantilla_sugerida'],
      'videos_del_producto': extra['videos_del_producto'] ?? [],
      'notas': notes('muestra', id),
      'planes': list(
        'planes',
      ).where((item) => item['application_id'] == id).toList(),
      'recordatorios': list('recordatorios')
          .where(
            (item) => item['entidad'] == 'muestra' && item['entidad_id'] == id,
          )
          .toList(),
      'avisos': list('avisos')
          .where((item) => (item['solicitud_ids'] as List? ?? []).contains(id))
          .toList(),
      'otras_de_la_tienda': samples
          .where(
            (item) =>
                item['application_id'] != id &&
                (item['tienda'] as Map?)?['tienda_key'] == store,
          )
          .map(
            (item) => {
              'application_id': item['application_id'],
              'grupo': item['grupo'],
              'etiqueta': item['etiqueta'],
              'producto': item['producto'],
            },
          )
          .toList(),
    });
  }
  if (uri.pathSegments.length == 4 && path.startsWith('/api/productos/')) {
    final id = uri.pathSegments[2];
    final stored = (extras['productos'] as Map?)?[id];
    if (stored is! Map) return null;
    final extended = jsonMap(stored);
    if (uri.pathSegments.last == 'evidencia') {
      return result({
        'product_id': id,
        'rev': extended['evidencia_rev'] ?? 0,
        'tabla_tallas': extended['tabla_tallas'],
        'resenas': extended['resenas'],
      });
    }
    if (uri.pathSegments.last == 'resenas' &&
        (query['cursor'] == null || query['cursor'] == '0')) {
      return result({
        'product_id': id,
        'rev': extended['evidencia_rev'] ?? 0,
        'resenas': extended['resenas'],
      });
    }
    // A first-page snapshot cannot prove the contents of subsequent pages.
    return null;
  }
  if (uri.pathSegments.length == 3 && path.startsWith('/api/productos/')) {
    final id = uri.pathSegments.last;
    final matches = samples
        .where((item) => (item['producto'] as Map?)?['product_id'] == id)
        .toList();
    final rows = jsonObjects(
      snapshot['productos'],
    ).where((item) => item['product_id'] == id);
    if (matches.isEmpty && rows.isEmpty) return null;
    final extended = (extras['productos'] as Map?)?[id];
    return result({
      'product_id': id,
      'ficha': matches.isEmpty ? null : matches.first['producto'],
      'con_inventario': null,
      'categoria_ruta': null,
      'comision_anuncios_bp': null,
      'fila': rows.isEmpty ? null : rows.first,
      'serie': [],
      'videos': jsonObjects(snapshot['videos'])
          .where(
            (item) => (_productosVideos(snapshot)[id] ?? <String>{}).contains(
              item['content_id'],
            ),
          )
          .toList(),
      'muestras': matches,
      'notas': notes('producto', id),
      if (extended is Map) 'extendido': extended,
    });
  }
  // Date-filtered sales/detail series are intentionally unavailable when the
  // snapshot cannot prove coverage. Never claim a truncated result is complete.
  return null;
}

/// Overlay only local fields on a fresh server response. Business metrics and
/// histories always retain their server representation.
JsonMap aplicarPendientes(String url, JsonMap data, List<JsonMap> outbox) {
  if (outbox.isEmpty) return data;
  final uri = Uri.parse(url);
  const localPaths = {
    '/api/plan': 'planes',
    '/api/notas': 'notas',
    '/api/recordatorios': 'recordatorios',
    '/api/avisos': 'avisos',
    '/api/plantillas': 'plantillas',
  };
  if (uri.path == '/api/snapshot')
    return proyectarSnapshot(url, data, outbox: outbox) ?? data;
  if (uri.path == '/api/preferencias')
    return immutableJson(
      jsonMap(_localConOps({'preferencias': data}, outbox)['preferencias']),
    );
  final key = localPaths[uri.path];
  if (key != null) {
    final projected = proyectarSnapshot(url, {
      'version_esquema': 1,
      'muestras': [],
      'local': {key: data['items'] ?? []},
    }, outbox: outbox);
    return immutableJson({
      ...data,
      if (projected != null) 'items': projected['items'],
    });
  }
  if (uri.path == '/api/muestras') {
    final samples = jsonObjects(data['items']);
    final seedPlans = <JsonMap>[];
    for (final sample in samples) {
      final advance = sample['avance'];
      if (advance is Map && advance['plan_id'] != null) {
        seedPlans.add({
          ...jsonMap(advance),
          'id': advance['plan_id'],
          'application_id': sample['application_id'],
          'estado': advance['etapa'],
          'fecha_plan': advance['fecha_planeada'],
        });
      }
    }
    final local = _localConOps({'planes': seedPlans}, outbox);
    return immutableJson({
      ...data,
      'items': samples
          .map((sample) => _muestraConLocal(sample, local))
          .toList(),
    });
  }
  if (uri.pathSegments.length == 3) {
    final local = _localConOps({
      for (final k in ['planes', 'notas', 'recordatorios', 'avisos'])
        k: data[k] ?? [],
    }, outbox);
    final entity = {
      'muestras': 'muestra',
      'tiendas': 'tienda',
      'productos': 'producto',
      'videos': 'video',
      'ordenes': 'orden',
    }[uri.pathSegments[1]];
    if (entity != null) {
      final id = uri.pathSegments.last;
      return immutableJson({
        ...data,
        for (final k in ['planes', 'notas', 'recordatorios', 'avisos'])
          if (data.containsKey(k))
            k: jsonObjects(local[k])
                .where(
                  (item) => k == 'planes'
                      ? item['application_id'] == id
                      : k == 'avisos'
                      ? (entity == 'tienda'
                            ? item['tienda_key'] == id
                            : (item['solicitud_ids'] as List? ?? []).contains(
                                id,
                              ))
                      : item['entidad'] == entity && item['entidad_id'] == id,
                )
                .toList(),
        if (data['muestra'] is Map)
          'muestra': _muestraConLocal(jsonMap(data['muestra']), local),
      });
    }
  }
  return data;
}

/// Fold acknowledged canonical server objects into the private base before
/// removing their outbox entries. This survives an offline restart after ACK.
JsonMap snapshotConResultados(
  JsonMap snapshot,
  List<JsonMap> envelopes,
  Map<Object?, JsonMap> results,
) {
  final local = jsonMap(jsonDecode(jsonEncode(snapshot['local'] ?? {})));
  const keys = {
    'plan': 'planes',
    'nota': 'notas',
    'recordatorio': 'recordatorios',
    'aviso': 'avisos',
    'plantilla': 'plantillas',
  };
  for (final envelope in envelopes) {
    final op = jsonMap(envelope['op']);
    final result = results[op['op_id']];
    if (result == null ||
        !const ['aplicada', 'duplicada'].contains(result['estado']))
      continue;
    final type = '${op['tipo']}';
    if (type == 'preferencias.editar') {
      if (result['objeto'] is Map) local['preferencias'] = result['objeto'];
      continue;
    }
    final key = keys[type.split('.').first];
    if (key == null) continue;
    final items = jsonObjects(local[key]).toList();
    final object = result['objeto'];
    final id = op['id'] ?? (op['datos'] as Map?)?['id'];
    if (type.endsWith('.borrar')) {
      items.removeWhere((item) => item['id'] == id);
    } else if (object is Map) {
      final canonical = jsonMap(object);
      final index = items.indexWhere((item) => item['id'] == canonical['id']);
      if (index < 0) {
        items.add(canonical);
      } else {
        items[index] = canonical;
      }
    }
    local[key] = items;
  }
  return immutableJson({...snapshot, 'local': local});
}

JsonMap _localConOps(JsonMap source, List<JsonMap> outbox) {
  final local = jsonMap(jsonDecode(jsonEncode(source)));
  const keys = {
    'plan': 'planes',
    'nota': 'notas',
    'recordatorio': 'recordatorios',
    'aviso': 'avisos',
    'plantilla': 'plantillas',
  };
  for (final envelope in outbox) {
    if (envelope.containsKey('op') && envelope['estado'] != 'pendiente')
      continue;
    final operation = jsonMap(envelope['op'] ?? envelope);
    final type = operation['tipo'];
    if (type is! String) continue;
    final parts = type.split('.');
    if (parts.length != 2) continue;
    final changes = operation['cambios'] is Map
        ? jsonMap(operation['cambios'])
        : <String, dynamic>{};
    if (type == 'preferencias.editar') {
      final before = jsonMap(local['preferencias'] ?? {});
      local['preferencias'] = {
        ...before,
        ...changes,
        'rev': (changes['rev'] as int? ?? before['rev'] as int? ?? 0) + 1,
      };
      continue;
    }
    final key = keys[parts.first];
    if (key == null) continue;
    final list = jsonObjects(local[key]).toList();
    if (parts.last == 'crear') {
      final values = jsonMap(operation['datos']);
      if (!list.any((item) => item['id'] == values['id'])) {
        list.add({
          'rev': 1,
          if (parts.first == 'plan') 'estado': 'por_planear',
          if (parts.first == 'recordatorio') ...{
            'estado': 'activo',
            'repetir': 'no',
            'pospuesto_hasta': null,
          },
          if (parts.first == 'nota') 'fijada': false,
          ...values,
        });
      }
    } else if (parts.last == 'borrar') {
      list.removeWhere((item) => item['id'] == operation['id']);
    } else if (parts.last == 'editar') {
      final index = list.indexWhere((item) => item['id'] == operation['id']);
      if (index >= 0)
        list[index] = {
          ...list[index],
          ...changes,
          'rev':
              (changes['rev'] as int? ?? list[index]['rev'] as int? ?? 0) + 1,
        };
    }
    local[key] = list;
  }
  return local;
}

Map<String, Set<String>> _productosVideos(JsonMap snapshot) {
  final result = <String, Set<String>>{};
  void add(Object? product, Object? video) {
    if (product is String && video is String) {
      (result[product] ??= <String>{}).add(video);
    }
  }

  for (final order in jsonObjects(snapshot['ordenes_recientes'])) {
    for (final line in jsonObjects(order['lineas'])) {
      add(line['product_id'], line['content_id']);
    }
  }
  final extras = (snapshot['extras'] as Map?)?['muestras'];
  if (extras is Map) {
    for (final sample in jsonObjects(snapshot['muestras'])) {
      final extra = extras[sample['application_id']];
      if (extra is Map) {
        for (final video in jsonObjects(extra['videos_del_producto'])) {
          add((sample['producto'] as Map?)?['product_id'], video['content_id']);
        }
      }
    }
  }
  return result;
}

JsonMap? _vistasNegocio(
  Uri uri,
  JsonMap snapshot,
  List<JsonMap> samples,
  JsonMap local,
) {
  final path = uri.path, query = uri.queryParameters;
  final dashboards = snapshot['dashboard'] as Map?;
  if (path == '/api/dashboard') {
    final value = dashboards?[query['periodo'] ?? '30d'];
    return value is Map ? jsonMap(value) : null;
  }
  final period = (dashboards?['todo'] as Map?)?['periodo'] as Map?;
  final fullRange =
      (query['desde'] == null ||
          period?['desde'] is String &&
              query['desde']!.compareTo(period!['desde'] as String) <= 0) &&
      (query['hasta'] == null ||
          period?['hasta'] is String &&
              query['hasta']!.compareTo(period!['hasta'] as String) >= 0);
  if (path == '/api/analitica/productos' ||
      path == '/api/analitica/videos' ||
      path == '/api/tiendas') {
    if (!fullRange) return null;
    final key = path.endsWith('videos')
        ? 'videos'
        : path.endsWith('productos')
        ? 'productos'
        : 'tiendas';
    var items = jsonObjects(snapshot[key]);
    // The snapshot's top 100 cannot prove that the complete video list fits.
    if (key == 'videos' && items.length >= 100) return null;
    final total = items.length;
    final limit = int.tryParse(query['limite'] ?? '');
    if (limit != null) items = items.take(limit.clamp(0, 1000)).toList();
    return {'items': items, 'total': total};
  }
  if (uri.pathSegments.length == 3 && path.startsWith('/api/tiendas/')) {
    if (!fullRange) return null;
    final id = uri.pathSegments.last;
    final stores = jsonObjects(
      snapshot['tiendas'],
    ).where((item) => item['tienda_key'] == id);
    if (stores.isEmpty) return null;
    final extra = ((snapshot['extras'] as Map?)?['tiendas'] as Map?)?[id];
    return {
      'tienda': stores.first,
      'muestras': samples
          .where((item) => (item['tienda'] as Map?)?['tienda_key'] == id)
          .toList(),
      'serie': extra is Map ? extra['serie'] ?? [] : [],
      'productos': jsonObjects(
        snapshot['productos'],
      ).where((item) => item['tienda_key'] == id).toList(),
      'notas': jsonObjects(local['notas'])
          .where(
            (item) => item['entidad'] == 'tienda' && item['entidad_id'] == id,
          )
          .toList(),
      'avisos': jsonObjects(
        local['avisos'],
      ).where((item) => item['tienda_key'] == id).toList(),
      'plantilla_sugerida': extra is Map ? extra['plantilla_sugerida'] : null,
    };
  }
  if (uri.pathSegments.length == 3 && path.startsWith('/api/videos/')) {
    final id = uri.pathSegments.last;
    final rows = jsonObjects(
      snapshot['videos'],
    ).where((item) => item['content_id'] == id);
    if (rows.isEmpty) return null;
    final ids = _productosVideos(snapshot).entries
        .where((item) => item.value.contains(id))
        .map((item) => item.key)
        .toSet();
    return {
      'video': rows.first,
      'serie': [],
      'productos': jsonObjects(
        snapshot['productos'],
      ).where((item) => ids.contains(item['product_id'])).toList(),
    };
  }
  if (path != '/api/ordenes') return null;
  final generated = snapshot['generado_at'], from = query['desde'];
  if (generated is! int || from == null) return null;
  final today = DateTime.fromMillisecondsSinceEpoch(
    generated * 1000,
    isUtc: true,
  ).subtract(const Duration(hours: 6));
  String day(DateTime d) =>
      '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';
  final orders = jsonObjects(snapshot['ordenes_recientes']);
  var covered = day(today.subtract(const Duration(days: 89)));
  if (orders.length >= 500) {
    final dates =
        orders.map((item) => item['fecha']).whereType<String>().toList()
          ..sort();
    if (dates.isEmpty) return null;
    final oldest = DateTime.tryParse(dates.first);
    if (oldest == null) return null;
    final next = day(oldest.add(const Duration(days: 1)));
    if (next.compareTo(covered) > 0) covered = next;
  }
  if (from.compareTo(covered) < 0 || from.compareTo(day(today)) > 0)
    return null;
  var items =
      orders.where((item) {
        final date = item['fecha'], lines = jsonObjects(item['lineas']);
        if (date is! String ||
            date.compareTo(from) < 0 ||
            query['hasta'] != null && date.compareTo(query['hasta']!) > 0)
          return false;
        if (query['estado'] != null &&
            !query['estado']!.split(',').contains(item['estado']))
          return false;
        for (final filter in ['producto', 'video', 'tienda']) {
          if (query[filter] == null) continue;
          if (!lines.any(
            (line) => filter == 'tienda'
                ? '${line['tienda_nombre'] ?? ''}'
                          .trim()
                          .replaceAll(RegExp(r'\s+'), ' ')
                          .toLowerCase() ==
                      query[filter]
                : line[filter == 'producto' ? 'product_id' : 'content_id'] ==
                      query[filter],
          ))
            return false;
        }
        final search = query['q']?.trim().toLowerCase();
        return search == null ||
            search.isEmpty ||
            '${item['order_id']} ${lines.map((line) => '${line['producto']} ${line['tienda_nombre']} ${line['product_id']}').join(' ')}'
                .toLowerCase()
                .contains(search);
      }).toList()..sort(
        (a, b) => (b['creada_at'] as int? ?? 0).compareTo(
          a['creada_at'] as int? ?? 0,
        ),
      );
  final total = items.length,
      page = (int.tryParse(query['pagina'] ?? '') ?? 1).clamp(1, 1000000),
      size = (int.tryParse(query['por_pagina'] ?? '') ?? 50).clamp(1, 200);
  items = items.skip((page - 1) * size).take(size).toList();
  return {'items': items, 'total': total, 'pagina': page, 'por_pagina': size};
}

JsonMap _muestraConLocal(JsonMap source, JsonMap local) {
  final plans = jsonObjects(
    local['planes'],
  ).where((plan) => plan['application_id'] == source['application_id']);
  if (plans.isEmpty) return source;
  final plan = plans.first;
  return {
    ...source,
    'avance': {
      ...?source['avance'] as Map?,
      'plan_id': plan['id'],
      'etapa': plan['estado'],
      'fecha_planeada': plan['fecha_plan'],
      'programada_para_at': plan['programada_para_at'],
      'fecha_publicada': plan['fecha_publicada'],
      'content_id': plan['content_id'],
      'vinculo_origen': plan['vinculo_origen'],
      'fijada': plan['fijada'] ?? false,
      'rev': plan['rev'],
    },
  };
}
