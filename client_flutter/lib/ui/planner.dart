import 'dart:convert';

import 'package:flutter/material.dart';

import '../app.dart';
import '../data/corte_repository.dart';
import '../domain/schedule.dart';
import 'format.dart';
import 'theme.dart';
import 'widgets.dart';

class BatchPlannerPage extends StatelessWidget {
  const BatchPlannerPage({super.key, this.initialSelection});
  final Set<String>? initialSelection;
  @override
  Widget build(BuildContext context) => ApiData(
    path: '/api/snapshot',
    builder: (context, data) => _PlannerForm(
      key: ValueKey(CorteScope.of(context).repo.cacheScope),
      snapshot: data,
      initialSelection: initialSelection,
    ),
  );
}

class _PlannerForm extends StatefulWidget {
  const _PlannerForm({
    super.key,
    required this.snapshot,
    this.initialSelection,
  });
  final JsonMap snapshot;
  final Set<String>? initialSelection;
  @override
  State<_PlannerForm> createState() => _PlannerFormState();
}

class _PlannerFormState extends State<_PlannerForm> {
  late int capacity;
  late Set<int> weekdays;
  late Set<String> selected;
  late DateTime start;
  bool reviewing = false, busy = false;
  String? error, saved;
  JsonMap? freshSnapshot;
  BatchSchedule? preview;
  List<JsonMap>? operations;
  JsonMap get snapshot => freshSnapshot ?? widget.snapshot;
  List<JsonMap> get samples => rowsOf(snapshot['muestras']);
  List<JsonMap> get plans => rowsOf(mapOf(snapshot['local'])['planes']);
  List<JsonMap> get candidates {
    final indexed = <String, List<JsonMap>>{};
    for (final plan in plans) {
      final id = plan['application_id'];
      if (id is String) indexed.putIfAbsent(id, () => []).add(plan);
    }
    return samples
        .where(
          (s) => canBatchSchedule(s, indexed[s['application_id']] ?? const []),
        )
        .toList();
  }

  @override
  void initState() {
    super.initState();
    final preferences = mapOf(mapOf(widget.snapshot['local'])['preferencias']);
    capacity = intOf(preferences['capacidad_videos_dia'], 3).clamp(1, 10);
    weekdays = preferences['dias_videos'] is List
        ? (preferences['dias_videos'] as List)
              .whereType<int>()
              .where((d) => d >= 0 && d <= 6)
              .toSet()
        : <int>{};
    final now = DateTime.now().toUtc().subtract(const Duration(hours: 6));
    start = DateTime.utc(
      now.year,
      now.month,
      now.day,
    ).add(Duration(days: now.hour >= 18 ? 1 : 0));
    final ids = candidates.map((s) => textOf(s['application_id'])).toSet();
    selected =
        (widget.initialSelection == null
                ? ids
                : ids.intersection(widget.initialSelection!))
            .take(200)
            .toSet();
  }

  BatchSchedule calculate(JsonMap data) => previewBatchSchedule(
    samples: rowsOf(data['muestras']),
    plans: rowsOf(mapOf(data['local'])['planes']),
    selectedIds: selected,
    start: start,
    capacity: capacity,
    weekdays: weekdays,
  );
  void review() {
    try {
      final value = calculate(snapshot);
      setState(() {
        preview = value;
        reviewing = true;
        operations = null;
        error = null;
      });
    } on ScheduleException catch (failure) {
      setState(() => error = failure.message);
    }
  }

