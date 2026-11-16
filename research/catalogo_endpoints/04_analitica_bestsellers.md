# 04 · Analítica y Bestsellers + Autorización de tienda

Familia: `data.shop_analytics.public.read`, `data.bestselling.public.read` (ambos «Awaiting review» en la app) + `seller.authorization.info` (aprobado) y `seller.shop.info` («Awaiting review»).
Investigado el 15/11/2026 solo con documentación (no se llamó a la API real ni se abrió `config.json`).

## Resumen de la familia

- Son **52 endpoints vigentes**: 44 de Analytics (32 de analítica de tienda, 4 Bestsellers, 8 de analítica del creador), 2 de Authorization y 6 de Seller. Además hay 12 versiones anteriores todavía documentadas y 8 retiradas sin documentación.
- **Ninguno sirve hoy con el token de creador de Corte.** Los 36 de `data.shop_analytics` y `data.bestselling` exigen **token de vendedor (`user_type = 0`) + `shop_cipher` obligatorio**. Lo dice la doc oficial de cada endpoint, y el changelog de Bestsellers agrega «All four APIs require a valid seller OAuth access token».
- Los únicos que aceptan **token de creador (`user_type = 1`) sin tienda** son Get Video Performances y los 7 de Live Room. Piden scopes que la app no tiene (`creator.data.live.read.public` o `creator.video.write`). Get Video Performances es solo para **creadores de EE. UU.**
- **Bloqueo extra en México:** según el filtro oficial «View app categories», con registro MX → mercado MX, **ninguna** API de Analytics/Bestsellers admite la categoría «Creator collaborations». Solo la admiten Connectors, ERP, TikTok Shop Seller y, para analítica de tienda, también Shoppable Content. Con registro US → MX sí aparece. Por eso, aunque aprueben los scopes, la llamada puede no estar permitida para esta app.
- `seller.authorization.info` (Get Authorized Shops, Get Shop Group and Related Shops) **sí** está habilitado para «Creator collaborations» en MX. Pero solo devuelve tiendas que **un vendedor** haya autorizado; con token de creador no aplica.
- El dato más valioso para Corte sería **Bestsellers**: top 100 de productos, videos y creadores del **mercado** del vendedor (MX), con rango de GMV. Requiere que **una tienda MX autorice la app**, que aprueben el scope y que la categoría esté habilitada.
- Ningún endpoint se puede llamar «solo con la app», sin usuario. Todos exigen el header `x-tts-access-token` (doc «Common parameters»).

> **[Nota del revisor, 15/11/2026]** Duplicados con otras familias, para no contarlos dos veces: el #46 (Get Authorized Category Assets) es el #1 de `03_afiliados_partner.md`; los #45, #47, #48, #49, #50, #51 y #52 son los #166, #169, #167, #168, #163, #164 y #165 de `05_vendedor_nucleo.md`. Además, el revisor confirmó en `api_meta` que «Content Posting» = `creator.video.write` también en los endpoints de publicación de la familia 01. El scope que esta familia lista para Get Video Performances es el mismo que piden los endpoints `/affiliate_creator/*/videos` de la 01.

## ¿Se puede llamar algo SIN autorización de una tienda? Evidencia

| Pregunta | Respuesta | Evidencia |
| --- | --- | --- |
| ¿Bestsellers con token de creador? | **No** | La doc oficial de los 4 dice en `x-tts-access-token`: «The seller access_token value … when user_type = 0»; `shop_cipher` es **Required**. Changelog «Bestsellers Analytics Open API Launch» (docv2/page/3dk9557y): «All four APIs require a valid seller OAuth access token». |
| ¿Shop Analytics con token de creador? | **No** | Los 32 tienen `scenario = 1`, `is_shop_chiper_exist = true` y token de vendedor `user_type = 0` (api_meta oficial de cada doc). |
| ¿Algún Analytics sin tienda? | **Sí, 8, pero con token de creador y scopes que faltan** | Get Video Performances y los 7 Live Room: `scenario = 4`, sin `shop_cipher`, token «creator access_token … when user_type = 1». |
| ¿Solo con la app (sin token de usuario)? | **No** | «Common parameters» (docv2/page/678e3a4278f4c20311b8b57e): `x-tts-access-token` en header para 202309+; todas las fichas lo marcan como Required. |
| ¿Mezclar tokens? | **No** | `creator-authorization-guide.txt`: «A creator token and a seller token are different credentials and must not be reused interchangeably»; error `101000` «Wrong token identity or wrong API-token pairing». |
| ¿La categoría «Creator collaborations» puede llamarlos en MX? | **No (registro MX → MX)** | Endpoint oficial de la página `…/api/v1/document/apis/{api_basic_id}/callable_categories?registration_country=MX&target_market=MX`. Bestsellers y Live Room: Connectors, ERP, TikTok Shop Seller. Shop Analytics y Video Performances: Shoppable Content, Connectors, ERP, TikTok Shop Seller. Con `registration_country=US&target_market=MX` aparecen «Creator collaborations» y «TikTok Shop Seller». **Contradicción:** el changelog de Bestsellers menciona «Creator collaborations» entre las categorías que pueden usarlos. |

## Tabla breve de TODOS los endpoints (52 vigentes)

Leyenda: «¿Sirve?» = con la cuenta de creador de Corte. «Vend.» = token de vendedor + `shop_cipher`. ⭐ = valor alto para Corte.

