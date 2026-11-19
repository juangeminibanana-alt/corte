import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'auth/auth_controller.dart';
import 'data/corte_repository.dart';
import 'platform/data_store.dart';
import 'platform/notifications.dart';
import 'platform/sales_notifications.dart';
import 'platform/theme_chrome.dart';
import 'ui/theme.dart';
import 'ui/theme_preferences.dart';
import 'ui/shell.dart';
import 'ui/widgets.dart';
import 'ui/desktop.dart';

class CorteApplication extends StatefulWidget {
  const CorteApplication({super.key});
  @override
  State<CorteApplication> createState() => _CorteApplicationState();
}

class _CorteApplicationState extends State<CorteApplication>
    with WidgetsBindingObserver {
  late final CorteAuthController _auth;
  late final CorteUiController _ui;
  late final CorteRouter _router;
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _auth = CorteAuthController();
    _ui = CorteUiController(auth: _auth);
    _router = CorteRouter(_ui);
    unawaited(_auth.initialize());
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      unawaited(_auth.resume());
      unawaited(_ui.resume());
    } else if (state == AppLifecycleState.paused ||
        state == AppLifecycleState.hidden ||
        state == AppLifecycleState.detached) {
      _auth.pause();
      _ui.pause();
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _router.dispose();
    _ui.dispose();
    _auth.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
    animation: Listenable.merge([_ui.appearance, _ui.textSize]),
    builder: (context, _) => MaterialApp.router(
      title: 'CUTGC',
      debugShowCheckedModeBanner: false,
      theme: corteTheme(),
      darkTheme: corteTheme(brightness: Brightness.dark),
      themeMode: _ui.appearance.mode,
      builder: (context, child) {
        Widget content = ThemeChromeSync(
          child: child ?? const SizedBox.shrink(),
        );
        if (_ui.textSize.available && !_ui.textSize.useSystem) {
          content = MediaQuery.withNoTextScaling(child: content);
        }
        return useDesktopWorkspace(context)
            ? Theme(
                data: desktopWorkspaceTheme(Theme.of(context)),
                child: content,
              )
            : content;
      },
      routerDelegate: _router,
      routeInformationParser: const CorteRouteParser(),
      locale: const Locale('es', 'MX'),
      supportedLocales: const [Locale('es', 'MX'), Locale('es'), Locale('en')],
      localizationsDelegates: GlobalMaterialLocalizations.delegates,
    ),
  );
}

class CorteUiController extends ChangeNotifier {
  CorteUiController({
    required this.auth,
    Future<CorteDataStore> Function() openStore = createCorteDataStore,
  }) : salesNotifications = CorteSalesNotifications(runtime: auth.runtime) {
    repo = CorteRepository(adapter: auth.transport);
    appearance = CorteThemePreferences(repo)..addListener(notifyListeners);
    textSize = CorteTextSizePreference(
      available: auth.runtime.platform == 'windows',
    );
    auth.addListener(_authChanged);
    unawaited(
      openStore()
          .then((store) {
            if (!_closed) {
              repo.attachStore(store);
              unawaited(textSize.load(store));
              repo.invalidar();
              unawaited(appearance.load(force: true));
              revision++;
              notifyListeners();
              unawaited(_maintain());
            }
          })
          .catchError((Object _) {
            if (_closed) return;
            storageAvailable = false;
            notifyListeners();
          }),
    );
    unawaited(
      notifications.initialize(
        onOpen: (value) {
          _openNotification(value);
        },
      ),
    );
    unawaited(salesNotifications.initialize(onOpen: _openNotification));
    _revisionTimer = Timer.periodic(const Duration(seconds: 25), (_) {
      unawaited(_maintain());
    });
  }
  final CorteAuthController auth;
  final notifications = CorteNotifications();
  final CorteSalesNotifications salesNotifications;
  static const _androidStartupDelay = Duration(seconds: 6);
  Timer? _revisionTimer, _refreshTimer, _startupTimer;
  bool _androidStartupPending = false;
  bool _maintaining = false;
  bool _foreground = true, _warmingImages = false;
  bool _dataDirty = true;
  String? _snapshotDay;
  DateTime? _lastImageWarm;
  String? _warmedRevision;
  String? _remoteRevision;
  late final CorteRepository repo;
  late final CorteThemePreferences appearance;
  late final CorteTextSizePreference textSize;
  String location = '/inicio';
  final _history = <String>[];
  bool _receivedRoute = false;
  int revision = 0;
  bool storageAvailable = true;
  bool _closed = false;
  String? _scope;
  int _scopeEpoch = 0;
  void _authChanged() {
    final value = auth.state.authenticated
        ? '${auth.state.ownerScope}:${auth.state.cacheScope}'
        : null;
    if (_scope != value) {
      _scope = value;
      _scopeEpoch++;
      _startupTimer?.cancel();
      _startupTimer = null;
      _androidStartupPending =
          auth.runtime.platform == 'android' && value != null;
      repo.setScopes(
        ownerScope: auth.state.authenticated ? auth.state.ownerScope : null,
        cacheScope: auth.state.authenticated ? auth.state.cacheScope : null,
      );
      appearance.resetForScope();
      unawaited(appearance.load());
      revision++;
      _remoteRevision = null;
      _warmedRevision = null;
    }
    _bindSalesNotifications();
    notifyListeners();
    unawaited(_maintain());
  }

