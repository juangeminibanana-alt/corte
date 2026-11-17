# 00 · Índice del catálogo de endpoints de TikTok para Corte

Revisión editorial y de cobertura: 15/11/2026. Solo se consultó documentación; no se llamó a la API real ni se abrió `config.json`.
App de Partner Center: «Creator collaborations», Custom, México. Token actual: creador (`user_type=1`) con 5 de los 6 scopes `creator.*`.

---

## a. Resumen ejecutivo

1. Se revisaron **6 familias** de APIs de TikTok, con **393 fichas** en total. Hay **8 endpoints repetidos** entre familias; sin ellos quedan **385 endpoints distintos**. De esos, **376 están verificados y vigentes**. Los otros **9** aparecen citados en la documentación, pero sin path o sin versión vigente verificada.
2. **Con la cuenta de creador, tal como está hoy, sirven 13 endpoints**, todos de la Affiliate Creator API (familia 01). Corte ya usa 10 y responden bien. Los 3 que no usa son agregar, quitar y fijar productos en la vitrina; el token ya tiene ese permiso.
3. Hay un 14.º endpoint, la búsqueda de pedidos por fecha de **liquidación** o de pago (`orders/trace/search`). Corte ya lo tiene programado, pero responde `105005`. Para que funcione hay que **reautorizar** al creador y conseguir `creator.affiliate.share_link.read`, que la app ya tiene aprobado.
4. **Corrección del revisor:** publicar un video con ancla de producto desde la PC (7 endpoints) pide el scope «Content Posting», cuya clave es **`creator.video.write`**. La app no lo tiene, y en México solo pueden llamarlo apps de categoría «Shoppable Content» o vendedores, no «Creator collaborations». Antes se creía que bastaba un scope que el token ya tiene.
5. **253 endpoints exigen token de TIENDA** (token de vendedor más `shop_cipher`): afiliados del lado vendedor, analítica, bestsellers, producto, pedidos, envíos, finanzas, promociones y devoluciones. Solo darían datos si una tienda de México autoriza la app, y los datos serían **de esa tienda**.
6. **16 exigen ser partner** TAP (agencia de campañas) o CAP (agencia de creadores). No se sabe si una persona física en México puede registrarse como partner.
7. **8 aceptan token de creador, pero piden scopes que la app no tiene**: analítica de LIVE y rendimiento de video (este último solo para creadores de EE. UU.).
8. **Fuera de TikTok Shop hay 73 endpoints:** TikTok for Developers (40) y TikTok API for Business (33). La **Display API** es la mejor vía para portadas, vistas y likes por video: pide una app aparte y se puede usar en modo Sandbox. La **Accounts API de Business** da lo más completo (retención, fuentes de tráfico, audiencia), pero exige registrarse como empresa.
9. De los **38 scopes** de la app, **36 quedaron ligados a endpoints verificados**. Dos no tienen ningún endpoint verificado: `creator.affiliate.link.write` y `seller.global_product.image_trans_task`.
10. **Lo que conviene primero:** reautorizar (trace/search) y probar la Display API en Sandbox. A mediano plazo, con una tienda MX que autorice la app: Marketplace Creator Performance (cómo ven las tiendas a Corte), Bestsellers y Get Product.

### Conteo por familia

| Familia | Archivo | Fichas | Verificadas vigentes | No verificadas | Sirven hoy con la cuenta de creador |
|---|---|---|---|---|---|
| 01 Affiliate Creator API (`creator.*`) | [01_afiliados_creador.md](01_afiliados_creador.md) | 32 | 26 | 6 | **13** (+1 con reautorización) |
| 02 Affiliate Seller API (`seller.affiliate_*`, marketplace, mensajes) | [02_afiliados_vendedor.md](02_afiliados_vendedor.md) | 51 (+2 webhooks) | 48 | 3 (legado) | 0 |
| 03 Affiliate Partner API (TAP/CAP) | [03_afiliados_partner.md](03_afiliados_partner.md) | 16 | 16 | 0 | 0 |
| 04 Analítica, Bestsellers y autorización | [04_analitica_bestsellers.md](04_analitica_bestsellers.md) | 52 (+12 versiones anteriores) | 52 (8 repetidas con 03 y 05) | 8 versiones retiradas sin doc (no se cuentan) | 0 |
| 05 Vendedor núcleo (producto, pedidos, envíos, finanzas…) | [05_vendedor_nucleo.md](05_vendedor_nucleo.md) | 169 | 169 | 0 | 0 |
| 06 TikTok for Developers y TikTok API for Business | [06_developers_y_business.md](06_developers_y_business.md) | 73 | 73 | 0 (algunos scopes y un método sin confirmar) | 0 hoy; 15 con app de Developers |
| **Total** | | **393** | **376 distintos** | **9** | **13** |

