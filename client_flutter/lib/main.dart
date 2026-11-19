import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'app.dart';
import 'platform/android_startup.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  // Keep keyboard, screen reader and browser accessibility navigation available.
  if (kIsWeb) WidgetsBinding.instance.ensureSemantics();
  SystemChrome.setSystemUIOverlayStyle(
    const SystemUiOverlayStyle(
      statusBarColor: Color(0xFF08090B),
      statusBarIconBrightness: Brightness.light,
      systemNavigationBarColor: Color(0xFF08090B),
      systemNavigationBarIconBrightness: Brightness.light,
    ),
  );
  LicenseRegistry.addLicense(() async* {
    final license = await rootBundle.loadString(
      'assets/fonts/OFL-MonaSans.txt',
    );
    yield LicenseEntryWithLineBreaks(['Mona Sans'], license);
    final webFontLicense = await rootBundle.loadString(
      'assets/fonts/OFL-CUTGCWebSans.txt',
    );
    yield LicenseEntryWithLineBreaks(['CUTGC Web Sans'], webFontLicense);
    final iconsLicense = await rootBundle.loadString(
      'assets/icons/LICENSE-Lucide.txt',
    );
    yield LicenseEntryWithLineBreaks(['Lucide'], iconsLicense);
  });
  CorteAndroidStartup.trackErrors();
  final recovery = await CorteAndroidStartup.recoveryMode();
  CorteAndroidStartup.mark(recovery ? 'dart_recovery_ready' : 'dart_ready');
  runApp(CorteApplication(androidRecovery: recovery));
}
