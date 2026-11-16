import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../app.dart';
import '../data/corte_repository.dart';
import '../domain/messages.dart';
import 'format.dart';
import 'theme.dart';
import 'widgets.dart';

DateTime _mexicoNow() =>
    DateTime.now().toUtc().subtract(const Duration(hours: 6));
String _calendar(DateTime value) =>
    '${value.year.toString().padLeft(4, '0')}-${value.month.toString().padLeft(2, '0')}-${value.day.toString().padLeft(2, '0')}';
DateTime? _parseDay(Object? value) =>
    value is String ? DateTime.tryParse(value) : null;
int _mexicoEpoch(DateTime day, TimeOfDay time) =>
    DateTime.utc(
      day.year,
      day.month,
      day.day,
      time.hour + 6,
      time.minute,
    ).millisecondsSinceEpoch ~/
    1000;
int _revision(JsonMap value) {
  final revision = value['rev'];
  if (revision is! int) {
    throw ErrorApi(
      codigo: 'revision_desconocida',
      mensaje: 'Actualiza esta información antes de editarla.',
    );
  }
  return revision;
}

Future<DateTime?> _pickDay(BuildContext context, DateTime? current) =>
    showDatePicker(
      context: context,
      initialDate: current ?? _mexicoNow(),
      firstDate: DateTime(2020),
      lastDate: DateTime(2100),
      helpText: 'Elige la fecha',
      cancelText: 'Cancelar',
      confirmText: 'Elegir',
    );

String _dayLabel(DateTime? value) =>
    value == null ? 'Elegir fecha' : _calendar(value);

Future<T?> _scopedDialog<T>(BuildContext context, WidgetBuilder builder) async {
  final controller = CorteScope.of(context);
  final navigator = Navigator.of(context, rootNavigator: true);
  final route = DialogRoute<T>(
    context: context,
    builder: (_) => CorteScope(
      controller: controller,
      child: Builder(builder: builder),
    ),
  );
  final result = await navigator.push<T>(route);
  // The caller owns form controllers. Pop completes before the exit animation;
  // wait until the overlay is removed before its finally block disposes them.
  await route.completed;
  return result;
}

class _EditorDialog extends StatefulWidget {
  const _EditorDialog({
    required this.title,
    required this.parentContext,
    required this.fields,
    required this.operation,
    this.acceptRevision,
  });
  final String title;
  final String saveLabel = 'Guardar';
  final BuildContext parentContext;
  final List<Widget> Function(_EditorDialogState state) fields;
  final JsonMap Function(String opId) operation;
  final void Function(JsonMap)? acceptRevision;
  @override
  State<_EditorDialog> createState() => _EditorDialogState();
}

class _EditorDialogState extends State<_EditorDialog> {
  final form = GlobalKey<FormState>();
  String _opId = nuevoId();
  bool busy = false;
  bool _rejected = false;
  String? error;
  JsonMap? vigente;
  String? _replacementOf;
  String? _openedScope;
  String? _openedOwner;
  bool _bound = false;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (!_bound) {
      _openedScope = CorteScope.of(context).repo.cacheScope;
      _openedOwner = CorteScope.of(context).repo.ownerScope;
      _bound = true;
    }
  }

  void changed([VoidCallback? change]) => setState(() {
    change?.call();
    if (_rejected && vigente == null) {
      _opId = nuevoId();
      _rejected = false;
      error = null;
    }
  });

  Future<void> save() async {
    if (!form.currentState!.validate() || vigente != null) return;
    final ui = CorteScope.of(context);
    setState(() {
      busy = true;
      error = null;
    });
    try {
      if (ui.repo.cacheScope != _openedScope ||
          ui.repo.ownerScope != _openedOwner)
        throw ErrorApi(
          codigo: 'sesion_cambiada',
          mensaje:
              'La cuenta conectada cambió. Conserva tu edición y abre de nuevo este formulario.',
        );
      final operation = widget.operation(_opId);
      final outcome = _replacementOf == null
          ? await ui.repo.guardarOps([operation])
          : await ui.repo.resolverOperacion(_replacementOf!, operation);
      if (!mounted) return;
      ui.refresh();
      Navigator.of(context).pop(true);
      if (widget.parentContext.mounted) {
        toast(
          widget.parentContext,
          outcome.enCola
              ? 'Guardado en este equipo; pendiente de envío.'
              : 'Guardado en Corte.',
        );
      }
    } catch (failure) {
      if (!mounted) return;
      setState(() {
        busy = false;
        _rejected = true;
        error = failure is ErrorApi
            ? failure.mensaje
            : 'No pudimos guardar. Conservamos tu edición para reintentarlo.';
        vigente = failure is ErrorApi ? failure.vigente : null;
        if (ui.repo.copiaPersistenteDisponible &&
            failure is ErrorApi &&
            (failure.codigo == 'conflicto' ||
                failure.codigo == 'operacion_invalida'))
          _replacementOf = _opId;
      });
    }
  }

  @override
  Widget build(BuildContext context) => PopScope(
    canPop: !busy,
    child: Dialog(
      child: ConstrainedBox(
        constraints: BoxConstraints(
          maxWidth: 600,
          maxHeight: MediaQuery.sizeOf(context).height * .9,
        ),
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Text(
                      widget.title,
                      style: Theme.of(context).textTheme.titleLarge,
                    ),
                  ),
                  IconButton(
                    tooltip: 'Cerrar',
                    onPressed: busy ? null : () => Navigator.of(context).pop(),
                    icon: const Icon(Icons.close_rounded),
                  ),
                ],
              ),
              const SizedBox(height: 12),
              Flexible(
                child: SingleChildScrollView(
                  child: Form(
                    key: form,
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        ...widget.fields(this),
                        if (error != null) ...[
                          const SizedBox(height: 16),
                          InlineNotice(text: error!, error: true),
                          if (vigente != null &&
                              widget.acceptRevision != null) ...[
                            const SizedBox(height: 8),
                            Text(
                              'Versión actual ${textOf(vigente!['rev'])}. Tu edición sigue en el formulario.',
                              style: const TextStyle(color: CorteColors.muted),
                            ),
                            TextButton(
                              onPressed: busy
                                  ? null
                                  : () => setState(() {
                                      widget.acceptRevision!(vigente!);
                                      vigente = null;
                                      error = null;
                                      _rejected = false;
                                      _opId = nuevoId();
                                    }),
                              child: const Text(
                                'Revisé el conflicto; conservar mi edición',
                              ),
                            ),
                          ],
                        ],
                      ],
                    ),
                  ),
                ),
              ),
              const SizedBox(height: 22),
              Wrap(
                alignment: WrapAlignment.end,
                spacing: 10,
                runSpacing: 10,
                children: [
                  TextButton(
                    onPressed: busy ? null : () => Navigator.of(context).pop(),
                    child: const Text('Cancelar'),
                  ),
                  FilledButton.icon(
                    onPressed: busy || vigente != null ? null : save,
                    icon: busy
                        ? const SizedBox.square(
                            dimension: 17,
                            child: CircularProgressIndicator(
                              strokeWidth: 2,
                              color: Colors.white,
                            ),
                          )
                        : const Icon(Icons.check_rounded, size: 19),
                    label: Text(busy ? 'Guardando…' : widget.saveLabel),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    ),
  );
}