| # | Nombre | Método + path | Scope | ¿Sirve al creador? | Valor |
| --- | --- | --- | --- | --- | --- |
| 1 | ⭐ Get Bestselling Products | GET /analytics/202511/products/bestselling | data.bestselling.public.read | No (Vend.) | Alto |
| 2 | ⭐ Get Bestselling Videos | GET /analytics/202511/videos/bestselling | data.bestselling.public.read | No (Vend.) | Alto |
| 3 | Get Bestselling Creators | GET /analytics/202511/creators/bestselling | data.bestselling.public.read | No (Vend.) | Medio |
| 4 | Get Bestselling LIVE Sessions | GET /analytics/202511/lives/bestselling | data.bestselling.public.read | No (Vend.) | Bajo |
| 5 | Get Video Performances | GET /analytics/202403/videos/performances | creator.video.write / creator.data.live.read.public | No (solo creadores de EE. UU.) | Ninguno (MX) |
| 6 | Get Live Room Core Stats | GET /analytics/202502/live_rooms/{live_room_id}/core_stats | creator.data.live.read.public | Sí con requisito (scope nuevo + categoría) | Bajo |
| 7 | Get Live Room GMV and Order Trends | GET /analytics/202502/live_rooms/{live_room_id}/gmv_trend_performances | creator.data.live.read.public | Sí con requisito | Bajo |
| 8 | Get Live Room Interactive Trends | GET /analytics/202502/live_rooms/{live_room_id}/interactive_trend_performances | creator.data.live.read.public | Sí con requisito | Bajo |
| 9 | Get Live Room Product Stats | GET /analytics/202502/live_rooms/{live_room_id}/product_stats | creator.data.live.read.public | Sí con requisito | Bajo |
| 10 | Get Live Room Traffic Performance | GET /analytics/202502/live_rooms/{live_room_id}/traffic_performances | creator.data.live.read.public | Sí con requisito | Bajo |
| 11 | Get Live Room User Portraits | GET /analytics/202502/live_rooms/{live_room_id}/user_portraits | creator.data.live.read.public | Sí con requisito | Bajo |
| 12 | Get Live Room View Trends | GET /analytics/202502/live_rooms/{live_room_id}/view_trend_performances | creator.data.live.read.public | Sí con requisito | Bajo |
| 13 | Get Shop Performance | GET /analytics/202609/shop/performance | data.shop_analytics.public.read | No (Vend.) | Ninguno |
| 14 | Get Shop Performance Per Hour | GET /analytics/202510/shop/performance/{date}/performance_per_hour | data.shop_analytics.public.read | No (Vend.) | Ninguno |
| 15 | Get Shop Product Performance List | GET /analytics/202605/shop_products/performance | data.shop_analytics.public.read | No (Vend.) | Bajo |
| 16 | Get Shop Product Performance Detail | GET /analytics/202509/shop_products/{product_id}/performance | data.shop_analytics.public.read | No (Vend.) | Bajo |
| 17 | Get Shop SKU Performance List | GET /analytics/202509/shop_skus/performance | data.shop_analytics.public.read | No (Vend.) | Ninguno |
| 18 | Get Shop SKU Performance Detail | GET /analytics/202509/shop_skus/{sku_id}/performance | data.shop_analytics.public.read | No (Vend.) | Ninguno |
| 19 | Get Shop Video Performance List | GET /analytics/202605/shop_videos/performance | data.shop_analytics.public.read | No (Vend.) | Medio |
| 20 | Get Shop Video Performance Overview | GET /analytics/202609/shop_videos/overview_performance | data.shop_analytics.public.read | No (Vend.) | Bajo |
| 21 | Get Shop Videos Performance Details (lote) | GET /analytics/202609/shop_videos/batch_performance | data.shop_analytics.public.read | No (Vend.) | Medio |
| 22 | Get Shop Video Performance Details (se retira) | GET /analytics/202509/shop_videos/{video_id}/performance | data.shop_analytics.public.read | No (Vend.) | Bajo |
| 23 | Get Shop Video Product Performance List | GET /analytics/202509/shop_videos/{video_id}/products/performance | data.shop_analytics.public.read | No (Vend.) | Bajo |
| 24 | Get Shop LIVE Performance Overview | GET /analytics/202609/shop_lives/overview_performance | data.shop_analytics.public.read | No (Vend.) | Ninguno |
| 25 | Get Shop LIVE Performance List | GET /analytics/202609/shop_lives/performance | data.shop_analytics.public.read | No (Vend.) | Bajo |
| 26 | Get Shop LIVE Minute Performance | GET /analytics/202510/shop_lives/{live_id}/performance_per_minutes | data.shop_analytics.public.read | No (Vend.) | Ninguno |
| 27 | Get Shop LIVE Products Performance List | GET /analytics/202512/shop/{live_id}/products_performance | data.shop_analytics.public.read | No (Vend.) | Ninguno |
| 28 | Get SPS Overview | GET /analytics/202610/shop_performances/overview | data.shop_analytics.public.read | No (Vend.; solo tiendas de EE. UU.) | Ninguno |
| 29 | Get SPS Benefits | GET /analytics/202610/shop_performances/benefits | data.shop_analytics.public.read | No (Vend.; solo EE. UU.) | Ninguno |
| 30 | Get SPS Metrics | GET /analytics/202606/shop_performances/metrics | data.shop_analytics.public.read | No (Vend.; solo EE. UU.) | Ninguno |
| 31 | Get SPS Metric Diagnosis | GET /analytics/202606/shop_performances/metrics/{metric_code}/diagnosis | data.shop_analytics.public.read | No (Vend.; solo EE. UU.) | Ninguno |
| 32 | Get SPS Metric Problem Details | GET /analytics/202606/shop_performances/metrics/{metric_code}/problem_details | data.shop_analytics.public.read | No (Vend.; solo EE. UU.) | Ninguno |
| 33 | Get SPS Metric Top Items | GET /analytics/202606/shop_performances/metrics/{metric_code}/top_items | data.shop_analytics.public.read | No (Vend.; solo EE. UU.) | Ninguno |
| 34 | Get ACC Brands | GET /analytics/202610/acc/brands | data.shop_analytics.public.read | No (Vend.) | Ninguno |
| 35 | Get ACC Audience Overview | GET /analytics/202610/acc/overview | data.shop_analytics.public.read | No (Vend.) | Ninguno |
| 36 | Get ACC Audience Penetration | GET /analytics/202610/acc/penetration | data.shop_analytics.public.read | No (Vend.) | Ninguno |
| 37 | Get ACC Audience Preference List | GET /analytics/202610/acc/preferences | data.shop_analytics.public.read | No (Vend.) | Bajo |
| 38 | Get ACC Audience Preference Summary | GET /analytics/202610/acc/preferences/summary | data.shop_analytics.public.read | No (Vend.) | Bajo |
| 39 | Get ACC LIVE Sales Factors | GET /analytics/202610/acc/preferences/live/factors | data.shop_analytics.public.read | No (Vend.) | Ninguno |
| 40 | Get ACC Top Sales Categories | GET /analytics/202610/acc/preferences/product/categories | data.shop_analytics.public.read | No (Vend.) | Bajo |
| 41 | Get Shop Off Site Pixels | GET /analytics/202610/off_site/pixels | data.shop_analytics.public.read | No (Vend.) | Ninguno |
| 42 | Get Off Site Performance Overview | GET /analytics/202610/off_site/overview | data.shop_analytics.public.read | No (Vend.) | Ninguno |
| 43 | Get Off Site Performance Details | GET /analytics/202610/off_site/details | data.shop_analytics.public.read | No (Vend.) | Ninguno |
| 44 | Get Off Site Audience Insights | GET /analytics/202610/off_site/insights | data.shop_analytics.public.read | No (Vend.) | Ninguno |
| 45 | Get Authorized Shops | GET /authorization/202309/shops | seller.authorization.info (o seller.fs.order&fufillment.management) | No (token de vendedor) | Bajo (habilitador) |
| 46 | Get Authorized Category Assets | GET /authorization/202405/category_assets | partner.authorization.info | No (token de partner `user_type = 3`) | Ninguno |
| 47 | Get Shop Group and Related Shops | GET /seller/202601/shop_groups | seller.authorization.info | No (token de vendedor) | Ninguno |
| 48 | Get Active Shops | GET /seller/202309/shops | seller.shop.info | No (token de vendedor) | Ninguno |
| 49 | Get Global Product Permission | GET /seller/202309/permissions | seller.shop.info | No (token de vendedor) | Ninguno |
| 50 | Get Seller Carousel Permission | GET /seller/202611/carousel_permission | serller.product.optimize | No (fuera de familia) | Ninguno |
| 51 | Upload Seller Image | POST /seller/202611/images/upload | serller.product.optimize | No (fuera de familia) | Ninguno |
| 52 | Upload Seller Materials | POST /seller/202611/materials/upload | serller.product.optimize | No (fuera de familia) | Ninguno |

### Versiones anteriores todavía documentadas (todas: token de vendedor + `shop_cipher`, `data.shop_analytics.public.read`)

