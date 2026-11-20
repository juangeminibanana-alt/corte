# Publicar un video de TikTok Shop desde CUTGC

El backend permite subir un video desde el dispositivo, vincularlo a un producto, enviarlo a TikTok Shop y consultar el resultado. La carga devuelve un `file_id` que se usa al preparar la publicación. [Guía de videos comprables de TikTok Shop](https://partner.tiktokshop.com/docv2/page/ng0l9170) · [Carga del archivo](https://partner.tiktokshop.com/docv2/page/upload-shoppable-video-file-202505).

## Rutas de CUTGC

| Método y ruta | Qué hace |
|---|---|
| `GET /api/publicaciones/shop/capacidades` | Informa si hay una cuenta Creator conectada y si tiene el permiso `creator.video.write`. |
| `POST /api/publicaciones/shop/archivo` | Recibe un solo campo multipart `archivo` de menos de 10 MiB y devuelve `file_id`. |
| `POST /api/publicaciones/shop/archivo/iniciar` | Para 10 a 500 MiB, recibe JSON con `nombre` y `bytes`. Devuelve `carga_id` y número de `partes`. |
| `PUT /api/publicaciones/shop/archivo/{carga_id}/partes/{numero}` | Recibe una parte binaria con tipo `application/octet-stream`. La última devuelve `file_id`. |
| `POST /api/publicaciones/shop/preparar` | Valida los datos y devuelve el cuerpo que recibiría TikTok junto con los permisos de la cuenta. Se puede usar antes de obtener el permiso. |
| `POST /api/publicaciones/shop/publicar` | Requiere cuenta Creator autorizada, permiso de escritura y el campo adicional `"confirmar": true`. Al aceptar TikTok la solicitud, devuelve `video_id`, `estado: "aceptada"` y `cuota` si la comunica el proveedor. |
| `GET /api/publicaciones/shop/{video_id}/estado` | Consulta el resultado para la cuenta autorizada. Devuelve el ID, el estado y, cuando corresponde, la fecha de publicación. |

Las rutas de la nube requieren sesión. Para cargar, publicar o consultar el estado se necesita la sesión del propietario de CUTGC con Firebase, desde la web o la app. El cliente envía en `X-Corte-Cache-Scope` el `cache_scope` actual de `GET /api/cloud/revision`. Si la cuenta cambió antes del envío, el cliente recibe HTTP 409 y debe volver a mostrar la cuenta activa.

La carga directa admite MP4, MOV, MKV, WMV, WebM, AVI, 3GP, FLV y MPEG. Para verificación de integridad se compara el MD5 cuando TikTok lo devuelve. Para los videos de 10 a 500 MiB, el servicio de TikTok acepta MP4, MOV y WebM. CUTGC envía las partes en orden y entrega el ID cuando TikTok termina de unirlas. Para la parte `i` (contando desde 1), los límites son `floor((i-1)*bytes/partes)` y `floor(i*bytes/partes)`, excluyendo el último byte de ese intervalo. La sesión de transferencia vive en memoria durante la carga. Tras una interrupción que requiera una sesión nueva, el usuario puede volver a seleccionar el archivo. [Inicio de la carga por partes](https://partner.tiktokshop.com/docv2/page/upload-file-init-202512) · [Guía de archivos grandes de TikTok Shop](https://partner.tiktokshop.com/docv2/page/wfi3nz36).

## Preparación y seguimiento

Ejemplo ficticio para **preparar**. El campo `titulo` contiene el texto del video y admite hasta 4000 unidades UTF-16. El público verá `titulo_ancla` en el enlace al producto. CUTGC valida de 1 a 29 caracteres en esa etiqueta, con letras, números y espacios.

```json
{
  "file_id": "v12d00gd0024d3nfqr7og65",
  "titulo": "Así queda el vestido de lino en movimiento",
  "product_id": "1234567890123456789",
  "titulo_ancla": "Vestido de lino",
  "is_ai_generated": false
}
```

La respuesta muestra `payload.video_info`, `payload.product_link_info` y `autorizacion`. Después de revisar el texto y el producto, el cliente puede enviar los mismos campos de entrada a **publicar** y agregar `confirmar: true`. TikTok recibe `POST /affiliate_creator/202607/videos`. Guardar el `video_id` permite consultar `GET /affiliate_creator/202509/videos/{video_id}/status`. [Contrato oficial de publicación](https://partner.tiktokshop.com/docv2/page/post-shoppable-video-202607) · [Metadatos de la versión 202607](https://partner.tiktokshop.com/api/v1/document/api_meta?src_document_id=post-shoppable-video-202607&workspace_id=3&aid=359713&locale=en).

| TikTok Shop | Estado en CUTGC | Acción del cliente |
|---|---|---|
| Solicitud aceptada con ID | `aceptada` | Conservar el ID y consultar su estado. |
| `PROCESSING` | `procesando` | Volver a consultar el estado más tarde. |
| `SUCCESS` | `publicada` | Mostrar `publicado_en` si se recibió, expresado en segundos Unix. |
| `FAIL` | `fallida` | Informar que TikTok terminó el proceso con un fallo. |

La respuesta de aceptación puede incluir la cuota de esa cuenta como texto. TikTok determina su valor. [Publicación y cuota](https://partner.tiktokshop.com/docv2/page/post-shoppable-video-202607) · [Estados del video](https://partner.tiktokshop.com/docv2/page/get-shoppable-video-status-202509).

El registro distingue los intentos por cuenta y archivo. Si la aceptación ya quedó guardada, repetir la misma solicitud devuelve el ID registrado. Una solicitud en curso, un resultado incierto o un cambio de datos para el mismo archivo puede devolver `409 conflicto`. Si después de iniciar el envío se pierde la conexión, cambia la cuenta o falla el guardado de la aceptación, CUTGC responde `503 publicacion_sin_confirmar`. El cliente debe comprobar el resultado en la cuenta de TikTok desde la que se envió el video.

## Programar y cancelar un envío

Después de cargar el video y revisar el producto, el creador elige una fecha y confirma la publicación. La nube guarda esa autorización para su cuenta de TikTok Shop. El planificador revisa la agenda cada 30 segundos y toma el siguiente video vencido. Puede enviarlo con la aplicación cerrada. Si la nube se reinicia, recupera los envíos pendientes al volver a arrancar.

| Método y ruta | Cuerpo y resultado |
|---|---|
| `POST /api/publicaciones/shop/agenda` | Acepta los mismos datos que publicar, con `confirmar: true` y `programada_at` en segundos Unix. Devuelve la fila programada con su `id`. |
| `GET /api/publicaciones/shop/agenda` | Devuelve `items` de la cuenta seleccionada con fecha, producto, título y estado. |
| `POST /api/publicaciones/shop/agenda/{id}/cancelar` | Recibe `{}` y devuelve la fila cancelada. Se puede cancelar mientras el video sigue programado. |

Las tres rutas requieren la sesión del propietario y el mismo `X-Corte-Cache-Scope` que la publicación inmediata. La agenda conserva la consulta y la cancelación para el creador identificado incluso si tiene que renovar sus permisos. Un envío aceptado incluye `video_id` para consultar el resultado de TikTok. El estado `por_verificar` pide revisar el perfil original antes de intentar otra publicación.

## Permisos, videos sociales y borrado

Para registro y mercado **México**, el catálogo público de Partner Center devolvió `available: true` el 20 de noviembre de 2026 para cargar el archivo, publicar y consultar el estado. Mostró dos categorías en las tres operaciones, **Shoppable Content** para desarrolladores y **TikTok Shop Seller** para aplicaciones internas de vendedores. [Categorías de carga en México](https://partner.tiktokshop.com/api/v1/document/apis/7502362897129981697/callable_categories?registration_country=MX&target_market=MX) · [Categorías de publicación](https://partner.tiktokshop.com/api/v1/document/apis/7502333053755541265/callable_categories?registration_country=MX&target_market=MX) · [Categorías de consulta de estado](https://partner.tiktokshop.com/api/v1/document/apis/7554323543954228993/callable_categories?registration_country=MX&target_market=MX).

El backend de CUTGC admite una cuenta Creator que haya concedido `creator.video.write`. La ruta de capacidades refleja el permiso en su autorización local. Los seis permisos registrados en la revisión del 16 de noviembre no incluían ese alcance. Falta verificar la categoría y la autorización actuales de CUTGC en Partner Center y probar el envío completo con una cuenta autorizada. [Autorizaciones registradas](API_COVERAGE.md#autorizaciones-verificadas) · [Integración de afiliados](https://partner.tiktokshop.com/docv2/page/affiliate-integration).

TikTok for Developers tiene otro flujo. Con `video.upload`, el creador recibe el video y completa la publicación en TikTok. Con `video.publish`, Direct Post requiere consentimiento del creador y su elección de privacidad. La publicación pública está sujeta a auditoría y TikTok excluye de sus usos aceptables las herramientas creadas únicamente para subir contenido a cuentas propias o del equipo. CUTGC utiliza Display para lectura y métricas. Integrar la publicación social queda pendiente. [Permisos oficiales](https://developers.tiktok.com/docs/en/tiktok-api-scopes) · [Carga de borradores](https://developers.tiktok.com/docs/en/content-posting-api-reference-upload-video) · [Directrices de publicación](https://developers.tiktok.com/docs/en/content-sharing-guidelines).

TikTok documenta `video.manage` para editar o eliminar publicaciones de las que el usuario es propietario. Antes de incorporar el borrado de videos hay que verificar el acceso de CUTGC al producto, el permiso concedido y el contrato de esa operación. El borrado de un video en TikTok sigue pendiente. Quitar un producto de la vitrina y borrar un registro local tienen efectos distintos. [Permisos de TikTok for Developers](https://developers.tiktok.com/docs/en/tiktok-api-scopes).

## Prueba local

Desde la raíz del repositorio y con las dependencias de `cloud/requirements.txt` instaladas en el entorno de la nube, estas pruebas usan cuentas y respuestas simuladas.

```powershell
.\.venv-cloud\Scripts\python.exe -m unittest discover -s cloud/tests -p "*publicaci*.py"
```