  void _bindSalesNotifications() => salesNotifications.bind(
    repo,
    authenticated: auth.state.authenticated,
    refreshAutomatically: !_androidStartupPending,
  );

  void go(String value) {
    if (!value.startsWith('/') || value.startsWith('//')) return;
    if (value == location) return;
    _history.add(location);
    location = value;
    notifyListeners();
  }

  void replace(String value) {
    location = value;
    notifyListeners();
  }

  void restoreRoute(String value) {
    if (!value.startsWith('/') || value.startsWith('//')) value = '/inicio';
    if (_receivedRoute && value != location) {
      final previous = _history.lastIndexOf(value);
      if (previous >= 0)
        _history.removeRange(previous, _history.length);
      else
        _history.add(location);
    }
    _receivedRoute = true;
    replace(value);
  }

  bool back() {
    if (_history.isEmpty) return false;
    location = _history.removeLast();
    notifyListeners();
    return true;
  }

  void refresh() {
    _dataDirty = true;
    repo.invalidar();
    revision++;
    notifyListeners();
    _refreshTimer?.cancel();
    _refreshTimer = Timer(const Duration(milliseconds: 400), () {
      unawaited(_maintain());
    });
  }

  Future<void> resume() async {
    _foreground = true;
    _dataDirty = true;
    final route = await notifications.readLaunchRoute();
    if (route != null && !_closed) _openNotification(route);
    unawaited(salesNotifications.refresh());
    await _maintain();
  }

  void pause() {
    _foreground = false;
    _startupTimer?.cancel();
    _startupTimer = null;
  }

  void _openNotification(String value) {
    var route = value.replaceFirst(RegExp(r'^#'), '');
    final uri = Uri.tryParse(route);
    if (uri == null) return;
    final parts = uri.pathSegments;
    // Previous native releases used /muestras/<id> for detail links.
    if (parts.length == 2 && parts.first == 'muestras') {
      if (parts[1] == 'sesion')
        route = '/muestras/plan';
      else if (!{'agenda', 'todas', 'plan'}.contains(parts[1]))
        route = '/muestras/m/${Uri.encodeComponent(parts[1])}';
    }
    go(route);
  }

