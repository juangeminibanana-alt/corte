import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:crypto/crypto.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;

import '../platform/corte_runtime.dart';
import '../platform/corte_transport.dart';
import '../platform/external_links.dart';
import '../platform/native_bridge.dart';
import 'auth_state.dart';
import 'web_sign_in.dart';

export 'auth_state.dart';

class CorteAuthController extends ChangeNotifier {
  CorteAuthController({
    CorteRuntime? runtime,
    CorteCredentialStore? credentials,
    CorteExternalLinks? links,
    CorteWebSignIn? webSignIn,
    Future<String?> Function()? androidSignIn,
    http.Client? client,
    DateTime Function()? clock,
  }) : runtime = runtime ?? CorteRuntime.current(),
       _credentials = credentials ?? const CorteNativeBridge(),
       _links = links ?? const CorteSystemLinks(),
       _webSignIn = webSignIn ?? createWebSignIn(),
       _androidSignIn =
           androidSignIn ?? const CorteNativeBridge().signInWithGoogle,
       _clock = clock ?? DateTime.now {
    transport = CorteTransport(
      runtime: this.runtime,
      client: client,
      readBearer: _readAuthorization,
      onNativeInvalidSession: _invalidate,
      onWebInvalidSession: () {
        _generation++;
        _set(
          const CorteAuthState(
            phase: CorteAuthPhase.signedOut,
            errorMessage: 'Tu sesión venció. Vuelve a entrar con Google.',
          ),
        );
      },
      onConnectionChanged: _connection,
    );
  }

  final CorteRuntime runtime;
  final CorteCredentialStore _credentials;
  final CorteExternalLinks _links;
  final CorteWebSignIn _webSignIn;
  final Future<String?> Function() _androidSignIn;
  final DateTime Function() _clock;
  late final CorteTransport transport;
  CorteAuthState _state = const CorteAuthState();
  CorteAuthState get state => _state;
  Uri get baseUri => runtime.baseUri;
  String get baseUrl => baseUri.origin;
  String? get ownerScope => _state.ownerScope;
  String? get cacheScope => _state.cacheScope;
  bool get isWeb => runtime.isWeb;
  Map<String, Object?>? _device, _pending;
  String? _lockedOwner;
  bool _disposed = false,
      _initialized = false,
      _credentialsReady = false,
      _foreground = true,
      _polling = false,
      _probing = false,
      _signingIn = false,
      _signingOut = false;
  int _generation = 0;
  Timer? _timer;
  CorteCancelToken? _pollCancel;
  Future<void> _storeTail = Future<void>.value();

  Future<void> _storeMutation(int generation, Future<void> Function() action) {
    final next = _storeTail.then((_) async {
      if (generation != _generation || _disposed) return;
      await action();
    });
    _storeTail = next.catchError((Object _) {});
    return next;
  }

  static final _tokenPattern = RegExp(r'^corte_native_v1_[A-Za-z0-9_-]{43}$');
  static final _idPattern = RegExp(r'^[A-Za-z0-9_-]{16,128}$');
  int get _now => _clock().millisecondsSinceEpoch ~/ 1000;
  static int _integer(Object? v) => v is num && v.isFinite ? v.toInt() : 0;
  static String? _text(Object? v) => v is String && v.isNotEmpty ? v : null;
  static Map<String, Object?>? _object(Object? v) =>
      v is Map ? Map<String, Object?>.from(v) : null;
  static Map<String, Object?>? _json(String? value) {
    if (value == null) return null;
    try {
      return _object(jsonDecode(value));
    } catch (_) {
      return null;
    }
  }

  static Map<String, Object?>? _response(CorteResponse r) {
    try {
      return _json(utf8.decode(r.bodyBytes));
    } catch (_) {
      return null;
    }
  }

  static String _scope(String uid) =>
      sha256.convert(utf8.encode('corte-owner:$uid')).toString();
  bool get _validDevice =>
      _device != null &&
      _tokenPattern.hasMatch(_text(_device!['token']) ?? '') &&
      _integer(_device!['expires_at']) > _now;
  bool get _validPending =>
      _pending != null && _integer(_pending!['expires_at']) > _now;

  Future<String?> _readAuthorization() async {
    if (_validDevice) return _device!['token'] as String;
    final expired = _text(_device?['token']);
    if (expired != null) await _invalidate(expired);
    return null;
  }

