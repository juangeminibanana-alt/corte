# 03 · Affiliate Partner API (TAP / CAP) y autorización de partner

Investigado el 15/11/2026 solo con documentación. No se llamó a la API real ni se abrió `config.json`.

## Resumen de la familia

- Son **16 endpoints**: 15 bajo `/affiliate_partner/` y `GET /authorization/202405/category_assets`. Todos usan el host `https://open-api.tiktokglobalshop.com`.
- Los usa el **partner afiliado**, no el creador. Hay dos tipos. El **TAP** (TikTok Affiliate Partner) arma campañas que juntan a vendedores con creadores y cobra parte de la comisión. La **CAP** (Creator Agency Partner, una agencia o MCN) consulta las órdenes y ganancias de los creadores que representa.
- Todos piden `category_asset_cipher`. Ese valor solo lo da *Get Authorized Category Assets* después de que un **partner** autoriza la app con el enlace `partner.tiktokshop.com/open/authorize?service_id=…`. El token que sale de esa autorización trae `user_type = 3`. El token de Corte es de **creador** (`user_type = 1`) y no tiene ese dato.
- Que la app tenga aprobados los scopes `partner.*` no basta. Esos scopes solo entran en un token de partner, nunca en el de creador.
- **Conclusión para Corte: 0 de 16 sirven con la cuenta de creador.** Para usar alguno, el usuario (o una agencia o TAP con quien trabaje) tendría que estar dado de alta como partner TAP o CAP en Partner Center y autorizar la app como partner. No pude verificar si una persona física puede registrarse como TAP o CAP en México.
- El dato más valioso de la familia son las **vistas, likes y comentarios por video** (endpoint 13). Solo existe para productos de una campaña TAP y solo lo ve el TAP dueño de esa campaña.
- Casi todo lo que la familia diría sobre el propio creador **ya llega por la Affiliate Creator API**: `campaign_id`, `creator_commission_reward_rate`, `isr`, `iva` y `shared_with_partner` en órdenes, y `collaboration.type = 5` (Partner Campaign) con `partner.id/name` en la Vitrina.

## Tabla de todos los endpoints

La columna «Scope» trae la clave probable de Partner Center. Las docs solo publican el **nombre** del scope, así que el emparejamiento nombre → clave es **inferido** (ver «Mapeo de scopes»).

> **[Nota del revisor, 15/11/2026]** El emparejamiento ya **está verificado** para las 6 claves. El JSON oficial que usa cada página docv2 (`https://partner.tiktokshop.com/api/v1/document/api_meta?src_document_id=<slug>&aid=359713&locale=en`, campo `scope_list[].scope_key`) da: `get-affiliate-partner-campaign-list-202405` → `partner.tap_campaign.read`; `create-affiliate-partner-campaign-202405` → `partner.tap_campaign.write`; `review-affiliate-partner-campaign-product-202405` → `partner.tap_campaign.product.write`; `generate-affiliate-partner-campaign-product-link-202405` → `partner.tap_campaign.link.write`; `generate-campaign-product-promotion-links-in-batch-202505` → `partner.tap_campaign.read` (como dice la spec); `search-cap-affiliate-orders-202603` → `partner.cap_orders.read`; `get-authorized-category-assets-202405` → `partner.authorization.info`. En todos, el header `x-tts-access-token` dice «when user_type = 3». Los demás endpoints de la tabla se asignan por el mismo nombre de scope.

| # | Nombre oficial | Método + path | Scope (clave probable) | ¿Sirve al creador? | Valor para Corte |
|---|---|---|---|---|---|
| 1 | Get Authorized Category Assets | `GET /authorization/202405/category_assets` | `partner.authorization.info` | No (requiere autorización de partner) | Bajo |
| 2 | Get Affiliate Partner Campaign List | `GET /affiliate_partner/202405/campaigns` | `partner.tap_campaign.read` | No (requiere ser TAP) | Bajo |
| 3 | Get Affiliate Partner Campaign Detail | `GET /affiliate_partner/202405/campaigns/{campaign_id}` | `partner.tap_campaign.read` | No (requiere ser TAP) | Bajo |
| 4 | Create Affiliate Partner Campaign | `POST /affiliate_partner/202405/campaigns` | `partner.tap_campaign.write` | No (requiere ser TAP) | Ninguno |
| 5 | Edit Affiliate Partner Campaign | `POST /affiliate_partner/202405/campaigns/{campaign_id}/partial_edit` | `partner.tap_campaign.write` | No (requiere ser TAP) | Ninguno |
| 6 | Publish Affiliate Partner Campaign | `POST /affiliate_partner/202405/campaigns/{campaign_id}/publish` | `partner.tap_campaign.write` | No (requiere ser TAP) | Ninguno |
| 7 | Get Affiliate Partner Campaign Product List | `GET /affiliate_partner/202405/campaigns/{campaign_id}/products` | `partner.tap_campaign.read` | No (requiere ser TAP) | Bajo |
| 8 | Review Affiliate Partner Campaign Product | `POST /affiliate_partner/202405/campaigns/{campaign_id}/products/{product_id}/review` | `partner.tap_campaign.product.write` | No (requiere ser TAP) | Ninguno |
| 9 | Generate Affiliate Partner Campaign Product Link | `POST /affiliate_partner/202405/campaigns/{campaign_id}/products/{product_id}/promotion_link/generate` | `partner.tap_campaign.link.write` | No (requiere ser TAP) | Bajo |
| 10 | Generate Campaign Product Promotion Links in Batch | `POST /affiliate_partner/202505/campaigns/{campaign_id}/products/promotion_links/generate_batch` | `partner.tap_campaign.read` (así lo marca la spec) | No (requiere ser TAP) | Bajo |
| 11 | Get Campaign Product Performance List | `GET /affiliate_partner/202501/campaigns/{campaign_id}/products/performance` | `partner.tap_campaign.read` | No (requiere ser TAP) | Bajo |
| 12 | Get Creator Performance for Campaign Product | `GET /affiliate_partner/202508/campaigns/{campaign_id}/products/{product_id}/performance` | `partner.tap_campaign.read` | No (requiere ser TAP) | Bajo |
| 13 | ⭐ Get Affiliate Campaign Creator Product Content Statistics | `GET /affiliate_partner/202508/campaigns/{campaign_id}/products/{product_id}/creator/{creator_temp_id}/content/statistics` | `partner.tap_campaign.read` | No. Sí solo si Corte fuera el TAP de una campaña donde el creador promueve el producto | **Alto si se cumple el requisito** (vistas, likes y comentarios por video). Requisito difícil |
| 14 | Get Affiliate Campaign Creator Product Sample Status | `GET /affiliate_partner/202508/campaigns/{campaign_id}/products/{product_id}/creator/{creator_temp_id}/content/statistics/sample/status` | `partner.tap_campaign.read` | No (requiere ser TAP) | Medio (rastreo de muestra, solo en campañas TAP) |
| 15 | Search TAP Affiliate Orders | `POST /affiliate_partner/202603/orders/search` | `partner.tap_campaign.read` | No (requiere ser TAP) | Bajo |
| 16 | Search CAP Affiliate Orders | `POST /affiliate_partner/202603/cap_order/search` | `partner.cap_orders.read` | No. Sí solo si una agencia (CAP) a la que esté vinculado el creador autoriza la app | Medio (impuestos estimados, `attribution_type`) |

