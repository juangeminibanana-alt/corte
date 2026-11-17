import 'dart:async';
import 'dart:convert';

import 'package:crypto/crypto.dart';
import 'package:http/http.dart' as http;

import '../domain/corte_models.dart';

const publicProductMaxBytes = 4 * 1024 * 1024;
const publicProductTimeout = Duration(seconds: 15);

ErrorApi _sourceError(String code, String message) =>
    ErrorApi(codigo: code, mensaje: message, http: 503);

Uri _productUrl(String value, String id) {
  final uri = Uri.tryParse(value);
  final path = uri == null
      ? null
      : RegExp(
          r'^/mx/pdp/(?:[A-Za-z0-9_-]+/)?([0-9]{1,25})/?$',
        ).firstMatch(uri.path);
  if (value.length > 2048 ||
      value.codeUnits.any((c) => c < 33 || c > 126 || c == 92) ||
      uri == null ||
      uri.scheme != 'https' ||
      uri.host != 'shop.tiktok.com' ||
      uri.userInfo.isNotEmpty ||
      uri.port != 443 ||
      uri.hasFragment ||
      path == null ||
      path.group(1) != id) {
    throw _sourceError(
      'fuente_respuesta_invalida',
      'TikTok devolvió un enlace que no corresponde al producto.',
    );
  }
  return uri;
}

/// A separate, credential-free client for the native app's public Internet read.
/// It never receives the Google session, TikTok credentials or a shared cookie jar.
class CortePublicProductSource {
  CortePublicProductSource({http.Client? client, DateTime Function()? clock})
    : _client = client ?? http.Client(),
      _clock = clock ?? DateTime.now;
  final http.Client _client;
  final DateTime Function() _clock;

  Future<JsonMap> read(String id) async {
    try {
      if (!RegExp(r'^[0-9]{1,25}$').hasMatch(id)) {
        throw ErrorApi(
          codigo: 'parametros_invalidos',
          mensaje: 'El producto no es válido.',
          http: 422,
        );
      }
      return await _read(id).timeout(publicProductTimeout);
    } on ErrorApi {
      rethrow;
    } on TimeoutException {
      throw _sourceError(
        'fuente_no_disponible',
        'TikTok tardó demasiado en responder. Conservamos los datos guardados.',
      );
    } catch (_) {
      throw _sourceError(
        'fuente_no_disponible',
        'No pudimos consultar la ficha pública. Conservamos los datos guardados.',
      );
    } finally {
      // Closing also aborts a request whose deadline expired during streaming.
      _client.close();
    }
  }

  Future<JsonMap> _read(String id) async {
    var url = _productUrl('https://shop.tiktok.com/mx/pdp/$id', id);
    for (var redirects = 0; redirects <= 3; redirects++) {
      final request = http.Request('GET', url)..followRedirects = false;
      final response = await _client.send(request);
      if ({301, 302, 303, 307, 308}.contains(response.statusCode)) {
        final location = response.headers['location'];
        if (redirects == 3 || location == null) {
          throw _sourceError(
            'fuente_respuesta_invalida',
            'TikTok no devolvió una ficha pública válida.',
          );
        }
        url = _productUrl(url.resolve(location).toString(), id);
        continue;
      }
      if ({401, 403, 429}.contains(response.statusCode)) {
        throw _sourceError(
          'fuente_verificacion_requerida',
          'TikTok solicita verificar el acceso a esta ficha. Conservamos los datos guardados.',
        );
      }
      if (response.statusCode != 200) {
        throw _sourceError(
          'fuente_no_disponible',
          'La ficha pública no está disponible en este momento.',
        );
      }
      final type = response.headers['content-type']
          ?.split(';')
          .first
          .trim()
          .toLowerCase();
      if (!{'text/html', 'application/xhtml+xml'}.contains(type) ||
          (response.contentLength != null &&
              response.contentLength! > publicProductMaxBytes)) {
        throw _sourceError(
          'fuente_respuesta_invalida',
          'TikTok no devolvió una ficha pública válida.',
        );
      }
      final bytes = <int>[];
      await for (final chunk in response.stream) {
        if (bytes.length + chunk.length > publicProductMaxBytes) {
          throw _sourceError(
            'fuente_respuesta_invalida',
            'La ficha pública supera el tamaño permitido.',
          );
        }
        bytes.addAll(chunk);
      }
      return parsePublicProductPage(
        utf8.decode(bytes, allowMalformed: true),
        productId: id,
        sourceUrl: url.toString(),
        now: _clock().millisecondsSinceEpoch ~/ 1000,
      );
    }
    throw _sourceError(
      'fuente_respuesta_invalida',
      'TikTok no devolvió una ficha pública válida.',
    );
  }
}

