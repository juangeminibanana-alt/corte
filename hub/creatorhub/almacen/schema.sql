-- =====================================================================================
-- Corte (creator-hub) · esquema SQLite rev. 9 · user_version = 9 (BUILD_SPEC §4.3; 03 §3.3)
-- rev. 5 (005.sql): tablas de la Display API · rev. 6 (006.sql): evidencia de producto · rev. 7 (007.sql): la tabla
-- orden_lineas_traza (trace_info de orders/search 202410). Lo que sigue describe la base de la rev. 4.
-- Es spec/verificacion/schema.sql (v1, transcrito en 03 §3.1) con los cambios de la rev. 3.1 y de la rev. 4, y nada más:
--   1. videos.portada_product_id TEXT (C4: portada = foto del producto con más pedidos válidos del video);
--   2. muestras.en_cohorte_desde_at INTEGER (primera vez que la clasificación FINAL la vio pendiente; nunca se borra);
--   3. rev. 4 (ficha completa de producto, migraciones/004.sql): imagenes admite los tipos 'g' (galería de vitrina) y
--      'm' (producto parecido); vitrina.precio_plat_min/max_centavos y vitrina.galeria_json; tablas muestra_etiquetas,
--      solicitudes_recuperadas, colaboraciones_dirigidas, dirigidas_tiendas, productos_parecidos, parecidos_consultas
--      y orden_trazas (todo de LECTURA de la API oficial de afiliados);
--   4. user_version = 4. Las semillas de meta (host_id, data_version, local_rev, img_rev, dv_pendiente, epoca_datos,
--      tz_offset_s) las inserta almacen.py; las 11 plantillas y las preferencias NO: solo EstadoLocal.sembrar().
-- Las columnas nuevas van al FINAL de su tabla y con el mismo texto que deja SQLite tras `ALTER TABLE … ADD COLUMN`
-- (", <columna>) STRICT"); `imagenes` va entre comillas como la deja `ALTER TABLE … RENAME TO` al reconstruirla. Así
-- sqlite_master es idéntico al de una base v1/1.0.0 migrada (migraciones/002.sql, 003.sql y 004.sql) y al de
-- hub/pruebas/util.base_de_prueba() (lo comprueba test_sync_esquema_util).
-- SQLite >= 3.37 (STRICT) y >= 3.25 (funciones de ventana). En el venv: 3.49.1.
-- Abrir SIEMPRE con: PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON; PRAGMA synchronous=NORMAL;
--                    PRAGMA busy_timeout=5000;  y verificar PRAGMA user_version.
-- Convenciones: tiempos = epoch UTC en segundos (INTEGER, sufijo _at); fechas locales 'YYYY-MM-DD' (TEXT);
--               dinero = centavos MXN (INTEGER, sufijo _centavos); tasas = puntos base (INTEGER, sufijo _bp, 800 = 8 %).
-- Los SECRETOS (app_secret, tokens, claves de dispositivos en claro, llave TLS) NUNCA viven aquí.
-- =====================================================================================

