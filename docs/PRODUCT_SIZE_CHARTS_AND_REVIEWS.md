# Tablas de tallas y reseñas por producto

Requisito del usuario del 16 de noviembre de 2026 para Corte en Android, Windows y web. Implementación **2.2.0**: consulta de la ficha pública de TikTok Shop México, persistencia por cuenta y visualización de su tabla y vista previa de reseñas con sus propias fotos. La extracción pública no equivale a recibir todo el historial de opiniones.

## Implementación y límites

- `POST /api/productos/{product_id}/extraer`, con revisión vigente y vínculo del creador, consulta el enlace público observado `https://shop.tiktok.com/mx/pdp/{product_id}`. No necesita contraseña, cookies o permisos Seller y no utiliza una API privada de reseñas.
- El extractor lee datos publicados en el HTML de esa ficha: `product_info.size_guide.image.url_list`, `review_info.product_reviews`, `review_ratings` y el total declarado. Se comprobó con un producto real: una tabla legible, tres opiniones de sesenta y cinco fotos de compradores asociadas correctamente.
- La interfaz ofrece **Obtener tallas y reseñas** desde producto y muestra, imagen original ampliable, procedencia/fecha y aviso explícito de vista previa. Conserva texto, valoración, variante y fecha recibidos. La compra verificada sólo se muestra si la fuente entrega ese indicador expresamente.
- Límites de lectura: 15 segundos, 4 MiB y tres redirecciones verificadas dentro del mismo producto/host/mercado. Una verificación o un error detiene la consulta y conserva los datos guardados. No se promete acceso a todas las fichas ni a todas las opiniones de TikTok.
- El backend conserva hasta cien opiniones recibidas, con páginas de veinte; esto no significa que el HTML público entregue cien. La respuesta real comprobada sólo entrega tres. Las imágenes siguen el proxy privado `/img/e/…` y la caché por propietario y creador.
- La sesión de navegador que el usuario verificó se conserva en el mismo perfil/pestaña. El extractor del servidor es independiente de ella; no se exportan cookies de TikTok a Google ni a Git. TikTok puede volver a solicitar una verificación.

## Resultado esperado

Cada ficha debe permitir consultar:

1. **Tabla de tallas del producto**, cuando corresponda: medidas y unidades del vendedor, o su imagen original ampliable. Una lista de variantes S/M/L no sustituye la tabla. No usar una tabla genérica de ropa ni estimar medidas.
2. **Reseñas reales** del mismo producto: texto, calificación, fecha y variante comprada cuando la fuente las entregue. Mostrar promedio y cantidad sólo si proceden de esa fuente; no calcular el total a partir de una página parcial.
3. **Fotos de compradores** vinculadas a su reseña, ampliables y diferenciadas de las fotos del catálogo. Una foto del vendedor no se puede reutilizar como foto de comprador.

La información debe ser accesible desde la ficha del producto y desde la muestra correspondiente. Mantener el diseño aprobado de Android y la composición de escritorio de Windows, con temas claro y oscuro, texto escalable y navegación por teclado. Las tablas anchas pueden desplazarse horizontalmente dentro de su sección; no deben desbordar la pantalla.

## Fuente y estado comprobados

- La conexión **cloud actual** fue consultada en modo de sólo lectura mediante `/api/session`: está conectada y su grant contiene exclusivamente `creator.affiliate.info`, `creator.affiliate.link.write`, `creator.affiliate.share_link.read`, `creator.affiliate_collaboration.read`, `creator.showcase.read` y `creator.showcase.write`. No contiene scopes Seller. No se renovó ni modificó la autorización.
- Se revisaron los campos completos de las 26 operaciones del catálogo público Affiliate Creator. Los contratos consultados no declaran tablas de medidas ni opiniones/fotos de compradores para los productos afiliados.
- Los SKU actuales proceden de `samples/labels` y sus propiedades de color/talla. La galería procede de `showcases/products`. Ninguno de esos datos demuestra que se haya obtenido una tabla de medidas o una reseña.
- La base original y la base local actual no contienen una integración de tablas de tallas o reseñas que se haya perdido durante la migración. Esto describe el código y los datos inspeccionados; no sustituye el requisito nuevo.
- La URL genérica inicial mostró un CAPTCHA. Tras completarlo el usuario se identificó la URL pública canónica de México; tanto esa URL como la ruta numérica publicada por TikTok respondieron HTTP 200 a una petición normal sin cookies. Se verificaron el HTML, el normalizador, el contrato de guardado y la imagen real. El estado de una URL genérica no debe extrapolarse a la ficha canónica comprobada.

