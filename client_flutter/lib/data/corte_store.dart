/// Private business JSON only. Platform implementations must commit writes
/// atomically and preserve existing content when a write fails. Never use this
/// store for tokens, OAuth codes, passwords or provider credentials.
abstract interface class CorteDataStore {
  Future<String?> read(String key);
  Future<void> write(String key, String value);
  Future<void> remove(String key);
}

class MemoryCorteDataStore implements CorteDataStore {
  final Map<String, String> _values = {};
  @override
  Future<String?> read(String key) async => _values[key];
  @override
  Future<void> write(String key, String value) async => _values[key] = value;
  @override
  Future<void> remove(String key) async => _values.remove(key);
}
