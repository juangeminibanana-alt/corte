import '../data/corte_store.dart';
import 'data_store_native.dart'
    if (dart.library.js_interop) 'data_store_web.dart'
    as implementation;

export '../data/corte_store.dart';

Future<CorteDataStore> createCorteDataStore() async =>
    implementation.createStore();

bool validCorteDataKey(String key) => RegExp(
  r'^corte\.data\.[a-f0-9]{64}\.(snapshot|outbox|images|image\.[a-f0-9]{64})$',
).hasMatch(key);

class CorteStoreException implements Exception {
  const CorteStoreException(this.message);
  final String message;
  @override
  String toString() => message;
}
