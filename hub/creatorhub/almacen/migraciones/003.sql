-- Migración user_version 2 -> 3 (BUILD_SPEC §4.3): cohorte de pendientes y versión de la caché de imágenes (C45).
-- muestras.en_cohorte_desde_at = primera vez que la clasificación FINAL vio la muestra pendiente (la escribe el
-- sincronizador; nunca se borra). meta.img_rev nace en 0 y lo sube hub-imagenes al cerrar cada lote.
ALTER TABLE muestras ADD COLUMN en_cohorte_desde_at INTEGER;
INSERT OR IGNORE INTO meta(clave, valor) VALUES ('img_rev', '0');
PRAGMA user_version = 3;
