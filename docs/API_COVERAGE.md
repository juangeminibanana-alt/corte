# Cobertura de APIs de producto, muestras y contenido

Verificado el **16 de noviembre de 2026** contra el catálogo público V2 y los metadatos oficiales de TikTok Shop. Este documento describe la integración de Corte y sus límites comprobados; no presupone acceso a APIs privadas o habilitadas individualmente por TikTok.

## Fuentes y método

El [índice público V2 oficial](https://partner.tiktokshop.com/api/v1/document/tree?workspace_id=3&aid=359713&locale=en) devolvió 1.036 documentos. La rama **Affiliate creator** contiene 26 operaciones y una página de introducción. Se consultaron los metadatos oficiales de las 26 operaciones, incluidas sus rutas, métodos, campos de respuesta y scopes. El parámetro `workspace_id=3` corresponde a la documentación global V2; omitirlo devuelve un índice legado más pequeño y no permite auditar el catálogo actual.

Cada página oficial ofrece los mismos metadatos mediante `GET /api/v1/document/api_meta`, con `src_document_id` igual a su slug. Por ejemplo, [metadatos de Check Creator Sample Eligibility](https://partner.tiktokshop.com/api/v1/document/api_meta?src_document_id=check-creator-sample-eligibility-202412&workspace_id=3&aid=359713&locale=en). No se usaron especificaciones de terceros como evidencia de disponibilidad.

Se contrastó además el código de sincronización y el contrato de Corte con su versión original. No se encontró una implementación anterior de reseñas que hubiera sido retirada al conectar la nube.

## Autorizaciones verificadas

- La conexión original almacenada con DPAPI fue inspeccionada en modo de solo lectura: sus permisos OAuth pertenecen a la familia **Creator** y no incluyen scopes **Seller**. No se modificó la fuente ni se publicaron credenciales, identificadores o datos de cuenta.
- Se verificó además el **grant cloud actual** en una lectura autenticada de `/api/session`: conexión activa con `creator.affiliate.info`, `creator.affiliate.link.write`, `creator.affiliate.share_link.read`, `creator.affiliate_collaboration.read`, `creator.showcase.read` y `creator.showcase.write`. No contiene scopes Seller. No se renovó ni modificó la autorización durante la comprobación.
- `GET /api/session` → `cuenta.permisos` contiene capacidades del perfil de creador. **No es la lista de scopes OAuth.**
- Los headers oficiales distinguen token de creador (`user_type=1`) y token de vendedor (`user_type=0`). Añadir una ruta Seller al cliente no concede acceso a ella: exige su autorización y, cuando corresponda, `shop_cipher`.

## Rutas de la aplicación y datos conectados

Las rutas de lectura de Corte consultan SQLite. Las llamadas a TikTok de esta tabla se realizan durante la sincronización; abrir una ficha no dispara todas estas consultas externas.

| Ruta o módulo de Corte | Método y ruta oficial TikTok | Datos utilizados | Límites relevantes |
|---|---|---|---|
| `/api/session`, perfil | [GET `/affiliate_creator/202508/profiles`](https://partner.tiktokshop.com/docv2/page/get-creator-profile-202508) | Perfil y capacidades del creador | No incluye catálogo de variantes ni reseñas. |
| `/api/muestras`, detalle de muestra | [POST `/affiliate_creator/202412/sample_applications/search`](https://partner.tiktokshop.com/docv2/page/search-creator-sample-applications-202412) | Solicitudes, producto y estado | La variante de una solicitud no equivale al catálogo completo de variantes. |
| `/api/muestras/{application_id}`, solicitudes recuperadas | [POST `/affiliate_creator/202412/sample_applications/single_query`](https://partner.tiktokshop.com/docv2/page/get-creator-sample-application-detail-202412) | Detalle, SKU y nombres de la variante solicitada | Describe la solicitud concreta. |
| Muestras y compromisos de publicación | [POST `/affiliate_creator/202409/sample_applications/fulfillments/search`](https://partner.tiktokshop.com/docv2/page/creator-search-sample-application-fulfillments-202409) | Cumplimiento, plazos y contenido asociado | No es una API de opiniones de compradores. |
| `/api/productos`, `/api/productos/{product_id}` | [POST `/affiliate_creator/202509/open_collaborations/products`](https://partner.tiktokshop.com/docv2/page/get-open-collaboration-product-list-by-product-ids-202509) | Título, tienda, `main_image_url`, categoría, precios, inventario general y comisión | Solo una imagen principal; la respuesta documentada no incluye galería, reseñas, descripción completa ni imágenes por SKU. Puede omitir productos solicitados. |
| Ficha → productos parecidos | [POST `/affiliate_creator/202405/open_collaborations/products/search`](https://partner.tiktokshop.com/docv2/page/search-open-collaboration-products-202405) | Productos del marketplace, foto principal, precios y comisión | La búsqueda por palabras no garantiza equivalencia entre productos. No añade fotos de compradores ni catálogo de SKU. |
| Ficha → galería y precios de vitrina | [GET `/affiliate_creator/202405/showcases/products`](https://partner.tiktokshop.com/docv2/page/get-showcase-products-202405) | `products[].main_images[]`, precios, inventario y estado de vitrina | Corte usa `origin=SHOWCASE`. La galería disponible corresponde a productos de esa vitrina. `review_status` es moderación del producto, **no reseñas de compradores**. |
| Ficha → variantes de muestra | [GET `/affiliate_creator/202412/samples/labels`](https://partner.tiktokshop.com/docv2/page/check-creator-sample-eligibility-202412) | Elegibilidad y `label.sample_product.sample_sku_list[]` | No garantiza devolver todos los SKU comerciales; puede responder `UNKNOWN`, `can_apply=false` y lista vacía. No incluye una foto por color. |
| Ficha → planes dirigidos | [POST `/affiliate_creator/202405/target_collaborations/search`](https://partner.tiktokshop.com/docv2/page/search-creator-target-collaborations-202405) | Planes, estados y comisiones por producto | Requiere la tienda correspondiente; no completa variantes o reseñas. |
| `/api/ordenes`, ventas de producto/video/tienda | [POST `/affiliate_creator/202410/orders/search`](https://partner.tiktokshop.com/docv2/page/search-creator-affiliate-orders-202410) | Líneas, importes, comisiones y atribución disponible | Las ventas de una variante no enumeran las variantes que no se vendieron. |
| Ficha → origen de ventas | [POST `/affiliate_creator/202505/orders/trace/search`](https://partner.tiktokshop.com/docv2/page/search-affiliate-orders-by-creator-202505) | Trazas y origen | Integrado con manejo explícito de errores de permiso. No inferir el permiso actual desde notas antiguas del repositorio. |

Son **11 operaciones de lectura conectadas**. La fase de etiquetas tiene TTL de 72 horas y un máximo de 60 productos por sincronización; las galerías se obtienen al sincronizar la vitrina. Una fase omitida por TTL no demuestra un permiso denegado.

### Forma de las variantes

Los metadatos oficiales de `samples/labels` documentan:

```text
label.sample_product.sample_sku_list[]
  id
  sale_properties[]: id, name, value_id, value_name
  price: amount, currency
  is_available
  unavailable_reason
```

Corte conserva propiedades como `{nombre: "Color", valor: "Azul"}` y `{nombre: "Talla", valor: "M"}`, la variante unida, precio y disponibilidad. No debe asignar una foto de la galería a un color por posición o similitud: el endpoint no entrega esa asociación.

Una lista vacía de SKU de muestra significa que esta consulta no aportó variantes. **No demuestra que el producto carezca de otros colores o tallas.** La variante ya elegida de una muestra se conserva independientemente de esa lista.

### Fotos y copia sin conexión

- La foto principal del producto usa `/img/p/{product_id}`. La galería de vitrina usa `/img/g/{product_id}-{indice}`, hasta 12 fotos, respetando su orden.
- El proveedor también documenta `addition.customized_main_images[]` en la vitrina. Corte no lo integra como una galería adicional; no se confirmó que explique un caso de fotos ausentes. Es un campo pendiente de aprovechamiento, no una API de reseñas ni una asociación foto–SKU.
- Desde la representación `f1`, `/api/snapshot` incluye `extras.productos` con hasta 100 `ProductoExtendido` ya almacenados y representados en la copia. Prioriza muestras pendientes; no consulta TikTok ni descarga todo el catálogo para construir el snapshot.
- **Solo las imágenes ya descargadas y versionadas** entran en `meta_imagenes` y `imagenes[]` para la precarga móvil. Las fotos diferidas conservan una ruta `?v=0`; necesitan conexión al solicitarse por primera vez. No se prometen todas las galerías disponibles sin conexión ni una precarga de 1.200 imágenes.
- El ETag `W/"dv…-lr…-ir…-f1"` distingue esta representación de las copias anteriores. Una copia antigua recibe el nuevo cuerpo aunque las versiones de datos no hayan cambiado. `version_esquema` sigue siendo `1`; `img_rev` del cuerpo es autoritativo.

Las portadas de video provienen de la autorización separada [TikTok Display API](https://developers.tiktok.com/docs/en/tiktok-api-v2-video-object). Esa conexión no concede permisos para variantes o reseñas de TikTok Shop. Una foto de producto nunca debe presentarse como portada del video.

## Las otras 15 operaciones del catálogo Creator

Estas completan las 26 operaciones públicas verificadas. Ninguna es una consulta general de detalle comercial con fotos por SKU ni una API de reseñas de compradores.

| Método y ruta | Función y situación en Corte |
|---|---|
| [POST `/affiliate_creator/202405/showcases/products/add`](https://partner.tiktokshop.com/docv2/page/add-showcase-products-202405) | Agregar a vitrina; no implementado. Es una mutación. |
| [DELETE `/affiliate_creator/202409/showcases/products`](https://partner.tiktokshop.com/docv2/page/remove-showcase-products-202409) | Quitar de vitrina; no implementado. Es una mutación. |
| [POST `/affiliate_creator/202409/showcases/products/top`](https://partner.tiktokshop.com/docv2/page/move-showcase-products-to-the-top-202409) | Fijar productos; no implementado. Es una mutación. |
| [POST `/affiliate_creator/202505/affiliate_sharing_links/general_publishers/generate_batch`](https://partner.tiktokshop.com/docv2/page/generate-general-sharing-links-202505) | Generar enlaces de afiliación; no implementado. |
| [POST `/affiliate_creator/202504/affiliate_sharing_links/publisher/{publisher_id}/generate_batch`](https://partner.tiktokshop.com/docv2/page/generate-publisher-sharing-links-in-batch-202504) | Generar enlaces para un publisher; no implementado. |
| [POST `/affiliate_creator/202505/videos/video_files`](https://partner.tiktokshop.com/docv2/page/upload-shoppable-video-file-202505) | Subir video comprable; no implementado. Requiere `creator.video.write`. |
| [GET `/affiliate_creator/202509/shop_products`](https://partner.tiktokshop.com/docv2/page/get-shop-products-202509) | Productos de la **tienda vinculada al creador**, que debe existir. Requiere `creator.video.write`; no integrado. Entrega imágenes, título, precio, marca y ventas; no SKU ni reseñas. No es una consulta de cualquier producto afiliado. |
| [GET `/affiliate_creator/202509/videos/{video_id}/status`](https://partner.tiktokshop.com/docv2/page/get-shoppable-video-status-202509) | Estado de publicación; no implementado. |
| [POST `/affiliate_creator/202511/videos/precheck_task`](https://partner.tiktokshop.com/docv2/page/create-video-precheck-task-202511) | Revisión previa de video; no implementado. |
| [GET `/affiliate_creator/202601/videos/precheck_tasks/{task_id}`](https://partner.tiktokshop.com/docv2/page/get-shoppable-video-precheck-result-202601) | Resultado de la revisión previa; no implementado. |
| [POST `/affiliate_creator/202511/photos/photo_files`](https://partner.tiktokshop.com/docv2/page/upload-shoppable-photo-file-202511) | Subir contenido fotográfico comprable; no implementado. No obtiene fotos de compradores. |
| [POST `/affiliate_creator/202603/videos`](https://partner.tiktokshop.com/docv2/page/post-shoppable-video-202603) | Publicar video comprable; no implementado. |
| [GET `/affiliate_creator/202606/toko_product_mappers`](https://partner.tiktokshop.com/docv2/page/map-tokopedia-to-tiktok-shop-product-ids-202606) | Mapeo de identificadores Tokopedia; no implementado, no completa fichas de México. |
| [POST `/affiliate_creator/202607/map_toko_product`](https://partner.tiktokshop.com/docv2/page/get-tokopedia-and-tiktok-shop-product-id-mappings-202607) | Mapeo Tokopedia/TikTok Shop; no implementado. |
| [POST `/affiliate_creator/202610/photos`](https://partner.tiktokshop.com/docv2/page/post-shoppable-photos-202610) | Publicar fotos comprables; no implementado. No consulta fotos de reseñas. |

## Otras familias: qué ofrecen y qué no demuestra su existencia

| API o capacidad oficial | Datos documentados | Condiciones y límite para Corte |
|---|---|---|
| [Seller Get Product](https://partner.tiktokshop.com/docv2/page/get-product-202309): GET `/product/202309/products/{product_id}` | Descripción, `main_images`, SKU con `sales_attributes` e imágenes `sku_img`, inventario y guía de tallas | Requiere token **Seller**, `seller.product.basic` y `shop_cipher`. No está integrado. No se puede utilizar con la autorización Creator original ni para acceder libremente a productos de otras tiendas. Su respuesta documentada tampoco incluye reseñas. |
| [Get Product SKPP Detail](https://partner.tiktokshop.com/docv2/page/get-product-skpp-detail-202606): GET `/product/202606/skpps/{product_id}` | Puntuación del programa SKPP, tareas y recompensas | Seller autorizado para SKPP en **Estados Unidos**. No es una API nueva de catálogo de SKU. |
| [Get Bestselling Products](https://partner.tiktokshop.com/docv2/page/get-bestselling-products-202511): GET `/analytics/202511/products/bestselling` | Ranking por GMV de hasta 100 productos; foto y `rating` agregado | Los metadatos exigen token **Seller**, `shop_cipher` y `data.bestselling.public.read`. La palabra `public` del scope no convierte un token Creator en válido. No está integrado, no enumera SKU y no devuelve texto o fotos de reseñas. |
| [Categoría Customer Reviews](https://partner.tiktokshop.com/docv2/page/hulvi36o) | TikTok documenta herramientas de gestión de reseñas para vendedores | La guía indica que algunas capacidades requieren habilitación de plataforma. No demuestra que estén disponibles para una app Creator, su mercado o su grant actual. No se debe afirmar que toda API de reseñas sea universalmente inexistente. |
| [Research: Query TikTok Shop Reviews](https://developers.tiktok.com/docs/en/research-api-specs-query-tiktok-shop-reviews): POST `/v2/research/tts/review/` | Texto, valoración, likes, fecha y nombre del producto | Requiere `research.data.basic` y token de cliente de Research. La respuesta cubre productos disponibles en la UE y no documenta fotos de reseñas. No corresponde al flujo Creator comercial de Corte. |

En el catálogo público V2 consultado, las operaciones cuyo nombre contiene `review` corresponden a decisiones de posventa, revisión de campañas o aprobación de muestras. No se identificó una operación pública Creator que entregue opiniones o fotos de compradores. Esto no excluye capacidades privadas o habilitadas individualmente por TikTok.

## Estado que puede afirmarse

**Implementado:** datos de muestra, variante solicitada, variantes que devuelva `samples/labels`, foto principal, galería de vitrina y conservación de fichas extendidas en la copia móvil.

**Vía pública adicional en 2.2.0:** `POST /api/productos/{id}/extraer` consulta el HTML publicado de la ficha MX, sin cookies ni una API privada. Obtiene su imagen de guía de tallas y la vista previa de reseñas con fotos, cuando la página los proporciona. Caso real comprobado: tabla ×1, opiniones ×3 de 60 y fotos ×5. Guarda procedencia y fecha y conserva datos anteriores ante errores o verificaciones. Esta fuente es distinta de los contratos oficiales Creator enumerados arriba.

**No implementado:** recuperación de todo el historial de reseñas; imágenes asociadas a cada color; ficha comercial Seller completa; aprovechamiento de imágenes personalizadas adicionales de vitrina.

Los [detalles de tablas de tallas, reseñas y fotografías de compradores](PRODUCT_SIZE_CHARTS_AND_REVIEWS.md) documentan la fuente pública comprobada y sus límites para Android, Windows y web. Una sección vacía o un enlace externo no completa esa integración.

**No verificado o no concedido por la evidencia disponible:** una vía Creator alternativa para enumerar todos los colores cuando `samples/labels` devuelve una lista vacía; acceso de la conexión cloud actual a capacidades Seller o privadas de reseñas. No presentar un campo vacío, un placeholder o un enlace Seller inaccesible como si completara esas funciones.
