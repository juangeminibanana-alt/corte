typedef JsonMap = Map<String, dynamic>;

JsonMap jsonMap(Object? value) {
  if (value is! Map || value.keys.any((key) => key is! String)) {
    throw const FormatException('La respuesta no es un objeto JSON válido.');
  }
  return Map<String, dynamic>.from(value);
}

dynamic _freeze(Object? value) {
  if (value is Map) {
    final mapped = jsonMap(value);
    return Map<String, dynamic>.unmodifiable({
      for (final entry in mapped.entries) entry.key: _freeze(entry.value),
    });
  }
  if (value is List) {
    return List<dynamic>.unmodifiable(value.map(_freeze));
  }
  if (value == null || value is String || value is bool || value is num) {
    return value;
  }
  throw const FormatException('La respuesta contiene un dato JSON inválido.');
}

JsonMap immutableJson(JsonMap value) => _freeze(value) as JsonMap;

List<JsonMap> jsonObjects(Object? value) {
  if (value == null) return const [];
  if (value is! List) {
    throw const FormatException('La respuesta no contiene la lista esperada.');
  }
  return List.unmodifiable(value.map((item) => immutableJson(jsonMap(item))));
}

/// Typed views retain every original field, including optional future metadata.
class JsonDto {
  JsonDto(JsonMap value) : raw = immutableJson(value);

  final JsonMap raw;

  String? text(String key) {
    final value = raw[key];
    if (value == null || value is String) return value as String?;
    throw FormatException('El campo $key debe ser texto.');
  }

  String requiredText(String key) {
    final value = text(key);
    if (value == null || value.isEmpty) {
      throw FormatException('Falta el campo $key.');
    }
    return value;
  }

  int? integer(String key) {
    final value = raw[key];
    if (value == null || value is int) return value as int?;
    throw FormatException('El campo $key debe ser entero.');
  }

  num? number(String key) {
    final value = raw[key];
    if (value == null || value is num) return value as num?;
    throw FormatException('El campo $key debe ser numérico.');
  }

  bool? flag(String key) {
    final value = raw[key];
    if (value == null || value is bool) return value as bool?;
    throw FormatException('El campo $key debe ser booleano.');
  }

  JsonMap? object(String key) {
    final value = raw[key];
    return value == null ? null : immutableJson(jsonMap(value));
  }

  List<JsonMap> objects(String key) => jsonObjects(raw[key]);

  List<String> strings(String key) {
    final value = raw[key];
    if (value == null) return const [];
    if (value is! List || value.any((item) => item is! String)) {
      throw FormatException('El campo $key debe ser una lista de textos.');
    }
    return List<String>.unmodifiable(value.cast<String>());
  }
}
