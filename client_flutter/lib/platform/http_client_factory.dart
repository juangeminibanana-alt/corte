import 'package:http/http.dart' as http;

import 'http_client_native.dart'
    if (dart.library.js_interop) 'http_client_web.dart'
    as implementation;

http.Client createPlatformHttpClient() => implementation.createClient();
