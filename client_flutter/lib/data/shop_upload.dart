import 'dart:typed_data';

import 'package:file_selector/file_selector.dart';

import 'corte_repository.dart';

const shopBase = '/api/publicaciones/shop';
const _chunkSize = 10 * 1024 * 1024;
const shopVideoLimit = 500 * 1024 * 1024;
const videoExtensions = [
  'mp4',
  'mov',
  'webm',
  'mkv',
  'wmv',
  'avi',
  '3gp',
  'flv',
  'mpeg',
  'mpg',
];

String? validateShopFile(String name, int size) {
  final ext = name.split('.').last.toLowerCase();
  if (!name.contains('.') || !videoExtensions.contains(ext)) {
    return 'Selecciona un archivo de video compatible.';
  }
  if (size <= 0 || size > shopVideoLimit) {
    return 'El video debe tener contenido y pesar hasta 500 MiB.';
  }
  if (size >= _chunkSize && !const ['mp4', 'mov', 'webm'].contains(ext)) {
    return 'Para videos de 10 MiB o más, usa MP4, MOV o WebM.';
  }
  return null;
}

Future<String> uploadShopVideo(
  CorteRepository repo,
  XFile file, {
  required void Function() checkAccount,
  required void Function(double) onProgress,
}) async {
  final size = await file.length();
  final validation = validateShopFile(file.name, size);
  if (validation != null) {
    throw ErrorApi(codigo: 'archivo_invalido', mensaje: validation);
  }
  final name = 'video.${file.name.split('.').last.toLowerCase()}';
  const path = '$shopBase/archivo';
  checkAccount();
  Future<Uint8List> read(int from, int to) async {
    final bytes = BytesBuilder(copy: false);
    await for (final chunk in file.openRead(from, to)) {
      if (bytes.length + chunk.length > to - from) break;
      bytes.add(chunk);
    }
    if (bytes.length != to - from) {
      throw ErrorApi(
        codigo: 'archivo_invalido',
        mensaje: 'El video cambió mientras se leía. Vuelve a seleccionarlo.',
      );
    }
    checkAccount();
    return bytes.takeBytes();
  }

  Map<String, dynamic> result;
  if (size < _chunkSize) {
    result = await repo.post(
      path,
      body: CorteVideoBytes(await read(0, size), filename: name),
    );
  } else {
    final init = await repo.post(
      '$path/iniciar',
      body: {'nombre': name, 'bytes': size},
    );
    final id = init['carga_id'], parts = init['partes'];
    if (id is! String ||
        !RegExp(r'^[A-Za-z0-9_-]{1,128}$').hasMatch(id) ||
        parts is! int ||
        parts < 1 ||
        parts > 100 ||
        (size + parts - 1) ~/ parts > _chunkSize) {
      throw ErrorApi(
        codigo: 'respuesta_invalida',
        mensaje: 'CUTGC no pudo preparar la carga por partes.',
      );
    }
    result = {};
    for (var i = 1; i <= parts; i++) {
      checkAccount();
      final end = i * size ~/ parts;
      final bytes = await read((i - 1) * size ~/ parts, end);
      result = await repo.put(
        '$path/$id/partes/$i',
        body: CorteVideoBytes(bytes),
      );
      if (i < parts && result['recibida'] != i) {
        throw ErrorApi(
          codigo: 'respuesta_invalida',
          mensaje: 'CUTGC no confirmó una parte del video.',
        );
      }
      onProgress(end / size);
    }
  }
  checkAccount();
  final id = result['file_id'];
  if (id is! String || id.isEmpty) {
    throw ErrorApi(
      codigo: 'respuesta_invalida',
      mensaje: 'TikTok no confirmó la carga del archivo.',
    );
  }
  onProgress(1);
  return id;
}
