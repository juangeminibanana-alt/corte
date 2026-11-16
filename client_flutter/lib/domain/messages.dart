import 'corte_json.dart';

const variablesMensaje = {
  'tienda',
  'producto',
  'fecha_compromiso',
  'fecha_anterior',
  'link_video',
  'lista_productos',
  'lista_fechas',
  'agradecimiento_socio',
  'problema_envio',
  'firma',
};

class MensajeResuelto {
  MensajeResuelto(this.texto, Iterable<String> faltantes)
    : faltantes = Set.unmodifiable(faltantes);
  final String texto;
  final Set<String> faltantes;
  bool get puedeCopiar => faltantes.isEmpty && texto.trim().isNotEmpty;
}

String nombreProductoMensaje(JsonMap sample) {
  final product = sample['producto'] is Map
      ? jsonMap(sample['producto'])
      : <String, dynamic>{};
  for (final key in ['titulo', 'titulo_corto']) {
    final value = product[key];
    if (value is String && value.trim().isNotEmpty) return value.trim();
  }
  return 'su producto';
}

String fechaMensaje(String value) {
  final date = DateTime.tryParse(value);
  if (date == null) return value;
  const months = [
    'enero',
    'febrero',
    'marzo',
    'abril',
    'mayo',
    'junio',
    'julio',
    'agosto',
    'septiembre',
    'octubre',
    'noviembre',
    'diciembre',
  ];
  return '${date.day} de ${months[date.month - 1]} de ${date.year}';
}

/// Same ten variables as the existing message contract. Known missing values
/// remain visible and block copying; arbitrary user braces remain untouched.
MensajeResuelto resolverMensaje({
  required String cuerpo,
  required JsonMap tienda,
  required List<JsonMap> muestras,
  Map<String, String> compromisos = const {},
  String? fechaAnterior,
  String? linkVideo,
  String firma = '',
  String problemaEnvio = 'no_llego',
}) {
  final missing = <String>{};
  final firstId = muestras.isEmpty ? null : muestras.first['application_id'];
  String? prior = fechaAnterior;
  for (final sample in muestras) {
    final promise = (sample['avisos'] as Map?)?['promesa'];
    if (promise is String && (prior == null || promise.compareTo(prior) > 0))
      prior = promise;
  }
  String? value(String key) {
    switch (key) {
      case 'tienda':
        return tienda['nombre'] is String ? tienda['nombre'] as String : null;
      case 'producto':
        return muestras.isEmpty
            ? 'su producto'
            : nombreProductoMensaje(muestras.first);
      case 'fecha_compromiso':
        return compromisos[firstId] == null
            ? null
            : fechaMensaje(compromisos[firstId]!);
      case 'fecha_anterior':
        return prior == null ? null : fechaMensaje(prior);
      case 'link_video':
        return linkVideo?.trim().isNotEmpty == true ? linkVideo!.trim() : null;
      case 'lista_productos':
        return muestras
            .map(
              (sample) =>
                  '• ${nombreProductoMensaje(sample)}${sample['variante'] is String && (sample['variante'] as String).isNotEmpty ? ' (${sample['variante']})' : ''}',
            )
            .join('\n');
      case 'lista_fechas':
        if (muestras.any(
          (sample) => compromisos[sample['application_id']] == null,
        ))
          return null;
        return muestras
            .map(
              (sample) =>
                  '• ${nombreProductoMensaje(sample)}: a más tardar el ${fechaMensaje(compromisos[sample['application_id']]!)}',
            )
            .join('\n');
      case 'agradecimiento_socio':
        return tienda['es_socio'] == true
            ? 'También gracias por todo lo que hemos vendido juntos con sus productos. '
            : '';
      case 'problema_envio':
        return problemaEnvio == 'incompleta'
            ? 'llegó incompleta'
            : 'no me llegó';
      case 'firma':
        return firma.trim().isEmpty ? '' : '\n— ${firma.trim()}';
      default:
        return null;
    }
  }

  final text = cuerpo.replaceAllMapped(RegExp(r'\{([a-z_]+)\}'), (match) {
    final key = match[1]!;
    if (!variablesMensaje.contains(key)) return match[0]!;
    final replacement = value(key);
    if (replacement == null) {
      missing.add(key);
      return match[0]!;
    }
    return replacement;
  });
  return MensajeResuelto(text, missing);
}
