import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:corte/app.dart';
import 'package:corte/auth/auth_controller.dart';
import 'package:corte/platform/corte_runtime.dart';
import 'package:corte/ui/catalog.dart';
import 'package:corte/ui/video_catalog.dart';

http.Response _json(Object body, [int status = 200]) => http.Response.bytes(
  utf8.encode(jsonEncode(body)),
  status,
  headers: {'content-type': 'application/json; charset=utf-8'},
);

http.Response _noEncontrado() => _json({
  'error': {'codigo': 'no_encontrado', 'mensaje': 'No encontramos ese recurso.'},
}, 404);

/// Instante en segundos de una fecha a una hora de México (UTC−6).
int _epoch(String fecha, [int hora = 12]) =>
    DateTime.parse(
      '${fecha}T${hora.toString().padLeft(2, '0')}:00:00-06:00',
    ).millisecondsSinceEpoch ~/
    1000;

Map<String, dynamic> _video(String id, [Map<String, dynamic> extra = const {}]) => {
  'content_id': id,
  'origen': 'display',
  'publicacion': 'publico',
  'descripcion': 'Video sintetico $id',
  'portada': null,
  'enlace': 'https://www.tiktok.com/@creadora/video/$id',
  'publicado_at': null,
  'duracion_s': 30,
  'vistas': 1200,
  'likes': 80,
  'comentarios': 4,
  'compartidos': 2,
  'metricas_at': _epoch('2026-11-17', 9),
  'ventas': null,
  'muestras_vinculadas': <String>[],
  ...extra,
};

Map<String, dynamic> _ventas(String id, int comision, String ultima) => {
  'content_id': id,
  'titulo': null,
  'miniatura': null,
  'enlace': 'https://www.tiktok.com/@creadora/video/$id',
  'pedidos': 3,
  'pedidos_validos': 2,
  'unidades': 3,
  'ventas_centavos': comision * 10,
  'comision_estimada_centavos': comision,
  'tasa_reembolso': 0,
  'participacion': 0.1,
  'primera_venta': '2026-01-10',
  'ultima_venta': ultima,
  'productos': 1,
  'tienda_principal': 'Tienda Sintetica',
  'muestras_vinculadas': <String>[],
};

