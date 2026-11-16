# 06 · TikTok for Developers y TikTok API for Business (cuentas)

Consulta de documentación: 15/11/2026. Solo se leyó documentación oficial; no se llamó a ninguna API real ni se abrió `config.json`.
Familia: Login Kit (OAuth v2), Display API, Content Posting API, Data Portability API, Research API (+ VCE), Commercial Content API (developers.tiktok.com) y Accounts API de TikTok API for Business v1.3 (business-api.tiktok.com).

## Resumen de la familia

- Estas APIs **no tienen relación con el token de TikTok Shop** (user_type=1, `open-api.tiktokglobalshop.com`). Hace falta una app aparte en developers.tiktok.com (client_key y client_secret propios) o en business-api.tiktok.com, y el creador tiene que autorizarla con su cuenta de TikTok. El `open_id` que se obtiene es distinto en cada app.
- ⭐ **Lo más útil para Corte es la Display API** (`/v2/user/info/`, `/v2/video/list/`, `/v2/video/query/`). Da la **portada real de cada video** (`cover_image_url`, caduca en 6 h), título, descripción, duración y vistas, likes, comentarios y compartidos por video. Hoy oEmbed ya no da miniatura, así que esto cubre ese hueco, y además permite cruzar vistas con pedidos usando el `content_id` de las órdenes.
- **Login Kit para escritorio** encaja con el hub de la PC: PKCE (la doc dice SHA-256 **en hex**), redirect a `http://127.0.0.1:*/callback/` con puerto comodín, access token de 2 h y refresh de 180 días con rotación. El intercambio del code pide `client_secret`, así que solo lo puede hacer el hub de Windows, nunca el APK.
- **Camino realista: Sandbox.** Admite hasta 10 cuentas «target user» y no requiere revisión. La revisión de producción dice que las apps «no deben ser para uso privado o personal», lo cual es un riesgo serio para Corte.
- **La Accounts API de Business** (`/business/get/`, `/business/video/list/`) da los datos más ricos: alcance, tiempo de visualización, % de video completo, fuentes de tráfico, audiencia por país, ciudad y género, y seguidores ganados por video. Pero exige registrarse como **desarrollador empresa** (correo con dominio propio y sitio web de empresa; la doc dice que no aceptan desarrolladores individuales) y llenar un formulario de acceso. Valor alto, pero el requisito es fuerte.
- **Content Posting API** tiene valor medio: permite subir los videos con IA desde la PC como borrador al inbox de TikTok. Sin auditoría solo publica en privado (SELF_ONLY). La doc no menciona cómo vincular productos de TikTok Shop.
- **No sirven en México:** Data Portability (solo usuarios del EEE y Reino Unido; los datos de TikTok Shop solo vienen en el archivo completo), Research API y VCE (solo académicos u organizaciones sin fines de lucro; creadores y usuarios comerciales no son elegibles; los datos de TikTok Shop son de tiendas de la UE) y Commercial Content API (solo datos de países europeos; México no está en la lista).

## Tabla de todos los endpoints

Leyenda «¿Sirve?»: **sí** · **req-T4D** = sí, con app de TikTok for Developers + Sandbox con la cuenta del creador (o producción aprobada) · **req-EMP** = sí, solo si Corte se registra como desarrollador empresa en TikTok API for Business y TikTok aprueba el scope «TikTok Accounts» · **no**.

| # | Nombre oficial | Método + path | Scope | ¿Sirve al creador? | Valor |
|---|---|---|---|---|---|
| 1 | Authorization request (Login Kit Desktop) | GET `https://www.tiktok.com/v2/auth/authorize/` | los que se pidan | req-T4D | medio (habilitador) |
| 2 | Get a User Access Token | POST `https://open.tiktokapis.com/v2/oauth/token/` (grant_type=authorization_code) | ninguno | req-T4D | medio (habilitador) |
| 3 | Refresh a User Access Token | POST `/v2/oauth/token/` (grant_type=refresh_token) | ninguno | req-T4D | medio (habilitador) |
| 4 | Revoke a User Access Token | POST `/v2/oauth/revoke/` | ninguno | req-T4D | bajo |
| 5 | Client access token | POST `/v2/oauth/token/` (grant_type=client_credentials) | ninguno (solo Research y Commercial Content) | no | ninguno |
| 6 | QR Code Authorization: get QR code | POST `/v2/oauth/get_qrcode/` | los que se pidan | req-T4D (plataforma Desktop sin confirmar) | medio |
| 7 | QR Code Authorization: check QR status | POST `/v2/oauth/check_qrcode/` | — | req-T4D (plataforma Desktop sin confirmar) | medio |
| 8 | ⭐ Get User Info | GET `/v2/user/info/` | user.info.basic / .profile / .stats | req-T4D | **alto** |
| 9 | ⭐ List Videos | POST `/v2/video/list/` | video.list | req-T4D | **alto** |
| 10 | ⭐ Query Videos | POST `/v2/video/query/` | video.list | req-T4D | **alto** |
| 11 | Query Creator Info | POST `/v2/post/publish/creator_info/query/` | video.publish | req-T4D + scope en revisión | bajo |
| 12 | Direct Post: init video | POST `/v2/post/publish/video/init/` | video.publish | req-T4D (sin auditoría: solo privado) | medio |
| 13 | Upload: init inbox video | POST `/v2/post/publish/inbox/video/init/` | video.upload | req-T4D | medio |
| 14 | Photo Post: init content | POST `/v2/post/publish/content/init/` | video.publish o video.upload | req-T4D | bajo |
| 15 | Get Post Status | POST `/v2/post/publish/status/fetch/` | video.upload / video.publish | req-T4D | medio |
| 16 | Send video (subida por partes) | PUT `{upload_url}` (open-upload.tiktokapis.com) | — | req-T4D | medio |
| 17 | Add Data Request | POST `/v2/user/data/add/` | portability.* | no (solo EEE/RU) | ninguno |
| 18 | Check Status of Data Request | POST `/v2/user/data/check/` | portability.* | no | ninguno |
| 19 | Cancel Data Request | POST `/v2/user/data/cancel/` | portability.* | no | ninguno |
| 20 | Download | POST `/v2/user/data/download/` | portability.* | no | ninguno |
| 21 | Query Videos (Research) | POST `/v2/research/video/query/` | research.data.basic | no | ninguno |
| 22 | Query User Info (Research) | POST `/v2/research/user/info/` | research.data.basic | no | ninguno |
| 23 | Query Video Comments | POST `/v2/research/video/comment/list/` | research.data.basic | no | ninguno |
| 24 | Query User Liked Videos | POST `/v2/research/user/liked_videos/` | research.data.basic | no | ninguno |
| 25 | Query User Pinned Videos | POST `/v2/research/user/pinned_videos/` | research.data.basic | no | ninguno |
| 26 | Query User Followers | POST `/v2/research/user/followers/` | research.data.basic | no | ninguno |
| 27 | Query User Following | POST `/v2/research/user/following/` | research.data.basic | no | ninguno |
| 28 | Query User Reposted Videos | POST `/v2/research/user/reposted_videos/` | research.data.basic | no | ninguno |
| 29 | Query Playlist Info | POST `/v2/research/playlist/info/` | research.data.basic | no | ninguno |
| 30 | Query TikTok Shop Info | POST `/v2/research/tts/shop/` | research.data.basic | no (tiendas de la UE) | ninguno |
| 31 | Query TikTok Shop Products | POST `/v2/research/tts/product/` | research.data.basic | no (UE) | ninguno |
| 32 | Query TikTok Shop Reviews | POST `/v2/research/tts/review/` | research.data.basic | no (UE) | ninguno |
| 33 | Create a batch compliance task | POST `/v2/research/validation_task/create/` | research.data.basic | no | ninguno |
| 34 | Get a batch compliance task status | POST `/v2/research/validation_task_status/get/` | research.data.basic | no | ninguno |
| 35 | Download a completed batch compliance task | POST `/v2/research/validation_task/download/` | research.data.basic | no | ninguno |
| 36 | Query Ads | POST `/v2/research/adlib/ad/query/` | research.adlib.basic | no (datos solo de Europa) | ninguno |
| 37 | Get Ad Details | POST `/v2/research/adlib/ad/detail/` | research.adlib.basic | no | ninguno |
| 38 | Get Ad Report | POST `/v2/research/adlib/ad/report/` | research.adlib.basic | no | ninguno |
| 39 | Query Advertisers | POST `/v2/research/adlib/advertiser/query/` | research.adlib.basic | no | ninguno |
| 40 | Query Commercial Content | POST `/v2/research/adlib/commercial_content/query/` | research.adlib.basic | no (creadores del EEE) | ninguno |
| 41 | TikTok account holder authorization URL | GET `https://www.tiktok.com/v2/auth/authorize?{parámetros}` (se copia de My Apps) | «TikTok Accounts» | req-EMP | medio (habilitador) |
| 42 | Obtain a TikTok account access token | POST `https://business-api.tiktok.com/open_api/v1.3/tt_user/oauth2/token/` | — | req-EMP | medio (habilitador) |
| 43 | Renew a TikTok account access token | POST `/open_api/v1.3/tt_user/oauth2/refresh_token/` | — | req-EMP | medio (habilitador) |
| 44 | Revoke a TikTok account access token | POST `/open_api/v1.3/tt_user/oauth2/revoke/` | — | req-EMP | bajo |
| 45 | Get the authorized TikTok account permission scopes | POST `/open_api/v1.3/tt_user/token_info/get/` | — | req-EMP | bajo |
| 46 | ⭐ Get profile data of a TikTok account | GET `/open_api/v1.3/business/get/` | user.info.* / user.insights / user.account.type | req-EMP | **alto** |
| 47 | ⭐ Get post data of a TikTok account | GET `/open_api/v1.3/business/video/list/` | video.list / video.insights | req-EMP | **alto** |
| 48 | Get benchmarks for a business category | GET `/open_api/v1.3/business/benchmark/` | no indicado | req-EMP | bajo |
| 49 | Get the post privacy settings | GET `/open_api/v1.3/business/video/settings/` | no indicado | req-EMP | bajo |
| 50 | Get comments on an owned video | GET `/open_api/v1.3/business/comment/list/` | no verificado | req-EMP | medio |
| 51 | Get all replies to a comment | GET `/open_api/v1.3/business/comment/reply/list/` | no verificado | req-EMP | bajo |
| 52 | Create a new comment | POST `/open_api/v1.3/business/comment/create/` | no verificado | req-EMP | bajo |
| 53 | Upload a comment image | POST `/open_api/v1.3/business/comment/image/upload/` | no verificado | req-EMP | bajo |
| 54 | Reply to an existing comment | POST `/open_api/v1.3/business/comment/reply/create/` | no verificado | req-EMP | bajo |
| 55 | Like/unlike a comment | POST `/open_api/v1.3/business/comment/like/` | no verificado | req-EMP | bajo |
| 56 | Hide/unhide a comment | POST `/open_api/v1.3/business/comment/hide/` | no verificado | req-EMP | bajo |
| 57 | Delete a comment | POST `/open_api/v1.3/business/comment/delete/` | no verificado | req-EMP | bajo |
| 58 | Publish a public video post | POST `/open_api/v1.3/business/video/publish/` | video.upload (borrador) / video.publish | req-EMP | medio |
| 59 | Publish a photo post | `/open_api/v1.3/business/photo/publish/` (método no verificado) | video.upload (borrador) | req-EMP | bajo |
| 60 | Get the publishing status | GET `/open_api/v1.3/business/publish/status/` | no verificado | req-EMP | bajo |
| 61 | Get recommended hashtags | GET `/open_api/v1.3/business/hashtag/suggestion/` | no verificado | req-EMP | medio |
| 62 | Get the location tags | GET `/open_api/v1.3/business/publish/location/` | no verificado | req-EMP | bajo |
| 63 | Enable/disable ad authorization of a post | POST `/open_api/v1.3/business/post/authorize/setting/` | biz.spark.auth | req-EMP | medio |
| 64 | Extend the authorization validity period | POST `/open_api/v1.3/business/post/authorize/` | no verificado (probable biz.spark.auth) | req-EMP | medio |
| 65 | Get the authorization status of a post | GET `/open_api/v1.3/business/post/authorize/status/` | no verificado | req-EMP | medio |
| 66 | Delete the authorization code of a post | POST `/open_api/v1.3/business/post/authorize/delete/` | no verificado | req-EMP | bajo |
| 67 | Add a URL property | POST `/open_api/v1.3/business/property/add/` | (app_id + secret) | req-EMP | bajo |
| 68 | Check the URL property verification | POST `/open_api/v1.3/business/property/verify/` | (app_id + secret) | req-EMP | bajo |
| 69 | Delete a verified URL property | POST `/open_api/v1.3/business/property/delete/` | (app_id + secret) | req-EMP | bajo |
| 70 | Get the list of URL properties | GET `/open_api/v1.3/business/property/list/` | (app_id + secret) | req-EMP | bajo |
| 71 | Create or update a Webhook configuration | POST `/open_api/v1.3/business/webhook/update/` | (app_id + secret) | req-EMP | bajo |
| 72 | Get Webhook configurations | GET `/open_api/v1.3/business/webhook/list/` | (app_id + secret) | req-EMP | bajo |
| 73 | Delete a Webhook configuration | POST `/open_api/v1.3/business/webhook/delete/` | (app_id + secret) | req-EMP | bajo |