---

## Conceptos que aplican a toda la familia

**Quién es el partner**
- La doc local `affiliate-creator-api-overview.txt` define la Affiliate Partner API como la de los **TikTok Affiliate Partners (TAPs)**. Sirve para manejar campañas que juntan a vendedores con creadores.
- Los TAP funcionan como «sub-afiliados» y cobran parte de la comisión, que siempre se reparte entre TAP y creador.
- En US/EMEA la norma son campañas de un TAP con un vendedor. En el resto del mundo, que incluye a México, son de un TAP con muchos vendedores, con «third party commission sharing».
- La descripción del endpoint 16 en la spec llama **CAP** a la agencia: «MCN (Creator Agency Partner)».

**Autorización de partner** (doc local `authorization-overview-202407.txt`)
- Enlace de autorización para resto del mundo: `https://partner.tiktokshop.com/open/authorize?service_id={service_id}`. En US cambia el dominio a `partner.us.tiktokshop.com`. Es otro enlace, distinto del de creador (`shop.tiktok.com/alliance/creator/auth?app_key=…&state=…`).
- El canje del código usa los mismos endpoints `auth.tiktok-shops.com/api/v2/token/get|refresh`.
- `user_type`: 1 = Creator y 3 = «Partner, current partner type used for Affiliate Partner / TAP authorization». El 2 es el tipo de partner antiguo.

**Parámetro `category_asset_cipher`**
- Todos los endpoints `/affiliate_partner/` lo piden en el query, en lugar del `shop_cipher` de vendedor.
- Se obtiene con el endpoint 1.
- La autorización del partner se otorga **por categoría de negocio**. Según la spec, la descripción del endpoint 1 dice: «access is granted based on business categories».

**Parámetros comunes**
- Van en el query: `app_key`, `timestamp` y `sign` (HMAC-SHA256). El token va en el header `x-tts-access-token`, igual que en la Affiliate Creator API (ver docs locales, sección *Common Parameters*).
- La spec marca `security: accessToken` y servidor `https://open-api.tiktokglobalshop.com`.

**Escenario en la spec**
- Los 15 endpoints `/affiliate_partner/` tienen `x-tts-scenario: 6` y el endpoint 1 tiene `x-tts-scenario: 7`.
- La spec no explica qué significa cada número.

**Disponibilidad regional** (doc local `affiliate-creator-api-overview.txt`)
- Las Affiliate APIs no están disponibles en Reino Unido ni en la UE.
- Hay señales de soporte para México:
  - Los endpoints 15 y 16 traen campos `*_isr` e `*_iva` marcados como «Mexico».
  - `MXN` aparece en los enums de moneda del endpoint 7.
- En `contact_info` de campañas, México no aparece entre los mercados que exigen WhatsApp, Zalo, Viber o LINE. Solo `email` es obligatorio.

**¿Por qué el token de creador no sirve?**
1. Todos los endpoints exigen `category_asset_cipher`, y ese valor solo sale de una autorización de partner.
2. La guía local `creator-authorization-guide.txt` dice que el token de creador solo lleva scopes `creator.*`. También documenta el error `101000` como «Wrong token identity or wrong API-token pairing».
3. Que el error exacto al usar un token de creador en estos endpoints sea `101000` es una **inferencia no probada**, porque las reglas prohíben llamar a la API.

**¿Podría un creador individual ser TAP o CAP?** **No verificado.**
- La doc local `affiliate-integration.txt` solo describe el registro como *service partner* para desarrolladores (ISV).
- La página oficial `business.tiktokshop.com/gb/partner` describe dos perfiles: «TikTok Shop Partners» y «Talent Agencies», estas últimas con servicios para creadores. Manda a aplicar en `partner.tiktokshop.com`, pero **no publica requisitos de elegibilidad** (persona moral o física, mínimos, etc.).
- La versión `/mx/partner` devuelve 404.
- No encontré ninguna fuente oficial que diga que un creador individual puede registrarse como TAP o CAP.

### Mapeo de scopes (nombre en docs → clave en Partner Center)

La spec (`x-tts-scopes`) y la doc local `affiliate-integration.txt` solo dan **nombres** de scope. Las claves `partner.*` vienen de la lista de la app que nos pasaron. Ninguna fuente pública consultada liga nombre con clave, así que el emparejamiento es **inferido por nombre**. Hay un antecedente análogo: «Shop Authorized Information» corresponde a `seller.authorization.info`.

| Nombre del scope en docs | ID (doc local) | Clave probable | Endpoints |
|---|---|---|---|
| Partner Authorized Information | — | `partner.authorization.info` | 1 |
| Read Affiliate Partner Campaigns | 733508 | `partner.tap_campaign.read` | 2, 3, 7, 10, 11, 12, 13, 14, 15 |
| Manage Affiliate Partner Campaigns | 733444 | `partner.tap_campaign.write` | 4, 5, 6 |
| Manage Affiliate Partner Campaign Products | 733572 | `partner.tap_campaign.product.write` | 8 |
| Manage Product Promote Links | — | `partner.tap_campaign.link.write` | 9 |
| Read CAP earnings order | — | `partner.cap_orders.read` | 16 |

La spec asigna el endpoint 10 (generación de enlaces en lote) a «Read Affiliate Partner Campaigns», no a «Manage Product Promote Links». Lo dejo tal como está documentado.