| Doc (slug) | Método + path | Diferencia principal | Estado |
| --- | --- | --- | --- |
| get-shop-performance-202405 | GET /analytics/202405/shop/performance | Tiene `with_comparison` | Documentada; fecha de retiro no verificada |
| get-shop-performance-202509 | GET /analytics/202509/shop/performance | Quitó `with_comparison`; datos alineados con Data Compass | Documentada; vigente la 202609 |
| get-shop-product-performance-detail-202405 | GET /analytics/202405/shop_products/{product_id}/performance | Tiene `with_comparison` | Documentada; retiro no verificado |
| get-shop-product-performance-list-202405 | GET /analytics/202405/shop_products/performance | Sin `category_filter` ni `product_status_filter` | Documentada; retiro no verificado |
| get-shop-product-performance-list-202509 | GET /analytics/202509/shop_products/performance | Solo GMV, órdenes y unidades (changelog kpkfccsa) | Documentada; vigente la 202605 |
| get-shop-video-performance-list-202509 | GET /analytics/202509/shop_videos/performance | — | **Se retira el 31/01/2027** (changelog 8z0tllw9) |
| get-shop-live-performance-overview-202508 | GET /analytics/202508/shop_lives/overview_performance | Tiene `with_comparison` | Documentada |
| get-shop-live-performance-overview-202509 | GET /analytics/202509/shop_lives/overview_performance | Agrega `today` | Documentada; vigente la 202609 |
| get-shop-live-performance-list-202508 | GET /analytics/202508/shop_lives/performance | — | Documentada |
| get-shop-live-performance-list-202509 | GET /analytics/202509/shop_lives/performance | — | Documentada; vigente la 202609 |
| get-shop-video-performance-overview-202509 | GET /analytics/202509/shop_videos/overview_performance | — | Documentada; vigente la 202609 |
| get-sps-overview-202606 | GET /analytics/202606/shop_performances/overview | — | Documentada; vigente la 202610 |

**Retiradas, no verificadas (sin doc disponible; `api_meta` responde `98001001`):** get-shop-product-performance-202405, get-shop-sku-performance-202406, get-shop-sku-performance-list-202406, get-shop-sku-performance-202509, get-shop-video-performance-list-202409, get-shop-video-performance-overview-202409, get-shop-video-performance-details-202409 y get-shop-video-product-performance-list-202409. Aparecen como enlaces en los changelogs j5k1cmia y ukjcmkq5, que dicen que las versiones 202406 y 202409 quedaban fuera de línea en abril de 2026. No se anotan sus paths porque no se pudieron verificar.

---

## Fuentes y abreviaturas usadas en las fichas

- **doc:** `https://partner.tiktokshop.com/docv2/page/<slug>`. Leída con el navegador integrado: la página se arma con JS y WebFetch no la lee. Sus datos (path, scope, `scope_key`, token, `shop_cipher`, parámetros, respuesta) se tomaron del JSON público que usa la propia página: `https://partner.tiktokshop.com/api/v1/document/api_meta?src_document_id=<slug>&aid=359713&locale=en`.
- **categorías:** `https://partner.tiktokshop.com/api/v1/document/apis/{api_basic_id}/callable_categories?registration_country=MX&target_market=MX`. Es la sección «View app categories» de la doc.
- **spec:** `https://raw.githubusercontent.com/isaackogan/TikTok-Shop-Api-SDKs/main/.openapi/tiktok-shop.openapi.yaml` (OpenAPI 3.1 «Generated from the TikTok Shop Partner Center documentation», `info.version` 2026.11.13; campos `x-tts-scopes`, `x-tts-requires-shop-cipher`, `x-tts-scenario`, `x-tts-docs-url`). Se usó como dato, sin ejecutar nada.
- **meta SDK:** `https://raw.githubusercontent.com/isaackogan/TikTok-Shop-Api-SDKs/main/python/src/tiktok_shop_api/generated/_meta.py` (`requiresShopCipher` por operación).
- Changelogs oficiales (docv2/page/…): 3dk9557y (Bestsellers), j5k1cmia (Analytics global), ukjcmkq5 (202509 y retiro de 202406/202409), 8z0tllw9 (retiros y ventanas, nov 2026 / ene 2027), 6az7iwe9 (Enhanced Shop/Video/LIVE 2026-09-28), kpkfccsa (202605), sv0xa2r6 (LIVE), joyljtav (consistencia de métricas). Parámetros comunes: 678e3a4278f4c20311b8b57e.
- Locales: `research/tiktok-docs/authorization-overview-202407.txt`, `creator-authorization-guide.txt`, `access-scope.txt`.

Valores de `scenario` observados en la doc oficial: 1 = API de tienda (vendedor con `shop_cipher`), 2 = vendedor sin `shop_cipher`, 4 = creador, 7 = partner. Es una inferencia por coincidencia con el token que pide cada doc; la doc no publica una tabla con estos valores.

---

## A. Bestsellers (`data.bestselling.public.read`)

Notas comunes del changelog 3dk9557y:
- Los datos vienen de Data Compass y cubren el **mercado registrado del vendedor**, no solo su tienda.
- El GMV llega **como rango con desplazamiento aleatorio** (no hay cifra exacta).
- Máximo 100 registros, sin paginación.
- Granularidad mínima de un día; `time_slot` 1D, 7D o 30D.
- `currency` USD o LOCAL.
- Tipo de acceso: Public, «available to all ISVs and sellers who request the Bestsellers scope».

Requisito común para Corte: un vendedor de TikTok Shop México autoriza la app con el enlace de vendedor (`services.tiktokshop.com/open/authorize?service_id=…`), sale el token `user_type = 0` y se obtiene `cipher` con Get Authorized Shops. Además, TikTok tiene que aprobar `data.bestselling.public.read` (hoy en «Awaiting review») y la categoría de la app debe estar permitida para MX (ver la evidencia de arriba).

### 1. ⭐ Get Bestselling Products
- **Método y path:** `GET /analytics/202511/products/bestselling` (única versión: 202511).
- **Scope:** Bestsellers (`data.bestselling.public.read`), Public.
- **Quién:** token de vendedor (`user_type = 0`) con `shop_cipher` **obligatorio**. No acepta token de creador, partner, TikTok for Developers ni cuenta Business.
- **Parámetros:**
  - Obligatorios: `date` (YYYY-MM-DD, fin inclusivo, en la zona horaria de la tienda, ≤ última fecha disponible; si te pasas, el error dice cuál es esa fecha), `time_slot` (`1D` | `7D` | `30D`), `shop_cipher`.
  - Opcionales: `category_id` (categoría de nivel 1), `currency` (`USD` | `LOCAL`, por defecto LOCAL).
- **Respuesta (`data.products[]`):** `rank`, `gmv_range` (texto, p. ej. «$97000.00~$191000.00»), `id`, `name`, `rating`, `shop_name`, `shop_id`, `product_image{height, width, thumb_urls[], uri, urls[]}` (la imagen se agregó según el changelog kpkfccsa).
- **Límites:** hasta 100 productos y sin paginación. Ventana de 1, 7 o 30 días que termina en `date`. Mercado del vendedor. Sin códigos de error de negocio.
- **¿Sirve con la cuenta de creador de Corte?** **No.** Sí con requisito: autorización de una tienda MX, scope aprobado y categoría de app habilitada en MX.
- **Valor para Corte:** **Alto.** Daría el top 100 de productos más vendidos de TikTok Shop MX, filtrable por categoría nivel 1 (moda masculina), con tienda, rating, imagen y rango de GMV. Sirve para elegir qué productos pedir como muestra o promocionar. Hoy Corte no tiene ningún dato de mercado.
- **Fuente:** doc get-bestselling-products-202511; spec; changelogs 3dk9557y y kpkfccsa; categorías (MX→MX: Connectors, ERP, TikTok Shop Seller).

