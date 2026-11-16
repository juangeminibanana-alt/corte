"""Cliente de la API de TikTok Shop (hub-nucleo; BUILD_SPEC §3.1, 03 §2.1).

- `firma`: HMAC-SHA256 idéntica a `server_anterior.generate_sign` (verificado en 200 casos).
- `transporte`: HTTPS con `urllib.request` (timeouts 10/30 s, TLS por defecto, solo hosts de TikTok, sin redirecciones).
- `politica`: tabla POLITICA de 03 §2.1 (configurable).
- `conexion`: fila `auth_estado`, `Conexion` y `Cuenta` del contrato (compartido por cliente y auth).
- `cliente`: `crear_cliente(...)` → ClienteTikTok (cubeta de 5 req/s, backoff, refresh single-flight, disyuntor, desfase).

El paquete no importa sus submódulos al cargarse (arranque rápido, C3).
"""
from __future__ import annotations