---

## Fichas detalladas

Todas las fichas comparten estas bases:
- **Fuente principal:** spec OpenAPI `https://raw.githubusercontent.com/isaackogan/TikTok-Shop-Api-SDKs/main/.openapi/tiktok-shop.openapi.yaml`, versión `2026.11.13`, generada de `partner.tiktokshop.com/docv2`.
- **Descripción de campos:** se leyó en la referencia generada de esa misma spec, `https://ttspa.docs.isaackogan.com/openapi/reference/operations/<slug>/`. Es un espejo no oficial generado de la spec; no es un blog.
- **URL oficial:** es el valor `x-tts-docs-url` de cada operación. Esas páginas se renderizan con JS y WebFetch no las pudo leer.

Montos: objetos `{amount: string, currency: string}`. Tasas: centésimas de punto porcentual (1000 = 10 %).

### 1. Get Authorized Category Assets
- **Método y path:** `GET /authorization/202405/category_assets` (operationId `getAuthorizedCategoryAssets`)
- **Scope:** «Partner Authorized Information», clave probable `partner.authorization.info`
- **Quién lo puede llamar:** token de **partner** (`user_type = 3`) después de la autorización de partner. La descripción dice «Target partner: All».
- **Parámetros:** ninguno propio, solo los comunes.
- **Respuesta:** `data.category_assets[]`, cada uno con:
  - `cipher`: el `category_asset_cipher`. No hay que descifrarlo.
  - `target_market`: string, sin enum documentado. El ejemplo trae `"US"`.
  - `category.id` (int64) y `category.name`. El nombre puede cambiar. El ejemplo trae id 3, «Customer Support».
- **Límites:** sin paginación. Sin errores específicos documentados.
- **¿Sirve con la cuenta de creador de Corte?** No. Sí con requisito: una cuenta de partner que autorice la app.
- **Valor para Corte:** bajo. Es un prerrequisito técnico. Lo único que diría es qué categorías de negocio tiene autorizadas el partner.
- **Fuente:** spec (path arriba); https://partner.tiktokshop.com/docv2/page/get-authorized-category-assets-202405 ; espejo `.../operations/getauthorizedcategoryassets/`. La spec enlaza a la *Partner authorization guide* (`docv2/page/678e3a3978f4c20311b8b555`), que no renderizó.

### 2. Get Affiliate Partner Campaign List
- **Método y path:** `GET /affiliate_partner/202405/campaigns` (`getAffiliatePartnerCampaignList`)
- **Scope:** «Read Affiliate Partner Campaigns» (ID 733508), clave probable `partner.tap_campaign.read`
- **Quién lo puede llamar:** partner TAP con `category_asset_cipher`.
- **Parámetros obligatorios:** `category_asset_cipher` y `page_size` (1–100).
- **Parámetro `status`:** la referencia lo marca obligatorio; la spec lo define como opcional. Valores: `READY`, `UPCOMING`, `ONGOING`, `CLOSED`, `UNSPECIFIED`.
- **Parámetros opcionales:**
  - `page_token`.
  - `type`: `MY_CAMPAIGNS` (por defecto), `GS_SELLING_CAMPAIGNS`, `SELLER_CAMPAIGNS` o `EXCLUSIVE_TIKTOK_SHOP`.
  - `query_type_filter`: es obligatorio cuando `type` es `SELLER_CAMPAIGNS` o `EXCLUSIVE_TIKTOK_SHOP`.
- **Reglas de `query_type_filter`:**
  - Con `SELLER_CAMPAIGNS`: `MARKETPLACE` (campañas aún no unidas) o `JOINED`.
  - Con `EXCLUSIVE_TIKTOK_SHOP`: `AVAILABLE` o `JOINED`.
  - Con `MARKETPLACE` o `AVAILABLE`, `status` debe ir en `UNSPECIFIED`.
  - Con los otros tipos se omite o va `DEFAULT`.
- **Respuesta:**
  - `campaigns[]` con `id`, `name`, `status`, `registration_start_time`, `registration_end_time`, `campaign_start_time` y `campaign_end_time` (Unix).
  - `next_page_token` y `total_count`.
- **Límites:** `page_size` máximo 100. Hay que repetir los mismos filtros en cada página.
- **Errores:** 16032001 («[I]nvalid parameter… Region mismatch», así viene en la spec), 16032007 Permission denied y 36009003 Internal error.
- **¿Sirve con la cuenta de creador de Corte?** No. Requiere ser TAP.
- **Valor para Corte:** bajo. Con `SELLER_CAMPAIGNS`/`MARKETPLACE` vería campañas de vendedores abiertas a TAPs, pero eso es una vista de TAP, no de creador.
- **Fuente:** spec; https://partner.tiktokshop.com/docv2/page/get-affiliate-partner-campaign-list-202405 ; espejo `.../getaffiliatepartnercampaignlist/`. El nombre y el scope también están en el doc local `affiliate-integration.txt` («API scope mapping»).

### 3. Get Affiliate Partner Campaign Detail
- **Método y path:** `GET /affiliate_partner/202405/campaigns/{campaign_id}` (`getAffiliatePartnerCampaignDetail`)
- **Scope:** «Read Affiliate Partner Campaigns», clave probable `partner.tap_campaign.read`
- **Quién lo puede llamar:** partner TAP.
- **Parámetros:** `campaign_id` en el path (entero decimal en string) y `category_asset_cipher` en el query. Los dos son obligatorios.
- **Respuesta:**
  - `id`, `name` (≤ 50 caracteres), `description` (≤ 1000), `status` y `region`.
  - Las 4 fechas de la campaña.
  - `commission_rate`: tasa total propuesta por el partner.
  - `contact_info`: `whatsapp`, `email`, `phone`, `zalo`, `viber` y `line`.
  - `target_shops[]` (`code`, `name`) y `target_seller_types[]` (`LOCAL`/`CROSS_BORDER`).
- **Límites:** ninguno aparte de los IDs.
- **Errores:** 16032001, 16032005 Campaign not found, 16032007 y 36009003.
- **¿Sirve con la cuenta de creador de Corte?** No. Requiere ser TAP.
- **Valor para Corte:** bajo.
- **Fuente:** spec; https://partner.tiktokshop.com/docv2/page/get-affiliate-partner-campaign-detail-202405 ; espejo `.../getaffiliatepartnercampaigndetail/`. También aparece en el doc local `affiliate-integration.txt`.

