import 'package:flutter/foundation.dart' show listEquals;
import 'package:flutter/material.dart';

import '../app.dart';
import '../data/corte_repository.dart';
import 'editors.dart';
import 'format.dart';
import 'theme.dart';
import 'widgets.dart';

class SettingsPage extends StatelessWidget {
  const SettingsPage({super.key});
  @override
  Widget build(BuildContext context) {
    final ui = CorteScope.of(context);
    final auth = ui.auth.state;
    return SingleChildScrollView(
      padding: const EdgeInsets.all(24),
      child: Align(
        alignment: Alignment.topLeft,
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 820),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const PageTitle(
                'Ajustes',
                subtitle: 'Tu cuenta y tu forma de trabajar.',
              ),
              const SectionHeading('Apariencia'),
              const _AppearanceSettings(),
              const SectionHeading('Tu cuenta de Google'),
              _SettingLine(
                label: 'Sesión',
                value: auth.ownerEmail ?? 'Cuenta conectada',
              ),
              _SettingLine(
                label: 'Conexión',
                value: auth.connected ? 'En línea' : 'Sin conexión',
              ),
              Align(
                alignment: Alignment.centerLeft,
                child: OutlinedButton.icon(
                  onPressed: () async {
                    if (!await _confirm(
                          context,
                          '¿Salir de Corte?',
                          'Se cerrará el acceso a esta cuenta en este dispositivo. Los cambios guardados se conservan.',
                          'Salir',
                        ) ||
                        !context.mounted) {
                      return;
                    }
                    await ui.auth.signOut();
                  },
                  icon: const Icon(Icons.logout_rounded, size: 19),
                  label: const Text('Salir de esta cuenta'),
                ),
              ),
              const SectionHeading('TikTok Shop'),
              ApiData(
                path: '/api/sesion',
                padding: EdgeInsets.zero,
                builder: (context, data) {
                  final account = mapOf(data['cuenta']);
                  final connection = mapOf(data['conexion']);
                  final sync = mapOf(data['sync']);
                  final caps = mapOf(data['capacidades']);
                  return Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      _SettingLine(
                        label: 'Cuenta',
                        value:
                            account['username'] is String &&
                                (account['username'] as String).isNotEmpty
                            ? '@${account['username']}'
                            : 'Sin cuenta conectada',
                      ),
                      _SettingLine(
                        label: 'Estado',
                        value: _connectionLabel(connection['estado']),
                      ),
                      if (connection['aviso'] is String &&
                          (connection['aviso'] as String).isNotEmpty)
                        Padding(
                          padding: const EdgeInsets.only(bottom: 12),
                          child: InlineNotice(
                            text: connection['aviso'] as String,
                          ),
                        ),
                      _SettingLine(
                        label: 'Última sincronización completa',
                        value: date(sync['ultima_ok_at'], time: true),
                      ),
                      if (sync['en_curso'] == true) ...[
                        LinearProgressIndicator(
                          value: sync['progreso'] is num
                              ? (sync['progreso'] as num).toDouble().clamp(0, 1)
                              : null,
                        ),
                        const SizedBox(height: 8),
                        Text(textOf(sync['texto'], 'Sincronizando…')),
                      ],
                      if (mapOf(sync['ultimo_error'])['mensaje'] is String)
                        Padding(
                          padding: const EdgeInsets.only(top: 10),
                          child: InlineNotice(
                            text:
                                mapOf(sync['ultimo_error'])['mensaje']
                                    as String,
                            error: true,
                          ),
                        ),
                      if (caps['sincronizar'] == true)
                        Align(
                          alignment: Alignment.centerLeft,
                          child: _SyncButton(
                            disabled: sync['en_curso'] == true,
                          ),
                        ),
                    ],
                  );
                },
              ),
              const SizedBox(height: 14),
              ApiData(
                path: '/api/display/estado',
                padding: EdgeInsets.zero,
                builder: (context, data) => _SettingLine(
                  label: 'Videos de TikTok',
                  value: _displayLabel(data['estado']),
                ),
              ),
              const SectionHeading('Tu organización'),
              const _NotificationSettings(),
              _NavigationLine(
                icon: Icons.sticky_note_2_outlined,
                title: 'Notas',
                subtitle:
                    'Ideas y detalles de tus muestras, productos y tiendas.',
                onTap: () => ui.go('/notas'),
              ),
              _NavigationLine(
                icon: Icons.notifications_none_rounded,
                title: 'Recordatorios',
                subtitle: 'Revisa y organiza tus próximos pasos.',
                onTap: () => ui.go('/recordatorios'),
              ),
              const SectionHeading('Plan de trabajo'),
              ApiData(
                path: '/api/preferencias',
                padding: EdgeInsets.zero,
                builder: (context, data) => _PreferencesForm(value: data),
              ),
              const SectionHeading('Copia y cambios pendientes'),
              if (!ui.storageAvailable)
                const InlineNotice(
                  text:
                      'El almacenamiento de este dispositivo no está disponible. Los cambios necesitan conexión para guardarse.',
                  error: true,
                ),
              _PendingChanges(
                key: ValueKey('${ui.revision}:${ui.repo.cacheScope}'),
              ),
              const SizedBox(height: 32),
            ],
          ),
        ),
      ),
    );
  }
}

