import 'web_sign_in_stub.dart'
    if (dart.library.js_interop) 'web_sign_in_browser.dart'
    as implementation;

abstract interface class CorteWebSignIn {
  Future<bool> signIn();
  Future<bool> finishRedirect();
  Future<void> redirectSignIn();
  Future<void> signOut();
}

class CorteWebAuthException implements Exception {
  const CorteWebAuthException(this.code, this.message);
  final String code;
  final String message;
  @override
  String toString() => 'CorteWebAuthException($code)';
}

CorteWebSignIn createWebSignIn() => implementation.createWebSignIn();
