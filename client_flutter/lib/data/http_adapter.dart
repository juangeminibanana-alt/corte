import 'dart:typed_data';

/// A bounded video upload. The transport selects multipart or raw bytes from the endpoint.
class CorteVideoBytes {
  const CorteVideoBytes(this.bytes, {this.filename});
  final Uint8List bytes;
  final String? filename;
}

/// Platform code owns HTTPS, session cookies/native credentials and cancellation.
/// Business repositories never receive an access token or creator identity.
abstract interface class CorteHttpAdapter {
  Future<CorteResponse> request(
    String method,
    String path, {
    Map<String, String> headers = const {},
    Object? body,
  });

  void close();
}

class CorteResponse {
  CorteResponse({
    required this.statusCode,
    required Map<String, String> headers,
    required Uint8List bodyBytes,
  }) : headers = Map.unmodifiable({
         for (final entry in headers.entries)
           entry.key.toLowerCase(): entry.value,
       }),
       bodyBytes = Uint8List.fromList(bodyBytes);

  final int statusCode;
  final Map<String, String> headers;
  final Uint8List bodyBytes;
}

/// Sanitized transport failure: never includes headers, response bodies or URLs.
class CorteTransportException implements Exception {
  const CorteTransportException(this.codigo, this.mensaje);

  final String codigo;
  final String mensaje;

  @override
  String toString() => mensaje;
}