class _AppearanceSettings extends StatefulWidget {
  const _AppearanceSettings();
  @override
  State<_AppearanceSettings> createState() => _AppearanceSettingsState();
}

class _AppearanceSettingsState extends State<_AppearanceSettings> {
  int? _revision;
  String? _scope;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final ui = CorteScope.of(context);
    if (_revision == ui.revision && _scope == ui.repo.cacheScope) return;
    _revision = ui.revision;
    _scope = ui.repo.cacheScope;
    // Loading may notify the MaterialApp; start it after this build has ended.
    Future.microtask(() {
      if (mounted) ui.appearance.load(force: true);
    });
  }

  @override
  Widget build(BuildContext context) {
    final ui = CorteScope.of(context);
    final appearance = ui.appearance;
    return AnimatedBuilder(
      animation: appearance,
      builder: (context, _) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              for (final option in const [
                ('claro', 'Claro', Icons.light_mode_outlined),
                ('oscuro', 'Oscuro', Icons.dark_mode_outlined),
                ('sistema', 'Sistema', Icons.brightness_auto_outlined),
              ])
                ChoiceChip(
                  avatar: Icon(option.$3, size: 18),
                  label: Text(option.$2),
                  selected: appearance.value == option.$1,
                  onSelected:
                      !appearance.loaded ||
                          appearance.busy ||
                          appearance.pending ||
                          appearance.needsReview
                      ? null
                      : (selected) async {
                          if (!selected) return;
                          try {
                            final result = await appearance.choose(option.$1);
                            if (!mounted) return;
                            ui.refresh();
                            toast(
                              context,
                              result.enCola
                                  ? 'Apariencia guardada en este equipo; pendiente de envío.'
                                  : 'Apariencia guardada.',
                            );
                          } catch (_) {
                            if (mounted) ui.refresh();
                          }
                        },
                ),
            ],
          ),
          const SizedBox(height: 10),
          Text(
            appearance.busy
                ? 'Guardando tu elección…'
                : appearance.pending
                ? 'Tu elección se enviará cuando recuperes la conexión.'
                : appearance.value == 'sistema'
                ? 'Corte cambia con el tema de tu dispositivo.'
                : 'Tu elección se conserva en tu cuenta de Corte.',
            style: TextStyle(color: context.corte.muted),
          ),
          if (appearance.error != null) ...[
            const SizedBox(height: 10),
            InlineNotice(text: appearance.error!, error: true),
            if (!appearance.loaded)
              TextButton(
                onPressed: () => appearance.load(force: true),
                child: const Text('Reintentar'),
              ),
          ],
        ],
      ),
    );
  }
}

String _connectionLabel(Object? state) =>
    const {
      'conectada': 'Conectada',
      'sin_credenciales': 'Integración pendiente de configurar',
      'sin_autorizar': 'Pendiente de autorización',
      'reautorizar': 'Necesita volver a autorizarse',
      'cuenta_sin_region': 'Falta la región de la cuenta',
    }[state] ??
    'Estado no disponible';

String _displayLabel(Object? state) =>
    const {
      'conectada': 'Conectados',
      'sin_credenciales': 'Integración pendiente de configurar',
      'sin_conectar': 'Pendientes de autorización',
      'reautorizar': 'Necesitan volver a autorizarse',
    }[state] ??
    'Estado no disponible';

class _NotificationSettings extends StatefulWidget {
  const _NotificationSettings();
  @override
  State<_NotificationSettings> createState() => _NotificationSettingsState();
}