  void _set(CorteAuthState value) {
    if (_disposed) return;
    _state = value;
    notifyListeners();
  }

  void _authenticated({bool connected = true, String? error}) {
    final uid = _text(_device?['owner_uid']);
    if (!_validDevice || uid == null) return;
    _set(
      CorteAuthState(
        phase: CorteAuthPhase.authenticated,
        connected: connected,
        ownerScope: _scope(uid),
        cacheScope: _validScope(_device?['cache_scope']),
        ownerEmail: _text(_device?['owner_email']),
        expiresAt: DateTime.fromMillisecondsSinceEpoch(
          _integer(_device?['expires_at']) * 1000,
          isUtc: true,
        ),
        errorMessage: error,
      ),
    );
  }

  void _waiting({String? error}) {
    if (!_validPending) return;
    _set(
      CorteAuthState(
        phase: CorteAuthPhase.awaitingApproval,
        errorMessage: error,
        pending: CortePendingApproval(
          userCode: _pending!['user_code'] as String,
          verificationUri: Uri.parse(_pending!['verification_uri'] as String),
          expiresAt: DateTime.fromMillisecondsSinceEpoch(
            _integer(_pending!['expires_at']) * 1000,
            isUtc: true,
          ),
        ),
      ),
    );
  }

  void _connection(bool connected) {
    if (!_state.authenticated || _state.connected == connected) return;
    if (!runtime.isWeb) {
      _authenticated(connected: connected);
      return;
    }
    _set(
      CorteAuthState(
        phase: _state.phase,
        connected: connected,
        ownerScope: _state.ownerScope,
        cacheScope: _state.cacheScope,
        ownerEmail: _state.ownerEmail,
        expiresAt: _state.expiresAt,
        errorMessage: _state.errorMessage,
        canRedirect: _state.canRedirect,
      ),
    );
  }

  Future<void> _invalidate(String usedToken) async {
    if (_device?['token'] != usedToken) {
      return; // Un401 antiguo no borra una sesión nueva.
    }
    _generation++;
    _device = null;
    _cancelPoll();
    try {
      await _storeMutation(
        _generation,
        () => _credentials.delete(deviceSessionKey),
      );
    } catch (_) {
      /* Gate cerrado en memoria. */
    }
    _set(
      const CorteAuthState(
        phase: CorteAuthPhase.signedOut,
        errorMessage: 'Tu sesión venció. Vuelve a conectar Corte con Google.',
      ),
    );
  }

  Future<void> initialize() async {
    if (_initialized || _disposed) return;
    _initialized = true;
    if (!runtime.isSupported) {
      _set(
        const CorteAuthState(
          phase: CorteAuthPhase.unsupported,
          errorMessage: 'Este sistema todavía no está habilitado.',
        ),
      );
      return;
    }
    if (runtime.isWeb) {
      await _checkWeb(finishRedirect: true);
      return;
    }
    try {
      _credentialsReady = false;
      _lockedOwner = await _credentials.read(sessionOwnerKey);
      _device = _json(await _credentials.read(deviceSessionKey));
      _pending = runtime.platform == 'windows'
          ? _json(await _credentials.read(pendingAuthorizationKey))
          : null;
      _credentialsReady = true;
      if (_validDevice) {
        final owner = _text(_device?['owner_uid']);
        if (_lockedOwner != null && owner != null && _lockedOwner != owner) {
          _device = null;
          _set(
            const CorteAuthState(
              phase: CorteAuthPhase.error,
              errorMessage:
                  'La copia de este dispositivo pertenece a otra cuenta.',
            ),
          );
          return;
        }
        await _probeNative();
      } else if (_validPending && _pendingIsValid(_pending!)) {
        _waiting();
        _schedule(const Duration(seconds: 3));
      } else {
        _pending = null;
        _set(const CorteAuthState(phase: CorteAuthPhase.signedOut));
      }
    } catch (_) {
      _set(
        const CorteAuthState(
          phase: CorteAuthPhase.error,
          errorMessage:
              'No pudimos abrir el almacenamiento seguro. Tu copia anterior se conserva.',
        ),
      );
    }
  }