/// Hub sintético: responde por ruta; lo demás, 404 como un hub que no lo tiene.
Future<void> _pintar(
  WidgetTester tester,
  Widget pagina,
  Map<String, Object> rutas, {
  List<String>? peticiones,
}) async {
  final auth = CorteAuthController(
    runtime: CorteRuntime(platform: 'web', baseUri: Uri.parse(corteCloudOrigin)),
    client: MockClient((request) async {
      peticiones?.add(request.url.path);
      final cuerpo = rutas[request.url.path];
      return cuerpo == null ? _noEncontrado() : _json(cuerpo);
    }),
  );
  final ui = CorteUiController(auth: auth);
  addTearDown(() {
    ui.dispose();
    auth.dispose();
  });
  await tester.pumpWidget(
    MaterialApp(
      home: CorteScope(
        controller: ui,
        child: Scaffold(body: pagina),
      ),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  group('orden del catálogo (igual que el hub)', () {
    final items = [
      _video('7400000000000000005'),
      _video('7400000000000000004'),
      _video('7400000000000000003', {
        'origen': 'ventas',
        'ventas': _ventas('7400000000000000003', 500, '2026-02-01'),
        'vistas': null,
      }),
      _video('7400000000000000002', {
        'origen': 'ventas',
        'ventas': _ventas('7400000000000000002', 900, '2026-03-01'),
        'vistas': 50,
      }),
      _video('7400000000000000001', {
        'publicado_at': _epoch('2026-04-01'),
        'vistas': 9000,
      }),
      _video('7400000000000000006', {
        'publicado_at': _epoch('2026-05-01'),
        'vistas': 10,
      }),
    ];
    List<String> ids(List<Map<String, dynamic>> xs) =>
        xs.map((v) => (v['content_id'] as String).substring(18)).toList();

    test('publicado: lo más nuevo, luego por última venta y al final sin ventas', () {
      expect(ids(sortCatalog(items, 'publicado')), ['6', '1', '2', '3', '4', '5']);
    });
    test('vistas: sin cifra al final', () {
      expect(ids(sortCatalog(items, 'vistas')), ['1', '4', '5', '2', '6', '3']);
    });
    test('comisión: los que no vendieron al final', () {
      expect(ids(sortCatalog(items, 'comision')), ['2', '3', '1', '4', '5', '6']);
    });
  });

  group('nunca se inventa una cifra', () {
    test('desde que se publicó, desde la fecha de los pedidos o registradas', () {
      final ahora = DateTime.utc(2026, 11, 18, 18);
      expect(
        noSalesText(_video('1', {'publicado_at': _epoch('2026-03-01', 0)}), '2026-03-01'),
        ('Sin ventas', 'desde que se publicó'),
      );
      expect(
        noSalesText(
          _video('1', {'publicado_at': _epoch('2026-02-28', 23)}),
          '2026-03-01',
          ahora: ahora,
        ),
        ('Sin ventas', 'desde el 1 mar'),
      );
      expect(
        noSalesText(_video('1'), '2026-03-01', ahora: ahora),
        ('Sin ventas', 'desde el 1 mar'),
      );
      expect(noSalesText(_video('1'), null), ('Sin ventas', 'registradas'));
      expect(
        noSalesText(_video('1', {'ventas': _ventas('1', 10, '2026-03-02')}), '2026-03-01'),
        isNull,
      );
    });
    test('una fecha de otro año lleva el año, como en la web', () {
      final ahora = DateTime.utc(2026, 11, 18, 18);
      expect(
        noSalesText(_video('1'), '2025-10-14', ahora: ahora),
        ('Sin ventas', 'desde el 14 oct 2025'),
      );
      expect(
        noSalesText(_video('1'), '2026-10-14', ahora: ahora),
        ('Sin ventas', 'desde el 14 oct'),
      );
      expect(fechaDeInstante(_epoch('2025-09-01'), ahora: ahora), '1 sep 2025');
    });
    test('la fecha de publicación se toma en hora de México', () {
      expect(fechaMexico(_epoch('2026-03-01', 0)), '2026-03-01');
      expect(fechaMexico(_epoch('2026-03-01', 23)), '2026-03-01');
    });
    test('un pedido en singular', () {
      expect(pedidosTexto(1), '1 pedido');
      expect(pedidosTexto(2), '2 pedidos');
      expect(pedidosTexto(1200), '1,200 pedidos');
    });
    test('avisos y estados de publicación', () {
      expect(catalogNotice(null), contains('Conecta las métricas'));
      expect(catalogNotice({'misma_cuenta': false}), contains('no es la de tu tienda'));
      expect(catalogNotice({'misma_cuenta': null}), contains('comprobar'));
      expect(catalogNotice({'misma_cuenta': true}), isNull);
      expect(publicationLabel('no_publico'), 'Ya no es público');
      expect(publicationLabel('no_confirmado'), 'Sin confirmar');
      expect(publicationLabel('publico'), isNull);
    });
  });

  testWidgets('«Todos» lista los videos sin ventas sin inventar ceros', (tester) async {
    final peticiones = <String>[];
    await _pintar(tester, const VideosPage(todos: true), {
      '/api/session': {
        'capacidades': {'catalogo_videos': true},
      },
      '/api/catalogo/videos': {
        'items': [
          _video('7400000000000000002', {'publicado_at': _epoch('2026-06-01')}),
          _video('7400000000000000003', {
            'origen': 'display_y_ventas',
            'ventas': _ventas('7400000000000000003', 123456, '2026-11-01'),
          }),
        ],
        'total': 2,
        'data_version': 1,
        'display': {'ultima_sync_at': _epoch('2026-11-17', 9), 'misma_cuenta': true},
        'pedidos_desde': '2026-03-01',
      },
    }, peticiones: peticiones);
    expect(find.text('Con ventas'), findsOneWidget);
    expect(find.text('Todos'), findsOneWidget);
    expect(find.text('desde que se publicó'), findsOneWidget);
    expect(find.text('\$1,235'), findsOneWidget);
    expect(find.text('\$0'), findsNothing);
    expect(find.text('Sin ventas · 1'), findsOneWidget);
    expect(peticiones, contains('/api/catalogo/videos'));
    expect(peticiones, isNot(contains('/api/analitica/videos')));
  });

  testWidgets('sin métricas de TikTok, «Todos» lo explica', (tester) async {
    await _pintar(tester, const VideosPage(todos: true), {
      '/api/session': {
        'capacidades': {'catalogo_videos': true},
      },
      '/api/catalogo/videos': {
        'items': [
          _video('7400000000000000003', {
            'origen': 'ventas',
            'ventas': _ventas('7400000000000000003', 900, '2026-11-01'),
            'vistas': null,
          }),
        ],
        'total': 1,
        'data_version': 1,
        'display': null,
        'pedidos_desde': '2026-03-01',
      },
    });
    expect(find.textContaining('Conecta las métricas de TikTok'), findsOneWidget);
    expect(find.text('Vistas'), findsNothing);
    expect(find.textContaining('Sin ventas ·'), findsNothing);
  });

  testWidgets('sin el catálogo en el hub no hay pestañas', (tester) async {
    final peticiones = <String>[];
    await _pintar(tester, const VideosPage(), {
      '/api/session': {'capacidades': <String, Object>{}},
      '/api/analitica/videos': {'items': <Object>[], 'total': 0, 'data_version': 1},
    }, peticiones: peticiones);
    expect(find.text('Todos'), findsNothing);
    expect(peticiones, isNot(contains('/api/catalogo/videos')));
  });

  testWidgets('«Con ventas» no espera la sesión y con el catálogo ofrece «Todos»', (tester) async {
    final peticiones = <String>[];
    await _pintar(tester, const VideosPage(), {
      '/api/session': {
        'capacidades': {'catalogo_videos': true},
      },
      '/api/analitica/videos': {
        'items': [_ventas('7400000000000000009', 5000, '2026-11-01')],
        'total': 1,
        'data_version': 1,
      },
    }, peticiones: peticiones);
    expect(peticiones, contains('/api/analitica/videos'));
    expect(peticiones, isNot(contains('/api/catalogo/videos')));
    expect(find.text('Con ventas'), findsOneWidget);
    expect(find.text('Todos'), findsOneWidget);
  });

  testWidgets('un hub que anuncia el catálogo pero responde 404 vuelve a «Con ventas»', (tester) async {
    final peticiones = <String>[];
    await _pintar(tester, const VideosPage(todos: true), {
      '/api/session': {
        'capacidades': {'catalogo_videos': true},
      },
      '/api/analitica/videos': {'items': <Object>[], 'total': 0, 'data_version': 1},
    }, peticiones: peticiones);
    expect(peticiones, contains('/api/catalogo/videos'));
    expect(peticiones, contains('/api/analitica/videos'));
    expect(find.text('Todos'), findsNothing);
    expect(find.text('No hay videos para esta búsqueda'), findsOneWidget);
  });

  testWidgets('el detalle de un video sin ventas sale del catálogo', (tester) async {
    const id = '7400000000000000001';
    await _pintar(tester, const VideoDetailPage(id: id, desdeTodos: true), {
      '/api/session': {
        'capacidades': {'catalogo_videos': true},
      },
      '/api/catalogo/videos/$id': {
        'video': _video(id, {
          'descripcion': 'Probador de vestidos',
          'publicado_at': _epoch('2026-10-01'),
        }),
        'ventas': null,
        'tendencia': <Object>[],
      },
      '/api/catalogo/videos': {
        'items': <Object>[],
        'total': 0,
        'data_version': 1,
        'display': {'ultima_sync_at': 1, 'misma_cuenta': true},
        'pedidos_desde': '2026-01-01',
      },
      '/api/notas': {'items': <Object>[], 'total': 0, 'data_version': 1},
    });
    expect(find.text('Probador de vestidos'), findsOneWidget);
    expect(
      find.text('Este video aún no tiene ventas desde que se publicó.'),
      findsOneWidget,
    );
    expect(find.text('Resultados de ventas'), findsNothing);
    expect(find.text('No encontramos este video'), findsNothing);
  });

  testWidgets('sin saber desde cuándo hay pedidos, el detalle solo dice lo seguro', (tester) async {
    const id = '7400000000000000001';
    await _pintar(tester, const VideoDetailPage(id: id), {
      '/api/session': {
        'capacidades': {'catalogo_videos': true},
      },
      '/api/catalogo/videos/$id': {
        'video': _video(id, {'publicado_at': _epoch('2026-10-01')}),
        'ventas': null,
        'tendencia': <Object>[],
      },
      '/api/notas': {'items': <Object>[], 'total': 0, 'data_version': 1},
    });
    expect(find.text('Este video no tiene ventas registradas en Corte.'), findsOneWidget);
    expect(find.textContaining('todavía no tiene pedidos guardados'), findsNothing);
  });

  testWidgets('sin el catálogo, el detalle sigue diciendo que no lo encontró', (tester) async {
    const id = '7400000000000000001';
    await _pintar(tester, const VideoDetailPage(id: id), {
      '/api/session': {'capacidades': <String, Object>{}},
    });
    expect(find.text('No encontramos este video'), findsOneWidget);
  });
}