### 2. ⭐ Get Bestselling Videos
- **Método y path:** `GET /analytics/202511/videos/bestselling`.
- **Scope:** `data.bestselling.public.read`.
- **Quién:** token de vendedor + `shop_cipher` obligatorio.
- **Parámetros:**
  - Obligatorios: `date`, `time_slot` (`1D` | `7D` | `30D`), `shop_cipher`.
  - Opcional: `currency`.
  - Este endpoint no tiene `category_id`.
- **Respuesta (`data.videos[]`):** `rank`, `id` (ID del video), `nick_name`, `gmv_range`, `views`, `likes`, `comments`, `shares`, `product_infos[]{product_id, product_name}`, `publish_time`, `duration`.
- **Límites:** top 100 por GMV, sin paginación, mercado del vendedor.
- **¿Sirve?** **No.** Sí con el mismo requisito que el #1.
- **Valor para Corte:** **Alto.** Daría los videos que más venden en MX, con vistas, likes, comentarios y compartidos, y los productos que traen. Son referencias de formato para sus videos UGC y le dan con qué comparar los suyos.
- **Fuente:** doc get-bestselling-videos-202511; spec; changelog 3dk9557y.

### 3. Get Bestselling Creators
- **Método y path:** `GET /analytics/202511/creators/bestselling`.
- **Scope:** `data.bestselling.public.read`.
- **Quién:** token de vendedor + `shop_cipher` obligatorio.
- **Parámetros:**
  - Obligatorios: `date`, `time_slot` (`1D` | `7D` | `30D`), `author_type` (`ALL` | `OFFICIAL` | `CHANNEL` | `AFFILIATE`), `shop_cipher`.
  - Opcional: `currency`.
- **Respuesta (`data.creators[]`):** `rank`, `gmv_range`, `open_id`, `user_name`, `nick_name`, `followers_count`, `likes_count`.
- **Límites:** top 100, sin paginación.
- **¿Sirve?** **No.** Sí con el mismo requisito que el #1.
- **Valor:** **Medio.** Con `author_type=AFFILIATE` serían los creadores afiliados que más venden en MX, para compararse con ellos. No dice en qué categoría venden.
- **Fuente:** doc get-bestselling-creators-202511; spec.

### 4. Get Bestselling LIVE Sessions
- **Método y path:** `GET /analytics/202511/lives/bestselling`. Ojo: el changelog enlaza el slug «get-bestselling-lives-202511», que ya no existe; el vigente es get-bestselling-live-sessions-202511.
- **Scope:** `data.bestselling.public.read`.
- **Quién:** token de vendedor + `shop_cipher` obligatorio.
- **Parámetros:**
  - Obligatorio: `shop_cipher`.
  - Marcados opcionales en la doc: `date`, `time_slot` (`1D` | `7D` | `30D`), `currency`.
- **Respuesta (`data.lives[]`):** `rank`, `gmv_range`, `id`, `title`, `start_time`, `duration`, `creator_name`, `open_id`, `creator_nick_name`.
- **Límites:** top 100.
- **¿Sirve?** **No.**
- **Valor:** **Bajo.** Corte hace videos UGC; los LIVE solo sirven como referencia.
- **Fuente:** doc get-bestselling-live-sessions-202511; spec.

---

## B. Analítica del creador (`scenario = 4`, token de creador, sin `shop_cipher`)

Requisitos comunes:
- Corte necesitaría que TikTok apruebe scopes **que la app no tiene ni pidió**: «Live Data» (`creator.data.live.read.public`) y/o «Content Posting» (`creator.video.write`).
- Además, el creador tendría que volver a autorizar para que entren en `granted_scopes`.
- Con registro MX → MX, la categoría «Creator collaborations» **no** aparece habilitada para estos endpoints.
- No se verificó si TikTok ofrece esos scopes a apps con mercado México.

### 5. Get Video Performances
- **Método y path:** `GET /analytics/202403/videos/performances`.
- **Scope:** la doc lista dos: Content Posting (`creator.video.write`) y Live Data (`creator.data.live.read.public`). **No verificado** si basta con uno o se necesitan ambos.
- **Quién:** token de creador (`user_type = 1`); no lleva `shop_cipher`.
- **Parámetros (obligatorios):** `video_ids` (separados por coma, del mismo autor, máx. 100), `start_time_ge` (int64; con un día de retraso; dentro de los últimos 180 días; solo cuenta la fecha), `end_time_le` (int64; con un día de retraso).
- **Respuesta:** `data.videos[]{id, performances[]{time_range{start_time, end_time}, metrics{anchor_display_rate, click_through_rate, order_count, item_sold_count, gmv{amount, currency}}}}`.
- **Límites:** 100 videos por llamada, 180 días hacia atrás, un día de retraso. La doc dice «**US-creator-only**».
- **¿Sirve con la cuenta de creador de Corte?** **No.** Es un creador de México y la API es solo para creadores de EE. UU.
- **Valor:** **Ninguno** para MX. En EE. UU. daría CTR del ancla de producto por video, un dato que hoy Corte no tiene.
- **Fuente:** doc get-video-performances-202403; spec; categorías. El changelog joyljtav anuncia que sus métricas de GMV y órdenes pasan a atribución unificada.

### 6–12. Live Room (7 endpoints, versión 202502)
Comunes a los siete:
- **Scope:** Live Data (`creator.data.live.read.public`).
- **Quién:** token de creador (`user_type = 1`), sin `shop_cipher`.
- **Parámetro:** `live_room_id` (path, obligatorio). La sala debe ser del creador dueño del token.
- **Errores:** `66009302` «Invalid param. Please check room id.» y `66009315` «No permission for the action.»
- **De dónde sale el `live_room_id`:** **no verificado**. Ningún endpoint de esta familia lista las salas del creador.
- **¿Sirve?** **Sí con requisito:** scope Live Data aprobado y autorizado por el creador, y categoría habilitada en MX (hoy no lo está con MX→MX). Además, Corte tendría que hacer LIVE.
- **Valor:** **Bajo.** Corte trabaja con videos UGC y no hay evidencia de que haga LIVE.
- **Fuente:** docs get-live-room-*-202502; spec; categorías.

| # | Nombre | Path | Campos de respuesta |
| --- | --- | --- | --- |
| 6 | Get Live Room Core Stats | `/analytics/202502/live_rooms/{live_room_id}/core_stats` | `stats{sales, local_gmv{amount,currency}, created_order_count, current_visitor_count, paid_order_count, local_unit_price, product_reach_count, watch_pv, click_through_rate, accumulated_new_follower_count, buyer_count, accumulated_comment_count, product_view_count, click_order_rate, avg_watching_duration, accumulated_sharing_count, peak_concurrent_user_count}` |
| 7 | Get Live Room GMV and Order Trends | `…/gmv_trend_performances` | `gmv_trend_performances[]{stats_type, data_points[]{order_count, timestamp, gmv{currency, amount}}}` |
| 8 | Get Live Room Interactive Trends | `…/interactive_trend_performances` | `interactive_trend_performances[]{stats_type, data_points[]{value, timestamp}}` |
| 9 | Get Live Room Product Stats | `…/product_stats` | `product_stats[]{main_image_url, product_id, is_live, click_through_rate, sellable_region, created_order_count, exposure_count, total_click_count, local_gmv, product_name, local_unit_price, paid_order_count, inventory_left_count, inventory_consumption_count, created_order_user_count, paid_user_count, click_order_rate}` |
| 10 | Get Live Room Traffic Performance | `…/traffic_performances` | `traffic_performances[]{source{name, watch_pv}, sub_sources[]{name, watch_pv}}` |
| 11 | Get Live Room User Portraits | `…/user_portraits` | `all_ads_gender_indicators[]`, `all_fan_indicators[]`, `all_ads_age_indicators[]`, `region_indicators[]`, `paid_ads_age_indicators[]`, `paid_ads_gender_indicators[]`, `paid_fan_indicators[]` (cada uno `{type, value}`) |
| 12 | Get Live Room View Trends | `…/view_trend_performances` | `view_trend_performances[]{stats_type, data_points[]{value, timestamp}}` |