Duplicados descontados (revisor): 04 #46 = 03 #1 (Get Authorized Category Assets); 04 #45, #47, #48, #49, #50, #51 y #52 = 05 #166, #169, #167, #168, #163, #164 y #165.

Reparto de los 376 por quién puede llamarlos:
- **Creador con el token actual:** 13.
- **Creador después de reautorizar:** 1 (trace/search), más 2 enlaces para compartir que además piden un producto en campaña de partner.
- **Creador con scopes que la app no tiene:** 16 (8 de publicación con `creator.video.write`; 8 de analítica de creador).
- **Tokopedia (solo Indonesia, sin valor):** 2.
- **Tienda:** 253.
- **Partner TAP/CAP:** 16.
- **App de TikTok for Developers:** 40 (15 aplican a Corte).
- **Cuenta de empresa en TikTok API for Business:** 33.

---

## b. Lo que sirve HOY con la cuenta de creador

Todos son de la familia 01, con token de creador y sin `shop_cipher`. **NO USADO** = Corte todavía no lo llama.

| Ficha 01 | Nombre | Método + path | Scope | Estado en Corte | Lo que falta aprovechar |
|---|---|---|---|---|---|
| #1 | Get Creator Profile | `GET /affiliate_creator/202508/profiles` | `creator.affiliate.info` | En uso | `creator_user_open_id` (sirve para E3 de la familia 02 y para webhooks) y `permissions` para ocultar funciones. |
| #2 | Get Showcase Products | `GET /affiliate_creator/202405/showcases/products` | `creator.showcase.read` | En uso (solo `origin=SHOWCASE`) | `origin=LIVE` devuelve la bolsa de productos del LIVE. |
| #3 | Add Showcase Products | `POST /affiliate_creator/202405/showcases/products/add` | `creator.showcase.write` | **NO USADO** | Botón «Agregar a mi vitrina» (hasta 20 por llamada). Es escritura: pedir confirmación al usuario. |
| #4 | Remove Showcase Products | `DELETE /affiliate_creator/202409/showcases/products` | `creator.showcase.write` | **NO USADO** | Limpiar productos agotados, sin comisión o no disponibles (hasta 200; DELETE con cuerpo JSON). |
| #5 | Move Showcase Products to the Top | `POST /affiliate_creator/202409/showcases/products/top` | `creator.showcase.write` | **NO USADO** | Fijar arriba lo que más vende. |
| #6 | Search Open Collaboration Products | `POST /affiliate_creator/202405/open_collaborations/products/search` | `creator.affiliate_collaboration.read` | En uso (fase «parecidos») | Filtros `category.id`, `commission_rate_range` y `sort_field=units_sold`. |
| #7 | Get Open Collaboration Product List By Product Ids | `POST /affiliate_creator/202509/open_collaborations/products` | `creator.affiliate_collaboration.read` | En uso (lotes de 20) | La spec permite **50 por llamada**: menos de la mitad de llamadas. |
| #8 | Search Creator Target Collaborations | `POST /affiliate_creator/202405/target_collaborations/search` | `creator.affiliate_collaboration.read` | En uso | No hay listado global de invitaciones: va una tienda a la vez, con `shop_id`. |
| #9 | Search Creator Sample Applications | `POST /affiliate_creator/202412/sample_applications/search` | `creator.affiliate_collaboration.read` | En uso | — |
| #10 | Get Creator Sample Application Detail | `POST /affiliate_creator/202412/sample_applications/single_query` | `creator.affiliate_collaboration.read` | En uso | — |
| #11 | Creator Search Sample Application Fulfillments | `POST /affiliate_creator/202409/sample_applications/fulfillments/search` | `creator.affiliate_collaboration.read` | En uso | Sin paginación documentada. |
| #12 | Check Creator Sample Eligibility | `GET /affiliate_creator/202412/samples/labels` | `creator.affiliate_collaboration.read` | En uso | `reach_limit` para avisar «ya no puedes pedir más muestras». |
| #13 | Search Creator Affiliate Orders | `POST /affiliate_creator/202410/orders/search` | `creator.affiliate_collaboration.read` | En uso | No filtra por fecha de actualización. |