  Future<void> _probeNative() async {
    if (_probing || !_validDevice || _disposed) return;
    _probing = true;
    final generation = _generation;
    try {
      final response = await transport.request('GET', '/api/native/session');
      if (generation != _generation || _disposed) return;
      final value = _response(response);
      final owner = _object(value?['owner']);
      final uid = _text(owner?['uid']);
      if (response.statusCode == 200 &&
          value?['authenticated'] == true &&
          uid != null &&
          uid.length <= 128) {
        if (_lockedOwner != null && _lockedOwner != uid) {
          _set(
            const CorteAuthState(
              phase: CorteAuthPhase.error,
              errorMessage:
                  'Esta copia pertenece a otra cuenta. Usa la cuenta original.',
            ),
          );
          return;
        }
        final updated = {
          ..._device!,
          'owner_uid': uid,
          'owner_email': owner?['email'],
          'cache_scope': _validScope(value?['cache_scope']),
        };
        await _storeMutation(generation, () async {
          await _credentials.write(sessionOwnerKey, uid);
          await _credentials.write(deviceSessionKey, jsonEncode(updated));
        });
        if (generation != _generation || _disposed) return;
        _lockedOwner = uid;
        _device = updated;
        _authenticated();
      } else if (_validDevice &&
          _text(_device?['owner_uid']) != null &&
          response.statusCode >= 500) {
        _authenticated(
          connected: false,
          error: 'No pudimos verificar la conexión. Tu copia sigue disponible.',
        );
      } else if (response.statusCode != 401) {
        _set(
          const CorteAuthState(
            phase: CorteAuthPhase.error,
            errorMessage:
                'No pudimos verificar esta sesión. Inténtalo de nuevo.',
          ),
        );
      }
    } on CorteTransportException {
      if (generation != _generation || _disposed) return;
      if (_text(_device?['owner_uid']) != null) {
        _authenticated(connected: false);
      } else {
        _set(
          const CorteAuthState(
            phase: CorteAuthPhase.error,
            errorMessage:
                'Conecta a internet para verificar la sesión anterior. Los datos se conservan.',
          ),
        );
      }
    } catch (_) {
      if (generation == _generation) {
        _set(
          const CorteAuthState(
            phase: CorteAuthPhase.error,
            errorMessage:
                'No pudimos conservar la sesión segura. Los datos anteriores se mantienen.',
          ),
        );
      }
    } finally {
      _probing = false;
    }
  }

  Future<void> _checkWeb({bool finishRedirect = false}) async {
    final generation = _generation;
    try {
      var response = await transport.request('GET', '/api/cloud/session');
      var value = _response(response);
      if (finishRedirect &&
          response.statusCode == 200 &&
          value?['authenticated'] != true) {
        if (await _webSignIn.finishRedirect()) {
          response = await transport.request('GET', '/api/cloud/session');
          value = _response(response);
        }
      }
      if (generation != _generation || _disposed) return;
      if (response.statusCode != 200 ||
          value?['cloud'] != true ||
          value?['authenticated'] is! bool) {
        throw const CorteTransportException(
          'respuesta_invalida',
          'El servidor no confirmó la sesión.',
        );
      }
      if (value?['authenticated'] == true) {
        final scope = _text(value?['owner_scope']);
        _set(
          CorteAuthState(
            phase: CorteAuthPhase.authenticated,
            connected: true,
            ownerScope: _validScope(scope),
            cacheScope: _validScope(value?['cache_scope']),
          ),
        );
      } else {
        _set(const CorteAuthState(phase: CorteAuthPhase.signedOut));
      }
    } on CorteWebAuthException catch (e) {
      _webError(e);
    } catch (_) {
      if (generation == _generation) {
        _set(
          const CorteAuthState(
            phase: CorteAuthPhase.error,
            errorMessage:
                'No pudimos comprobar la sesión. Revisa tu conexión e inténtalo de nuevo.',
          ),
        );
      }
    }
  }

  void _webError(CorteWebAuthException e) {
    _set(
      CorteAuthState(
        phase: CorteAuthPhase.signedOut,
        errorMessage: e.message,
        canRedirect: e.code == 'auth/popup-blocked',
      ),
    );
  }

  static String? _validScope(Object? value) =>
      value is String && RegExp(r'^[a-f0-9]{64}$').hasMatch(value)
      ? value
      : null;

