-- rev. 7 (18/11/2026) · trace_info de cada línea SKU de POST /affiliate_creator/202410/orders/search (etapa 2 de
-- docs/ORDER_TRACE_RETIREMENT.md). Solo agrega una tabla: ninguna existente cambia.
-- Una fila = la línea se observó con el código nuevo en una ventana COMPLETA: traza_tipo es trace_info.type normalizado
-- (GENERAL, SPECIFIC u otro valor, tal cual) o NULL si TikTok no reportó traza. Sin fila = sin dato (línea guardada antes
-- de esta versión, o en una ventana incompleta). Nunca se guarda trace_info.id.
-- La FK compuesta borra las filas cuando se reescriben, purgan o borran sus líneas. Reconstruir orden_lineas u ordenes
-- con las FK activas (DROP + RENAME) borraría también estas filas.
CREATE TABLE IF NOT EXISTS orden_lineas_traza (
  order_id TEXT NOT NULL,
  linea_n INTEGER NOT NULL,
  traza_tipo TEXT,                  -- trace_info.type normalizado; NULL = sin traza reportada
  capturada_at INTEGER NOT NULL,    -- inicio de la sync que la observó
  PRIMARY KEY (order_id, linea_n),
  FOREIGN KEY (order_id, linea_n) REFERENCES orden_lineas(order_id, linea_n) ON DELETE CASCADE
) STRICT;
PRAGMA user_version = 7;
