import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

/// Keeps the Windows title bar aligned with the resolved Material theme,
/// including system brightness changes and explicit in-app overrides.
class ThemeChromeSync extends StatefulWidget {
  const ThemeChromeSync({super.key, required this.child});

  final Widget child;

  @override
  State<ThemeChromeSync> createState() => _ThemeChromeSyncState();
}

class _ThemeChromeSyncState extends State<ThemeChromeSync>
    with WidgetsBindingObserver {
  static const _channel = MethodChannel('corte/window');
  Brightness? _brightness, _sent;
  bool _scheduled = false, _force = false;
  int _request = 0;

  bool get _supported =>
      !kIsWeb && defaultTargetPlatform == TargetPlatform.windows;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _brightness = Theme.of(context).brightness;
    _schedule();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) _schedule(force: true);
  }

  void _schedule({bool force = false}) {
    if (!_supported || !mounted) return;
    _force |= force;
    if (_scheduled || (!_force && _brightness == _sent)) return;
    _scheduled = true;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      _scheduled = false;
      unawaited(_sync());
    });
    WidgetsBinding.instance.ensureVisualUpdate();
  }

  Future<void> _sync() async {
    final brightness = _brightness;
    if (!mounted || brightness == null) return;
    final force = _force;
    _force = false;
    if (!force && _sent == brightness) return;
    final request = ++_request;
    _sent = brightness;
    try {
      await _channel.invokeMethod<void>(
        'setDarkMode',
        brightness == Brightness.dark,
      );
    } on MissingPluginException {
      // Older runners can still open the app; their frame follows Windows.
      if (mounted && request == _request) _sent = null;
    } on PlatformException {
      // A missing/unsupported DWM capability must not interrupt the UI.
      if (mounted && request == _request) _sent = null;
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _request++;
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => widget.child;
}