### 4. Create Affiliate Partner Campaign
- **Método y path:** `POST /affiliate_partner/202405/campaigns` (`createAffiliatePartnerCampaign`)
- **Scope:** «Manage Affiliate Partner Campaigns» (ID 733444), clave probable `partner.tap_campaign.write`
- **Quién lo puede llamar:** partner TAP.
- **Parámetro de query:** `category_asset_cipher`, obligatorio.
- **Cuerpo, campos obligatorios:**
  - `name`: 1–50 caracteres, sin espacio inicial.
  - `description`: 1–1000 caracteres.
  - `campaign_start_time`: no puede ser anterior a ahora.
  - `campaign_end_time`: periodo de 1 a 360 días.
  - `registration_start_time`: debe ser igual a `campaign_start_time`.
  - `registration_end_time`: al menos 1 día de registro y sin pasar de `campaign_end_time`.
  - `commission_rate`: de 100 a 8000.
  - `contact_info.email`.
- **Cuerpo, campos condicionales:**
  - `contact_info.whatsapp`: obligatorio en MY, SG, GB e ID; opcional en US.
  - `contact_info.zalo` en VN, `contact_info.viber` en PH y `contact_info.line` en TH.
  - `contact_info.phone` es opcional.
  - Hay que mandar **exactamente uno** de `target_shop_codes` (menos de 100) o `target_seller_types` (`LOCAL`/`CROSS_BORDER`).
- **Respuesta:** `data.campaign_id`. La campaña no se muestra a los vendedores hasta publicarla (endpoint 6).
- **Errores:** 16032001, 16032002 Invalid campaign period, 16032003 Invalid registration period, 16032004 Invalid campaign seller scope y 16032013 «Payment account not yet activated». Es decir, el TAP necesita una cuenta de pagos activa.
- **¿Sirve con la cuenta de creador de Corte?** No.
- **Valor para Corte:** ninguno. Corte no crea campañas.
- **Fuente:** spec; https://partner.tiktokshop.com/docv2/page/create-affiliate-partner-campaign-202405 ; espejo `.../createaffiliatepartnercampaign/`. También aparece en el doc local `affiliate-integration.txt`.

### 5. Edit Affiliate Partner Campaign
- **Método y path:** `POST /affiliate_partner/202405/campaigns/{campaign_id}/partial_edit` (`editAffiliatePartnerCampaign`)
- **Scope:** «Manage Affiliate Partner Campaigns», clave probable `partner.tap_campaign.write`
- **Quién lo puede llamar:** partner TAP.
- **Parámetros:** `campaign_id` en el path y `category_asset_cipher` en el query, los dos obligatorios.
- **Cuerpo:** todos los campos son opcionales y son los mismos que en Create. Lo que no se manda conserva su valor, también dentro de `contact_info`.
- **Reglas de edición:**
  - `target_shop_codes` y `target_seller_types` son excluyentes. Para cambiar de uno a otro se manda el anterior como arreglo vacío.
  - Las fechas de inicio solo se editan en `READY` o `UPCOMING`. Las de fin no se editan en `CLOSED`.
  - Una campaña cerrada no se puede editar.
- **Respuesta:** `data: {}`.
- **Errores:** 16032001–16032005, 16032007 y 16032008 Operation denied.
- **¿Sirve con la cuenta de creador de Corte?** No.
- **Valor para Corte:** ninguno.
- **Fuente:** spec; https://partner.tiktokshop.com/docv2/page/edit-affiliate-partner-campaign-202405 ; espejo `.../editaffiliatepartnercampaign/`. También aparece en el doc local `affiliate-integration.txt`.

### 6. Publish Affiliate Partner Campaign
- **Método y path:** `POST /affiliate_partner/202405/campaigns/{campaign_id}/publish` (`publishAffiliatePartnerCampaign`)
- **Scope:** «Manage Affiliate Partner Campaigns», clave probable `partner.tap_campaign.write`
- **Quién lo puede llamar:** partner TAP.
- **Parámetros:** `campaign_id` en el path y `category_asset_cipher` en el query. El cuerpo va vacío (`{}`).
- **Respuesta:** `data: {}`. Al publicarla, los vendedores ya ven la campaña.
- **Errores:** 16032001, 16032005, 16032007, 16032008 y 16032011 «Max campaign online count reached». Hay un tope de campañas en línea, pero la spec no dice cuántas.
- **¿Sirve con la cuenta de creador de Corte?** No.
- **Valor para Corte:** ninguno.
- **Fuente:** spec; https://partner.tiktokshop.com/docv2/page/publish-affiliate-partner-campaign-202405 ; espejo `.../publishaffiliatepartnercampaign/`. También aparece en el doc local `affiliate-integration.txt`.

### 7. Get Affiliate Partner Campaign Product List
- **Método y path:** `GET /affiliate_partner/202405/campaigns/{campaign_id}/products` (`getAffiliatePartnerCampaignProductList`)
- **Scope:** «Read Affiliate Partner Campaigns», clave probable `partner.tap_campaign.read`
- **Quién lo puede llamar:** partner TAP. Lista los productos que los vendedores inscribieron en su campaña.
- **Parámetros obligatorios:** `campaign_id` (path), `category_asset_cipher` y `page_size` (1–100).
- **Parámetros opcionales:**
  - `page_token`.
  - `review_status`: `PENDING`, `APPROVED`, `REJECTED`, `PENDING_CLOSED` o `CLOSED`.
  - `product_name` y `shop_name`, que buscan por subcadena.
  - `product_id`.
  - `category_id`, que también incluye las hojas debajo de esa categoría.
- **Respuesta, `products[]`:**
  - `id`, `review_status`, `name`, `main_image_url` y `product_description`.
  - `lowest_price` y `highest_price`.
  - `inventory`.
  - `shop_name`.
  - Tasas: `total_commission_rate`, `creator_commission_rate`, `partner_commission_rate` y `open_collaboration_commission_rate`.
  - `is_available`.
  - `product_sales`: unidades vendidas dentro de la campaña.
  - `category{id,name}`.
  - `sample_quota`: muestras que el vendedor puede repartir.
  - `sku_information_list[]`, cada uno con `sku_id`, `sku_name`, `inventory.available_quantity`, `base_price`, `region_prices[]` y `properties[]`. Los precios traen `list_price`, `sale_price` y `localized_dutiable_price`, y la moneda puede ser, entre otras, `MXN`.
  - Además: `next_page_token` y `total_count`.