/// Creates/updates the existing PlanVideo contract, including stage-specific
/// dates, TikTok link and reasons. A server conflict never resets typed fields.
Future<bool?> showPlanEditor(
  BuildContext context,
  JsonMap muestra, {
  JsonMap? plan,
  String? estadoInicial,
}) async {
  final ui = CorteScope.of(context);
  JsonMap? current = plan;
  final sampleId = textOf(muestra['application_id']);
  if (current == null && sampleId.isNotEmpty) {
    try {
      final response = await ui.repo.get('/api/plan');
      final matching = rowsOf(
        response['items'],
      ).where((item) => item['application_id'] == sampleId);
      if (matching.isNotEmpty) current = matching.first;
    } catch (error) {
      if (!context.mounted) return null;
      // A known plan must not silently become another creation while offline.
      if (mapOf(muestra['avance'])['plan_id'] != null) {
        toast(
          context,
          error is ErrorApi
              ? error.mensaje
              : 'No pudimos abrir el plan actual.',
        );
        return null;
      }
    }
  }
  if (!context.mounted) return null;
  final product = mapOf(muestra['producto']);
  final store = mapOf(muestra['tienda']);
  final title = TextEditingController(
    text: textOf(
      current?['titulo'],
      textOf(product['titulo_corto'], textOf(product['titulo'], 'Video')),
    ),
  );
  final notes = TextEditingController(text: textOf(current?['notas']));
  final link = TextEditingController(text: textOf(current?['enlace_video']));
  final reasonText = TextEditingController(
    text: textOf(current?['motivo_texto']),
  );
  final id = textOf(current?['id'], nuevoId());
  String stage = estadoInicial ?? textOf(current?['estado'], 'planeada');
  const stages = {
    'por_planear': 'Por planear',
    'planeada': 'Planeada',
    'video_listo': 'Video listo',
    'programada': 'Programada',
    'publicada': 'Publicada',
    'no_se_puede': 'No se puede publicar',
  };
  if (!stages.containsKey(stage)) stage = 'por_planear';
  DateTime? planned = _parseDay(current?['fecha_plan']);
  DateTime? published = _parseDay(current?['fecha_publicada']);
  final scheduledEpoch = current?['programada_para_at'];
  final scheduled = scheduledEpoch is int
      ? DateTime.fromMillisecondsSinceEpoch(
          scheduledEpoch * 1000,
          isUtc: true,
        ).subtract(const Duration(hours: 6))
      : null;
  DateTime? scheduledDay = scheduled;
  TimeOfDay scheduledTime = scheduled == null
      ? const TimeOfDay(hour: 18, minute: 0)
      : TimeOfDay(hour: scheduled.hour, minute: scheduled.minute);
  String reason = textOf(current?['motivo_no_se_puede'], 'otro');
  const reasons = {
    'agotado': 'Producto agotado',
    'desactivado': 'Producto desactivado',
    'no_llego': 'No me llegó',
    'incompleta': 'Muestra incompleta',
    'no_va_con_mi_contenido': 'No va con mi contenido',
    'otro': 'Otro motivo',
  };
  if (!reasons.containsKey(reason)) reason = 'otro';
  bool acceptedPrior = current?['vinculo_origen'] == 'video_previo_aceptado';
  final isPrior = current?['vinculo_origen'] == 'video_previo' || acceptedPrior;
  try {
    return await _scopedDialog<bool>(
      context,
      (dialogContext) => _EditorDialog(
        title: current == null ? 'Planear video' : 'Editar plan',
        parentContext: context,
        acceptRevision: (value) => current = {...?current, 'rev': value['rev']},
        fields: (state) => [
          TextFormField(
            controller: title,
            maxLength: 200,
            onChanged: (_) => state.changed(),
            decoration: const InputDecoration(labelText: 'Nombre del video'),
            validator: (value) => value == null || value.trim().isEmpty
                ? 'Escribe un nombre.'
                : null,
          ),
          const SizedBox(height: 14),
          DropdownButtonFormField<String>(
            initialValue: stage,
            isExpanded: true,
            decoration: const InputDecoration(labelText: 'Tu avance'),
            items: stages.entries
                .map(
                  (item) => DropdownMenuItem(
                    value: item.key,
                    child: Text(item.value),
                  ),
                )
                .toList(),
            onChanged: state.busy
                ? null
                : (value) => state.changed(() => stage = value ?? stage),
          ),
          const SizedBox(height: 16),
          if (stage == 'planeada') ...[
            const Text('¿Qué día harás el video?'),
            const SizedBox(height: 8),
            OutlinedButton.icon(
              onPressed: state.busy
                  ? null
                  : () async {
                      final value = await _pickDay(dialogContext, planned);
                      if (value != null && state.mounted)
                        state.changed(() => planned = value);
                    },
              icon: const Icon(Icons.calendar_today_outlined, size: 18),
              label: Text(_dayLabel(planned)),
            ),
            const SizedBox(height: 16),
          ],
          if (stage == 'programada') ...[
            const Text('Publicación programada · hora de México'),
            const SizedBox(height: 8),
            Wrap(
              spacing: 12,
              runSpacing: 8,
              children: [
                OutlinedButton(
                  onPressed: state.busy
                      ? null
                      : () async {
                          final value = await _pickDay(
                            dialogContext,
                            scheduledDay,
                          );
                          if (value != null && state.mounted)
                            state.changed(() => scheduledDay = value);
                        },
                  child: Text(_dayLabel(scheduledDay)),
                ),
                OutlinedButton(
                  onPressed: state.busy
                      ? null
                      : () async {
                          final value = await showTimePicker(
                            context: dialogContext,
                            initialTime: scheduledTime,
                            helpText: 'Hora de publicación',
                          );
                          if (value != null && state.mounted)
                            state.changed(() => scheduledTime = value);
                        },
                  child: Text(scheduledTime.format(dialogContext)),
                ),
              ],
            ),
            const SizedBox(height: 16),
          ],
          if (stage == 'publicada') ...[
            OutlinedButton.icon(
              onPressed: state.busy
                  ? null
                  : () async {
                      final value = await _pickDay(dialogContext, published);
                      if (value != null && state.mounted)
                        state.changed(() => published = value);
                    },
              icon: const Icon(Icons.event_outlined),
              label: Text(
                published == null
                    ? 'Fecha de publicación: hoy'
                    : _dayLabel(published),
              ),
            ),
            const SizedBox(height: 16),
          ],
          if (stage == 'video_listo' ||
              stage == 'programada' ||
              stage == 'publicada') ...[
            TextFormField(
              controller: link,
              onChanged: (_) => state.changed(),
              keyboardType: TextInputType.url,
              decoration: const InputDecoration(
                labelText: 'Enlace del video de TikTok (opcional)',
                hintText: 'https://www.tiktok.com/@…/video/…',
              ),
              validator: (value) {
                if (value == null || value.trim().isEmpty) return null;
                final uri = Uri.tryParse(value.trim());
                return uri == null ||
                        uri.scheme != 'https' ||
                        !(uri.host == 'tiktok.com' ||
                            uri.host.endsWith('.tiktok.com'))
                    ? 'Usa un enlace HTTPS de TikTok.'
                    : null;
              },
            ),
            if (isPrior)
              CheckboxListTile(
                contentPadding: EdgeInsets.zero,
                value: acceptedPrior,
                onChanged: state.busy
                    ? null
                    : (value) =>
                          state.changed(() => acceptedPrior = value ?? false),
                title: const Text('La tienda aceptó este video anterior'),
              ),
            const SizedBox(height: 16),
          ],
          if (stage == 'no_se_puede') ...[
            DropdownButtonFormField<String>(
              initialValue: reason,
              isExpanded: true,
              decoration: const InputDecoration(labelText: 'Motivo'),
              items: reasons.entries
                  .map(
                    (item) => DropdownMenuItem(
                      value: item.key,
                      child: Text(item.value),
                    ),
                  )
                  .toList(),
              onChanged: state.busy
                  ? null
                  : (value) => state.changed(() => reason = value ?? reason),
            ),
            const SizedBox(height: 16),
            TextFormField(
              controller: reasonText,
              maxLength: 300,
              onChanged: (_) => state.changed(),
              decoration: const InputDecoration(
                labelText: 'Detalle del motivo (opcional)',
              ),
            ),
          ],
          TextFormField(
            controller: notes,
            minLines: 2,
            maxLines: 5,
            maxLength: 5000,
            onChanged: (_) => state.changed(),
            decoration: const InputDecoration(
              labelText: 'Notas para tu video (opcional)',
            ),
          ),
        ],
        operation: (opId) {
          if (stage == 'planeada' && planned == null)
            throw ErrorApi(
              codigo: 'fecha_faltante',
              mensaje: 'Elige qué día harás el video.',
            );
          if (stage == 'programada' && scheduledDay == null)
            throw ErrorApi(
              codigo: 'fecha_faltante',
              mensaje: 'Elige la fecha de publicación programada.',
            );
          if (stage == 'publicada' && isPrior && !acceptedPrior)
            throw ErrorApi(
              codigo: 'video_previo',
              mensaje:
                  'Confirma que la tienda aceptó este video anterior o usa otro video.',
            );
          final changes = <String, dynamic>{
            'titulo': title.text.trim(),
            'estado': stage,
            'notas': notes.text.trim().isEmpty ? null : notes.text.trim(),
          };
          if (planned != null) changes['fecha_plan'] = _calendar(planned!);
          if (stage == 'video_listo' && current?['fecha_video_listo'] == null)
            changes['fecha_video_listo'] = _calendar(_mexicoNow());
          if (stage == 'programada')
            changes['programada_para_at'] = _mexicoEpoch(
              scheduledDay!,
              scheduledTime,
            );
          if (stage == 'publicada' &&
              (published != null || current?['estado'] != 'publicada'))
            changes['fecha_publicada'] = _calendar(published ?? _mexicoNow());
          if (link.text.trim().isNotEmpty) {
            changes['enlace_video'] = link.text.trim();
            final match = RegExp(
              r'/video/(\d+)',
            ).firstMatch(Uri.parse(link.text.trim()).path);
            if (match != null) changes['content_id'] = match.group(1);
            changes['vinculo_origen'] = isPrior
                ? (acceptedPrior ? 'video_previo_aceptado' : 'video_previo')
                : 'manual';
          }
          if (stage == 'no_se_puede') {
            changes['motivo_no_se_puede'] = reason;
            changes['motivo_texto'] = reasonText.text.trim().isEmpty
                ? null
                : reasonText.text.trim();
          }
          return current == null
              ? {
                  'op_id': opId,
                  'tipo': 'plan.crear',
                  'datos': {
                    'id': id,
                    'application_id': sampleId.isEmpty ? null : sampleId,
                    'product_id': product['product_id'],
                    'tienda_key': store['tienda_key'],
                    ...changes,
                  },
                }
              : {
                  'op_id': opId,
                  'tipo': 'plan.editar',
                  'id': id,
                  'cambios': {'rev': _revision(current!), ...changes},
                };
        },
      ),
    );
  } finally {
    title.dispose();
    notes.dispose();
    link.dispose();
    reasonText.dispose();
  }
}