---

## C. Analítica de tienda (`data.shop_analytics.public.read`)

Comunes a los 32:
- **Scope:** «TikTok Shop Analytics» (`data.shop_analytics.public.read`), Public.
- **Quién:** token de vendedor (`user_type = 0`) con `shop_cipher` **obligatorio** (`scenario = 1`).
- **Fechas:** `start_date_ge` es inclusiva y `end_date_lt` exclusiva, en YYYY-MM-DD y en la zona horaria de la tienda.
- **Moneda:** `currency` `USD` | `LOCAL` (por defecto LOCAL). En Get Shop Performance la doc dice «Currently, only local currency is supported in the response».
- **Regiones:** desde el changelog j5k1cmia están disponibles en todos los mercados (versiones 202405 en adelante), salvo SPS, que es solo para tiendas de EE. UU.
- **Categorías (MX→MX):** Shoppable Content, Connectors, ERP y TikTok Shop Seller; **no** Creator collaborations.
- **¿Sirve con la cuenta de creador de Corte?** **No** en los 32. Solo serviría si una tienda autoriza la app, y los datos serían **de esa tienda**.
- **Fuente común:** doc `<slug>` + spec + meta SDK (`requiresShopCipher: True`).

### C1. Tienda

**13. Get Shop Performance** · `GET /analytics/202609/shop/performance` · doc get-shop-performance-202609 (versiones 202509 y 202405 en la tabla de arriba)
- Parámetros: obligatorios `start_date_ge`, `end_date_lt`, `shop_cipher`; opcionales `granularity` (`ALL` | `1D`, por defecto ALL), `currency`.
- Respuesta: `latest_available_date`; `performance.intervals[]{start_date, end_date, sales{…}, traffic{…}, breakdowns{…}}`.
  - `sales`: avg_order_value, avg_sku_order_value, cancellations_and_returns, creator_live_*_gmv, creator_video_attributed_gmv, creator_video_gmv, creator_video_indirect_gmv, customers_count, gmv, gmv_with_tax, gmv_with_tiktok_co_funding, items_sold, live_*_gmv, orders_count, product_card_attributed_gmv, refunds, seller_live_*_gmv, seller_video_*_gmv, shipping_fees, sku_orders_count, tax, video_attributed_gmv, video_gmv, video_indirect_gmv.
  - `traffic`: avg_conversation_rate, avg_page_views, avg_visitors, product_clicks, product_impressions, unique_clicks, unique_product_impressions.
  - `breakdowns`: affiliate_product_card_attributed_gmv, content_breakdown[]{channel, content_type, gmv, indirect_gmv}, seller_product_card_gmv, shop_tab_and_search{…}.
- Error: `28001022`.
- ¿Sirve? No. Valor: **Ninguno**; son ventas totales de una tienda ajena.

**14. Get Shop Performance Per Hour** · `GET /analytics/202510/shop/performance/{date}/performance_per_hour` · doc get-shop-performance-per-hour-202510
- Parámetros: `date` (path, obligatorio; últimos 30 días, incluye hoy), `shop_cipher`; opcional `currency`.
- Respuesta: `performance{latest_available_timestamp, intervals[]{index, avg_order_value, avg_sku_order_value, customers, customers_count, gmv, items_sold, live_attributed_gmv, orders_count, product_card_attributed_gmv, product_clicks, product_impressions, sku_orders_count, unique_clicks, unique_product_impressions, video_attributed_gmv, visitors}, overall{…}}`.
- Límite: **desde el 06/11/2026, máximo 7 días por solicitud** (changelog 8z0tllw9).
- ¿Sirve? No. Valor: Ninguno.

### C2. Producto y SKU

**15. Get Shop Product Performance List** · `GET /analytics/202605/shop_products/performance` · doc get-shop-product-performance-list-202605 (versiones 202509 y 202405 en la tabla de arriba)
- Parámetros:
  - Obligatorios: `start_date_ge`, `end_date_lt`, `shop_cipher`.
  - Opcionales: `page_size` (máx. 100, por defecto 10), `page_token`, `sort_field` (`gmv` | `items_sold` | `orders`), `sort_order`, `currency`, `category_filter` (IDs de categoría nivel 1), `product_status_filter` (`LIVE` | `INACTIVE` | `ALL`).
- Respuesta:
  - `products[]{id, total_performance{…}, seller_live_performance, seller_video_performance, seller_product_card_performance, affiliate_total_performance{…, avg_daily_creator_posted_content}, affiliate_live_performance, affiliate_video_performance{attributed_video_gmv, new_video_count, …}, shop_tab_performance}`, `next_page_token`, `total_count`, `latest_available_date`.
  - `total_performance` trae: gmv, orders, items_sold, product_impressions, product_clicks, ctr, add_cart_rate, refunds, etc.
- ¿Sirve? No. Valor: **Bajo**; daría el GMV afiliado por producto de una tienda que autorice.

**16. Get Shop Product Performance Detail** · `GET /analytics/202509/shop_products/{product_id}/performance` · doc get-shop-product-performance-detail-202509 (versión 202405 en la tabla de arriba)
- Parámetros: `product_id` (path), `start_date_ge`, `end_date_lt`, `shop_cipher`; opcionales `granularity`, `currency`.
- Respuesta: `performance{intervals[]{sales{gmv, orders, items_sold, breakdowns[]}, traffic{breakdowns[]}, cancel_and_refunds{returned, canceled, refunded, replacements}}, ratings[]{stars, count, percentage}, top_contents[]{type, contents[]{content_id, items_sold, gmv}}, top_creators[]{creator_open_id, creator_name, creator_profile, gmv, items_sold}}`, `latest_available_date`.
- Errores: `28001007`, `28001022`, `36009003`.
- ¿Sirve? No. Valor: **Bajo.** `top_creators` y `top_contents` dirían si Corte está en el top de ese producto, pero solo con permiso de la tienda.

**17. Get Shop SKU Performance List** · `GET /analytics/202509/shop_skus/performance` · doc get-shop-sku-performance-list-202509
- Parámetros: obligatorios `start_date_ge`, `end_date_lt`, `shop_cipher`; opcionales `page_size` (máx. 100), `page_token`, `sort_field` (`gmv` | `sku_orders` | `units_sold`), `sort_order`, `category_filter`, `product_status_filter`, `product_ids`, `currency`.
- Respuesta: `skus[]{id, product_id, gmv, sku_orders, units_sold}`, `next_page_token`, `total_count`, `latest_available_date`.
- ¿Sirve? No. Valor: Ninguno.

**18. Get Shop SKU Performance Detail** · `GET /analytics/202509/shop_skus/{sku_id}/performance` · doc get-shop-sku-performance-detail-202509
- Parámetros: `sku_id` (path), `start_date_ge`, `end_date_lt`, `shop_cipher`; opcionales `granularity`, `currency`.
- Respuesta: `performance{product_id, sku_id, intervals[]{gmv, gmv_breakdown[]{amount, currency, type}, items_sold, items_sold_breakdown[], sku_orders}}`, `latest_available_date`.
- ¿Sirve? No. Valor: Ninguno.