- **Límites:** `page_size` máximo 100. Hay que repetir los filtros al paginar.
- **Errores:** 16032001, 16032005, 16032007 y 36009003.
- **¿Sirve con la cuenta de creador de Corte?** No. Requiere ser TAP.
- **Valor para Corte:** bajo. El reparto de comisión entre creador y partner y el `sample_quota` serían interesantes, pero solo para productos de la campaña del propio TAP.
- **Fuente:** spec; https://partner.tiktokshop.com/docv2/page/get-affiliate-partner-campaign-product-list-202405 ; espejo `.../getaffiliatepartnercampaignproductlist/`. También aparece en el doc local `affiliate-integration.txt`.

### 8. Review Affiliate Partner Campaign Product
- **Método y path:** `POST /affiliate_partner/202405/campaigns/{campaign_id}/products/{product_id}/review` (`reviewAffiliatePartnerCampaignProduct`)
- **Scope:** «Manage Affiliate Partner Campaign Products» (ID 733572), clave probable `partner.tap_campaign.product.write`
- **Quién lo puede llamar:** partner TAP. Aprueba o rechaza productos que los vendedores mandaron a su campaña. El producto tiene que estar pendiente.
- **Parámetros:** `campaign_id` y `product_id` en el path, y `category_asset_cipher` en el query.
- **Cuerpo:**
  - `review_result`, obligatorio: `APPROVE`, `REJECT` o `REJECT_FOREVER`.
  - `reject_reasons[]`, opcional: `COMMISSION_TOO_LOW`, `PRODUCT_HARD_TO_PROMOTE`, `PRODUCT_TOO_EXPENSIVE` o `NO_SUITABLE_CREATOR`.
- **Respuesta:** `data: {}`.
- **Errores:** 16032001, 16032005, 16032007 y 16032009 («Product operation denied, please ensure campaign is under online status»).
- **¿Sirve con la cuenta de creador de Corte?** No.
- **Valor para Corte:** ninguno.
- **Fuente:** spec; https://partner.tiktokshop.com/docv2/page/review-affiliate-partner-campaign-product-202405 ; espejo `.../reviewaffiliatepartnercampaignproduct/`. También aparece en el doc local `affiliate-integration.txt`.

### 9. Generate Affiliate Partner Campaign Product Link
- **Método y path:** `POST /affiliate_partner/202405/campaigns/{campaign_id}/products/{product_id}/promotion_link/generate` (`generateAffiliatePartnerCampaignProductLink`)
- **Scope:** «Manage Product Promote Links», clave probable `partner.tap_campaign.link.write`
- **Quién lo puede llamar:** partner TAP, para productos de una campaña en línea con `review_status` `APPROVED` o `PENDING_CLOSED`.
- **Parámetros:** `campaign_id` y `product_id` en el path, y `category_asset_cipher` en el query.
- **Cuerpo:** `creator_commission_rate`, obligatorio. Va de 100 (1 %) hasta la tasa total que fijó el vendedor para la campaña.
- **Respuesta:** `data.product_promotion_link`. La agencia lo comparte con sus creadores, que deciden si agregan el producto a su Vitrina.
- **Errores:** 16032001, 16032005, 16032007, 16032008, 16032009, 16032010 Campaign product not found y 36009003.
- **¿Sirve con la cuenta de creador de Corte?** No.
- **Valor para Corte:** bajo. Este endpoint es el lado del TAP, el que **le manda** el enlace al creador.
  - **[Corrección del revisor]** Aquí se afirmaba, sin fuente, que el creador usa `creator.affiliate.link.write` para sus enlaces. No está verificado: ninguna página `api_meta` revisada asocia esa clave a una API. Los enlaces del lado creador (Generate General Sharing Links 202505 y Generate Publisher Sharing Links in Batch 202504) piden `creator.affiliate.share_link.read`, verificado en su `api_meta`.
- **Fuente:** spec; https://partner.tiktokshop.com/docv2/page/generate-affiliate-partner-campaign-product-link-202405 ; espejo `.../generateaffiliatepartnercampaignproductlink/`.

### 10. Generate Campaign Product Promotion Links in Batch
- **Método y path:** `POST /affiliate_partner/202505/campaigns/{campaign_id}/products/promotion_links/generate_batch` (`generateCampaignProductPromotionLinksInBatch`)
- **Scope:** la spec dice «Read Affiliate Partner Campaigns», clave probable `partner.tap_campaign.read`.
- **Quién lo puede llamar:** partner TAP. En campañas iniciadas por TikTok (OPS) o por el vendedor se usa el **ID de campaña unida**, que se crea cuando el partner se une, y no el ID original.
- **Parámetros:** `campaign_id` en el path. `category_asset_cipher` va en el query y aquí no aparece como obligatorio.
- **Cuerpo:** `product_ids[]`, máximo 50.
- **Respuesta:** `data.product_promotion_links[]` (`product_id`, `link`) y `data.failed_product_ids[]`.
- **Límites:** 50 productos por llamada. La spec no documenta errores (`[]`).
- **¿Sirve con la cuenta de creador de Corte?** No.
- **Valor para Corte:** bajo.
- **Fuente:** spec; https://partner.tiktokshop.com/docv2/page/generate-campaign-product-promotion-links-in-batch-202505 ; espejo `.../generatecampaignproductpromotionlinksinbatch/`.

### 11. Get Campaign Product Performance List
- **Método y path:** `GET /affiliate_partner/202501/campaigns/{campaign_id}/products/performance` (`getCampaignProductPerformanceList`)
- **Scope:** «Read Affiliate Partner Campaigns», clave probable `partner.tap_campaign.read`
- **Quién lo puede llamar:** partner TAP.
- **Parámetros:** `campaign_id` (path) y `category_asset_cipher` son obligatorios. `page_size` (1–50) y `page_token` son opcionales.
- **Respuesta, `campaign_product_statistics[]`:**
  - `data_update_time`: string, el ejemplo viene en milisegundos.
  - Conteos: `creator_sales_num`, `collaborated_creators_num`, `promoted_creator_num` y `sample_requested_creator_num`.
  - `campaign_product_detail`, que trae:
    - `product_id`, `product_status` (`PRODUCT_PENDING`, `PRODUCT_APPROVED`, …), `product_name` y `product_stock_count`.
    - Tasas: `total_commission_percent`, que es la suma de `creator_commission_percent` y `partner_commission_percent`, más `plan_commission_percent`.
    - `product_price{min_price,max_price,currency}` y `product_thumbnail{uri,url_list[]}`.
    - `indicator_data`, todo en string: `paid_order_num`, `actual_order_num`, `estimated_amount`, `actual_amount` (GMV), `estimated_partner_commission`, `actual_partner_commission` y conteos de creadores.
  - Además: `total_count` y `next_page_token`.
