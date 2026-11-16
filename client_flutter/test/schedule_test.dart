import 'package:flutter_test/flutter_test.dart';
import 'package:corte/domain/corte_models.dart';
import 'package:corte/domain/schedule.dart';

JsonMap sample(
  String id, {
  String group = 'vencida',
  String stage = 'por_planear',
  String? date,
  bool received = true,
  int position = 10,
  String? promise,
  bool fixed = false,
}) => {
  'application_id': id,
  'grupo': group,
  'recibida': received,
  'posicion_cola': position,
  'producto': {'product_id': id, 'titulo': 'Producto $id'},
  'tienda': {'tienda_key': 't:$id'},
  'avance': {
    'plan_id': null,
    'etapa': stage,
    'fecha_planeada': date,
    'fijada': fixed,
    'rev': 0,
  },
  'avisos': {'promesa': promise},
};
BatchSchedule preview(
  List<JsonMap> samples, {
  List<JsonMap> plans = const [],
  int capacity = 1,
  Set<int> days = const {0, 1, 2, 3, 4},
  int maxDays = 3660,
}) => previewBatchSchedule(
  samples: samples,
  plans: plans,
  selectedIds: samples.map((s) => s['application_id'] as String),
  start: DateTime.utc(2026, 11, 16),
  capacity: capacity,
  weekdays: days,
  maxCalendarDays: maxDays,
);

