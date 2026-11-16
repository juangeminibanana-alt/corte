# 02 · Affiliate Seller API (lado VENDEDOR): catálogo de endpoints

Familia: `seller.affiliate_collaboration.read`, `seller.affiliate_collaboration.write`, `seller.creator_marketplace.read`, `seller.affiliate_messages.write`.
Revisado el 15/11/2026 solo con documentación. No se llamó a la API real ni se abrió `config.json`.

## Resumen de la familia

- La Affiliate Seller API (prefijo `/affiliate_seller/`) tiene **48 endpoints vigentes** en el árbol oficial de docv2. Son el lado VENDEDOR del programa de afiliados: colaboraciones abiertas y dirigidas, reglas y revisión de muestras, búsqueda de creadores en el Creator Marketplace con métricas, mensajería tienda↔creador (10 APIs más el webhook 33), cupos de alcance a creadores, pedidos de afiliado de la tienda, reportes Compass y campañas de partner vistas desde la tienda.
- **Las 48 piden en el header el access_token de VENDEDOR.** El texto literal de docv2 es «The seller access_token value from Get Access Token, when user_type = 0». Todas, menos una, piden también el `shop_cipher` de la tienda.
- **Con el token de creador de Corte (user_type = 1) no se puede llamar ninguna.** Los endpoints de creador usan otro escenario: docv2 y la spec marcan `scenario = 4` para creador y `scenario = 1` para vendedor.
- La app de Corte («Creator collaborations», México) **sí está en las categorías habilitadas** de docv2 para registro MX → mercado MX en 42 de los 48 endpoints. Además ya tiene aprobados los 4 scopes de la familia y `seller.authorization.info`. El único bloqueo es que **una tienda MX autorice la app** y entregue un token de vendedor.
- Lo único con valor real para un creador es ⭐ **Get Marketplace Creator Performance**: muestra cómo ven las tiendas a Corte (PPS, calificación de vendedores, tasa de publicación tras muestra, puntuación de muestras, puntuación de cumplimiento a 90 días, nivel, demografía de seguidores, GMV/GPM y tendencia). Funciona solo con un token de tienda MX, por ejemplo de una tienda propia de Corte.
- **No existe API de mensajes del lado creador.** Toda la mensajería es de la tienda, así que Corte no puede leer ni contestar mensajes de las tiendas por API. El webhook 33 avisa a la TIENDA cuando un creador le escribe.

### Requisitos usados en este archivo

- **R1:** una tienda de TikTok Shop **MX** (puede ser una tienda propia de Corte) autoriza la app con el enlace de vendedor. Así se obtiene un token de vendedor (`user_type = 0`) y el `shop_cipher` con Get Authorized Shops (`GET /authorization/202309/shops`, scope `seller.authorization.info`).
- **R2:** la tienda que autoriza la app es **una de las tiendas que colaboran con Corte** (le mandaron muestras o invitaciones). Los datos solo cubren a esa tienda. Es poco realista.

## Tabla breve de TODOS los endpoints

Abreviaturas de scope: **CR** = `seller.affiliate_collaboration.read`, **CW** = `seller.affiliate_collaboration.write`, **MK** = `seller.creator_marketplace.read`, **MSG** = `seller.affiliate_messages.write`.

| # | Nombre oficial | Método + path | Scope | ¿Sirve al creador? | Valor |
|---|---|---|---|---|---|
| A1 | Get Open Collaboration Settings | GET /affiliate_seller/202409/open_collaboration_settings | CR | No | ninguno |
| A2 | Edit Open Collaboration Settings | POST /affiliate_seller/202405/open_collaboration_settings | CW | No | ninguno |
| A3 | Get Open Collaboration Sample Rules | GET /affiliate_seller/202410/open_collaborations/sample_rules | CR | No (solo con R2) | bajo |
| A4 | Edit Open Collaboration Sample Rule | POST /affiliate_seller/202410/open_collaborations/sample_rules | CW | No | ninguno |
| A5 | Create Open Collaboration | POST /affiliate_seller/202412/open_collaborations | CW | No | ninguno |
| A6 | Search Open Collaborations | POST /affiliate_seller/202412/open_collaborations/search | CR | No | ninguno |
| A7 | Remove Open Collaboration | DELETE /affiliate_seller/202409/open_collaborations/products/{product_id} | CW | No | ninguno |
| A8 | Get Open Collaboration Creator Content Details | GET /affiliate_seller/202508/open_collaborations/creator_content_details | CR | No (solo con R2) | bajo |
| A9 | Seller Search Open Collaboration Products | POST /affiliate_seller/202405/open_collaborations/products/search | CR | Sí con R1 (redundante) | bajo |
| A10 | Remove Creator From Open Collaboration Product | POST /affiliate_seller/202508/open_collaborations/{open_collaboration_id}/remove_creator | CW | No | ninguno |
| B1 | Create Target Collaboration | POST /affiliate_seller/202508/target_collaborations | CW | No | ninguno |
| B2 | Search Target Collaborations | POST /affiliate_seller/202508/target_collaborations/search | CR | No | ninguno |
| B3 | Update Target Collaboration | PUT /affiliate_seller/202508/target_collaborations/{target_collaboration_id} | CW | No | ninguno |
| B4 | Remove Target Collaboration | DELETE /affiliate_seller/202409/target_collaborations/{target_collaboration_id} | CW | No | ninguno |
| B5 | Query Target Collaboration Detail | GET /affiliate_seller/202508/target_collaborations/{target_collaboration_id} | CR | No (solo con R2) | bajo |
| B6 | Generate Target Collaboration Link | POST /affiliate_seller/202509/target_collaboration/{target_collaboration_id}/link | CW | No | ninguno |
| B7 | Check Target Collaboration Conflicts | POST /affiliate_seller/202605/target_collaborations/conflicts/check | CW | No | ninguno |
| B8 | Resolve Target Collaboration Conflicts | POST /affiliate_seller/202605/target_collaborations/conflicts/resolve | CW | No | ninguno |
| B9 | Query Creator Promotion Details in Target Collaboration | POST /affiliate_seller/202608/target_collaborations/creator_promotion_details/query | CR + CW | No (solo con R2) | bajo |
| C1 | Search Sample Applications | POST /affiliate_seller/202508/sample_applications/search | CR | No (solo con R2) | bajo |
| C2 | Review a Sample Application | POST /affiliate_seller/202507/sample_applications/{application_id}/review | CW | No | ninguno |
| C3 | Search Sample Application Fulfillments | POST /affiliate_seller/202409/sample_applications/{application_id}/fulfillments/search | CR | No (solo con R2) | bajo |
| C4 | Seller Get Sample Request Deeplink | GET /affiliate_seller/202512/sample_applications/deeplink | CR | No | ninguno |
| D1 | Get Conversation List | GET /affiliate_seller/202412/conversations | MSG | No | ninguno |
| D2 | Get Creator Conversation Messages | GET /affiliate_seller/202412/conversation/{conversation_id}/messages | MSG | No | ninguno |
| D3 | Get Latest Unread Messages | GET /affiliate_seller/202412/conversations/messages/list/newest | MSG | No | ninguno |
| D4 | Get or Create Creator Conversation | POST /affiliate_seller/202508/conversations | MSG | No | ninguno |
| D5 | Upload Message Image | POST /affiliate_seller/202511/images/upload | MSG | No | ninguno |
| D6 | Send IM Message | POST /affiliate_seller/202412/conversations/{conversation_id}/messages | MSG | No | ninguno |
| D7 | Mark Conversations as Read | POST /affiliate_seller/202412/conversatons/read (sic) | MSG | No | ninguno |
| D8 | Get Inbox Category Counts | GET /affiliate_seller/202608/conversations/group_counts | MSG | No | ninguno |
| D9 | Update Conversation Status | POST /affiliate_seller/202608/conversations/{conversation_id}/status | MSG | No | ninguno |
| D10 | Upload Message Image V2 | POST /affiliate_seller/202608/media/upload | MSG | No | ninguno |
| E1 | Search Creators in Creator Marketplace | POST /affiliate_seller/202608/marketplace_creators/search | MK | Sí con R1 | medio |
| E2 | Get Creator Marketplace Advanced Search Filters | POST /affiliate_seller/202608/marketplace_creators/search/filter | MK | Sí con R1 | bajo |
| E3 | ⭐ Get Marketplace Creator Performance | GET /affiliate_seller/202608/marketplace_creators/{creator_user_id} | MK | Sí con R1 (más riesgos, ver ficha) | **alto** |
| F1 | Get Weekly Creator Outreach Quota | GET /affiliate_seller/202607/creator_outreach/quota | CR | No | ninguno |
| F2 | Get Weekly Creator Outreach Records | POST /affiliate_seller/202608/creator_outreach/records/query | CR + CW | No | ninguno |
| F3 | Check Creator Outreach Eligibility | POST /affiliate_seller/202610/creator_outreach/eligibility/check | CR | Sí con R1 (solo da creator_level) | bajo |
| G1 | Search Seller Affiliate Orders | POST /affiliate_seller/202410/orders/search | CR | No (solo con R2) | bajo |
| G2 | Create Compass Offline Export Task | POST /affiliate_seller/202603/compass/offline_task | CR | No | ninguno |
| G3 | Get Compass Task List | GET /affiliate_seller/202603/compass/offline_tasks | CR | No | ninguno |
| G4 | Download Compass Task File | GET /affiliate_seller/202603/compass/offline_tasks/{task_id}/file | CR | No | ninguno |
| H1 | Search Seller Partner Campaigns | GET /affiliate_seller/202611/partner_campaigns | CR | No | ninguno |
| H2 | Get Seller Partner Campaign Detail | GET /affiliate_seller/202611/partner_campaigns/{campaign_id} | CR | No | ninguno |
| H3 | Get Seller Partner Campaign Candidate Products | GET /affiliate_seller/202611/partner_campaigns/{campaign_id}/candidate_products | CR | No | ninguno |
| H4 | Get Seller Partner Campaign Registered Products | GET /affiliate_seller/202611/partner_campaigns/{campaign_id}/products | CR | No | ninguno |
| H5 | Register Seller Partner Campaign Products | POST /affiliate_seller/202611/partner_campaigns/{campaign_id}/products | CW | No | ninguno |
| W1 | Webhook (33) New message listener | evento push (no es endpoint) | no indicado en la doc | No | ninguno |
| W2 | Webhook (56) Sample Application Status Change | evento push (no es endpoint) | no indicado en la doc | No (solo con R2) | bajo |
| L1 | Generate Affiliate Product Promotion Link (legado) | POST /affiliate_seller/202405/products/{product_id}/promotion_link/generate | CW (según guía) | No | ninguno · **no verificado como vigente** |
| L2 | Create Target Collaboration (legado 202405) | POST /affiliate_seller/202405/target_collaborations | CW (según guía) | No | ninguno · reemplazado por B1 |
| L3 | Remove Creator Affiliate from Collaboration (legado 202405) | POST /affiliate_seller/202405/open_collaborations/{id}/remove_creator | CW (según guía) | No | ninguno · reemplazado por A10 |

