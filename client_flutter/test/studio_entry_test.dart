import 'package:corte/ui/studio_entry.dart';
import 'package:corte/ui/theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  const artwork = ValueKey('studio-entry-artwork');

  testWidgets(
    'waits for the route, leaves controls active and only plays once',
    (tester) async {
      var taps = 0;
      final ready = ValueNotifier(false);
      final section = ValueNotifier('Hoy');
      addTearDown(ready.dispose);
      addTearDown(section.dispose);
      await tester.pumpWidget(
        MaterialApp(
          home: ValueListenableBuilder<bool>(
            valueListenable: ready,
            builder: (context, isReady, child) =>
                CorteStudioEntrance(ready: isReady, child: child!),
            child: Scaffold(
              body: Center(
                child: ValueListenableBuilder<String>(
                  valueListenable: section,
                  builder: (context, title, _) =>
                      TextButton(onPressed: () => taps++, child: Text(title)),
                ),
              ),
            ),
          ),
        ),
      );
      expect(find.byKey(artwork), findsNothing);
      ready.value = true;
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 440));
      expect(find.byKey(artwork), findsOneWidget);
      await tester.tap(find.text('Hoy'));
      expect(taps, 1);
      await tester.pump(CorteMotion.intro);
      expect(find.byKey(artwork), findsNothing);

      section.value = 'Dinero';
      await tester.pump();
      expect(find.text('Dinero'), findsOneWidget);
      expect(find.byKey(artwork), findsNothing);
    },
  );

  testWidgets('reduced motion skips the ident', (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: MediaQuery(
          data: MediaQueryData(disableAnimations: true),
          child: CorteStudioEntrance(child: Scaffold(body: Text('Acceso'))),
        ),
      ),
    );
    expect(find.text('Acceso'), findsOneWidget);
    expect(find.byKey(artwork), findsNothing);
  });
}