- **Límites:** `page_size` máximo 50. Los números vienen como texto. La spec no documenta errores.
- **¿Sirve con la cuenta de creador de Corte?** No.
- **Valor para Corte:** bajo. Son agregados por producto de la campaña del TAP, no del creador.
- **Fuente:** spec; https://partner.tiktokshop.com/docv2/page/get-campaign-product-performance-list-202501 ; espejo `.../getcampaignproductperformancelist/`.

### 12. Get Creator Performance for Campaign Product
- **Método y path:** `GET /affiliate_partner/202508/campaigns/{campaign_id}/products/{product_id}/performance` (`getCreatorPerformanceForCampaignProduct`)
- **Scope:** «Read Affiliate Partner Campaigns», clave probable `partner.tap_campaign.read`
- **Quién lo puede llamar:** partner TAP.
- **Parámetros:** `campaign_id`, `product_id` (path) y `category_asset_cipher` son obligatorios. `page_size` (1–50) y `page_token` son opcionales.
- **Respuesta:** `total_creator_count` y `promotion_creators[]`, cada uno con:
  - `paid_amount{currency,amount}`, `room_count` y `video_count`.
  - `free_sample_status`, con 17 valores: `NOT_REQUESTED`, `PENDING`, `AWAITING_SHIPMENT`, `AWAITING_COLLECTION`, `SHIPPED`, `CONTENT_PENDING`, `REJECT_CANCELLED`, `OVERDUE_CANCELLED`, `UNFULFIL_CANCELLED`, `DEL_PLAN_CANCELLED`, `SELLER_NOT_SHIP_CANCELLED`, `WITHDRAW_CANCELLED`, `UNFULFILLABLE_CANCELLED`, `OPERATOR_MANUAL_CANCELLED`, `OPERATOR_MANUAL_FAILED`, `OPERATOR_MANUAL_COMPLETED` y `COMPLETED`.
  - `commission`.
  - `effective_start_time` y `effective_end_time`.
  - `creator{nick_name, avatar_url, follower_num, user_name, creator_open_id}`.
  - `affiliate_product_id`.
  - Además: `next_page_token`.
- **Límites:** `page_size` máximo 50.
- **Errores:** 36009003.
- **¿Sirve con la cuenta de creador de Corte?** No.
- **Valor para Corte:** bajo. Para el creador solo saldría su propia fila, y únicamente en campañas del TAP. La lista de 17 estados de muestra sí sirve de **referencia** para nombrar estados en la interfaz: coincide con los que Corte ya ve, como `UNFULFIL_CANCELLED` y `SELLER_NOT_SHIP_CANCELLED`.
- **Fuente:** spec; https://partner.tiktokshop.com/docv2/page/get-creator-performance-for-campaign-product-202508 ; espejo `.../getcreatorperformanceforcampaignproduct/`.

### 13. ⭐ Get Affiliate Campaign Creator Product Content Statistics
- **Método y path:** `GET /affiliate_partner/202508/campaigns/{campaign_id}/products/{product_id}/creator/{creator_temp_id}/content/statistics` (`getAffiliateCampaignCreatorProductContentStatistics`)
- **Scope:** «Read Affiliate Partner Campaigns», clave probable `partner.tap_campaign.read`
- **Quién lo puede llamar:** partner TAP, sobre un creador que promueve un producto de su campaña.
- **Parámetros obligatorios:**
  - En el path: `campaign_id`, `product_id` y `creator_temp_id` (Creator Open ID). Get Creator Profile 202508 devuelve `creator_user_open_id`, también descrito como «Creator Open ID». **No está verificado** que sea el mismo valor que ve el TAP.
  - En el query: `affiliate_product_id` y `category_asset_cipher`.
- **Parámetro opcional:** `content_type` (`VIDEO` o `LIVE_ROOM`).
- **Respuesta, `creator_content_statistics[]`:**
  - `content_type`.
  - `cover_img_url`: **solo para LIVE; los videos no lo traen**.
  - `source_url`: URL pública reproducible.
  - `view_count`, `like_count` y `comment_num`.
  - `paid_order_num` y `paid_amount`.
  - `linked_tiktok_video`: URL amigable.
  - `published_date` y `content_end_date`. Este último es null en videos. La doc dice formato `YYYY_MM_DD`, pero el ejemplo usa `2024-11-13`.
- **Límites:** sin paginación documentada. Un creador y un producto por llamada.
- **Errores:** 16032001 y 36009003.
- **¿Sirve con la cuenta de creador de Corte?** No. Sí solo si Corte fuera el TAP de una campaña donde el creador promueve ese producto. En la práctica, eso exige que el usuario sea TAP, cree una campaña y se promueva a sí mismo.
- **Valor para Corte:** **alto como dato, con viabilidad muy baja.** Daría **vistas, likes y comentarios por video**, un dato que Corte no tiene por ninguna otra vía documentada. También el enlace reproducible. **No** resuelve las portadas de video, porque `cover_img_url` solo viene en LIVE.
- **Fuente:** spec; https://partner.tiktokshop.com/docv2/page/get-affiliate-campaign-creator-product-content-statistics-202508 ; espejo `.../getaffiliatecampaigncreatorproductcontentstatistics/`.

