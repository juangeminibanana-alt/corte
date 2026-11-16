import 'package:url_launcher/url_launcher.dart';

import 'corte_runtime.dart';

abstract interface class CorteExternalLinks {
  Future<bool> open(Uri uri);
}

class CorteSystemLinks implements CorteExternalLinks {
  const CorteSystemLinks();

  @override
  Future<bool> open(Uri uri) {
    final host = uri.host.toLowerCase();
    final allowed =
        host == Uri.parse(corteCloudOrigin).host ||
        host == 'tiktok.com' ||
        host.endsWith('.tiktok.com') ||
        host == 'tiktokshop.com' ||
        host.endsWith('.tiktokshop.com');
    if (uri.scheme != 'https' ||
        !allowed ||
        uri.userInfo.isNotEmpty ||
        (uri.hasPort && uri.port != 443)) {
      throw ArgumentError('Enlace externo no permitido.');
    }
    return launchUrl(uri, mode: LaunchMode.externalApplication);
  }
}
