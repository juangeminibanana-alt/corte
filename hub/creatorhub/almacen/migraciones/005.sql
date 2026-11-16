-- Migración user_version 4 -> 5 (rev. 5, 15/11/2026): métricas de TUS videos con la Display API de TikTok for Developers.
-- almacen.py la ejecuta dentro de UNA transacción, con copia previa hub.sqlite.bak-v4 (o bak-v3 si la base es de Corte
-- 1.0.0: 004.sql y 005.sql corren seguidas). Solo CREA tablas e índices: ninguna fila existente cambia. El texto de cada
-- tabla es EL MISMO que en schema.sql (lo comprueba hub/pruebas/test_sync_esquema_util.py).
--   videos_tiktok         uno por video PÚBLICO de la cuenta conectada (POST /v2/video/list/). video_id = content_id de
--                         las líneas de orders/search: así se cruzan vistas con ventas.
--   videos_tiktok_dias    foto diaria de las cifras de cada video (tendencia). Solo se agrega un día si alguna cifra cambió.
--   perfil_tiktok         la cuenta conectada (GET /v2/user/info/): seguidores, siguiendo, likes y número de videos.
--   perfil_tiktok_dias    foto diaria del perfil.
CREATE TABLE IF NOT EXISTS videos_tiktok (   -- POST /v2/video/list/ · solo videos públicos de la cuenta conectada
  video_id TEXT PRIMARY KEY,        -- id de la Display API = content_id de orden_lineas
  titulo TEXT,
  descripcion TEXT,                 -- video_description
  duracion_s INTEGER,
  creado_at INTEGER,                -- create_time
  share_url TEXT,
  embed_link TEXT,
  vistas INTEGER,                   -- view_count
  likes INTEGER,                    -- like_count
  comentarios INTEGER,              -- comment_count
  compartidos INTEGER,              -- share_count
  portada_url TEXT,                 -- cover_image_url: firmada, caduca en ~6 h; se baja a la caché como 'v:<video_id>'
  portada_url_at INTEGER,           -- cuándo se obtuvo esa URL
  visto_at INTEGER NOT NULL,        -- última sincronización en la que la API lo devolvió
  primera_vez_at INTEGER NOT NULL,
  actualizado_at INTEGER NOT NULL
) STRICT;
CREATE INDEX IF NOT EXISTS ix_videos_tiktok_creado ON videos_tiktok(creado_at);

CREATE TABLE IF NOT EXISTS videos_tiktok_dias (   -- foto diaria de las cifras de cada video (tendencia)
  video_id TEXT NOT NULL,
  fecha TEXT NOT NULL,              -- 'YYYY-MM-DD' en hora de México; la última lectura del día gana
  vistas INTEGER,
  likes INTEGER,
  comentarios INTEGER,
  compartidos INTEGER,
  actualizado_at INTEGER NOT NULL,
  PRIMARY KEY (video_id, fecha)
) STRICT;
CREATE INDEX IF NOT EXISTS ix_videos_tiktok_dias_fecha ON videos_tiktok_dias(fecha);

CREATE TABLE IF NOT EXISTS perfil_tiktok (   -- GET /v2/user/info/ · la cuenta conectada con la Display API
  id INTEGER PRIMARY KEY CHECK (id = 1),
  open_id TEXT,
  union_id TEXT,
  username TEXT,
  nombre TEXT,                      -- display_name
  bio TEXT,                         -- bio_description
  enlace_perfil TEXT,               -- profile_deep_link
  verificada INTEGER,               -- is_verified
  seguidores INTEGER,               -- follower_count
  siguiendo INTEGER,                -- following_count
  likes_total INTEGER,              -- likes_count
  videos_total INTEGER,             -- video_count
  actualizado_at INTEGER NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS perfil_tiktok_dias (   -- foto diaria del perfil (tendencia de seguidores y likes)
  fecha TEXT PRIMARY KEY,           -- 'YYYY-MM-DD' en hora de México
  seguidores INTEGER,
  siguiendo INTEGER,
  likes_total INTEGER,
  videos_total INTEGER,
  actualizado_at INTEGER NOT NULL
) STRICT;

PRAGMA user_version = 5;