### 14. Get Affiliate Campaign Creator Product Sample Status
- **Método y path:** `GET /affiliate_partner/202508/campaigns/{campaign_id}/products/{product_id}/creator/{creator_temp_id}/content/statistics/sample/status` (`getAffiliateCampaignCreatorProductSampleStatus`)
- **Scope:** «Read Affiliate Partner Campaigns», clave probable `partner.tap_campaign.read`
- **Quién lo puede llamar:** partner TAP. El creador debe haber pedido la muestra de ese producto antes.
- **Parámetros:** `campaign_id`, `product_id` y `creator_temp_id` en el path, y `category_asset_cipher` en el query. Todos obligatorios.
- **Respuesta, `data.sample_status`:**
  - `shipping_provider_name`.
  - `delivery_option`: `ECONOMY_SHIPPING` o `PREMIUM_SHIPPING`.
  - `estimated_earliest_delivery_date` y `estimated_latest_delivery_date` (Unix, en string).
  - `quantity`.
  - `tracking_results[]`:
    - `tracking_event_update_date`.
    - `tracking_event_description`: `THE_PACKAGE_HAS_BEEN_DELIVERED`, `OUT_FOR_DELIVERY`, `ORDER_PACKED_AND_READY_FOR_DROP_OFF_AT_CARRIERS_FACILITY` u `ORDER_PLACED`.
    - `tracking_event_description_extended`.
- **Límites:** una muestra por llamada.
- **Errores:** 16032001 y 36009003.
- **¿Sirve con la cuenta de creador de Corte?** No. Requiere ser TAP, y además la muestra tendría que pertenecer a una campaña de ese TAP. Las muestras de Corte vienen de colaboraciones de tiendas (`FREE_SAMPLE`), no de campañas TAP.
- **Valor para Corte:** medio como dato: paquetería, ventana estimada de entrega y eventos de rastreo, justo el tema de muestras. En la práctica no aplica a sus muestras actuales.
- **Fuente:** spec; https://partner.tiktokshop.com/docv2/page/get-affiliate-campaign-creator-product-sample-status-202508 ; espejo `.../getaffiliatecampaigncreatorproductsamplestatus/`.

### 15. Search TAP Affiliate Orders
- **Método y path:** `POST /affiliate_partner/202603/orders/search` (`searchTAPAffiliateOrders`)
- **Scope:** «Read Affiliate Partner Campaigns», clave probable `partner.tap_campaign.read`
- **Quién lo puede llamar:** partner **TAP**. La descripción dice «TAP can use this API…».
- **Parámetros de query:** `category_asset_cipher` y `page_size` (1–100, por defecto 20) son obligatorios. `page_token` es opcional.
- **Cuerpo (opcional):** `create_time_ge` y `create_time_lt` van en pareja, y `campaign_id` es opcional.
- **Respuesta, `sku_orders[]`:**
  - Identificación y fechas: `id`, `create_time`, `delivery_time`, `settlement_time` y `last_update_time`.
  - `settle_status`: `CUSTOMER UNPAID`, `PENDING`, `SETTLED`, `INELIGIBLE` o `FROZEN`.
  - Producto y contenido: `sku_id`, `campaign_id`, `creator_username`, `product_name`, `product_id`, `price`, `quantity`, `content_type` y `content_id`.
  - Tasas: `creator_/partner_standard_commission_rate`, `creator_/partner_shop_ads_commission_rate` y `creator_/partner_tap_bonus_commission_rate`.
  - `is_carousel` y `fully_return`.
  - Montos `estimated_*` y `actual_*` para creador y partner. Incluyen `estimated_partner_isr`, `estimated_partner_iva`, `actual_partner_isr` y `actual_partner_iva`, marcados «Mexico».
  - Además: `next_page_token` y `total_count`, que cuenta líneas SKU.
- **Límites:**
  - Ventana máxima de **3 meses**. Sin fechas, toma los últimos 3 meses.
  - `page_size` máximo 100.
  - Hay que repetir `campaign_id` y las fechas en cada página.
  - Los montos `actual_*` solo vienen con `SETTLED` o `INELIGIBLE`.
- **Errores:** 36009003.
- **¿Sirve con la cuenta de creador de Corte?** No. Requiere ser TAP. Además, solo devuelve órdenes de las campañas de **ese** TAP.
- **Valor para Corte:** bajo. Para el creador, lo único nuevo sería cuánto se queda el TAP: las tasas y montos `partner_*`. Corte ya recibe `campaign_id` y `creator_commission_reward_rate` en sus propias órdenes.
- **Fuente:** spec; https://partner.tiktokshop.com/docv2/page/search-tap-affiliate-orders-202603 ; espejo `.../searchtapaffiliateorders/`.

### 16. Search CAP Affiliate Orders
- **Método y path:** `POST /affiliate_partner/202603/cap_order/search` (`searchCAPAffiliateOrders`)
- **Scope:** «Read CAP earnings order», clave probable `partner.cap_orders.read`
- **Quién lo puede llamar:** partner **CAP**, es decir, la agencia o MCN de creadores («MCN (Creator Agency Partner)» según la descripción).
- **Parámetros de query:** `category_asset_cipher` y `page_size` (1–100, por defecto 20) son obligatorios. `page_token` es opcional.
- **Cuerpo (opcional, filtros con AND):**
  - `order_id` y `product_id`.
  - `settle_status`: 1 CUSTOMER UNPAID, 2 PENDING, 3 SETTLED, 4 INELIGIBLE o 5 FROZEN.
  - `create_time_ge` y `create_time_lt`, en pareja.
- **Respuesta, `sku_orders[]`:**
  - Identificación: `id`, `tags`, `sku_id`, `open_collaboration_id`, `target_collaboration_id`, **`creator_username`**, `product_name`, `product_id`, `shop_name`, `quantity` y `price`.
  - Fechas: `create_time`, `delivery_time`, `settlement_time` y `last_update_time`.
  - Estado: `settle_status` (etiqueta), `fully_return` e `is_carousel`.
  - Contenido: `content_type`, `content_id` y **`attribution_type`** (`Direct`, `Indirect` o vacío).
  - Configuración de comisión: `commission_model`, `commission_tier_setting`, `standard_commission_rate`, `commission_bonus_rate`, `shop_ads_commission_rate`, `tap_bonus_commission_rate` y **`revenue_sharing_portion_rate`**.
  - Montos estimados: `estimated_commission_base`, `_standard_commission`, `_bonus_commission`, `_shop_ads_commission`, `_tap_bonus_commission`, **`estimated_creator_tax_isr`**, **`estimated_creator_tax_iva`**, `estimated_creator_tax_pit`, **`estimated_creator_total_earnings_after_tax`**, `estimated_total_agency_earnings`, `estimated_agency_isr` y `estimated_agency_iva`.
  - Montos reales: los equivalentes `actual_*`, entre ellos `actual_creator_total_earnings_after_tax`, `actual_total_agency_commission`, `actual_agency_isr` y `actual_agency_iva`. Solo vienen con `SETTLED` o `INELIGIBLE`.
  - Además: `next_page_token` y `total_count`, que cuenta líneas SKU.