Fuera de la tabla:
- **#14 `POST /affiliate_creator/202505/orders/trace/search`:** ya integrado, pero hoy responde `105005`. Ver la tabla c.
- **#25 Map Tokopedia to TikTok Shop Product IDs:** técnicamente se puede llamar con el token actual, pero solo aplica a Indonesia (valor ninguno).

---

## c. Lo que daría datos nuevos a Corte si se cumple un requisito

⭐ = valor alto. La dificultad es una estimación del revisor a partir de los requisitos documentados.

| Endpoint(s) | Familia · ficha | Dato nuevo para Corte | Requisito | Dificultad | Valor |
|---|---|---|---|---|---|
| ⭐ Search Affiliate Orders by Creator · `POST /affiliate_creator/202505/orders/trace/search` | 01 · #14 | Pedidos filtrados por **`SETTLE_TIME`** (lo liquidado en un periodo, para conciliar pagos) o por `PAY_TIME`, y el estado **`DEDUCTED`**. | **Reautorizar**: el creador quita todo el acceso, vuelve a autorizar, y luego se revisa que `granted_scopes` traiga `creator.affiliate.share_link.read`. La categoría «Creator collaborations» está habilitada en MX→MX (verificado por el revisor). | Baja | Alto |
| ⭐ Display API: Get User Info · List Videos · Query Videos (`GET /v2/user/info/`, `POST /v2/video/list/`, `POST /v2/video/query/`) | 06 · #8–#10 | **Portada real** de cada video (caduca en 6 h), título, duración, **vistas, likes, comentarios y compartidos por video**; seguidores y likes totales. Cruzando con `content_id` salen pedidos por cada 1,000 vistas. | App aparte en developers.tiktok.com con Login Kit Desktop y Display API. Usar **Sandbox** con la cuenta del creador como usuario de prueba (sin revisión). La revisión de producción prohíbe apps de uso personal. | Media | Alto |
| Content Posting API de Developers: subida al inbox, publicación directa y estado (`/v2/post/publish/...`) | 06 · #12, #13, #15, #16 | Mandar desde la PC el video terminado como borrador al inbox de TikTok. No documenta cómo anclar productos de TikTok Shop. | La misma app de Developers, con scope `video.upload` (o `video.publish`). Sin auditoría, solo publica en privado. | Media | Medio |
| ⭐ Accounts API: Get profile data · Get post data (`GET /open_api/v1.3/business/get/`, `GET /open_api/v1.3/business/video/list/`) | 06 · #46, #47 | Vistas, visitas al perfil y likes **por día** (hasta 60 días atrás); por video: **retención**, % visto completo, **fuentes de tráfico**, audiencia por país, ciudad y género, y seguidores ganados. | Registrarse como **desarrollador empresa** en TikTok API for Business (correo de dominio y sitio web de empresa; no aceptan individuos), llenar el formulario Accounts API y lograr la aprobación del scope «TikTok Accounts». Disponibilidad en MX no documentada. | Alta | Alto |
| ⭐ Get Marketplace Creator Performance · `GET /affiliate_seller/202608/marketplace_creators/{creator_user_id}` | 02 · E3 | **Cómo ven las tiendas a Corte:** PPS a 90 días, calificación de vendedores, `post_rate`, `sample_score`, puntuación de cumplimiento a 90 días, reseñas de cumplimiento, nivel, demografía de seguidores, GMV/GPM por tipo de contenido y tendencia. | **Token de una tienda MX** que autorice la app (más `shop_cipher` con Get Authorized Shops) y el Open ID de Corte en **la misma app** (sale del perfil 202508). Riesgos no explicados: errores `16901007` y `16032012`. | Alta | Alto |
| Search Creators in Creator Marketplace · `POST /affiliate_seller/202608/marketplace_creators/search` | 02 · E1 | Comparar a Corte con otros creadores de MX (GMV, seguidores, vistas promedio, nivel) a 30 días. | El mismo de E3. | Alta | Medio |
| ⭐ Get Bestselling Products · Get Bestselling Videos (`GET /analytics/202511/products/bestselling`, `GET /analytics/202511/videos/bestselling`) | 04 · #1, #2 | Top 100 del **mercado MX** en 1, 7 o 30 días: productos (filtrables por categoría) y videos con vistas, likes y rango de GMV. | Token de una tienda MX, aprobación de `data.bestselling.public.read` (hoy en «Awaiting review») y **categoría permitida**: con registro MX→MX, «Creator collaborations» **no** aparece. | Alta | Alto |
| Get Bestselling Creators · `GET /analytics/202511/creators/bestselling` | 04 · #3 | Top 100 de creadores afiliados en MX. | Los mismos de #1. | Alta | Medio |
| Get Shop Video Performance List · Get Shop Videos Performance Details (lote) | 04 · #19, #21 | Vistas, likes y GMV de los videos de Corte **en esa tienda**; `thumbnail_url`, `play_url` y `title`. | Una tienda socia autoriza la app; `data.shop_analytics.public.read` aprobado y categoría permitida. | Alta | Medio |
| ⭐ Get Product · Search Size Charts · Inventory Search | 05 · #26, #36, #19 | Descripción completa, atributos, **todas las imágenes**, video, guía de tallas estructurada y stock por talla y color. Solo de productos de esa tienda. | Una **tienda socia** autoriza la app; `seller.product.basic` aprobado (hoy en «Awaiting review»). | Alta | Alto (condicionado) |
| Search Coupon List · Get Coupon · Search Promotion Activities · Get Activity | 05 · #133, #134, #127, #128 | Cupones **exclusivos para creador** y calendario de ofertas de una tienda socia. | Tienda socia más `seller.promotion.info` aprobado. | Alta | Medio |
| Upload Shoppable Video File · Post Shoppable Video (+ precheck y estado) | 01 · #17–#21 | Publicar desde la PC el video de una muestra pendiente **con ancla de producto**. No verificado que cuente para el cumplimiento. | **Corregido por el revisor:** scope `creator.video.write` (no está en la app) **y** una app de categoría «Shoppable Content» (en MX→MX, «Creator collaborations» no puede). Más cuotas de publicación. | Muy alta | Alto como función; viabilidad baja |
| Webhook `shoppable_content_posting` (tipo 17); no es endpoint | 01 · anexo | Aviso cada vez que el creador agrega o quita un producto en un video, con `content_id`, **aunque el video no tenga ventas**. | Receptor HTTPS público (el hub es local) y webhook configurado en Partner Center. | Media | Alto |
| Search CAP Affiliate Orders · `POST /affiliate_partner/202603/cap_order/search` | 03 · #16 | Impuestos estimados y reales, ganancia neta estimada después de impuestos, `attribution_type` y porcentaje que se queda la agencia. | Que una **agencia CAP** con la que trabaje Corte autorice la app como partner. | Alta | Medio |
| Get Affiliate Campaign Creator Product Content Statistics | 03 · #13 | Vistas, likes y comentarios por video, pero solo en campañas TAP. | Ser **TAP**, crear una campaña y que el producto esté en ella. | Muy alta | Alto como dato; viabilidad muy baja |
| Generate General Sharing Links · `POST /affiliate_creator/202505/affiliate_sharing_links/general_publishers/generate_batch` | 01 · #16 | Enlaces rastreables fuera de TikTok (WhatsApp, Instagram); sus pedidos llegan como `LINKSHARE`. | Reautorizar (share_link.read) y que el producto esté en una campaña de partner. | Media/Alta | Bajo (medio si opera como agencia) |
| Live Room (7 endpoints, `/analytics/202502/live_rooms/{live_room_id}/...`) | 04 · #6–#12 | Estadísticas de LIVE propios. | Scope `creator.data.live.read.public` (no está en la app), categoría permitida, y que Corte haga LIVE. | Alta | Bajo |