  Future<void> signIn({bool redirect = false}) async {
    if (_signingIn || _signingOut || _disposed || !runtime.isSupported) return;
    _signingIn = true;
    try {
      if (runtime.isWeb) {
        if (redirect) {
          await _webSignIn.redirectSignIn();
          return;
        }
        if (await _webSignIn.signIn()) await _checkWeb();
        return;
      }
      if (!_credentialsReady) {
        _initialized = false;
        await initialize();
        if (!_credentialsReady) return;
      }
      if (runtime.platform == 'android') {
        if (_validDevice) {
          await _probeNative();
        } else {
          await _signInAndroid();
        }
        return;
      }
      if (_validPending && _pendingIsValid(_pending!)) {
        await openVerificationPage();
        _waiting();
        _schedule(const Duration(seconds: 3));
        return;
      }
      final generation = ++_generation;
      _set(const CorteAuthState(phase: CorteAuthPhase.checking));
      final random = Random.secure();
      final verifier = base64Url
          .encode(List.generate(32, (_) => random.nextInt(256)))
          .replaceAll('=', '');
      final challenge = base64Url
          .encode(sha256.convert(ascii.encode(verifier)).bytes)
          .replaceAll('=', '');
      final response = await transport.request(
        'POST',
        '/api/native/auth/start',
        body: {
          'platform': runtime.platform,
          'name': 'Corte para Windows',
          'code_challenge': challenge,
        },
        maxResponseBytes: 32 * 1024,
      );
      if (generation != _generation || _disposed) return;
      final value = _response(response);
      final duration = _integer(value?['expires_in']);
      final pending = <String, Object?>{
        'request_id': value?['request_id'],
        'code_verifier': verifier,
        'user_code': value?['user_code'],
        'verification_uri': value?['verification_uri'],
        'expires_at': _now + duration,
      };
      if (response.statusCode != 200 ||
          duration < 1 ||
          duration > 600 ||
          !_pendingIsValid(pending)) {
        throw const CorteTransportException(
          'acceso_no_iniciado',
          'No pudimos iniciar el acceso. Inténtalo de nuevo.',
        );
      }
      await _storeMutation(
        generation,
        () => _credentials.write(pendingAuthorizationKey, jsonEncode(pending)),
      );
      if (generation != _generation || _disposed) return;
      _pending = pending;
      _waiting();
      await openVerificationPage();
      _schedule(
        Duration(seconds: max(3, min(60, _integer(value?['interval'])))),
      );
    } on CorteWebAuthException catch (e) {
      _webError(e);
    } on CorteTransportException catch (e) {
      _set(
        CorteAuthState(
          phase: CorteAuthPhase.signedOut,
          errorMessage: e.mensaje,
        ),
      );
    } catch (_) {
      _set(
        const CorteAuthState(
          phase: CorteAuthPhase.error,
          errorMessage:
              'No pudimos guardar el acceso seguro. Tu copia anterior se conserva.',
        ),
      );
    } finally {
      _signingIn = false;
    }
  }

  Future<void> _signInAndroid() async {
    final generation = ++_generation;
    _set(const CorteAuthState(phase: CorteAuthPhase.checking));
    String? error;
    try {
      final idToken = await _androidSignIn();
      if (generation != _generation || _disposed) return;
      if (idToken != null) {
        final response = await transport.request(
          'POST',
          '/api/native/auth/google',
          body: {'id_token': idToken, 'device_name': 'Corte para Android'},
          maxResponseBytes: 32 * 1024,
        );
        if (generation != _generation || _disposed) return;
        final device = _grantedDevice(response);
        if (device == null) {
          error = switch (response.statusCode) {
            401 => 'Google no pudo confirmar el acceso. Vuelve a intentarlo.',
            403 => 'Esta cuenta de Google no tiene acceso a Corte.',
            429 => 'Espera un momento y vuelve a intentarlo.',
            _ => 'No pudimos conectar Corte con Google. Vuelve a intentarlo.',
          };
        } else if (_lockedOwner != null &&
            _lockedOwner != device['owner_uid']) {
          error = 'Esta copia pertenece a otra cuenta. Usa la cuenta original.';
        } else {
          await _saveNativeDevice(device, generation);
          return;
        }
      }
    } on PlatformException catch (e) {
      error = switch (e.code) {
        'google_unavailable' =>
          'Actualiza Servicios de Google Play e inténtalo de nuevo.',
        'google_no_account' =>
          'Agrega tu cuenta de Google en los ajustes de Android.',
        'google_sign_in_busy' => 'Google ya está confirmando el acceso.',
        _ => 'No pudimos conectar con Google. Vuelve a intentarlo.',
      };
    } on MissingPluginException {
      error = 'El acceso con Google no está disponible en esta instalación.';
    } on CorteTransportException catch (e) {
      error = e.mensaje;
    } catch (_) {
      error =
          'No pudimos guardar el acceso seguro. Tu copia anterior se conserva.';
    }
    if (generation == _generation && !_disposed) {
      _set(
        CorteAuthState(phase: CorteAuthPhase.signedOut, errorMessage: error),
      );
    }
  }