  Future<void> _maintain() async {
    if (_closed || !_foreground || !auth.state.authenticated) return;
    if (_androidStartupPending) {
      // Keep the first authenticated frames free of full snapshot, outbox,
      // thumbnail and notification work. A pause restarts the window on resume.
      _startupTimer ??= Timer(_androidStartupDelay, () {
        _startupTimer = null;
        if (_closed || !_foreground || !auth.state.authenticated) return;
        _androidStartupPending = false;
        _bindSalesNotifications();
        unawaited(_maintain());
      });
      return;
    }
    if (_maintaining) return;
    final epoch = _scopeEpoch;
    bool current() => !_closed && _scopeEpoch == epoch;
    _maintaining = true;
    try {
      final remote = await repo.get(
        '/api/cloud/revision',
        force: true,
        permitirCacheSinRed: false,
      );
      if (!current()) return;
      if (remote['cache_scope'] != auth.state.cacheScope) {
        await auth.resume();
        return;
      }
      final value = '${remote['revision']}';
      final first = _remoteRevision == null;
      final changed = _remoteRevision != null && _remoteRevision != value;
      _remoteRevision = value;
      if (changed) {
        repo.invalidar();
        revision++;
        notifyListeners();
      }
      final result = await repo.flushOps();
      if (!current()) return;
      if (result.resultados.isNotEmpty) {
        repo.invalidar();
        revision++;
        notifyListeners();
      }
      final today = DateTime.now().toIso8601String().substring(0, 10);
      final refreshData =
          first ||
          changed ||
          _dataDirty ||
          result.resultados.isNotEmpty ||
          _snapshotDay != today;
      if (refreshData) await appearance.load(force: true);
      if (!current()) return;
      SnapshotDto? snapshot;
      if (repo.copiaPersistenteDisponible && refreshData) {
        snapshot = await repo.snapshot(
          force: changed || result.resultados.isNotEmpty,
        );
        if (!current()) return;
        if (!_warmingImages &&
            (_warmedRevision != value ||
                _lastImageWarm == null ||
                DateTime.now().difference(_lastImageWarm!) >
                    const Duration(minutes: 5))) {
          _warmingImages = true;
          _lastImageWarm = DateTime.now();
          _warmedRevision = value;
          unawaited(
            repo
                .precargarImagenes(snapshot)
                .catchError((Object _) {})
                .whenComplete(() {
                  _warmingImages = false;
                }),
          );
        }
      }
      if (refreshData) {
        await notifications.refresh(repo, snapshot: snapshot);
        if (!current()) return;
        _dataDirty = false;
        _snapshotDay = today;
      }
    } catch (_) {
      // Interrupted maintenance preserves the scoped snapshot, outbox and alarms.
    } finally {
      _maintaining = false;
      if (!current()) unawaited(_maintain());
    }
  }

  Future<void> synchronize() async {
    await repo.sincronizar();
    refresh();
  }

  @override
  void dispose() {
    _closed = true;
    _revisionTimer?.cancel();
    _refreshTimer?.cancel();
    _startupTimer?.cancel();
    notifications.dispose();
    salesNotifications.dispose();
    appearance.removeListener(notifyListeners);
    appearance.dispose();
    textSize.dispose();
    auth.removeListener(_authChanged);
    repo.close();
    super.dispose();
  }
}

class CorteScope extends InheritedNotifier<CorteUiController> {
  const CorteScope({
    super.key,
    required CorteUiController controller,
    required super.child,
  }) : super(notifier: controller);
  static CorteUiController of(BuildContext context) =>
      context.dependOnInheritedWidgetOfExactType<CorteScope>()!.notifier!;
}

class CorteRouteParser extends RouteInformationParser<String> {
  const CorteRouteParser();
  @override
  Future<String> parseRouteInformation(
    RouteInformation routeInformation,
  ) async {
    final value = routeInformation.uri;
    return value.path == '/' || value.path.isEmpty
        ? '/inicio'
        : value.toString();
  }

  @override
  RouteInformation restoreRouteInformation(String configuration) =>
      RouteInformation(uri: Uri.parse(configuration));
}

class CorteRouter extends RouterDelegate<String>
    with ChangeNotifier, PopNavigatorRouterDelegateMixin<String> {
  CorteRouter(this.ui) {
    ui.addListener(notifyListeners);
  }
  final CorteUiController ui;
  @override
  final navigatorKey = GlobalKey<NavigatorState>();
  @override
  String get currentConfiguration => ui.location;
  @override
  Future<void> setNewRoutePath(String configuration) async {
    ui.restoreRoute(configuration);
  }

  @override
  Future<bool> popRoute() async => ui.back();
  @override
  Widget build(BuildContext context) => CorteScope(
    controller: ui,
    child: Navigator(
      key: navigatorKey,
      pages: [
        MaterialPage<void>(
          key: const ValueKey('corte'),
          child: ui.auth.state.authenticated
              ? const CorteShell()
              : const CorteAccess(),
        ),
      ],
      onDidRemovePage: (_) {},
    ),
  );
  @override
  void dispose() {
    ui.removeListener(notifyListeners);
    super.dispose();
  }
}

