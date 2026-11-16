String textOf(Object? value, [String fallback = '']) => value is String
    ? (value.trim().isEmpty ? fallback : value)
    : value == null
    ? fallback
    : value.toString();
int intOf(Object? value, [int fallback = 0]) =>
    value is num ? value.round() : int.tryParse('$value') ?? fallback;
Map<String, dynamic> mapOf(Object? value) =>
    value is Map ? Map<String, dynamic>.from(value) : <String, dynamic>{};
List<Map<String, dynamic>> rowsOf(Object? value) => value is List
    ? value.whereType<Map>().map((m) => Map<String, dynamic>.from(m)).toList()
    : [];
List<String> stringsOf(Object? value) =>
    value is List ? value.whereType<String>().toList() : [];

String integer(Object? value) {
  final n = intOf(value);
  return n.toString().replaceAllMapped(
    RegExp(r'(\d)(?=(\d{3})+(?!\d))'),
    (m) => '${m[1]},',
  );
}

String money(Object? centavos, {bool decimals = false}) {
  if (centavos == null) return '—';
  final n = intOf(centavos);
  final amount = n.abs() / 100;
  final main = (decimals ? amount.floor() : amount.round())
      .toString()
      .replaceAllMapped(RegExp(r'(\d)(?=(\d{3})+(?!\d))'), (m) => '${m[1]},');
  return '${n < 0 ? '−' : ''}\$$main${decimals ? '.${(n.abs() % 100).toString().padLeft(2, '0')}' : ''}';
}

String percent(Object? bp) => bp == null
    ? '—'
    : '${(intOf(bp) / 100).toStringAsFixed(intOf(bp) % 100 == 0 ? 0 : 1)} %';

String date(Object? seconds, {bool time = false}) {
  final epoch = intOf(seconds);
  if (epoch <= 0) return 'Sin fecha';
  final d = DateTime.fromMillisecondsSinceEpoch(epoch * 1000).toLocal();
  const months = [
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
  return '${d.day} ${months[d.month - 1]}${time ? ', ${d.hour.toString().padLeft(2, '0')}:${d.minute.toString().padLeft(2, '0')}' : ''}';
}

String stageLabel(Object? value) =>
    const {
      'por_planear': 'Por planear',
      'sin_planear': 'Por planear',
      'planeada': 'Planeada',
      'lista': 'Video listo',
      'listo': 'Video listo',
      'video_listo': 'Video listo',
      'publicada': 'Publicada',
      'programada': 'Programada',
      'no_se_puede': 'No se puede publicar',
      'vencida': 'Vencida sin video',
      'por_vencer': 'Por vencer',
      'en_envio': 'En envío',
      'sin_envio': 'Sin envío',
      'entregada': 'Entregada',
      'pausada': 'Pausada',
      'completa': 'Completa',
      'descartada': 'Descartada',
    }[textOf(value)] ??
    textOf(value).replaceAll('_', ' ');