-- ------------------------------------------------------------------ configuración
CREATE TABLE IF NOT EXISTS meta (
  clave TEXT PRIMARY KEY,           -- host_id, data_version, local_rev, dv_pendiente, epoca_datos, tz_offset_s, modo,
                                    -- legado_importado_at, legado_sha256 (ya no hay install_id: la entropía DPAPI es constante por
                                    -- propósito y el sobre de credenciales.dpapi no depende de esta base, spec 03 §7.1)
  valor TEXT NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS preferencias (
  clave TEXT PRIMARY KEY,           -- sync.auto_min, sync.auto_activa, lan.activo, imagenes.max_mb, ...
  valor_json TEXT NOT NULL,
  actualizado_at INTEGER NOT NULL
) STRICT;

-- ------------------------------------------------------------------ conexión con TikTok (sin secretos)
CREATE TABLE IF NOT EXISTS auth_estado (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  app_key TEXT NOT NULL,
  app_secret_presente INTEGER NOT NULL DEFAULT 0,
  tokens_presentes INTEGER NOT NULL DEFAULT 0,
  open_id TEXT,
  user_type INTEGER,                -- debe ser 1 (creador)
  seller_name TEXT,
  granted_scopes_json TEXT NOT NULL DEFAULT '[]',
  access_expira_at INTEGER,         -- access_token_expire_in (ES un epoch, no una duración)
  refresh_expira_at INTEGER,
  estado TEXT NOT NULL DEFAULT 'sin_credenciales'
    CHECK (estado IN ('sin_credenciales','sin_autorizar','conectada','reautorizar','cuenta_sin_region')),
  origen TEXT CHECK (origen IN ('importado','oauth','manual','demo')),
  ultimo_refresh_at INTEGER,
  refresh_rechazos_seguidos INTEGER NOT NULL DEFAULT 0,   -- 2 rechazos definitivos seguidos -> 'reautorizar' (§2.1)
  refresh_aviso TEXT,               -- 'renovacion_pendiente' tras un fallo transitorio (la UI muestra un aviso suave)
  ultimo_error_codigo INTEGER,
  ultimo_error_mensaje TEXT,        -- SIEMPRE pasado por limpiar() (§7.6)
  actualizado_at INTEGER NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS oauth_states (
  state TEXT PRIMARY KEY,           -- secrets.token_urlsafe(24), un solo uso, 30 min; se purgan vencidos en cada tic
  creado_at INTEGER NOT NULL,
  expira_at INTEGER NOT NULL,
  usado_at INTEGER
) STRICT;

CREATE TABLE IF NOT EXISTS cuenta (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  creator_open_id TEXT NOT NULL,
  username TEXT NOT NULL,
  avatar_url TEXT,                  -- firmada con x-expires: se descarga a caché al recibirla
  selection_region TEXT,
  register_region TEXT,
  user_type TEXT,
  seller_type TEXT,
  permisos_json TEXT NOT NULL DEFAULT '[]',
  actualizado_at INTEGER NOT NULL
) STRICT;

-- ------------------------------------------------------------------ catálogo
CREATE TABLE IF NOT EXISTS tiendas (
  tienda_key TEXT PRIMARY KEY,      -- nombre normalizado (minúsculas, espacios colapsados) o 'shop:<shop_id>' si solo se conoce el id
  nombre TEXT NOT NULL,
  shop_id TEXT,                     -- lo dan fulfillments/search y target_collaborations
  primera_vez_at INTEGER NOT NULL,
  actualizado_at INTEGER NOT NULL
) STRICT;
CREATE UNIQUE INDEX IF NOT EXISTS ux_tiendas_shop_id ON tiendas(shop_id) WHERE shop_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS tienda_alias (   -- la tienda cambió de nombre (misma shop_id) o se conocía como 'shop:<id>'
  alias TEXT PRIMARY KEY,
  tienda_key TEXT NOT NULL REFERENCES tiendas(tienda_key),
  creado_at INTEGER NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS productos (
  product_id TEXT PRIMARY KEY,
  titulo TEXT,
  tienda_key TEXT REFERENCES tiendas(tienda_key),
  imagen_url TEXT,
  enlace TEXT,                      -- detail_link
  precio_min_centavos INTEGER,      -- original_price.minimum_amount (precio de LISTA)
  precio_max_centavos INTEGER,      -- original_price.maximum_amount (precio de LISTA, máximo entre variantes)
  moneda TEXT,
  comision_bp INTEGER,              -- commission.rate (puede faltar)
  comision_monto_min_centavos INTEGER,  -- commission.amount "19.15 - 19.25" = precio de VENTA × tasa
  comision_monto_max_centavos INTEGER,
  shop_ads_bp INTEGER,              -- shop_ads_commission.rate
  unidades_vendidas INTEGER,        -- units_sold GLOBAL del producto (no son tus ventas)
  con_inventario INTEGER,
  categoria TEXT,                   -- "Ropa interior y de hombre > Camisas y abrigos para hombre > Camisas"
  categoria_hoja_id TEXT,
  region TEXT,
  en_colaboracion_abierta INTEGER NOT NULL DEFAULT 1,  -- 0 si la API dejó de devolverlo
  origen TEXT NOT NULL DEFAULT 'api' CHECK (origen IN ('api','orden')),
  consultado_at INTEGER,
  huella TEXT,
  actualizado_at INTEGER NOT NULL
) STRICT;
CREATE INDEX IF NOT EXISTS ix_productos_tienda ON productos(tienda_key);
CREATE INDEX IF NOT EXISTS ix_productos_consultado ON productos(consultado_at);

-- ------------------------------------------------------------------ muestras
CREATE TABLE IF NOT EXISTS muestras (
  application_id TEXT PRIMARY KEY,
  product_id TEXT NOT NULL,
  sku_id TEXT,
  variante TEXT,                    -- sku_sale_property_value_names unidos con " / "
  main_order_id TEXT,               -- NULL si la API devolvió "0" o ""
  activity_id TEXT,
  tipo TEXT NOT NULL DEFAULT 'FREE_SAMPLE',   -- del cumplimiento (sample_application_type) o del detalle
  estado_api TEXT NOT NULL,         -- status de la búsqueda, NORMALIZADO (sin espacios, mayúsculas; frecuente: 'UNKNOWN')
  pistas_json TEXT NOT NULL DEFAULT '[]',     -- filtros ESPECÍFICOS (no comodín) donde apareció
  solicitada_at INTEGER,            -- create_time de single_query (inmutable)
  detalle_estado TEXT NOT NULL DEFAULT 'pendiente' CHECK (detalle_estado IN ('pendiente','ok','error')),
  detalle_intentos INTEGER NOT NULL DEFAULT 0,   -- solo errores NO transitorios; se reinicia si cambia `tipo`
  detalle_reintento_at INTEGER,     -- errores transitorios: próximo intento
  detalle_espera_s INTEGER,         -- última espera usada (1 h, 2 h, 4 h… tope 7 días)
  clase TEXT NOT NULL
    CHECK (clase IN ('debe_video','entregada','exenta','cancelada','nunca_enviada','pendiente_abierta')),
  subestado TEXT NOT NULL,
  clase_desde_at INTEGER NOT NULL,
  vista_en_sync INTEGER,            -- último sync_id que la devolvió
  primera_vez_at INTEGER NOT NULL,
  huella TEXT NOT NULL,
  actualizado_at INTEGER NOT NULL
, en_cohorte_desde_at INTEGER) STRICT;
CREATE INDEX IF NOT EXISTS ix_muestras_clase ON muestras(clase);
CREATE INDEX IF NOT EXISTS ix_muestras_producto ON muestras(product_id);
CREATE INDEX IF NOT EXISTS ix_muestras_pedido ON muestras(main_order_id) WHERE main_order_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS cumplimientos (
  fulfillment_id TEXT PRIMARY KEY,
  application_id TEXT NOT NULL,     -- SIN UNIQUE: puede haber re-cumplimientos; el vigente lo elige v_cumplimiento_vigente
  product_id TEXT NOT NULL,
  shop_id TEXT,
  tipo TEXT,                        -- FREE_SAMPLE | SAMPLE_COUPON | ...
  estado TEXT NOT NULL,             -- PENDING ONGOING SUCCEED FAILED OVERDUE SUSPEND CANCELLED EXEMPTED REPEATED DESCONOCIDO
  fecha_limite_at INTEGER,          -- SOLO si estado IN ('PENDING','ONGOING') y pasa la guardia (§4.2); si no, NULL
  suspension_s INTEGER NOT NULL DEFAULT 0,
  estado_producto TEXT,             -- bound_product_status
  vista_en_sync INTEGER,            -- último sync_id que lo devolvió (o que lo confirmó por single_query)
  huella TEXT NOT NULL,
  actualizado_at INTEGER NOT NULL
) STRICT;
CREATE INDEX IF NOT EXISTS ix_cumpl_app ON cumplimientos(application_id);
CREATE INDEX IF NOT EXISTS ix_cumpl_estado ON cumplimientos(estado);

CREATE TABLE IF NOT EXISTS muestras_historial (
  id INTEGER PRIMARY KEY,
  application_id TEXT NOT NULL,
  sync_id INTEGER,
  campo TEXT NOT NULL CHECK (campo IN ('estado_api','cumplimiento','clase')),
  antes TEXT,
  despues TEXT,
  at INTEGER NOT NULL
) STRICT;
CREATE INDEX IF NOT EXISTS ix_hist_app ON muestras_historial(application_id, at);

-- ------------------------------------------------------------------ órdenes de afiliado
CREATE TABLE IF NOT EXISTS ordenes (
  order_id TEXT PRIMARY KEY,
  creada_at INTEGER NOT NULL,
  entregada_at INTEGER,
  estado TEXT NOT NULL,             -- SETTLED REFUNDED To-SETTLE 'AWAITING PAYMENT' FROZEN UNSPECIFIED | NO_DEVUELTA (local)
  es_final INTEGER GENERATED ALWAYS AS (estado IN ('SETTLED','REFUNDED','NO_DEVUELTA')) VIRTUAL,
  vista_en_sync INTEGER,
  huella TEXT NOT NULL,             -- 'incompleta' si llegó en una ventana incompleta (la siguiente sync la reemplaza)
  actualizado_at INTEGER NOT NULL
) STRICT;
CREATE INDEX IF NOT EXISTS ix_ordenes_creada ON ordenes(creada_at);
CREATE INDEX IF NOT EXISTS ix_ordenes_estado ON ordenes(estado, creada_at);

CREATE TABLE IF NOT EXISTS orden_lineas (
  order_id TEXT NOT NULL REFERENCES ordenes(order_id) ON DELETE CASCADE,
  linea_n INTEGER NOT NULL,         -- ordinal de la fila dentro de la orden, en el orden de la API (0, 1, 2…)
  sku_id TEXT,                      -- sku.id NO identifica la línea: la misma SKU se repite (una fila por unidad)
  product_id TEXT NOT NULL,
  producto_nombre TEXT,             -- nombre al momento de la compra
  tienda_nombre TEXT,
  tienda_key TEXT,
  precio_centavos INTEGER,          -- price.amount UNITARIO ("$334.00")
  moneda TEXT,
  cantidad INTEGER NOT NULL,        -- incluye unidades reembolsadas
  reembolsadas INTEGER NOT NULL DEFAULT 0,
  devueltas INTEGER NOT NULL DEFAULT 0,
  comision_bp INTEGER,              -- commission_rate total
  comision_std_bp INTEGER,
  comision_ads_bp INTEGER,
  comision_bono_bp INTEGER,
  com_estimada_centavos INTEGER,    -- estimated_commission (ya con deducciones)
  com_real_centavos INTEGER,        -- actual_commission (ganancia final; > 0 solo en SETTLED)
  base_estimada_centavos INTEGER,
  base_real_centavos INTEGER,
  isr_centavos INTEGER,
  iva_centavos INTEGER,
  compartido_centavos INTEGER,      -- shared_with_partner (parte compartida con tu agencia)
  tipo_contenido TEXT,              -- VIDEO LIVE SHOP PRE_LIVE PROMOTION_PAGE LINKSHARE
  content_id TEXT,
  campaign_id TEXT,
  open_collab_id TEXT,
  target_collab_id TEXT,
  es_carrusel INTEGER,
  linea_actualizada_at INTEGER,     -- last_update_time
  PRIMARY KEY (order_id, linea_n)
) STRICT;
CREATE INDEX IF NOT EXISTS ix_lineas_producto ON orden_lineas(product_id);
CREATE INDEX IF NOT EXISTS ix_lineas_sku ON orden_lineas(sku_id) WHERE sku_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_lineas_tienda ON orden_lineas(tienda_key);
CREATE INDEX IF NOT EXISTS ix_lineas_video ON orden_lineas(content_id) WHERE tipo_contenido = 'VIDEO';

-- ------------------------------------------------------------------ videos e imágenes
CREATE TABLE IF NOT EXISTS videos (
  content_id TEXT PRIMARY KEY,
  titulo TEXT,                      -- oEmbed title
  autor TEXT,
  miniatura_url TEXT,               -- firmada, caduca: se descarga de inmediato
  oembed_estado TEXT NOT NULL DEFAULT 'pendiente'
    CHECK (oembed_estado IN ('pendiente','ok','no_disponible','error')),
  oembed_intentos INTEGER NOT NULL DEFAULT 0,
  oembed_at INTEGER,
  primera_venta_at INTEGER,
  actualizado_at INTEGER NOT NULL
, portada_product_id TEXT) STRICT;

CREATE TABLE IF NOT EXISTS "imagenes" (
  img_key TEXT PRIMARY KEY,         -- 'p:<product_id>' | 'v:<content_id>' | 'a:cuenta' | rev. 4: 'g:<product_id>-<n>' | 'm:<product_id>'
  tipo TEXT NOT NULL CHECK (tipo IN ('p','v','a','g','m','e')),   -- e = tabla o foto de reseña importada explícitamente
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
CREATE INDEX IF NOT EXISTS ix_img_estado ON imagenes(estado);
CREATE INDEX IF NOT EXISTS ix_img_acceso ON imagenes(ultimo_acceso_at);

CREATE TABLE IF NOT EXISTS vitrina (
  product_id TEXT PRIMARY KEY,
  titulo TEXT,
  tienda_nombre TEXT,
  tienda_key TEXT,                  -- norm(shop.name) calculado al ingerir (NULL si viene vacío)
  imagen_url TEXT,
  precio_min_centavos INTEGER,      -- price.original_price
  precio_max_centavos INTEGER,
  precio_desc_min_centavos INTEGER, -- price.seller_discount_price (precio de VENTA del vendedor)
  precio_desc_max_centavos INTEGER,
  comision_bp INTEGER,
  inventario TEXT,                  -- IN_STOCK | SOLD_OUT
  revision TEXT,                    -- APPROVED ...
  oculto INTEGER,
  agregado TEXT,                    -- ADDED | REJECTED
  fuente TEXT,
  enlace TEXT,
  colaboracion_tipo TEXT,
  vista_en_sync INTEGER,
  actualizado_at INTEGER NOT NULL
, precio_plat_min_centavos INTEGER, precio_plat_max_centavos INTEGER, galeria_json TEXT) STRICT;

-- ------------------------------------------------------------------ sincronización
CREATE TABLE IF NOT EXISTS sync_ejecuciones (
  sync_id INTEGER PRIMARY KEY,
  tipo TEXT NOT NULL CHECK (tipo IN ('incremental','completa','reparacion')),
  origen TEXT NOT NULL CHECK (origen IN ('auto','usuario','arranque','telefono','demo')),
  estado TEXT NOT NULL CHECK (estado IN ('en_curso','ok','parcial','error','cancelada')),
  iniciada_at INTEGER NOT NULL,
  terminada_at INTEGER,
  llamadas_api INTEGER NOT NULL DEFAULT 0,
  reintentos INTEGER NOT NULL DEFAULT 0,
  cambios INTEGER NOT NULL DEFAULT 0,
  resumen_json TEXT,                -- {"muestras":{"nuevos":0,"cambiados":2}, "muestras_filtros_fallidos":[...], ...}
  error_codigo TEXT,                -- sin_internet | reautorizar | token_rechazado | credenciales_cambiaron | interrumpida | ...
  error_mensaje TEXT,               -- SIEMPRE pasado por limpiar()
  data_version_final INTEGER
) STRICT;
CREATE INDEX IF NOT EXISTS ix_sync_inicio ON sync_ejecuciones(iniciada_at);

CREATE TABLE IF NOT EXISTS sync_pasos (
  sync_id INTEGER NOT NULL REFERENCES sync_ejecuciones(sync_id) ON DELETE CASCADE,
  paso TEXT NOT NULL CHECK (paso IN ('perfil','muestras','cumplimientos','detalles','productos','ordenes',
                                     'vitrina','videos','imagenes','clasificacion')),
  orden INTEGER NOT NULL,
  estado TEXT NOT NULL CHECK (estado IN ('pendiente','en_curso','ok','parcial','error','omitido')),
  iniciado_at INTEGER,
  terminado_at INTEGER,
  hechos INTEGER NOT NULL DEFAULT 0,
  total INTEGER,
  paginas INTEGER NOT NULL DEFAULT 0,
  llamadas INTEGER NOT NULL DEFAULT 0,
  reintentos INTEGER NOT NULL DEFAULT 0,
  nuevos INTEGER NOT NULL DEFAULT 0,
  cambiados INTEGER NOT NULL DEFAULT 0,
  cursor_json TEXT,                 -- p. ej. {"ventana_ge": 1757000000} para reanudar
  error_codigo TEXT,
  error_mensaje TEXT,
  PRIMARY KEY (sync_id, paso)
) STRICT;

CREATE TABLE IF NOT EXISTS sync_cursores (
  clave TEXT PRIMARY KEY,           -- ordenes.barrido_completo_at, productos.refresco_at, vitrina.at, muestras.estados_rechazados, ...
  valor TEXT NOT NULL,
  actualizado_at INTEGER NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS api_errores (
  id INTEGER PRIMARY KEY,
  sync_id INTEGER,
  at INTEGER NOT NULL,
  endpoint TEXT NOT NULL,           -- path sin query (nunca la URL firmada completa)
  http_status INTEGER,
  codigo INTEGER,
  mensaje TEXT,                     -- limpiar() + 300 caracteres
  request_id TEXT,
  intento INTEGER NOT NULL,
  decision TEXT NOT NULL CHECK (decision IN ('reintentar','refrescar_token','omitir_paso','abortar','reautorizar'))
) STRICT;
CREATE INDEX IF NOT EXISTS ix_api_errores_at ON api_errores(at);

-- ------------------------------------------------------------------ estado local del usuario (no viene de TikTok)
-- "Tu avance" de cada muestra (PlanVideo del contrato = PlanMuestra de 01_ux §2.4/§7.2). Un solo plan vivo por solicitud.
CREATE TABLE IF NOT EXISTS plan_videos (
  id TEXT PRIMARY KEY,              -- uuid4 generado por el cliente (permite crear sin conexión)
  application_id TEXT,
  product_id TEXT,
  tienda_key TEXT,
  titulo TEXT NOT NULL CHECK (length(titulo) BETWEEN 1 AND 200),
  fecha_plan TEXT,                  -- 'YYYY-MM-DD' local; obligatoria desde 'planeada'
  estado TEXT NOT NULL DEFAULT 'por_planear'
    CHECK (estado IN ('por_planear','planeada','video_listo','programada','publicada','no_se_puede')),
  fecha_video_listo TEXT,
  programada_para_at INTEGER,       -- obligatoria en 'programada'
  fecha_publicada TEXT,
  content_id TEXT,                  -- video vinculado (un mismo content_id puede estar en varias muestras: paquetes)
  enlace_video TEXT,
  vinculo_origen TEXT CHECK (vinculo_origen IS NULL OR vinculo_origen IN
    ('manual','sugerido_por_ventas','confirmado_por_tiktok','video_previo','video_previo_aceptado')),
  sugerencias_descartadas_json TEXT NOT NULL DEFAULT '[]',
  motivo_no_se_puede TEXT CHECK (motivo_no_se_puede IS NULL OR motivo_no_se_puede IN
    ('agotado','desactivado','no_llego','incompleta','no_va_con_mi_contenido','otro')),
  motivo_texto TEXT CHECK (motivo_texto IS NULL OR length(motivo_texto) <= 300),
  fijada INTEGER NOT NULL DEFAULT 0,
  nombre_corto TEXT CHECK (nombre_corto IS NULL OR length(nombre_corto) <= 60),
  notas TEXT CHECK (notas IS NULL OR length(notas) <= 5000),
  orden INTEGER NOT NULL DEFAULT 0,
  en_cohorte_desde_at INTEGER,      -- primera vez que la muestra se vio pendiente (base del progreso, 01_ux M9)
  creado_at INTEGER NOT NULL,
  actualizado_at INTEGER NOT NULL,
  rev INTEGER NOT NULL DEFAULT 1,
  eliminado INTEGER NOT NULL DEFAULT 0,
  dispositivo_id TEXT NOT NULL DEFAULT 'pc',
  CHECK (estado <> 'planeada' OR fecha_plan IS NOT NULL),
  CHECK (estado <> 'programada' OR programada_para_at IS NOT NULL),
  CHECK (estado <> 'no_se_puede' OR motivo_no_se_puede IS NOT NULL)
) STRICT;
CREATE INDEX IF NOT EXISTS ix_plan_fecha ON plan_videos(fecha_plan) WHERE eliminado = 0;
CREATE UNIQUE INDEX IF NOT EXISTS ux_plan_muestra ON plan_videos(application_id) WHERE eliminado = 0 AND application_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_plan_video ON plan_videos(content_id) WHERE eliminado = 0 AND content_id IS NOT NULL;

-- Avisos a tiendas (AvisoTienda, 01_ux §2.5): solo se agregan; "quitar" = quitado_at. Nunca se borran.
CREATE TABLE IF NOT EXISTS avisos_tienda (
  id TEXT PRIMARY KEY,              -- uuid4 del cliente
  tienda_key TEXT NOT NULL,
  solicitud_ids_json TEXT NOT NULL DEFAULT '[]',
  plantilla_id TEXT NOT NULL,
  texto TEXT NOT NULL CHECK (length(texto) <= 5000),
  compromisos_json TEXT NOT NULL DEFAULT '{}',   -- {application_id: 'YYYY-MM-DD'} fecha prometida de PUBLICACIÓN
  fecha_anterior TEXT,
  origen TEXT NOT NULL CHECK (origen IN ('copiado','por_mi_cuenta')),
  copiado_at INTEGER,
  marcado_enviado_at INTEGER,
  quitado_at INTEGER,
  creado_at INTEGER NOT NULL,
  actualizado_at INTEGER NOT NULL,
  rev INTEGER NOT NULL DEFAULT 1,
  dispositivo_id TEXT NOT NULL DEFAULT 'pc'
) STRICT;
CREATE INDEX IF NOT EXISTS ix_avisos_tienda ON avisos_tienda(tienda_key);

CREATE TABLE IF NOT EXISTS plantillas (   -- 11 predeterminadas (01_ux §4.8), editables y restaurables
  id TEXT PRIMARY KEY,
  nombre TEXT NOT NULL CHECK (length(nombre) BETWEEN 1 AND 60),
  cuerpo TEXT NOT NULL CHECK (length(cuerpo) BETWEEN 1 AND 5000),
  predeterminada INTEGER NOT NULL DEFAULT 1,
  creado_at INTEGER NOT NULL,
  actualizado_at INTEGER NOT NULL,
  rev INTEGER NOT NULL DEFAULT 1,
  dispositivo_id TEXT NOT NULL DEFAULT 'pc'
) STRICT;

CREATE TABLE IF NOT EXISTS preferencias_sinc (   -- PreferenciasSincronizadas (se sincronizan PC <-> celular)
  id INTEGER PRIMARY KEY CHECK (id = 1),
  valor_json TEXT NOT NULL,
  actualizado_at INTEGER NOT NULL,
  rev INTEGER NOT NULL DEFAULT 1,
  dispositivo_id TEXT NOT NULL DEFAULT 'pc'
) STRICT;

CREATE TABLE IF NOT EXISTS notas (
  id TEXT PRIMARY KEY,
  entidad TEXT NOT NULL CHECK (entidad IN ('muestra','tienda','producto','video','orden','general')),
  entidad_id TEXT,
  texto TEXT NOT NULL CHECK (length(texto) BETWEEN 1 AND 5000),
  fijada INTEGER NOT NULL DEFAULT 0,
  creado_at INTEGER NOT NULL,
  actualizado_at INTEGER NOT NULL,
  rev INTEGER NOT NULL DEFAULT 1,
  eliminado INTEGER NOT NULL DEFAULT 0,
  dispositivo_id TEXT NOT NULL DEFAULT 'pc'
) STRICT;
CREATE INDEX IF NOT EXISTS ix_notas_entidad ON notas(entidad, entidad_id) WHERE eliminado = 0;

CREATE TABLE IF NOT EXISTS recordatorios (
  id TEXT PRIMARY KEY,
  entidad TEXT NOT NULL DEFAULT 'general' CHECK (entidad IN ('muestra','tienda','plan','general')),
  entidad_id TEXT,
  titulo TEXT NOT NULL CHECK (length(titulo) BETWEEN 1 AND 200),
  vence_at INTEGER NOT NULL,
  repetir TEXT NOT NULL DEFAULT 'no' CHECK (repetir IN ('no','diario','semanal')),
  estado TEXT NOT NULL DEFAULT 'activo' CHECK (estado IN ('activo','hecho','cancelado')),
  pospuesto_hasta INTEGER,
  notificado_at INTEGER,
  creado_at INTEGER NOT NULL,
  actualizado_at INTEGER NOT NULL,
  rev INTEGER NOT NULL DEFAULT 1,
  eliminado INTEGER NOT NULL DEFAULT 0,
  dispositivo_id TEXT NOT NULL DEFAULT 'pc'
) STRICT;
CREATE INDEX IF NOT EXISTS ix_record_vence ON recordatorios(estado, vence_at) WHERE eliminado = 0;

CREATE TABLE IF NOT EXISTS ops_aplicadas (   -- idempotencia de mutaciones hechas sin conexión (teléfono); retención 30 días
  op_id TEXT PRIMARY KEY,           -- uuid4 del cliente; se inserta en la MISMA transacción que la mutación
  dispositivo_id TEXT NOT NULL,
  recibida_at INTEGER NOT NULL,
  resultado_json TEXT NOT NULL
) STRICT;

-- ------------------------------------------------------------------ dispositivos emparejados (LAN)
CREATE TABLE IF NOT EXISTS dispositivos (
  device_id TEXT PRIMARY KEY,       -- 32 hex
  nombre TEXT NOT NULL CHECK (length(nombre) BETWEEN 1 AND 48),
  plataforma TEXT NOT NULL DEFAULT 'android' CHECK (plataforma IN ('android')),
  clave_dpapi BLOB NOT NULL,        -- device_key VIGENTE (32 B) cifrada con DPAPI (usuario actual)
  clave_pendiente_dpapi BLOB,       -- rotación en dos fases: la nueva, hasta su primera petición válida
  clave_pendiente_at INTEGER,       -- si no se usa en 7 días se descarta la NUEVA (nunca la vieja)
  permisos TEXT NOT NULL DEFAULT 'lectura_escritura' CHECK (permisos IN ('lectura','lectura_escritura')),
  creado_at INTEGER NOT NULL,
  confirmado_at INTEGER,            -- primera petición firmada; si no llega en 10 min se borra el dispositivo
  clave_rotada_at INTEGER NOT NULL,
  ultimo_uso_at INTEGER,            -- se acumula en memoria y se vuelca cada 60 s o al cambiar la IP
  ultima_ip TEXT,
  revocado_at INTEGER
) STRICT;

-- ------------------------------------------------------------------ rev. 4: ficha completa de producto (API oficial)
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

-- ------------------------------------------------------------------ rev. 5: métricas de tus videos (Display API)
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

-- ------------------------------------------------------------------ vistas de lectura (analítica)
-- Una línea es VÁLIDA ("vendió", 01_ux §6.0) si su orden está en SETTLED, To-SETTLE o AWAITING PAYMENT.
-- REFUNDED y NO_DEVUELTA no cuentan; FROZEN se muestra aparte como "retenida"; UNSPECIFIED no cuenta (se avisa).
-- comision_centavos = la mejor cifra disponible: real si SETTLED, estimada si To-SETTLE / AWAITING PAYMENT / FROZEN, 0 si no.
-- Identidad: Σ comision_centavos = liquidada + por liquidar + retenida (= Kpis.comision_total_centavos).
CREATE VIEW IF NOT EXISTS v_lineas AS
WITH tz AS (SELECT COALESCE((SELECT CAST(valor AS INTEGER) FROM meta WHERE clave = 'tz_offset_s'), -21600) AS off),
     pm AS (SELECT DISTINCT main_order_id FROM muestras WHERE main_order_id IS NOT NULL)
SELECT l.order_id, l.linea_n, l.sku_id, l.product_id, l.producto_nombre, l.tienda_nombre,
       COALESCE(ta.tienda_key, l.tienda_key)                            AS tienda_key,
       l.precio_centavos, l.cantidad, l.reembolsadas, l.devueltas, l.comision_bp,
       MAX(0, l.cantidad - MAX(l.reembolsadas, l.devueltas))           AS unidades_netas,
       COALESCE(l.precio_centavos, 0) * MAX(0, l.cantidad - MAX(l.reembolsadas, l.devueltas)) AS ventas_linea_centavos,
       COALESCE(l.base_estimada_centavos,
                COALESCE(l.precio_centavos, 0) * MAX(0, l.cantidad - MAX(l.reembolsadas, l.devueltas))) AS base_centavos,
       COALESCE(l.com_estimada_centavos, 0)                             AS com_estimada_centavos,
       COALESCE(l.com_real_centavos, 0)                                 AS com_real_centavos,
       CASE WHEN o.estado = 'SETTLED' THEN COALESCE(l.com_real_centavos, 0)
            WHEN o.estado IN ('To-SETTLE', 'AWAITING PAYMENT', 'FROZEN') THEN COALESCE(l.com_estimada_centavos, 0)
            ELSE 0 END                                                  AS comision_centavos,
       l.tipo_contenido, l.content_id,
       o.estado, o.creada_at,
       date(o.creada_at + tz.off, 'unixepoch')                         AS fecha,
       strftime('%Y-%m', o.creada_at + tz.off, 'unixepoch')            AS mes,
       date(o.creada_at + tz.off, 'unixepoch', 'weekday 0', '-6 days') AS semana,   -- lunes
       (o.estado IN ('SETTLED', 'To-SETTLE', 'AWAITING PAYMENT'))      AS valida,
       (pm.main_order_id IS NOT NULL)                                   AS es_pedido_muestra
FROM orden_lineas l JOIN ordenes o USING (order_id) CROSS JOIN tz
LEFT JOIN pm ON pm.main_order_id = l.order_id
LEFT JOIN tienda_alias ta ON ta.alias = l.tienda_key;

-- Mediana del precio UNITARIO pagado por SKU (líneas válidas, sin pedidos de muestra, sin líneas de $1.00 o menos).
CREATE VIEW IF NOT EXISTS v_precio_sku AS
WITH x AS (SELECT sku_id, precio_centavos AS p,
                  ROW_NUMBER() OVER (PARTITION BY sku_id ORDER BY precio_centavos) AS rn,
                  COUNT(*) OVER (PARTITION BY sku_id) AS n
           FROM v_lineas
           WHERE valida AND NOT es_pedido_muestra AND sku_id IS NOT NULL AND precio_centavos > 100)
SELECT sku_id, CAST(ROUND(AVG(p)) AS INTEGER) AS mediana_centavos, MAX(n) AS lineas
FROM x WHERE rn IN ((n + 1) / 2, (n + 2) / 2) GROUP BY sku_id;

-- Un cumplimiento por solicitud: abierto > SUCCEED/REPEATED > EXEMPTED > FAILED/OVERDUE > CANCELLED > DESCONOCIDO.
CREATE VIEW IF NOT EXISTS v_cumplimiento_vigente AS
SELECT fulfillment_id, application_id, product_id, shop_id, tipo, estado, fecha_limite_at, suspension_s,
       estado_producto, vista_en_sync, actualizado_at
FROM (SELECT c.*, ROW_NUMBER() OVER (
        PARTITION BY c.application_id
        ORDER BY CASE c.estado WHEN 'PENDING' THEN 0 WHEN 'ONGOING' THEN 0 WHEN 'SUSPEND' THEN 0
                               WHEN 'SUCCEED' THEN 1 WHEN 'REPEATED' THEN 1 WHEN 'EXEMPTED' THEN 2
                               WHEN 'FAILED' THEN 3 WHEN 'OVERDUE' THEN 3 WHEN 'CANCELLED' THEN 4 ELSE 5 END,
                 c.actualizado_at DESC, c.fulfillment_id DESC) AS rn
      FROM cumplimientos c)
WHERE rn = 1;

CREATE VIEW IF NOT EXISTS v_muestras AS
WITH b AS (
  SELECT m.application_id, m.product_id, m.sku_id, m.variante, m.main_order_id, m.tipo,
         m.estado_api, m.clase, m.subestado, m.clase_desde_at, m.solicitada_at, m.pistas_json, m.primera_vez_at,
         COALESCE(m.solicitada_at, (SELECT o.creada_at FROM ordenes o WHERE o.order_id = m.main_order_id),
                  m.primera_vez_at)                                                  AS solicitada_at_efectiva,
         (m.solicitada_at IS NULL)                                                   AS solicitada_aprox,
         c.fulfillment_id, c.estado AS cumplimiento, c.fecha_limite_at, c.estado_producto, c.suspension_s,
         c.vista_en_sync AS cumplimiento_vista_en_sync,
         p.titulo, p.imagen_url, p.enlace, p.precio_min_centavos, p.precio_max_centavos, p.con_inventario,
         p.comision_bp, p.comision_monto_min_centavos, p.comision_monto_max_centavos, p.unidades_vendidas, p.categoria,
         p.en_colaboracion_abierta, p.origen AS producto_origen,
         COALESCE((SELECT a.tienda_key FROM tienda_alias a WHERE a.alias = p.tienda_key), p.tienda_key,
                  (SELECT t2.tienda_key FROM tiendas t2 WHERE t2.shop_id = c.shop_id),
                  (SELECT a.tienda_key FROM tienda_alias a WHERE a.alias = v.tienda_key), v.tienda_key) AS tienda_key,
         c.shop_id AS shop_id_cumplimiento,
         -- fuentes de precio (01_ux §6.0): variante (lo pagado por ESA SKU) > vitrina (seller_discount_price) >
         -- commission.amount ÷ tasa > precio de lista. NUNCA el máximo de lista para el número grande.
         ps.mediana_centavos AS precio_sku_centavos,
         v.precio_desc_min_centavos, v.precio_desc_max_centavos, (v.product_id IS NOT NULL) AS en_vitrina,
         CASE WHEN p.comision_bp > 0 AND p.comision_monto_min_centavos > 0
              THEN CAST(ROUND(p.comision_monto_min_centavos * 10000.0 / p.comision_bp) AS INTEGER) END AS precio_comision_min_centavos,
         CASE WHEN p.comision_bp > 0 AND p.comision_monto_max_centavos > 0
              THEN CAST(ROUND(p.comision_monto_max_centavos * 10000.0 / p.comision_bp) AS INTEGER) END AS precio_comision_max_centavos,
         (SELECT MIN(l.precio_centavos) FROM orden_lineas l
           WHERE l.order_id = m.main_order_id AND l.product_id = m.product_id)       AS pagado_pedido_muestra_centavos,
         pl.id AS plan_id, COALESCE(pl.estado, 'por_planear') AS etapa, pl.fecha_plan, pl.programada_para_at,
         pl.fecha_publicada, pl.content_id AS plan_content_id, pl.vinculo_origen, COALESCE(pl.fijada, 0) AS fijada,
         COALESCE(pl.rev, 0) AS plan_rev, pl.motivo_no_se_puede, pl.sugerencias_descartadas_json, pl.actualizado_at AS plan_actualizado_at
  FROM muestras m
  LEFT JOIN v_cumplimiento_vigente c ON c.application_id = m.application_id
  LEFT JOIN productos p              ON p.product_id = m.product_id
  LEFT JOIN vitrina v                ON v.product_id = m.product_id
  LEFT JOIN v_precio_sku ps          ON ps.sku_id = m.sku_id
  LEFT JOIN plan_videos pl           ON pl.application_id = m.application_id AND pl.eliminado = 0),
d AS (
  SELECT b.*,
         CASE subestado
           WHEN 'video_aprobado' THEN 'entregada' WHEN 'exenta_por_tiktok' THEN 'exenta'
           WHEN 'video_en_revision' THEN 'en_revision'
           WHEN 'por_grabar' THEN 'por_vencer' WHEN 'video_borrado_con_plazo' THEN 'por_vencer'
           WHEN 'pausada' THEN 'pausada'
           WHEN 'vencida_sin_video' THEN 'vencida' WHEN 'video_no_cumplio' THEN 'vencida' WHEN 'video_borrado' THEN 'vencida'
           WHEN 'esperando_aprobacion' THEN 'esperando_aprobacion' WHEN 'esperando_respuesta' THEN 'esperando_aprobacion'
           WHEN 'por_enviar' THEN 'en_camino' WHEN 'en_camino' THEN 'en_camino' WHEN 'aprobada_esperando_envio' THEN 'en_camino'
           WHEN 'cancelada_sin_detalle' THEN 'pedido_cancelado' WHEN 'cumplimiento_cancelado' THEN 'pedido_cancelado'
           ELSE 'sin_envio' END                                                       AS grupo,
         CASE WHEN precio_sku_centavos IS NOT NULL THEN 'variante' WHEN precio_desc_min_centavos IS NOT NULL THEN 'vitrina'
              WHEN precio_comision_min_centavos IS NOT NULL THEN 'comision' WHEN precio_min_centavos IS NOT NULL THEN 'lista' END AS precio_fuente,
         COALESCE(precio_sku_centavos, precio_desc_min_centavos, precio_comision_min_centavos, precio_min_centavos) AS precio_venta_min_centavos,
         CASE WHEN precio_sku_centavos IS NOT NULL THEN precio_sku_centavos
              WHEN precio_desc_min_centavos IS NOT NULL THEN COALESCE(precio_desc_max_centavos, precio_desc_min_centavos)
              WHEN precio_comision_min_centavos IS NOT NULL THEN COALESCE(precio_comision_max_centavos, precio_comision_min_centavos)
              ELSE COALESCE(precio_max_centavos, precio_min_centavos) END              AS precio_venta_max_centavos,
         -- comisión por venta: commission.amount (refleja el precio de venta real); si falta, precio de la variante o de
         -- lista mínimo × tasa. Umbrales y prioridad usan el MÍNIMO (01_ux §2.6).
         COALESCE(comision_monto_min_centavos,
                  CAST(ROUND(COALESCE(precio_sku_centavos, precio_desc_min_centavos, precio_min_centavos) * comision_bp / 10000.0) AS INTEGER))
                                                                                       AS comision_por_venta_centavos,
         COALESCE(comision_monto_max_centavos, comision_monto_min_centavos,
                  CAST(ROUND(COALESCE(precio_sku_centavos, precio_desc_max_centavos, precio_max_centavos) * comision_bp / 10000.0) AS INTEGER))
                                                                                       AS comision_por_venta_max_centavos,
         ((estado_producto IS NULL OR estado_producto IN ('LIVE', 'UNKNOWN')) AND COALESCE(con_inventario, 1) <> 0) AS promocionable,
         (clase = 'debe_video' AND etapa = 'publicada' AND COALESCE(vinculo_origen, '') <> 'video_previo') AS saldada,
         (SELECT COUNT(DISTINCT l.content_id) FROM v_lineas l
           WHERE l.product_id = b.product_id AND l.tipo_contenido = 'VIDEO' AND l.valida AND NOT l.es_pedido_muestra
             AND l.content_id IS NOT NULL
             AND l.fecha >= date(b.solicitada_at_efectiva + COALESCE((SELECT CAST(valor AS INTEGER) FROM meta
                                                                      WHERE clave = 'tz_offset_s'), -21600), 'unixepoch'))
                                                                                       AS videos_detectados,
         (fulfillment_id IS NOT NULL OR clase IN ('debe_video', 'entregada', 'exenta')) AS recibida
  FROM b),
e AS (
  SELECT d.*,
         -- pendiente (01_ux §2.5): grupo Por vencer / Vencida / Pausada y etapa ∉ {Publicada, No se puede}. Un video PREVIO a la
         -- muestra nunca cuenta como publicado (01_ux §2.4 regla 4; la API además rechaza esa combinación con 422).
         (grupo IN ('por_vencer', 'vencida', 'pausada') AND etapa <> 'no_se_puede'
          AND NOT (etapa = 'publicada' AND COALESCE(vinculo_origen, '') <> 'video_previo'))   AS pendiente,
         CASE WHEN saldada THEN COALESCE(CAST(strftime('%s', fecha_publicada) AS INTEGER) + 21600, plan_actualizado_at) END AS saldada_at,
         -- valor de la muestra (≈): el cupón de muestra NO fue un regalo -> precio − lo que pagaste en su pedido
         CASE WHEN tipo = 'SAMPLE_COUPON'
              THEN CASE WHEN pagado_pedido_muestra_centavos IS NULL OR precio_venta_min_centavos IS NULL THEN 0
                        ELSE MAX(0, precio_venta_min_centavos - pagado_pedido_muestra_centavos) END
              ELSE COALESCE(precio_venta_min_centavos, 0) END                         AS valor_muestra_centavos,
         CASE WHEN tipo = 'SAMPLE_COUPON'
              THEN CASE WHEN pagado_pedido_muestra_centavos IS NULL OR precio_venta_max_centavos IS NULL THEN 0
                        ELSE MAX(0, precio_venta_max_centavos - pagado_pedido_muestra_centavos) END
              ELSE COALESCE(precio_venta_max_centavos, 0) END                         AS valor_muestra_max_centavos,
         CASE WHEN clase <> 'debe_video' THEN NULL
              WHEN saldada THEN 'saldada'
              WHEN etapa = 'no_se_puede' THEN 'no_se_puede'
              WHEN videos_detectados > 0 THEN 'video_no_vinculado'
              WHEN NOT promocionable THEN 'producto_no_disponible'
              WHEN etapa <> 'por_planear' THEN 'planeada'
              ELSE 'pendiente' END                                                     AS deuda_estado
  FROM d)
SELECT e.*, t.nombre AS tienda_nombre, COALESCE(shop_id_cumplimiento, t.shop_id) AS shop_id
FROM e LEFT JOIN tiendas t ON t.tienda_key = e.tienda_key;

-- Conteos por tienda para la salud con nombre (01_ux §2.7; la regla se aplica en analitica.salud_tienda) y FilaTienda.
CREATE VIEW IF NOT EXISTS v_salud_tiendas AS
WITH ms AS (
  SELECT tienda_key,
         COUNT(*)                                                  AS solicitudes,
         SUM(recibida)                                             AS recibidas,
         SUM(grupo = 'entregada')                                  AS entregadas,
         SUM(grupo = 'exenta')                                     AS exentas,
         SUM(clase = 'debe_video')                                 AS debidas,
         SUM(saldada)                                              AS saldadas,
         SUM(pendiente)                                            AS pendientes,
         SUM(pendiente AND etapa = 'por_planear')                  AS pendientes_por_planear,
         SUM(pendiente AND etapa <> 'por_planear')                 AS pendientes_con_plan,
         SUM(etapa = 'publicada')                                  AS publicadas,
         SUM(deuda_estado = 'video_no_vinculado')                  AS video_no_vinculado,
         SUM(clase = 'pendiente_abierta')                          AS abiertas,
         SUM(clase = 'cancelada')                                  AS canceladas,
         SUM(clase = 'nunca_enviada')                              AS nunca_enviadas,
         SUM(grupo = 'sin_envio')                                  AS sin_envio,
         SUM(CASE WHEN pendiente THEN valor_muestra_centavos ELSE 0 END)      AS valor_debido_centavos,
         SUM(CASE WHEN recibida THEN valor_muestra_centavos ELSE 0 END)       AS valor_recibido_min_centavos,
         SUM(CASE WHEN recibida THEN valor_muestra_max_centavos ELSE 0 END)   AS valor_recibido_max_centavos,
         MAX(solicitada_at_efectiva)                               AS ultima_solicitud_at
  FROM v_muestras WHERE tienda_key IS NOT NULL GROUP BY tienda_key),
vs AS (
  SELECT tienda_key,
         COUNT(DISTINCT order_id)                                  AS pedidos,
         COUNT(DISTINCT CASE WHEN valida THEN order_id END)        AS pedidos_validos,
         SUM(CASE WHEN valida THEN com_estimada_centavos ELSE 0 END) AS comision_estimada_centavos,
         SUM(comision_centavos)                                    AS comision_centavos,
         MAX(CASE WHEN valida THEN creada_at END)                  AS ultima_venta_at
  FROM v_lineas GROUP BY tienda_key)
SELECT t.tienda_key, t.nombre, t.shop_id,
       COALESCE(ms.solicitudes, 0) AS solicitudes, COALESCE(ms.recibidas, 0) AS recibidas,
       COALESCE(ms.entregadas, 0) AS entregadas, COALESCE(ms.exentas, 0) AS exentas,
       COALESCE(ms.debidas, 0) AS debidas, COALESCE(ms.saldadas, 0) AS saldadas,
       COALESCE(ms.pendientes, 0) AS pendientes, COALESCE(ms.pendientes_por_planear, 0) AS pendientes_por_planear,
       COALESCE(ms.pendientes_con_plan, 0) AS pendientes_con_plan, COALESCE(ms.publicadas, 0) AS publicadas,
       COALESCE(ms.video_no_vinculado, 0) AS video_no_vinculado,
       COALESCE(ms.abiertas, 0) AS abiertas, COALESCE(ms.canceladas, 0) AS canceladas,
       COALESCE(ms.nunca_enviadas, 0) AS nunca_enviadas, COALESCE(ms.sin_envio, 0) AS sin_envio,
       COALESCE(ms.valor_debido_centavos, 0) AS valor_debido_centavos,
       COALESCE(ms.valor_recibido_min_centavos, 0) AS valor_recibido_min_centavos,
       COALESCE(ms.valor_recibido_max_centavos, 0) AS valor_recibido_max_centavos, ms.ultima_solicitud_at,
       COALESCE(vs.pedidos, 0) AS pedidos, COALESCE(vs.pedidos_validos, 0) AS pedidos_validos,
       COALESCE(vs.comision_estimada_centavos, 0) AS comision_estimada_centavos,
       COALESCE(vs.comision_centavos, 0) AS comision_centavos, vs.ultima_venta_at
FROM tiendas t LEFT JOIN ms USING (tienda_key) LEFT JOIN vs USING (tienda_key)
WHERE t.tienda_key NOT IN (SELECT alias FROM tienda_alias);

-- Evidencia aportada explícitamente: no es una respuesta simulada de Affiliate Creator.
CREATE TABLE IF NOT EXISTS producto_evidencia (
  product_id TEXT PRIMARY KEY,
  evidencia_json TEXT NOT NULL CHECK (length(evidencia_json) <= 196608 AND json_valid(evidencia_json)),
  rev INTEGER NOT NULL CHECK (rev >= 1),
  actualizado_at INTEGER NOT NULL
) STRICT;

-- rev. 7 (migraciones/007.sql, mismo DDL): trace_info de cada línea de orders/search 202410. Fila = observada en una
-- ventana completa (traza_tipo NULL = sin traza reportada); sin fila = sin dato. Nunca guarda trace_info.id.
CREATE TABLE IF NOT EXISTS orden_lineas_traza (
  order_id TEXT NOT NULL,
  linea_n INTEGER NOT NULL,
  traza_tipo TEXT,                  -- trace_info.type normalizado; NULL = sin traza reportada
  capturada_at INTEGER NOT NULL,    -- inicio de la sync que la observó
  PRIMARY KEY (order_id, linea_n),
  FOREIGN KEY (order_id, linea_n) REFERENCES orden_lineas(order_id, linea_n) ON DELETE CASCADE
) STRICT;

-- Una reserva por archivo del creador. NULL conserva un envío con resultado aún desconocido.
CREATE TABLE IF NOT EXISTS publicaciones_shop (
  cuenta_sha256 TEXT NOT NULL,
  archivo_sha256 TEXT NOT NULL,
  solicitud_sha256 TEXT NOT NULL,
  iniciado_at INTEGER NOT NULL,
  resultado_json TEXT CHECK (resultado_json IS NULL OR json_valid(resultado_json)),
  PRIMARY KEY (cuenta_sha256, archivo_sha256)
) STRICT;

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