Map<String, dynamic> _map(Object? value) =>
    value is Map<String, dynamic> ? value : <String, dynamic>{};

String? _text(Object? value, int maximum) {
  if (value is! String) return null;
  final clean = value
      .replaceAll(RegExp(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]'), '')
      .trim();
  if (clean.isEmpty) return null;
  return clean.length <= maximum ? clean : clean.substring(0, maximum);
}

int? _integer(Object? value, {int minimum = 0, int maximum = 1000000000}) {
  final parsed = value is int
      ? value
      : value is String && RegExp(r'^[0-9]{1,15}$').hasMatch(value)
      ? int.tryParse(value)
      : null;
  return parsed != null && parsed >= minimum && parsed <= maximum
      ? parsed
      : null;
}

num? _average(Object? value) =>
    value is num && value.isFinite && value >= 1 && value <= 5 ? value : null;

int? _reviewTime(Object? value, int now) {
  var stamp = _integer(value, minimum: 1, maximum: 99999999999999);
  if (stamp == null) return null;
  if (stamp >= 100000000000) stamp ~/= 1000;
  return stamp <= now + 300 ? stamp : null;
}

List<String> _images(Object? value, {int maximum = 10}) {
  if (value is! List) return [];
  final result = <String>[];
  for (final item in value.take(100)) {
    if (item is! String ||
        item.length > 4096 ||
        item.codeUnits.any((c) => c < 33 || c > 126 || c == 92))
      continue;
    final uri = Uri.tryParse(item);
    if (uri == null ||
        uri.scheme != 'https' ||
        uri.port != 443 ||
        uri.userInfo.isNotEmpty ||
        uri.hasFragment ||
        ![
          '.ibyteimg.com',
          '.byteimg.com',
          '.tiktokcdn.com',
          '.tiktokcdn-us.com',
        ].any((suffix) => uri.host.endsWith(suffix)))
      continue;
    if (!result.contains(item)) result.add(item);
    if (result.length >= maximum) break;
  }
  return result;
}

JsonMap? _review(Object? value, String id, int now) {
  final item = _map(value);
  if (item.isEmpty ||
      item.containsKey('product_id') && item['product_id'] != id)
    return null;
  final text = _text(item['review_text'], 5000) ?? '';
  final rating = _integer(item['review_rating'], minimum: 1, maximum: 5);
  final images = _images(item['review_images']);
  if (text.isEmpty && rating == null && images.isEmpty) return null;
  final day = _reviewTime(item['review_time'], now);
  final variant = _text(item['sku_specification'], 200);
  var reviewId = item['review_id'];
  if (reviewId is! String ||
      !RegExp(r'^[A-Za-z0-9_-]{1,128}$').hasMatch(reviewId)) {
    final canonicalImages = images.map((url) {
      final uri = Uri.parse(url);
      return '${uri.host}${uri.path}';
    }).toList();
    reviewId =
        'public-${sha256.convert(utf8.encode(jsonEncode([id, text, rating, day, variant, canonicalImages]))).toString().substring(0, 32)}';
  }
  return {
    'id': reviewId,
    'texto': text,
    'estrellas': rating,
    'fecha': day,
    'variante': variant,
    'compra_verificada': item['is_verified_purchase'] is bool
        ? item['is_verified_purchase']
        : null,
    'imagenes': images,
  };
}

/// Pure parser of the observed public MX SSR data. No JavaScript is executed.
/// Unavailable blocks are omitted so an update preserves previously saved data.
JsonMap parsePublicProductPage(
  String html, {
  required String productId,
  required String sourceUrl,
  required int now,
}) {
  if (!RegExp(r'^[0-9]{1,25}$').hasMatch(productId) ||
      utf8.encode(html).length > publicProductMaxBytes) {
    throw _sourceError(
      'fuente_respuesta_invalida',
      'La ficha pública no tiene el formato permitido.',
    );
  }
  var canonical = _productUrl(
    sourceUrl,
    productId,
  ).replace(query: null).toString().split('?').first;
  if (RegExp(
    r'<title\b[^>]*>\s*(?:security check|captcha|access denied|just a moment)',
    caseSensitive: false,
  ).hasMatch(html)) {
    throw _sourceError(
      'fuente_verificacion_requerida',
      'TikTok solicita verificar el acceso a esta ficha.',
    );
  }
  final scripts =
      RegExp(r'<script\b([^>]*)>([\s\S]*?)</script\s*>', caseSensitive: false)
          .allMatches(html)
          .where(
            (match) => RegExp(
              r'''(?:^|\s)id\s*=\s*(["'])__MODERN_ROUTER_DATA__\1(?=\s|$)''',
              caseSensitive: false,
            ).hasMatch(match.group(1)!),
          )
          .toList();
  if (scripts.length != 1) {
    throw _sourceError(
      'fuente_sin_datos',
      'La ficha no ofrece datos públicos de tallas o reseñas que Corte pueda leer.',
    );
  }
  final JsonMap data;
  try {
    data = _map(jsonDecode(scripts.single.group(2)!));
  } catch (_) {
    throw _sourceError(
      'fuente_respuesta_invalida',
      'TikTok devolvió información pública inválida.',
    );
  }
  JsonMap? component;
  for (final pageValue in _map(data['loaderData']).values.take(20)) {
    final page = _map(pageValue),
        components = _map(_map(pageValue)['page_config'])['components_map'];
    if (components is! List) continue;
    for (final candidate in components.take(100)) {
      final value = _map(_map(candidate)['component_data']);
      if (_map(value['product_info'])['product_id'] != productId) continue;
      final route = _map(page['route_info']);
      if ((route['route_product_id'] ?? productId) != productId) {
        throw _sourceError(
          'fuente_respuesta_invalida',
          'La ficha pública corresponde a otro producto.',
        );
      }
      if (route['canonical_url'] is String) {
        canonical = _productUrl(
          route['canonical_url'],
          productId,
        ).toString().split('?').first;
      }
      component = value;
      break;
    }
    if (component != null) break;
  }
  if (component == null)
    throw _sourceError(
      'fuente_sin_datos',
      'No encontramos información pública de este producto.',
    );
  final product = _map(component['product_info']);
  final source = {
    'tipo': 'captura_tiktok',
    'url': canonical,
    'nombre': 'TikTok Shop México',
  };
  final header = {
    'estado': 'disponible',
    'fuente': source,
    'consultado_at': now,
  };
  final result = <String, dynamic>{};
  final chartImages = _images(
    _map(_map(product['size_guide'])['image'])['url_list'],
    maximum: 1,
  );
  if (chartImages.isNotEmpty) {
    result['tabla_tallas'] = {
      ...header,
      'tabla': {
        'columnas': <String>[],
        'filas': <List<String>>[],
        'unidad': null,
        'imagenes': chartImages,
      },
    };
  }
  final reviews = _map(component['review_info']),
      ratings = _map(_map(component['review_info'])['review_ratings']);
  var total =
      _integer(reviews['total_reviews']) ?? _integer(ratings['review_count']);
  var average =
      _average(ratings['overall_score']) ??
      _average(_map(product['review'])['product_rating']);
  final rows = <JsonMap>[], seen = <String>{};
  final original = reviews['product_reviews'];
  for (final value in original is List ? original.take(1000) : const []) {
    final row = _review(value, productId, now);
    if (row != null && seen.add(row['id'] as String)) rows.add(row);
    if (rows.length >= 100) break;
  }
  if (total != null && total < rows.length) total = null;
  if (total == 0) average = null;
  if (rows.isNotEmpty ||
      total != null ||
      reviews.isNotEmpty && average != null) {
    result['resenas'] = {
      ...header,
      'promedio': average,
      'total': total,
      'items': rows,
    };
  }
  if (result.isEmpty)
    throw _sourceError(
      'fuente_sin_datos',
      'Esta ficha no proporciona una tabla o reseñas legibles.',
    );
  while (utf8.encode(jsonEncode(result)).length > 180 * 1024) {
    if (rows.isEmpty)
      throw _sourceError(
        'fuente_respuesta_invalida',
        'La información pública supera el tamaño permitido.',
      );
    rows.removeLast();
  }
  return immutableJson(result);
}