«No» significa que no funciona con el token de creador (user_type = 1). Con R1, cualquier endpoint funcionaría técnicamente, pero devolvería datos **de la tienda**, no de Corte. Por eso solo se marca «Sí con R1» donde el dato le sirve a un creador.

## Reglas comunes a los 48 endpoints (verificadas)

- **Host:** `https://open-api.tiktokglobalshop.com`. Query comunes: `app_key`, `sign`, `timestamp` y `shop_cipher`. Headers: `content-type: application/json` (multipart para subir imágenes) y `x-tts-access-token` = **token de vendedor, user_type = 0** (texto de docv2 en las 48 páginas).
- **`shop_cipher`:** lo exigen 47 de 48 (`is_shop_chiper_exist = true` en docv2 y `requiresShopCipher: True` en la spec). La excepción es **D5 Upload Message Image (202511)**. El valor se obtiene con Get Authorized Shops `GET /authorization/202309/shops` (scope `seller.authorization.info`, también con token de vendedor).
- **Autorización de vendedor (ROW, incluye MX):** `https://services.tiktokshop.com/open/authorize?service_id={service_id}`. Los tokens se canjean igual que los de creador (`auth.tiktok-shops.com/api/v2/token/get`), pero son **dos tokens distintos** (fuente: `research/tiktok-docs/authorization-overview-202407.txt` y `affiliate-integration.txt`).
- **Escenario:** las 48 tienen `scenario = 1` en docv2 y en la spec. Para comparar, los endpoints `/affiliate_creator/` tienen `scenario = 4` y los `/affiliate_partner/` tienen `scenario = 6`. Excepción: D5 tiene `scenario = 2`.
- **Disponibilidad en México:** consulté el buscador «View app categories» de cada página de docv2 con registro = MX y mercado = MX. En **42 de 48** endpoints aparecen las categorías «App developer / Customer Engagement / **Creator collaborations**» (la categoría de la app de Corte) y «Seller inhouse developer / TikTok Shop Seller». En los 6 más nuevos (F3 y H1–H5) docv2 no tiene `api_basic_id`, así que **la disponibilidad en MX no se pudo verificar**. El overview dice que las Affiliate APIs no están disponibles en UK ni en la UE.
- **Comisiones:** casi siempre se expresan en centésimas de por ciento (`1000` = 10%, rango 100–8000). Excepción: `commission_rate` de C1 es un decimal en texto (`"0.20"` = 20%, rango 0.01–0.8).
- **Creator Open ID:** es un identificador seudónimo **único por app**. Dos tiendas que usan la misma app ven el mismo Open ID del creador; apps distintas ven Open IDs distintos (docv2 «Creator Open ID for Affiliate APIs», página `3obfokj6`). Corte ya puede obtener el suyo con Get Creator Profile 202508 (`creator_user_open_id`, ver `research/tiktok-docs/get-creator-profile-202508.txt`).
- **Errores comunes:** `36009003` (error interno, reintentar) y `98001004` (parámetro inválido).
- **Erratas oficiales que hay que respetar al pie de la letra:** path `conversatons/read` (D7); GET `conversation/{id}/messages` en singular contra POST `conversations/{id}/messages` (D2/D6); `target_collaboration/{id}/link` en singular (B6); campos `creator_user_oepn_id` y `target_collabration_id` (C1); `creator_inivited_count` (B2); `creator_agency_staus` (E1).

---

## Fichas detalladas

### A. Colaboraciones abiertas (open collaborations)

#### A1. Get Open Collaboration Settings
- **Método y path:** `GET /affiliate_seller/202409/open_collaboration_settings`
- **Scope:** Read Seller Affiliate Collaboration (`seller.affiliate_collaboration.read`)
- **Quién lo puede llamar:** token de vendedor con shop_cipher.
- **Parámetros:** solo los comunes.
- **Respuesta:** `open_collaboration_settings.auto_add_product.enable` (bool) y `.commission_rate` (int, comisión por defecto de los productos agregados automáticamente).
- **Límites:** ninguno documentado.
- **¿Sirve con la cuenta de creador de Corte?** No.
- **Valor para Corte:** ninguno.
- **Fuente:** https://partner.tiktokshop.com/docv2/page/get-open-collaboration-settings-202409 · spec `getOpenCollaborationSettings`.

#### A2. Edit Open Collaboration Settings
- **Método y path:** `POST /affiliate_seller/202405/open_collaboration_settings`
- **Scope:** Manage Seller Affiliate Collaboration (`seller.affiliate_collaboration.write`)
- **Quién:** token de vendedor con shop_cipher.
- **Parámetros (body):** `auto_add_product` (opcional), con `enable` (bool, obligatorio) y `commission_rate` (int, obligatorio, 100–8000). Inscribe el catálogo actual y los productos futuros en colaboración abierta. Viene apagado por defecto.
- **Respuesta:** `data: {}`.
- **Límites:** comisión de 1% a 80%.
- **¿Sirve a Corte?** No. **Valor:** ninguno.
- **Fuente:** https://partner.tiktokshop.com/docv2/page/edit-open-collaboration-settings-202405 · spec `editOpenCollaborationSettings`.

#### A3. Get Open Collaboration Sample Rules
- **Método y path:** `GET /affiliate_seller/202410/open_collaborations/sample_rules`
- **Scope:** `seller.affiliate_collaboration.read`
- **Quién:** token de vendedor con shop_cipher.
- **Parámetros:** query `product_ids` ([]string, obligatorio, de 1 a 200 por petición).
- **Respuesta:** `sample_rules[]` con `product_id`, `sample_quota`, `is_sample_time_unlimited`, `status` (NOT_STARTED, ONGOING…), `available_quantity`, `start_time`, `end_time` y `thresholds` {`minimum_follower_count`, `minimum_gmv` (30 días), `avg_ec_video_views` (30 días), `category_ids`, `predicted_fulfillment_rank`}.
- **Límites:** 200 productos por llamada.
- **¿Sirve a Corte?** No. Con R2 mostraría los umbrales que esa tienda pide para dar muestras.
- **Valor:** bajo (explicaría rechazos de muestras de una sola tienda).
- **Fuente:** https://partner.tiktokshop.com/docv2/page/get-open-collaboration-sample-rules-202410 · spec `getOpenCollaborationSampleRules`.

#### A4. Edit Open Collaboration Sample Rule
- **Método y path:** `POST /affiliate_seller/202410/open_collaborations/sample_rules`
- **Scope:** `seller.affiliate_collaboration.write`
- **Quién:** token de vendedor con shop_cipher.
- **Parámetros (body):**
  - `product_id` (obligatorio). Solo cabe una regla por producto y gana la última llamada.
  - `sample_rule` {`sample_quota`, `is_sample_time_unlimited`, `start_time` y `end_time` (van juntos), `thresholds` {…igual que A3…}, `activate_status` (obligatorio: ACTIVATE / DEACTIVATE)}.
  - `predicted_fulfillment_rank`: ALL, LOW, …
- **Respuesta:** `data: {}`.
- **¿Sirve a Corte?** No. **Valor:** ninguno.
- **Nota:** la guía local (2024) decía que las muestras gratis no se podían agregar a una colaboración abierta por API. Este endpoint (202410) ya permite manejar las reglas de muestras.
- **Fuente:** https://partner.tiktokshop.com/docv2/page/edit-open-collaboration-sample-rule-202410 · spec `editOpenCollaborationSampleRule` · `research/tiktok-docs/affiliate-integration.txt`.

#### A5. Create Open Collaboration
- **Método y path:** `POST /affiliate_seller/202412/open_collaborations`
- **Scope:** `seller.affiliate_collaboration.write`
- **Quién:** token de vendedor con shop_cipher.
- **Parámetros (body):** `product_id` (obligatorio, un producto por petición) y `commission_rate` (obligatorio, 100–8000).
- **Respuesta:** `open_collaboration` {`id`, `product_id`, `effective_time`}.
- **Errores:** 16003012 (ya existe), 16003025 (cuenta desactivada), 16003033 (comisión fuera de 1–80%), 16003035 (producto restringido), 16603010 (vendedor restringido).
- **¿Sirve a Corte?** No. **Valor:** ninguno.
- **Fuente:** https://partner.tiktokshop.com/docv2/page/create-open-collaboration-202412 · spec `createOpenCollaboration`.