Future<bool?> showMessageEditor(
  BuildContext context, {
  required JsonMap tienda,
  List<JsonMap> muestras = const [],
  String? plantillaId,
}) => _scopedDialog<bool>(
  context,
  (_) => MessageEditorDialog(
    tienda: tienda,
    muestras: muestras,
    plantillaId: plantillaId,
  ),
);

/// Copies a real stored template and records the corresponding local notice.
/// Copying and marking a message sent are separate, explicit actions.
class MessageEditorDialog extends StatefulWidget {
  const MessageEditorDialog({
    super.key,
    required this.tienda,
    this.muestras = const [],
    this.plantillaId,
  });
  final JsonMap tienda;
  final List<JsonMap> muestras;
  final String? plantillaId;
  @override
  State<MessageEditorDialog> createState() => _MessageEditorDialogState();
}

class _MessageEditorDialogState extends State<MessageEditorDialog> {
  final _body = TextEditingController();
  final _link = TextEditingController();
  final _commitments = <String, String>{};
  List<JsonMap> _templates = [];
  String? _selected, _prior, _scope, _owner, _error;
  String _signature = '', _problem = 'no_llego';
  bool _loading = true, _busy = false, _initialized = false, _copied = false;
  String _opId = nuevoId();
  final String _noticeId = nuevoId();
  int? _noticeRev;
  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_initialized) return;
    _initialized = true;
    _scope = CorteScope.of(context).repo.cacheScope;
    _owner = CorteScope.of(context).repo.ownerScope;
    _load();
  }

  Future<void> _load() async {
    try {
      final repo = CorteScope.of(context).repo;
      final responses = await Future.wait([
        repo.get('/api/plantillas'),
        repo.get('/api/preferencias'),
      ]);
      if (!mounted) return;
      _templates = rowsOf(responses[0]['items']);
      _signature = textOf(responses[1]['firma_mensajes']);
      if (_signature.isEmpty) _signature = textOf(responses[1]['firma']);
      for (final sample in widget.muestras) {
        final id = textOf(sample['application_id']);
        final advance = mapOf(sample['avance']);
        final promise = mapOf(sample['avisos'])['promesa'];
        final commitment = advance['fecha_planeada'];
        if (commitment is String) _commitments[id] = commitment;
        if (promise is String &&
            (_prior == null || promise.compareTo(_prior!) > 0))
          _prior = promise;
        if (_link.text.isEmpty && advance['enlace_video'] is String)
          _link.text = advance['enlace_video'] as String;
      }
      final preferred =
          widget.plantillaId ??
          (widget.muestras.length > 1 ? 'varias_muestras' : 'disculpa_y_fecha');
      final candidates = _templates.where((item) => item['id'] == preferred);
      if (_templates.isEmpty)
        throw ErrorApi(
          codigo: 'plantillas_no_disponibles',
          mensaje:
              'No hay plantillas disponibles en esta copia. Conecta Corte y actualiza.',
        );
      _choose(candidates.isEmpty ? _templates.first : candidates.first);
      setState(() => _loading = false);
    } catch (error) {
      if (mounted)
        setState(() {
          _loading = false;
          _error = error is ErrorApi
              ? error.mensaje
              : 'No pudimos abrir las plantillas. Vuelve a intentarlo.';
        });
    }
  }

  void _choose(JsonMap template) {
    _selected = textOf(template['id']);
    _body.text = textOf(template['cuerpo']);
    const single =
        'Hola, equipo de {tienda}. Les dije que publicaba el video de {producto} el {fecha_anterior} y no lo cumplí; una disculpa. Ya lo tengo para el {fecha_compromiso}. Gracias por la paciencia.{firma}';
    if (_selected == 'nueva_fecha' &&
        template['predeterminada'] == true &&
        widget.muestras.length >= 2 &&
        _body.text.trim() == single) {
      _body.text =
          'Hola, equipo de {tienda}. Les dije que publicaba los videos el {fecha_anterior} y no lo cumplí; una disculpa. Ya los tengo así:\n{lista_fechas}\nGracias por la paciencia.{firma}';
    }
  }

  MensajeResuelto get _resolved => resolverMensaje(
    cuerpo: _body.text,
    tienda: widget.tienda,
    muestras: widget.muestras,
    compromisos: _commitments,
    fechaAnterior: _prior,
    linkVideo: _link.text,
    firma: _signature,
    problemaEnvio: _problem,
  );
  Future<void> _save({required bool sent}) async {
    final resolved = _resolved;
    if (!resolved.puedeCopiar || _busy) return;
    final ui = CorteScope.of(context);
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      if (ui.repo.cacheScope != _scope || ui.repo.ownerScope != _owner)
        throw ErrorApi(
          codigo: 'sesion_cambiada',
          mensaje: 'La cuenta conectada cambió. Abre de nuevo este mensaje.',
        );
      final now = DateTime.now().toUtc().millisecondsSinceEpoch ~/ 1000;
      if (!sent) {
        try {
          await Clipboard.setData(ClipboardData(text: resolved.texto));
        } catch (_) {
          throw ErrorApi(
            codigo: 'portapapeles_no_disponible',
            mensaje:
                'No pudimos copiar al portapapeles. Conservamos el mensaje para volver a intentarlo.',
          );
        }
        _copied = true;
      }
      final op = <String, dynamic>{
        'op_id': _opId,
        if (_noticeRev == null) ...{
          'tipo': 'aviso.crear',
          'datos': {
            'id': _noticeId,
            'tienda_key': widget.tienda['tienda_key'],
            'solicitud_ids': widget.muestras
                .map((item) => item['application_id'])
                .whereType<String>()
                .toList(),
            'plantilla_id': _selected,
            'texto': resolved.texto,
            'compromisos': _commitments,
            'origen': _copied ? 'copiado' : 'por_mi_cuenta',
            'fecha_anterior': _prior,
            'copiado_at': _copied ? now : null,
            'marcado_enviado_at': sent ? now : null,
          },
        } else ...{
          'tipo': 'aviso.editar',
          'id': _noticeId,
          'cambios': {
            'rev': _noticeRev,
            'texto': resolved.texto,
            'compromisos': _commitments,
            if (sent) 'marcado_enviado_at': now,
          },
        },
      };
      final result = await ui.repo.guardarOps([op]);
      if (!mounted) return;
      _noticeRev = (_noticeRev ?? 0) + 1;
      for (final ack in result.resultados) {
        if (ack['op_id'] == _opId &&
            ack['objeto'] is Map &&
            (ack['objeto'] as Map)['rev'] is int)
          _noticeRev = (ack['objeto'] as Map)['rev'] as int;
      }
      _opId = nuevoId();
      ui.refresh();
      if (sent) {
        Navigator.of(context).pop(true);
      } else
        setState(() => _busy = false);
      if (mounted)
        toast(
          context,
          result.enCola
              ? '${sent ? 'Envío registrado' : 'Mensaje copiado'} en este equipo; pendiente de sincronizar.'
              : sent
              ? 'Marcado como enviado.'
              : 'Mensaje copiado. Envíalo en el chat de TikTok y luego márcalo como enviado.',
        );
    } catch (error) {
      if (mounted)
        setState(() {
          _busy = false;
          _error =
              '${_copied && _noticeRev == null ? 'El mensaje está en el portapapeles, pero falta guardar el aviso. ' : ''}${error is ErrorApi ? error.mensaje : 'No pudimos guardar el aviso. Conservamos el mensaje.'}';
        });
    }
  }

  @override
  void dispose() {
    _body.dispose();
    _link.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final resolved = _resolved;
    final needsDates =
        _body.text.contains('{fecha_compromiso}') ||
        _body.text.contains('{lista_fechas}');
    return PopScope(
      canPop: !_busy,
      child: Dialog(
        child: ConstrainedBox(
          constraints: BoxConstraints(
            maxWidth: 640,
            maxHeight: MediaQuery.sizeOf(context).height * .92,
          ),
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: Text(
                        'Mensaje a ${textOf(widget.tienda['nombre'], 'la tienda')}',
                        style: Theme.of(context).textTheme.titleLarge,
                      ),
                    ),
                    IconButton(
                      tooltip: 'Cerrar',
                      onPressed: _busy
                          ? null
                          : () => Navigator.of(context).pop(),
                      icon: const Icon(Icons.close_rounded),
                    ),
                  ],
                ),
                const SizedBox(height: 16),
                Flexible(
                  child: SingleChildScrollView(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        if (_loading)
                          const Center(child: CircularProgressIndicator())
                        else if (_templates.isNotEmpty) ...[
                          DropdownButtonFormField<String>(
                            initialValue: _selected,
                            isExpanded: true,
                            decoration: const InputDecoration(
                              labelText: 'Plantilla',
                            ),
                            items: _templates
                                .map(
                                  (item) => DropdownMenuItem(
                                    value: textOf(item['id']),
                                    child: Text(
                                      textOf(
                                        item['nombre'],
                                        textOf(
                                          item['titulo'],
                                          textOf(item['id']),
                                        ),
                                      ),
                                      overflow: TextOverflow.ellipsis,
                                    ),
                                  ),
                                )
                                .toList(),
                            onChanged: _busy || _noticeRev != null
                                ? null
                                : (value) => setState(
                                    () => _choose(
                                      _templates.firstWhere(
                                        (item) => item['id'] == value,
                                      ),
                                    ),
                                  ),
                          ),
                          if (needsDates) ...[
                            const SizedBox(height: 16),
                            const Text('Fechas que puedes cumplir'),
                            for (final sample in widget.muestras)
                              Padding(
                                padding: const EdgeInsets.only(top: 8),
                                child: OutlinedButton.icon(
                                  onPressed: _busy
                                      ? null
                                      : () async {
                                          final id = textOf(
                                            sample['application_id'],
                                          );
                                          final day = await _pickDay(
                                            context,
                                            _parseDay(_commitments[id]),
                                          );
                                          if (day != null && mounted)
                                            setState(
                                              () => _commitments[id] =
                                                  _calendar(day),
                                            );
                                        },
                                  icon: const Icon(
                                    Icons.calendar_today_outlined,
                                    size: 18,
                                  ),
                                  label: Text(
                                    '${nombreProductoMensaje(sample)} · ${_commitments[sample['application_id']] ?? 'Elegir fecha'}',
                                  ),
                                ),
                              ),
                          ],
                          if (_body.text.contains('{fecha_anterior}')) ...[
                            const SizedBox(height: 12),
                            OutlinedButton.icon(
                              onPressed: _busy
                                  ? null
                                  : () async {
                                      final day = await _pickDay(
                                        context,
                                        _parseDay(_prior),
                                      );
                                      if (day != null && mounted)
                                        setState(() => _prior = _calendar(day));
                                    },
                              icon: const Icon(Icons.history_rounded, size: 18),
                              label: Text(
                                'Fecha anterior: ${_prior ?? 'Elegir fecha'}',
                              ),
                            ),
                          ],
                          if (_body.text.contains('{link_video}')) ...[
                            const SizedBox(height: 12),
                            TextField(
                              controller: _link,
                              enabled: !_busy,
                              onChanged: (_) => setState(() {}),
                              decoration: const InputDecoration(
                                labelText: 'Enlace del video de TikTok',
                              ),
                            ),
                          ],
                          if (_body.text.contains('{problema_envio}')) ...[
                            const SizedBox(height: 12),
                            DropdownButtonFormField<String>(
                              initialValue: _problem,
                              decoration: const InputDecoration(
                                labelText: 'Problema de envío',
                              ),
                              items: const [
                                DropdownMenuItem(
                                  value: 'no_llego',
                                  child: Text('No me llegó'),
                                ),
                                DropdownMenuItem(
                                  value: 'incompleta',
                                  child: Text('Llegó incompleta'),
                                ),
                              ],
                              onChanged: _busy
                                  ? null
                                  : (value) => setState(
                                      () => _problem = value ?? _problem,
                                    ),
                            ),
                          ],
                          const SizedBox(height: 16),
                          const Text('Vista previa'),
                          const SizedBox(height: 8),
                          SelectableText(resolved.texto),
                          const SizedBox(height: 8),
                          ExpansionTile(
                            title: const Text('Editar texto de este mensaje'),
                            tilePadding: EdgeInsets.zero,
                            children: [
                              TextField(
                                controller: _body,
                                enabled: !_busy,
                                maxLines: 7,
                                maxLength: 5000,
                                onChanged: (_) => setState(() {}),
                                decoration: const InputDecoration(
                                  labelText:
                                      'Texto y variables de la plantilla',
                                ),
                              ),
                            ],
                          ),
                          if (resolved.faltantes.isNotEmpty)
                            InlineNotice(
                              text:
                                  'Completa los datos antes de copiar: ${resolved.faltantes.join(', ')}.',
                            ),
                          const SizedBox(height: 12),
                          const Text(
                            'Copiar registra el aviso. Marca «Ya lo envié» sólo después de enviarlo en el chat.',
                            style: TextStyle(color: CorteColors.muted),
                          ),
                        ],
                        if (_error != null) ...[
                          const SizedBox(height: 12),
                          InlineNotice(text: _error!, error: true),
                        ],
                      ],
                    ),
                  ),
                ),
                const SizedBox(height: 20),
                Wrap(
                  alignment: WrapAlignment.end,
                  spacing: 12,
                  runSpacing: 10,
                  children: [
                    OutlinedButton(
                      onPressed: _busy || !resolved.puedeCopiar || _loading
                          ? null
                          : () => _save(sent: true),
                      child: const Text('Ya lo envié'),
                    ),
                    FilledButton.icon(
                      onPressed: _busy || !resolved.puedeCopiar || _loading
                          ? null
                          : () => _save(sent: false),
                      icon: Icon(
                        _busy
                            ? Icons.hourglass_empty_rounded
                            : Icons.copy_rounded,
                      ),
                      label: Text(_busy ? 'Guardando…' : 'Copiar mensaje'),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

Future<bool?> showNoteEditor(
  BuildContext context,
  String entidad,
  String? entidadId, {
  JsonMap? note,
}) => _noteEditor(context, entidad, entidadId, note: note);

Future<bool?> _noteEditor(
  BuildContext context,
  String entidad,
  String? entidadId, {
  JsonMap? note,
}) async {
  JsonMap? current = note;
  final controller = TextEditingController(text: textOf(note?['texto']));
  bool pinned = note?['fijada'] == true;
  final id = textOf(note?['id'], nuevoId());
  try {
    return await _scopedDialog<bool>(
      context,
      (_) => _EditorDialog(
        title: note == null ? 'Añadir nota' : 'Editar nota',
        parentContext: context,
        acceptRevision: (value) => current = {...?current, 'rev': value['rev']},
        fields: (state) => [
          TextFormField(
            controller: controller,
            minLines: 4,
            maxLines: 10,
            maxLength: 5000,
            onChanged: (_) => state.changed(),
            decoration: const InputDecoration(labelText: 'Tu nota'),
            validator: (value) => value == null || value.trim().isEmpty
                ? 'Escribe la nota.'
                : null,
          ),
          CheckboxListTile(
            contentPadding: EdgeInsets.zero,
            value: pinned,
            title: const Text('Fijar esta nota'),
            onChanged: state.busy
                ? null
                : (value) => state.changed(() => pinned = value ?? false),
          ),
        ],
        operation: (opId) => current == null
            ? {
                'op_id': opId,
                'tipo': 'nota.crear',
                'datos': {
                  'id': id,
                  'entidad': entidad,
                  'entidad_id': entidadId,
                  'texto': controller.text.trim(),
                  'fijada': pinned,
                },
              }
            : {
                'op_id': opId,
                'tipo': 'nota.editar',
                'id': id,
                'cambios': {
                  'texto': controller.text.trim(),
                  'fijada': pinned,
                  'rev': _revision(current!),
                },
              },
      ),
    );
  } finally {
    controller.dispose();
  }
}

Future<void> _localAction(BuildContext context, JsonMap operation) async {
  final ui = CorteScope.of(context);
  try {
    final result = await ui.repo.guardarOps([operation]);
    if (!context.mounted) return;
    ui.refresh();
    toast(
      context,
      result.enCola
          ? 'Guardado en este equipo; pendiente de envío.'
          : 'Guardado en Corte.',
    );
  } catch (error) {
    if (context.mounted)
      toast(
        context,
        error is ErrorApi ? error.mensaje : 'No pudimos guardar este cambio.',
      );
  }
}

Future<bool> _confirmDelete(BuildContext context, String title) async =>
    await showDialog<bool>(
      context: context,
      builder: (dialog) => AlertDialog(
        title: Text(title),
        content: const Text(
          'Este cambio se guardará también en tus otros dispositivos.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialog).pop(false),
            child: const Text('Conservar'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(dialog).pop(true),
            child: const Text('Eliminar'),
          ),
        ],
      ),
    ) ??
    false;

class NotesPanel extends StatelessWidget {
  const NotesPanel({
    super.key,
    required this.entidad,
    this.entidadId,
    this.initialNotes,
  });
  final String entidad;
  final String? entidadId;
  final List<JsonMap>? initialNotes;
  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      SectionHeading(
        'Notas',
        action: TextButton.icon(
          onPressed: () => _noteEditor(context, entidad, entidadId),
          icon: const Icon(Icons.add_rounded),
          label: const Text('Añadir'),
        ),
      ),
      ApiData(
        path: '/api/notas',
        query: {'entidad': entidad, 'entidad_id': entidadId},
        padding: EdgeInsets.zero,
        builder: (context, data) {
          final notes = rowsOf(data['items']);
          if (notes.isEmpty)
            return const Padding(
              padding: EdgeInsets.symmetric(vertical: 12),
              child: Text(
                'Añade ideas, detalles o algo que quieras recordar.',
                style: TextStyle(color: CorteColors.muted),
              ),
            );
          return Column(
            children: notes
                .map(
                  (note) => Padding(
                    padding: const EdgeInsets.symmetric(vertical: 12),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        if (note['fijada'] == true)
                          const Padding(
                            padding: EdgeInsets.only(top: 4, right: 9),
                            child: Icon(
                              Icons.push_pin_outlined,
                              size: 17,
                              color: CorteColors.action,
                            ),
                          ),
                        Expanded(child: SelectableText(textOf(note['texto']))),
                        PopupMenuButton<String>(
                          tooltip: 'Acciones de nota',
                          onSelected: (action) async {
                            if (action == 'editar') {
                              await _noteEditor(
                                context,
                                entidad,
                                entidadId,
                                note: note,
                              );
                              return;
                            }
                            if (await _confirmDelete(
                                  context,
                                  '¿Eliminar esta nota?',
                                ) &&
                                context.mounted) {
                              await _localAction(context, {
                                'op_id': nuevoId(),
                                'tipo': 'nota.borrar',
                                'id': note['id'],
                                'rev': _revision(note),
                              });
                            }
                          },
                          itemBuilder: (_) => const [
                            PopupMenuItem(
                              value: 'editar',
                              child: Text('Editar'),
                            ),
                            PopupMenuItem(
                              value: 'borrar',
                              child: Text('Eliminar'),
                            ),
                          ],
                        ),
                      ],
                    ),
                  ),
                )
                .toList(),
          );
        },
      ),
    ],
  );
}