class _NotificationSettingsState extends State<_NotificationSettings> {
  String? permission;
  bool busy = false, loaded = false;
  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (loaded) return;
    loaded = true;
    final service = CorteScope.of(context).notifications;
    if (service.supported) {
      service
          .permission()
          .then((value) {
            if (mounted) setState(() => permission = value);
          })
          .catchError((Object _) {
            if (mounted) setState(() => permission = 'no_disponible');
          });
    }
  }

  @override
  Widget build(BuildContext _) {
    final ui = CorteScope.of(context);
    if (!ui.notifications.supported) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(bottom: 18),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            permission == 'concedido'
                ? 'Notificaciones permitidas en Android.'
                : permission == 'no_disponible'
                ? 'Las notificaciones no están disponibles en este dispositivo.'
                : 'Recibe avisos de tus recordatorios en este dispositivo.',
          ),
          if (permission == 'denegado')
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Text(
                'Android todavía no permite las notificaciones de Corte.',
                style: TextStyle(color: context.corte.muted),
              ),
            ),
          const SizedBox(height: 8),
          OutlinedButton.icon(
            onPressed:
                busy || permission == null || permission == 'no_disponible'
                ? null
                : () async {
                    setState(() => busy = true);
                    try {
                      final value = await ui.notifications.requestPermission();
                      if (!mounted) return;
                      setState(() => permission = value);
                      if (value == 'concedido') {
                        await ui.notifications.refresh(ui.repo);
                      }
                    } catch (_) {
                      if (mounted) {
                        toast(
                          context,
                          'No pudimos actualizar los permisos de notificaciones.',
                        );
                      }
                    } finally {
                      if (mounted) setState(() => busy = false);
                    }
                  },
            icon: const Icon(Icons.notifications_active_outlined, size: 19),
            label: Text(
              busy
                  ? 'Actualizando…'
                  : permission == 'concedido'
                  ? 'Actualizar avisos'
                  : 'Activar notificaciones',
            ),
          ),
        ],
      ),
    );
  }
}

class _SettingLine extends StatelessWidget {
  const _SettingLine({required this.label, required this.value});
  final String label, value;
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(bottom: 15),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: TextStyle(color: context.corte.muted, fontSize: 13)),
        const SizedBox(height: 3),
        SelectableText(
          value,
          style: const TextStyle(fontWeight: FontWeight.w600),
        ),
      ],
    ),
  );
}

class _NavigationLine extends StatelessWidget {
  const _NavigationLine({
    required this.icon,
    required this.title,
    required this.subtitle,
    required this.onTap,
  });
  final IconData icon;
  final String title, subtitle;
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) => ListTile(
    contentPadding: const EdgeInsets.symmetric(vertical: 7),
    leading: Icon(icon, color: context.corte.cyanInk),
    title: Text(title, style: const TextStyle(fontWeight: FontWeight.w700)),
    subtitle: Text(subtitle),
    trailing: const Icon(Icons.chevron_right_rounded),
    onTap: onTap,
  );
}

class _SyncButton extends StatefulWidget {
  const _SyncButton({required this.disabled});
  final bool disabled;
  @override
  State<_SyncButton> createState() => _SyncButtonState();
}

class _SyncButtonState extends State<_SyncButton> {
  bool busy = false;
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(top: 12),
    child: OutlinedButton.icon(
      onPressed: busy || widget.disabled
          ? null
          : () async {
              final ui = CorteScope.of(context);
              setState(() => busy = true);
              try {
                await ui.synchronize();
                if (context.mounted) {
                  toast(context, 'Sincronización solicitada.');
                }
              } catch (error) {
                if (context.mounted) toast(context, _errorText(error));
              } finally {
                if (mounted) setState(() => busy = false);
              }
            },
      icon: const Icon(Icons.sync_rounded, size: 19),
      label: Text(busy ? 'Solicitando…' : 'Sincronizar ahora'),
    ),
  );
}

class _PreferencesForm extends StatefulWidget {
  const _PreferencesForm({required this.value});
  final JsonMap value;
  @override
  State<_PreferencesForm> createState() => _PreferencesFormState();
}

class _PreferencesFormState extends State<_PreferencesForm> {
  final form = GlobalKey<FormState>();
  final signature = TextEditingController();
  late int capacity;
  late Set<int> days;
  late JsonMap base;
  String opId = nuevoId();
  bool busy = false, dirty = false;
  String? error;
  JsonMap? current;
  @override
  void initState() {
    super.initState();
    _load(widget.value);
  }

  void _load(JsonMap value) {
    base = value;
    capacity = intOf(value['capacidad_videos_dia'], 3).clamp(1, 10);
    days = value['dias_videos'] is List
        ? (value['dias_videos'] as List)
              .whereType<int>()
              .where((d) => d >= 0 && d <= 6)
              .toSet()
        : <int>{};
    signature.text = textOf(value['firma']);
    dirty = false;
    current = null;
    error = null;
    opId = nuevoId();
  }