#### A6. Search Open Collaborations
- **Método y path:** `POST /affiliate_seller/202412/open_collaborations/search`
- **Scope:** `seller.affiliate_collaboration.read`
- **Quién:** token de vendedor con shop_cipher.
- **Parámetros:**
  - Query: `page_size` (obligatorio, 1–100), `page_token`, `sort_order` (por defecto DESC), `sort_field` (p. ej. `product_original_price`; por defecto, fecha de creación descendente).
  - Body: `keyword_type` + `keyword` (por ID o nombre de producto; la doc da `PRODUCT_ID` como ejemplo; no verifiqué la lista completa de valores) y `top_level_category_id`.
- **Respuesta:**
  - `open_collaborations[]` con `id`, `status` (NORMAL…), `current_commission` {`rate`, `start_time`, `end_time`}, `showcase_creator_count`, `content_creator_count` y `product` {`id`, `title`, `main_image_url`, `status`, `inventory`, `original_price`}.
  - `next_page_token` y `total_count`.
- **Límites:** 100 por página. En las páginas siguientes hay que repetir los mismos filtros.
- **¿Sirve a Corte?** No. **Valor:** ninguno.
- **Fuente:** https://partner.tiktokshop.com/docv2/page/search-open-collaborations-202412 · spec `searchOpenCollaborations`.

#### A7. Remove Open Collaboration
- **Método y path:** `DELETE /affiliate_seller/202409/open_collaborations/products/{product_id}`
- **Scope:** `seller.affiliate_collaboration.write`
- **Quién:** token de vendedor con shop_cipher.
- **Parámetros:** path `product_id` (obligatorio).
- **Respuesta:** `terminated_effective_time` (la baja no es inmediata).
- **Límites:** solo procede con `status == NORMAL`. Errores: 16003025.
- **Nota:** la doc remite a «POST /affiliate_seller/202409/open_collaborations/search», pero el endpoint de búsqueda publicado es la versión **202412** (A6). Es una inconsistencia de la doc oficial.
- **¿Sirve a Corte?** No. **Valor:** ninguno.
- **Fuente:** https://partner.tiktokshop.com/docv2/page/remove-open-collaboration-202409 · spec `removeOpenCollaboration`.

#### A8. Get Open Collaboration Creator Content Details
- **Método y path:** `GET /affiliate_seller/202508/open_collaborations/creator_content_details`
- **Scope:** `seller.affiliate_collaboration.read`
- **Quién:** token de vendedor con shop_cipher.
- **Parámetros (query):** `product_id` (obligatorio), `page_size` (obligatorio, 1–100), `page_token`.
- **Respuesta:**
  - `creator_content_details[]` con `creator_profile` {`username`, `nickname`, `follower_count`, `avatar.url`, `creator_open_id`}, `video_count`, `live_count`, `promotion_status` (NORMAL…) y `promotion_end_time`.
  - `product` {`id`, `image_url`}, `next_page_token` y `total_count`.
- **¿Sirve a Corte?** No. Con R2 vería sus conteos de videos y LIVE para el producto de esa tienda.
- **Valor:** bajo (Corte ya los deduce de sus órdenes y muestras).
- **Fuente:** https://partner.tiktokshop.com/docv2/page/get-open-collaboration-creator-content-details-202508 · spec `getOpenCollaborationCreatorContentDetails`.

#### A9. Seller Search Open Collaboration Products
- **Método y path:** `POST /affiliate_seller/202405/open_collaborations/products/search`
- **Scope:** `seller.affiliate_collaboration.read`
- **Quién:** token de vendedor con shop_cipher.
- **Parámetros:**
  - Query: `page_size` (obligatorio, 1–20), `page_token`, `sort_order` (por defecto ASC), `sort_field` (`commission_rate` por defecto, `product_sales_price`, `commission`, `units_sold`; la lista viene de la spec).
  - Body: `title_keywords[]`, `sales_price_range` {`amount_ge`, `amount_lt`}, `category.id` (solo primer nivel), `commission_rate_range` {`rate_ge`, `rate_lt`}.
- **Respuesta:**
  - `products[]` con `shop.name`, `id`, `has_inventory`, `units_sold`, `title`, `sale_region`, `main_image_url`, `detail_link`, `original_price` y `sales_price` {currency, minimum_amount, maximum_amount}, `category_chains[]` y `commission` {`rate`, `currency`, `amount`}.
  - `next_page_token` y `total_count`.
- **Límites:** 20 por página. Solo devuelve productos de las regiones donde la tienda vende.
- **¿Sirve a Corte?** Sí con R1, pero es **redundante**: Corte ya tiene el equivalente de creador (`/affiliate_creator/202405/open_collaborations/products/search` y `/affiliate_creator/202509/open_collaborations/products`).
- **Valor:** bajo.
- **Fuente:** https://partner.tiktokshop.com/docv2/page/seller-search-open-collaboration-products-202405 · spec `sellerSearchOpenCollaborationProducts` · ejemplo en `research/tiktok-docs/affiliate-integration.txt`.

#### A10. Remove Creator From Open Collaboration Product
- **Método y path:** `POST /affiliate_seller/202508/open_collaborations/{open_collaboration_id}/remove_creator`
- **Scope:** `seller.affiliate_collaboration.write`
- **Quién:** token de vendedor con shop_cipher.
- **Parámetros:** path `open_collaboration_id`. Body: `creator_user_open_id` (obligatorio) y `product_id` (obligatorio).
- **Respuesta:** `data: {}`.
- **Límites:** el creador puede volver a unirse; la tienda tendría que repetir la llamada.
- **¿Sirve a Corte?** No. **Valor:** ninguno.
- **Fuente:** https://partner.tiktokshop.com/docv2/page/remove-creator-from-open-collaboration-product-202508 · spec `removeCreatorFromOpenCollaborationProduct`.

### B. Colaboraciones dirigidas (target collaborations)

#### B1. Create Target Collaboration
- **Método y path:** `POST /affiliate_seller/202508/target_collaborations`
- **Scope:** `seller.affiliate_collaboration.write`
- **Quién:** token de vendedor con shop_cipher.
- **Parámetros (body):**
  - Obligatorios: `name`, `end_time` (string, Unix), `products[]` (máx. 100) {`id`, `target_commission_rate` (obligatorio), `shop_ads_commission_rate`}, `creator_user_open_ids[]` (máx. 50) y `seller_contact_info` {`email`, `phone_number`, `whatsapp`, `telegram`, `line`}.
  - También obligatorio: `free_sample_rule` {`has_free_sample` (obligatorio), `is_sample_approval_exempt` (obligatorio), `use_product_sample_setting`}.
  - Opcionales: `message`, `preferred_content_type` (obsoleto), `sample_fulfillment_content_type` (NO_PREFERENCE / SHOPPABLE_LIVE).
- **Respuesta:** `target_collaboration.id`, `target_collaboration_conflicts[]` {`creator_user_open_id`, `product_id`}, `invalid_open_id_list`, `invalid_product_id_list`, `create_time`.
- **Errores:**
  - 16024004 (no se pueden mezclar cuentas de prueba y reales) y 16024006 (no puede invitar a su creador oficial).
  - 16024008 (producto ajeno), 16024016 (creador ya ligado a una tienda) y 16024019 (cupo insuficiente).
  - 16024020, 16024021 (creador excede el límite de seguidores) y 16024022 (par en conflicto).
  - 50001702 (creador o producto no disponible), 50001703 (palabras sensibles), 98001004 y 36009003.
- **¿Sirve a Corte?** No. **Valor:** ninguno.
- **Fuente:** https://partner.tiktokshop.com/docv2/page/create-target-collaboration-202508 · spec `createTargetCollaboration`.

#### B2. Search Target Collaborations
- **Método y path:** `POST /affiliate_seller/202508/target_collaborations/search`
- **Scope:** `seller.affiliate_collaboration.read`
- **Quién:** token de vendedor con shop_cipher.
- **Parámetros:**
  - Query: `page_size` (20, 50 o 100), `page_token`.
  - Body: `collaboration_status` (obligatorio: ONGOING = quedan más de 7 días, EXPIRING = quedan menos de 7 días, VALID, CANCELING, COMPLETED), `creator_accept_status` (ACCEPT / ALL), `free_sample_setting` (WITH_FREE_SAMPLE / ALL), `search_param` {`keyword_type` (PRODUCT_ID, PRODUCT_NAME, …), `keyword`}, `creator_user_open_id`.
- **Respuesta:**
  - `total_count`, `next_page_token` y `target_collaborations[]`.
  - Cada colaboración trae `id`, `name`, `message`, `start_time`, `end_time`, `create_time` y `update_time`.
  - Además trae `creator_inivited_count` (sic), `showcase_creator_count`, `content_creator_count`, `product_count`, `free_sample_rule` y `type` (STANDARD…).
- **¿Sirve a Corte?** No. **Valor:** ninguno (Corte ya ve sus invitaciones con `/affiliate_creator/202405/target_collaborations/search`).
- **Fuente:** https://partner.tiktokshop.com/docv2/page/search-target-collaborations-202508 · spec `searchTargetCollaborations`.

#### B3. Update Target Collaboration
- **Método y path:** `PUT /affiliate_seller/202508/target_collaborations/{target_collaboration_id}`
- **Scope:** `seller.affiliate_collaboration.write`
- **Quién:** token de vendedor con shop_cipher.
- **Parámetros (body, todo obligatorio salvo lo marcado):** `name`, `end_time`, `products[]` {`id`, `commission_rate`, `target_ad_commission_rate` (opcional)}, `creator_user_open_ids[]` (máx. 50), `seller_contact_info` {`email` (obligatorio), …} y `free_sample_rule`.
- **Respuesta:** `target_collaboration_conflicts[]` y `update_failed` {`remove_creator_open_ids`, `remove_product_ids`, `add_creator_open_ids`, `add_products`, `change_commissions`, `end_time`, `seller_contact_info`, `name`, `invalid_product_id_list`, `invalid_open_id_list`}.
- **Límites:** solo colaboraciones STANDARD. Un éxito puede traer fallas parciales en `update_failed`.
- **Errores:** los de B1 más 16024018 (creador bloqueado), 36009007 (timeout) y 50001701 (colaboración vencida).
- **¿Sirve a Corte?** No. **Valor:** ninguno.
- **Fuente:** https://partner.tiktokshop.com/docv2/page/update-target-collaboration-202508 · spec `updateTargetCollaboration`. El path se confirmó en `python/src/tiktok_shop_api/generated/_meta.py`.

