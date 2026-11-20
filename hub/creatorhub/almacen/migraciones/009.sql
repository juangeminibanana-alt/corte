-- Publicaciones que el creador confirmó para enviar a una hora determinada.
CREATE TABLE IF NOT EXISTS agenda_publicaciones_shop (
  id TEXT PRIMARY KEY,
  cuenta_sha256 TEXT NOT NULL,
  archivo_sha256 TEXT NOT NULL,
  file_id TEXT,
  datos_json TEXT NOT NULL CHECK (json_valid(datos_json)),
  programada_at INTEGER NOT NULL,
  consentida_at INTEGER NOT NULL,
  estado TEXT NOT NULL CHECK (estado IN ('programada','enviando','aceptada','cancelada','fallida','por_verificar')),
  intento TEXT,
  intento_at INTEGER,
  video_id TEXT,
  mensaje TEXT
) STRICT;
CREATE UNIQUE INDEX IF NOT EXISTS agenda_shop_archivo_activo ON agenda_publicaciones_shop(cuenta_sha256, archivo_sha256)
  WHERE estado NOT IN ('cancelada','fallida');
CREATE INDEX IF NOT EXISTS agenda_shop_turno ON agenda_publicaciones_shop(cuenta_sha256, estado, programada_at);
PRAGMA user_version = 9;