  @override
  void didUpdateWidget(_PreferencesForm oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!dirty && oldWidget.value['rev'] != widget.value['rev']) {
      _load(widget.value);
    } else if (dirty &&
        !busy &&
        current == null &&
        base['rev'] != widget.value['rev'] &&
        base['capacidad_videos_dia'] == widget.value['capacidad_videos_dia'] &&
        base['firma'] == widget.value['firma'] &&
        listEquals(
          base['dias_videos'] as List?,
          widget.value['dias_videos'] as List?,
        )) {
      // Appearance uses the same preference revision. Safely advance the base
      // only if none of this form's fields changed on the server.
      base = widget.value;
      opId = nuevoId();
    }
  }

  @override
  void dispose() {
    signature.dispose();
    super.dispose();
  }

  void changed(VoidCallback update) => setState(() {
    update();
    dirty = true;
  });
  Future<void> save() async {
    if (busy || current != null || !form.currentState!.validate()) return;
    if (days.isEmpty) {
      setState(() => error = 'Elige al menos un día para tus videos.');
      return;
    }
    if (base['rev'] is! int) {
      setState(() => error = 'Actualiza las preferencias antes de guardarlas.');
      return;
    }
    final ui = CorteScope.of(context);
    setState(() {
      busy = true;
      error = null;
    });
    try {
      final result = await ui.repo.guardarOps([
        {
          'op_id': opId,
          'tipo': 'preferencias.editar',
          'cambios': {
            'rev': base['rev'],
            'capacidad_videos_dia': capacity,
            'dias_videos': days.toList()..sort(),
            'firma': signature.text.trim(),
          },
        },
      ]);
      if (!mounted) return;
      setState(() {
        dirty = false;
        opId = nuevoId();
      });
      ui.refresh();
      toast(
        context,
        result.enCola
            ? 'Guardado en este equipo; pendiente de envío.'
            : 'Preferencias guardadas.',
      );
    } catch (failure) {
      if (mounted) {
        setState(() {
          error = _errorText(failure);
          current = failure is ErrorApi ? failure.vigente : null;
        });
      }
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Form(
    key: form,
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        DropdownButtonFormField<int>(
          key: ValueKey('capacity:${base['rev']}'),
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
              : (value) => changed(() => capacity = value ?? capacity),
        ),
        const SizedBox(height: 18),
        const Text(
          'Días para tus videos',
          style: TextStyle(fontWeight: FontWeight.w600),
        ),
        const SizedBox(height: 8),
        Wrap(
          spacing: 7,
          runSpacing: 6,
          children: [
            for (var i = 0; i < 7; i++)
              FilterChip(
                label: Text(
                  const ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom'][i],
                ),
                selected: days.contains(i),
                onSelected: busy
                    ? null
                    : (selected) => changed(() {
                        selected ? days.add(i) : days.remove(i);
                      }),
              ),
          ],
        ),
        const SizedBox(height: 18),
        TextFormField(
          controller: signature,
          maxLength: 200,
          enabled: !busy,
          decoration: const InputDecoration(
            labelText: 'Tu firma',
            helperText: 'Para las plantillas de mensajes que usan {firma}.',
          ),
          onChanged: (_) => changed(() {}),
        ),
        if (error != null)
          Padding(
            padding: const EdgeInsets.only(top: 10),
            child: InlineNotice(text: error!, error: true),
          ),
        if (current != null) ...[
          const SizedBox(height: 10),
          const Text(
            'Tu edición se conserva. Revisa la versión actual antes de volver a guardar.',
          ),
          Align(
            alignment: Alignment.centerLeft,
            child: TextButton(
              onPressed: () async {
                if (!await _confirm(
                      context,
                      '¿Cargar las preferencias actuales?',
                      'El formulario se reemplazará por la versión guardada en Corte.',
                      'Cargar versión actual',
                    ) ||
                    !mounted) {
                  return;
                }
                setState(() => _load(current!));
              },
              child: const Text('Cargar versión actual'),
            ),
          ),
        ],
        const SizedBox(height: 12),
        Align(
          alignment: Alignment.centerLeft,
          child: FilledButton(
            onPressed: busy || !dirty || current != null ? null : save,
            child: Text(busy ? 'Guardando…' : 'Guardar preferencias'),
          ),
        ),
      ],
    ),
  );
}

class _PendingChanges extends StatefulWidget {
  const _PendingChanges({super.key});
  @override
  State<_PendingChanges> createState() => _PendingChangesState();
}