Future<bool?> showReminderEditor(
  BuildContext context,
  String entidad,
  String? entidadId, {
  JsonMap? reminder,
}) => _reminderEditor(context, entidad, entidadId, reminder: reminder);

Future<bool?> _reminderEditor(
  BuildContext context,
  String entidad,
  String? entidadId, {
  JsonMap? reminder,
}) async {
  JsonMap? current = reminder;
  final title = TextEditingController(text: textOf(reminder?['titulo']));
  final epoch = reminder?['vence_at'];
  final moment = epoch is int
      ? DateTime.fromMillisecondsSinceEpoch(
          epoch * 1000,
          isUtc: true,
        ).subtract(const Duration(hours: 6))
      : _mexicoNow().add(const Duration(hours: 1));
  DateTime day = moment;
  TimeOfDay time = TimeOfDay(hour: moment.hour, minute: moment.minute);
  String repeat = textOf(reminder?['repetir'], 'no');
  final id = textOf(reminder?['id'], nuevoId());
  try {
    return await _scopedDialog<bool>(
      context,
      (dialog) => _EditorDialog(
        title: reminder == null ? 'Crear recordatorio' : 'Editar recordatorio',
        parentContext: context,
        acceptRevision: (value) => current = {...?current, 'rev': value['rev']},
        fields: (state) => [
          TextFormField(
            controller: title,
            maxLength: 200,
            onChanged: (_) => state.changed(),
            decoration: const InputDecoration(
              labelText: '¿Qué quieres recordar?',
            ),
            validator: (value) => value == null || value.trim().isEmpty
                ? 'Escribe un título.'
                : null,
          ),
          const SizedBox(height: 12),
          const Text('Fecha y hora de México'),
          const SizedBox(height: 8),
          Wrap(
            spacing: 12,
            runSpacing: 8,
            children: [
              OutlinedButton(
                onPressed: state.busy
                    ? null
                    : () async {
                        final value = await _pickDay(dialog, day);
                        if (value != null && state.mounted)
                          state.changed(() => day = value);
                      },
                child: Text(_dayLabel(day)),
              ),
              OutlinedButton(
                onPressed: state.busy
                    ? null
                    : () async {
                        final value = await showTimePicker(
                          context: dialog,
                          initialTime: time,
                        );
                        if (value != null && state.mounted)
                          state.changed(() => time = value);
                      },
                child: Text(time.format(dialog)),
              ),
            ],
          ),
          const SizedBox(height: 18),
          DropdownButtonFormField<String>(
            initialValue: repeat,
            decoration: const InputDecoration(labelText: 'Repetir'),
            items: const [
              DropdownMenuItem(value: 'no', child: Text('No repetir')),
              DropdownMenuItem(value: 'diario', child: Text('Cada día')),
              DropdownMenuItem(value: 'semanal', child: Text('Cada semana')),
            ],
            onChanged: state.busy
                ? null
                : (value) => state.changed(() => repeat = value ?? repeat),
          ),
        ],
        operation: (opId) {
          final values = {
            'titulo': title.text.trim(),
            'vence_at': _mexicoEpoch(day, time),
            'repetir': repeat,
          };
          return current == null
              ? {
                  'op_id': opId,
                  'tipo': 'recordatorio.crear',
                  'datos': {
                    'id': id,
                    'entidad': entidad,
                    'entidad_id': entidadId,
                    ...values,
                  },
                }
              : {
                  'op_id': opId,
                  'tipo': 'recordatorio.editar',
                  'id': id,
                  'cambios': {'rev': _revision(current!), ...values},
                };
        },
      ),
    );
  } finally {
    title.dispose();
  }
}

