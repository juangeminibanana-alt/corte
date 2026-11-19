import 'dart:async';
import 'dart:ui' show PlatformDispatcher;

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

/// Low-volume, app-local milestones. The native journal accepts only stage IDs.
abstract final class CorteAndroidStartup {
  static const _channel = MethodChannel('corte/startup');
  static bool get _android =>
      !kIsWeb && defaultTargetPlatform == TargetPlatform.android;

  static void mark(String phase) {
    if (_android) unawaited(_send(phase));
  }

  static Future<void> _send(String phase) async {
    try {
      await _channel.invokeMethod<void>('mark', phase);
    } on Exception {
      // Diagnostics must not affect the current activity.
    }
  }

  static void trackErrors() {
    if (!_android) return;
    final previousFrameError = FlutterError.onError;
    FlutterError.onError = (details) {
      mark('dart_frame_error');
      previousFrameError?.call(details);
    };
    final dispatcher = PlatformDispatcher.instance;
    final previousUncaughtError = dispatcher.onError;
    dispatcher.onError = (error, stack) {
      mark('dart_uncaught_error');
      return previousUncaughtError?.call(error, stack) ?? false;
    };
  }
}
