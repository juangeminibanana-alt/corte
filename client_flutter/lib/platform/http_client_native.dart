import 'package:http/http.dart' as http;

http.Client createClient() => http.Client();

Uri browserOrigin() => throw UnsupportedError('Sólo disponible en web.');