#### B4. Remove Target Collaboration
- **Método y path:** `DELETE /affiliate_seller/202409/target_collaborations/{target_collaboration_id}`
- **Scope:** `seller.affiliate_collaboration.write`
- **Quién:** token de vendedor con shop_cipher.
- **Respuesta:** `data: {}`.
- **Errores:** 600001001 (demasiadas llamadas) y 600001002 (falló el bloqueo).
- **¿Sirve a Corte?** No. **Valor:** ninguno.
- **Fuente:** https://partner.tiktokshop.com/docv2/page/remove-target-collaboration-202409 · spec `removeTargetCollaboration`.

#### B5. Query Target Collaboration Detail
- **Método y path:** `GET /affiliate_seller/202508/target_collaborations/{target_collaboration_id}`
- **Scope:** `seller.affiliate_collaboration.read`
- **Quién:** token de vendedor con shop_cipher.
- **Respuesta:** `target_collaboration` con:
  - Datos generales: `id`, `name`, `message`, `seller_contact_info`, `start_time`, `end_time`, `update_time`, `creator_invited_count`, `showcase_creator_count`, `content_creator_count`, `product_count`, `free_sample_rule`, `type` y `sample_fulfillment_content_type`.
  - `products[]`: `id`, `main_image_url`, `title`, `original_price`, `commission` {`rate`, `effective_time`, `currency`, `minimum_amount`, `maximum_amount`, `shop_ads_commission_rate`}, `status`, `commission_effective_status` y `collaboration_status`.
  - `creators[]`: `username`, `nickname`, `avatar.url`, `selection_region`, `showcase_product_count`, `content_product_count`, `collaboration_status`, `product_effective_status` y `creator_open_id`.
- **Errores:** 50001700 (la tienda no puede ver esa colaboración).
- **¿Sirve a Corte?** No. Con R2 mostraría el estado de Corte dentro de la invitación de esa tienda.
- **Valor:** bajo.
- **Fuente:** https://partner.tiktokshop.com/docv2/page/query-target-collaboration-detail-202508 · spec `queryTargetCollaborationDetail`.

#### B6. Generate Target Collaboration Link
- **Método y path:** `POST /affiliate_seller/202509/target_collaboration/{target_collaboration_id}/link` (en singular, así es el oficial)
- **Scope:** `seller.affiliate_collaboration.write`
- **Quién:** token de vendedor con shop_cipher.
- **Respuesta:** `link`: enlace que lleva al creador a revisar y aceptar la invitación.
- **¿Sirve a Corte?** No. **Valor:** ninguno.
- **Fuente:** https://partner.tiktokshop.com/docv2/page/generate-target-collaboration-link-202509 · spec `generateTargetCollaborationLink`.

#### B7. Check Target Collaboration Conflicts
- **Método y path:** `POST /affiliate_seller/202605/target_collaborations/conflicts/check`
- **Scope:** `seller.affiliate_collaboration.write`
- **Quién:** token de vendedor con shop_cipher.
- **Parámetros (body):** `creator_open_id_list[]` (obligatorio) y `product_id_list[]` (obligatorio).
- **Respuesta:** `has_conflict` y `conflict_items[]` {`creator_open_id`, `product_id`, `existing_collaboration_id`}.
- **¿Sirve a Corte?** No. **Valor:** ninguno.
- **Fuente:** https://partner.tiktokshop.com/docv2/page/check-target-collaboration-conflicts-202605 · spec `checkTargetCollaborationConflicts`.

#### B8. Resolve Target Collaboration Conflicts
- **Método y path:** `POST /affiliate_seller/202605/target_collaborations/conflicts/resolve`
- **Scope:** `seller.affiliate_collaboration.write`
- **Quién:** token de vendedor con shop_cipher.
- **Parámetros (body):** `conflict_items[]` (obligatorio) {`existing_collaboration_id`, `creator_open_id`}.
- **Respuesta:** `success_items[]` y `failed_items[]`.
- **¿Sirve a Corte?** No. **Valor:** ninguno.
- **Fuente:** https://partner.tiktokshop.com/docv2/page/resolve-target-collaboration-conflicts-202605 · spec `resolveTargetCollaborationConflicts`.

#### B9. Query Creator Promotion Details in Target Collaboration
- **Método y path:** `POST /affiliate_seller/202608/target_collaborations/creator_promotion_details/query`
- **Scope:** Read **y** Manage Seller Affiliate Collaboration (`seller.affiliate_collaboration.read` y `.write`)
- **Quién:** token de vendedor con shop_cipher.
- **Parámetros (body):** `creator_user_open_id` (obligatorio), `invitation_group_id` (obligatorio), `query`, `query_type` (PRODUCT_ID / PRODUCT_NAME), `invitation_id`, `product_filter.added_types[]` (ALL / ADDED / NOT_ADDED).
- **Respuesta:** `data.product_details[]` con:
  - `product_base_info`: `product_id`, `title`, `image.url`, `price` y `promotion_price` {min_price, max_price}, `target_commission`, `open_commission`, `target_ads_commission`, `old_target_commission`, `old_target_ads_commission`, `commission_effective_time` (ms), `ads_commission_effective_time` y `product_status`.
  - `product_add_status`, `video_count`, `live_count` e `is_commission_effective`.
- **¿Sirve a Corte?** No. Con R2 mostraría sus videos y LIVE por producto en la invitación de esa tienda.
- **Valor:** bajo.
- **Fuente:** https://partner.tiktokshop.com/docv2/page/query-creator-promotion-details-in-target-collaboration-202608 · spec `queryCreatorPromotionDetailsInTargetCollaboration`.

### C. Muestras del lado vendedor

#### C1. Search Sample Applications
- **Método y path:** `POST /affiliate_seller/202508/sample_applications/search`
- **Scope:** `seller.affiliate_collaboration.read`
- **Quién:** token de vendedor con shop_cipher.
- **Parámetros:**
  - Query: `page_size` (opcional, 1–50), `page_token`.
  - Body (todo opcional): `product_id`, `title` (búsqueda aproximada), `creator_user_oepn_id` (sic), `username` (búsqueda aproximada), `target_collabration_id` (sic), `order_id` y `status`.
  - Valores de `status`: PENDING, AWAITING_SHIPMENT, SHIPPED, CONTENT_PENDING, REJECT_CANCELLED, OVERDUE_CANCELLED, UNFULFILL_CANCELLED, DEL_OPEN_COLLAB, SELLER_NOT_SHIP_CANCELLED, WITHDRAW_CANCELLED, UNFULFILLABLE_CANCELLED, OPS_CANCELLED, OPS_FAILED, OPS_COMPLETED, COMPLETED.
- **Respuesta:**
  - `sample_applications[]`: `id`, `commission_rate` (decimal en texto), `status`, `order_id`, `available_quantity`, `approve_expiration_time`, `shipment_expiration_time`, `tracking_number`, `fulfillment_status` (PENDING, ONGOING, SUCCEED, FAILED, OVERDUE, SUSPEND, CANCELLED, EXEMPTED), `is_approvable`, `disapprovable_reasons[]` y `partner_name`.
  - `creator`: `creator_open_id`, `username`, `nickname`, `follower_count`, `avatar_url`, `gmv` (30 días), `content_count` (30 días), `fulfillment_percentage` (tasa de cumplimiento de muestras a 90 días; vacía si el creador no la autoriza) y `ec_video_view` (mediana a 30 días).
  - `product`: `id`, `title`, `sku_id`, `sku_image_url`, `sku_name`.
  - `next_page_token` y `total_count`.
- **Límites:** 50 por página.
- **¿Sirve a Corte?** No. Con R2 vería, solo para esa tienda, `shipment_expiration_time`, `approve_expiration_time`, `tracking_number` y su `fulfillment_percentage` a 90 días.
- **Valor:** bajo. La tasa de cumplimiento también sale en E3, que es más útil.
- **Fuente:** https://partner.tiktokshop.com/docv2/page/search-sample-applications-202508 · spec `searchSampleApplications` · modelo `search_sample_applications_request.py`.

#### C2. Review a Sample Application
- **Método y path:** `POST /affiliate_seller/202507/sample_applications/{application_id}/review`
- **Scope:** `seller.affiliate_collaboration.write`
- **Quién:** token de vendedor con shop_cipher.
- **Parámetros (body):** `review_result` (obligatorio: APPROVE / REJECT) y `reject_reason` (NOT_MATCH, OFFLINE, OUT_OF_STOCK, OTHER; obligatorio si REJECT).
- **Respuesta:** `data: {}`.
- **Límites:** solo procede con solicitudes en PENDING de colaboración abierta. Error 16022020: la tienda no puede revisar solicitudes de agencia.
- **¿Sirve a Corte?** No. **Valor:** ninguno.
- **Fuente:** https://partner.tiktokshop.com/docv2/page/review-a-sample-application-202507 · spec `reviewASampleApplication`.