  String fingerprint(BatchSchedule value, List<JsonMap> currentPlans) =>
      jsonEncode([
        for (final item in value.items)
          {
            'id': item.applicationId,
            'date': item.date,
            'late': item.late,
            'promise': item.breaksPromise,
            'plan': currentPlans
                .where((p) => p['application_id'] == item.applicationId)
                .firstOrNull,
            'advance': item.sample['avance'],
          },
        value.excluded,
        value.unassigned,
      ]);
  Future<void> save() async {
    if (busy || preview == null || preview!.items.isEmpty) return;
    final ui = CorteScope.of(context);
    setState(() {
      busy = true;
      error = null;
    });
    try {
      // Recheck occupancy/revisions immediately before committing. Offline, the
      // repository uses only the verified scope's snapshot and durable outbox.
      final latest = await ui.repo.snapshot(force: true);
      if (!mounted) return;
      final checked = calculate(latest.raw);
      final latestPlans = rowsOf(mapOf(latest.raw['local'])['planes']);
      if (fingerprint(checked, latestPlans) != fingerprint(preview!, plans)) {
        setState(() {
          freshSnapshot = latest.raw;
          preview = checked;
          operations = null;
          error =
              'La información cambió. Revisa las fechas actualizadas antes de guardar.';
        });
        return;
      }
      operations ??= batchScheduleOperations(checked, latestPlans, nuevoId);
      if (operations!.isEmpty) return;
      final result = await ui.repo.guardarOps(operations!);
      if (!mounted) return;
      setState(
        () => saved = result.enCola
            ? 'El lote se guardó en este dispositivo. Hay cambios pendientes de envío.'
            : 'Tus ${checked.items.length} planes se guardaron en CUTGC.',
      );
      ui.refresh();
    } catch (failure) {
      if (mounted) {
        setState(
          () => error = failure is ErrorApi
              ? failure.mensaje
              : failure is ScheduleException
              ? failure.message
              : 'No pudimos guardar el plan. La vista previa se conserva.',
        );
      }
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final ui = CorteScope.of(context);
    if (saved != null) {
      return ListView(
        padding: const EdgeInsets.all(24),
        children: [
          const PageTitle('Tu plan está guardado'),
          InlineNotice(text: saved!),
          const SizedBox(height: 20),
          Align(
            alignment: Alignment.centerLeft,
            child: FilledButton(
              onPressed: () => ui.go('/muestras'),
              child: const Text('Ver mis muestras'),
            ),
          ),
        ],
      );
    }
    final result = preview;
    return ListView(
      padding: const EdgeInsets.all(24),
      children: [
        PageTitle(
          reviewing ? 'Revisa tu plan' : 'Armar mi plan',
          subtitle: reviewing
              ? 'Confirma las fechas antes de guardar.'
              : 'Reparte tus muestras recibidas entre tus días de trabajo.',
          back: busy
              ? null
              : () {
                  if (reviewing) {
                    setState(() {
                      reviewing = false;
                      error = null;
                    });
                  } else {
                    ui.go('/muestras');
                  }
                },
          action: reviewing
              ? FilledButton.icon(
                  onPressed: busy || result == null || result.items.isEmpty
                      ? null
                      : save,
                  icon: const Icon(Icons.check_rounded, size: 19),
                  label: Text(busy ? 'Guardando…' : 'Guardar este plan'),
                )
              : null,
        ),
        if (error != null) ...[
          InlineNotice(text: error!, error: true),
          const SizedBox(height: 18),
        ],
        if (!reviewing) ...[
          const SectionHeading('Ritmo para este plan'),
          ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 450),
            child: DropdownButtonFormField<int>(
              initialValue: capacity,
              decoration: const InputDecoration(labelText: 'Videos por día'),
              items: List.generate(
                10,
                (i) => DropdownMenuItem(
                  value: i + 1,
                  child: Text('${i + 1} ${i == 0 ? 'video' : 'videos'}'),
                ),
              ),
              onChanged: busy
                  ? null
                  : (value) => setState(() {
                      capacity = value ?? capacity;
                      operations = null;
                    }),
            ),
          ),
          const SizedBox(height: 16),
          Wrap(
            spacing: 7,
            runSpacing: 6,
            children: [
              for (var i = 0; i < 7; i++)
                FilterChip(
                  label: Text(
                    const ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom'][i],
                  ),
                  selected: weekdays.contains(i),
                  onSelected: busy
                      ? null
                      : (value) => setState(() {
                          value ? weekdays.add(i) : weekdays.remove(i);
                          operations = null;
                        }),
                ),
            ],
          ),
          const SizedBox(height: 12),
          Align(
            alignment: Alignment.centerLeft,
            child: OutlinedButton.icon(
              onPressed: busy
                  ? null
                  : () async {
                      final today = mexicoDay(DateTime.now());
                      final value = await showDatePicker(
                        context: context,
                        initialDate: start,
                        firstDate: today,
                        lastDate: today.add(const Duration(days: 366)),
                        helpText: '¿Desde qué día?',
                        cancelText: 'Cancelar',
                        confirmText: 'Elegir',
                      );
                      if (value != null && mounted) {
                        setState(() {
                          start = DateTime.utc(
                            value.year,
                            value.month,
                            value.day,
                          );
                          operations = null;
                        });
                      }
                    },
              icon: const Icon(Icons.event_outlined, size: 19),
              label: Text('Desde ${scheduleDate(start)}'),
            ),
          ),
          SectionHeading(
            'Muestras para incluir',
            subtitle:
                '${selected.length} seleccionadas · ${candidates.length} disponibles',
            action: TextButton(
              onPressed: () => setState(() {
                selected = selected.isEmpty
                    ? candidates
                          .take(200)
                          .map((s) => textOf(s['application_id']))
                          .toSet()
                    : <String>{};
              }),
              child: Text(
                selected.isEmpty ? 'Seleccionar' : 'Quitar selección',
              ),
            ),
          ),
          if (candidates.length > 200)
            const InlineNotice(
              text: 'Puedes planear hasta 200 muestras por lote.',
            ),
          if (candidates.isEmpty)
            const EmptyState(
              'No hay muestras recibidas sin fecha',
              text:
                  'Las muestras con fecha o con un video listo conservan su plan. Puedes revisar cada muestra desde su ficha.',
            ),
          for (final sample in candidates)
            _CandidateRow(
              sample: sample,
              selected: selected.contains(sample['application_id']),
              onChanged: (value) => setState(() {
                final id = textOf(sample['application_id']);
                if (!value) {
                  selected.remove(id);
                } else if (selected.length < 200) {
                  selected.add(id);
                }
              }),
            ),
          const SizedBox(height: 20),
          Align(
            alignment: Alignment.centerLeft,
            child: FilledButton.icon(
              onPressed: selected.isEmpty || busy ? null : review,
              icon: const Icon(Icons.calendar_month_outlined, size: 19),
              label: const Text('Revisar fechas'),
            ),
          ),
        ] else if (result != null) ...[
          Text(
            '${result.items.length} videos · $capacity por día',
            style: Theme.of(context).textTheme.titleLarge,
          ),
          if (result.finish != null) ...[
            const SizedBox(height: 6),
            Text('Terminas de grabar el ${result.finish}.'),
            Text(
              'Con dos días de margen, último día sugerido de publicación: ${result.publishBy}.',
              style: TextStyle(color: context.corte.muted),
            ),
          ],
          if (result.lateCount > 0 || result.brokenPromises > 0) ...[
            const SizedBox(height: 16),
            InlineNotice(
              error: true,
              text:
                  '${result.lateCount} muestras quedan después de su fecha límite y ${result.brokenPromises} no alcanzan la fecha prometida con dos días de margen. Revisa el ritmo o prepara una nueva fecha con la tienda.',
            ),
          ],
          if (result.excluded.isNotEmpty) ...[
            const SizedBox(height: 12),
            InlineNotice(
              text:
                  '${result.excluded.length} selecciones ya no pueden planearse en este lote y conservan su estado actual.',
            ),
          ],
          if (result.unassigned.isNotEmpty) ...[
            const SizedBox(height: 12),
            InlineNotice(
              text:
                  '${result.unassigned.length} muestras no encontraron lugar dentro del rango. Se conservarán sin cambios.',
              error: true,
            ),
          ],
          const SizedBox(height: 20),
          for (var i = 0; i < result.items.length; i++) ...[
            if (i == 0 || result.items[i - 1].date != result.items[i].date)
              Padding(
                padding: const EdgeInsets.only(top: 18, bottom: 9),
                child: Text(
                  '${result.items[i].date} · ${result.items.where((e) => e.date == result.items[i].date).length} nuevos + ${result.occupied[result.items[i].date] ?? 0} ya planeados',
                  style: const TextStyle(fontWeight: FontWeight.w700),
                ),
              ),
            _PreviewRow(item: result.items[i]),
          ],
          const SizedBox(height: 24),
          Align(
            alignment: Alignment.centerLeft,
            child: FilledButton(
              onPressed: busy || result.items.isEmpty ? null : save,
              child: Text(busy ? 'Guardando…' : 'Guardar este plan'),
            ),
          ),
        ],
        const SizedBox(height: 32),
      ],
    );
  }
}

