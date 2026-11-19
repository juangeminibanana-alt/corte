import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:http/http.dart' as http;

import '../data/http_adapter.dart';
import 'corte_runtime.dart';
import 'http_client_factory.dart';

export '../data/http_adapter.dart';

class CorteCancelToken {
  final _done = Completer<void>();
  bool get cancelled => _done.isCompleted;
  Future<void> get whenCancelled => _done.future;
  void cancel() {
    if (!_done.isCompleted) _done.complete();
  }
}

/// API e imágenes usan el mismo origen. Las credenciales se agregan aquí, nunca en widgets.
class CorteTransport implements CorteHttpAdapter {
  CorteTransport({
    CorteRuntime? runtime,
    http.Client? client,
    Future<String?> Function()? readBearer,
    Future<void> Function(String)? onNativeInvalidSession,
    void Function()? onWebInvalidSession,
    void Function(bool)? onConnectionChanged,
  }) : runtime = runtime ?? CorteRuntime.current(),
       _client = client ?? createPlatformHttpClient(),
       _readBearer = readBearer,
       _onNativeInvalidSession = onNativeInvalidSession,
       _onWebInvalidSession = onWebInvalidSession,
       _onConnectionChanged = onConnectionChanged;

  final CorteRuntime runtime;
  final http.Client _client;
  final Future<String?> Function()? _readBearer;
  final Future<void> Function(String)? _onNativeInvalidSession;
  final void Function()? _onWebInvalidSession;
  final void Function(bool)? _onConnectionChanged;
  bool _closed = false;
  final _active = <CorteCancelToken>{};
  Uri get baseUri => runtime.baseUri;

  Uri _uri(String path) {
    final Uri relative;
    try {
      relative = Uri.parse(path);
    } catch (_) {
      throw const CorteTransportException(
        'ruta_invalida',
        'La ruta solicitada no es válida.',
      );
    }
    List<String> rawSegments;
    try {
      rawSegments = path
          .split('?')
          .first
          .split('/')
          .skip(1)
          .map(Uri.decodeComponent)
          .toList();
    } catch (_) {
      throw const CorteTransportException(
        'ruta_invalida',
        'La ruta solicitada no es válida.',
      );
    }
    if (!path.startsWith('/') ||
        path.startsWith('//') ||
        relative.hasScheme ||
        relative.hasAuthority ||
        relative.hasFragment ||
        path.length > 8192 ||
        path.contains('\\') ||
        rawSegments.any(
          (s) =>
              s.isEmpty ||
              s == '.' ||
              s == '..' ||
              s.contains('/') ||
              s.contains('\\') ||
              RegExp(r'[\x00-\x1f\x7f]').hasMatch(s),
        ) ||
        RegExp(r'[\x00-\x1f\x7f]').hasMatch(path) ||
        relative.pathSegments.isEmpty ||
        !{'api', 'img'}.contains(relative.pathSegments.first) ||
        relative.pathSegments.any(
          (s) =>
              s.isEmpty ||
              s == '.' ||
              s == '..' ||
              s.contains('/') ||
              s.contains('\\') ||
              RegExp(r'[\x00-\x1f\x7f]').hasMatch(s),
        )) {
      throw const CorteTransportException(
        'ruta_invalida',
        'La ruta solicitada no es válida.',
      );
    }
    final result = baseUri.resolve(path);
    if (result.origin != baseUri.origin) {
      throw const CorteTransportException(
        'ruta_invalida',
        'El origen no es válido.',
      );
    }
    return result;
  }

  static String? _errorCode(Uint8List bytes) {
    try {
      final value = jsonDecode(utf8.decode(bytes));
      return value is Map &&
              value['error'] is Map &&
              value['error']['codigo'] is String
          ? value['error']['codigo'] as String
          : null;
    } catch (_) {
      return null;
    }
  }