Total: **73 endpoints**. Sin empresa, Corte puede usar 15 (los #1–4 y #6–16, de TikTok for Developers). Otros 33 (#41–73) solo con registro de empresa en Business. Los 25 restantes no aplican a un creador de México.

## Qué sirve a un creador de México (decisión rápida)

| Producto | ¿Disponible para Corte? | Qué daría | Requisito |
|---|---|---|---|
| Display API + Login Kit Desktop | **Sí** | Portadas reales, títulos, vistas, likes, comentarios y compartidos por video; seguidores, likes totales y número de videos del perfil | App en developers.tiktok.com con Login Kit (Desktop) + Display API; Sandbox con la cuenta del creador como target user (sin revisión). La revisión de producción tiene riesgo por la regla de «uso personal». |
| Content Posting API | Sí, limitado | Subir videos desde la PC como borrador al inbox de TikTok; estado de la publicación | Scope `video.upload` (o `video.publish`); sin auditoría solo privado; en Sandbox no hay posts públicos |
| Accounts API (Business) | Solo con empresa | Alcance, retención, % completado, fuentes de tráfico, audiencia por país, ciudad y género por video; métricas diarias de 60 días | Desarrollador empresa (correo con dominio y sitio web de empresa), formulario Accounts API, revisión de scopes de 2–3 días hábiles; algunos campos solo para cuentas Advanced Access o Verified Business |
| Data Portability | No | — | Solo usuarios del EEE y Reino Unido |
| Research API / VCE | No | — | Solo académicos u organizaciones sin fines de lucro; creadores y usuarios comerciales no son elegibles |
| Commercial Content API | No | — | Datos solo de países europeos |

---

# Fichas detalladas

## A. Login Kit / OAuth v2 (developers.tiktok.com)

Notas comunes:
- Host de API: `https://open.tiktokapis.com`. Errores OAuth: `{error, error_description, log_id}`.
- Es una app distinta de la de Partner Center: tiene su propio client_key y client_secret, y su token no sirve para TikTok Shop.
- **Tiempos de vida (verificado):** el access token dura **2 horas** (`expires_in`) y el refresh token **180 días** (`refresh_expires_in`). **El refresh token rota:** cada refresh devuelve uno nuevo, el anterior deja de servir y, si se sigue usando, hay que volver a autorizar. Fuente: https://developers.tiktok.com/doc/oauth-user-access-token-management
- La guía de Display API sugiere refrescar «cada 12 horas», lo cual no cuadra con un access token de 2 h. Conviene programar el refresh a partir de `expires_in`.
- **Sandbox (verificado):** hasta 5 sandboxes por app y hasta **10 target users**. Hay que ser dueño de cada cuenta, y cada una acepta los Términos para Desarrolladores. **No requiere revisión.** «Sandbox mode does not offer access to Content Posting API for public videos or Data Portability API». Una vez agregados, los target users pueden autorizar Login Kit y los productos que dependen de él. La configuración se puede importar a un Draft de producción. Fuente: https://developers.tiktok.com/docs/en/add-a-sandbox
- **Revisión de producción:** se pide un video de demostración, URLs verificadas de Términos, Privacidad y sitio, y la regla «Apps must not be for private or personal use». Fuentes: https://developers.tiktok.com/docs/en/getting-started-create-an-app · https://developers.tiktok.com/docs/en/app-review-guidelines
- Se puede registrar la app con una cuenta individual: una organización es «highly recommended but not required».

### A1. Authorization request (Login Kit Desktop)
- **Método/path:** GET `https://www.tiktok.com/v2/auth/authorize/` (se abre en el navegador del sistema).
- **Scope:** los que se pidan en `scope` (separados por coma); el usuario puede negar algunos.
- **Quién llama:** usuario de TikTok for Developers, o sea el creador autoriza la app.
- **Parámetros obligatorios:** `client_key`, `scope`, `redirect_uri` (idéntica a una registrada), `state` (anti-CSRF), `response_type=code`, `code_challenge`, `code_challenge_method=S256`.
- **PKCE:** `code_verifier` de 43 a 128 caracteres `[A-Za-z0-9-._~]`, nuevo en cada solicitud. La doc dice textualmente que hay que usar **codificación hex de SHA-256** para el challenge, cuando el estándar RFC 7636 usa base64url. Hay que probar cuál acepta TikTok. El generador del ejemplo usa `Math.random()`; usar CSPRNG.
- **Redirect para escritorio:** máximo 10 URIs, menos de 512 caracteres, absolutas, `http` o `https`, estáticas (sin parámetros ni fragmento). **Solo `localhost` o `127.0.0.1`**, con **puerto obligatorio**; se admite y recomienda el **comodín `*`** para puertos aleatorios. Ejemplos válidos: `http://localhost:3455/callback/`, `http://127.0.0.1:*/callback/`.
- **Respuesta (callback):** `code`, `scopes`, `state`; si falla, `error` y `error_description`.
- **Límites:** el ejemplo guarda `state` 60 s en cookie.
- **¿Sirve con la cuenta de Corte?** Sí, con requisito T4D. El hub de Windows abre el navegador, escucha en `127.0.0.1:{puerto}` y recibe el code sin que el usuario pegue URLs, cosa que hoy sí pasa con TikTok Shop.
- **Valor:** medio (habilitador de la Display API).
- **Fuente:** https://developers.tiktok.com/doc/login-kit-desktop

### A2. Get a User Access Token
- **Método/path:** POST `https://open.tiktokapis.com/v2/oauth/token/` · `Content-Type: application/x-www-form-urlencoded`.
- **Scope:** ninguno. **Quién llama:** el servidor de la app (el hub de la PC), porque lleva `client_secret`.
- **Parámetros:** `client_key`*, `client_secret`* (la doc no hace excepción para escritorio), `code`* (URL-decodificado), `grant_type=authorization_code`*, `redirect_uri`* (idéntica), `code_verifier` (**obligatorio en móvil y escritorio**).
- **Respuesta:** `access_token` (2 h), `expires_in`, `refresh_token`, `refresh_expires_in` (180 días), `open_id`, `scope` (lista con comas), `token_type=Bearer`.
- **¿Sirve?** Sí, con requisito T4D. El `client_secret` vive solo en el hub (DPAPI), igual que el app_secret de TikTok Shop.
- **Valor:** medio (habilitador).
- **Fuente:** https://developers.tiktok.com/docs/en/oauth-get-a-user-access-token

### A3. Refresh a User Access Token
- **Método/path:** POST `/v2/oauth/token/` (form-urlencoded).
- **Parámetros:** `client_key`*, `client_secret`*, `grant_type=refresh_token`*, `refresh_token`* (el más reciente).
- **Respuesta:** los mismos campos que A2. **Rota:** hay que guardar el nuevo `refresh_token` y reemplazar todos los valores. El refresh token vale 180 días desde que se emitió por primera vez.
- **¿Sirve?** Sí, con requisito T4D. **Valor:** medio. **Fuente:** https://developers.tiktok.com/docs/en/oauth-refresh-a-user-access-token

### A4. Revoke a User Access Token
- **Método/path:** POST `/v2/oauth/revoke/` (form-urlencoded). **Parámetros:** `client_key`*, `client_secret`*, `token`*.
- **Respuesta:** si sale bien, `{}`; si no, `error`, `error_description` y `log_id`. La app desaparece de las apps conectadas del usuario.
- **¿Sirve?** Sí, con requisito T4D (botón «Desconectar TikTok»). **Valor:** bajo. **Fuente:** https://developers.tiktok.com/docs/en/oauth-revoke-a-user-access-token

### A5. Client access token
- **Método/path:** POST `/v2/oauth/token/` con `grant_type=client_credentials`, `client_key` y `client_secret`.
- **Respuesta:** `access_token`, `expires_in=7200`, `token_type=Bearer`; no da refresh token. **Solo sirve para Research API y Commercial Content API.** Errores: `invalid_client`, `invalid_request`, `server_error`, `temporarily_unavailable`, `unauthorized_client`, `unsupported_grant_type`.
- **¿Sirve?** No, porque Corte no tiene acceso a esas APIs. **Valor:** ninguno. **Fuente:** https://developers.tiktok.com/docs/en/client-access-token-management

### A6–A7. QR Code Authorization
- **A6 · get QR:** POST `/v2/oauth/get_qrcode/` (form-urlencoded). Pide `client_key`* y `scope`*; `state` es opcional. Responde `scan_qrcode_url` (se le agrega `client_ticket`, que codificado mide menos de 512 caracteres) y `token`.
- **A7 · check:** POST `/v2/oauth/check_qrcode/`. Pide `client_key`*, `client_secret`* y `token`*. Responde `status` (`new`, `expired`, `scanned`, `confirmed`; el ejemplo también muestra `utilised`), `client_ticket`, `redirect_uri` y `code` cuando queda confirmado, y `state`.
- **Límites:** la vigencia del QR no está documentada (si sale `expired`, se pide otro QR) y no hay intervalo de consulta indicado.
- **¿Sirve?** Sí, con requisito T4D, pero **no verificado para apps Desktop**: la doc no dice qué plataformas lo admiten y su ejemplo es una app web. La experiencia sería ideal para Corte: la PC muestra el QR y el creador lo escanea con la app de TikTok en su teléfono.
- **Valor:** medio. **Fuente:** https://developers.tiktok.com/docs/en/login-kit-qr-code-authorization

---

## B. Display API ⭐ (developers.tiktok.com)

Notas comunes:
- Prerrequisito: «Approval for both a Login Kit and TikTok API products»; la guía usa `scope=user.info.basic,video.list`. Fuente: https://developers.tiktok.com/docs/en/display-api-get-started
- **Límite de tasa:** 600 solicitudes por minuto (ventana deslizante) **en cada endpoint**; al pasarse da HTTP 429 `rate_limit_exceeded`. Fuente: https://developers.tiktok.com/doc/tiktok-api-v2-rate-limit
- Errores v2: `access_token_invalid` (401), `scope_not_authorized` (401), `invalid_params` (400), `scope_permission_missed` (400), `rate_limit_exceeded` (429), `internal_error` (500). Fuente: https://developers.tiktok.com/docs/en/tiktok-api-v2-error-handling
- **Región:** la doc no menciona restricciones por país; no hay evidencia de que México quede fuera.
- **Sandbox:** la doc no lista la Display API de forma explícita, pero dice que Login Kit y los productos que dependen de él funcionan con target users. Falta confirmarlo creando el sandbox.

### B1. ⭐ Get User Info
- **Método/path:** GET `https://open.tiktokapis.com/v2/user/info/?fields=...` · header `Authorization: Bearer {access_token}`.
- **Quién llama:** usuario de TikTok for Developers (token del creador).
- **Parámetros:** `fields`* (lista con comas; solo regresan los campos que se pidan).
- **Campos por scope (verificado):**

| Campo | Tipo | Scope |
|---|---|---|
| `open_id` | string | user.info.basic |
| `union_id` | string (igual entre apps del mismo desarrollador) | user.info.basic |
| `avatar_url`, `avatar_url_100`, `avatar_large_url` | string | user.info.basic |
| `display_name` | string | user.info.basic |
| `bio_description` | string | user.info.profile |
| `profile_deep_link` | string | user.info.profile |
| `is_verified` | boolean | user.info.profile |
| `username` | string | user.info.profile |
| `follower_count` | int64 | user.info.stats |
| `following_count` | int64 | user.info.stats |
| `likes_count` | int64 (likes totales de todos sus videos) | user.info.stats |
| `video_count` | int64 (videos públicos) | user.info.stats |

- **Respuesta:** `data.user{...}` y `error{code, message, log_id}`.
- **Migración:** desde el 29/02/2024, pedir campos de profile o stats con solo `user.info.basic` da 401 `scope_not_authorized`. Fuente: https://developers.tiktok.com/bulletin/user-info-scope-migration
- **¿Sirve con la cuenta de Corte?** Sí, con requisito T4D (scopes `user.info.basic`, `user.info.profile`, `user.info.stats`).
- **Valor:** **alto**. Da seguidores, likes totales y número de videos públicos; guardando una foto diaria se obtiene el crecimiento de seguidores, que hoy no existe en Corte. Es confiable para conciliar el `username` con `perfil.json`.
- **Fuente:** https://developers.tiktok.com/doc/tiktok-api-v2-get-user-info

### B2. ⭐ List Videos
- **Método/path:** POST `https://open.tiktokapis.com/v2/video/list/?fields=...` · headers `Authorization: Bearer`, `Content-Type: application/json`.
- **Scope:** `video.list`. **Solo videos públicos.**
- **Parámetros:** `fields` en la query (campos del Video Object, ver B4). En el body, `cursor` (int64, timestamp UTC **en milisegundos**; se puede mandar uno propio para traer videos anteriores a esa fecha) y `max_count` (int32, **10 por defecto, máximo 20**).
- **Respuesta:** `data.videos[]` (Video Object), `data.cursor`, `data.has_more` y `error`.
- **Orden y paginación:** por `create_time` descendente; se pagina con `cursor` mientras `has_more` sea verdadero.
- **¿Sirve?** Sí, con requisito T4D.
- **Valor:** **alto**. Es el catálogo completo de videos públicos del creador con **portada real** (`cover_image_url`), título, descripción, duración, `create_time` y métricas (`view_count`, `like_count`, `comment_count`, `share_count`). Permite calcular **pedidos por cada 1,000 vistas** cruzando con `content_id` de `/affiliate_creator/202410/orders/search`, y detectar videos sin ventas. Como devuelve hasta 20 por página, un catálogo típico de videos con pedidos cabe en pocas páginas.
- **Fuente:** https://developers.tiktok.com/doc/tiktok-api-v2-video-list

### B3. ⭐ Query Videos
- **Método/path:** POST `https://open.tiktokapis.com/v2/video/query/?fields=...` · `Authorization: Bearer`, `Content-Type: application/json`.
- **Scope:** `video.list`.
- **Parámetros:** `fields`* en la query (valores permitidos: id, create_time, cover_image_url, share_url, video_description, duration, height, width, title, embed_html, embed_link, like_count, comment_count, share_count, view_count, is_aigc). En el body, `filters.video_ids`* con **hasta 20 IDs**.
- **Comportamiento:** comprueba que los videos sean del usuario autorizado y **puede renovar la vigencia de `cover_image_url`**.
- **Respuesta:** `data.videos[]` y `error`.
- **¿Sirve?** Sí, con requisito T4D.
- **Valor:** **alto**. Sirve para refrescar portadas (caducan en 6 h) y métricas de los videos con ventas, en lotes de 20 por `content_id`.
- **Fuente:** https://developers.tiktok.com/doc/tiktok-api-v2-video-query

### B4. Video Object (campos completos, verificado)

| Campo | Tipo | Nota |
|---|---|---|
| `id` | string | ID del video («item_id»). Debería ser el mismo número que `content_id` de las órdenes de afiliado; falta confirmarlo con datos reales |
| `create_time` | int64 | epoch UTC en **segundos** |
| `cover_image_url` | string | portada estática del CDN; **caduca en 6 h** (por políticas de confianza y seguridad) |
| `share_url` | string | enlace para compartir |
| `video_description` | string | máximo 150 caracteres |
| `duration` | int32 | segundos |
| `height`, `width` | int32 | — |
| `title` | string | máximo 150 caracteres |
| `embed_html` | string | HTML para incrustar |
| `embed_link` | string | enlace de inserción de tiktok.com |
| `like_count` | int32 | — |
| `comment_count` | int32 | — |
| `share_count` | int32 | — |
| `view_count` | int64 | — |
| `is_aigc` | bool | verdadero si el video está marcado como generado con IA (relevante: Corte hace UGC con IA) |

Fuente: https://developers.tiktok.com/doc/tiktok-api-v2-video-object

---

## C. Content Posting API (developers.tiktok.com)

Notas comunes:
- **Sin auditoría:** como máximo 5 usuarios pueden publicar en 24 h, la cuenta debe estar en **privado** al publicar y los posts quedan `SELF_ONLY`. La auditoría quita esa restricción.
- **Para todos:** hay un tope de creadores activos por cliente en 24 h y un límite por creador de «alrededor de 15 posts al día», compartido entre todos los clientes de Direct Post.
- **Requisitos de interfaz:** mostrar el nickname del creador; que el usuario elija la privacidad sin valor por defecto; interruptores de Comentarios, Duet y Stitch apagados por defecto; aviso de contenido comercial («Your brand» y «Branded content»); aceptar la Music Usage Confirmation; **no agregar marcas de agua**. Fuente: https://developers.tiktok.com/docs/en/content-sharing-guidelines
- **Sandbox:** no hay posts públicos.
- **La doc no menciona vincular productos de TikTok Shop** (ancla de producto) en ningún parámetro: **no verificado** que se pueda.
- **Restricciones de medios:** MP4, WebM o MOV; H.264, H.265, VP8 o VP9; de 23 a 60 FPS; de 360 a 4096 px; hasta 4 GB; partes de 5 a 64 MB (la última hasta 128 MB), entre 1 y 1000 partes, subidas en orden. Imágenes WebP o JPEG de hasta 1080p y 20 MB. `PULL_FROM_URL` exige HTTPS sin redirecciones y dominio verificado. Fuente: https://developers.tiktok.com/doc/content-posting-api-media-transfer-guide

### C1. Query Creator Info
- **Método/path:** POST `https://open.tiktokapis.com/v2/post/publish/creator_info/query/` · `Authorization: Bearer`, `Content-Type: application/json; charset=UTF-8`. El body va vacío.
- **Scope:** `video.publish`. **Límite:** 20 por minuto por token.
- **Respuesta:** `creator_avatar_url` (vale 2 h), `creator_username`, `creator_nickname`, `privacy_level_options` (cuenta pública: PUBLIC_TO_EVERYONE, MUTUAL_FOLLOW_FRIENDS, SELF_ONLY; cuenta privada: FOLLOWER_OF_CREATOR, MUTUAL_FOLLOW_FRIENDS, SELF_ONLY), `comment_disabled`, `duet_disabled`, `stitch_disabled`, `max_video_post_duration_sec`.
- **Errores:** `spam_risk_too_many_posts`, `spam_risk_user_banned_from_posting`, `reached_active_user_cap`, `access_token_invalid`, `scope_not_authorized`, `rate_limit_exceeded`.
- **¿Sirve?** Sí, con requisito T4D (el scope `video.publish` pasa por revisión). **Valor:** bajo. **Fuente:** https://developers.tiktok.com/docs/en/content-posting-api-reference-query-creator-info

### C2. Direct Post: init video
- **Método/path:** POST `/v2/post/publish/video/init/`. **Scope:** `video.publish`. **Límite:** 6 por minuto por token.
- **Body:** `post_info` lleva `privacy_level`* (tiene que estar en `privacy_level_options`), `title` (hasta 2200 runas UTF-16), `disable_duet`, `disable_stitch`, `disable_comment`, `video_cover_timestamp_ms`, `brand_content_toggle`, `brand_organic_toggle` e `is_aigc`. `source_info` lleva `source`* (`FILE_UPLOAD` o `PULL_FROM_URL`), `video_url`, `video_size`, `chunk_size` y `total_chunk_count`.
- **Respuesta:** `data.publish_id` (hasta 64 caracteres) y `data.upload_url` (solo con FILE_UPLOAD, **vale 1 h**).
- **Errores:** `invalid_param`, `spam_risk_too_many_posts`, `spam_risk_user_banned_from_posting`, `reached_active_user_cap`, `unaudited_client_can_only_post_to_private_accounts`, `url_ownership_unverified`, `privacy_level_option_mismatch`, `access_token_invalid`, `scope_not_authorized`, `rate_limit_exceeded`.
- **¿Sirve?** Sí, con requisito T4D y auditoría para publicar en público; sin auditoría solo privado. **Valor:** medio: publicar desde la PC con `is_aigc=true` y el aviso de contenido de marca.
- **Fuente:** https://developers.tiktok.com/doc/content-posting-api-reference-direct-post

### C3. Upload: init inbox video
- **Método/path:** POST `/v2/post/publish/inbox/video/init/`. **Scope:** `video.upload`. **Límite:** 6 por minuto por token.
- **Body:** `source_info` con `source`*, `video_size`, `chunk_size` y `total_chunk_count` (obligatorios con FILE_UPLOAD) o `video_url` (con PULL_FROM_URL).
- **Respuesta:** `publish_id` y `upload_url` (1 h). El usuario tiene que **tocar la notificación del inbox** para terminar el post en TikTok.
- **Límites:** `spam_risk_too_many_pending_share` permite **5 envíos pendientes en 24 h**.
- **¿Sirve?** Sí, con requisito T4D. Que funcione en Sandbox no está verificado: la doc solo excluye los «posts públicos». **Valor:** medio: mandar al teléfono, como borrador, el video con IA terminado en la PC, para que el creador agregue ahí el producto de TikTok Shop.
- **Fuente:** https://developers.tiktok.com/doc/content-posting-api-reference-upload-video

### C4. Photo Post: init content
- **Método/path:** POST `/v2/post/publish/content/init/`. **Scope:** `video.publish` (DIRECT_POST) o `video.upload` (MEDIA_UPLOAD). **Límite:** 6 por minuto.
- **Body:** `media_type=PHOTO`*, `post_mode`*, `post_info` (`title` de hasta 90 runas, `description` de hasta 4000, `privacy_level`, `disable_comment`, `auto_add_music`, `brand_content_toggle`, `brand_organic_toggle`), `source_info` (`source=PULL_FROM_URL`*, `photo_images`* con hasta 35 URLs verificadas y `photo_cover_index`*) e `is_aigc`.
- **Respuesta:** `publish_id`. **Error particular:** `app_version_check_failed` (MEDIA_UPLOAD pide TikTok 31.8 o superior).
- **¿Sirve?** Sí, con requisito T4D (exige dominio verificado para las URLs). **Valor:** bajo. **Fuente:** https://developers.tiktok.com/doc/content-posting-api-reference-photo-post

### C5. Get Post Status
- **Método/path:** POST `/v2/post/publish/status/fetch/`. **Scope:** `video.upload` o `video.publish`. **Límite:** 30 por minuto.
- **Body:** `publish_id`*.
- **Respuesta:** `status` (PROCESSING_UPLOAD, PROCESSING_DOWNLOAD, SEND_TO_USER_INBOX, PUBLISH_COMPLETE, FAILED), `fail_reason`, `publicaly_available_post_id[]` (así viene escrito en la doc; solo aparece si el post es público y pasó moderación), `uploaded_bytes` y `downloaded_bytes`.
- **¿Sirve?** Sí, con requisito T4D. **Valor:** medio: ligar el video recién publicado con su ID para después cruzarlo con órdenes. **Fuente:** https://developers.tiktok.com/doc/content-posting-api-reference-get-video-status

### C6. Send video (PUT a upload_url)
- **Método/path:** PUT a la `upload_url` completa (host `open-upload.tiktokapis.com`). **Headers:** `Content-Type` (video/mp4, video/quicktime o video/webm), `Content-Length` y `Content-Range: bytes {primero}-{último}/{total}`. El body es binario.
- **¿Sirve?** Sí, con requisito T4D. **Valor:** medio. **Fuente:** https://developers.tiktok.com/doc/content-posting-api-get-started y la referencia de Direct Post.

---

## D. Data Portability API (developers.tiktok.com)

Notas comunes:
- **Elegibilidad por región:** «available for TikTok users in the European Economic Area (EEA) or United Kingdom (UK)». El desarrollador tiene que poder distinguir a esos usuarios porque **la API no devuelve datos de usuarios fuera del EEE o Reino Unido**. Este texto viene del fragmento de búsqueda de https://developers.tiktok.com/products/data-portability-api; WebFetch recibió 403. El blog oficial de 2024 solo menciona el EEE: https://developers.tiktok.com/blog/2024-introducing-tiktok-data-portability-api
- Requiere aprobar Data Portability y también Login Kit (dos aprobaciones), con UX mockups; la revisión suele tardar de 3 a 4 semanas. **No está disponible en Sandbox.** Cuota: «1000 requests per minute» (la doc la llama diaria). Fuentes: https://developers.tiktok.com/docs/en/data-portability-api-get-started · https://developers.tiktok.com/docs/en/data-portability-api-faq
- **Scopes:** `portability.{all|postsandprofile|activity|directmessages}.{single|ongoing}`. Con un scope `.single`, la solicitud se puede crear una sola vez.
- **¿Incluye TikTok Shop? Sí, pero solo en el archivo completo (`all_data`):** comunicaciones con tiendas, información de pago, historial de soporte, disputas, **historial de pedidos**, navegación y reseñas de productos, reembolsos y devoluciones, direcciones, carrito y cupones. Son datos **del comprador**; no se mencionan comisiones de afiliado (lo más cercano es «Income and Wallet > Transaction History» con «Earnings»). La categoría Activity > «Purchases» solo trae regalos. Fuente: https://developers.tiktok.com/docs/en/data-portability-data-types
- **Para Corte (México): no aplica.**

### D1. Add Data Request
- POST `https://open.tiktokapis.com/v2/user/data/add/?fields=request_id` · `Authorization: Bearer`, `Content-Type: application/json`.
- **Body:** `data_format`* (`text` o `json`) y `category_selection_list`* (`all_data`, `video`, `profile`, `activity`, `direct_message`; `all_data` tiene prioridad).
- **Respuesta:** `data.request_id` (int64).
- **¿Sirve?** No (solo EEE/RU). **Valor:** ninguno. **Fuente:** https://developers.tiktok.com/docs/en/data-portability-api-add-data-request

### D2. Check Status of Data Request
- POST `/v2/user/data/check/?fields=request_id,apply_time,collect_time,status,data_format,category_selection_list`. **Body:** `request_id`*.
- **Respuesta:** `status` (`pending`, `downloading`, `expired`, `cancelled`), `apply_time`, `collect_time`, `data_format` y `category_selection_list`. Los datos caducan **4 días** después de quedar listos.
- **¿Sirve?** No. **Valor:** ninguno. **Fuente:** https://developers.tiktok.com/docs/en/data-portability-api-check-status-of-data-request

### D3. Cancel Data Request
- POST `/v2/user/data/cancel/`. **Body:** `request_id`. Responde `error{code: ok}`. Cancelar no termina el acceso «ongoing».
- **¿Sirve?** No. **Valor:** ninguno. **Fuente:** https://developers.tiktok.com/docs/en/data-portability-api-cancel-data-request

### D4. Download
- POST `/v2/user/data/download/`. **Body:** `request_id`*. La respuesta es un **ZIP en streaming**. Error documentado: `invalid_params` (400).
- **¿Sirve?** No. **Valor:** ninguno. **Fuente:** https://developers.tiktok.com/docs/en/data-portability-api-download

---

## E. Research API y VCE (developers.tiktok.com)

Notas comunes:
- **Elegibilidad:** instituciones académicas de EE. UU., EEE, Reino Unido, Canadá o Suiza; organizaciones sin fines de lucro o independientes de la UE; en Brasil, académicos u ONG que estudien seguridad juvenil. Hay que ser independiente de intereses comerciales y presentar revisión ética. Fuente: https://developers.tiktok.com/products/research-api
- **Los creadores, anunciantes y usuarios comerciales NO son elegibles** (el FAQ responde «No»). Cuota: 1000 solicitudes diarias y 100,000 registros al día; para followers y following, 20,000 llamadas y 2 millones de registros. Se reinicia a las 00:00 UTC. Los videos nuevos tardan hasta 48 h y las estadísticas hasta 10 días. Fuente: https://developers.tiktok.com/doc/research-api-faq
- **Token:** client access token (A5). **Scope:** `research.data.basic`. Hay otros scopes de investigación (`research.data.u18eu`, `research.data.vra`) listados en https://developers.tiktok.com/doc/tiktok-api-scopes
- **Datos de TikTok Shop:** solo «EU-based TikTok Shops» (página de producto); las respuestas de E10–E12 describen tiendas y productos «operating / available for purchase in the EU».
- **VCE (Virtual Compute Environment):** es un entorno seguro, **no un endpoint REST**: se consulta con un SDK de Python en notebook. Tiene una «Test Stage» con muestra aleatoria (la doc dice 5,000 registros diarios en un lugar y 100,000 en otro) y una etapa de ejecución en la que **solo salen resultados agregados**. Se abre a organizaciones no académicas sin fines de lucro «under limited conditions». Fuentes: https://developers.tiktok.com/docs/en/vce-getting-started · página de producto.
- **Para Corte: ninguno es usable.** Para todas las fichas de esta sección: ¿Sirve? **no** · Valor **ninguno**.

| # | Endpoint | Parámetros clave | Campos clave | Límites | Fuente |
|---|---|---|---|---|---|
| E1 | POST `/v2/research/video/query/` | `fields`*; `query`* (and/or/not con `field_name` en create_date, username, region_code, video_id, hashtag_name, keyword, music_id, effect_id, video_length, view_count, comment_count; operaciones EQ, IN, GT, GTE, LT, LTE); `start_date`* y `end_date`* (YYYYMMDD, **≤ 30 días**); `max_count` (20 por defecto, **100 máx.**); `cursor`; `search_id`; `is_random` | id, video_description, create_time, region_code, share/view/like/comment_count, music_id, hashtag_names, username, effect_ids, playlist_id, voice_to_text, is_stem_verified, favorites_count, video_duration, hashtag_info_list, sticker_info_list, effect_info_list, video_mention_list, video_label, video_tag | 100 por llamada | https://developers.tiktok.com/doc/research-api-specs-query-videos |
| E2 | POST `/v2/research/user/info/` | `fields`*; body `username` | display_name, bio_description, avatar_url, is_verified, follower_count, following_count, likes_count, video_count, bio_url | — | https://developers.tiktok.com/doc/research-api-specs-query-user-info |
| E3 | POST `/v2/research/video/comment/list/` | `fields`; `video_id` o `comment_id`; `max_count` (≤ 100); `cursor` | id, video_id, text, like_count, reply_count, parent_comment_id, create_time | datos personales tachados | https://developers.tiktok.com/docs/en/research-api-specs-query-video-comments |
| E4 | POST `/v2/research/user/liked_videos/` | `fields`; `username`*; `max_count` (≤ 100); `cursor` (segundos) | `user_liked_videos[]` (Video object de Research); `video_tag` marca IA (1, 2) y de marca (7 = «Creator Earns Commission», 1 = «Paid Partnership») | ≤ 100 | https://developers.tiktok.com/docs/en/research-api-specs-query-user-liked-videos |
| E5 | POST `/v2/research/user/pinned_videos/` | `fields`; `username`* | `pinned_videos_list[]` | sin paginación | https://developers.tiktok.com/docs/en/research-api-specs-query-user-pinned-videos |
| E6 | POST `/v2/research/user/followers/` | `username`*; `max_count` (≤ 100); `cursor` | `user_followers[]{display_name, username}` | ≤ 100 | https://developers.tiktok.com/docs/en/research-api-specs-query-user-followers |
| E7 | POST `/v2/research/user/following/` | igual que E6 | `user_following[]` | ≤ 100 | https://developers.tiktok.com/docs/en/research-api-specs-query-user-following |
| E8 | POST `/v2/research/user/reposted_videos/` | `fields`; `username`*; `max_count` (≤ 100); `cursor` | `user_reposted_videos[]` (el ejemplo usa `reposted_videos`) | ≤ 100 | https://developers.tiktok.com/docs/en/research-api-specs-query-user-reposted-videos |
| E9 | POST `/v2/research/playlist/info/` | `playlist_id`*; `cursor`; `max_count` (sin máximo documentado) | playlist_id, playlist_name, playlist_item_total, playlist_last_updated, playlist_video_ids, has_more, cursor | — | https://developers.tiktok.com/docs/en/research-api-specs-query-playlist-info |
| E10 | POST `/v2/research/tts/shop/` | `fields` (shop_name, shop_rating, shop_review_count, item_sold_count, shop_id; el ejemplo agrega shop_performance_value); `shop_name`; `limit` (≤ 10) | `data.shop_data[]` | **tiendas de la UE**; ≤ 10 | https://developers.tiktok.com/docs/en/research-api-specs-query-tiktok-shop-info |
| E11 | POST `/v2/research/tts/product/` | `fields` (product_id, product_sold_count, product_description, product_price, product_review_count, product_name, product_rating_1..5_count); `shop_id`; `page_start` (desde 1); `page_size` (≤ 10) | `data.product_data[]` | **productos a la venta en la UE**; ≤ 10 | https://developers.tiktok.com/docs/en/research-api-specs-query-tiktok-shop-products |
| E12 | POST `/v2/research/tts/review/` | `fields` (product_name, review_text, review_like_count, create_time, review_rating); `product_id`; `page_start`; `page_size` (≤ 10) | `data.review_data[]` | **UE**; ≤ 10 | https://developers.tiktok.com/docs/en/research-api-specs-query-tiktok-shop-reviews |
| E13 | POST `/v2/research/validation_task/create/` | form-data `file_data`* (hasta 10,000 IDs) y `category`* (`video` o `comment`) | `task_id` | 10,000 IDs | https://developers.tiktok.com/docs/en/batch-compliance-apis |
| E14 | POST `/v2/research/validation_task_status/get/` | `task_id`* | `task_status` (Completed, Processing, Failed) | — | ídem |
| E15 | POST `/v2/research/validation_task/download/` | `task_id`* | archivo de texto con los IDs válidos | el ejemplo de la doc apunta a la URL de status | ídem |

Quién llama en todas: un investigador aprobado, con client access token. Ninguna sirve a un creador.

---

## F. Commercial Content API (developers.tiktok.com)

Notas comunes:
- Está abierta «al público y a investigadores»: hace falta cuenta de desarrollador con correo oficial y una solicitud; la aprobación suele tardar 2 días hábiles. **Solo incluye datos de países de la UE** en esta fase, aunque quien consulta puede estar en cualquier país. Los anuncios quedan consultables hasta un año después de su última exhibición. Fuente: https://developers.tiktok.com/products/commercial-content-api
- **Países soportados:** los 27 de la UE más Noruega, Islandia, Liechtenstein, Reino Unido y Suiza. **México no está.** Fuente: https://developers.tiktok.com/docs/en/commercial-content-api-supported-countries
- **Token:** client access token. **Scope:** `research.adlib.basic`. No trae datos de TikTok Shop.
- **Para Corte:** ¿Sirve? **no** (no hay datos de México) · Valor **ninguno**.

| # | Endpoint | Parámetros clave | Campos clave | Límites | Fuente |
|---|---|---|---|---|---|
| F1 | POST `/v2/research/adlib/ad/query/` | `fields`* (ad.id, ad.first_shown_date y ad.last_shown_date son obligatorios; además ad.status, ad.status_statement, ad.videos, ad.image_urls, ad.reach, advertiser.business_id, advertiser.business_name, advertiser.paid_for_by); `filters.ad_published_date_range`* (min con antigüedad ≤ 1 año), `country_code_list`, `ad_type`, `ad_status`, `ad_reach`, `ages`, `gender`; `search_term` (≤ 50 caracteres); `search_type`; `max_count` (**≤ 10**); `search_id` | `ads[]{ad, advertiser}`, `has_more`, `search_id` | 10 por llamada | https://developers.tiktok.com/docs/en/commercial-content-api-query-ads |
| F2 | POST `/v2/research/adlib/ad/detail/` | `fields`* (ad.*, advertiser.*, ad_group.targeting_info); `ad_id`* | ad (reach con desglose por región, edad y género; rejection_info; call_to_action; …), advertiser (tiktok_account), ad_group.targeting_info | — | https://developers.tiktok.com/docs/en/commercial-content-api-get-ad-details |
| F3 | POST `/v2/research/adlib/ad/report/` | `fields=count_time_series_by_country`; `filters.ad_published_date_range`* (min posterior al 01/10/2022); `country_code`; `advertiser_business_ids` | `count_time_series_by_country{país: [{date, count}]}` | — | https://developers.tiktok.com/docs/en/commercial-content-api-get-ad-report |
| F4 | POST `/v2/research/adlib/advertiser/query/` | `fields` (business_name, business_id, country_code); `search_term`* (≤ 50 caracteres); `max_count` (≤ 50) | `advertisers[]` | 50 | https://developers.tiktok.com/docs/en/commercial-content-api-query-advertisers |
| F5 | POST `/v2/research/adlib/commercial_content/query/` | `fields` (id, create_timestamp, create_date, label, brand_names, creator, videos); `filters.content_published_date_range`* (min posterior al 01/10/2022); `creator_country_code` (**solo EEE**, sin RU ni CH); `creator_usernames`; `max_count` (≤ 50); `search_id` | `commercial_contents[]`, `has_more`, `search_id` | 50 | https://developers.tiktok.com/docs/en/commercial-content-api-query-commercial-content |

---

## G. TikTok API for Business: Accounts API v1.3 (business-api.tiktok.com)

Notas comunes (leídas del portal oficial; las páginas se generan con JS y se leyeron con el navegador integrado desde el mismo portal):
- **Qué es:** tres servicios para cuentas de TikTok: Insights (reportes), Moderation (comentarios) y Video Publishing. Usos autorizados: gestionar la presencia orgánica de **cuentas propias de marcas o creadores** (publicar, moderar, analizar insights de perfil y posts, autorizar posts para anuncios). **Uso prohibido:** juntar reportes de creadores autorizados para montar un programa propio de influencers afiliados (descubrimiento o ranking), y descargar o migrar videos. Fuente: https://business-api.tiktok.com/portal/docs?id=1737944384433218
- **Tipos de cuenta (términos oficiales):** General o Personal; «TikTok Account with Advanced Access» (se obtiene al vincular la cuenta con una cuenta de TikTok for Business o con un Business Center sin verificar); «Verified Business Account» (después de la verificación de negocio). **La autorización la da cualquier «TikTok organic account»**, pero algunos campos solo existen para Advanced Access o Verified Business (ver G6 y G7).
- **Requisitos del desarrollador (bloqueo principal):** cuenta de TikTok for Business, registro de desarrollador con **correo de dominio de empresa** y **sitio web de empresa**; la doc dice textualmente que por ahora no pueden dar de alta cuentas personales ni desarrolladores individuales. Además, desde el 20/03/2026 hay que llenar el **«Accounts API Access Application Form»** antes de pedir el scope «TikTok Accounts». Los cambios de permisos se revisan en 2 a 3 días hábiles. Fuentes: https://business-api.tiktok.com/portal/docs?id=1738855176671234 · https://business-api.tiktok.com/portal/docs?id=1738855280338946
- **Autorización:** se comparte la «TikTok account holder authorization URL» (de la forma `https://www.tiktok.com/v2/auth/authorize?{parámetros}`, opcionalmente con `&disable_auto_auth=1` y `state`). El **redirect URL** tiene que ser **https, sin puerto, sin query ni fragmento, terminar en `/`** y medir de 10 a 512 caracteres; se permiten hasta 10 por app. **No admite 127.0.0.1 con puerto**: el hub necesitaría una página https (como la de web.app que ya existe) y que el usuario pegue el code, igual que hoy con TikTok Shop. El `auth_code` vale **10 minutos** y se usa una sola vez. Fuentes: https://business-api.tiktok.com/portal/docs?id=1738083939371009 · https://business-api.tiktok.com/portal/docs?id=1832209711206401 · https://business-api.tiktok.com/portal/docs?id=1766042058952706
- **Tokens:** el access token dura **1 día** (`expires_in` 86400) y el refresh token **1 año** (`refresh_token_expires_in` 31536000). La doc no dice si el refresh token rota; conviene guardar siempre el que regrese. Fuente: https://business-api.tiktok.com/portal/docs?id=1738084387220481
- **Scopes que aparecen en el ejemplo de token:** message.list.manage, video.list, video.insights, user.insights, user.info.basic, comment.list, biz.brand.insights, biz.spark.auth, tcm.order.update, comment.list.manage, video.upload, video.publish, biz.ads.recommend, user.account.type, biz.creator.info, user.info.username, message.list.send, user.info.profile, user.info.stats, message.list.read, biz.creator.insights.
- **Límite de tasa:** **40 QPM por cuenta autorizada y por endpoint**; global por app: 600 QPM en nivel Basic y 1,000 en Advanced, Premium o Ultimate. Fuente: https://business-api.tiktok.com/portal/docs?id=1738084416214017
- **Latencia:** los datos «offline» (likes, audience_*, video_views, reach, …) llegan con **24 a 48 h** de retraso (UTC); username, share_url, thumbnail_url, etc. son en tiempo real. Fuente: https://business-api.tiktok.com/portal/docs?id=1746624508278786
- **Región:** la doc no restringe México ni lo confirma (**no verificado**). La FAQ dice que el alcance de un post depende de la región de la cuenta.
- **Quién llama en toda la sección:** un desarrollador empresa en TikTok API for Business con el token de cuenta de TikTok (header `Access-Token`), y `business_id` igual al `open_id`.

### G1. TikTok account holder authorization URL
- La URL se copia de My Apps → App Detail → Basic Information y tiene la forma `https://www.tiktok.com/v2/auth/authorize?{parámetros}` (los parámetros exactos no están desglosados en la doc). Agrega `state` y `disable_auto_auth=1`. Al volver, el redirect trae `auth_code` (y `state`).
- **¿Sirve?** Sí, con requisito EMP. **Valor:** medio (habilitador). **Fuente:** https://business-api.tiktok.com/portal/docs?id=1738083939371009

### G2. Obtain a TikTok account access token
- POST `https://business-api.tiktok.com/open_api/v1.3/tt_user/oauth2/token/` · `Content-Type: application/json`.
- **Body:** `client_id`*, `client_secret`*, `grant_type=authorization_code`*, `auth_code`* (10 min, un solo uso), `redirect_uri`*.
- **Respuesta:** `data.access_token` (1 día), `token_type=Bearer`, `scope`, `expires_in`, `refresh_token` (1 año), `refresh_token_expires_in`, `open_id`.
- **¿Sirve?** Sí, con requisito EMP. **Valor:** medio. **Fuente:** https://business-api.tiktok.com/portal/docs?id=1738084387220481

### G3. Renew a TikTok account access token
- POST `/open_api/v1.3/tt_user/oauth2/refresh_token/` (JSON). **Body:** `client_id`*, `client_secret`*, `grant_type=refresh_token`*, `refresh_token`*. Responde lo mismo que G2.
- **¿Sirve?** Sí, con requisito EMP. **Valor:** medio. **Fuente:** ídem.

### G4. Revoke a TikTok account access token
- POST `/open_api/v1.3/tt_user/oauth2/revoke/` (JSON). **Body:** `client_id`*, `client_secret`*, `access_token`*. Responde `code=0` con `data: {}`. El usuario también puede revocar desde la app: Configuración y privacidad → Seguridad → Administrar permisos de apps.
- **¿Sirve?** Sí, con requisito EMP. **Valor:** bajo. **Fuente:** ídem y https://business-api.tiktok.com/portal/docs?id=1776983576127490

### G5. Get the authorized TikTok account permission scopes
- POST `/open_api/v1.3/tt_user/token_info/get/`. Da `scope` (lista con comas) para el access token. Parámetros detallados no extraídos.
- **¿Sirve?** Sí, con requisito EMP. **Valor:** bajo. **Fuente:** https://business-api.tiktok.com/portal/docs?id=1765927978092545

### G6. ⭐ Get profile data of a TikTok account
- **Método/path:** GET `https://business-api.tiktok.com/open_api/v1.3/business/get/` (en v1.2 era POST) · header `Access-Token`.
- **Parámetros (en la URL):** `business_id`* (= open_id), `start_date` y `end_date` (YYYY-MM-DD en UTC; por defecto los últimos 7 días hasta ayer; **ventana máxima de 60 días hacia atrás**), `fields` (arreglo; por defecto `["display_name","profile_image"]`).
- **Campos y scope:**

| Campo | Scope | Restricción |
|---|---|---|
| `is_business_account`, `has_advanced_access` | user.account.type | — |
| `profile_image` (URL temporal con `x-expires`), `display_name` | user.info.basic | — |
| `username` | user.info.username | — |
| `profile_deep_link`, `bio_description`, `is_verified` | user.info.profile | — |
| `following_count`, `followers_count`, `total_likes`, `videos_count` | user.info.stats | — |
| `metrics[]` diarios: `date`, `video_views`, `profile_views`, `likes`, `comments`, `shares`, `followers_count` | user.insights | 24–48 h de retraso |
| `unique_video_views`, `daily_total_followers`, `daily_new_followers`, `daily_lost_followers`, `engaged_audience` | user.insights | **solo Advanced Access o Verified Business** |
| `audience_activity[]{hour, count}` | user.insights | Advanced Access o Verified Business **y ≥ 100 seguidores** |
| `phone_number_clicks`, `lead_submissions`, `app_download_clicks`, `bio_link_clicks`, `email_clicks`, `address_clicks` | user.insights | **solo Verified Business** |
| `audience_ages[]`, `audience_genders[]`, `audience_countries[]`, `audience_cities[]` (con porcentaje) | user.insights | **≥ 100 seguidores** |

- **Notas:** solo hay datos si el creador **activó TikTok Analytics** (publicó al menos un video y tocó «Activar»). `video_views` suma lo orgánico y lo pagado.
- **¿Sirve?** Sí, con requisito EMP; la mayoría de los campos funciona con cuenta personal.
- **Valor:** **alto**. Da vistas, visitas al perfil y likes **por día**, ganancia de seguidores y **demografía de la audiencia** (edad, género, país, ciudad). Corte podría cruzarlo con las comisiones diarias.
- **Fuente:** https://business-api.tiktok.com/portal/docs?id=1762228399168514

### G7. ⭐ Get post data of a TikTok account
- **Método/path:** GET `/open_api/v1.3/business/video/list/` · `Access-Token`.
- **Parámetros:** `business_id`*, `fields` (por defecto `["item_id"]`; si se piden varios, hay que incluir `item_id`), `filters.video_ids[]`, `filters.ad_post_only`, `cursor` (ms, por defecto ahora), `max_count` (**10 por defecto, máximo 20**; puede devolver menos aunque `has_more` sea verdadero).
- **Campos con `video.list`:** `item_id`, `media_type`, `is_ad`, `thumbnail_url` (temporal, con `x-expires`), `share_url`, `embed_url`, `caption`, `is_ai_generated`, `video_duration`, `likes`, `comments`, `shares` (incluye «Enviar a amigos»), `favorites`, `create_time`, `reach`, `video_views`.
- **Campos con `video.insights`:** `total_time_watched`, `average_time_watched`, `full_video_watched_rate`, `new_followers`, `video_view_retention[]{second, percentage}`, `impression_sources[]{impression_source, percentage}`, `audience_genders[]`, `audience_countries[]`, `audience_cities[]`, `audience_types[]`, `engagement_likes[]`. Además `profile_views` (solo Advanced Access o Verified Business) y `website_clicks`, `phone_number_clicks`, `lead_submissions`, `app_download_clicks`, `email_clicks`, `address_clicks` (solo Verified Business).
- **Respuesta:** `videos[]`, `cursor`, `has_more`. Las métricas son **de toda la vida del video** (sin el límite de 60 días).
- **Alcance:** posts públicos de video, foto o texto, incluidos los «Only show in ads».
- **¿Sirve?** Sí, con requisito EMP.
- **Valor:** **alto**. Es lo más completo para entender por qué un video vende: retención, % visto completo, fuentes de tráfico (FYP, perfil, búsqueda…), país y ciudad de quien lo vio y seguidores ganados por video. Junto con `content_id` de las órdenes, daría «retención contra pedidos».
- **Fuente:** https://business-api.tiktok.com/portal/docs?id=1762228421622786

### G8. Get benchmarks for a business category
- GET `/open_api/v1.3/business/benchmark/`. **Parámetros:** `business_id`* y `business_category`* (enum con 25 valores, por ejemplo `CLOTHING_AND_ACCESSORIES` y `SHOPPING_AND_RETAIL`).
- **Respuesta:** `average_likes`, `average_comments`, `average_shares`, `average_video_count`, `average_follower_count`, `average_follower_growth` (30 días), `average_engagement_rate` y `average_video_views`, todos **promedios de Verified Business Accounts** de la categoría.
- **Scope:** no indicado en la doc (**no verificado**). **¿Sirve?** Sí, con requisito EMP. **Valor:** bajo (comparación contra marcas, no contra creadores afiliados). **Fuente:** https://business-api.tiktok.com/portal/docs?id=1822388944791617

### G9. Get the post privacy settings
- GET `/open_api/v1.3/business/video/settings/` con `business_id`*. Responde `privacy_level_options`, `comment_disabled`, `duet_disabled`, `stitch_disabled` y más (sin leer completo).
- **Scope:** no indicado. **¿Sirve?** Sí, con requisito EMP. **Valor:** bajo. **Fuente:** https://business-api.tiktok.com/portal/docs?id=1816387951979521

### G10–G17. Comentarios sobre videos propios
- **G10 · GET `/open_api/v1.3/business/comment/list/`:** `business_id`*, `video_id`*, `comment_ids`, `include_replies`, `status`, `sort_field`, `sort_order`, `cursor`, `max_count`. Responde `comments[]{comment_id, video_id, user_id (en desuso), unique_identifier, create_time, text, likes, replies, owner, liked, pinned, status, username, display_name, profile_image, parent_comment_id, reply_list[], image_url}`, `cursor` y `has_more`. Incluye comentarios públicos y ocultos.
- **G11 · GET `/business/comment/reply/list/`:** `business_id`*, `video_id`*, `comment_id`*.
- **G12 · POST `/business/comment/create/`:** `business_id`*, `video_id`*.
- **G13 · POST `/business/comment/image/upload/`:** `image_file`* y devuelve `image_uri`.
- **G14 · POST `/business/comment/reply/create/`:** `business_id`*, `video_id`*, `comment_id`*.
- **G15 · POST `/business/comment/like/`:** `business_id`*, `comment_id`*, `action`*.
- **G16 · POST `/business/comment/hide/`:** `business_id`*, `comment_id`*, `video_id`*, `action`*.
- **G17 · POST `/business/comment/delete/`:** `business_id`*, `comment_id`* (solo comentarios propios).
- **Scope:** **no verificado**. En el ejemplo de token aparecen `comment.list` y `comment.list.manage`, pero no se confirmó qué endpoint pide cuál.
- **¿Sirve?** Sí, con requisito EMP. **Valor:** G10 medio (ver qué preguntan los compradores en los videos con ventas: talla, envío); el resto bajo.
- **Fuentes:** https://business-api.tiktok.com/portal/docs?id=1760232109619202 y los doc_id 1762228430145538, 1762228442072066, 1856212334897154, 1762228448779266, 1762228456608770, 1762228474532865 y 1762228483080193 (formato `https://business-api.tiktok.com/portal/docs?id={doc_id}`).

### G18–G22. Publicación
- **G18 · POST `/open_api/v1.3/business/video/publish/`:** `business_id`*, `video_url`*, `custom_thumbnail_url`, `post_info`* (`caption`, `is_brand_organic`, `is_branded_content`, `tto_invite_link`, `disable_comment`, `disable_duet`, `disable_stitch`, `thumbnail_offset`, `is_ai_generated`, `upload_to_draft`, `location_id`, `location_name`, `is_ads_only`, `music_sound_info{…}`). Con `upload_to_draft=true` (requiere `video.upload`) se ignoran los demás campos de `post_info` y el borrador llega al inbox. **No se vio ningún campo para vincular productos de TikTok Shop.** El scope para publicar en público no se confirmó; probablemente es `video.publish`.
- **G19 · `/open_api/v1.3/business/photo/publish/`:** `business_id`*, `photo_images`*, `post_info`* (`is_draft` requiere `video.upload`). **Método no verificado** (la extracción no lo encontró).
- **G20 · GET `/business/publish/status/`:** `business_id`*, `publish_id`*; responde `status`, `post_ids[]` y `reason`.
- **G21 · GET `/business/hashtag/suggestion/`:** `business_id`*, `keyword`*; devuelve hashtags recomendados.
- **G22 · GET `/business/publish/location/`:** `business_id`*, `search_query`*; devuelve etiquetas de ubicación.
- **¿Sirve?** Sí, con requisito EMP. **Valor:** G18 y G21 medio (publicar o enviar borradores de los videos con IA desde la PC y sugerir hashtags por producto); los demás bajo.
- **Fuentes:** doc_id 1762228496095234, 1803630424390658, 1816387106635778, 1762228503821314 y 1870580030749698.

### G23–G26. Autorización de posts para anuncios (Spark Ads)
- **G23 · POST `/business/post/authorize/setting/`:** `business_id`*, `item_id`*, `is_ad_promotable`*. Scope `biz.spark.auth`.
- **G24 · POST `/business/post/authorize/`:** `business_id`*, `item_id`*; amplía la vigencia de un código existente.
- **G25 · GET `/business/post/authorize/status/`:** `business_id`*, `item_id`*.
- **G26 · POST `/business/post/authorize/delete/`:** `business_id`*, `item_id`*.
- **Scope de G24–G26:** no verificado (probable `biz.spark.auth`).
- **¿Sirve?** Sí, con requisito EMP. **Valor:** medio. Las tiendas suelen pedir a los afiliados códigos de autorización para anunciar sus videos; esto permitiría ver y renovar esos permisos desde Corte. Es una inferencia de uso, no algo que diga la doc.
- **Fuentes:** doc_id 1815051741912066, 1815051784582210, 1815051801257986 y 1815051817073665.

### G27–G30. Propiedades de URL (para publicar con video_url)
- POST `/business/property/add/`, POST `/business/property/verify/`, POST `/business/property/delete/` y GET `/business/property/list/`. Se autentican con `app_id` y `secret` (no con el token de cuenta); add usa `url_property_meta`.
- **¿Sirve?** Sí, con requisito EMP y dominio propio. **Valor:** bajo.
- **Fuentes:** doc_id 1769325280876545, 1769325308162050, 1769325351919617 y 1769325368603650.

### G31–G33. Webhooks de cuentas
- POST `/business/webhook/update/` (`app_id`*, `secret`*, `event_type`*, `callback_url`*), GET `/business/webhook/list/` y POST `/business/webhook/delete/`. Los eventos son de publicación de posts y de comentarios (`comment.update`). El hub de la PC no tiene URL pública, así que no aplica sin un servidor.
- **¿Sirve?** Sí, con requisito EMP y servidor público. **Valor:** bajo.
- **Fuentes:** doc_id 1810521279479810, 1810521289122818 y 1810521297052673.

---

## Huecos y datos no verificados

1. **Display API en Sandbox:** la doc no la menciona de forma explícita; solo dice que funcionan Login Kit y sus productos dependientes, y excluye Content Posting público y Data Portability. Se confirma creando el sandbox.
2. **Producción de TikTok for Developers:** la regla «Apps must not be for private or personal use» probablemente impide aprobar Corte como app pública. Hay que planear sobre Sandbox (hasta 10 cuentas). La doc **no documenta** si los tokens o sandboxes caducan.
3. **PKCE en hex vs base64url:** la doc de Login Kit Desktop dice hex SHA-256, que se aparta del RFC. Probar ambas al implementar.
4. **QR Code Authorization para apps Desktop:** la doc no dice qué plataformas lo admiten.
5. **Cruce `id` (Display) ↔ `content_id` (órdenes de afiliado):** ambos son IDs de video de TikTok (oEmbed usaba `/video/{content_id}`), pero no se comprobó con datos reales.
6. **Guardar en caché portadas (`cover_image_url`, TTL 6 h):** la doc no dice si se puede guardar la imagen en disco; solo indica que la URL caduca y se renueva con `/v2/video/query/`.
7. **Content Posting y Business publish:** no hay campo documentado para anclar productos de TikTok Shop. Tampoco se sabe si el inbox upload (C3) funciona en Sandbox.
8. **Accounts API de Business:** disponibilidad en México no documentada; desarrolladores individuales no aceptados; scopes de los endpoints de comentarios (G10–G17), de publicación (G20–G22) y de Spark (G24–G26) sin confirmar; método de G19 sin confirmar; tampoco se sabe si el refresh token rota.
9. **Data Portability:** la página de producto dio 403 con WebFetch; el texto «EEA or UK» viene del fragmento de búsqueda de esa misma página oficial y coincide con el blog oficial (que solo menciona el EEE).
10. **Research API:** sin límite documentado de `max_count` en playlist; la restricción a la UE de los endpoints de TikTok Shop sale de la descripción de la respuesta, no de una regla explícita.
11. **Fuente 2 (spec OpenAPI de isaackogan/TikTok-Shop-Api-SDKs):** no aplica a esta familia porque cubre el Partner API de TikTok Shop, no developers.tiktok.com ni business-api. No se consultó.
12. **Docs locales** (`research/tiktok-docs/*.txt`): no contienen nada de esta familia (búsqueda sin resultados).

## Fuentes

developers.tiktok.com:
- https://developers.tiktok.com/doc/tiktok-api-v2-get-user-info
- https://developers.tiktok.com/bulletin/user-info-scope-migration
- https://developers.tiktok.com/doc/tiktok-api-v2-video-list
- https://developers.tiktok.com/doc/tiktok-api-v2-video-query
- https://developers.tiktok.com/doc/tiktok-api-v2-video-object
- https://developers.tiktok.com/doc/display-api-overview · https://developers.tiktok.com/docs/en/display-api-get-started
- https://developers.tiktok.com/doc/tiktok-api-v2-rate-limit · https://developers.tiktok.com/docs/en/tiktok-api-v2-error-handling
- https://developers.tiktok.com/doc/tiktok-api-scopes
- https://developers.tiktok.com/doc/login-kit-desktop · https://developers.tiktok.com/docs/en/login-kit-overview · https://developers.tiktok.com/docs/en/login-kit-qr-code-authorization
- https://developers.tiktok.com/doc/oauth-user-access-token-management · https://developers.tiktok.com/docs/en/oauth-get-a-user-access-token · https://developers.tiktok.com/docs/en/oauth-refresh-a-user-access-token · https://developers.tiktok.com/docs/en/oauth-revoke-a-user-access-token · https://developers.tiktok.com/docs/en/client-access-token-management
- https://developers.tiktok.com/docs/en/add-a-sandbox · https://developers.tiktok.com/docs/en/getting-started-create-an-app · https://developers.tiktok.com/docs/en/app-review-guidelines
- https://developers.tiktok.com/doc/content-posting-api-get-started · https://developers.tiktok.com/doc/content-posting-api-reference-direct-post · https://developers.tiktok.com/doc/content-posting-api-reference-upload-video · https://developers.tiktok.com/doc/content-posting-api-reference-get-video-status · https://developers.tiktok.com/docs/en/content-posting-api-reference-query-creator-info · https://developers.tiktok.com/doc/content-posting-api-reference-photo-post · https://developers.tiktok.com/doc/content-posting-api-media-transfer-guide · https://developers.tiktok.com/docs/en/content-sharing-guidelines
- https://developers.tiktok.com/doc/data-portability-api-get-started · https://developers.tiktok.com/docs/en/data-portability-api-add-data-request · https://developers.tiktok.com/docs/en/data-portability-api-check-status-of-data-request · https://developers.tiktok.com/docs/en/data-portability-api-cancel-data-request · https://developers.tiktok.com/docs/en/data-portability-api-download · https://developers.tiktok.com/docs/en/data-portability-data-types · https://developers.tiktok.com/docs/en/data-portability-api-faq · https://developers.tiktok.com/docs/en/data-portability-api-application-guidelines · https://developers.tiktok.com/products/data-portability-api (fragmento de búsqueda) · https://developers.tiktok.com/blog/2024-introducing-tiktok-data-portability-api
- https://developers.tiktok.com/products/research-api · https://developers.tiktok.com/doc/research-api-get-started · https://developers.tiktok.com/doc/research-api-faq · https://developers.tiktok.com/docs/en/about-research-api · https://developers.tiktok.com/docs/en/vce-getting-started · las referencias `research-api-specs-*` y `batch-compliance-apis` citadas en cada fila
- https://developers.tiktok.com/products/commercial-content-api · https://developers.tiktok.com/docs/en/commercial-content-api-getting-started · `commercial-content-api-query-ads`, `-get-ad-details`, `-get-ad-report`, `-query-advertisers`, `-query-commercial-content`, `-supported-countries`

business-api.tiktok.com (portal v1.3; formato `https://business-api.tiktok.com/portal/docs?id={doc_id}`):
- https://business-api.tiktok.com/portal/docs/organic-api-overview/v1.3 · https://business-api.tiktok.com/portal/docs/accounts-api/v1.3
- Overview 1737944384433218 · Authorization 1738083939371009 · Authorization FAQs 1766042058952706 · Redirect URL 1832209711206401 · Authentication 1738084387220481 · Rate limits 1738084416214017 · Data latency 1746624508278786 · FAQs 1776983576127490 · Register as developer 1738855176671234 · App permissions 1738855280338946
- Referencia: 1765927978092545, 1762228399168514, 1762228421622786, 1822388944791617, 1816387951979521, 1760232109619202, 1762228430145538, 1762228442072066, 1856212334897154, 1762228448779266, 1762228456608770, 1762228474532865, 1762228483080193, 1762228496095234, 1803630424390658, 1816387106635778, 1762228503821314, 1870580030749698, 1815051741912066, 1815051784582210, 1815051801257986, 1815051817073665, 1769325280876545, 1769325308162050, 1769325351919617, 1769325368603650, 1810521279479810, 1810521289122818, 1810521297052673

Local: notas internas de contexto de Corte (no se publican; las docs locales de `tiktok-docs\` tampoco cubren esta familia).
