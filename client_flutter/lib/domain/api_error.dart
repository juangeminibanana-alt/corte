import 'corte_json.dart';

class ErrorApi implements Exception {
  ErrorApi({
    required this.codigo,
    required this.mensaje,
    this.http = 0,
    JsonMap? detalle,
    JsonMap? vigente,
    this.reintentarEnS,
  }) : detalle = detalle == null ? null : immutableJson(detalle),
       vigente = vigente == null ? null : immutableJson(vigente);

  final String codigo;
  final String mensaje;
  final int http;
  final JsonMap? detalle;
  final JsonMap? vigente;
  final int? reintentarEnS;

  bool get esConflicto => http == 409 || codigo == 'conflicto';
  bool get esAutenticacion => http == 401;
  bool get esTransitorio =>
      (http == 0 &&
          const [
            'red',
            'sin_internet',
            'timeout',
            'tiempo_agotado',
          ].contains(codigo)) ||
      http == 408 ||
      http == 429 ||
      http >= 500;

  @override
  String toString() => mensaje;
}