#### C3. Search Sample Application Fulfillments
- **Método y path:** `POST /affiliate_seller/202409/sample_applications/{application_id}/fulfillments/search`
- **Scope:** `seller.affiliate_collaboration.read`
- **Quién:** token de vendedor con shop_cipher.
- **Parámetros:** path `application_id`. Body: `content_format` (LIVE / VIDEO).
- **Respuesta:** `fulfillments[]` con `product` {`id`, `main_image_url`} y `content` {`id`, `format`, `url`, `view_count`, `like_count`, `comment_count`, `paid_order_count`, `page_link`, `description`, `create_time`, `live_end_time`}.
- **¿Sirve a Corte?** No. Con R2 vería las vistas, likes y pedidos del video con que cumplió esa muestra.
- **Valor:** bajo. La versión de creador (`/affiliate_creator/202409/sample_applications/fulfillments/search`) ya la usa Corte. No verifiqué si la de creador trae `view_count`/`like_count`; eso toca a la familia de creador.
- **Fuente:** https://partner.tiktokshop.com/docv2/page/search-sample-application-fulfillments-202409 · spec `searchSampleApplicationFulfillments`.

#### C4. Seller Get Sample Request Deeplink
- **Método y path:** `GET /affiliate_seller/202512/sample_applications/deeplink`
- **Scope:** `seller.affiliate_collaboration.read`
- **Quién:** token de vendedor con shop_cipher.
- **Parámetros (query):**
  - `product_id` (obligatorio; sin campaña ni colaboración, debe estar en colaboración abierta activa) y `sku_id` (obligatorio).
  - `campaign_id` (si el producto está en una campaña TAP; tipos MY_CAMPAIGNS o SELLER_CAMPAIGNS).
  - `collaboration_id` (no se combina con `campaign_id`).
  - `valid_days` (de 1 a 14, 7 por defecto).
- **Respuesta:** `deeplink`: abre TikTok en la página para pedir la muestra. La tienda puede mandarlo como QR.
- **¿Sirve a Corte?** No. **Valor:** ninguno.
- **Fuente:** https://partner.tiktokshop.com/docv2/page/seller-get-sample-request-deeplink-202512 · spec `sellerGetSampleRequestDeeplink`.

### D. Mensajería tienda↔creador (las 10 APIs) y su webhook

Toda la mensajería es **bandeja de la TIENDA**. En la spec no hay ningún endpoint de conversaciones en `/affiliate_creator/`; los únicos `conversations` que existen son los de `/affiliate_seller/` y `/customer_service/` (vendedor↔comprador). Corte **no puede** leer ni mandar mensajes a las tiendas por API.

#### D1. Get Conversation List
- **Método y path:** `GET /affiliate_seller/202412/conversations`
- **Scope:** Manage Affiliate Messages (`seller.affiliate_messages.write`)
- **Quién:** token de vendedor con shop_cipher.
- **Parámetros (query):**
  - `page_size` (obligatorio, 1–50), `page_token`.
  - `only_need_conversation_id` (por defecto `true`, que devuelve solo el id).
  - `conversation_status` (ALL, UNREAD, UNREPLIED, STARRED, ARCHIVED). Un mensaje sigue «no leído» hasta llamar D7; contestar no lo marca como leído.
  - Docv2 también lista `only_need_conversation_id` en el body.
- **Respuesta:** `has_more`, `next_page_token` y `conversations[]` {`id`, `unread_count`, `username`, `avatar`, `creator_im_id`}.
- **¿Sirve a Corte?** No. **Valor:** ninguno.
- **Fuente:** https://partner.tiktokshop.com/docv2/page/get-conversation-list-202412 · spec `getConversationList`.

#### D2. Get Creator Conversation Messages
- **Método y path:** `GET /affiliate_seller/202412/conversation/{conversation_id}/messages` (`conversation` en singular)
- **Scope:** `seller.affiliate_messages.write`
- **Quién:** token de vendedor con shop_cipher.
- **Parámetros:** path `conversation_id` (debe ser de la tienda). Query: `page_size` (obligatorio, 1–20), `page_token`.
- **Respuesta:** `has_more`, `next_page_token` y `messages[]` {`conversation_index`, `message_body` {`id`, `conversation_id`, `type`, `content` (JSON en texto), `create_time`, `sender_id`}}.
- **Tipos de mensaje:** TEXT, PRODUCT_CARD, TARGET_COLLABORATION_CARD, FREE_SAMPLE_CARD, IMAGE, CRM_TEXT_WITH_IMAGE_CARD, CRM_TEXT_WITH_PRODUCTS_CARD, NOTIFICATION, EMOTICONS y SYSTEM.
- **Errores:** 16032001 (la región del creador y la de la tienda no coinciden).
- **¿Sirve a Corte?** No. **Valor:** ninguno.
- **Fuente:** https://partner.tiktokshop.com/docv2/page/get-creator-conversation-messages-202412 · spec `getCreatorConversationMessages`.

#### D3. Get Latest Unread Messages
- **Método y path:** `GET /affiliate_seller/202412/conversations/messages/list/newest`
- **Scope:** `seller.affiliate_messages.write`
- **Quién:** token de vendedor con shop_cipher.
- **Respuesta:** `newest_message_list[]` {`conversation_id`, `content`, `type`, `sender_id`, `unread_message_count`}.
- **Límites:** solo devuelve los no leídos del **último minuto**. TikTok recomienda usar el webhook 33.
- **¿Sirve a Corte?** No. **Valor:** ninguno.
- **Fuente:** https://partner.tiktokshop.com/docv2/page/get-latest-unread-messages-202412 · spec `getLatestUnreadMessages`.

#### D4. Get or Create Creator Conversation
- **Método y path:** `POST /affiliate_seller/202508/conversations`
- **Scope:** `seller.affiliate_messages.write`
- **Quién:** token de vendedor con shop_cipher.
- **Parámetros (body):** `creator_open_id` (obligatorio) y `only_need_conversation_id`.
- **Respuesta:** `conversation_id`, `is_new`, `username`, `avatar`, `unread_count`, `creator_im_id`.
- **Errores (límites reales de la tienda):**
  - 16030001 (creador dado de baja) y 16030002 (la tienda llegó a su cupo de IM).
  - 16030003 (la tienda no cumple el requisito de GMV de afiliados) y 16030007 (tienda inválida).
  - 16030009 (no usar cuentas de prueba), 16032001 (regiones distintas) y 45101021 (control de privacidad del usuario).
- **¿Sirve a Corte?** No. **Valor:** ninguno.
- **Fuente:** https://partner.tiktokshop.com/docv2/page/get-or-create-creator-conversation-202508 · spec `getOrCreateCreatorConversation`.

#### D5. Upload Message Image
- **Método y path:** `POST /affiliate_seller/202511/images/upload`
- **Scope:** `seller.affiliate_messages.write`
- **Quién:** token de vendedor. **Sin shop_cipher** (docv2 y spec); `scenario = 2`.
- **Parámetros:** multipart `data` (archivo, obligatorio): jpg, gif, webp o png, de hasta 10 MB, sin archivos vacíos.
- **Respuesta:** `url`, `width`, `height`. Se usan en el mensaje IMAGE de D6.
- **Errores:** 36009003, 45101001.
- **¿Sirve a Corte?** No. **Valor:** ninguno.
- **Fuente:** https://partner.tiktokshop.com/docv2/page/upload-message-image-202511 · spec `uploadMessageImage`.

#### D6. Send IM Message
- **Método y path:** `POST /affiliate_seller/202412/conversations/{conversation_id}/messages`
- **Scope:** `seller.affiliate_messages.write`
- **Quién:** token de vendedor con shop_cipher.
- **Parámetros (body):** `msg_type` (obligatorio) y `content` (obligatorio, JSON en texto). Formatos de `content`:
  - TEXT: `{"content"}`, de hasta 2,000 caracteres.
  - PRODUCT_CARD: `{"product_id"}`.
  - TARGET_COLLABORATION_CARD: `{"target_collaboration_id"}`.
  - FREE_SAMPLE_CARD: `{"apply_id"}`.
  - IMAGE: `{"url","width","height"}`, con la URL obtenida en D5 o D10.
  - CRM_TEXT_WITH_PRODUCTS_CARD: `{"product_ids" (1–5),"title" (≤ 50),"content" (≤ 500)}`.
  - CRM_TEXT_WITH_IMAGE_CARD: `{"image_url","title" (≤ 50),"content" (≤ 500)}`.
- **Respuesta:** `message_id` (no siempre viene).
- **Errores y límites:** 16030100 (cupo de mensajes con ese creador), 16030101 (el nivel de la tienda no permite contactarlo), 16032001 (regiones distintas), 45101004 (10,000 peticiones por día) y 36009003.
- **¿Sirve a Corte?** No. **Valor:** ninguno.
- **Fuente:** https://partner.tiktokshop.com/docv2/page/send-im-message-202412 · spec `sendIMMessage` · modelo `send_im_message_request.py`.

#### D7. Mark Conversations as Read
- **Método y path:** `POST /affiliate_seller/202412/conversatons/read` (la errata `conversatons` es oficial)
- **Scope:** `seller.affiliate_messages.write`
- **Quién:** token de vendedor con shop_cipher.
- **Parámetros (body):** `conversation_ids[]` (obligatorio, hasta 20).
- **Respuesta:** `failed_conversation_ids[]` (hay que reintentar solo esos).
- **¿Sirve a Corte?** No. **Valor:** ninguno.
- **Fuente:** https://partner.tiktokshop.com/docv2/page/mark-conversations-as-read-202412 · spec `markConversationsAsRead`.

#### D8. Get Inbox Category Counts
- **Método y path:** `GET /affiliate_seller/202608/conversations/group_counts`
- **Scope:** `seller.affiliate_messages.write`
- **Quién:** token de vendedor con shop_cipher.
- **Respuesta:** `data.group_counts[]` {`group_type` (UNREAD, UNREPLIED, STARRED, ARCHIVED), `count`}.
- **¿Sirve a Corte?** No. **Valor:** ninguno.
- **Fuente:** https://partner.tiktokshop.com/docv2/page/get-inbox-category-counts-202608 · spec `getInboxCategoryCounts`.