  Map<String, Object?>? _grantedDevice(CorteResponse response) {
    final value = _response(response);
    final owner = _object(value?['owner']);
    final uid = _text(owner?['uid']);
    final token = _text(value?['token']);
    final deviceId = _text(value?['device_id']);
    final expiry = _integer(value?['expires_at']);
    if (response.statusCode != 200 ||
        value?['estado'] != 'autorizado' ||
        uid == null ||
        uid.length > 128 ||
        token == null ||
        !_tokenPattern.hasMatch(token) ||
        deviceId == null ||
        !_idPattern.hasMatch(deviceId) ||
        expiry <= _now) {
      return null;
    }
    return {
      'token': token,
      'device_id': deviceId,
      'expires_at': expiry,
      'owner_uid': uid,
      'owner_email': owner?['email'],
    };
  }

  Future<void> _saveNativeDevice(
    Map<String, Object?> device,
    int generation,
  ) async {
    final uid = device['owner_uid'] as String;
    await _storeMutation(generation, () async {
      await _credentials.write(sessionOwnerKey, uid);
      await _credentials.write(deviceSessionKey, jsonEncode(device));
      await _credentials.delete(pendingAuthorizationKey);
    });
    if (generation != _generation || _disposed) return;
    _lockedOwner = uid;
    _device = device;
    _pending = null;
    await _probeNative();
  }

  bool _pendingIsValid(Map<String, Object?> pending) {
    final uri = Uri.tryParse(_text(pending['verification_uri']) ?? '');
    return _idPattern.hasMatch(_text(pending['request_id']) ?? '') &&
        RegExp(
          r'^[A-Za-z0-9._~-]{43,128}$',
        ).hasMatch(_text(pending['code_verifier']) ?? '') &&
        RegExp(
          r'^[A-Z2-9]{4}-[A-Z2-9]{4}$',
        ).hasMatch(_text(pending['user_code']) ?? '') &&
        uri != null &&
        uri.scheme == 'https' &&
        uri.hasAuthority &&
        uri.origin == baseUri.origin &&
        uri.path == '/conectar-dispositivo' &&
        !uri.hasFragment &&
        uri.userInfo.isEmpty &&
        uri.queryParameters['codigo'] == pending['user_code'];
  }

  Future<void> openVerificationPage() async {
    if (_pending == null) return;
    if (!_validPending) {
      await _finishPending('El código venció. Vuelve a conectar tu cuenta.');
      return;
    }
    if (!_pendingIsValid(_pending!)) return;
    // Nunca falla en silencio: si el sistema no abre el navegador (o lanza un error), se dice y el enlace queda a la vista.
    var opened = false;
    try {
      opened = await _links.open(
        Uri.parse(_pending!['verification_uri'] as String),
      );
    } catch (_) {
      opened = false;
    }
    if (!opened) {
      _waiting(
        error:
            'No se abrió el navegador. Copia el enlace y ábrelo en cualquier navegador, aquí o en tu computadora.',
      );
    }
  }

  void _schedule(Duration delay) {
    _timer?.cancel();
    if (_foreground && !_disposed && _validPending) {
      _timer = Timer(delay, () {
        unawaited(pollNow());
      });
    }
  }

