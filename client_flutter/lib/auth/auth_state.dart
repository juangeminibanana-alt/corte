enum CorteAuthPhase {
  checking,
  signedOut,
  awaitingApproval,
  authenticated,
  error,
  unsupported,
}

class CortePendingApproval {
  const CortePendingApproval({
    required this.userCode,
    required this.verificationUri,
    required this.expiresAt,
  });
  final String userCode;
  final Uri verificationUri;
  final DateTime expiresAt;
}

/// Estado público: nunca contiene bearer, verifier, request_id ni identidad privada de TikTok.
class CorteAuthState {
  const CorteAuthState({
    this.phase = CorteAuthPhase.checking,
    this.connected = false,
    this.ownerScope,
    this.cacheScope,
    this.ownerEmail,
    this.expiresAt,
    this.pending,
    this.errorMessage,
    this.canRedirect = false,
  });

  final CorteAuthPhase phase;
  final bool connected;
  final String? ownerScope;
  final String? cacheScope;
  final String? ownerEmail;
  final DateTime? expiresAt;
  final CortePendingApproval? pending;
  final String? errorMessage;
  final bool canRedirect;
  bool get authenticated => phase == CorteAuthPhase.authenticated;
  bool get offline => authenticated && !connected;
  bool get busy => phase == CorteAuthPhase.checking;
}