class CorteAccess extends StatelessWidget {
  const CorteAccess({super.key});
  @override
  Widget build(BuildContext context) {
    final ui = CorteScope.of(context);
    final state = ui.auth.state;
    final pending = ui.auth.runtime.platform == 'windows'
        ? state.pending
        : null;
    return Scaffold(
      appBar: AppBar(
        backgroundColor: CorteColors.chrome,
        foregroundColor: Colors.white,
        title: const CorteWordmark(),
        centerTitle: true,
        automaticallyImplyLeading: false,
      ),
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 410),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text(
                  state.busy
                      ? 'Abriendo tu espacio'
                      : pending != null
                      ? 'Conecta este dispositivo'
                      : 'Tu espacio en CUTGC',
                  style: Theme.of(context).textTheme.headlineLarge?.copyWith(
                    fontSize: 25,
                    fontWeight: FontWeight.w700,
                    letterSpacing: -.5,
                    height: 1.2,
                  ),
                ),
                const SizedBox(height: 12),
                Text(
                  pending != null
                      ? 'Confirma este código en el navegador para conectar tu cuenta con Google.'
                      : 'Tus muestras, tus productos y tus resultados, juntos.',
                  style: TextStyle(
                    color: context.corte.muted,
                    fontSize: 16,
                    height: 1.5,
                  ),
                ),
                const SizedBox(height: 30),
                if (state.busy)
                  const Center(
                    child: CircularProgressIndicator(
                      semanticsLabel: 'Conectando con CUTGC',
                    ),
                  )
                else if (pending != null) ...[
                  Container(
                    padding: const EdgeInsets.all(22),
                    decoration: BoxDecoration(
                      color: context.corte.rose,
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: SelectableText(
                      pending.userCode,
                      textAlign: TextAlign.center,
                      style: const TextStyle(
                        fontSize: 32,
                        fontWeight: FontWeight.w800,
                        letterSpacing: 3,
                      ),
                    ),
                  ),
                  const SizedBox(height: 12),
                  // El enlace siempre a la vista: si el navegador no se abre, se copia y se abre en cualquier lado.
                  SelectableText(
                    pending.verificationUri.toString(),
                    textAlign: TextAlign.center,
                    style: TextStyle(color: context.corte.muted, fontSize: 13),
                  ),
                  TextButton.icon(
                    onPressed: () => Clipboard.setData(
                      ClipboardData(text: pending.verificationUri.toString()),
                    ),
                    icon: const Icon(Icons.copy_rounded, size: 18),
                    label: const Text('Copiar enlace'),
                  ),
                  const SizedBox(height: 8),
                  FilledButton.icon(
                    onPressed: ui.auth.openVerificationPage,
                    icon: const Icon(Icons.open_in_new_rounded, size: 19),
                    label: const Text('Abrir Google en el navegador'),
                  ),
                  const SizedBox(height: 10),
                  TextButton(
                    onPressed: ui.auth.pollNow,
                    child: const Text('Ya autoricé este dispositivo'),
                  ),
                ] else ...[
                  FilledButton.icon(
                    onPressed: () => ui.auth.signIn(),
                    icon: const Icon(Icons.login_rounded, size: 20),
                    label: const Text('Continuar con Google'),
                  ),
                  if (state.canRedirect)
                    TextButton(
                      onPressed: () => ui.auth.signIn(redirect: true),
                      child: const Text('Continuar en esta pestaña'),
                    ),
                  if (state.phase == CorteAuthPhase.error)
                    TextButton(
                      onPressed: ui.auth.resume,
                      child: const Text('Reintentar conexión'),
                    ),
                ],
                if (state.errorMessage != null) ...[
                  const SizedBox(height: 18),
                  InlineNotice(text: state.errorMessage!, error: true),
                ],
                const SizedBox(height: 30),
                Text(
                  'Acceso privado con tu cuenta de Google.',
                  textAlign: TextAlign.center,
                  style: TextStyle(color: context.corte.muted, fontSize: 13),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
