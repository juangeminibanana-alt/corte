# Retiro de `orders/trace/search`: consumidores y conservación del histórico

Revisado el **18 de noviembre de 2026** sobre el código publicado en la nube (`f3f963c`, imagen `corte@sha256:71e0ad75…`). Este documento identifica a cada consumidor del origen de ventas y fija cómo conservar su histórico. Por sí mismo no cambia el comportamiento: la migración corresponde al siguiente incremento.

**Estado (18/11/2026):** la etapa 1 está completa. El backend quedó en `df5ff36`: Corte ya no llama la ruta, `origen_ventas_aviso` siempre va en null y `orden_trazas` queda como histórico cerrado. La web y Flutter ya no tienen la nota del permiso (ni la demo `?trazas=sin_permiso`) y rotulan el bloque como «Histórico hasta {fecha}» cuando llega `origen_ventas.hasta_at`. **La etapa 2 está implementada** (contrato rev. 7, migración 007): ver su sección. Las secciones «Qué hace hoy el backend publicado» y «Consumidores», con sus números de línea, describen `f3f963c`, el código anterior a la etapa 1.

## Estado oficial

- `POST /affiliate_creator/202505/orders/trace/search` quedó **retirada para todos los mercados el 15 de agosto de 2026** según el [aviso oficial](https://partner.tiktokshop.com/docv2/page/si5r1bv3) ("Breaking Change", "Action Required"). TikTok advierte que las llamadas posteriores fallan.
- Reemplazo: `POST /affiliate_creator/202410/orders/search`, que Corte ya llama en el paso de pedidos. Sus filtros son `create_time_ge`/`create_time_lt` en segundos; no existe `time_type` ni filtro por fecha de pago, entrega o liquidación.
- Por línea SKU, 202410 documenta un `trace_info {id, type}` **opcional**. `GENERAL` significa que `id` es el `eid` de un enlace general; `SPECIFIC`, que es un `publisher_id`. No aporta atribución de contenido (eso es `content_type`/`content_id`), nombre del publicador, URL, clics, fecha de liquidación, saldo ni fecha de depósito. La documentación no define qué significa su ausencia.
- El aviso afirma que la respuesta es idéntica, pero los metadatos difieren: `trace` pasa a `trace_info`, el id de pedido pasa de entero a texto, cambian los estados y los filtros de tiempo pasan de milisegundos a segundos (los tiempos de la respuesta de 202505 ya venían en segundos: la muestra trae `1685548800` y el código retirado leía `create_time` como segundos). Según 202505, `actual_commission`/`estimated_commission` incluían bono y recompensa pero no Shop Ads; según 202410 usan la tasa total, que sí incluye Shop Ads (ver [SALES_AND_PAYOUTS.md](SALES_AND_PAYOUTS.md)).
- **No falta ningún permiso de TikTok.** El reemplazo usa `creator.affiliate_collaboration.read`, ya concedido al grant de la nube. Un 105005 en la ruta retirada no se resuelve volviendo a autorizar; no se debe recomendar.

## Qué hace hoy el backend publicado

La fase 5 «trazas» de la ficha completa llama la ruta retirada dentro del paso `productos_ventas` de **cada** sincronización (`hub/creatorhub/sincronizador_ficha.py:23-26, 49, 516-586`). Recorre hasta 5 ventanas de 7 días en una incremental y 13 en una completa, pero solo avanza mientras cada ventana responde código 0: con cualquier error se detiene en la primera. La sincronización automática corre 30 minutos después de que termina la anterior (como máximo unas 48 al día) y la fase no tiene TTL. Es la última de cinco fases, así que no impide las demás. Cada intento fallido deja una fila en `api_errores`.

| Respuesta de TikTok | Efecto en Corte |
| --- | --- |
| 105005 o 16501011 | Una llamada por sincronización y fase `sin_permiso`. La web muestra «requiere un permiso extra en Partner Center» en productos con ventas y sin trazas; las apps Flutter lo muestran, dentro del mosaico «Origen de tus ventas», en cualquier producto sin trazas, aunque no tenga ventas. El mensaje es engañoso: la ruta está retirada. |
| Cualquier otro código sin regla de reintento en `hub/creatorhub/tiktok/politica.py`, o HTTP 4xx con JSON sin código | Una llamada por sincronización y fase `error`, sin aviso visible. |
| HTTP 5xx, 429, cuerpo no JSON (por ejemplo, un 404 HTML), 36009003 o 36009004 | 3 reintentos: 4 llamadas y 4 filas en `api_errores` por sincronización, con esperas de hasta 7 s (unos 3,5 s en promedio). Luego fase `error`. |
| 36009002 o 98001004 | 5 y 2 reintentos (6 y 3 llamadas). 36009002 respeta `Retry-After` hasta 120 s por espera; 98001004 espera hasta 45 s en total. Luego fase `error`. |
| 105001, 105002, 36009005, 101000 o códigos de región | Renovación del token o aborto. Puede marcar la conexión Shop para reautorizar, abortar la sincronización y suspender la automática. Es el caso de mayor riesgo. |
| Código 0 | Recorre las 5 o 13 ventanas (al menos una llamada en cada una) y reescribe las filas del pedido en `orden_trazas`. |

Las respuestas que terminan en fase `sin_permiso` o `error` quedan en `api_errores` (máximo 500 filas, compartidas con el resto de rutas), en `sync_ejecuciones.resumen_json['fases']['trazas']` y en el cursor `trazas.estado`. De ellas, la API solo refleja `sin_permiso`: `origen_ventas_aviso = 'sin_permiso'` en `GET /api/productos/{id}` y en `extras.productos` de `GET /api/snapshot`. El caso de mayor riesgo no llega a `fases.trazas` ni al cursor: queda en `api_errores`, en `sync_ejecuciones.estado`/`error_codigo` y en `auth_estado`, y se ve en `/api/sync/estado`, `/api/sync/historial` y `conexion.estado` de `/api/session`; además escribe un aviso en `logs/hub-AAAAMMDD.log`. Ese registro del hub vive en el disco de la VM y no llega a Cloud Logging, que solo recibe la salida del contenedor (el acceso HTTP). La fase y la tabla datan del 15/11/2026, después del retiro, así que es probable que `orden_trazas` esté vacía en la nube; está pendiente comprobarlo en modo de solo lectura (etapa 0).

## Consumidores

| Papel | Ubicación |
| --- | --- |
| Productor | `hub/creatorhub/sincronizador_ficha.py`: `P_TRAZAS` (49), constantes de la fase (52, 63, 64, 66), `ORDEN_FASES`/`TEXTOS_FASES` (73, 79), `_bajar_trazas` (516-532), `_fase_trazas` (534-581), cursor `trazas.estado` (583-586). `CODIGOS_SIN_PERMISO` (68) **también lo usan las otras fases** y `MAX_PAGINAS_DIRIGIDAS` (65) es de la fase dirigidas: ambos se conservan. |
| Almacenamiento | Tabla `orden_trazas` (`hub/creatorhub/almacen/schema.sql:567-579`, `migraciones/004.sql:124-136`): PK `(order_id, linea_n)`, sin llave foránea. Guarda `traza_tipo`; nunca guardó `trace.id`. Su único escritor borra y vuelve a insertar las filas de un pedido cuando cambian (`sincronizador_ficha.py:565-575`). |
| Borrado | Purga de 400 días en una sincronización completa (`hub/creatorhub/sincronizador.py:1260-1265`). Borrados explícitos del usuario, desconexión con borrado o cambio de cuenta (`TABLAS_TIKTOK`, `hub/creatorhub/almacen/almacen.py:54-60`). La copia en Firebase (exportación local) no incluye esta tabla y la ruta retirada ya no puede repoblarla: además de `hub.sqlite` en el disco `corte-data`, solo la conservan sus snapshots diarios automáticos (`corte-daily-data-snapshot`, rotativos a 14 días), que también guardan durante ese plazo las filas purgadas o borradas. |
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

1. **Registro cerrado.** `orden_trazas` queda como histórico de una fuente retirada. Después de apagar el productor nada la escribe ni la reescribe; solo la vacían la purga de 400 días de la sincronización completa (la misma retención que los pedidos) y los borrados explícitos de usuario o de cuenta.
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
SELECT sync_id, estado, error_codigo, json_extract(resumen_json, '$.fases.trazas') FROM sync_ejecuciones
 ORDER BY sync_id DESC LIMIT 5;
```

El resultado dice qué fila de la tabla anterior aplica y si existe histórico que conservar.

### Etapa 1: dejar de llamar la ruta y congelar el histórico (sin cambio de esquema)

- Quitar la fase `trazas` de `ORDEN_FASES` y `TEXTOS_FASES`, su código y sus constantes exclusivas (52, 63, 64, 66). Conservar `CODIGOS_SIN_PERMISO` y `MAX_PAGINAS_DIRIGIDAS`.
- No editar el DDL de `orden_trazas`, ni siquiera sus comentarios: SQLite los guarda en `sqlite_master` y un esquema nuevo debe ser idéntico a uno migrado (`schema.sql:12-15`).
- Purga de 400 días: **se mantiene** para `orden_trazas` (decisión de la etapa 1). Prioriza la minimización de datos y conserva la misma retención que los pedidos; el histórico se va retirando con la antigüedad de sus pedidos.
- Lectores: `origen_ventas_aviso` siempre `null`. `origen_ventas` agrega procedencia opcional (`fuente`, `desde_at`, `hasta_at`, `pedidos` distintos) y rotula el balde nulo como «Sin enlace reportado» en lugar de afirmar «Sin enlace compartido».
- **Hecho.** Web: sin `NotaPermisoOrigen` ni el texto del permiso; «Histórico hasta {fecha}» solo cuando llega `hasta_at` (un hub anterior no lo envía y la sección queda como antes). Flutter: sin la rama `sin_permiso`, con el mismo rótulo.
- Demo: retirar la ruta del transporte falso; una llamada accidental recibe el 404 demo y las pruebas pueden exigir cero llamadas.
- Subir `REV_SNAPSHOT`, porque el snapshot incluye `producto_extendido`.
- Se revierte redeplegando el digest anterior: no hay migración.

### Etapa 2: capturar `trace_info` desde el paso de pedidos

**Implementada (rev. 7, 18/11/2026).**

- Sin llamadas nuevas: `trace_info` sale de las mismas ventanas semanales de 202410 (`hub/creatorhub/sincronizador.py`, `_bajar_ventana`); `_insertar_lineas` lo lee junto con cada línea.
- Migración 007: tabla `orden_lineas_traza(order_id, linea_n, traza_tipo, capturada_at)` `STRICT`, llave `(order_id, linea_n)` y llave foránea compuesta a `orden_lineas` con borrado en cascada (reescritura de un pedido, purga de 400 días y borrado de los datos de TikTok). Se escribe en la misma transacción que las líneas y solo con ventanas completas. Una fila presente significa «observada»: `traza_tipo` = `trace_info.type` normalizado (`GENERAL`, `SPECIFIC` u otro valor tal cual) o NULL = «sin traza reportada» (sin la clave, `null`, `{}`, tipo vacío o solo `id`). Su ausencia, «sin dato». Un número se guarda como texto, tal cual, y cuenta como enlace (la doc solo define `GENERAL`/`SPECIFIC`). Un tipo que no es texto ni número (lista, objeto, booleano) no escribe fila: no se convierte en «sin traza reportada». La clave retirada `trace` nunca se usa de respaldo.
- Pedidos sin cambios: se descartó alinear la secuencia `(sku_id, product_id)` guardada con la respuesta (la doc no garantiza el orden de las filas y la misma SKU puede repetirse). Si un pedido completo sin cambios todavía no tiene ninguna fila de traza, se reescriben sus líneas **y** sus trazas desde la misma respuesta, una sola vez, sin contarlo como pedido cambiado ni tocar su huella. El barrido completo (400 días; la sincronización automática lo hace en cuanto pasan 7 días desde el anterior) rellena así todos los pedidos que TikTok sigue devolviendo; uno que ya no devuelve (`NO_DEVUELTA`) nunca se vuelve a observar. Un pedido cuyas líneas traen todas un tipo no textual se vuelve a intentar en cada sincronización, sin efecto en las cifras. `trace_info` no entra en la huella.
- No se guarda `trace_info.id` (minimización: en GENERAL es un id por clic de quien creó el enlace; en SPECIFIC, un `publisher_id`).
- Diagnóstico sin guardar respuestas: `sync_ejecuciones.resumen_json.trazas_202410` cuenta líneas observadas y escritas, `por_tipo` (con `SIN_TRAZA`), `tipo_no_textual`, `id_sin_tipo`, `clave_trace_info` (líneas que traen la clave, aunque sea `null` o `{}`: separa «TikTok no manda el campo» de «lo manda vacío», que en `por_tipo` caen juntos en `SIN_TRAZA`), `clave_trace_antigua` y `pedidos_rellenados`.
- Lectores: `ProductoExtendido.origen_ventas_actual` (contrato rev. 7, ETag del snapshot `-f5-`) cuenta las mismas líneas que `v_lineas` (todos los estados, como el histórico) que tienen fila, **sin** los pedidos que ya están en `orden_trazas`: esos se quedan solo en el bloque histórico, así que ningún pedido cuenta en los dos y nunca se suman. Las líneas sin fila van aparte como `lineas_sin_dato`, y solo las de pedidos creados desde el inicio del periodo del bloque que TikTok todavía devuelve: las anteriores esperan al barrido completo y un `NO_DEVUELTA` no se volverá a observar. La web y Flutter muestran el bloque actual antes del histórico y solo si TikTok reportó al menos un enlace (`con_enlace > 0`): Corte no crea enlaces y un bloque entero de «Sin enlace reportado» no dice de dónde vino ninguna venta. Con los dos bloques a la vista, cada gráfica nombra su bloque y cada tipo de enlace conserva su color en las dos barras.
- **Reversión (corregida):** la imagen anterior **no arranca** con una base en `user_version` 7: la abre en solo lectura y el hub falla al iniciar (`local.sembrar()` → `base_de_version_nueva`). Volver atrás requiere una imagen de vuelta atrás construida antes del despliegue (el código anterior más un paso que copia la base a `hub.sqlite.bak-v7`, comprueba que la única diferencia sea `orden_lineas_traza`, la borra y regresa a `user_version` 6), o restaurar el snapshot manual. Antes de desplegar, tomar ese snapshot manual del disco de datos: los automáticos rotan a los 14 días y el respaldo `hub.sqlite.bak-v6` se borra a los 7. Mantener `initialize_empty_data_disk=false`.

## Pendiente de verificar

- La respuesta actual de la ruta retirada en la nube y el contenido de `orden_trazas` (etapa 0).
- Si las respuestas reales de 202410 traen `trace_info`, `trace` o ninguno, y con qué tipos: lo dirán `clave_trace_info`, `clave_trace_antigua` y `por_tipo` en `resumen_json.trazas_202410` de la primera sincronización con la rev. 7, sin guardar las respuestas. Si aparece `id_sin_tipo > 0`, decidir el tratamiento con esa forma real y borrar esas filas NULL para que el relleno las vuelva a leer.
- Clientes Windows: los paquetes publicados 1.1.x (`CreatorHub.exe` en modo `cliente_nube` desde `a066bd7`) y 2.0.0 (Flutter) son clientes de la nube: no ejecutan la sincronización local ni llaman a la API de TikTok Shop, así que basta con desplegar la etapa 1 en la nube. Solo una instalación 1.0.3 sin actualizar, con conexión propia de TikTok Shop y sincronización automática, seguiría llamando la ruta; eso se resuelve instalando una versión ya publicada. Falta confirmar si queda alguna activa.