  @override
  Future<CorteResponse> request(
    String method,
    String path, {
    Map<String, String> headers = const {},
    Object? body,
    Duration timeout = const Duration(seconds: 20),
    CorteCancelToken? cancelToken,
    int maxResponseBytes = 20 * 1024 * 1024,
  }) async {
    if (_closed) {
      throw const CorteTransportException(
        'cerrado',
        'La conexión ya se cerró.',
      );
    }
    final uri = _uri(path);
    method = method.toUpperCase();
    if (!{'GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE'}.contains(method)) {
      throw const CorteTransportException(
        'metodo_invalido',
        'Este método no está permitido.',
      );
    }
    if (cancelToken?.cancelled == true) {
      throw const CorteTransportException('cancelado', 'Petición cancelada.');
    }
    final unauthenticated = {
      '/api/native/auth/start',
      '/api/native/auth/poll',
      '/api/native/auth/google',
    }.contains(uri.path);
    final bearer = runtime.isWeb || unauthenticated
        ? null
        : await _readBearer?.call();
    final prepared = <String, String>{
      'Accept': 'application/json',
      'X-CH-Hub': '1',
    };
    for (final entry in headers.entries) {
      if ({
        'authorization',
        'cookie',
        'origin',
        'host',
        'x-ch-hub',
      }.contains(entry.key.toLowerCase())) {
        throw const CorteTransportException(
          'cabecera_invalida',
          'Esta cabecera se gestiona dentro de la aplicación.',
        );
      }
      prepared[entry.key] = entry.value;
    }
    if (!runtime.isWeb) prepared['Origin'] = baseUri.origin;
    if (bearer != null) prepared['Authorization'] = 'Bearer $bearer';
    if (!runtime.isWeb &&
        method == 'POST' &&
        uri.path == '/api/cloud/import' &&
        !prepared.keys.any(
          (k) => k.toLowerCase() == 'x-corte-expected-creator',
        )) {
      final identity = await request(
        'GET',
        '/api/native/session',
        timeout: timeout,
        cancelToken: cancelToken,
      );
      if (identity.statusCode != 200) return identity;
      Object? value;
      try {
        value = jsonDecode(utf8.decode(identity.bodyBytes));
      } catch (_) {
        value = null;
      }
      final creator = value is Map ? value['tiktok_open_id'] : null;
      if (creator is! String ||
          !RegExp(r'^[\x21-\x7e]{1,256}$').hasMatch(creator)) {
        throw const CorteTransportException(
          'cuenta_no_disponible',
          'Conecta tu cuenta de TikTok antes de importar.',
        );
      }
      prepared['X-Corte-Expected-Creator'] = creator;
    }
    Uint8List? payload;
    if (body != null) {
      try {
        payload = body is Uint8List
            ? body
            : Uint8List.fromList(utf8.encode(jsonEncode(body)));
      } catch (_) {
        throw const CorteTransportException(
          'cuerpo_invalido',
          'Los datos de la petición no son válidos.',
        );
      }
      final limit = uri.path == '/api/cloud/import'
          ? 20 * 1024 * 1024
          : {
              '/api/cloud/tiktok/import',
              '/api/cloud/display/import',
            }.contains(uri.path)
          ? 64 * 1024
          : 256 * 1024;
      if (payload.length > limit) {
        throw const CorteTransportException(
          'cuerpo_demasiado_grande',
          'Los datos superan el límite permitido.',
        );
      }
      prepared['Content-Type'] = 'application/json; charset=utf-8';
    }
    final abort = CorteCancelToken();
    _active.add(abort);
    var timedOut = false;
    final timer = Timer(timeout, () {
      timedOut = true;
      abort.cancel();
    });
    final trigger = cancelToken == null
        ? abort.whenCancelled
        : Future.any<void>([abort.whenCancelled, cancelToken.whenCancelled]);
    try {
      final request = http.AbortableRequest(method, uri, abortTrigger: trigger)
        ..followRedirects = false
        ..headers.addAll(prepared);
      if (payload != null) request.bodyBytes = payload;
      final response = await _client.send(request);
      final bytes = BytesBuilder(copy: false);
      await for (final chunk in response.stream) {
        if (bytes.length + chunk.length > maxResponseBytes) {
          abort.cancel();
          throw const CorteTransportException(
            'respuesta_demasiado_grande',
            'La respuesta supera el límite permitido.',
          );
        }
        bytes.add(chunk);
      }
      final result = CorteResponse(
        statusCode: response.statusCode,
        headers: response.headers,
        bodyBytes: bytes.takeBytes(),
      );
      if (!runtime.isWeb &&
          bearer != null &&
          result.statusCode == 401 &&
          _errorCode(result.bodyBytes) == 'sesion_nativa_invalida') {
        await _onNativeInvalidSession?.call(bearer);
      }
      if (runtime.isWeb &&
          result.statusCode == 401 &&
          _errorCode(result.bodyBytes) == 'sesion_requerida') {
        _onWebInvalidSession?.call();
      }
      if (result.statusCode >= 200 && result.statusCode < 400) {
        _onConnectionChanged?.call(true);
      } else if (result.statusCode == 503 &&
          _errorCode(result.bodyBytes) == 'identidad_no_disponible') {
        _onConnectionChanged?.call(false);
      }
      return result;
    } on CorteTransportException {
      rethrow;
    } on http.RequestAbortedException {
      throw CorteTransportException(
        timedOut ? 'tiempo_agotado' : 'cancelado',
        timedOut
            ? 'La petición tardó demasiado. Inténtalo de nuevo.'
            : 'Petición cancelada.',
      );
    } catch (_) {
      _onConnectionChanged?.call(false);
      throw const CorteTransportException(
        'sin_internet',
        'No pudimos conectar con CUTGC. Tu copia y tus cambios siguen guardados.',
      );
    } finally {
      timer.cancel();
      _active.remove(abort);
    }
  }

  Future<Uint8List> getImageBytes(
    String path, {
    CorteCancelToken? cancelToken,
  }) async {
    if (!_uri(path).path.startsWith('/img/')) {
      throw const CorteTransportException(
        'ruta_invalida',
        'No es una imagen de CUTGC.',
      );
    }
    final response = await request(
      'GET',
      path,
      headers: const {'Accept': 'image/*'},
      cancelToken: cancelToken,
      maxResponseBytes: 10 * 1024 * 1024,
    );
    if (response.statusCode != 200 ||
        !(response.headers['content-type'] ?? '').startsWith('image/')) {
      throw const CorteTransportException(
        'imagen_no_disponible',
        'No pudimos cargar esta imagen.',
      );
    }
    return response.bodyBytes;
  }

  @override
  void close() {
    if (_closed) return;
    _closed = true;
    for (final active in _active) {
      active.cancel();
    }
    _client.close();
  }
}
