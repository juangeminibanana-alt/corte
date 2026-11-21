import 'package:file_selector/file_selector.dart';
import 'package:flutter/material.dart';

import '../app.dart';
import '../data/shop_upload.dart';
import '../domain/domain.dart';
import 'catalog.dart' show openPublicLink;
import 'format.dart';
import 'theme.dart';
import 'widgets.dart';
import 'work.dart' show pagePadding, productName;

const shopPublisherRoute = '/videos/publicar';

class ShopPublishButton extends StatelessWidget {
  const ShopPublishButton({super.key, this.productId});
  final String? productId;

  @override
  Widget build(BuildContext context) => FilledButton.icon(
    onPressed: () => CorteScope.of(context).go(
      Uri(
        path: shopPublisherRoute,
        queryParameters: productId == null ? null : {'producto': productId!},
      ).toString(),
    ),
    icon: const Icon(Icons.video_call_outlined),
    label: Text(
      productId == null ? 'Publicar video' : 'Publicar con esta prenda',
    ),
  );
}

String _message(Object error) => error is ErrorApi
    ? error.mensaje
    : 'No se pudo completar la operación. Revisa tu conexión.';

class ShopPublisherPage extends StatefulWidget {
  const ShopPublisherPage({super.key, this.initialProduct, this.pickVideo});
  final String? initialProduct;
  final Future<XFile?> Function()? pickVideo;
  @override
  State<ShopPublisherPage> createState() => _ShopPublisherPageState();
}