class _PendingChangesState extends State<_PendingChanges> {
  Future<List<JsonMap>>? future;
  bool busy = false;
  String? error;
  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    future ??= CorteScope.of(
      context,
    ).repo.opsPendientes(incluirConflictos: true);
  }

  void reload() => setState(
    () => future = CorteScope.of(
      context,
    ).repo.opsPendientes(incluirConflictos: true),
  );
  Future<void> send() async {
    final ui = CorteScope.of(context);
    setState(() {
      busy = true;
      error = null;
    });
    try {
      final result = await ui.repo.flushOps();
      if (!mounted) return;
      final applied = result.resultados
          .where((r) => r['estado'] == 'aplicada' || r['estado'] == 'duplicada')
          .length;
      final rejected = result.resultados
          .where((r) => r['estado'] == 'conflicto' || r['estado'] == 'invalida')
          .length;
      ui.refresh();
      toast(
        context,
        rejected > 0
            ? '$applied cambios confirmados; $rejected necesitan revisión.'
            : '$applied cambios confirmados.',
      );
      reload();
    } catch (failure) {
      if (mounted) setState(() => error = _errorText(failure));
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final ui = CorteScope.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          ui.repo.copiaPersistenteDisponible
              ? 'El guardado local está habilitado para esta cuenta.'
              : 'La copia sin conexión estará disponible cuando se verifique la cuenta y su espacio de datos.',
        ),
        const SizedBox(height: 10),
        if (error != null)
          Padding(
            padding: const EdgeInsets.only(bottom: 10),
            child: InlineNotice(text: error!, error: true),
          ),
        FutureBuilder<List<JsonMap>>(
          future: future,
          builder: (context, snapshot) {
            if (snapshot.hasError) {
              return InlineNotice(
                text: _errorText(snapshot.error!),
                error: true,
                action: TextButton(
                  onPressed: reload,
                  child: const Text('Reintentar'),
                ),
              );
            }
            if (!snapshot.hasData) return const LinearProgressIndicator();
            final entries = snapshot.data!;
            if (entries.isEmpty) {
              return Padding(
                padding: const EdgeInsets.symmetric(vertical: 12),
                child: Text(
                  'No hay cambios pendientes en este dispositivo.',
                  style: TextStyle(color: context.corte.muted),
                ),
              );
            }
            final pending = entries
                .where((e) => e['estado'] == 'pendiente')
                .length;
            return Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text(
                  '$pending pendientes · ${entries.length - pending} para revisar',
                  style: const TextStyle(fontWeight: FontWeight.w600),
                ),
                Align(
                  alignment: Alignment.centerLeft,
                  child: TextButton.icon(
                    onPressed: busy || pending == 0 ? null : send,
                    icon: const Icon(Icons.cloud_upload_outlined),
                    label: Text(busy ? 'Enviando…' : 'Enviar pendientes'),
                  ),
                ),
                for (final entry in entries.take(50))
                  _QueuedChange(
                    entry: entry,
                    disabled: busy,
                    onChanged: reload,
                  ),
                if (entries.length > 50)
                  Text(
                    '${entries.length - 50} cambios adicionales conservados en la cola.',
                  ),
              ],
            );
          },
        ),
      ],
    );
  }
}

class _QueuedChange extends StatefulWidget {
  const _QueuedChange({
    required this.entry,
    required this.disabled,
    required this.onChanged,
  });
  final JsonMap entry;
  final bool disabled;
  final VoidCallback onChanged;
  @override
  State<_QueuedChange> createState() => _QueuedChangeState();
}

class _QueuedChangeState extends State<_QueuedChange> {
  bool busy = false;
  String? error;
  Future<void> review() async {
    final ui = CorteScope.of(context);
    final op = mapOf(widget.entry['op']);
    final current = mapOf(mapOf(widget.entry['resultado'])['objeto']);
    final type = textOf(op['tipo']);
    if (current['rev'] is! int ||
        !(type.endsWith('.editar') || type.endsWith('.borrar'))) {
      toast(
        context,
        'Abre el registro original para revisar este cambio. La copia local se conserva.',
      );
      return;
    }
    final changes = mapOf(op['cambios'])..remove('rev');
    final accepted = await showDialog<bool>(
      context: context,
      builder: (dialog) => AlertDialog(
        title: const Text('Revisar cambio pendiente'),
        content: SizedBox(
          width: 480,
          child: SingleChildScrollView(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  '${_operationLabel(type)} · versión actual ${current['rev']}',
                ),
                const SizedBox(height: 14),
                if (type.endsWith('.borrar'))
                  const Text(
                    'Este registro cambió desde que intentaste eliminarlo. Volver a intentarlo eliminará su versión actual.',
                  ),
                for (final entry in changes.entries)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 12),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          _fieldLabel(entry.key),
                          style: const TextStyle(fontWeight: FontWeight.w700),
                        ),
                        Text(
                          'Actual: ${_fieldValue(current[entry.key])}',
                          style: TextStyle(color: context.corte.muted),
                        ),
                        SelectableText(
                          'Tu cambio: ${_fieldValue(entry.value)}',
                        ),
                      ],
                    ),
                  ),
              ],
            ),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialog).pop(false),
            child: const Text('Conservar sin enviar'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(dialog).pop(true),
            child: const Text('Volver a intentar este cambio'),
          ),
        ],
      ),
    );
    if (accepted != true || !mounted) return;
    setState(() {
      busy = true;
      error = null;
    });
    try {
      final replacement = <String, dynamic>{
        ...op,
        'op_id': nuevoId(),
        if (type.endsWith('.editar'))
          'cambios': {...changes, 'rev': current['rev']},
        if (type.endsWith('.borrar')) 'rev': current['rev'],
      };
      final result = await ui.repo.resolverOperacion(
        textOf(op['op_id']),
        replacement,
      );
      if (!mounted) return;
      ui.refresh();
      toast(
        context,
        result.enCola
            ? 'Cambio revisado y guardado en este equipo; pendiente de envío.'
            : 'Cambio revisado y confirmado en Corte.',
      );
    } catch (failure) {
      if (mounted) setState(() => error = _errorText(failure));
    } finally {
      if (mounted) {
        setState(() => busy = false);
        widget.onChanged();
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final op = mapOf(widget.entry['op']);
    final result = mapOf(widget.entry['resultado']);
    final failed = widget.entry['estado'] != 'pendiente';
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const Divider(),
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 12),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(
                failed ? Icons.error_outline_rounded : Icons.schedule_rounded,
                size: 20,
                color: failed ? context.corte.action : context.corte.muted,
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      _operationLabel(op['tipo']),
                      style: const TextStyle(fontWeight: FontWeight.w600),
                    ),
                    Text(
                      failed
                          ? textOf(
                              mapOf(result['error'])['mensaje'],
                              'Este cambio necesita revisión.',
                            )
                          : 'Guardado en este equipo; pendiente de envío.',
                      style: TextStyle(color: context.corte.muted),
                    ),
                    if (error != null)
                      Text(
                        error!,
                        style: TextStyle(color: context.corte.action),
                      ),
                  ],
                ),
              ),
              PopupMenuButton<String>(
                enabled: !widget.disabled && !busy,
                tooltip: 'Acciones del cambio',
                onSelected: (action) async {
                  if (action == 'revisar') {
                    await review();
                    return;
                  }
                  final ui = CorteScope.of(context);
                  if (!await _confirm(
                        context,
                        '¿Descartar este cambio local?',
                        'Se quitará sólo este cambio de la cola. Los datos ya guardados en Corte se conservarán.',
                        'Descartar cambio',
                      ) ||
                      !mounted) {
                    return;
                  }
                  setState(() {
                    busy = true;
                    error = null;
                  });
                  try {
                    await ui.repo.descartarOperacion(textOf(op['op_id']));
                    if (mounted) {
                      widget.onChanged();
                      ui.refresh();
                    }
                  } catch (failure) {
                    if (mounted) setState(() => error = _errorText(failure));
                  } finally {
                    if (mounted) setState(() => busy = false);
                  }
                },
                itemBuilder: (_) => [
                  if (failed)
                    const PopupMenuItem(
                      value: 'revisar',
                      child: Text('Revisar y volver a intentar'),
                    ),
                  const PopupMenuItem(
                    value: 'descartar',
                    child: Text('Descartar cambio local'),
                  ),
                ],
              ),
            ],
          ),
        ),
      ],
    );
  }
}

