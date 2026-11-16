# Corte para Windows y Android: autorización v1

El ejecutable y el APK conservan su interfaz empaquetada, sus puentes nativos y
sus datos sin conexión. El cliente nativo hace las solicitudes HTTPS al origen
fijo de Corte; nunca entrega su credencial a JavaScript ni carga la web remota
como interfaz de la app.

## Aprobar una app

Todos los POST envían JSON, `Origin: https://corte-e-book-21589.web.app` y
`X-CH-Hub: 1`. Los endpoints de inicio/sondeo no llevan cookies ni Authorization.

1. El nativo genera un verifier aleatorio PKCE de 43–128 caracteres
   `[A-Za-z0-9._~-]`. Envía `POST /api/native/auth/start` con
   `{platform: "windows" | "android", name: "nombre de hasta 80 caracteres",
   code_challenge: "base64url sin padding de SHA256(verifier)"}`.
2. Recibe `{request_id, user_code, verification_uri, expires_in: 600, interval: 3}`.
   Abre `verification_uri` en el navegador del sistema. No abre Google dentro
   de WebView2 ni Android WebView. El verifier y request_id quedan en el nativo.
3. La web exige la sesión Google owner existente. Consulta
   `GET /api/native/auth/request?codigo=XXXX-XXXX`, muestra nombre/sistema/código
   y pide aprobación explícita. `POST /api/native/auth/approve` o `/deny` recibe
   `{user_code}` y conserva los controles de cookie, Origin y CSRF.
4. Cada 3 segundos el nativo envía `POST /api/native/auth/poll` con
   `{request_id, code_verifier}`. `202 {estado: "pendiente"}` continúa;
   `429` respeta `Retry-After`; `403` denegado y `410` vencido terminan el intento.
5. Una única entrega devuelve `200 {estado: "autorizado", device_id,
   token: "corte_native_v1_<43 caracteres base64url>", expires_at,
   owner: {uid, email}}`. El token dura 30 días. Se persiste cifrado con DPAPI
   en Windows o AndroidKeystore en Android antes de anunciar éxito.

La entrega del token es de un solo uso, serializada con SQLite. Repetir el canje
después del éxito devuelve `409 autorizacion_entregada`: si se perdió la respuesta,
hay que iniciar otra autorización. No existe un caché de respuesta con tokens.

## Usar y revocar

El transporte nativo añade `Authorization: Bearer corte_native_v1_…` para la API
de negocio e imágenes. El gateway solo reenvía este formato exacto; los tokens
Google, Basic y otras cabeceras Authorization no pasan. La API valida el hash,
caducidad y revocación del dispositivo, y consulta el usuario Firebase vivo:
owner permitido, correo verificado, proveedor Google, no deshabilitado y sin
revocación posterior a la autorización Google que aprobó el dispositivo.

Todo `POST /api/cloud/import` con bearer exige además
`X-Corte-Expected-Creator: <open_id exacto>`: de 1 a 256 caracteres ASCII visibles,
sin espacios ni codificación adicional. El broker nativo obtiene ese OID mediante
`GET /api/native/session`; no lo entrega a JavaScript. El gateway solo reenvía
esta cabecera junto con un bearer nativo bien formado. El servidor adquiere el
mismo mutex de las mutaciones de cuenta, compara el OID vivo de la bóveda y
mantiene el mutex hasta terminar la importación. Si falta, es inválido, difiere o
no hay cuenta conectada, devuelve `409 cuenta_cambio_sin_importar`, sin escribir
ni devolver identificadores. Esto también se exige al importar un archivo desde
el diálogo de Windows. La importación manual del navegador con cookie conserva
su contrato actual y no necesita esta cabecera.

`GET /api/native/session` exige bearer y devuelve estado, device_id, expires_at y
owner. Puede incluir `tiktok_open_id` y `username`, exclusivamente para que el
broker nativo decida si una migración local corresponde a la misma cuenta.
**Estos identificadores nunca se trasladan al JavaScript de la UI local.** Un
username coincidente por sí solo no prueba que una copia antigua sea de esa cuenta.

`POST /api/native/devices/self/revoke {}` cierra el acceso del propio dispositivo.
Con cookie Google owner, `GET /api/native/devices` lista sus dispositivos y
`POST /api/native/devices/<device_id>/revoke {}` revoca uno. Un bearer no puede
aprobar otros dispositivos, listar/revocar los ajenos ni administrar sesiones
Google (`/api/cloud/login`, `/logout`, `/session`, `/config`).

Un `401 sesion_nativa_invalida` requiere reconectar. Un
`503 identidad_no_disponible` es un fallo temporal del proveedor: mantener la
credencial cifrada y la copia local; reintentar sin afirmar que fue revocada.

Los tokens solo existen en la respuesta HTTPS y en la memoria/almacén cifrado del
cliente. `native.sqlite`, dentro del volumen persistente existente, conserva
hashes SHA256 de tokens, HMAC de códigos/request_id, estados y metadatos de
dispositivos. No modifica credenciales ni IAM del proyecto Google compartido.

## OAuth de TikTok desde la app

Las llamadas bearer a `POST /api/auth/link` y `POST /api/display/conectar` registran
el hash del state generado, el callback exacto y el dispositivo que lo inició,
durante 10 minutos. Esto permite que el navegador externo vuelva sin cookie
Google únicamente a ese callback registrado, mientras el dispositivo y su owner
sigan autorizados. Los servicios originales siguen validando y consumiendo su
state de un solo uso y PKCE de Display. No se exponen otros endpoints anónimos.

## Datos sin conexión

Preservar copia/caché/cola nativas, op_id y revisiones. Los lotes siguen limitados
a 200 operaciones, pero además deben quedar por debajo de los 256 KB de la API
cloud; agrupar por bytes UTF-8, no solo por cantidad. El gateway limita respuestas
a 20 MB. El snapshot actual contiene órdenes recientes y una selección de videos;
no representa una réplica histórica completa de la SQLite original de Windows.