class _ShopPublisherPageState extends State<ShopPublisherPage> {
  final _caption = TextEditingController(), _anchor = TextEditingController();
  late Future<JsonMap> _capabilities;
  JsonMap? _product;
  XFile? _video;
  String? _uploaded, _messageText, _phase, _acceptedId;
  double _progress = 0;
  bool _scheduled = false, _ai = false, _started = false, _composeNew = true;
  DateTime? _when;
  int _refresh = 0;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_started) return;
    _started = true;
    _capabilities = CorteScope.of(context).repo.get('$shopBase/capacidades');
    final id = widget.initialProduct;
    if (id != null && RegExp(r'^[0-9]{1,25}$').hasMatch(id)) _loadProduct(id);
  }

  void _checkPermissions() {
    final pending = CorteScope.of(context).repo.get('$shopBase/capacidades');
    setState(() {
      _capabilities = pending;
    });
  }

  Future<void> _loadProduct(String id) async {
    try {
      final data = await CorteScope.of(context).repo.get('/api/productos/$id');
      final p = [
        data['ficha'],
        data['fila'],
        ...rowsOf(data['muestras']).map((m) => m['producto']),
      ].whereType<Map>().where((x) => x.isNotEmpty).firstOrNull;
      if (mounted && p != null && _product == null) {
        _useProduct({...mapOf(data['fila']), ...mapOf(p), 'product_id': id});
      }
    } catch (_) {
      if (mounted) {
        setState(
          () => _messageText =
              'No pudimos cargar esta prenda. Puedes elegirla en el catálogo.',
        );
      }
    }
  }

  void _useProduct(JsonMap p) {
    final suggested = productName(p)
        .replaceAll(RegExp(r'[^\p{L}\p{N} ]', unicode: true), '')
        .replaceAll(RegExp(r'\s+'), ' ')
        .trim();
    setState(() {
      _product = p;
      _anchor.text = String.fromCharCodes(suggested.runes.take(29)).trimRight();
      _messageText = null;
    });
  }

  Future<void> _chooseProduct() async {
    final ui = CorteScope.of(context);
    final data = ui.repo.get(
      '/api/analitica/productos',
      query: const {'limite': 1000},
    );
    final chosen = await showDialog<JsonMap>(
      context: context,
      builder: (_) => CorteScope(controller: ui, child: _ProductPicker(data)),
    );
    if (mounted && chosen != null) _useProduct(chosen);
  }

  Future<void> _chooseVideo() async {
    try {
      final file = widget.pickVideo == null
          ? await openFile(
              acceptedTypeGroups: const [
                XTypeGroup(
                  label: 'Videos',
                  extensions: videoExtensions,
                  mimeTypes: ['video/*'],
                ),
              ],
            )
          : await widget.pickVideo!();
      if (file == null) return;
      final error = validateShopFile(file.name, await file.length());
      if (!mounted) return;
      setState(() {
        _messageText = error;
        if (error == null) {
          _video = file;
          _uploaded = null;
        }
      });
    } catch (_) {
      if (mounted) {
        setState(() => _messageText = 'No pudimos abrir el archivo de video.');
      }
    }
  }

  Future<void> _chooseDate() async {
    final now = DateTime.now();
    final first = DateUtils.dateOnly(now);
    final chosen = await showDatePicker(
      context: context,
      firstDate: first,
      lastDate: DateTime(now.year + 10),
      initialDate: _when?.isAfter(first) == true ? _when! : now,
    );
    if (!mounted || chosen == null) return;
    final time = await showTimePicker(
      context: context,
      initialTime: TimeOfDay.fromDateTime(
        _when ?? now.add(const Duration(hours: 1)),
      ),
    );
    if (time == null || !mounted) return;
    setState(
      () => _when = DateTime(
        chosen.year,
        chosen.month,
        chosen.day,
        time.hour,
        time.minute,
      ),
    );
  }

  String? _validate() {
    if (_product == null) return 'Elige la prenda que vas a enlazar.';
    if (_video == null) return 'Elige el archivo de video.';
    if (_caption.text.length > 4000) {
      return 'La descripción supera el límite de TikTok de 4000 caracteres.';
    }
    final anchor = _anchor.text.trim();
    if (anchor.isEmpty ||
        anchor.runes.length >= 30 ||
        !RegExp(r'^[\p{L}\p{N} ]+$', unicode: true).hasMatch(anchor)) {
      return 'Escribe una etiqueta de 1 a 29 letras, números o espacios para el enlace.';
    }
    if (_scheduled && (_when == null || !_when!.isAfter(DateTime.now()))) {
      return 'Elige una fecha y hora futura.';
    }
    return null;
  }

  String _localTime(DateTime value) {
    final local = MaterialLocalizations.of(context);
    return '${local.formatMediumDate(value)} · ${TimeOfDay.fromDateTime(value).format(context)}';
  }

  Future<void> _submit() async {
    if (_phase != null) return;
    final error = _validate();
    if (error != null) {
      setState(() => _messageText = error);
      return;
    }
    final ui = CorteScope.of(context), file = _video!, product = _product!;
    final scope = ui.repo.cacheScope;
    void check() {
      if (!mounted || scope == null || ui.repo.cacheScope != scope) {
        throw ErrorApi(
          codigo: 'sesion_cambiada',
          mensaje: 'Cambió la cuenta activa. Abre el formulario de nuevo.',
        );
      }
    }

    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: Text(
          _scheduled ? '¿Programar este video?' : '¿Publicar este video ahora?',
        ),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(file.name, style: Theme.of(context).textTheme.titleMedium),
              const SizedBox(height: 8),
              Text(productName(product)),
              Text('Enlace · ${_anchor.text.trim()}'),
              if (_caption.text.isNotEmpty) ...[
                const SizedBox(height: 12),
                Text(_caption.text),
              ],
              const SizedBox(height: 12),
              Text(
                _scheduled
                    ? 'CUTGC lo enviará a TikTok Shop el ${_localTime(_when!)} (hora de este dispositivo), incluso si cierras la app.'
                    : 'CUTGC enviará el video a tu cuenta de TikTok Shop con el enlace a esta prenda.',
              ),
              if (_ai) const Text('Marcado como contenido generado con IA.'),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('Volver a editar'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            child: Text(
              _scheduled ? 'Confirmar programación' : 'Confirmar publicación',
            ),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    setState(() {
      _phase = 'Subiendo video';
      _progress = 0;
      _messageText = null;
    });
    var submitting = false;
    try {
      check();
      _uploaded ??= await uploadShopVideo(
        ui.repo,
        file,
        checkAccount: check,
        onProgress: (progress) {
          if (mounted) setState(() => _progress = progress);
        },
      );
      check();
      if (_scheduled && !_when!.isAfter(DateTime.now())) {
        throw ErrorApi(
          codigo: 'fecha_pasada',
          mensaje:
              'La hora elegida ya pasó. Elige otra hora para el video cargado.',
        );
      }
      setState(
        () => _phase = _scheduled
            ? 'Guardando en la agenda'
            : 'Enviando a TikTok Shop',
      );
      submitting = true;
      final result = await ui.repo.post(
        '$shopBase/${_scheduled ? 'agenda' : 'publicar'}',
        body: {
          'file_id': _uploaded,
          'titulo': _caption.text,
          'product_id': product['product_id'],
          'titulo_ancla': _anchor.text.trim(),
          'is_ai_generated': _ai,
          'confirmar': true,
          if (_scheduled)
            'programada_at': _when!.millisecondsSinceEpoch ~/ 1000,
        },
      );
      check();
      if (_scheduled
          ? result['estado'] != 'programada'
          : result['video_id'] is! String) {
        throw ErrorApi(
          codigo: 'respuesta_invalida',
          mensaje:
              'Comprueba el resultado en la agenda o en TikTok antes de repetir el envío.',
        );
      }
      setState(() {
        _acceptedId = _scheduled ? null : result['video_id'] as String;
        _messageText = _scheduled
            ? 'El video quedó programado.'
            : 'TikTok Shop aceptó el envío. Puedes consultar cuándo queda publicado.';
        _composeNew = false;
        _refresh++;
      });
    } catch (e) {
      if (mounted) {
        final uncertain =
            submitting &&
            (e is! ErrorApi ||
                e.esTransitorio ||
                e.codigo == 'conflicto' ||
                e.codigo == 'respuesta_invalida');
        setState(() {
          _messageText = uncertain
              ? 'Comprueba la agenda y los videos de tu cuenta de TikTok antes de repetir el envío. ${_message(e)}'
              : _message(e);
          _refresh++;
        });
      }
    } finally {
      if (mounted) setState(() => _phase = null);
    }
  }

  void _newVideo() {
    setState(() {
      _video = null;
      _uploaded = null;
      _acceptedId = null;
      _messageText = null;
      _product = null;
      _caption.clear();
      _anchor.clear();
      _scheduled = false;
      _when = null;
      _ai = false;
      _composeNew = true;
    });
  }

  @override
  void dispose() {
    _caption.dispose();
    _anchor.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final ui = CorteScope.of(context);
    return Align(
      alignment: Alignment.topLeft,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 940),
        child: ListView(
          padding: pagePadding(context),
          children: [
            PageTitle(
              'Publicar video',
              back: () {
                if (!ui.back()) ui.go('/videos');
              },
            ),
            const SizedBox(height: 20),
            FutureBuilder<JsonMap>(
              future: _capabilities,
              builder: (context, snapshot) {
                if (snapshot.hasError) {
                  return Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      InlineNotice(text: _message(snapshot.error!)),
                      TextButton(
                        onPressed: _checkPermissions,
                        child: const Text('Volver a comprobar'),
                      ),
                    ],
                  );
                }
                if (!snapshot.hasData) {
                  return const LinearProgressIndicator(
                    semanticsLabel: 'Consultando permisos',
                  );
                }
                final capabilities = snapshot.data!;
                final canPublish =
                    capabilities['scope_concedido'] == true &&
                    ui.repo.cacheScope != null;
                final connectionNotice = Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    InlineNotice(
                      text: capabilities['cuenta_creator_conectada'] == true
                          ? 'Puedes preparar el video aquí. Para enviarlo, TikTok Shop debe autorizar la publicación en esta cuenta.'
                          : 'Conecta una cuenta de creador de TikTok Shop para publicar videos.',
                    ),
                    Wrap(
                      children: [
                        TextButton(
                          onPressed: () => ui.go('/ajustes/tiktok'),
                          child: const Text('Abrir conexión de TikTok Shop'),
                        ),
                        TextButton(
                          onPressed: _checkPermissions,
                          child: const Text('Comprobar permiso'),
                        ),
                      ],
                    ),
                  ],
                );
                if (!_composeNew) {
                  return Align(
                    alignment: Alignment.centerLeft,
                    child: OutlinedButton.icon(
                      onPressed: _newVideo,
                      icon: const Icon(Icons.add),
                      label: const Text('Preparar otro video'),
                    ),
                  );
                }
                return AbsorbPointer(
                  absorbing: _phase != null,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      if (!canPublish) connectionNotice,
                      Text(
                        'Video y prenda',
                        style: Theme.of(context).textTheme.titleLarge,
                      ),
                      const SizedBox(height: 12),
                      Wrap(
                        spacing: 12,
                        runSpacing: 8,
                        children: [
                          OutlinedButton.icon(
                            onPressed: _phase == null ? _chooseProduct : null,
                            icon: const Icon(Icons.checkroom_outlined),
                            label: Text(
                              _product == null
                                  ? 'Elegir prenda'
                                  : 'Cambiar prenda',
                            ),
                          ),
                          OutlinedButton.icon(
                            onPressed: _phase == null ? _chooseVideo : null,
                            icon: const Icon(Icons.video_file_outlined),
                            label: Text(
                              _video == null ? 'Elegir video' : 'Cambiar video',
                            ),
                          ),
                        ],
                      ),
                      if (_product != null)
                        Padding(
                          padding: const EdgeInsets.symmetric(
                            vertical: CorteSpace.small,
                          ),
                          child: Row(
                            children: [
                              if (textOf(_product!['imagen']).isNotEmpty) ...[
                                CortePhoto(
                                  textOf(_product!['imagen']),
                                  width: 50,
                                  height: 58,
                                ),
                                const SizedBox(width: CorteSpace.medium),
                              ],
                              Expanded(
                                child: Text(
                                  productName(_product!),
                                  style: Theme.of(
                                    context,
                                  ).textTheme.titleMedium,
                                ),
                              ),
                            ],
                          ),
                        ),
                      if (_video != null)
                        Text(_video!.name)
                      else
                        Text(
                          'Hasta 500 MiB. Desde 10 MiB usa MP4, MOV o WebM.',
                          style: TextStyle(color: context.corte.muted),
                        ),
                      const SizedBox(height: 16),
                      TextField(
                        enabled: _phase == null,
                        controller: _caption,
                        minLines: 2,
                        maxLines: 5,
                        decoration: const InputDecoration(
                          labelText: 'Descripción del video',
                        ),
                      ),
                      const SizedBox(height: 12),
                      TextField(
                        enabled: _phase == null,
                        controller: _anchor,
                        maxLength: 29,
                        decoration: const InputDecoration(
                          labelText: 'Texto del enlace a la prenda',
                        ),
                      ),
                      CheckboxListTile(
                        contentPadding: EdgeInsets.zero,
                        controlAffinity: ListTileControlAffinity.leading,
                        title: const Text(
                          'Este video incluye contenido generado con IA',
                        ),
                        value: _ai,
                        onChanged: _phase == null
                            ? (v) => setState(() => _ai = v == true)
                            : null,
                      ),
                      const SizedBox(height: 12),
                      Text(
                        'Cuándo publicar',
                        style: Theme.of(context).textTheme.titleMedium,
                      ),
                      Wrap(
                        spacing: 8,
                        runSpacing: 8,
                        children: [
                          ChoiceChip(
                            label: const Text('Ahora'),
                            selected: !_scheduled,
                            onSelected: _phase == null
                                ? (_) => setState(() => _scheduled = false)
                                : null,
                          ),
                          ChoiceChip(
                            label: const Text('Programar'),
                            selected: _scheduled,
                            onSelected: _phase == null
                                ? (_) => setState(() => _scheduled = true)
                                : null,
                          ),
                        ],
                      ),
                      if (_scheduled)
                        TextButton.icon(
                          onPressed: _phase == null ? _chooseDate : null,
                          icon: const Icon(Icons.calendar_month_outlined),
                          label: Text(
                            _when == null
                                ? 'Elegir fecha y hora local'
                                : _localTime(_when!),
                          ),
                        ),
                      const SizedBox(height: 16),
                      FilledButton.icon(
                        onPressed: _phase == null && canPublish
                            ? _submit
                            : null,
                        icon: const Icon(Icons.send_outlined),
                        label: Text(
                          _scheduled
                              ? 'Revisar programación'
                              : 'Revisar publicación',
                        ),
                      ),
                    ],
                  ),
                );
              },
            ),
            if (_phase != null) ...[
              const SizedBox(height: 12),
              Semantics(liveRegion: true, child: Text(_phase!)),
              LinearProgressIndicator(
                value: _progress > 0 && _progress < 1 ? _progress : null,
              ),
            ],
            if (_messageText != null) ...[
              const SizedBox(height: 12),
              Semantics(
                liveRegion: true,
                child: InlineNotice(text: _messageText!),
              ),
            ],
            if (_acceptedId != null) _VideoStatus(id: _acceptedId!),
            const SizedBox(height: 28),
            _ShopAgenda(key: ValueKey(_refresh)),
          ],
        ),
      ),
    );
  }
}