String _operationLabel(Object? type) =>
    const {
      'plan.crear': 'Crear plan',
      'plan.editar': 'Actualizar plan',
      'plan.borrar': 'Eliminar plan',
      'nota.crear': 'Crear nota',
      'nota.editar': 'Actualizar nota',
      'nota.borrar': 'Eliminar nota',
      'recordatorio.crear': 'Crear recordatorio',
      'recordatorio.editar': 'Actualizar recordatorio',
      'recordatorio.borrar': 'Eliminar recordatorio',
      'preferencias.editar': 'Actualizar preferencias',
      'aviso.crear': 'Crear aviso',
      'aviso.editar': 'Actualizar aviso',
      'plantilla.editar': 'Actualizar plantilla',
    }[type] ??
    'Cambio de organización';

String _fieldLabel(String field) =>
    const {
      'capacidad_videos_dia': 'Videos por día',
      'dias_videos': 'Días para tus videos',
      'firma': 'Firma',
      'tema': 'Apariencia',
      'titulo': 'Título',
      'texto': 'Texto',
      'estado': 'Estado',
      'fecha_plan': 'Fecha del plan',
      'fecha_video_listo': 'Fecha de video listo',
      'fecha_publicada': 'Fecha de publicación',
      'vence_at': 'Fecha del recordatorio',
      'pospuesto_hasta': 'Pospuesto hasta',
      'repetir': 'Repetición',
      'notas': 'Notas',
      'fijada': 'Fijada',
      'enlace_video': 'Enlace del video',
    }[field] ??
    field.replaceAll('_', ' ');
String _fieldValue(Object? value) => value == null
    ? 'Sin valor'
    : const {
        'claro': 'Claro',
        'oscuro': 'Oscuro',
        'sistema': 'Sistema',
      }.containsKey(value)
    ? const {'claro': 'Claro', 'oscuro': 'Oscuro', 'sistema': 'Sistema'}[value]!
    : value is bool
    ? (value ? 'Sí' : 'No')
    : value is List
    ? value.map(_fieldValue).join(', ')
    : textOf(value);