  Future<void> pollNow() async {
    if (_polling || _disposed || !_foreground || _pending == null) return;
    if (!_validPending) {
      await _finishPending('El código venció. Vuelve a conectar tu cuenta.');
      return;
    }
    _polling = true;
    final generation = _generation;
    final pending = _pending!;
    final cancel = CorteCancelToken();
    _pollCancel = cancel;
    var next = const Duration(seconds: 3);
    try {
      final response = await transport.request(
        'POST',
        '/api/native/auth/poll',
        body: {
          'request_id': pending['request_id'],
          'code_verifier': pending['code_verifier'],
        },
        maxResponseBytes: 32 * 1024,
        cancelToken: cancel,
      );
      if (generation != _generation || _disposed) return;
      if (response.statusCode == 202 || response.statusCode >= 500) return;
      if (response.statusCode == 429) {
        next = Duration(
          seconds: max(
            3,
            min(60, int.tryParse(response.headers['retry-after'] ?? '') ?? 3),
          ),
        );
        return;
      }
      final device = _grantedDevice(response);
      if (device != null) {
        if (_lockedOwner != null && _lockedOwner != device['owner_uid']) {
          await _finishPending(
            'Esta copia pertenece a otra cuenta. Usa la cuenta original.',
          );
          return;
        }
        await _saveNativeDevice(device, generation);
      } else {
        await _finishPending(
          response.statusCode == 410
              ? 'El código venció. Inicia otra conexión.'
              : response.statusCode == 403
              ? 'No se autorizó este dispositivo. Puedes volver a intentarlo.'
              : response.statusCode == 409
              ? 'La autorización ya se entregó. Si no llegó, inicia otra conexión.'
              : 'No se pudo completar el acceso. Inicia otra conexión.',
        );
      }
    } on CorteTransportException {
      // La credencial/PKCE y la copia se conservan; no hay reintentos de otras mutaciones.
    } catch (_) {
      if (generation == _generation) {
        await _finishPending(
          'No pudimos conservar la sesión segura. Vuelve a conectar la app.',
        );
      }
    } finally {
      _polling = false;
      _pollCancel = null;
      if (generation == _generation) _schedule(next);
    }
  }

  Future<void> _finishPending(String message) async {
    _pending = null;
    _cancelPoll();
    try {
      await _storeMutation(
        _generation,
        () => _credentials.delete(pendingAuthorizationKey),
      );
    } catch (_) {
      /* No se borra la copia. */
    }
    _set(
      CorteAuthState(phase: CorteAuthPhase.signedOut, errorMessage: message),
    );
  }

  void _cancelPoll() {
    _timer?.cancel();
    _timer = null;
    _pollCancel?.cancel();
  }

  void pause() {
    _foreground = false;
    _cancelPoll();
  }

  Future<void> resume() async {
    if (_signingOut || _disposed) return;
    _foreground = true;
    if (runtime.platform == 'android' && _signingIn) return;
    if (!_initialized) {
      await initialize();
      return;
    }
    if (runtime.isWeb) {
      await _checkWeb();
      return;
    }
    if (!_credentialsReady) {
      _initialized = false;
      await initialize();
      return;
    }
    if (_validPending) {
      _waiting();
      _schedule(const Duration(seconds: 3));
    } else if (_validDevice) {
      await _probeNative();
    } else if (_device != null) {
      await _readAuthorization();
    }
  }

  Future<void> refreshSession() => runtime.isWeb ? _checkWeb() : _probeNative();

  Future<void> signOut() async {
    if (_signingOut || _disposed) return;
    _signingOut = true;
    _generation++;
    _cancelPoll();
    _pending = null;
    try {
      if (runtime.isWeb) {
        await _webSignIn.signOut();
      } else {
        try {
          if (_validDevice) {
            await transport.request(
              'POST',
              '/api/native/devices/self/revoke',
              body: const {},
              timeout: const Duration(seconds: 8),
            );
          }
        } finally {
          _device = null;
          await _storeMutation(_generation, () async {
            await _credentials.delete(deviceSessionKey);
            await _credentials.delete(pendingAuthorizationKey);
          });
        }
      }
      _set(const CorteAuthState(phase: CorteAuthPhase.signedOut));
    } catch (_) {
      _device = null;
      _set(
        const CorteAuthState(
          phase: CorteAuthPhase.signedOut,
          errorMessage:
              'Se cerró el acceso local. No pudimos confirmar el cierre remoto; revisa tus dispositivos desde Corte.',
        ),
      );
    } finally {
      _signingOut = false;
    }
  }

  @override
  void dispose() {
    _disposed = true;
    _generation++;
    _cancelPoll();
    transport.close();
    super.dispose();
  }
}