class _ProductPicker extends StatefulWidget {
  const _ProductPicker(this.data);
  final Future<JsonMap> data;
  @override
  State<_ProductPicker> createState() => _ProductPickerState();
}

class _ProductPickerState extends State<_ProductPicker> {
  String query = '';
  @override
  Widget build(BuildContext context) => AlertDialog(
    title: const Text('Elegir prenda'),
    content: SizedBox(
      width: 440,
      height: 360,
      child: Column(
        children: [
          TextField(
            autofocus: true,
            decoration: const InputDecoration(
              labelText: 'Buscar una prenda',
              prefixIcon: Icon(Icons.search),
            ),
            onChanged: (value) =>
                setState(() => query = value.trim().toLowerCase()),
          ),
          const SizedBox(height: 8),
          Expanded(
            child: FutureBuilder<JsonMap>(
              future: widget.data,
              builder: (context, snapshot) {
                if (snapshot.hasError) {
                  return InlineNotice(text: _message(snapshot.error!));
                }
                if (!snapshot.hasData) {
                  return const Center(child: CircularProgressIndicator());
                }
                final products = rowsOf(snapshot.data!['items'])
                    .where(
                      (p) =>
                          RegExp(
                            r'^[0-9]{1,25}$',
                          ).hasMatch(textOf(p['product_id'])) &&
                          '${productName(p)} ${textOf(p['tienda_nombre'])}'
                              .toLowerCase()
                              .contains(query),
                    )
                    .toList();
                if (products.isEmpty) {
                  return const Center(
                    child: Text(
                      'No encontramos prendas en tu catálogo para esta búsqueda.',
                    ),
                  );
                }
                return ListView.builder(
                  itemCount: products.length,
                  itemBuilder: (context, i) {
                    final p = products[i];
                    return ListTile(
                      contentPadding: EdgeInsets.zero,
                      leading: CortePhoto(
                        p['imagen'] is String ? p['imagen'] as String : null,
                        width: 42,
                        height: 48,
                      ),
                      title: Text(
                        productName(p),
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                      ),
                      subtitle: Text(
                        textOf(p['tienda_nombre'], textOf(p['product_id'])),
                      ),
                      onTap: () => Navigator.pop(context, p),
                    );
                  },
                );
              },
            ),
          ),
        ],
      ),
    ),
    actions: [
      TextButton(
        onPressed: () => Navigator.pop(context),
        child: const Text('Cerrar'),
      ),
    ],
  );
}