---

## d. Mapa scope → endpoints (los 38 scopes de la app)

Clave verificada = el revisor o la familia la leyó en el JSON oficial `api_meta` de docv2 (`scope_list[].scope_key`).

### Aprobados (17)

| Scope | Endpoints | Token que los llama | Clave |
|---|---|---|---|
| `creator.affiliate.info` | 01 #1 Get Creator Profile | Creador | Verificada (revisor) |
| `creator.affiliate_collaboration.read` | 01 #6–#13 (8) y #25 (Tokopedia); webhook tipo 17 | Creador | Alta confianza por nombre; en uso con el token actual |
| `creator.showcase.read` | 01 #2 | Creador | Verificada (revisor) |
| `creator.showcase.write` | 01 #3, #4, #5 | Creador | Verificada en #3 (revisor) |
| `creator.affiliate.link.write` | **Ninguno verificado** | — | **Sin endpoint.** No es «Content Posting» (esa clave es `creator.video.write`). Confirmar en Partner Center › Manage API. |
| `creator.affiliate.share_link.read` | 01 #14, #15, #16, #26 | Creador (**falta en el token**) | Verificada en #14, #15 y #16 (revisor) |
| `seller.affiliate_messages.write` | 02 D1–D10 (10) | Tienda | Verificada (familia 02) |
| `seller.affiliate_collaboration.read` | 02 A1, A3, A6, A8, A9, B2, B5, B9, C1, C3, C4, F1, F2, F3, G1–G4, H1–H4 (22) | Tienda | Verificada (familia 02) |
| `seller.affiliate_collaboration.write` | 02 A2, A4, A5, A7, A10, B1, B3, B4, B6, B7, B8, B9, C2, F2, H5 (15) y legado L1–L3 | Tienda | Verificada (familia 02) |
| `seller.creator_marketplace.read` | 02 E1, E2, E3 | Tienda | Verificada (familia 02) |
| `seller.authorization.info` | Get Authorized Shops (04 #45 = 05 #166) y Get Shop Group and Related Shops (04 #47 = 05 #169) | Tienda (sin `shop_cipher`) | Verificada (familia 04) |
| `partner.tap_campaign.read` | 03 #2, #3, #7, #10, #11, #12, #13, #14, #15 (9) | Partner TAP | Verificada (revisor) |
| `partner.tap_campaign.write` | 03 #4, #5, #6 | Partner TAP | Verificada (revisor) |
| `partner.tap_campaign.product.write` | 03 #8 | Partner TAP | Verificada (revisor) |
| `partner.tap_campaign.link.write` | 03 #9 | Partner TAP | Verificada (revisor) |
| `partner.authorization.info` | 03 #1 (= 04 #46) | Partner | Verificada (revisor) |
| `partner.cap_orders.read` | 03 #16 | Partner CAP | Verificada (revisor) |

### En revisión, «Awaiting review» (21); todos piden token de tienda

| Scope | Endpoints | Clave |
|---|---|---|
| `data.bestselling.public.read` | 04 #1–#4 | Verificada (familia 04) |
| `data.shop_analytics.public.read` | 04 #13–#44 (32) y 12 versiones anteriores | Verificada (familia 04) |
| `seller.shop.info` | Get Active Shops, Get Global Product Permission (04 #48, #49 = 05 #167, #168) y Get Global Seller Warehouses (05 #112) | Verificada (familia 04) |
| `seller.product.basic` | 05: 48 endpoints (p. ej., ⭐ #26 Get Product, #44, #19, #36) | Verificada (revisor) |
| `seller.product.write` | 05 #20, #27, #28, #48, #51, #52 | Verificada (revisor) |
| `seller.product.delete` | 05 #21, #25 | Verificada (revisor) |
| `serller.product.optimize` (errata oficial) | 05 #24, #32, #34, #41, #45, #46, #163–#165 (9) | Verificada (revisor y familia 04) |
| `seller.global_product.info` | 05 #14, #29 | Verificada (revisor) |
| `seller.global_product.write` | 05 #12, #15, #16, #17 | Verificada (revisor) |
| `seller.global_product.delete` | 05 #13 | Verificada (revisor) |
| `seller.global_product.category.info` | 05 #6, #7, #10, #11 | Verificada (revisor) |
| `seller.global_product.image_trans_task` | **Ninguno verificado** | **Sin endpoint.** La traducción de imágenes (05 #45 y #46) pide `serller.product.optimize`. |
| `seller.order.info` | 05 #73, #77, #78, #79, #80 | Verificada (revisor) |
| `seller.fulfillment.basic` | 05: 20 endpoints (#82, #83, #86, #91–#93, #95, #96, #98, #99, #101, #102, #105–#111, #156) | Verificada (revisor) |
| `seller.fulfillment.package.write` | 05 #81, #84, #87, #89, #94, #97 («Package Split And Combine») | Verificada (revisor) |
| `seller.delivery.status.write` | 05 #90 (solo SEA) | Verificada (revisor) |
| `seller.logistics` | 05 #85, #88, #100, #111, #113–#117 (9) | Verificada (revisor) |
| `seller.finance.info` | 05 #118–#125 (8) | Verificada (revisor) |
| `seller.promotion.info` | 05 #127, #128, #133, #134, #136–#144 (13) | Verificada (revisor) |
| `seller.promotion.write` | 05 #126, #129–#132, #135 (6) | Verificada (revisor) |
| `seller.return_refund.basic` | 05 #145–#162 (18) | Verificada (revisor) |

### Scopes que la app NO tiene pero que piden endpoints relevantes

- **`creator.video.write` («Content Posting»):** 01 #17–#24. También aparece como opcional en #1, #2 y #3, que ya responden sin él. Lo pide también 04 #5.
- **`creator.data.live.read.public` («Live Data»):** 04 #5–#12.
- **`seller.fs.order&fufillment.management`:** aparece como alternativa en pedidos, envíos y Get Authorized Shops.
- Sin equivalente en la app: Customer Service, Read/Write External Order References y Manage Seller Redeem Info Callback (05).
- **De otras plataformas (otra app):** `user.info.basic`, `user.info.profile`, `user.info.stats`, `video.list`, `video.upload` y `video.publish` (TikTok for Developers); `user.insights`, `video.insights` y otros (TikTok API for Business).

**Recomendación (de la familia 05, la respalda el revisor):** quitar de la solicitud los scopes de vendedor sin valor para un creador (pedidos, finanzas, envíos, logística, devoluciones, global product, borrado, escritura, traducción de imágenes). Si se busca la ruta de «tienda socia», basta con `seller.product.basic` y `seller.promotion.info`. Pedir scopes de más alarga la revisión (`research/tiktok-docs/authorization-overview-202407.txt`).

---

## e. Lo que NINGUNA API oficial da a Corte (y por qué)

1. **Mensajes entre creador y tienda.** Las 10 APIs de mensajería son de la bandeja de la tienda (`/affiliate_seller/`); no existe nada equivalente en `/affiliate_creator/` (02).
2. **Pedir o retirar una muestra, o pedir prórroga o suspensión de un cumplimiento.** La doc menciona la suspensión, pero no hay endpoint (01).
3. **Saldo, retiros y pagos del creador.** `creator.*` no tiene endpoint de billetera. La conciliación depende de `SETTLED` y de trace con `SETTLE_TIME`. Data Portability incluye «Earnings», pero solo para usuarios del EEE y Reino Unido (01, 06).
4. **Reseñas de productos afiliados con la conexión actual.** No se identificó una operación pública Affiliate Creator que entregue opiniones o fotos de compradores para Corte MX. TikTok también documenta una categoría Customer Reviews para vendedores, sin que se haya comprobado acceso aplicable al catálogo afiliado de Corte. Research API cubre productos disponibles en la UE y exige investigación aprobada; no resuelve este uso comercial. No interpretar esta limitación como inexistencia universal de APIs de reseñas. Ver la auditoría actualizada y el requisito en `docs/API_COVERAGE.md` y `docs/PRODUCT_SIZE_CHARTS_AND_REVIEWS.md`.
5. **Datos completos de productos de otras tiendas** (descripción, tallas, stock) sin que esa tienda autorice la app. Todo pasa por el `shop_cipher` de la tienda dueña (05).
6. **Métricas de video o LIVE dentro de la API de creador de TikTok Shop.** `creator.*` no da vistas ni likes. Get Video Performances es solo para EE. UU. Las vías son la Display API, Business o la analítica de una tienda (01, 04, 06).
7. **Anclar un producto de TikTok Shop al publicar** con la Content Posting API de Developers o con la publicación de Business: no hay campo documentado. La publicación de Shop (`/affiliate_creator/*/videos`) sí ancla, pero no está habilitada para la categoría de la app en MX (01, 06; verificado por el revisor).
8. **Listado global de invitaciones dirigidas.** Solo se consulta tienda por tienda con `shop_id` (01).
9. **Datos del mercado** (bestsellers, cómo ven las tiendas a Corte) **sin una tienda.** Todos exigen token de vendedor (02, 04).
10. **Sincronizar pedidos por fecha de actualización.** `orders/search 202410` no tiene ese filtro (01).

---

## Revisión: contradicciones encontradas y correcciones aplicadas

| # | Hallazgo | Dónde | Qué hizo el revisor |
|---|---|---|---|
| 1 | **Clave de «Content Posting».** La 01 suponía, por eliminación, `creator.affiliate.link.write`; la 04 decía `creator.video.write`. | 01 vs 04 | Verificado en `api_meta` de 6 endpoints de la 01: es **`creator.video.write`**. Se corrigió la 01: resumen, mapa de scopes, tabla, fichas 17 y 20 y huecos. |
| 2 | **Categoría de la app para publicar.** Nadie lo había revisado. | 01 | Verificado en `callable_categories` (MX→MX) de Upload Shoppable Video File y Post Shoppable Video: solo «Shoppable Content» y «TikTok Shop Seller». En cambio, trace/search sí admite «Creator collaborations». Se anotó en la 01. |
| 3 | La 01 contaba **22 endpoints usables** porque incluía los de publicación. | 01 (resumen estructurado) | Corregido: **13 hoy**, 14 con reautorización, 16 si además hay producto en campaña de partner. |
| 4 | La 03 afirmaba **sin fuente** que el creador usa `creator.affiliate.link.write` para sus enlaces. | 03 #9 | Corregido: los enlaces del lado creador piden `creator.affiliate.share_link.read` (verificado). `creator.affiliate.link.write` queda sin endpoint. |
| 5 | La 03 y la 05 daban el mapeo de claves `partner.*` y `seller.*` como **inferido**. | 03 y 05 | Verificadas en `api_meta` las 6 claves `partner.*` y 17 claves `seller.*`, entre ellas «Package Split And Combine» = `seller.fulfillment.package.write`. Notas agregadas en ambos archivos. |
| 6 | `seller.global_product.image_trans_task`: la 05 dudaba si era alias de «Product Optimization». | 05 | El `api_meta` de Create Image Translation Tasks da `serller.product.optimize`; el scope de la app queda sin endpoint verificado. |
| 7 | **Duplicados entre familias** (8 endpoints). | 03, 04 y 05 | Anotados en la 04 y descontados en este índice. |
| 8 | ¿Dos scopes en un endpoint se piden con «O» o con «Y»? | 01, 04 y 05 | Hay evidencia de «O»: el perfil y la vitrina piden también `creator.video.write`, que el token no tiene, y aun así responden. Se anotó en la 01 como inferencia. |
| 9 | Categoría «Creator collaborations» en MX→MX: la 02 dice que sí está habilitada (42 de 48 APIs de vendedor afiliado) y la 04 dice que no (Analytics y Bestsellers). | 02 vs 04 | No es contradicción: son APIs distintas con listas distintas. Queda como pendiente la región de registro de la app (ver f). |
| 10 | El changelog de Bestsellers menciona «Creator collaborations», pero el filtro MX→MX no la incluye. | 04 | Se mantiene como contradicción de la doc oficial; pendiente. |
| 11 | Get Live Room Info (01 N1, sin path) frente a los 7 Live Room 202502 de la 04 (con path, otro scope). | 01 vs 04 | Pueden ser versiones distintas del mismo tema. La 01 lo deja como no verificado; la analítica de LIVE vigente es la de la 04. |

Afirmaciones de contexto que no vienen de la API (por ejemplo, que una tienda concentre la mayor parte de la comisión o cuántas muestras quedan pendientes): salen de los datos privados de desarrollo de Corte, que no se publican, no de la documentación de TikTok. Se dejaron solo como contexto general, sin cifras.

---

## f. Pendientes de verificación

1. **Región de registro de la app en Partner Center (MX o US).** De ella depende si «Creator collaborations» puede llamar Analytics, Bestsellers y la publicación de videos. La consulta US→MX de Post Shoppable Video devolvió `available: true` sin categorías, así que no es concluyente.
2. **`creator.affiliate.link.write`:** qué API usa. Revisarlo en Partner Center › App & Service › Manage API (columna «API Names»).
3. **`seller.global_product.image_trans_task`:** qué API usa (mismo lugar).
4. **trace/search:** si devuelve todos los pedidos o solo los de share links, y cuál es su ventana máxima. Solo se sabrá al llamarlo después de reautorizar.
5. **Publicación de videos:** si la app puede pedir `creator.video.write`, si cambiar de categoría o usar otra app es viable, y si un video publicado por API cuenta para el cumplimiento de la muestra.
6. **Display API:** que funcione en Sandbox; que `id` del video sea igual a `content_id` de los pedidos; si el PKCE va en hex o en base64url; si se puede guardar la portada en caché.
7. **Webhooks** (tipo 17 y otros): configuración en Partner Center, si llegan con autorización de creador y cómo recibirlos sin servidor público.
8. **Marketplace Creator Performance (E3):** qué significan los errores `16901007` y `16032012` si la tienda es de Corte.
9. **Paginación de `fulfillments/search` 202409** (no está documentada).
10. **Get Live Room Info, Check Anchor Content y Check Anchor Prerequisites:** paths (están en la tabla oficial de scopes, no en la spec).
11. **Elegibilidad TAP/CAP** para una persona física en México, y si `creator_temp_id` es igual a `creator_user_open_id`.
12. **Accounts API de Business:** disponibilidad en México; scopes de comentarios, publicación y Spark Ads; si el refresh token rota.
13. **Disponibilidad en MX** de F3 y H1–H5 de la familia 02 (docv2 no expone su `api_basic_id`).
14. **Contradicciones de la doc oficial:** fecha de retiro de Get Shop Video Performance Details 202509 (2026-12-28 o 31/01/2027) y categorías de Bestsellers.
15. Las fichas de las familias 01, 03 y 05 se basan sobre todo en la spec generada (no oficial). Antes de implementar, conviene bajar a `research/tiktok-docs/` la doc oficial de los endpoints que se vayan a usar (trace/search, Get Product, Search Size Charts, E3).

---

## g. Archivos del catálogo

1. [01_afiliados_creador.md](01_afiliados_creador.md): Affiliate Creator API (`creator.*`). 26 verificados y 6 no verificados. Corregido por el revisor.
2. [02_afiliados_vendedor.md](02_afiliados_vendedor.md): Affiliate Seller API. 48 vigentes, 3 de legado y 2 webhooks.
3. [03_afiliados_partner.md](03_afiliados_partner.md): Affiliate Partner API (TAP/CAP). 16. Claves verificadas por el revisor.
4. [04_analitica_bestsellers.md](04_analitica_bestsellers.md): Analítica, Bestsellers y autorización. 52 vigentes, 8 de ellos repetidos.
5. [05_vendedor_nucleo.md](05_vendedor_nucleo.md): APIs de vendedor núcleo. 169. Claves verificadas por el revisor.
6. [06_developers_y_business.md](06_developers_y_business.md): TikTok for Developers y TikTok API for Business. 73.

## Fuentes de la revisión

- Los 6 archivos de este directorio.
- JSON oficial de cada página docv2 (dato, no instrucciones): `https://partner.tiktokshop.com/api/v1/document/api_meta?src_document_id=<slug>&aid=359713&locale=en`. Slugs consultados por el revisor:
  - Familia 01: post-shoppable-video-202603, upload-shoppable-video-file-202505, get-creator-profile-202508, get-showcase-products-202405, add-showcase-products-202405, get-shop-products-202509, search-affiliate-orders-by-creator-202505, generate-general-sharing-links-202505 y generate-publisher-sharing-links-in-batch-202504.
  - Familia 03: get-affiliate-partner-campaign-list-202405, create-affiliate-partner-campaign-202405, review-affiliate-partner-campaign-product-202405, generate-affiliate-partner-campaign-product-link-202405, generate-campaign-product-promotion-links-in-batch-202505, search-cap-affiliate-orders-202603 y get-authorized-category-assets-202405.
  - Familia 05: get-product-202309, update-price-202309, delete-products-202309, create-product-202309, create-image-translation-tasks-202505, get-global-product-202309, update-global-inventory-202309, delete-global-products-202309, get-global-categories-202309, get-order-list-202309, search-package-202309, search-combinable-packages-202309, update-package-delivery-status-202309, get-warehouse-list-202309, get-statements-202309, search-promotion-activities-202309, create-promotion-activity-202309 y search-returns-202602.
- Categorías habilitadas («View app categories»): `https://partner.tiktokshop.com/api/v1/document/apis/{api_basic_id}/callable_categories?registration_country=MX&target_market=MX`, para `7502333053755541265` (Post Shoppable Video), `7502362897129981697` (Upload Shoppable Video File) y `7502362897130800897` (trace/search). También `registration_country=US` para el primero.
- Búsquedas web para `creator.affiliate.link.write` y `seller.global_product.image_trans_task`: sin resultados oficiales. Solo aparecieron blogs de terceros, que no se citan como fuente.
- Docs locales: `research\tiktok-docs\affiliate-integration.txt` y `access-scope.txt` (sin menciones de esas dos claves).
