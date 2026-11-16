import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'app.dart';

void main() {
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
  });
  runApp(const CorteApplication());
}
