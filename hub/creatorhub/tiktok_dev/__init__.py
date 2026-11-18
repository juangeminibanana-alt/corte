"""Display API de TikTok for Developers (rev. 5, 15/11/2026): métricas de los videos PROPIOS del creador.

Es OTRA app, distinta de la de TikTok Shop (Partner Center): Login Kit de escritorio con PKCE, redirect
`http://127.0.0.1:<puerto del hub>/oauth/tiktok` y los scopes user.info.basic, user.info.profile, user.info.stats y
video.list. Todo es de LECTURA.

- `pkce`: verifier de 43–128 caracteres [A-Za-z0-9-._~], code_challenge = SHA-256 del verifier en HEX (escritorio) y
  state aleatorio.
- `errores`: `ErrorDisplay` (código corto + mensaje en español; nunca el texto de TikTok ni un secreto).
- `boveda`: `BovedaDisplay` = la misma bóveda DPAPI de TikTok Shop (sobre + .nuevo + fsync + os.replace, generación,
  archivo ilegible apartado) con su propio archivo `<secretos>\\tiktok_display.dpapi` y su propia entropía.
- `cliente`: `ClienteDisplay` con transporte INYECTADO: canje del code, refresh single-flight con rotación del
  refresh_token (se guarda de inmediato y de forma atómica), revocación, user/info, video/list paginado y video/query
  dirigida (1 a 20 videos propios por ID, en texto).
- `datos`: normalización de las respuestas y escritura en las tablas de la migración 005 (sin red).
- `servicio`: `ServicioDisplay` (estado, credenciales, inicio de conexión, callback /oauth/tiktok, desconexión).
- `demo`: transporte falso del modo demo (perfil y videos sintéticos de la identidad de demo, coherentes con sus ventas).

El paquete no importa sus submódulos al cargarse (arranque rápido, C3).
"""
from __future__ import annotations
