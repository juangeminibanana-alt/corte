-- Conserva todas las imágenes y añade el namespace de evidencia explícita.
CREATE TABLE imagenes_rev6 (
  img_key TEXT PRIMARY KEY,
  tipo TEXT NOT NULL CHECK (tipo IN ('p','v','a','g','m','e')),
  ref_id TEXT NOT NULL,
  url_origen TEXT,
  url_huella TEXT,
  version TEXT,
  ruta_rel TEXT,
  mime TEXT,
  ancho INTEGER,
  alto INTEGER,
  bytes INTEGER,
  lqip TEXT,
  color TEXT,
  estado TEXT NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente','ok','error','bloqueada')),
  intentos INTEGER NOT NULL DEFAULT 0,
  ultimo_error TEXT,
  descargada_at INTEGER,
  ultimo_acceso_at INTEGER,
  actualizado_at INTEGER NOT NULL
) STRICT;
INSERT INTO imagenes_rev6(img_key,tipo,ref_id,url_origen,url_huella,version,ruta_rel,mime,ancho,alto,bytes,lqip,color,
                          estado,intentos,ultimo_error,descargada_at,ultimo_acceso_at,actualizado_at)
  SELECT img_key,tipo,ref_id,url_origen,url_huella,version,ruta_rel,mime,ancho,alto,bytes,lqip,color,
         estado,intentos,ultimo_error,descargada_at,ultimo_acceso_at,actualizado_at FROM imagenes;
DROP TABLE imagenes;
ALTER TABLE imagenes_rev6 RENAME TO imagenes;
CREATE INDEX IF NOT EXISTS ix_img_estado ON imagenes(estado);
CREATE INDEX IF NOT EXISTS ix_img_acceso ON imagenes(ultimo_acceso_at);

CREATE TABLE IF NOT EXISTS producto_evidencia (
  product_id TEXT PRIMARY KEY,
  evidencia_json TEXT NOT NULL CHECK (length(evidencia_json) <= 196608 AND json_valid(evidencia_json)),
  rev INTEGER NOT NULL CHECK (rev >= 1),
  actualizado_at INTEGER NOT NULL
) STRICT;
PRAGMA user_version = 6;
