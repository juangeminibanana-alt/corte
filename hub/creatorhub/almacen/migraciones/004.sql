-- Migración user_version 3 -> 4 (rev. 4, 15/11/2026): ficha completa de producto con la API oficial de afiliados.
-- almacen.py ejecuta cada sentencia dentro de UNA transacción, con copia previa hub.sqlite.bak-v3, y omite un
-- `ADD COLUMN` si la columna ya existe. El texto de cada tabla es EL MISMO que en schema.sql: el esquema migrado queda
-- idéntico al de una base nueva (lo comprueba hub/pruebas/test_sync_esquema_util.py).
--   1. imagenes: el CHECK de `tipo` admite 'g' (galería de vitrina) y 'm' (producto parecido del marketplace). SQLite no
--      cambia un CHECK en caliente: tabla nueva + copia de TODAS las filas + DROP + RENAME (sale "imagenes" entre
--      comillas, igual que en schema.sql) y sus dos índices otra vez. Ninguna vista ni llave foránea la referencia.
--   2. vitrina: precio con descuento de la plataforma y las fotos de la galería (los demás campos ya existían).
--   3. Tablas nuevas (todo de LECTURA de la API; nunca respuestas crudas): elegibilidad de muestra, solicitudes que solo
--      se conocen por su cumplimiento, planes dirigidos por tienda, parecidos del marketplace y origen de cada venta.
CREATE TABLE imagenes_rev4 (
  img_key TEXT PRIMARY KEY,         -- 'p:<product_id>' | 'v:<content_id>' | 'a:cuenta' | rev. 4: 'g:<product_id>-<n>' | 'm:<product_id>'
  tipo TEXT NOT NULL CHECK (tipo IN ('p','v','a','g','m')),   -- rev. 4: g = galería de vitrina, m = producto parecido
  ref_id TEXT NOT NULL,             -- ^\d{1,25}$ (o 'cuenta' para tipo a; '<product_id>-<n>' para g): se valida antes de armar rutas
  url_origen TEXT,
  url_huella TEXT,                  -- sha1(host + path) sin query volátil
  version TEXT,                     -- 8 hex de sha256(bytes originales) -> ?v= en la URL
  ruta_rel TEXT,                    -- relativa a cache/img/; extensión por formato detectado por Pillow (lista blanca)
  mime TEXT,
  ancho INTEGER,
  alto INTEGER,
  bytes INTEGER,
  lqip TEXT,                        -- data URI WebP de 16 px de ancho (≤ 600 B) para el blur-up (02_visual §8.3)
  color TEXT,                       -- '#rrggbb', promedio de 8×8 (pozo de color y halo del detalle)
  estado TEXT NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente','ok','error','bloqueada')),
  intentos INTEGER NOT NULL DEFAULT 0,
  ultimo_error TEXT,
  descargada_at INTEGER,
  ultimo_acceso_at INTEGER,         -- se acumula en memoria y se vuelca cada 60 s (no se escribe en cada /img)
  actualizado_at INTEGER NOT NULL
) STRICT;
INSERT INTO imagenes_rev4(img_key, tipo, ref_id, url_origen, url_huella, version, ruta_rel, mime, ancho, alto, bytes, lqip,
                          color, estado, intentos, ultimo_error, descargada_at, ultimo_acceso_at, actualizado_at)
  SELECT img_key, tipo, ref_id, url_origen, url_huella, version, ruta_rel, mime, ancho, alto, bytes, lqip,
         color, estado, intentos, ultimo_error, descargada_at, ultimo_acceso_at, actualizado_at FROM imagenes;
DROP TABLE imagenes;
ALTER TABLE imagenes_rev4 RENAME TO imagenes;
CREATE INDEX IF NOT EXISTS ix_img_estado ON imagenes(estado);
CREATE INDEX IF NOT EXISTS ix_img_acceso ON imagenes(ultimo_acceso_at);

ALTER TABLE vitrina ADD COLUMN precio_plat_min_centavos INTEGER;
ALTER TABLE vitrina ADD COLUMN precio_plat_max_centavos INTEGER;
ALTER TABLE vitrina ADD COLUMN galeria_json TEXT;

