-- Migración user_version 1 -> 2 (BUILD_SPEC §4.3, C4): portada de cada video = foto del producto (sin oEmbed).
-- almacen.py ejecuta cada sentencia dentro de UNA transacción, con copia previa hub.sqlite.bak-v1, y omite un
-- `ADD COLUMN` si la columna ya existe (así una base intermedia no falla). El texto de la columna es el mismo que en
-- schema.sql: el esquema migrado queda idéntico al de una base nueva.
ALTER TABLE videos ADD COLUMN portada_product_id TEXT;
PRAGMA user_version = 2;
