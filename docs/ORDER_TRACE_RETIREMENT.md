# Retiro de `orders/trace/search`: consumidores y conservación del histórico

Revisado el **18 de noviembre de 2026** sobre el código publicado en la nube (`f3f963c`, imagen `corte@sha256:71e0ad75…`). Este documento identifica a cada consumidor del origen de ventas y fija cómo conservar su histórico. Por sí mismo no cambia el comportamiento: la migración corresponde al siguiente incremento.

## Estado oficial

- `POST /affiliate_creator/202505/orders/trace/search` quedó **retirada para todos los mercados el 15 de agosto de 2026** según el [aviso oficial](https://partner.tiktokshop.com/docv2/page/si5r1bv3) ("Breaking Change", "Action Required"). TikTok advierte que las llamadas posteriores fallan.
- Reemplazo: `POST /affiliate_creator/202410/orders/search`, que Corte ya llama en el paso de pedidos. Sus filtros son `create_time_ge`/`create_time_lt` en segundos; no existe `time_type` ni filtro por fecha de pago, entrega o liquidación.
- Por línea SKU, 202410 documenta un `trace_info {id, type}` **opcional**. `GENERAL` significa que `id` es el `eid` de un enlace general; `SPECIFIC`, que es un `publisher_id`. No aporta atribución de contenido (eso es `content_type`/`content_id`), nombre del publicador, URL, clics, fecha de liquidación, saldo ni fecha de depósito. La documentación no define qué significa su ausencia.
- El aviso afirma que la respuesta es idéntica, pero los metadatos difieren: `trace` pasa a `trace_info`, el id de pedido pasa de entero a texto, cambian los estados y los tiempos pasan de milisegundos a segundos.
- **No falta ningún permiso de TikTok.** El reemplazo usa `creator.affiliate_collaboration.read`, ya concedido al grant de la nube. Un 105005 en la ruta retirada no se resuelve volviendo a autorizar; no se debe recomendar.

## Qué hace hoy el backend publicado

La fase 5 «trazas» de la ficha completa llama la ruta retirada dentro del paso `productos_ventas` de **cada** sincronización: 5 ventanas de 7 días en una incremental y 13 en una completa (`hub/creatorhub/sincronizador_ficha.py:23-26, 49, 516-586`). Con la sincronización automática cada 30 minutos son unas 48 llamadas diarias; la fase no tiene TTL. Es la última de cinco fases, así que no impide las demás.

| Respuesta de TikTok | Efecto en Corte |
| --- | --- |
| 105005 o 16501011 | Fase `sin_permiso`. La ficha muestra «requiere un permiso extra en Partner Center» en productos con ventas y sin trazas. El mensaje es engañoso: la ruta está retirada. |
| Otro código, o HTTP 4xx sin código | Fase `error`, sin aviso visible; un intento por sincronización. |
| HTTP 5xx, 429 o cuerpo no JSON (por ejemplo, un 404 HTML) | Hasta 3 reintentos con espera (unos 7 s por sincronización) y fase `error`. |
| 105001, 105002, 36009005, 101000 o códigos de región | Renovación del token o aborto. Puede marcar la conexión Shop para reautorizar, abortar la sincronización y suspender la automática. Es el caso de mayor riesgo. |
| Código 0 | Reescribe las filas del pedido en `orden_trazas`. |

Los fallos solo quedan en `api_errores` (máximo 500 filas, compartidas con el resto de rutas) y en `sync_ejecuciones.resumen_json['fases']['trazas']`, dentro del SQLite del disco de la VM. No aparecen en los logs de aplicación ni en la API. La fase y la tabla datan del 15/11/2026, después del retiro, así que es probable que `orden_trazas` esté vacía en la nube; está pendiente comprobarlo en modo de solo lectura (etapa 0).

## Consumidores

| Papel | Ubicación |
| --- | --- |
| Productor | `hub/creatorhub/sincronizador_ficha.py`: `P_TRAZAS` (49), constantes de la fase (52, 63-66), `ORDEN_FASES`/`TEXTOS_FASES` (73, 79), `_bajar_trazas` (516-532), `_fase_trazas` (534-581), cursor `trazas.estado` (583-586). `CODIGOS_SIN_PERMISO` (68) **también lo usan las otras fases**. |
| Almacenamiento | Tabla `orden_trazas` (`hub/creatorhub/almacen/schema.sql:567-579`, `migraciones/004.sql:124-136`): PK `(order_id, linea_n)`, sin llave foránea. Guarda `traza_tipo`; nunca guardó `trace.id`. Su único escritor borra y vuelve a insertar las filas de un pedido cuando cambian (`sincronizador_ficha.py:565-575`). |
| Borrado | Purga de 400 días en una sincronización completa (`hub/creatorhub/sincronizador.py:1260-1265`). Borrados explícitos del usuario, desconexión con borrado o cambio de cuenta (`TABLAS_TIKTOK`, `hub/creatorhub/almacen/almacen.py:54-60`). La copia en Firebase no incluye esta tabla: el único ejemplar está en el disco de la VM. |
| Lectores | `hub/creatorhub/analitica/vista.py`: `origen_ventas` (1249-1265; el balde nulo se rotula «Sin enlace compartido») y `origen_ventas_aviso` a partir del cursor `trazas.estado` (1106, 1113-1114). |
| API | `GET /api/productos/{product_id}` (`hub/creatorhub/api/rutas.py:392-393`) y `extras.productos` de `GET /api/snapshot` (`hub/creatorhub/analitica/servicio.py`). La nube reenvía `/api/*` al despachador del hub (`cloud/app.py`). |
| Contrato | `spec/contrato.ts:761-765` (`origen_ventas`, `origen_ventas_aviso`) y 981-996 (`CuentaOrigen`, `OrigenVentas`). |
| Web | `ui/src/pantallas/productos/logicaFicha.ts:182-189`, `FichaCompleta.tsx:350-396` (incluida `NotaPermisoOrigen`), `PantallaProducto.tsx:190-191` y `textos.ts:197-203`. El texto dice «pedidos» aunque el valor cuenta líneas SKU. |
| Flutter | `client_flutter/lib/domain/corte_models.dart:166, 191-192` y `client_flutter/lib/ui/catalog.dart:636-643, 709-730`. Las apps instaladas muestran el mosaico con **cualquier** aviso no nulo y solo tienen texto para `sin_permiso`. |
| Demo | `hub/creatorhub/demo/transporte.py` (ruta, `_trazas` y la bandera `trazas_sin_permiso`), `hub/creatorhub/demo/sinteticos.py:469-475`, `ui/src/datos/demo/ficha_demo.ts` y `ui/src/datos/demo/transporte_demo.ts` (`?trazas=sin_permiso`). El falso de 202410 no emite `trace_info`. |
| Documentos | Este archivo, [API_COVERAGE.md](API_COVERAGE.md) y [SALES_AND_PAYOUTS.md](SALES_AND_PAYOUTS.md). El catálogo histórico `research/catalogo_endpoints/00_INDICE.md` y `01_afiliados_creador.md` todavía recomienda reautorizar: es obsoleto en ese punto. |

No consumen trazas: `cloud/display_import.py`, `hub/creatorhub/nube.py`, `hub/creatorhub/local/estado.py` ni `/api/sync/historial` (expone solo los pasos públicos, nunca `fases`).

## Cómo conservar el histórico

### Principios

1. **Registro cerrado.** `orden_trazas` queda como histórico de una fuente retirada. Después de apagar el productor nada la escribe ni la reescribe; solo la vacían los borrados explícitos de usuario o de cuenta.
2. **Procedencia por tabla.** Lo que llegue de 202410 va a otra tabla. Escribirlo en `orden_trazas` mezclaría fuentes: las posiciones `linea_n` vienen de respuestas distintas, la llave chocaría y el escritor actual borra el pedido completo antes de insertar.
3. **La ausencia no es un negativo.** Cada línea nueva queda en uno de tres estados: *traza reportada* (`GENERAL`, `SPECIFIC` u otro valor guardado tal cual), *sin traza reportada* (línea capturada por el código nuevo en una ventana completa, sin `trace_info` o con tipo vacío) o *sin dato* (no capturada). Ninguno de ellos significa «orgánico» ni «vino de un video».
4. **Sin atribución fabricada.** Nunca derivar una traza de `content_type`, `LINKSHARE`, `tag` o campañas; nunca copiar filas históricas a líneas nuevas; nunca unir ambas fuentes por `linea_n` o `sku_id`; nunca usar datos demo.
5. **Contrato compatible.** Solo se agregan campos opcionales. `origen_ventas_aviso` conserva su tipo `'sin_permiso' | null` y pasa a ser siempre `null`; un valor nuevo no nulo dejaría un mosaico vacío en las apps Flutter instaladas.

### Etapa 0: diagnóstico de solo lectura

Con autorización para leer la VM, abrir `/var/lib/corte/datos/hub.sqlite` con `?mode=ro` y consultar:

```sql
SELECT COUNT(*), COUNT(DISTINCT order_id), MIN(creada_at), MAX(creada_at), SUM(traza_tipo IS NOT NULL) FROM orden_trazas;
SELECT valor, actualizado_at FROM sync_cursores WHERE clave = 'trazas.estado';
SELECT http_status, codigo, decision, COUNT(*), MIN(at), MAX(at) FROM api_errores
 WHERE endpoint = '/affiliate_creator/202505/orders/trace/search' GROUP BY 1, 2, 3;
SELECT sync_id, json_extract(resumen_json, '$.fases.trazas') FROM sync_ejecuciones ORDER BY sync_id DESC LIMIT 5;
```

El resultado dice qué fila de la tabla anterior aplica y si existe histórico que conservar.

### Etapa 1: dejar de llamar la ruta y congelar el histórico (sin cambio de esquema)

- Quitar la fase `trazas` de `ORDEN_FASES` y `TEXTOS_FASES`, su código y sus constantes exclusivas. Conservar `CODIGOS_SIN_PERMISO`.
- No editar el DDL de `orden_trazas`, ni siquiera sus comentarios: SQLite los guarda en `sqlite_master` y un esquema nuevo debe ser idéntico a uno migrado (`schema.sql:12-15`).
- Decidir explícitamente si la purga de 400 días sigue aplicando a `orden_trazas`. Quitarla conserva el histórico más allá de sus pedidos; mantenerla prioriza la minimización de datos.
- Lectores: `origen_ventas_aviso` siempre `null`. `origen_ventas` agrega procedencia opcional (`fuente`, `desde_at`, `hasta_at`, `pedidos` distintos) y rotula el balde nulo como «Sin enlace reportado» en lugar de afirmar «Sin enlace compartido».
- Web: retirar `NotaPermisoOrigen` y el texto del permiso; mostrar «histórico hasta {fecha}». Flutter: la rama `sin_permiso` queda inalcanzable.
- Demo: retirar la ruta del transporte falso; una llamada accidental recibe el 404 demo y las pruebas pueden exigir cero llamadas.
- Subir `REV_SNAPSHOT`, porque el snapshot incluye `producto_extendido`.
- Se revierte redeplegando el digest anterior: no hay migración.

### Etapa 2: capturar `trace_info` desde el paso de pedidos

- Sin llamadas nuevas: 202410 ya se consulta por ventana semanal (`hub/creatorhub/sincronizador.py`, `_bajar_ventana`), pero `_insertar_lineas` descarta `trace_info`.
- Migración 007 con una tabla nueva, por ejemplo `orden_lineas_traza(order_id, linea_n, traza_tipo, capturada_at)`, llave `(order_id, linea_n)` y llave foránea compuesta a `orden_lineas` con borrado en cascada, escrita en la misma transacción que las líneas. Una fila presente significa «observada» (estados 1 o 2); su ausencia, «sin dato».
- En pedidos sin cambios, escribir solo si la secuencia `(sku_id, product_id)` guardada coincide con la respuesta; si no, contarlo como `trazas_sin_alinear`. No agregar `trace_info` a la huella del pedido.
- No guardar `trace_info.id` (minimización; el código anterior tampoco guardaba `trace.id`).
- Lectores: bloque actual desde `v_lineas` con la tabla nueva y bloque `historico` opcional desde `orden_trazas`; nunca sumar ambas fuentes para el mismo pedido.
- **Reversión:** la etapa 2 sube `user_version` a 7 y la imagen anterior abriría la base en solo lectura. Antes de desplegarla, tomar un snapshot del disco de datos; el respaldo automático `hub.sqlite.bak-v6` se borra a los 7 días. Mantener `initialize_empty_data_disk=false`.

## Pendiente de verificar

- La respuesta actual de la ruta retirada en la nube y el contenido de `orden_trazas` (etapa 0).
- Si las respuestas reales de 202410 traen `trace_info`, `trace` o ninguno: Corte no las guarda hoy.
- El hub de Windows comparte este código y también llama la ruta cada 30 minutos hasta actualizarse.