CREATE TABLE IF NOT EXISTS muestra_etiquetas (   -- GET samples/labels?product_id= · elegibilidad de muestra (TTL 72 h)
  product_id TEXT PRIMARY KEY,
  puede_solicitar INTEGER,          -- label.can_apply
  estado TEXT,                      -- label.status: UNKNOWN | TO_APPLY | ONGOING | COMPLETE
  application_id TEXT,              -- solo si ya la pediste
  limite_alcanzado INTEGER,         -- label.reach_limit
  skus_json TEXT NOT NULL DEFAULT '[]',   -- sample_sku_list normalizado (propiedades, precio en centavos, disponible, motivo)
  error_codigo TEXT,                -- la última consulta falló (se reintenta a las 24 h); lo de arriba es lo último bueno
  consultado_at INTEGER NOT NULL,
  huella TEXT,                      -- NULL = nunca hubo una respuesta buena
  actualizado_at INTEGER NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS solicitudes_recuperadas (   -- solicitudes que NO salen en sample_applications/search
  application_id TEXT PRIMARY KEY,  -- se recuperan con single_query usando el tipo de su cumplimiento
  product_id TEXT NOT NULL,
  fulfillment_id TEXT,
  tipo TEXT,                        -- FREE_SAMPLE | SAMPLE_COUPON
  sku_id TEXT,
  variante TEXT,                    -- sku_sale_property_value_names unidos con " / "
  main_order_id TEXT,               -- NULL si la API devolvió "0" o ""
  estado_api TEXT,
  solicitada_at INTEGER,            -- create_time (0 -> NULL)
  estado TEXT NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente','ok','error')),
  intentos INTEGER NOT NULL DEFAULT 0,
  reintento_at INTEGER,             -- espera creciente: 1, 2, 4… días (máx. 5 intentos)
  actualizado_at INTEGER NOT NULL
) STRICT;
CREATE INDEX IF NOT EXISTS ix_recuperadas_producto ON solicitudes_recuperadas(product_id);

CREATE TABLE IF NOT EXISTS colaboraciones_dirigidas (   -- POST target_collaborations/search {shop_id} (semanal)
  collab_id TEXT NOT NULL,
  product_id TEXT NOT NULL,
  shop_id TEXT NOT NULL,
  nombre TEXT,
  estado TEXT,                      -- LIVE | EXPIRED | DELETED | ENDED
  comision_bp INTEGER,              -- commission.rate en centésimas de % (= puntos base)
  comision_monto_centavos INTEGER,  -- commission.amount: estimada sobre el precio mínimo
  moneda TEXT,
  titulo TEXT,
  actualizado_at INTEGER NOT NULL,
  PRIMARY KEY (collab_id, product_id)
) STRICT;
CREATE INDEX IF NOT EXISTS ix_dirigidas_producto ON colaboraciones_dirigidas(product_id);
CREATE INDEX IF NOT EXISTS ix_dirigidas_tienda ON colaboraciones_dirigidas(shop_id);

CREATE TABLE IF NOT EXISTS dirigidas_tiendas (   -- última consulta de target_collaborations de cada shop_id
  shop_id TEXT PRIMARY KEY,
  planes INTEGER NOT NULL DEFAULT 0,
  error_codigo TEXT,                -- la última consulta falló (se reintenta a las 24 h)
  consultado_at INTEGER NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS productos_parecidos (   -- open_collaborations/products/search por palabras del título (TTL 7 días)
  product_id TEXT NOT NULL,         -- producto de la ficha
  parecido_id TEXT NOT NULL,
  posicion INTEGER NOT NULL,        -- orden en que lo devolvió TikTok (la relevancia la decide TikTok)
  titulo TEXT,
  tienda_nombre TEXT,
  imagen_url TEXT,
  precio_min_centavos INTEGER,      -- original_price (precio de lista)
  precio_max_centavos INTEGER,
  comision_bp INTEGER,
  comision_monto_min_centavos INTEGER,  -- commission.amount "a - b" = precio de venta × tasa
  comision_monto_max_centavos INTEGER,
  unidades_vendidas INTEGER,        -- units_sold global del producto
  enlace TEXT,                      -- detail_link (ver en TikTok Shop)
  PRIMARY KEY (product_id, parecido_id)
) STRICT;

CREATE TABLE IF NOT EXISTS parecidos_consultas (
  product_id TEXT PRIMARY KEY,
  palabras_json TEXT NOT NULL DEFAULT '[]',
  resultados INTEGER NOT NULL DEFAULT 0,
  error_codigo TEXT,                -- la última consulta falló (se reintenta a las 24 h)
  consultado_at INTEGER NOT NULL,
  huella TEXT
) STRICT;

CREATE TABLE IF NOT EXISTS orden_trazas (   -- POST orders/trace/search · origen de cada venta (pide un permiso extra)
  order_id TEXT NOT NULL,
  linea_n INTEGER NOT NULL,         -- posición de la SKU dentro del pedido, en el orden de la API
  sku_id TEXT,
  product_id TEXT,
  tipo_contenido TEXT,              -- SHOP VIDEO LIVE PRE_LIVE PROMOTION_PAGE LINKSHARE
  traza_tipo TEXT,                  -- trace.type: GENERAL | SPECIFIC (NULL = sin enlace compartido)
  creada_at INTEGER NOT NULL,
  actualizado_at INTEGER NOT NULL,
  PRIMARY KEY (order_id, linea_n)
) STRICT;
CREATE INDEX IF NOT EXISTS ix_trazas_producto ON orden_trazas(product_id);
CREATE INDEX IF NOT EXISTS ix_trazas_creada ON orden_trazas(creada_at);

PRAGMA user_version = 4;