### C3. Video

**19. Get Shop Video Performance List** · `GET /analytics/202605/shop_videos/performance` · doc get-shop-video-performance-list-202605
- Parámetros:
  - Obligatorios: `start_date_ge`, `end_date_lt`, `shop_cipher`.
  - Opcionales: `page_size` (1–100, por defecto 10), `page_token`, `sort_field` (gmv, gpm, avg_customers, sku_orders, items_sold, views, click_through_rate, post_time), `sort_order`, `currency`, `account_type` (`ALL` | `OFFICIAL_ACCOUNTS` | `MARKETING_ACCOUNTS` | `AFFILIATE_ACCOUNTS`).
- Respuesta: `videos[]{id, title, username, advertisable, attributed_gmv, avg_customers, click_through_rate, comments, creator{author_type, creator_country, creator_id, nick_name, open_id, user_name}, ctor, duration, gmv, gpm, hash_tags[], indirect_gmv, items_sold, likes, new_followers, product_clicks, product_impressions, products[]{id, name}, review_type, shares, sku_orders, v_to_l_clicks, v_to_l_rate, video_finish_rate, video_post_time, views}`, `next_page_token`, `total_count`, `latest_available_date`.
- Límites:
  - La doc pide un rango de 60 días como máximo; **desde el 06/11/2026 son 30 días por solicitud** (changelog 8z0tllw9).
  - Las versiones 202409 y 202509 se retiran el 31/01/2027.
- ¿Sirve? No. Requisito: que una tienda con la que colabora (p. ej., la que concentra su comisión) autorice la app.
- Valor: **Medio.** Con `account_type=AFFILIATE_ACCOUNTS` daría **vistas, likes, comentarios, tasa de terminación y GMV de los videos de Corte** para esa tienda. Hoy Corte no tiene vistas.

**20. Get Shop Video Performance Overview** · `GET /analytics/202609/shop_videos/overview_performance` · doc get-shop-video-performance-overview-202609
- Parámetros: obligatorios `start_date_ge`, `end_date_lt`, `shop_cipher`; opcionales `today` (bool; métricas en tiempo real de hoy), `granularity`, `currency`, `account_type`.
- Respuesta: `performance.intervals[]{start_date, end_date, today, avg_daily_customers, ctor_sku_order, ctr, gpm, product_clicks, product_impressions, shoppable_video_attributed_gmv, video_attributed_gmv, video_attributed_sku_orders, video_gmv, video_indirect_gmv, video_product_viewers, video_views}`, `latest_available_date`.
- ¿Sirve? No. Valor: Bajo.

**21. Get Shop Videos Performance Details (lote)** · `GET /analytics/202609/shop_videos/batch_performance` · doc get-shop-videos-performance-details-202609
- Parámetros:
  - Obligatorios: `video_ids` (arreglo de int64, `explode: false`; el changelog 6az7iwe9 dice «Max 500»), `start_date_ge`, `end_date_lt` (rango ≤ 60 días), `shop_cipher`.
  - Opcionales: `granularity`, `currency`.
- Respuesta: `videos[]{video_id, error{code, message}, performance{intervals[]{sales{overall{ctr, customers, gmv, gpm, items_sold, product_clicks, product_impressions}}, traffic{comments, likes, new_followers, shares, views}}, viewer_profile[]{type, gender_distribution[], age_distribution[], country_distribution[]}}, video{id, title, duration, play_url, thumbnail_url, username, video_post_time}}`, `latest_available_date`.
- ¿Sirve? No. Requisito: tienda que autorice; solo para videos ligados a esa tienda.
- Valor: **Medio.** Es el único endpoint de la familia con `thumbnail_url`, `play_url` y `title` de video. Resolvería las portadas que oEmbed ya no da (ver `CONTEXTO.md`), pero solo para videos de tiendas que autoricen.

**22. Get Shop Video Performance Details** · `GET /analytics/202509/shop_videos/{video_id}/performance` · doc get-shop-video-performance-details-202509
- Parámetros: `video_id` (path), `start_date_ge`, `end_date_lt` (≤ 60 días), `shop_cipher`; opcionales `granularity`, `currency`.
- Respuesta: `performance{intervals[]{sales{overall{gmv, gpm, customers, items_sold, ctr, product_impressions, product_clicks}, breakdowns[]{product_id, …}}, traffic{views, new_followers, shares, comments, likes}}, viewer_profile[]}`, `latest_available_date`.
- Estado: **se retira.** El changelog 6az7iwe9 dice «no later than 2026-12-28» y el 8z0tllw9 dice «January 31, 2027» (contradicción entre changelogs). Se reemplaza por el #21.
- ¿Sirve? No. Valor: Bajo.

**23. Get Shop Video Product Performance List** · `GET /analytics/202509/shop_videos/{video_id}/products/performance` · doc get-shop-video-product-performance-list-202509
- Parámetros: `video_id` (path), `start_date_ge`, `end_date_lt`, `shop_cipher`; opcionales `page_size` (1–100), `page_token`, `sort_field` (`gmv` | `units_sold` | `daily_avg_buyers`), `sort_order`, `currency`.
- Respuesta: `products[]{id, name, ctr, customers, daily_avg_buyers, gmv, gpm, product_clicks, product_detail_url, product_image{thumb_uri, thumb_url_list[]}, product_impressions, units_sold}`, `next_page_token`, `total_count`, `latest_available_date`.
- ¿Sirve? No. Valor: Bajo.

### C4. LIVE de tienda

**24. Get Shop LIVE Performance Overview** · `GET /analytics/202609/shop_lives/overview_performance` · doc get-shop-live-performance-overview-202609
- Parámetros: obligatorios `start_date_ge`, `end_date_lt`, `shop_cipher`; opcionales `today`, `granularity`, `currency`, `account_type` (`ALL` | `LINKED_ACCOUNTS` | `AFFILIATE_ACCOUNTS`).
- Respuesta: `latest_available_date`, `updated_at`, `performance.intervals[]{avg_live_auction_price, avg_viewing_duration, ctor_sku_order, live_attributed_gmv, live_attributed_items_sold, live_attributed_sku_orders, live_auction_*, live_ctr, live_gmv, live_indirect_gmv, show_gpm, views}`.
- Error: `36009003`.
- ¿Sirve? No. Valor: Ninguno.

**25. Get Shop LIVE Performance List** · `GET /analytics/202609/shop_lives/performance` · doc get-shop-live-performance-list-202609
- Parámetros:
  - Obligatorios: `start_date_ge`, `end_date_lt`, `account_type` (`OFFICIAL_ACCOUNTS` | `MARKETING_ACCOUNTS` | `AFFILIATE_ACCOUNTS`), `shop_cipher`.
  - Opcionales: `page_size` (máx. 100), `page_token`, `sort_field` (live_attributed_gmv, products_added, products_sold, live_attributed_sku_orders, live_attributed_items_sold, attributed_customers), `sort_order`, `currency`.
- Respuesta: `live_stream_sessions[]{id, title, start_time, end_time, creator{author_type, creator_country, nick_name, open_id, user_name}, interaction_performance{…}, sales_performance{…}, traffic{…}}`, `next_page_token`, `total_count`, `latest_available_date`, `updated_at`.
- Nota de la doc: «Sellers can only query room ID data for their own official creator accounts».
- ¿Sirve? No. Valor: Bajo.

