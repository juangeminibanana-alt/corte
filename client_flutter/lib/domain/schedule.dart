import 'corte_models.dart';

const _occupy = {'planeada', 'video_listo', 'programada'};
const _pending = {'vencida', 'por_vencer', 'pausada'};

DateTime mexicoDay(DateTime value) {
  final local = value.toUtc().subtract(const Duration(hours: 6));
  return DateTime.utc(local.year, local.month, local.day);
}

String scheduleDate(DateTime day) =>
    '${day.year.toString().padLeft(4, '0')}-${day.month.toString().padLeft(2, '0')}-${day.day.toString().padLeft(2, '0')}';
DateTime? _day(Object? value) {
  if (value is! String || !RegExp(r'^\d{4}-\d{2}-\d{2}$').hasMatch(value)) {
    return null;
  }
  final parsed = DateTime.tryParse('${value}T00:00:00Z');
  return parsed != null && scheduleDate(parsed) == value ? parsed : null;
}

String? _dateOf(JsonMap value, String dateKey, String epochKey) {
  final direct = _day(value[dateKey]);
  if (direct != null) return scheduleDate(direct);
  final epoch = value[epochKey];
  return epoch is int && epoch > 0
      ? scheduleDate(
          mexicoDay(
            DateTime.fromMillisecondsSinceEpoch(epoch * 1000, isUtc: true),
          ),
        )
      : null;
}

String? _text(Object? value) =>
    value is String && value.isNotEmpty ? value : null;
JsonMap _object(Object? value) =>
    value is Map ? jsonMap(value) : <String, dynamic>{};

/// Adds dates only to received, promotable, pending work without a reserved
/// date. Existing fixed/ready/scheduled/published work is never moved.
bool canBatchSchedule(JsonMap sample, List<JsonMap> plans) {
  if (!_pending.contains(sample['grupo']) ||
      sample['recibida'] != true ||
      sample['prioridad'] == 'no_se_puede_etiquetar') {
    return false;
  }
  final advance = _object(sample['avance']);
  final stage = advance['etapa'];
  final previous =
      stage == 'publicada' && advance['vinculo_origen'] == 'video_previo';
  if (advance['fijada'] == true ||
      _day(advance['fecha_planeada']) != null ||
      (!previous && stage != null && stage != 'por_planear')) {
    return false;
  }
  for (final plan in plans) {
    if (plan['application_id'] != sample['application_id']) continue;
    if (plan['fijada'] == true ||
        _dateOf(plan, 'fecha_plan', 'programada_para_at') != null) {
      return false;
    }
    if (plan['estado'] != 'por_planear' &&
        !(plan['estado'] == 'publicada' &&
            plan['vinculo_origen'] == 'video_previo')) {
      return false;
    }
  }
  return _text(sample['application_id']) != null;
}

class BatchScheduleItem {
  BatchScheduleItem({
    required JsonMap sample,
    required this.date,
    this.late = false,
    this.breaksPromise = false,
  }) : sample = immutableJson(sample);
  final JsonMap sample;
  final String date;
  final bool late, breaksPromise;
  String get applicationId => sample['application_id'] as String;
}

class BatchSchedule {
  BatchSchedule({
    required List<BatchScheduleItem> items,
    required Map<String, int> occupied,
    required List<String> excluded,
    required List<String> unassigned,
  }) : items = List.unmodifiable(items),
       occupied = Map.unmodifiable(occupied),
       excluded = List.unmodifiable(excluded),
       unassigned = List.unmodifiable(unassigned);
  final List<BatchScheduleItem> items;
  final Map<String, int> occupied;
  final List<String> excluded, unassigned;
  String? get finish => items.isEmpty
      ? null
      : items.map((e) => e.date).reduce((a, b) => a.compareTo(b) >= 0 ? a : b);
  String? get publishBy => finish == null
      ? null
      : scheduleDate(_day(finish)!.add(const Duration(days: 2)));
  int get lateCount => items.where((e) => e.late).length;
  int get brokenPromises => items.where((e) => e.breaksPromise).length;
}