const _agendaStates = {
  'programada': 'Programada',
  'enviando': 'Enviando a TikTok',
  'aceptada': 'Aceptada por TikTok',
  'cancelada': 'Cancelada',
  'fallida': 'Fallida',
  'por_verificar': 'Revisar en TikTok',
};

class _ShopAgenda extends StatefulWidget {
  const _ShopAgenda({super.key});
  @override
  State<_ShopAgenda> createState() => _ShopAgendaState();
}

class _ShopAgendaState extends State<_ShopAgenda> {
  Future<JsonMap>? _data;
  final _busy = <String>{};
  String? _error;
  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (CorteScope.of(context).repo.cacheScope != null) {
      _data ??= CorteScope.of(context).repo.get('$shopBase/agenda');
    }
  }

  void _reload() {
    final pending = CorteScope.of(context).repo.get('$shopBase/agenda');
    setState(() {
      _data = pending;
    });
  }

  Future<void> _cancel(JsonMap item) async {
    final id = textOf(item['id']);
    final repo = CorteScope.of(context).repo, scope = repo.cacheScope;
    final yes = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('¿Cancelar la programación?'),
        content: Text(
          'Se cancelará el envío programado de «${textOf(item['titulo_ancla'])}».',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Conservar'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Cancelar programación'),
          ),
        ],
      ),
    );
    if (yes != true || !mounted || scope == null || repo.cacheScope != scope) {
      return;
    }
    setState(() {
      _busy.add(id);
      _error = null;
    });
    try {
      await repo.post(
        '$shopBase/agenda/${Uri.encodeComponent(id)}/cancelar',
        body: {},
      );
    } catch (e) {
      if (mounted) setState(() => _error = _message(e));
    } finally {
      if (mounted) {
        _busy.remove(id);
        _reload();
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    if (CorteScope.of(context).repo.cacheScope == null) {
      return const SizedBox.shrink();
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Wrap(
          alignment: WrapAlignment.spaceBetween,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            Text(
              'Agenda de publicación',
              style: Theme.of(context).textTheme.titleLarge,
            ),
            TextButton.icon(
              onPressed: _reload,
              icon: const Icon(Icons.refresh_rounded),
              label: const Text('Actualizar agenda'),
            ),
          ],
        ),
        if (_error != null) InlineNotice(text: _error!),
        FutureBuilder<JsonMap>(
          future: _data,
          builder: (context, snapshot) {
            if (snapshot.hasError) {
              return InlineNotice(text: _message(snapshot.error!));
            }
            if (!snapshot.hasData) {
              return const LinearProgressIndicator(
                semanticsLabel: 'Cargando agenda',
              );
            }
            final items = rowsOf(snapshot.data!['items']);
            if (items.isEmpty) {
              return Text(
                'Tus videos programados aparecerán aquí.',
                style: TextStyle(color: context.corte.muted),
              );
            }
            return Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                for (final item in items)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 8),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Divider(),
                        Text(
                          textOf(item['titulo_ancla'], 'Video de TikTok Shop'),
                          style: Theme.of(context).textTheme.titleMedium,
                        ),
                        Text(
                          '${date(item['programada_at'], time: true)} · ${_agendaStates[item['estado']] ?? 'Estado desconocido'}',
                        ),
                        if (textOf(item['titulo']).isNotEmpty)
                          Text(
                            textOf(item['titulo']),
                            maxLines: 2,
                            overflow: TextOverflow.ellipsis,
                          ),
                        if (textOf(item['mensaje']).isNotEmpty)
                          Text(textOf(item['mensaje'])),
                        if (item['estado'] == 'programada')
                          TextButton.icon(
                            onPressed: _busy.contains(item['id'])
                                ? null
                                : () => _cancel(item),
                            icon: const Icon(Icons.event_busy_outlined),
                            label: const Text('Cancelar programación'),
                          ),
                        if (item['estado'] == 'aceptada' &&
                            item['video_id'] is String)
                          _VideoStatus(
                            key: ValueKey(item['video_id']),
                            id: item['video_id'] as String,
                          ),
                      ],
                    ),
                  ),
              ],
            );
          },
        ),
      ],
    );
  }
}