#### D9. Update Conversation Status
- **Método y path:** `POST /affiliate_seller/202608/conversations/{conversation_id}/status`
- **Scope:** `seller.affiliate_messages.write`
- **Quién:** token de vendedor con shop_cipher.
- **Parámetros (body):** `action` (obligatorio: STARRED, UNSTARRED, ARCHIVED).
- **Respuesta:** `data: {}`.
- **¿Sirve a Corte?** No. **Valor:** ninguno.
- **Fuente:** https://partner.tiktokshop.com/docv2/page/update-conversation-status-202608 · spec `updateConversationStatus`.

#### D10. Upload Message Image V2
- **Método y path:** `POST /affiliate_seller/202608/media/upload`
- **Scope:** `seller.affiliate_messages.write`
- **Quién:** token de vendedor **con** shop_cipher (a diferencia de D5).
- **Parámetros:** multipart `data` (jpg, gif, webp o png, de hasta 10 MB).
- **Respuesta:** `url`, `width`, `height`.
- **¿Sirve a Corte?** No. **Valor:** ninguno.
- **Fuente:** https://partner.tiktokshop.com/docv2/page/upload-message-image-v2-202608 · spec `uploadMessageImageV2`.

#### W1. Webhook (33) New message listener
- **Tipo:** evento push, `type = 33`. **Disparador:** «When a creator sends a message to the seller».
- **Carga:** `type`, `shop_id`, `tts_notification_id`, `timestamp` y `data` {`index`, `message_id`, `conversation_id`, `msg_type` (TEXT, PRODUCT_CARD, TARGET_COLLABORATION_CARD, FREE_SAMPLE_CARD), `content`, `create_time`, `sender.sender_im_user_id`}.
- **Quién lo recibe:** la app autorizada por la **tienda** (trae `shop_id`). La página no indica el scope (no verificado).
- **¿Sirve a Corte?** No. Además, un webhook necesita una URL pública, y el hub de Corte vive en una PC de su red local.
- **Valor:** ninguno.
- **Fuente:** docv2, sección Webhooks, «(33) New message listener» (documento `6790b76eb59cf9030997b783`) · spec `NewMessageListenerWebhook` (tipo 33).

#### W2. Webhook (56) Sample Application Status Change
- **Tipo:** evento push, `type = 56`. **Disparador:** cambia el estado de una solicitud de muestra del creador.
- **Carga:** `type`, `tts_notification_id`, `shop_id`, `timestamp` y `data` {`application_id`, `new_status` (los 15 estados de C1), `creator[]` {`creator_open_id`}, `product[]` {`id`, `sku_id`}}.
- **Quién lo recibe:** por el `shop_id`, lo **infiero** del lado tienda; la doc no lo dice explícitamente. Scope no indicado (no verificado).
- **¿Sirve a Corte?** No. Con R2 avisaría de los cambios de estado en esa tienda.
- **Valor:** bajo (Corte ya puede consultar estados con la API de creador y no tiene URL pública).
- **Fuente:** docv2, sección Webhooks, «(56) Sample Application Status Change» (documento `6939a1e66ae5d8050a4bd0c4`) · spec `SampleApplicationStatusChangeWebhook` (tipo 56).

### E. Marketplace de creadores (búsqueda y detalle con métricas)

#### E1. Search Creators in Creator Marketplace
- **Método y path:** `POST /affiliate_seller/202608/marketplace_creators/search` (versiones 202608 y 202508; esta última se llamaba «Seller Search Creator on Marketplace»)
- **Scope:** Read Creator Marketplace (`seller.creator_marketplace.read`)
- **Quién:** token de vendedor con shop_cipher.
- **Parámetros:**
  - Query: `page_size` (obligatorio, **12 o 20**), `page_token`.
  - Body (todo opcional): `search_key` (se reenvía para tener resultados estables) y `keyword` (username o nickname).
  - `follower_demographics` {`age_ranges[]` (AGE_RANGE_18_24, …), `count_range` {`count_ge`, `count_le`}, `gender_distribution` {`gender`, `percentage_ge` (×10,000)}}.
  - `gmv_ranges[]` (GMV_RANGE_0_100, _100_1000, _1000_10000, _10000_AND_ABOVE), `units_sold_ranges[]` y `category[]` {`parent_category_id`, `child_category_id_list`}.
  - `content_performance` {`avg_video_views`, `avg_shoppable_video_views`, `avg_engagement_rate`, `avg_shopable_engagement_rate`, `avg_live_avg_viewers_ge`, `avg_shoppable_live_avg_viewers_ge`}.
  - `affiliate_data` {`avg_commission_rate`, `post_rate` (ALL / OK / GOOD / BETTER), `creator_agency_staus` (sic: AGENCY_MANAGED / INDEPENDENT), `is_fast_growing`, `not_invited_l90_days`}.
  - `advanced_filters` {`content_preference_type[]`, `eligible_flat_fee` (solo US), `option_list[]`, `sorter_algorithm_id`} y `data_groups[]`.
- **Respuesta:**
  - `next_page_token`, `search_key` y `creators[]`.
  - Cada creador trae `username`, `nickname`, `avatar.url`, `selection_region`, `category_ids`, `avg_ec_live_uv`, `avg_ec_video_view_count`, `follower_count` y `creator_open_id`.
  - Ventas: `gmv`, `live_gmv` y `video_gmv` (solo si el creador autoriza datos precisos), `gmv_range` (solo US) y `units_sold_range`.
  - `top_follower_demographics` {`age_ranges` (top 3), `major_gender`}.
  - `creator_profile` {`is_official_recommend`, `creator_bind_mcn_name`, `is_fast_growing`, `has_collaborated`, `user_type_tag[]` (1 = privacidad, 2 = carve-out), `has_invited_90d`, `is_creator_blocked`, `pps_score`, `is_eligible_flat_fee`, `is_rising_star`, `creator_level`}.
- **Límites:** datos de los **últimos 30 días**. 10,000 peticiones por día (error 45101004). 12 o 20 por página.
- **¿Sirve a Corte?** Sí con R1.
- **Valor:** **medio**. Permite comparar a Corte con otros creadores de moda masculina en MX (GMV, seguidores, vistas promedio, nivel) y ver su propia ficha de marketplace buscando su username en `keyword`.
- **Fuente:** https://partner.tiktokshop.com/docv2/page/search-creators-in-creator-marketplace-202608 · spec `searchCreatorsInCreatorMarketplace` · changelog «Marketplace Creator API add an optional parameter».

#### E2. Get Creator Marketplace Advanced Search Filters
- **Método y path:** `POST /affiliate_seller/202608/marketplace_creators/search/filter` (versiones 202608 y 202601)
- **Scope:** `seller.creator_marketplace.read`
- **Quién:** token de vendedor con shop_cipher.
- **Parámetros (body):** `options[]` {`option_type`}. Valores vistos: OPTION_VERTICAL_PRO, OPTION_LANGUAGE y OPTION_SORTER; no verifiqué la lista completa. Si `options` va vacío, devuelve listas vacías.
- **Respuesta:** `data.option_list[]` {`option_type`, `options[]` {`id`, `name`, `option_children[]`}} y `data.sorters[]` {`algorithm_id`, `name`}.
- **Límites:** los filtros cambian por país, así que hay que pedirlos en tiempo de ejecución.
- **¿Sirve a Corte?** Sí con R1 (solo como apoyo de E1).
- **Valor:** bajo.
- **Fuente:** https://partner.tiktokshop.com/docv2/page/get-creator-marketplace-advanced-search-filters-202608 · spec `getCreatorMarketplaceAdvancedSearchFilters`.

#### E3. ⭐ Get Marketplace Creator Performance
- **Método y path:** `GET /affiliate_seller/202608/marketplace_creators/{creator_user_id}` (versiones 202608 y 202508)
- **Scope:** `seller.creator_marketplace.read`
- **Quién:** token de vendedor con shop_cipher.
- **Parámetros:**
  - Path: `creator_user_id` = **Creator Open ID**.
  - Query: `data_groups` (CSV; si se omite, trae los 5 grupos).
  - Grupos: BASIC_CREATOR_INFORMATION, CONTENT_PERFORMANCE, FOLLOWER_INFORMATION, COLLABORATION, SALES_AND_GMV.
- **Respuesta (`data.creator`):**
  - Perfil: `username`, `nickname`, `avatar`, `selection_region`, `bio_description`, `follower_count`, `profile_tt_uri`.
  - Categorías y marcas: `category_ids`, `top_collaborated_brand_ids` (top 10), `brand_collaboration_count`.
  - Ventas: `units_sold`, `units_sold_range`, `gmv`, `video_gmv`, `live_gmv`, `gmv_range` (solo US), `category_gmv_distribution[]`, `content_gmv_distribution[]` (VIDEO / LIVE / SHOWCASE), `product_original_price_range` (30 días).
  - GPM: `gpm`, `video_gpm`, `live_gpm` y sus rangos.
  - Contenido a 30 días: `promoted_product_num`, `ec_live_count`, `ec_video_count`.
  - Promedios: `avg_ec_video_play_count`, likes, comentarios y compartidos, `ec_video_engagement_rate`, `ec_live_engagement_rate`.
  - Comisión: `avg_commission_rate` y su rango. Solo US: `avg_gmv_per_buyer`.
  - Seguidores: `follower_location[]`, `follower_age[]`, `follower_gender[]`.
  - Reputación: **`pps`** (Promotion Performance Score, 90 días), **`rating`** (calificación de vendedores que trabajaron con el creador) y **`post_rate`** (probabilidad de publicar tras recibir muestra).
  - `creator_profile`:
    - **`creator_level`**, **`creator_fulfillment_score_90d`**, **`creator_fulfillment_reviews`** (reseñas de cumplimiento de vendedores, 90 días) y **`sample_score`** (puntuación de crédito sobre 100).
    - Medianas a 30 días de LIVE y video, `contact_info_available` e `is_rising_star`.
    - `creator_connect_info` {`is_paired`, `is_connect`, `is_blocked`} y **`creator_trend_profile[]`** (GMV, unidades, seguidores y engagement por periodo).