**26. Get Shop LIVE Minute Performance** · `GET /analytics/202510/shop_lives/{live_id}/performance_per_minutes` · doc get-shop-live-minute-performance-202510
- Parámetros: `live_id` (path), `shop_cipher`; opcionales `page_token`, `currency`.
- Respuesta: `performance{overall{live_title, start_time, end_time, duration, gmv, items_sold, unique_viewers, impressions}, intervals[]{start_time, end_time, sales{…}, traffic{…}, interactions{…}, conversion{…}}}`, `next_page_token`, `total_count`.
- Límite: solo después de terminar el LIVE y solo para cuentas oficiales o de marketing de la tienda.
- ¿Sirve? No. Valor: Ninguno.

**27. Get Shop LIVE Products Performance List** · `GET /analytics/202512/shop/{live_id}/products_performance` · doc get-shop-live-products-performance-list-202512
- Parámetros: `live_id` (path), `shop_cipher`; opcionales `sort_order`, `sort_field` (gmv, items_sold, customers, created_sku_orders, sku_orders, main_orders, product_impressions, product_clicks), `currency`.
- Respuesta: `products[]{id, name, sales{direct_gmv, items_sold, customers, created_sku_orders, avg_price, sku_orders, main_orders, payment_rate}, traffic{product_impressions, ctr, add_to_cart_count, click_to_order_rate{…}, gpm{watch_gpm}, produt_clicks}}`. `produt_clicks` está escrito así en el ejemplo de la spec.
- ¿Sirve? No. Valor: Ninguno.

### C5. SPS: Shop Performance Score (solo tiendas de EE. UU.)

Comunes: `shop_cipher` obligatorio y `locale` opcional (BCP 47). La doc dice «Available only for US-region shops». Para Corte: **No** sirve y su valor es **Ninguno** (tiendas de México, métricas de operación del vendedor).

| # | Nombre | Path | Parámetros extra | Respuesta |
| --- | --- | --- | --- | --- |
| 28 | Get SPS Overview | `/analytics/202610/shop_performances/overview` (versión anterior 202606) | — | `sps_score, sps_tier, sps_tier_text, peer_percentile, dimensions[]{name, status, status_text, score, weight}, primary_category{…}, evaluate_duration_days, start_evaluation_time, end_evaluation_time, update_time` |
| 29 | Get SPS Benefits | `/analytics/202610/shop_performances/benefits` | — | `benefits[]{benefit_name, is_unlocked, unlock_score}` |
| 30 | Get SPS Metrics | `/analytics/202606/shop_performances/metrics` | — | `metrics[]{metric_code, metric_name, dimension, score, status, status_text, value, value_unit, top_reason_text, evaluate_duration_days, start_evaluation_time, end_evaluation_time, benchmarks{excellent_threshold, poor_threshold}}` |
| 31 | Get SPS Metric Diagnosis | `/analytics/202606/shop_performances/metrics/{metric_code}/diagnosis` | `metric_code` (NRR, NBFR, SFCR, OTDR, AHT, IM_DSAT); `trend_duration_days` (1–90, por defecto 30) | Respuesta no leída en la spec (fragmento cortado): **no verificado** |
| 32 | Get SPS Metric Problem Details | `…/{metric_code}/problem_details` | `page_size` (1–50), `page_token` | `metric_code, total_count, next_page_token`, `*_problem_order_items[]` por métrica, `im_dsat_chat_items[]` |
| 33 | Get SPS Metric Top Items | `…/{metric_code}/top_items` | `metric_code` (NRR, NBFR, OTDR, AHT) | `nrr_top_product_items[], nbfr_top_product_items[], aht_aftersales_type_items[], otdr_logistics_items[]` |

Fuente: docs get-sps-*; spec; changelogs 3t9j6tz0 y 46di8q34 (títulos vistos en el árbol de docs, no leídos).

### C6. ACC: audiencia de marca

Comunes:
- `shop_cipher`; `brand_id` e `industry_id` son obligatorios, salvo en ACC Brands.
- `date` opcional (por defecto la última disponible).
- `trend_days` opcional (7 | 14 | 30).
- `scope` opcional (`MY_SHOP` | `MARKET`).
- Paginación con `page_size` (10 | 20 | 50 | 100) y `page_token`.

| # | Nombre | Path | Parámetros clave | Respuesta | Valor |
| --- | --- | --- | --- | --- | --- |
| 34 | Get ACC Brands | `/analytics/202610/acc/brands` | — | `brands[]{brand_id, brand_logo_url, brand_name, industry_id, industry_name, shop_id, shop_name, ttms_id}` | Ninguno |
| 35 | Get ACC Audience Overview | `/analytics/202610/acc/overview` | `benchmark` (5, 10, 25, 50) | `key_metrics{acc, awareness, consideration, conversion, new_conversion, repeat_conversion}`, `trend[]`, `latest_available_date` | Ninguno |
| 36 | Get ACC Audience Penetration | `/analytics/202610/acc/penetration` | `account_type`, `form` (ALL, PRODUCT, VIDEO, LIVE, PHOTO), `audience_type` | `funnel{viewed, clicked, ordered, total}` | Ninguno |
| 37 | Get ACC Audience Preference List | `/analytics/202610/acc/preferences` | obligatorios `audience_type` y `entity_type` (PRODUCT, LIVE, VIDEO, PHOTO); `scope=MARKET`, `keyword`, categorías, `sort_field` | `items[]{rank, entity_id, entity_name, entity_cover, entity_detail, metrics{customers, gmv_range, orders}}` | Bajo (con `scope=MARKET` mostraría tendencias del mercado, pero exige una marca ACC de la tienda) |
| 38 | Get ACC Audience Preference Summary | `/analytics/202610/acc/preferences/summary` | `audience_type` obligatorio | `channel_summaries[]{product_top_items[], video_top_items[], live_top_items[], …}` | Bajo |
| 39 | Get ACC LIVE Sales Factors | `/analytics/202610/acc/preferences/live/factors` | `audience_type` obligatorio | `factors[]{factor_id, factor_name, metrics}` | Ninguno |
| 40 | Get ACC Top Sales Categories | `/analytics/202610/acc/preferences/product/categories` | `audience_type` obligatorio | `categories[]{category_id, category_level, category_name, metrics, children[]}` | Bajo |

¿Sirve? **No** en ninguno (token de vendedor + marca ACC de esa tienda). Fuente: docs get-acc-*-202610; spec; changelog fb9qtudp (título visto en el árbol de docs, no leído).

### C7. Off-site: tráfico fuera de TikTok

Comunes:
- `shop_cipher`; `pixel_id` y `attribution_setting` (`VIEW_14D` | `CLICK_14D_OR_VIEW_1D`) son obligatorios, salvo en Pixels.
- `date` opcional: semanas de domingo a sábado; la más antigua empieza el 14/06/2026; se pueden pedir las últimas 12 semanas.