void main() {
  test(
    'respects capacity, chosen weekdays, existing plans and deduplicated sample occupancy',
    () {
      final samples = [
        sample('1'),
        sample('2'),
        sample('3'),
        sample('4', stage: 'planeada', date: '2026-11-16'),
      ];
      final plans = <JsonMap>[
        {
          'id': 'reserved',
          'application_id': '4',
          'estado': 'planeada',
          'fecha_plan': '2026-11-16',
          'fijada': true,
        },
        {
          'id': 'loose',
          'application_id': null,
          'estado': 'video_listo',
          'fecha_plan': '2026-11-18',
        },
      ];
      final result = preview(samples, plans: plans, capacity: 2, days: {0, 2});
      expect(result.items.map((e) => e.date), [
        '2026-11-16',
        '2026-11-18',
        '2026-11-23',
      ]);
      expect(result.occupied['2026-11-16'], 1);
      expect(result.occupied['2026-11-18'], 1);
      expect(result.excluded, ['4']);
      expect(plans.first['fecha_plan'], '2026-11-16');
    },
  );

  test(
    'scheduled timestamp at 01 UTC occupies previous Mexico day when no plan date exists',
    () {
      final epoch =
          DateTime.utc(2026, 11, 17, 1).millisecondsSinceEpoch ~/ 1000;
      final result = preview(
        [sample('1')],
        plans: [
          {
            'id': 'scheduled',
            'estado': 'programada',
            'programada_para_at': epoch,
          },
        ],
      );
      expect(result.items.single.date, '2026-11-17');
      expect(result.occupied['2026-11-16'], 1);
    },
  );

  test(
    'deadline-ordered urgent items precede queue priority and lateness stays explicit',
    () {
      final urgent = sample('2', group: 'por_vencer', position: 99)
        ..['fecha_limite_at'] =
            DateTime.utc(2026, 11, 16, 18).millisecondsSinceEpoch ~/ 1000;
      final later = sample('3', group: 'por_vencer', position: 0)
        ..['fecha_limite_at'] =
            DateTime.utc(2026, 11, 20, 18).millisecondsSinceEpoch ~/ 1000;
      final result = preview([sample('1', position: 0), later, urgent]);
      expect(result.items.map((e) => e.applicationId), ['2', '3', '1']);
      expect(result.items.first.late, isFalse);
      final missed = preview(
        [urgent],
        plans: [
          {'id': 'loose', 'estado': 'planeada', 'fecha_plan': '2026-11-16'},
        ],
      );
      expect(missed.items.single.late, isTrue);
      expect(missed.lateCount, 1);
    },
  );

  test(
    'swaps same-priority slots to preserve a promise without displacing urgent work',
    () {
      final result = preview([
        sample('1', position: 0),
        sample('2', position: 1, promise: '2026-11-18'),
      ]);
      expect(result.items.first.applicationId, '2');
      expect(result.brokenPromises, 0);
      final urgent = sample('3', group: 'por_vencer', position: 99);
      final impossible = preview([urgent, sample('2', promise: '2026-11-18')]);
      expect(impossible.items.first.applicationId, '3');
      expect(impossible.brokenPromises, 1);
    },
  );

  test(
    'excludes unreceived, untaggable, fixed, ready, scheduled and published work',
    () {
      final cases = [
        sample('1', received: false),
        sample('2', fixed: true),
        sample('3', stage: 'video_listo'),
        sample('4', stage: 'programada'),
        sample('5', stage: 'publicada'),
        sample('6', stage: 'no_se_puede'),
        sample('7', group: 'completa'),
        sample('8')..['prioridad'] = 'no_se_puede_etiquetar',
      ];
      for (final item in cases) {
        expect(canBatchSchedule(item, []), isFalse);
      }
      final previous = sample('9', stage: 'publicada');
      (previous['avance'] as Map)['vinculo_origen'] = 'video_previo';
      expect(canBatchSchedule(previous, []), isTrue);
    },
  );

  test(
    'bounded horizon and duplicate selection never create an infinite or duplicate plan',
    () {
      final result = previewBatchSchedule(
        samples: [sample('1'), sample('2')],
        plans: [],
        selectedIds: ['1', '1', 'missing', '2'],
        start: DateTime.utc(2026, 11, 16),
        capacity: 1,
        weekdays: {0},
        maxCalendarDays: 1,
      );
      expect(result.items.length, 1);
      expect(result.excluded, ['missing']);
      expect(result.unassigned, ['2']);
      expect(
        () => preview([sample('1')], days: {}),
        throwsA(isA<ScheduleException>()),
      );
    },
  );

  test(
    'existing unscheduled plan is edited with real revision and notes remain untouched',
    () {
      final existing = <String, dynamic>{
        'id': 'original-plan',
        'application_id': '1',
        'estado': 'por_planear',
        'rev': 7,
        'notas': 'original history',
      };
      final result = preview([sample('1')], plans: [existing]);
      var n = 0;
      final ops = batchScheduleOperations(result, [
        existing,
      ], () => 'synthetic-${n++}');
      expect(ops.single['tipo'], 'plan.editar');
      expect(ops.single['id'], 'original-plan');
      expect(ops.single['cambios'], {
        'rev': 7,
        'estado': 'planeada',
        'fecha_plan': '2026-11-16',
      });
      expect(existing['notas'], 'original history');
    },
  );

  test(
    'advance-only existing plan uses its ID/revision and never creates a duplicate',
    () {
      final item = sample('1');
      (item['avance'] as Map)['plan_id'] = 'existing';
      (item['avance'] as Map)['rev'] = 4;
      final result = preview([item]);
      final ops = batchScheduleOperations(result, [], () => 'synthetic-id');
      expect(ops.single['tipo'], 'plan.editar');
      expect(ops.single['id'], 'existing');
      expect((ops.single['cambios'] as Map)['rev'], 4);
    },
  );

  test(
    'new operations have separate caller-provided IDs and canonical plan fields',
    () {
      final result = preview([sample('1')]);
      var n = 0;
      final ops = batchScheduleOperations(result, [], () => 'uuid-${n++}');
      expect(ops.single['op_id'], 'uuid-0');
      final data = ops.single['datos'] as Map;
      expect(data['id'], 'uuid-1');
      expect(data['application_id'], '1');
      expect(data['product_id'], '1');
      expect(data['estado'], 'planeada');
      expect(data['notas'], '');
      expect(result.finish, '2026-11-16');
      expect(result.publishBy, '2026-11-18');
    },
  );

  test(
    'preview owns immutable sample identity and rejects unknown edit revisions',
    () {
      final item = sample('1');
      (item['avance'] as Map)['plan_id'] = 'old';
      (item['avance'] as Map)['rev'] = null;
      final result = preview([item]);
      item['application_id'] = 'changed';
      expect(result.items.single.applicationId, '1');
      expect(
        () => result.items.single.sample['application_id'] = 'other',
        throwsUnsupportedError,
      );
      expect(
        () => batchScheduleOperations(result, [], () => 'synthetic'),
        throwsA(isA<ScheduleException>()),
      );
    },
  );
}