class _CandidateRow extends StatelessWidget {
  const _CandidateRow({
    required this.sample,
    required this.selected,
    required this.onChanged,
  });
  final JsonMap sample;
  final bool selected;
  final ValueChanged<bool> onChanged;
  @override
  Widget build(BuildContext context) {
    final product = mapOf(sample['producto']);
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 12),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Checkbox(
                value: selected,
                onChanged: (value) => onChanged(value ?? false),
                semanticLabel:
                    'Incluir ${textOf(product['titulo_corto'], textOf(product['titulo']))}',
              ),
              CortePhoto(product['imagen'] as String?, width: 62, height: 68),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      textOf(
                        product['titulo_corto'],
                        textOf(product['titulo'], 'Producto'),
                      ),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(fontWeight: FontWeight.w700),
                    ),
                    Text(
                      textOf(mapOf(sample['tienda'])['nombre']),
                      style: TextStyle(color: context.corte.cyanInk),
                    ),
                    if (sample['fecha_limite_at'] != null)
                      Text(
                        'Fecha límite: ${date(sample['fecha_limite_at'])}',
                        style: TextStyle(
                          color: context.corte.muted,
                          fontSize: 12,
                        ),
                      ),
                  ],
                ),
              ),
            ],
          ),
        ),
        const Divider(),
      ],
    );
  }
}

class _PreviewRow extends StatelessWidget {
  const _PreviewRow({required this.item});
  final BatchScheduleItem item;
  @override
  Widget build(BuildContext context) {
    final product = mapOf(item.sample['producto']);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 10),
      child: Row(
        children: [
          CortePhoto(product['imagen'] as String?, width: 54, height: 58),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  textOf(
                    product['titulo_corto'],
                    textOf(product['titulo'], 'Producto'),
                  ),
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                ),
                if (item.late || item.breaksPromise)
                  Text(
                    item.late
                        ? 'Después de la fecha límite'
                        : 'Necesita una nueva fecha con la tienda',
                    style: TextStyle(color: context.corte.action, fontSize: 12),
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
