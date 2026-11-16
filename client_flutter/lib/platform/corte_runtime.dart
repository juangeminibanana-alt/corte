import 'package:flutter/foundation.dart';

import 'http_client_native.dart'
    if (dart.library.js_interop) 'http_client_web.dart'
    as implementation;

const corteCloudOrigin = 'https://corte-e-book-21589.web.app';

class CorteRuntime {
  const CorteRuntime({required this.platform, required this.baseUri});

  factory CorteRuntime.current() {
    if (kIsWeb) {
      return CorteRuntime(
        platform: 'web',
        baseUri: implementation.browserOrigin(),
      );
    }
    final platform = switch (defaultTargetPlatform) {
      TargetPlatform.android => 'android',
      TargetPlatform.windows => 'windows',
      _ => 'unsupported',
    };
    return CorteRuntime(
      platform: platform,
      baseUri: Uri.parse(corteCloudOrigin),
    );
  }

  final String platform;
  final Uri baseUri;
  bool get isWeb => platform == 'web';
  bool get isSupported =>
      isWeb || platform == 'android' || platform == 'windows';
}
