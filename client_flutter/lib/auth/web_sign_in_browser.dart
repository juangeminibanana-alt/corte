import 'dart:js_interop';

import 'web_sign_in.dart';

@JS('corteAuth.signIn')
external JSPromise<JSAny?> _signIn();
@JS('corteAuth.finishRedirect')
external JSPromise<JSAny?> _finishRedirect();
@JS('corteAuth.redirectSignIn')
external JSPromise<JSAny?> _redirectSignIn();
@JS('corteAuth.signOut')
external JSPromise<JSAny?> _signOut();

CorteWebSignIn createWebSignIn() => const _BrowserSignIn();

class _BrowserSignIn implements CorteWebSignIn {
  const _BrowserSignIn();

  Future<bool> _result(JSPromise<JSAny?> Function() call) async {
    try {
      final value = (await call().toDart)?.dartify();
      if (value is Map && value['ok'] == false) {
        throw CorteWebAuthException(
          value['code'] is String ? value['code'] as String : 'error_google',
          value['message'] is String
              ? value['message'] as String
              : 'No pudimos completar el acceso con Google.',
        );
      }
      return value is Map && value['authenticated'] == true;
    } on CorteWebAuthException {
      rethrow;
    } catch (_) {
      throw const CorteWebAuthException(
        'puente_no_disponible',
        'No se pudo cargar el acceso con Google. Recarga la página.',
      );
    }
  }

  @override
  Future<bool> signIn() => _result(() => _signIn());
  @override
  Future<bool> finishRedirect() => _result(() => _finishRedirect());
  @override
  Future<void> redirectSignIn() async {
    await _result(() => _redirectSignIn());
  }

  @override
  Future<void> signOut() async {
    await _result(() => _signOut());
  }
}