BatchSchedule previewBatchSchedule({
  required List<JsonMap> samples,
  required List<JsonMap> plans,
  required Iterable<String> selectedIds,
  required DateTime start,
  required int capacity,
  required Set<int> weekdays,
  int maxCalendarDays = 3660,
}) {
  if (capacity < 1 ||
      capacity > 10 ||
      weekdays.isEmpty ||
      weekdays.any((day) => day < 0 || day > 6) ||
      maxCalendarDays < 1 ||
      maxCalendarDays > 3660) {
    throw const ScheduleException(
      'Elige de 1 a 10 videos por día y al menos un día de trabajo.',
    );
  }
  final first = DateTime.utc(start.year, start.month, start.day);
  final byId = {
    for (final sample in samples)
      if (_text(sample['application_id']) != null)
        sample['application_id'] as String: sample,
  };
  final candidates = <JsonMap>[], excluded = <String>[];
  for (final id in selectedIds.toSet()) {
    final sample = byId[id];
    if (sample == null || !canBatchSchedule(sample, plans)) {
      excluded.add(id);
      continue;
    }
    candidates.add(sample);
  }
  candidates.sort((a, b) {
    final aUrgent = a['grupo'] == 'por_vencer',
        bUrgent = b['grupo'] == 'por_vencer';
    if (aUrgent != bUrgent) return aUrgent ? -1 : 1;
    if (aUrgent) {
      final due =
          ((a['fecha_limite_at'] as num?)?.toInt() ?? 9007199254740991)
              .compareTo(
                (b['fecha_limite_at'] as num?)?.toInt() ?? 9007199254740991,
              );
      if (due != 0) return due;
    }
    final position = ((a['posicion_cola'] as num?)?.toInt() ?? 2147483647)
        .compareTo((b['posicion_cola'] as num?)?.toInt() ?? 2147483647);
    return position != 0
        ? position
        : (a['application_id'] as String).compareTo(
            b['application_id'] as String,
          );
  });
  final occupied = <String, int>{}, seen = <String>{};
  void reserve(String? key, String? date, Object? stage) {
    if (key == null ||
        date == null ||
        !_occupy.contains(stage) ||
        !seen.add(key)) {
      return;
    }
    occupied[date] = (occupied[date] ?? 0) + 1;
  }

  for (final plan in plans) {
    final id = _text(plan['application_id']);
    reserve(
      id == null
          ? (_text(plan['id']) == null ? null : 'plan:${plan['id']}')
          : 'sample:$id',
      _dateOf(plan, 'fecha_plan', 'programada_para_at'),
      plan['estado'],
    );
  }
  for (final sample in samples) {
    final advance = _object(sample['avance']);
    reserve(
      _text(sample['application_id']) == null
          ? null
          : 'sample:${sample['application_id']}',
      _dateOf(advance, 'fecha_planeada', 'programada_para_at'),
      advance['etapa'],
    );
  }
  final slots = <String>[];
  for (
    var offset = 0;
    offset < maxCalendarDays && slots.length < candidates.length;
    offset++
  ) {
    final day = first.add(Duration(days: offset));
    if (!weekdays.contains(day.weekday - 1)) continue;
    final date = scheduleDate(day);
    final available = capacity - (occupied[date] ?? 0);
    for (var i = 0; i < available && slots.length < candidates.length; i++) {
      slots.add(date);
    }
  }
  final assigned = candidates.take(slots.length).toList();
  DateTime? promise(JsonMap sample) =>
      _day(_object(sample['avisos'])['promesa']);
  DateTime? limit(JsonMap sample) => sample['fecha_limite_at'] is int
      ? mexicoDay(
          DateTime.fromMillisecondsSinceEpoch(
            (sample['fecha_limite_at'] as int) * 1000,
            isUtc: true,
          ),
        )
      : null;
  final promised = assigned.where((s) => promise(s) != null).toList()
    ..sort((a, b) => promise(a)!.compareTo(promise(b)!));
  // Same promise swap as the original planner. Never displace an urgent item
  // with a non-urgent one or break the other item's deadline/promise.
  for (final sample in promised) {
    final i = assigned.indexOf(sample);
    final deadline = promise(sample)!.subtract(const Duration(days: 2));
    if (!_day(slots[i])!.isAfter(deadline)) continue;
    for (var j = i - 1; j >= 0; j--) {
      final other = assigned[j],
          earlier = _day(slots[j])!,
          later = _day(slots[i])!;
      if (earlier.isAfter(deadline) ||
          (other['grupo'] == 'por_vencer') !=
              (sample['grupo'] == 'por_vencer')) {
        continue;
      }
      final otherLimit = other['grupo'] == 'por_vencer' ? limit(other) : null;
      final otherPromise = promise(other);
      if ((otherLimit != null && later.isAfter(otherLimit)) ||
          (otherPromise != null &&
              later.add(const Duration(days: 2)).isAfter(otherPromise))) {
        continue;
      }
      assigned[j] = sample;
      assigned[i] = other;
      break;
    }
  }
  return BatchSchedule(
    items: [
      for (var i = 0; i < assigned.length; i++)
        BatchScheduleItem(
          sample: assigned[i],
          date: slots[i],
          late:
              limit(assigned[i]) != null &&
              _day(slots[i])!.isAfter(limit(assigned[i])!),
          breaksPromise:
              promise(assigned[i]) != null &&
              _day(
                slots[i],
              )!.add(const Duration(days: 2)).isAfter(promise(assigned[i])!),
        ),
    ],
    occupied: occupied,
    excluded: excluded,
    unassigned: candidates
        .skip(slots.length)
        .map((s) => s['application_id'] as String)
        .toList(),
  );
}