class RemindersPanel extends StatelessWidget {
  const RemindersPanel({
    super.key,
    required this.entidad,
    this.entidadId,
    this.initialReminders,
  });
  final String entidad;
  final String? entidadId;
  final List<JsonMap>? initialReminders;
  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      SectionHeading(
        'Recordatorios',
        action: TextButton.icon(
          onPressed: () => _reminderEditor(context, entidad, entidadId),
          icon: const Icon(Icons.add_rounded),
          label: const Text('Añadir'),
        ),
      ),
      ApiData(
        path: '/api/recordatorios',
        padding: EdgeInsets.zero,
        builder: (context, data) {
          final reminders = rowsOf(data['items'])
              .where(
                (item) =>
                    item['entidad'] == entidad &&
                    item['entidad_id'] == entidadId,
              )
              .toList();
          if (reminders.isEmpty)
            return const Padding(
              padding: EdgeInsets.symmetric(vertical: 12),
              child: Text(
                'Organiza aquí tus próximos pasos.',
                style: TextStyle(color: CorteColors.muted),
              ),
            );
          return Column(
            children: reminders
                .map(
                  (item) => Padding(
                    padding: const EdgeInsets.symmetric(vertical: 10),
                    child: Row(
                      children: [
                        IconButton(
                          tooltip: item['estado'] == 'hecho'
                              ? 'Volver a activar recordatorio'
                              : 'Marcar como hecho',
                          onPressed: () => _localAction(context, {
                            'op_id': nuevoId(),
                            'tipo': 'recordatorio.editar',
                            'id': item['id'],
                            'cambios': {
                              'rev': _revision(item),
                              'estado': item['estado'] == 'hecho'
                                  ? 'activo'
                                  : 'hecho',
                            },
                          }),
                          icon: Icon(
                            item['estado'] == 'hecho'
                                ? Icons.check_circle_rounded
                                : Icons.radio_button_unchecked_rounded,
                            color: item['estado'] == 'hecho'
                                ? CorteColors.cyanInk
                                : CorteColors.muted,
                          ),
                        ),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                textOf(item['titulo']),
                                style: TextStyle(
                                  decoration: item['estado'] == 'hecho'
                                      ? TextDecoration.lineThrough
                                      : null,
                                ),
                              ),
                              Text(
                                date(
                                  item['pospuesto_hasta'] ?? item['vence_at'],
                                  time: true,
                                ),
                                style: const TextStyle(
                                  color: CorteColors.muted,
                                  fontSize: 12,
                                ),
                              ),
                            ],
                          ),
                        ),
                        PopupMenuButton<String>(
                          tooltip: 'Acciones de recordatorio',
                          onSelected: (action) async {
                            if (action == 'editar') {
                              await _reminderEditor(
                                context,
                                entidad,
                                entidadId,
                                reminder: item,
                              );
                              return;
                            }
                            if (action == 'posponer') {
                              await _localAction(context, {
                                'op_id': nuevoId(),
                                'tipo': 'recordatorio.editar',
                                'id': item['id'],
                                'cambios': {
                                  'rev': _revision(item),
                                  'estado': 'activo',
                                  'pospuesto_hasta':
                                      DateTime.now().millisecondsSinceEpoch ~/
                                          1000 +
                                      86400,
                                },
                              });
                              return;
                            }
                            if (await _confirmDelete(
                                  context,
                                  '¿Eliminar este recordatorio?',
                                ) &&
                                context.mounted)
                              await _localAction(context, {
                                'op_id': nuevoId(),
                                'tipo': 'recordatorio.borrar',
                                'id': item['id'],
                                'rev': _revision(item),
                              });
                          },
                          itemBuilder: (_) => const [
                            PopupMenuItem(
                              value: 'editar',
                              child: Text('Editar'),
                            ),
                            PopupMenuItem(
                              value: 'posponer',
                              child: Text('Posponer un día'),
                            ),
                            PopupMenuItem(
                              value: 'borrar',
                              child: Text('Eliminar'),
                            ),
                          ],
                        ),
                      ],
                    ),
                  ),
                )
                .toList(),
          );
        },
      ),
    ],
  );
}
