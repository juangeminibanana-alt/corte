-- Historial mínimo de envíos de videos comprables, aislado por cuenta.
CREATE TABLE IF NOT EXISTS publicaciones_shop (
  cuenta_sha256 TEXT NOT NULL,
  archivo_sha256 TEXT NOT NULL,
  solicitud_sha256 TEXT NOT NULL,
  iniciado_at INTEGER NOT NULL,
  resultado_json TEXT CHECK (resultado_json IS NULL OR json_valid(resultado_json)),
  PRIMARY KEY (cuenta_sha256, archivo_sha256)
) STRICT;
PRAGMA user_version = 8;