- **Límites y condiciones:**
  - 10,000 peticiones por día (45101004) y 36009002 (demasiadas peticiones).
  - GMV y unidades exactos solo si el creador autoriza datos precisos.
  - `creator_profile` puede venir vacío según la cuenta o la región de quien llama.
  - 16901006: la región de selección del creador debe coincidir con la de la tienda.
- **¿Sirve con la cuenta de creador de Corte?** **Sí con requisito:**
  1. R1: token de una tienda **MX** (región igual a la de Corte).
  2. Su propio Creator Open ID, que sale de Get Creator Profile 202508 con su token de creador y la **misma app**: el Open ID es único por app.
  3. Riesgos documentados, no probados: 16901007 («The seller could not obtain an official creator profile due to insufficient permissions») puede aplicar si la tienda es suya y su cuenta es la «oficial» de la tienda. 16032012 («only affiliate partner cipher can access this api») no está explicado en la doc.
- **Valor para Corte:** **alto**. Es la única forma documentada de ver **cómo lo ven las tiendas**: PPS, calificación de vendedores, tasa de publicación tras muestra, puntuación de muestras y de cumplimiento a 90 días, reseñas de cumplimiento, nivel de creador, demografía de seguidores, GMV/GPM por tipo de contenido y tendencia. Encaja con su meta de quedar bien con las tiendas y medir el efecto de ponerse al corriente con las muestras pendientes.
- **Fuente:** https://partner.tiktokshop.com/docv2/page/get-marketplace-creator-performance-202608 · spec `getMarketplaceCreatorPerformance` · docv2 «Creator Open ID for Affiliate APIs» (`3obfokj6`) · `research/tiktok-docs/get-creator-profile-202508.txt`.

### F. Alcance a creadores (cupos de outreach)

#### F1. Get Weekly Creator Outreach Quota
- **Método y path:** `GET /affiliate_seller/202607/creator_outreach/quota`
- **Scope:** `seller.affiliate_collaboration.read`
- **Quién:** token de vendedor con shop_cipher.
- **Respuesta (`data`):**
  - Cupo: `shop_id`, `quota_type`, `gmv_tier`, `quota_sum`, `quota_use`, `unlimited`, `reached_max_follower_cnt`, `new_connect_count`, `pair_connect_count`, `start_time`, `end_time`.
  - Reglas: `gmv_level_rule[]` y `quota_details[]` {`creator_levels[]`, `quota_period_sum`/`use`, `quota_bonus_sum`/`use`}.
  - `bonus_exposure_post_percentile_threshold`.
- **¿Sirve a Corte?** No. **Valor:** ninguno.
- **Fuente:** https://partner.tiktokshop.com/docv2/page/get-weekly-creator-outreach-quota-202607 · spec `getWeeklyCreatorOutreachQuota`.

#### F2. Get Weekly Creator Outreach Records
- **Método y path:** `POST /affiliate_seller/202608/creator_outreach/records/query`
- **Scope:** `seller.affiliate_collaboration.read` y `.write`
- **Quién:** token de vendedor con shop_cipher.
- **Parámetros (body):** `page_index` (obligatorio, mayor que 0) y `page_size` (obligatorio, mayor que 1 y de hasta 50).
- **Respuesta:** `data.total` y `data.connect_list[]` {`id`, `creator_open_id`, `has_sent_im_message`, `has_sent_invitation`, `is_paired`}.
- **¿Sirve a Corte?** No. **Valor:** ninguno.
- **Fuente:** https://partner.tiktokshop.com/docv2/page/get-weekly-creator-outreach-records-202608 · spec `getWeeklyCreatorOutreachRecords`.

#### F3. Check Creator Outreach Eligibility
- **Método y path:** `POST /affiliate_seller/202610/creator_outreach/eligibility/check`
- **Scope:** `seller.affiliate_collaboration.read`
- **Quién:** token de vendedor con shop_cipher.
- **Parámetros (body):** `creator_infos[]` (obligatorio, de 1 a 100 Open IDs únicos) {`creator_open_id`}.
- **Respuesta:** `creator_eligibility_results[]` {`creator_level`, `creator_open_id`, `is_blocked`, `is_connected`, `is_creator_follower_count_threshold_met`, `is_creator_level_quota_available`, `is_paired`}, `ineligible_creator_levels[]` e `is_batch_quota_consumable`.
- **Límites:** **disponibilidad en MX no verificada** (docv2 no tiene `api_basic_id` para este endpoint).
- **¿Sirve a Corte?** Sí con R1, pero solo aporta su `creator_level`, que E3 ya da.
- **Valor:** bajo.
- **Fuente:** https://partner.tiktokshop.com/docv2/page/check-creator-outreach-eligibility-202610 · spec `checkCreatorOutreachEligibility`.

### G. Pedidos de afiliado de la tienda y reportes Compass

#### G1. Search Seller Affiliate Orders
- **Método y path:** `POST /affiliate_seller/202410/orders/search`
- **Scope:** `seller.affiliate_collaboration.read`
- **Quién:** token de vendedor con shop_cipher.
- **Parámetros:**
  - Query: `page_size` (obligatorio, 1–100, 20 por defecto), `page_token`.
  - Body: `create_time_ge`, `create_time_lt` (**máximo 3 meses por petición**; sin fechas devuelve los últimos 3 meses) y `program_id` (campaña de agencia).
- **Respuesta:**
  - `orders[]`: `id`, `delivery_time`, `create_time`, `status` (obsoleto) y `skus[]`.
  - Cada SKU: `sku_id`, `settlement_status` (Unknown, AWAITING PAYMENT, To-SETTLE, SETTLED, INELIGIBLE), `open_collaboration_id`, `target_collaboration_id`, `campaign_id`, `creator_username`, `price`, `quantity`, `content_type` (SHOP, VIDEO, LIVE, PRE_LIVE, PROMOTION_PAGE, LINKSHARE), `content_id` y `product_id`.
  - Comisiones: `commission_model`, `commission_tier_setting`, `commission_rate`, `partner_commission_rate`, `shop_ads_commission_rate`, `estimated_*` y `actual_*` (base, comisión, comisión de partner y de Shop Ads) y `estimated/actual_cofunded_creator_bonus_amount`.
  - Otros: `fully_return`, `is_carousel`, `sku_name`, `seller_sku`, `next_page_token` y `total_count` (cuenta líneas SKU).
- **¿Sirve a Corte?** No. Con R2 vería sus pedidos solo en esa tienda.
- **Valor:** bajo. Corte ya tiene sus órdenes con `/affiliate_creator/202410/orders/search`. Lo nuevo serían `seller_sku`, `commission_model` y el bono co-financiado, solo de esa tienda.
- **Fuente:** https://partner.tiktokshop.com/docv2/page/search-seller-affiliate-orders-202410 · spec `searchSellerAffiliateOrders` · modelo `search_seller_affiliate_orders_request.py`.

#### G2. Create Compass Offline Export Task
- **Método y path:** `POST /affiliate_seller/202603/compass/offline_task`
- **Scope:** `seller.affiliate_collaboration.read`
- **Quién:** token de vendedor con shop_cipher.
- **Parámetros (body):** `module_type` (CREATOR / BASE), `window_type` (PAST_24H, PAST_7_DAYS, PAST_30_DAYS), `end_day` (AAAAMMDD en hora local de la región; la doc incluye «mx: UTC-6») y `plan_type` (ALL, TARGET, OPEN, PARTNER).
- **Respuesta:** `task.id`.
- **¿Sirve a Corte?** No. **Valor:** ninguno. El formato del archivo exportado no está documentado (no verificado).
- **Fuente:** https://partner.tiktokshop.com/docv2/page/create-compass-offline-export-task-202603 · spec `createCompassOfflineExportTask`.

#### G3. Get Compass Task List
- **Método y path:** `GET /affiliate_seller/202603/compass/offline_tasks`
- **Scope:** `seller.affiliate_collaboration.read`
- **Quién:** token de vendedor con shop_cipher.
- **Parámetros (query):** `doc_type` (obligatorio: CREATOR / BASE).
- **Respuesta:** `tasks[]` {`module_type`, `id`, `file_name`, `status` (RUNNING, SUCCEEDED, FAILED)}.
- **Límites:** solo tareas de los **últimos 7 días**. La doc dice que pagina, pero no lista parámetros de paginación.
- **¿Sirve a Corte?** No. **Valor:** ninguno.
- **Fuente:** https://partner.tiktokshop.com/docv2/page/get-compass-task-list-202603 · spec `getCompassTaskList`.

#### G4. Download Compass Task File
- **Método y path:** `GET /affiliate_seller/202603/compass/offline_tasks/{task_id}/file`
- **Scope:** `seller.affiliate_collaboration.read`
- **Quién:** token de vendedor con shop_cipher (valida que la tarea sea de la tienda).
- **Respuesta:** `file.base64`.
- **¿Sirve a Corte?** No. **Valor:** ninguno.
- **Fuente:** https://partner.tiktokshop.com/docv2/page/download-compass-task-file-202603 · spec `downloadCompassTaskFile`.

### H. Campañas de partner vistas desde la tienda

Disponibilidad en MX no verificada para H1–H5: son de la versión 202611 y docv2 aún no tiene `api_basic_id` para ellos.

#### H1. Search Seller Partner Campaigns
- **Método y path:** `GET /affiliate_seller/202611/partner_campaigns`
- **Scope:** `seller.affiliate_collaboration.read`
- **Quién:** token de vendedor con shop_cipher.
- **Parámetros (query):**
  - `page_size` (obligatorio, 1–100), `page_token`.
  - `key_word` y `search_type` (CAMPAIGN_NAME, CAMPAIGN_ID, AGENCY_NAME).
  - `campaign_join_status_category` (JOINED, NOT_JOINED, CLOSED, UNSPECIFIED).
  - `campaign_online_status` y `campaign_types[]` (AGENCY_INITIATED, SELLER_INITIATED, OPS_CAMPAIGN).