class NotesPage extends StatelessWidget {
  const NotesPage({super.key});
  @override
  Widget build(BuildContext context) => ApiData(
    path: '/api/notas',
    builder: (context, data) {
      final items = rowsOf(data['items']);
      return ListView(
        padding: const EdgeInsets.all(24),
        children: [
          PageTitle(
            'Notas',
            subtitle: 'Tus ideas y detalles, a mano.',
            action: FilledButton.icon(
              onPressed: () => showNoteEditor(context, 'general', null),
              icon: const Icon(Icons.add_rounded),
              label: const Text('Añadir nota'),
            ),
          ),
          if (items.isEmpty)
            const EmptyState(
              'Tu próxima idea empieza aquí',
              text:
                  'Guarda una nota general o añádela desde una muestra, tienda o producto.',
              icon: Icons.sticky_note_2_outlined,
            ),
          for (final note in items) ...[
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 17),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  if (note['fijada'] == true)
                    Padding(
                      padding: const EdgeInsets.only(right: 10, top: 3),
                      child: Icon(
                        Icons.push_pin_outlined,
                        size: 19,
                        color: context.corte.action,
                      ),
                    ),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        _EntityLink(value: note),
                        const SizedBox(height: 7),
                        SelectableText(textOf(note['texto'])),
                        if (note['actualizado_at'] != null)
                          Padding(
                            padding: const EdgeInsets.only(top: 8),
                            child: Text(
                              date(note['actualizado_at']),
                              style: TextStyle(
                                color: context.corte.muted,
                                fontSize: 12,
                              ),
                            ),
                          ),
                      ],
                    ),
                  ),
                  IconButton(
                    tooltip: 'Editar nota',
                    onPressed: () => showNoteEditor(
                      context,
                      textOf(note['entidad'], 'general'),
                      note['entidad_id'] as String?,
                      note: note,
                    ),
                    icon: const Icon(Icons.edit_outlined, size: 20),
                  ),
                  _DeleteLocalButton(
                    item: note,
                    type: 'nota.borrar',
                    label: 'nota',
                  ),
                ],
              ),
            ),
            const Divider(),
          ],
        ],
      );
    },
  );
}

class RemindersPage extends StatefulWidget {
  const RemindersPage({super.key});
  @override
  State<RemindersPage> createState() => _RemindersPageState();
}

class _RemindersPageState extends State<RemindersPage> {
  String filter = 'activos';
  @override
  Widget build(BuildContext context) => ApiData(
    path: '/api/recordatorios',
    builder: (context, data) {
      final items = rowsOf(data['items'])
          .where(
            (r) =>
                filter == 'todos' ||
                (filter == 'hechos'
                    ? r['estado'] == 'hecho'
                    : r['estado'] == 'activo'),
          )
          .toList();
      return ListView(
        padding: const EdgeInsets.all(24),
        children: [
          PageTitle(
            'Recordatorios',
            subtitle: 'Dale fecha a tus próximos pasos.',
            action: FilledButton.icon(
              onPressed: () => showReminderEditor(context, 'general', null),
              icon: const Icon(Icons.add_rounded),
              label: const Text('Añadir recordatorio'),
            ),
          ),
          Wrap(
            spacing: 8,
            children: [
              for (final entry in const {
                'activos': 'Activos',
                'hechos': 'Hechos',
                'todos': 'Todos',
              }.entries)
                ChoiceChip(
                  label: Text(entry.value),
                  selected: filter == entry.key,
                  onSelected: (_) => setState(() => filter = entry.key),
                ),
            ],
          ),
          const SizedBox(height: 16),
          if (items.isEmpty)
            const EmptyState(
              'No hay recordatorios en esta vista',
              text: 'Puedes añadir uno o consultar otro filtro.',
              icon: Icons.notifications_none_rounded,
            ),
          for (final reminder in items)
            _ReminderRow(
              key: ValueKey('${reminder['id']}:${reminder['rev']}'),
              item: reminder,
            ),
        ],
      );
    },
  );
}

class _ReminderRow extends StatefulWidget {
  const _ReminderRow({super.key, required this.item});
  final JsonMap item;
  @override
  State<_ReminderRow> createState() => _ReminderRowState();
}