- **Límites:**
  - Ventana máxima de **92 días**. Sin fechas, toma los 3 meses calendario anteriores hasta ahora.
  - `page_size` máximo 100.
  - Para paginar estable hay que fijar `create_time_ge` y `create_time_lt`.
- **Errores:** 36009003.
- **¿Sirve con la cuenta de creador de Corte?** No. Sí con requisito: que el creador esté vinculado a una agencia (CAP) y que **esa agencia** autorice la app de Corte como partner. Ojo: la respuesta traería las órdenes de **todos** los creadores de la agencia. Habría que filtrar por `creator_username` y no guardar lo ajeno, según las políticas de mínimo necesario.
- **Valor para Corte:** medio. Corte ya recibe `isr`, `iva`, `shared_with_partner` y `actual_commission` en `POST /affiliate_creator/202410/orders/search`. Lo nuevo sería:
  - el **desglose estimado y real** de impuestos;
  - la **ganancia neta estimada después de impuestos** para órdenes aún no liquidadas;
  - `attribution_type` (directa o indirecta);
  - `revenue_sharing_portion_rate`, el porcentaje que se va a la agencia.
- **Fuente:** spec; https://partner.tiktokshop.com/docv2/page/search-cap-affiliate-orders-202603 ; espejo `.../searchcapaffiliateorders/`. Los campos de la API de creador vienen del doc local `search-creator-affiliate-orders-202410.txt`.

---

## Qué sí puede hacer Corte desde su lado (sin la API de partner)

Todo esto está documentado en las docs locales de la Affiliate Creator API, que ya se usa:

- **¿Vende el creador por campañas TAP?** En cada SKU de `POST /affiliate_creator/202410/orders/search`, revisar `skus[].campaign_id`, `creator_commission_reward_rate`, `estimated_creator_commission_reward_fee` y `actual_creator_commission_reward_fee`. Según la doc local, el `reward_rate` es lo que un affiliate partner le asigna al creador. Fuente: `search-creator-affiliate-orders-202410.txt`. También existe en `search-affiliate-orders-by-creator-202505.txt`.
- **¿Está vinculado a una agencia?** Revisar `skus[].shared_with_partner`: es la parte del ingreso después de impuestos que se comparte con la institución afiliada. Si viene con monto, hay una agencia de por medio. Fuente: `search-creator-affiliate-orders-202410.txt`.
- **Productos de campaña TAP en la Vitrina:** en `GET /affiliate_creator/202405/showcases/products`, ver `collaboration.type = 5` («Partner Campaign») junto con `collaboration.partner.id/name` y `commission.reward_rate`. Fuente: `get-showcase-products-202405.txt`.
- **Impuestos de México:** las órdenes de creador ya traen `isr` e `iva` («Only for Mexico creator»). No hace falta la API de CAP para mostrarlos.

## Huecos y pendientes

1. ~~**Claves de scope no verificadas.**~~ **[Revisor]** Resuelto: las 6 claves `partner.*` se verificaron en el `api_meta` oficial (ver la nota bajo «Tabla de todos los endpoints»).
2. **Elegibilidad TAP/CAP en México no verificada:** no hay fuente oficial legible sobre requisitos ni sobre si una persona física puede registrarse. `partner.tiktokshop.com` (docs de autorización de partner) no renderiza con WebFetch, y `business.tiktokshop.com/mx/partner` da 404.
3. **Error exacto con token de creador no verificado:** que estos endpoints rechacen el token de creador se deduce de que exigen `category_asset_cipher`. No se probó contra la API, por regla.
4. **Equivalencia de `creator_temp_id` con `creator_user_open_id`** (endpoints 13 y 14): no verificada.
5. **Límite de campañas en línea** (error 16032011): la spec no da el número.
6. **Significado de `x-tts-scenario` 6 y 7:** no documentado en la spec.
7. **Errores del endpoint 1 y de los endpoints 202501/202505:** la spec no lista errores específicos.
8. Las páginas oficiales `docv2` de cada endpoint (URL en cada ficha) se renderizan con JS y no se pudieron leer directamente. Todo se tomó de la spec generada de ellas y de las docs locales.
9. `developers.tiktok.com` y `business-api.tiktok.com` no tienen esta familia: viven solo en la TikTok Shop Partner API (`open-api.tiktokglobalshop.com`). No se usaron como fuente.
10. Hay una discrepancia menor: la referencia generada usa la spec `2026.10.28` y el YAML crudo es `2026.11.13`. No encontré diferencias en esta familia.

## Fuentes

- Docs locales:
  - `research\tiktok-docs\affiliate-creator-api-overview.txt`: tipos de Affiliate API, definición de TAP y campañas por región.
  - `research\tiktok-docs\affiliate-integration.txt`: «API scope mapping» con los IDs 733508, 733444 y 733572, y el registro como partner.
  - `research\tiktok-docs\authorization-overview-202407.txt`: enlace de autorización de partner y `user_type = 3`.
  - `research\tiktok-docs\creator-authorization-guide.txt`: scopes `creator.*` y error 101000.
  - `research\tiktok-docs\search-creator-affiliate-orders-202410.txt`, `search-affiliate-orders-by-creator-202505.txt` y `get-showcase-products-202405.txt`: campos de lado creador relacionados con campañas y agencias.
- Spec OpenAPI (fuente principal de los 16 endpoints): https://raw.githubusercontent.com/isaackogan/TikTok-Shop-Api-SDKs/main/.openapi/tiktok-shop.openapi.yaml (info.version 2026.11.13, «Generated from the TikTok Shop Partner Center documentation»).
- Referencia generada de esa spec (descripciones de campos): https://ttspa.docs.isaackogan.com/openapi/reference/ (grupos «Affiliate partner» y «Authorization»).
- URLs oficiales (`x-tts-docs-url`, no renderizan sin JS): `https://partner.tiktokshop.com/docv2/page/<slug>`, listadas en cada ficha.
- Página oficial de tipos de partner (sin requisitos de elegibilidad): https://business.tiktokshop.com/gb/partner