- **Respuesta:**
  - `campaign_details[]`: `affiliate_partner_id`, `affiliate_partner_name`, `campaign_id`, `campaign_name`, `campaign_statistics`, `commission_rate`, `description`, `start_time` y `end_time` (ms en texto), `is_target_campaign`, `registration_*_time`, `seller_campaign_extra`, `status` y `type`.
  - `campaign_join_status_counts[]`, `next_page_token` y `total_num`.
- **Límites:** solo se pueden leer páginas completas dentro de los primeros 10,000 registros.
- **¿Sirve a Corte?** No. **Valor:** ninguno.
- **Fuente:** https://partner.tiktokshop.com/docv2/page/search-seller-partner-campaigns-202611 · spec `searchSellerPartnerCampaigns`.

#### H2. Get Seller Partner Campaign Detail
- **Método y path:** `GET /affiliate_seller/202611/partner_campaigns/{campaign_id}`
- **Scope:** `seller.affiliate_collaboration.read`
- **Quién:** token de vendedor con shop_cipher.
- **Respuesta:** `campaign_detail` con:
  - Estadísticas: `paid_gmv`, `settled_gmv`, `est_total_commissions`, `settled_total_commissions`, `paid_order_num`, `settled_order_num`, …
  - Registro: `can_register` (solo indica si la ventana está abierta), `is_registered`, `is_auto_register`.
  - Participantes: `invited_agency_details[]` y `seller_info`.
  - `version` (MVP / MULTI_CREATOR_CO…; no verifiqué la lista completa).
  - No devuelve datos de contacto.
- **¿Sirve a Corte?** No. **Valor:** ninguno.
- **Fuente:** https://partner.tiktokshop.com/docv2/page/get-seller-partner-campaign-detail-202611 · spec `getSellerPartnerCampaignDetail`.

#### H3. Get Seller Partner Campaign Candidate Products
- **Método y path:** `GET /affiliate_seller/202611/partner_campaigns/{campaign_id}/candidate_products`
- **Scope:** `seller.affiliate_collaboration.read`
- **Quién:** token de vendedor con shop_cipher.
- **Parámetros (query):** `page_size` (obligatorio: 20, 50 o 100), `page_token`, `key_word`, `category_id` y `product_search_key` (obligatorio: SEARCH_BY_PRODUCT_NAME / SEARCH_BY_PRODUCT_ID).
- **Respuesta:**
  - `product_detail[]`: `has_registered`, `image`, `is_under_governed`, `open_plan_commission_rate`, `open_plan_ads_commission_rate`, `price_range`, `product_id`, `product_name`, `product_stock` y `tier_commission_info`.
  - `next_page_token` y `total_num`.
- **¿Sirve a Corte?** No. **Valor:** ninguno.
- **Fuente:** https://partner.tiktokshop.com/docv2/page/get-seller-partner-campaign-candidate-products-202611 · spec `getSellerPartnerCampaignCandidateProducts`.

#### H4. Get Seller Partner Campaign Registered Products
- **Método y path:** `GET /affiliate_seller/202611/partner_campaigns/{campaign_id}/products`
- **Scope:** `seller.affiliate_collaboration.read`
- **Quién:** token de vendedor con shop_cipher.
- **Parámetros (query):** `page_size` (obligatorio: 10, 20, 50 o 100), `page_token`, `key_word`, `product_search_key` (obligatorio) y `product_status` (obligatorio: PENDING, ONGOING, REJECTED, CLOSED).
- **Respuesta:**
  - Conteos: `pending_num`, `ongoing_num`, `rejected_num`, `closed_num` y `total_num`.
  - `product_details[]`: `can_seller_re_register`, `product_statistics.sold_num`, `rejected_reason[]`, `sample_quota`, `shared_sample_quota`, `total_commission_rate`, `total_ads_commission_rate`, …
- **¿Sirve a Corte?** No. **Valor:** ninguno.
- **Fuente:** https://partner.tiktokshop.com/docv2/page/get-seller-partner-campaign-registered-products-202611 · spec `getSellerPartnerCampaignRegisteredProducts`.

#### H5. Register Seller Partner Campaign Products
- **Método y path:** `POST /affiliate_seller/202611/partner_campaigns/{campaign_id}/products`
- **Scope:** `seller.affiliate_collaboration.write`
- **Quién:** token de vendedor con shop_cipher.
- **Parámetros (body):**
  - Obligatorios: `campaign_contact_info[]` {`type` (EMAIL obligatorio; WHATSAPP opcional), `value`, `region_code`}, `product_ids[]` (de 1 a 200) y `total_commission_rate`.
  - Opcionales: `creator_commission_rate` + `partner_commission_rate` (modelo anterior), `product_ads_commission_rate` (mapa) y `sample_quota` (de 0 a 100,000,000).
- **Respuesta:** `data: {}`. No devuelve resultado por producto y no garantiza idempotencia.
- **¿Sirve a Corte?** No. **Valor:** ninguno.
- **Fuente:** https://partner.tiktokshop.com/docv2/page/register-seller-partner-campaign-products-202611 · spec `registerSellerPartnerCampaignProducts`.

### L. Endpoints de legado (solo en la guía local)

Estos tres aparecen en `research/tiktok-docs/affiliate-integration.txt` (guía de 2024, con ejemplos cURL). **No aparecen** en el árbol actual de docv2 ni en la spec OpenAPI (48 operaciones `affiliate_seller`). Las páginas actuales de B1 y A10 solo listan las versiones 202508.

- **L1. Generate Affiliate Product Promotion Link:** `POST /affiliate_seller/202405/products/{product_id}/promotion_link/generate`. Según la tabla de la guía, el scope es «Manage Seller Affiliate Collaboration». La respuesta del ejemplo es `product_promotion_link`. **No verificado como vigente:** no encontré ninguna versión actual en docv2. Valor para Corte: ninguno.
- **L2. Create Target Collaboration (202405):** `POST /affiliate_seller/202405/target_collaborations`. El body del ejemplo usaba `creator_user_ids`. Lo reemplaza B1 (202508, con Open IDs).
- **L3. Remove Creator Affiliate from Collaboration (202405):** `POST /affiliate_seller/202405/open_collaborations/{id}/remove_creator`. Lo reemplaza A10 (202508).
- «Seller Search Affiliate Open Collaboration Product», como la llama la guía, es el mismo path que A9 (vigente).

---

## Huecos y advertencias

1. **No hay mensajería del lado creador.** Corte no puede leer ni contestar a las tiendas por API. Para «quedar bien» con las 30 tiendas a las que les debe video, el contacto sigue siendo en la app de TikTok.
2. **Todo exige token de VENDEDOR (user_type = 0).** Con el token actual de creador no se puede llamar ningún endpoint de esta familia.
3. Lo único útil para Corte (E3, y en menor medida E1) requiere **R1**: una tienda MX que autorice la app. No hay modo de prueba documentado para MX.
4. **Disponibilidad en MX no verificada** para F3 y H1–H5: docv2 no expone las categorías habilitadas para esos 6 endpoints.
5. Errores no explicados en la doc de E3: 16032012 («only affiliate partner cipher can access this api») y 16901007 (perfil de creador oficial). No sé si impedirían que una tienda propia de Corte consulte su propio perfil.
6. Varios campos solo existen en **US**: `gmv_range`, `avg_gmv_per_buyer`, `eligible_flat_fee` e `is_eligible_flat_fee`. En MX esos campos no vendrán.
7. Los webhooks (W1, W2) necesitan una URL pública. El hub de Corte vive en su PC, así que no los podría recibir sin un servidor externo.
8. Los tres endpoints de legado (L1–L3) solo están en la guía local. L1 no tiene reemplazo visible en docv2.

## Fuentes consultadas

1. **Docs locales:** `research/tiktok-docs/affiliate-integration.txt`, `authorization-overview-202407.txt`, `access-scope.txt`, `affiliate-creator-api-overview.txt`, `get-creator-profile-202508.txt` y `research/CONTEXTO.md`.
2. **Spec OpenAPI** «TikTok Shop Partner API» versión 2026.11.13, generada desde docv2: https://github.com/isaackogan/TikTok-Shop-Api-SDKs/blob/main/.openapi/tiktok-shop.openapi.yaml.
   - La leí por el espejo https://cdn.jsdelivr.net/gh/isaackogan/TikTok-Shop-Api-SDKs@main/.openapi/tiktok-shop.openapi.yaml, porque `raw.githubusercontent.com` no resolvió DNS.
   - Métodos y paths confirmados en `python/src/tiktok_shop_api/generated/_meta.py`.
   - Modelos usados: `search_seller_affiliate_orders_request.py`, `search_sample_applications_request.py`, `send_im_message_request.py`, `mark_conversations_as_read_request.py`, `get_or_create_creator_conversation_request.py`, `new_message_listener_webhook*.py` y `sample_application_status_change_webhook*.py`. Todo se tomó como dato; no se ejecutó nada.
3. **docv2 oficial** (https://partner.tiktokshop.com/docv2/page/…): las 48 páginas de API listadas en las fichas, la página «Affiliate Seller API overview», los webhooks (33) y (56), «Creator Open ID for Affiliate APIs» (`3obfokj6`), el changelog «Marketplace Creator API add an optional parameter» y Get Authorized Shops 202309.
   - Las páginas se renderizaron en el navegador integrado y se leyeron sus metadatos oficiales: path, método, scope y `scope_key`, header de token, parámetros, respuesta, errores, versiones y categorías habilitadas para MX → MX.
4. developers.tiktok.com y business-api.tiktok.com: no se usaron, porque esta familia es exclusiva del Partner API de TikTok Shop. No cité blogs de terceros.