class _VideoStatus extends StatefulWidget {
  const _VideoStatus({super.key, required this.id});
  final String id;
  @override
  State<_VideoStatus> createState() => _VideoStatusState();
}

class _VideoStatusState extends State<_VideoStatus> {
  String? _label;
  bool _busy = false, _published = false;
  Future<void> _check() async {
    setState(() => _busy = true);
    try {
      final data = await CorteScope.of(
        context,
      ).repo.get('$shopBase/${Uri.encodeComponent(widget.id)}/estado');
      if (mounted) {
        setState(() {
          _published = data['estado'] == 'publicada';
          _label = switch (data['estado']) {
            'procesando' => 'TikTok está procesando el video.',
            'publicada' => 'El video está publicado.',
            'fallida' => 'TikTok no pudo publicar el video.',
            _ => 'Aún no se confirmó el estado del video.',
          };
        });
      }
    } catch (e) {
      if (mounted) setState(() => _label = _message(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      if (_label != null) Semantics(liveRegion: true, child: Text(_label!)),
      if (_published)
        TextButton(
          onPressed: () => CorteScope.of(
            context,
          ).go('/videos/${Uri.encodeComponent(widget.id)}?desde=todos'),
          child: const Text('Ver ficha del video'),
        ),
      TextButton.icon(
        onPressed: _busy ? null : _check,
        icon: const Icon(Icons.sync),
        label: Text(_busy ? 'Consultando…' : 'Consultar estado en TikTok'),
      ),
    ],
  );
}

class PublishedVideoActions extends StatelessWidget {
  const PublishedVideoActions({super.key, required this.link});
  final String link;
  @override
  Widget build(BuildContext context) {
    final uri = Uri.tryParse(link);
    final available =
        uri != null &&
        uri.scheme == 'https' &&
        uri.userInfo.isEmpty &&
        (!uri.hasPort || uri.port == 443) &&
        (uri.host == 'tiktok.com' || uri.host.endsWith('.tiktok.com'));
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: [
        FilledButton.icon(
          onPressed: available ? () => openPublicLink(context, link) : null,
          icon: const Icon(Icons.play_arrow_rounded),
          label: const Text('Ver video en TikTok'),
        ),
        if (available)
          OutlinedButton.icon(
            onPressed: () async {
              final go = await showDialog<bool>(
                context: context,
                builder: (ctx) => AlertDialog(
                  title: const Text('Eliminar desde TikTok'),
                  content: const Text(
                    'Abre el video con tu cuenta de creador. En TikTok, abre las opciones del video y selecciona Eliminar.',
                  ),
                  actions: [
                    TextButton(
                      onPressed: () => Navigator.pop(ctx, false),
                      child: const Text('Cerrar'),
                    ),
                    FilledButton(
                      onPressed: () => Navigator.pop(ctx, true),
                      child: const Text('Abrir video en TikTok'),
                    ),
                  ],
                ),
              );
              if (go == true && context.mounted) {
                await openPublicLink(context, link);
              }
            },
            icon: const Icon(Icons.open_in_new_rounded),
            label: const Text('Eliminar desde TikTok'),
          ),
        TextButton.icon(
          icon: const Icon(Icons.visibility_outlined),
          label: const Text('Privacidad del video'),
          onPressed: () => showDialog<void>(
            context: context,
            builder: (ctx) => AlertDialog(
              title: const Text('Quién puede ver tu video'),
              content: const SingleChildScrollView(
                child: Text(
                  'Si promocionas productos de vendedores en TikTok Shop México, '
                  'el video debe estar disponible para todos.\n\n'
                  'Para otros videos, puedes elegir la audiencia en los ajustes '
                  'de privacidad de la publicación en TikTok.',
                ),
              ),
              actions: [
                TextButton(
                  onPressed: () => openPublicLink(
                    ctx,
                    'https://seller-mx.tiktok.com/university/essay?knowledge_id=7219665592977153&lang=es-419',
                  ),
                  child: const Text('Términos de TikTok Shop'),
                ),
                if (available)
                  TextButton(
                    onPressed: () {
                      Navigator.pop(ctx);
                      openPublicLink(context, link);
                    },
                    child: const Text('Abrir video en TikTok'),
                  ),
                FilledButton(
                  onPressed: () => Navigator.pop(ctx),
                  child: const Text('Cerrar'),
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}