### Rutas oficiales que no equivalen al acceso actual

| Fuente | Datos documentados | Condición |
| --- | --- | --- |
| [Get Product](https://partner.tiktokshop.com/docv2/page/get-product-202309), `GET /product/202309/products/{product_id}` | `size_chart.image.urls`, `size_chart.template.id`, descripción y datos del producto | Token Seller, `seller.product.basic` y `shop_cipher` de la tienda propietaria. No permite completar productos ajenos con un token Creator. |
| [Search Size Charts](https://partner.tiktokshop.com/docv2/page/search-size-charts-202407), `POST /product/202407/sizecharts/search` | Tablas estructuradas e imágenes de las tablas creadas por ese vendedor | Mismo acceso Seller; la selección de idioma `es-MX` no concede acceso a otras tiendas. |
| [Customer Reviews](https://partner.tiktokshop.com/docv2/page/hulvi36o) | TikTok documenta herramientas para vendedores | No se ha verificado una capacidad concedida a Corte que entregue reseñas/fotos de productos afiliados. La existencia de la categoría no demuestra ese acceso. |
| [Research Shop Reviews](https://developers.tiktok.com/docs/en/research-api-specs-query-tiktok-shop-reviews) | Texto, estrellas, fecha y likes; no documenta fotos | Research aprobado y productos disponibles en la UE; no resuelve el uso comercial Creator de Corte en México. |

El esquema vigente de tablas estructuradas usa `data.size_chart[].size_chart_datas[].size_chart_data.table.headers[]` y `table.rows[].cells[].value`, junto con `unit_system`, `measurement_type`, `is_one_size`, `description` y `images[]`. No implementar el antiguo ejemplo `table.contents` como si fuera el contrato vigente.

## Condiciones para implementar y aceptar la función

- Obtener primero una respuesta real de una fuente autorizada, comprobando producto, mercado y permisos. Una autorización Seller sólo cubre los productos de esa tienda; no resuelve por sí sola el catálogo afiliado de otras tiendas.
- Registrar fuente, producto, fecha de consulta y estado por separado para tabla, reseñas y sus imágenes. Distinguir datos disponibles, consulta pendiente, acceso no disponible, error, ausencia confirmada y no aplicable. Un error o falta de acceso nunca significa «0 reseñas».
- Conservar unidades y textos originales. No declarar compra verificada, correspondencia con una variante o promedio global si la fuente no lo proporciona.
- Paginar reseñas conservando sus identificadores y asociar cada foto con su propia reseña. Evitar duplicados al actualizar y no mezclar productos o cuentas.
- Guardar los datos y medios en la infraestructura Google existente. Extender conjuntamente persistencia, borrado por cambio de cuenta, contrato, snapshot, proxy de imágenes y caché privada antes de conectar los componentes de Flutter.
- Las imágenes nuevas deben seguir las validaciones de origen, límites y versiones de contenido existentes. La caché debe conservar el aislamiento Firebase UID + creador. No incrustar URLs privadas sin control ni publicar respuestas de clientes en Git.
- Verificar con datos reales una tabla, una reseña con fotografías y un producto sin acceso, en móvil y escritorio y en ambos temas. Probar paginación, actualización, cambio de cuenta y lectura de la copia sin conexión. Las fixtures sintéticas sirven para pruebas, no como demostración de una integración real.

La consulta de fuente pública y el almacenamiento están implementados. La recuperación de **todas** las reseñas sigue fuera de lo que entrega esta fuente comprobada. Abrir el enlace original permite consultar la ficha completa en TikTok; se distingue de los datos efectivamente conservados dentro de Corte.
