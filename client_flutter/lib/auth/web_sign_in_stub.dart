import 'web_sign_in.dart';

CorteWebSignIn createWebSignIn() => const _Unavailable();

class _Unavailable implements CorteWebSignIn {
  const _Unavailable();
  Never _fail() => throw const CorteWebAuthException(
    'no_disponible',
    'Este acceso corresponde al navegador.',
  );
  @override
  Future<bool> signIn() async => _fail();
  @override
  Future<bool> finishRedirect() async => false;
  @override
  Future<void> redirectSignIn() async => _fail();
  @override
  Future<void> signOut() async => _fail();
}