/// Call only after the user confirms the preview; retain these IDs if a response
/// is lost. Existing records use their real rev and keep their notes/metadata.
List<JsonMap> batchScheduleOperations(
  BatchSchedule preview,
  List<JsonMap> plans,
  String Function() nextId,
) {
  final result = <JsonMap>[];
  for (final item in preview.items) {
    final sample = item.sample, advance = _object(item.sample['avance']);
    final existing = plans
        .where((p) => p['application_id'] == item.applicationId)
        .firstOrNull;
    final planId = _text(existing?['id']) ?? _text(advance['plan_id']);
    if (planId != null) {
      final revision = existing?['rev'] ?? advance['rev'];
      if (revision is! int) {
        throw const ScheduleException(
          'Actualiza la información del plan antes de guardarlo.',
        );
      }
      result.add({
        'op_id': nextId(),
        'tipo': 'plan.editar',
        'id': planId,
        'cambios': {
          'rev': revision,
          'estado': 'planeada',
          'fecha_plan': item.date,
        },
      });
    } else {
      final product = _object(sample['producto']),
          shop = _object(sample['tienda']);
      final title =
          _text(product['titulo_corto']) ??
          _text(product['titulo']) ??
          'Video de muestra';
      result.add({
        'op_id': nextId(),
        'tipo': 'plan.crear',
        'datos': {
          'id': nextId(),
          'application_id': item.applicationId,
          if (_text(product['product_id']) != null)
            'product_id': product['product_id'],
          if (_text(shop['tienda_key']) != null)
            'tienda_key': shop['tienda_key'],
          'titulo': String.fromCharCodes(title.runes.take(200)),
          'estado': 'planeada',
          'fecha_plan': item.date,
          'notas': '',
        },
      });
    }
  }
  return result;
}

class ScheduleException implements Exception {
  const ScheduleException(this.message);
  final String message;
  @override
  String toString() => message;
}