class _ReminderRowState extends State<_ReminderRow> {
  bool busy = false;
  Future<void> changeState() async {
    if (busy || widget.item['rev'] is! int) return;
    final ui = CorteScope.of(context);
    setState(() => busy = true);
    try {
      final result = await ui.repo.guardarOps([
        {
          'op_id': nuevoId(),
          'tipo': 'recordatorio.editar',
          'id': widget.item['id'],
          'cambios': {
            'rev': widget.item['rev'],
            'estado': widget.item['estado'] == 'hecho' ? 'activo' : 'hecho',
          },
        },
      ]);
      if (mounted) {
        ui.refresh();
        toast(
          context,
          result.enCola
              ? 'Guardado en este equipo; pendiente de envío.'
              : 'Recordatorio actualizado.',
        );
      }
    } catch (error) {
      if (mounted) toast(context, _errorText(error));
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final item = widget.item;
    final done = item['estado'] == 'hecho';
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 12),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              IconButton(
                tooltip: done ? 'Volver a activar' : 'Marcar como hecho',
                onPressed: busy ? null : changeState,
                icon: Icon(
                  done
                      ? Icons.check_circle_rounded
                      : Icons.radio_button_unchecked_rounded,
                  color: done ? context.corte.cyanInk : context.corte.muted,
                ),
              ),
              Expanded(
                child: Padding(
                  padding: const EdgeInsets.only(top: 9),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        textOf(item['titulo']),
                        style: TextStyle(
                          fontWeight: FontWeight.w600,
                          decoration: done ? TextDecoration.lineThrough : null,
                        ),
                      ),
                      const SizedBox(height: 4),
                      Text(
                        date(
                          item['pospuesto_hasta'] ?? item['vence_at'],
                          time: true,
                        ),
                        style: TextStyle(color: context.corte.muted),
                      ),
                      _EntityLink(value: item),
                    ],
                  ),
                ),
              ),
              IconButton(
                tooltip: 'Editar recordatorio',
                onPressed: busy
                    ? null
                    : () => showReminderEditor(
                        context,
                        textOf(item['entidad'], 'general'),
                        item['entidad_id'] as String?,
                        reminder: item,
                      ),
                icon: const Icon(Icons.edit_outlined, size: 20),
              ),
              _DeleteLocalButton(
                item: item,
                type: 'recordatorio.borrar',
                label: 'recordatorio',
              ),
            ],
          ),
        ),
        const Divider(),
      ],
    );
  }
}

class _DeleteLocalButton extends StatefulWidget {
  const _DeleteLocalButton({
    required this.item,
    required this.type,
    required this.label,
  });
  final JsonMap item;
  final String type, label;
  @override
  State<_DeleteLocalButton> createState() => _DeleteLocalButtonState();
}

class _DeleteLocalButtonState extends State<_DeleteLocalButton> {
  bool busy = false;
  @override
  Widget build(BuildContext _) => IconButton(
    tooltip: 'Eliminar ${widget.label}',
    icon: const Icon(Icons.delete_outline_rounded, size: 20),
    onPressed: busy
        ? null
        : () async {
            final ui = CorteScope.of(context);
            if (!await _confirm(
                  context,
                  widget.label == 'nota'
                      ? '¿Eliminar esta nota?'
                      : '¿Eliminar este recordatorio?',
                  'Este cambio también se enviará a Corte.',
                  'Eliminar',
                ) ||
                !mounted) {
              return;
            }
            if (widget.item['rev'] is! int) {
              toast(context, 'Actualiza esta información antes de eliminarla.');
              return;
            }
            setState(() => busy = true);
            try {
              final result = await ui.repo.guardarOps([
                {
                  'op_id': nuevoId(),
                  'tipo': widget.type,
                  'id': widget.item['id'],
                  'rev': widget.item['rev'],
                },
              ]);
              if (mounted) {
                ui.refresh();
                toast(
                  context,
                  result.enCola
                      ? 'Guardado en este equipo; pendiente de envío.'
                      : 'Eliminado.',
                );
              }
            } catch (error) {
              if (mounted) toast(context, _errorText(error));
            } finally {
              if (mounted) setState(() => busy = false);
            }
          },
  );
}

class _EntityLink extends StatelessWidget {
  const _EntityLink({required this.value});
  final JsonMap value;
  @override
  Widget build(BuildContext context) {
    final entity = textOf(value['entidad']);
    final id = value['entidad_id'];
    final prefix = const {
      'muestra': '/muestras/m/',
      'tienda': '/tiendas/',
      'producto': '/productos/',
      'video': '/videos/',
      'orden': '/ordenes/',
    }[entity];
    final label = const {
      'muestra': 'Ver muestra',
      'tienda': 'Ver tienda',
      'producto': 'Ver producto',
      'video': 'Ver video',
      'orden': 'Ver orden',
      'plan': 'Ver plan',
    }[entity];
    if (prefix == null || id is! String || id.isEmpty) {
      return Text(
        'General',
        style: TextStyle(color: context.corte.muted, fontSize: 12),
      );
    }
    return TextButton(
      style: TextButton.styleFrom(
        padding: EdgeInsets.zero,
        alignment: Alignment.centerLeft,
        minimumSize: const Size(44, 36),
      ),
      onPressed: () =>
          CorteScope.of(context).go('$prefix${Uri.encodeComponent(id)}'),
      child: Text(label ?? 'Ver detalle'),
    );
  }
}

String _errorText(Object error) => error is ErrorApi
    ? error.mensaje
    : 'No pudimos completar el cambio. La información anterior se conserva.';
Future<bool> _confirm(
  BuildContext context,
  String title,
  String text,
  String action,
) async =>
    await showDialog<bool>(
      context: context,
      builder: (dialog) => AlertDialog(
        title: Text(title),
        content: Text(text),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialog).pop(false),
            child: const Text('Cancelar'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(dialog).pop(true),
            child: Text(action),
          ),
        ],
      ),
    ) ??
    false;