| # | Nombre | Path | Respuesta | Valor |
| --- | --- | --- | --- | --- |
| 41 | Get Shop Off Site Pixels | `/analytics/202610/off_site/pixels` | `pixels[]{pixel_id, pixel_name}` | Ninguno |
| 42 | Get Off Site Performance Overview | `/analytics/202610/off_site/overview` | `key_metrics{off_site_effect_rate, …, off_site_gmv, tiktok_shop_gmv}`, `trend{…}` | Ninguno |
| 43 | Get Off Site Performance Details | `/analytics/202610/off_site/details` (además `content_type` obligatorio: VIDEO, LIVE o PRODUCT; `page_size` 10, 20 o 50) | `contents[]{content_id, content_type, title, cover_image_url, post_time, duration_seconds, rank, creator{id, name, avatar_url}, metrics{…}}` | Ninguno |
| 44 | Get Off Site Audience Insights | `/analytics/202610/off_site/insights` | `age[], consumption_level[], followed_shop[], gender[], personas[], region[], top_favorite_content[], top_purchase_category_preferences[]` (cada uno `{name, off_site_customers_value, tts_customers_value}`) | Ninguno |

¿Sirve? **No.** Fuente: docs get-off-site-*-202610 y get-shop-off-site-pixels-202610; spec.

---

## D. Autorización

### 45. Get Authorized Shops
- **Método y path:** `GET /authorization/202309/shops`.
- **Scope:** Shop Authorized Information (`seller.authorization.info`). La doc oficial también lista «FS Order&Fulfillment Management» (`seller.fs.order&fufillment.management`, así escrito); **no verificado** si cualquiera de los dos basta.
- **Quién:** token de vendedor (`user_type = 0`); sin `shop_cipher` (`scenario = 2`).
- **Parámetros:** solo los comunes (`app_key`, `sign`, `timestamp`, header `x-tts-access-token`).
- **Respuesta:** `data.shops[]{id, name, region, seller_type, cipher, code}`.
- **Error:** `36009003`.
- **Límites:** solo lista tiendas que **el vendedor del token** haya autorizado para la app. Sin paginación documentada.
- **Categorías MX→MX:** **sí incluye «Creator collaborations»**.
- **¿Sirve con la cuenta de creador de Corte?** **No.** La doc pide token de vendedor, y la guía local dice que los tokens de creador y vendedor no son intercambiables (error `101000`). Lo que pasaría con token de creador **no está documentado** (no verificado).
- **Valor:** **Bajo (habilitador).** Es el paso obligatorio para conseguir `cipher` (= `shop_cipher`) si alguna tienda autoriza la app; sin eso ningún endpoint de Analytics ni Bestsellers funciona.
- **Fuente:** doc get-authorized-shops-202309; spec; categorías; `access-scope.txt` («Shop Authorized Information: … access to the seller's TikTok Shop shop ID(s)», Public).

### 46. Get Authorized Category Assets (familia partner; se incluye porque está en el grupo Authorization)
- **Método y path:** `GET /authorization/202405/category_assets`.
- **Scope:** Partner Authorized Information (`partner.authorization.info`), que ya está aprobado en la app.
- **Quién:** token de partner (`user_type = 3`, TAP/CAP).
- **Parámetros:** solo los comunes.
- **Respuesta:** `category_assets[]{cipher, target_market, category{id, name}}`. Ese `cipher` es el `category_asset_cipher` de las API de Affiliate Partner.
- **Categorías MX→MX:** Creator collaborations y TikTok Shop Seller.
- **¿Sirve?** **No** con token de creador. **Valor:** Ninguno para el creador (lo cubre la familia de partner).
- **Fuente:** doc get-authorized-category-assets-202405; spec.

---

## E. Seller

### 47. Get Shop Group and Related Shops
- **Método y path:** `GET /seller/202601/shop_groups`.
- **Scope:** `seller.authorization.info`.
- **Quién:** token de vendedor; sin `shop_cipher`.
- **Respuesta:** `shop_group_data{shop_group{source, shop_group_name}, shops[]{shop_id, seller_id, shop_name, shop_region}}`. La doc pone como ejemplo una tienda de EE. UU. con una de México.
- **Error:** `98001004`.
- **Categorías MX→MX:** incluye Creator collaborations.
- **¿Sirve?** **No.** **Valor:** Ninguno.
- **Fuente:** doc get-shop-group-and-related-shops-202601; spec.

### 48. Get Active Shops
- **Método y path:** `GET /seller/202309/shops`.
- **Scope:** Global Shop Information (`seller.shop.info`).
- **Quién:** token de vendedor; sin `shop_cipher`.
- **Respuesta:** `shops[]{id, region}`.
- **Categorías MX→MX:** **no** incluye Creator collaborations.
- **¿Sirve?** **No.** **Valor:** Ninguno.
- **Fuente:** doc get-active-shops-202309; spec.

### 49. Get Global Product Permission
- **Método y path:** `GET /seller/202309/permissions`.
- **Scope:** `seller.shop.info`.
- **Quién:** token de vendedor (transfronterizo).
- **Respuesta:** `permissions[]` (p. ej., `MANAGE_GLOBAL_PRODUCT`).
- **Categorías MX→MX:** no incluye Creator collaborations.
- **¿Sirve?** **No.** **Valor:** Ninguno.
- **Fuente:** doc get-global-product-permission-202309; spec.

### 50–52. Fuera de la familia (scope `serller.product.optimize`, así escrito en la doc)
- **50. Get Seller Carousel Permission:** `GET /seller/202611/carousel_permission` → `has_auto_post_permission`, `has_photo_mode_permission`.
- **51. Upload Seller Image:** `POST /seller/202611/images/upload` (multipart, ≤ 10 MiB) → `uri`, `url`.
- **52. Upload Seller Materials:** `POST /seller/202611/materials/upload` (`shop_cipher` obligatorio; cuerpo `material_groups`, `materials`, `post_type`, `product_id`).
- Los tres piden token de vendedor. ¿Sirven? **No.** Valor: Ninguno.
- La consulta de categorías respondió 400 para el #50 (y para el #29 SPS Benefits); no se verificó para esos dos.
- **Fuente:** docs get-seller-carousel-permission-202611, upload-seller-image-202611, upload-seller-materials-202611; spec.

---

## Huecos y puntos no verificados

1. **Región de registro de la cuenta de Partner Center:** de ella depende que «Creator collaborations» pueda llamar Analytics/Bestsellers en MX. Con MX→MX, no; con US→MX, sí. No se conoce la región de registro de esta app. Hay que verla en Partner Center antes de esperar algo de los scopes «Awaiting review».
2. **Contradicción en Bestsellers:** el changelog 3dk9557y incluye «Creator collaborations» entre las categorías que pueden usarlo, pero el filtro oficial MX→MX no la incluye.
3. **Comportamiento real con token de creador** en Get Authorized Shops y en Analytics: la doc pide token de vendedor y no documenta qué pasa con uno de creador. No se probó, porque estaba prohibido llamar a la API.
4. **Get Video Performances:** no se sabe si basta uno de los dos scopes listados o se necesitan ambos.
5. **Live Room:** no hay endpoint en esta familia que dé el `live_room_id`, y no se sabe si TikTok ofrece el scope `creator.data.live.read.public` a apps de México.
6. **Versiones 202406/202409 y get-shop-product-performance-202405 / get-shop-sku-performance-202509:** sin doc (retiradas). Sus paths no se anotaron.
7. **Retiro de Get Shop Video Performance Details 202509:** un changelog dice 2026-12-28 y otro 31/01/2027.
8. **Get SPS Metric Diagnosis:** no se leyeron los campos de respuesta.
9. No se revisaron developers.tiktok.com ni business-api.tiktok.com. Las métricas de video que da TikTok for Developers o una cuenta Business (vistas por video) quedan fuera de esta familia, aunque cubrirían el hueco de vistas y portadas de Corte por otra vía.
