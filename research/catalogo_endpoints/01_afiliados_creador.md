# 01 · Affiliate Creator API (`creator.*`): catálogo de endpoints para Corte

Investigado el 15/11/2026. Solo se revisó documentación: no se llamó a la API real ni se abrió `config.json`.

## Resumen de la familia

1. La familia `/affiliate_creator/*` tiene **26 endpoints verificados** en la spec OpenAPI generada de las docs oficiales del Partner API (`info.version 2026.11.13`). Todos se llaman con **token de creador** (`user_type=1`, header `x-tts-access-token`) y **sin `shop_cipher`**.
2. Por bloque: perfil (1), vitrina (4), colaboración abierta y dirigida (3), muestras (4), pedidos (2), share links (2), publicación de contenido (7: subir video/foto, revisión previa, publicar, estado y productos de tienda propia) y Tokopedia (2, solo aplican a Indonesia).
3. **Corte usa 11 de lectura. Con el token actual responden 10.** `POST /affiliate_creator/202505/orders/trace/search` pide el scope **«Read Affiliate Share Link» = `creator.affiliate.share_link.read`**. Es el único `creator.*` que le falta al token, y por eso Corte recibe hoy `105005`.
4. **Sin aprovechar todavía:** trace/search (filtra por fecha de **liquidación** o de pago y trae el estado `DEDUCTED`) y la escritura de vitrina (agregar, quitar y fijar; el token ya tiene `creator.showcase.write`). También el flujo de **publicar video comprable**: subir → revisión previa → publicar → estado.
5. **En esta familia no hay métricas de video ni de LIVE** (vistas, likes, GMV por LIVE). «Get Live Room Info», «Check Anchor Content» y «Check Anchor Prerequisites» aparecen en la tabla oficial de scopes, pero no tienen path en ninguna fuente, así que quedan **no verificados**.
6. ~~El scope «Content Posting» no tiene clave verificada; por eliminación podría ser `creator.affiliate.link.write`.~~ **[Corrección del revisor, 15/11/2026]** La clave **sí está verificada y es `creator.video.write`**, que la app **no** tiene aprobada (ni pedida). Fuente: JSON oficial que usa cada página docv2, `https://partner.tiktokshop.com/api/v1/document/api_meta?src_document_id=<slug>&aid=359713&locale=en`, campo `scope_list[].scope_key`, revisado en `post-shoppable-video-202603`, `upload-shoppable-video-file-202505`, `get-shop-products-202509`, `get-creator-profile-202508`, `add-showcase-products-202405` y `get-showcase-products-202405`. Además, la sección «View app categories» (`…/api/v1/document/apis/{api_basic_id}/callable_categories?registration_country=MX&target_market=MX`) de Upload Shoppable Video File (`7502362897129981697`) y Post Shoppable Video (`7502333053755541265`) **solo admite «Shoppable Content» y «TikTok Shop Seller»**, no «Creator collaborations». Conclusión: los 7 endpoints de publicación y Get Shop Products **no sirven hoy** con la app de Corte; harían falta el scope `creator.video.write` y una app de categoría «Shoppable Content» (si la app está registrada en MX). La clave `creator.affiliate.link.write` queda **sin endpoint verificado**.
7. Webhook valioso: `shoppable_content_posting` (tipo 17). Avisa cada vez que el creador agrega o quita un producto en un video y trae el `content_id`. Exige un receptor HTTPS público; el hub de Corte es local.

## Convenciones y mapa de scopes

- Host `https://open-api.tiktokglobalshop.com`, firma HMAC-SHA256 y parámetros comunes `app_key`, `sign`, `timestamp`. Todos los endpoints los llevan, así que no se repiten en las fichas.
- **Quién llama:** los 26 están bajo «Affiliate creator» y requieren token de creador. Un token de vendedor contra estas APIs da `101000` (fuente: `research/tiktok-docs/creator-authorization-guide.txt`).
- **Regiones:** las Affiliate APIs no están disponibles en Reino Unido ni en la UE (`affiliate-creator-api-overview.txt`). México está soportado: `orders/search 202410` trae `isr` e `iva` «Only for Mexico creator».
- La spec da los scopes como **nombre visible** (`x-tts-scopes`), no como clave. Mapeo:

| Nombre en la spec | Clave en Partner Center | ¿Está en el token de Corte? | Verificación |
|---|---|---|---|
| Affiliate Information | `creator.affiliate.info` | Sí | Por nombre (alta confianza) |
| Read Creator Affiliate Collaborations | `creator.affiliate_collaboration.read` | Sí | Por nombre (alta confianza) |
| Read Showcase Products | `creator.showcase.read` | Sí | Por nombre (alta confianza) |
| Manage Showcase Products | `creator.showcase.write` | Sí | Por nombre (alta confianza) |
| Read Affiliate Share Link | `creator.affiliate.share_link.read` | **No** | Por nombre, y coincide con el `105005` que recibe Corte en trace/search (`hub/creatorhub/sincronizador_ficha.py`) |
| Content Posting | **`creator.video.write`** (corrección del revisor) | **No** (la app no lo tiene aprobado) | **Verificado por el revisor** en `api_meta` oficial (`scope_list[].scope_key`) de 6 endpoints de esta familia. La hipótesis anterior (`creator.affiliate.link.write`) era incorrecta. |
| (sin nombre verificado) | `creator.affiliate.link.write` | Sí | **Sin endpoint verificado.** Ninguna página `api_meta` revisada ni la búsqueda web lo asocian a una API. Confirmar en Partner Center › Manage API (columna «API Names»). |

- Cuando la spec lista dos scopes (por ejemplo, el perfil pide «Affiliate Information, Content Posting»), **no dice si basta uno (O) o si se necesitan los dos (Y)**. Lo seguro es que el perfil y la vitrina ya responden con el token actual.
  - **[Nota del revisor]** Evidencia a favor de «O»: el perfil (`creator.affiliate.info` + `creator.video.write`) y Get Showcase Products (`creator.showcase.read` + `creator.video.write`) responden hoy con un token que **no** tiene `creator.video.write`. Es inferencia a partir del uso real de Corte, no una regla publicada.
- La tabla local de scopes (`affiliate-integration.txt` §API scope mapping) es más vieja que la spec. Ahí «Get Shop Products» cae bajo «Affiliate Information»; la spec lo pone bajo «Content Posting».

## Tabla de todos los endpoints

⭐ = valor alto para Corte. Estado: **en uso** = Corte ya lo llama.

| # | Nombre oficial | Método + path | Scope (spec) | ¿Sirve al creador de Corte? | Valor | Estado |
|---|---|---|---|---|---|---|
| 1 | Get Creator Profile | `GET /affiliate_creator/202508/profiles` | Affiliate Information, Content Posting | Sí | medio | en uso |
| 2 | Get Showcase Products | `GET /affiliate_creator/202405/showcases/products` | Content Posting, Read Showcase Products | Sí | medio | en uso (solo `origin=SHOWCASE`) |
| 3 | Add Showcase Products | `POST /affiliate_creator/202405/showcases/products/add` | Content Posting, Manage Showcase Products | Sí (el token tiene showcase.write) | medio | sin usar |
| 4 | Remove Showcase Products | `DELETE /affiliate_creator/202409/showcases/products` | Manage Showcase Products | Sí | medio | sin usar |
| 5 | Move Showcase Products to the Top | `POST /affiliate_creator/202409/showcases/products/top` | Manage Showcase Products | Sí | bajo | sin usar |
| 6 | Search Open Collaboration Products | `POST /affiliate_creator/202405/open_collaborations/products/search` | Read Creator Affiliate Collaborations | Sí | medio | en uso |
| 7 | ⭐ Get Open Collaboration Product List By Product Ids | `POST /affiliate_creator/202509/open_collaborations/products` | Read Creator Affiliate Collaborations | Sí | alto | en uso (lotes de 20; la spec permite 50) |
| 8 | Search Creator Target Collaborations | `POST /affiliate_creator/202405/target_collaborations/search` | Read Creator Affiliate Collaborations | Sí, con `shop_id` | medio | en uso |
| 9 | ⭐ Search Creator Sample Applications | `POST /affiliate_creator/202412/sample_applications/search` | Read Creator Affiliate Collaborations | Sí | alto | en uso |
| 10 | Get Creator Sample Application Detail | `POST /affiliate_creator/202412/sample_applications/single_query` | Read Creator Affiliate Collaborations | Sí | medio | en uso |
| 11 | ⭐ Creator Search Sample Application Fulfillments | `POST /affiliate_creator/202409/sample_applications/fulfillments/search` | Read Creator Affiliate Collaborations | Sí | alto | en uso |
| 12 | Check Creator Sample Eligibility | `GET /affiliate_creator/202412/samples/labels` | Read Creator Affiliate Collaborations | Sí | medio | en uso |
| 13 | ⭐ Search Creator Affiliate Orders | `POST /affiliate_creator/202410/orders/search` | Read Creator Affiliate Collaborations | Sí | alto | en uso |
| 14 | ⭐ Search Affiliate Orders by Creator | `POST /affiliate_creator/202505/orders/trace/search` | **Read Affiliate Share Link** | **Sí, si se reautoriza con `creator.affiliate.share_link.read`** | alto | integrado; hoy da `105005` |
| 15 | Generate Publisher Sharing Links in Batch | `POST /affiliate_creator/202504/affiliate_sharing_links/publisher/{publisher_id}/generate_batch` | Read Affiliate Share Link | Sí, con dos requisitos: share_link.read y producto en campaña de partner | bajo | sin usar |
| 16 | Generate General Sharing Links | `POST /affiliate_creator/202505/affiliate_sharing_links/general_publishers/generate_batch` | Read Affiliate Share Link | Sí, con los mismos requisitos | bajo (medio si opera como agencia/TAP) | sin usar |
| 17 | ⭐ Upload Shoppable Video File | `POST /affiliate_creator/202505/videos/video_files` | Content Posting (`creator.video.write`) | **No hoy** (revisor): falta `creator.video.write` y la categoría «Creator collaborations» no está habilitada en MX→MX | alto como función; viabilidad baja | sin usar |
| 18 | Create Video Precheck Task | `POST /affiliate_creator/202511/videos/precheck_task` | Content Posting | Igual que 17 | medio | sin usar |
| 19 | Get Shoppable Video Precheck Result | `GET /affiliate_creator/202601/videos/precheck_tasks/{task_id}` | Content Posting | Igual que 17 | medio | sin usar |
| 20 | ⭐ Post Shoppable Video | `POST /affiliate_creator/202603/videos` | Content Posting (`creator.video.write`) | Igual que 17 (verificado: categorías MX→MX = Shoppable Content y TikTok Shop Seller), más cuotas de publicación | alto como función; viabilidad baja | sin usar |
| 21 | Get Shoppable Video Status | `GET /affiliate_creator/202509/videos/{video_id}/status` | Content Posting | Igual que 17; solo para videos publicados por API | medio | sin usar |
| 22 | Upload Shoppable Photo File | `POST /affiliate_creator/202511/photos/photo_files` | Content Posting | Igual que 17 | bajo | sin usar |
| 23 | Post Shoppable Photos | `POST /affiliate_creator/202610/photos` | Content Posting | Dudoso: el perfil real no tiene `PHOTO_SHOPPABLE_PERMISSION_*` | bajo | sin usar |
| 24 | Get Shop Products | `GET /affiliate_creator/202509/shop_products` | Content Posting | **No**: exige tienda vinculada | ninguno | sin usar |
| 25 | Map Tokopedia to TikTok Shop Product IDs | `GET /affiliate_creator/202606/toko_product_mappers` | Read Creator Affiliate Collaborations | No (Tokopedia) | ninguno | sin usar |
| 26 | Get Tokopedia and TikTok Shop Product ID Mappings | `POST /affiliate_creator/202607/map_toko_product` | Read Affiliate Share Link | No (Tokopedia) | ninguno | sin usar |
| N1 | Get Live Room Info | **no verificado** (sin path) | Affiliate Information (tabla local) | No se sabe | potencialmente alto | no existe en la spec |
| N2 | Check Anchor Content | **no verificado** (sin path) | Affiliate Information (tabla local) | No se sabe | no se sabe | no existe en la spec |
| N3 | Check Anchor Prerequisites | **no verificado** (sin path) | Affiliate Information (tabla local) | No se sabe | no se sabe | no existe en la spec |
| N4 | Search Music | **no verificado**: `GET /affiliate_creator/202602/music/search` (solo citado) | sin dato | No se sabe | bajo | no existe en la spec |
| N5 | Post Shoppable Video (versión 202505) | **no verificado**: `POST /affiliate_creator/202505/videos` (solo citado) | sin dato | No se sabe | bajo | no existe en la spec |
| N6 | Get Shop Category And Collection | **no verificado** (sin path) | sin dato | No se sabe | ninguno | no existe en la spec |

**[Nota del revisor, 15/11/2026]** «Igual que 17» en las filas 18–23 significa ahora: **no sirve hoy**, porque el scope «Content Posting» es `creator.video.write` (no aprobado) y la categoría de la app no está habilitada para publicar en MX→MX. La fila 14 sí quedó confirmada: `api_meta` de `search-affiliate-orders-by-creator-202505` da `scope_key = creator.affiliate.share_link.read`, y sus categorías MX→MX (`api_basic_id 7502362897130800897`) incluyen «Creator collaborations». También se confirmó `creator.affiliate.share_link.read` en `generate-general-sharing-links-202505` y `generate-publisher-sharing-links-in-batch-202504`. Con el token actual sirven **13** endpoints (#1–#13); con reautorización, **14** (+#14), más #15 y #16 si el producto está en una campaña de partner.

---

## Confirmación de los 11 de lectura que Corte ya usa

Se buscó el uso de cada uno en `hub/creatorhub/sincronizador.py` y en `hub/creatorhub/sincronizador_ficha.py`.

| Endpoint | Dónde lo usa Corte | ¿Responde con el token actual? |
|---|---|---|
| `GET 202508/profiles` | sincronizador.py, auth.py, conexion.py | Sí |
| `POST 202412/sample_applications/search` | sincronizador.py | Sí |
| `POST 202412/sample_applications/single_query` | sincronizador.py y la fase «recuperadas» de ficha | Sí |
| `POST 202409/sample_applications/fulfillments/search` | sincronizador.py | Sí |
| `POST 202509/open_collaborations/products` | sincronizador.py | Sí |
| `POST 202410/orders/search` | sincronizador.py | Sí |
| `GET 202405/showcases/products` | sincronizador.py (`origin=SHOWCASE`) | Sí |
| `GET 202412/samples/labels` | ficha, fase «etiquetas» | Sí |
| `POST 202405/target_collaborations/search` | ficha, fase «dirigidas» | Sí |
| `POST 202405/open_collaborations/products/search` | ficha, fase «parecidos» | Sí |
| `POST 202505/orders/trace/search` | ficha, fase «trazas» | **No**: `105005`. Su scope es «Read Affiliate Share Link» (`creator.affiliate.share_link.read`). |

**Cómo conseguir el scope que falta.** La app ya lo tiene aprobado. La guía oficial dice: *«If the authorized scopes are not sufficient… ask the creator to "remove all access" and re-authorize again»*. Después de canjear el code, hay que comprobar que `granted_scopes` lo incluya (`creator-authorization-guide.txt`, pasos 6–7 y §Partial authorization).

---

## Fichas detalladas

Abreviaturas de fuente:
- **[LOCAL]**: archivo en `research\tiktok-docs\`.
- **[SPEC]**: `https://raw.githubusercontent.com/isaackogan/TikTok-Shop-Api-SDKs/main/.openapi/tiktok-shop.openapi.yaml` (`info.version 2026.11.13`). De ahí salen los scopes (`x-tts-scopes`), los códigos de error y las URLs oficiales. Los esquemas se leyeron en la vista renderizada del mismo spec, `https://ttspa.docs.isaackogan.com/openapi/reference/operations/<operación>/` (spec 2026.10.28). Ese sitio no es oficial; se usó solo como lector del mismo YAML.
- **[DOC]**: página oficial `https://partner.tiktokshop.com/docv2/page/<slug>` (`x-tts-docs-url`). WebFetch no la puede leer porque se arma con JS, así que se cita como referencia.

### Perfil

#### 1. Get Creator Profile
- **Método y path:** `GET /affiliate_creator/202508/profiles`
- **Scope:** Affiliate Information, Content Posting (`creator.affiliate.info`).
- **Quién:** token de creador. El creador debe tener región de venta configurada; si no, falla por precondición.
- **Parámetros:** ninguno, aparte de los comunes.
- **Respuesta:**
  - `avatar{width,height,url}`, `username`, `selection_region`, `register_region`.
  - `seller_type` (`CROSS_BORDER`, `LOCAL`).
  - `permissions[]` (`LIVE_STREAM_PERMISSION`, `SELF_SALE_PERMISSION`, `ADD_AFFILIATE_PERMISSION`, `PHOTO_SHOPPABLE_PERMISSION_PRODUCT`, `PHOTO_SHOPPABLE_PERMISSION_SHOP`).
  - `user_type` (`TIKTOK_SHOP_OFFICIAL_ACCOUNT`, `TIKTOK_MARKETING_ACCOUNT`, `TIKTOK_SHOP_CREATOR`).
  - `creator_user_open_id`.
- **Errores:** `16015006` (sin región de selección), `16015007` (sin región de venta), `16501011` (sin permiso), `16504002`, `36009002` (demasiadas solicitudes).
- **Límites:** sin paginación. El límite de frecuencia no tiene cifra publicada (solo existe el error 36009002).
- **¿Sirve a Corte?** Sí, en uso (perfil, permisos y región del creador). Ojo: `seller_type` puede traer valores que la doc no lista.
- **Valor:** medio (ya capturado). Dos usos posibles:
  - `permissions` para habilitar u ocultar funciones; por ejemplo, ocultar fotos comprables, que pueden depender de `PHOTO_SHOPPABLE_*`.
  - `creator_user_open_id` para cruzar con el `creator_open_id` de los webhooks.
- **Fuente:** [LOCAL] `get-creator-profile-202508.txt`; [SPEC] `getCreatorProfile`; [DOC] `get-creator-profile-202508`.

### Vitrina (showcase)

#### 2. Get Showcase Products
- **Método y path:** `GET /affiliate_creator/202405/showcases/products`
- **Scope:** Content Posting, Read Showcase Products (`creator.showcase.read`).
- **Quién:** token de creador.
- **Parámetros (query):**
  - `page_size` (obligatorio, 1–20).
  - `page_token` (opcional).
  - `origin` (obligatorio): `SHOWCASE` (vitrina) o `LIVE` (bolsa de productos del LIVE).
- **Respuesta:**
  - `products[]`:
    - `id`, `title`, `shop.name`, `main_images[]{width, heigth [sic], url}`, `addition.customized_main_images[]`.
    - `price.original_price` / `seller_discount_price` / `platform_discount_price` `{minimum_amount, maximum_amount, currency}`.
    - `status{inventory_status (IN_STOCK|SOLD_OUT), review_status (APPROVED|UNDER_REVIEW|CHANGES_UNDER_REVIEW|UNAVAILABLE|REJECTED|ZERO_COMMISSION), is_hidden, added_status (ADDED|NOT_ADDED|REJECTED)}`.
    - `source` (THIRD_PARTY|AFFILIATE|TIKTOK_STORE), `detail_link`, `third_party_link`, `sale_regions[]`.
    - `commission{rate, reward_rate}` en centésimas de %.
    - `collaboration{id, type (1 abierta, 2 dirigida, 5 campaña de partner, 11 flat fee, 12 Collaboration Plus, 13 Affiliate Promotion), partner{id,name}}`.
  - `next_page_token`, `total_count`.
- **Límites:** hasta 2000 productos en vitrina. Errores `18001405` (cuenta sin región de selección) y `36009003`.
- **¿Sirve a Corte?** Sí, en uso con `origin=SHOWCASE`.
- **Valor:** medio. Dato nuevo: con `origin=LIVE` y el creador transmitiendo, devuelve la bolsa del LIVE con `added_status`. Aunque el creador tenga `LIVE_STREAM_PERMISSION`, solo sirve si hace LIVEs.
- **Nota:** la spec declara `added_status` a nivel de producto, pero el ejemplo lo anida en `status`.
- **Fuente:** [LOCAL] `get-showcase-products-202405.txt`; [SPEC] `getShowcaseProducts`; [DOC] `get-showcase-products-202405`.

#### 3. Add Showcase Products
- **Método y path:** `POST /affiliate_creator/202405/showcases/products/add`
- **Scope:** Content Posting, Manage Showcase Products (`creator.showcase.write`).
- **Quién:** token de creador. Los usuarios de Global Shop necesitan al menos una región seleccionada. El producto ya debe formar parte de una colaboración (`affiliate-integration.txt`, §Showcase interactions).
- **Cuerpo:**
  - `add_type` (obligatorio): `PRODUCT_ID` o `PRODUCT_LINK`.
  - `product_ids[]` (máximo 20, cuando `add_type=PRODUCT_ID`).
  - `product_link` (cuando `add_type=PRODUCT_LINK`).
- **Respuesta:** `errors[]{code, message, detail.product_id}`, que se omite si no hubo errores. Ojo: puede responder `code=0` con productos que no se agregaron.
- **¿Sirve a Corte?** Sí; el token tiene `creator.showcase.write`.
- **Valor:** medio. No da datos nuevos, pero permite un botón «Agregar a mi vitrina» desde «parecidos» o desde planes dirigidos. Es escritura: requiere confirmación explícita del usuario en la app.
- **Fuente:** [SPEC] `addShowcaseProducts`; [DOC] `add-showcase-products-202405`; [LOCAL] `affiliate-integration.txt` (líneas 435–441).

#### 4. Remove Showcase Products
- **Método y path:** `DELETE /affiliate_creator/202409/showcases/products`
- **Scope:** Manage Showcase Products (`creator.showcase.write`).
- **Quién:** token de creador.
- **Cuerpo:** `product_ids[]` (obligatorio, de 1 a 200). Es un **DELETE con cuerpo JSON**; hay que confirmar que el cliente HTTP del hub lo envíe.
- **Respuesta:** `data{code, message, request_id}`.
- **Errores:** `16015001` (los ids no están en la vitrina), `16015027` (error de sistema).
- **¿Sirve a Corte?** Sí.
- **Valor:** medio. Permite limpiar la vitrina de productos `SOLD_OUT`, `ZERO_COMMISSION` o `UNAVAILABLE` detectados con el #2. Es escritura.
- **Fuente:** [SPEC] `removeShowcaseProducts`; [DOC] `remove-showcase-products-202409`.

#### 5. Move Showcase Products to the Top
- **Método y path:** `POST /affiliate_creator/202409/showcases/products/top`
- **Scope:** Manage Showcase Products.
- **Quién:** token de creador.
- **Cuerpo:** `product_ids[]` (obligatorio). Deben estar ya en la vitrina; el orden del arreglo es el orden final. No se documenta un máximo.
- **Respuesta:** `data{code, message, request_id}`.
- **Errores:** `16015001`, `16015027`.
- **¿Sirve a Corte?** Sí.
- **Valor:** bajo. Serviría para fijar arriba los productos que más venden. Es escritura.
- **Fuente:** [SPEC] `moveShowcaseProductsToTheTop`; [DOC] `move-showcase-products-to-the-top-202409`.

### Colaboración abierta y dirigida

#### 6. Search Open Collaboration Products
- **Método y path:** `POST /affiliate_creator/202405/open_collaborations/products/search`
- **Scope:** Read Creator Affiliate Collaborations (`creator.affiliate_collaboration.read`). En la tabla local de scopes aparece con su nombre viejo, «Creator Search Open Collaboration Product».
- **Quién:** token de creador. Solo busca en las regiones en las que el creador está registrado como afiliado.
- **Query:**
  - `page_size` (obligatorio, 1–20) y `page_token`. Para cada página siguiente hay que repetir los mismos filtros.
  - `sort_field` (`commission_rate`, `product_sales_price`, `commission`, `units_sold`).
  - `sort_order` (`ASC` por defecto, `DESC`).
- **Cuerpo (todo opcional):**
  - `title_keywords[]`: máximo 20, de hasta 255 caracteres; se combinan con Y.
  - `sales_price_range{amount_ge, amount_lt}`.
  - `category{id}`.
  - `commission_rate_range{rate_ge (100–8000), rate_lt (mínimo 1000)}`.
- **Respuesta:**
  - `products[]{id, title, shop.name, has_inventory, units_sold, sale_region, main_image_url, detail_link, original_price{currency,minimum_amount,maximum_amount}, sales_price{…}, category_chains[] (máx. 3){id,local_name,is_leaf,parent_id}, commission{rate,currency,amount}}`.
  - `units_sold` **no viene si el creador no otorgó el compartido de datos precisos**.
  - `next_page_token`, `total_count`.
- **¿Sirve a Corte?** Sí, en uso: fase «parecidos» con `title_keywords`.
- **Valor:** medio. Corte todavía no usa `category.id`, `commission_rate_range` ni `sort_field=units_sold`. Con ellos podría mostrar «lo más vendido de tu categoría con comisión ≥ X %».
- **Nota:** el ejemplo curl de `affiliate-integration.txt` (línea 210) usa por error el path `/affiliate_seller/202405/...`. El path correcto es el de la spec.
- **Fuente:** [SPEC] `searchOpenCollaborationProducts`; [DOC] `search-open-collaboration-products-202405`; [LOCAL] `affiliate-integration.txt` (líneas 207–290).

#### 7. ⭐ Get Open Collaboration Product List By Product Ids
- **Método y path:** `POST /affiliate_creator/202509/open_collaborations/products`
- **Scope:** Read Creator Affiliate Collaborations.
- **Quién:** token de creador.
- **Parámetros:** query `product_ids` (lista numérica separada por comas, **máximo 50 por solicitud**); el cuerpo va vacío (`{}`).
- **Respuesta:** `products[]` con los mismos campos que el #6, más `shop_ads_commission{rate}`. Puede devolver menos productos que los pedidos.
- **¿Sirve a Corte?** Sí, en uso.
- **Valor:** alto. Es de donde salen imágenes, títulos, precios y comisión de los productos de pedidos y muestras. No trae datos nuevos, pero **Corte pide lotes de 20 y la spec permite 50**, lo que reduce las llamadas a menos de la mitad. Esta doc no estaba descargada en `tiktok-docs/` (era la excepción registrada en `CONTEXTO.md`); ya queda verificada en la spec.
- **Fuente:** [SPEC] `getOpenCollaborationProductListByProductIds`; [DOC] `get-open-collaboration-product-list-by-product-ids-202509`.

#### 8. Search Creator Target Collaborations
- **Método y path:** `POST /affiliate_creator/202405/target_collaborations/search`
- **Scope:** Read Creator Affiliate Collaborations.
- **Quién:** token de creador. Se consulta una tienda a la vez.
- **Query:** `page_size` (obligatorio, 0–100) y `page_token`. Para cada página siguiente hay que repetir `page_size`, `shop_id`, `keyword` y `keyword_type`.
- **Cuerpo:**
  - `shop_id` (obligatorio).
  - `keyword_type` (`TARGET_COLLABORATIONS_ID`: devuelve LIVE/EXPIRED/DELETED/ENDED; `TARGET_COLLABORATIONS_NAME`: solo LIVE).
  - `keyword` (para ID, un entero en base 10; para nombre, menos de 500 bytes).
- **Respuesta:** `total_count`, `next_page_token`, `target_collaborations[]{id, name, status (LIVE|EXPIRED|DELETED|ENDED), products[]{id, title, main_image_url, commission{rate, amount, currency}}}`.
- **¿Sirve a Corte?** Sí, en uso. El `shop_id` sale de cumplimientos.
- **Valor:** medio. Limitación: **no existe un listado global de invitaciones**; hay que conocer el `shop_id` de cada tienda.
- **Fuente:** [LOCAL] `search-creator-target-collaborations-202405.txt`; [SPEC] `searchCreatorTargetCollaborations`; [DOC] `search-creator-target-collaborations-202405`.

### Muestras

#### 9. ⭐ Search Creator Sample Applications
- **Método y path:** `POST /affiliate_creator/202412/sample_applications/search`
- **Scope:** Read Creator Affiliate Collaborations.
- **Quién:** token de creador.
- **Query:** `page_size` (1–50, 20 por defecto) y `page_token`; en cada página hay que repetir los mismos `application_statuses`.
- **Cuerpo:** `application_statuses[]`. La spec no lo marca obligatorio, pero Corte comprobó que sí lo es; con algunos estados devuelve todo, así que hay que deduplicar por `id`. Valores:
  - `PENDING`, `AWAITING_SHIPMENT`, `SHIPPED`, `CONTENT_PENDING`, `COMPLETED`.
  - `REJECT_CANCELLED`, `OVERDUE_CANCELLED`, `UNFULFILL_CANCELLED`, `FULFILLMENT_SUSPEND`, `DEL_OPEN_COLLAB`, `SELLER_NOT_SHIP_CANCELLED`, `WITHDRAW_CANCELLED`, `UNFULFILLABLE_CANCELLED`.
  - `OPS_CANCELLED`, `OPS_FAILED`, `OPS_ COMPLETED` (con espacio en la doc).
  - `TO_BE_POST`, `POST_IN_REVIEW`, `POST_FAILED`, `CANCELED`.
- **Respuesta:**
  - `next_page_token` (cadena vacía en la última página).
  - `sample_applications[]{id, sample_product{id, sku_id, sku_sale_property_value_names[]}, main_order_id, activity_id, status, creator_fulfillment{id, expiration_time, total_suspend_duration, status, bound_product_status}}`.
- **¿Sirve a Corte?** Sí, en uso.
- **Valor:** alto (ya capturado). No trae `create_time`; para eso está el #10.
- **Fuente:** [LOCAL] `search-creator-sample-applications-202412.txt`; [SPEC] `searchCreatorSampleApplications`; [DOC] `search-creator-sample-applications-202412`.

#### 10. Get Creator Sample Application Detail
- **Método y path:** `POST /affiliate_creator/202412/sample_applications/single_query`
- **Scope:** Read Creator Affiliate Collaborations.
- **Quién:** token de creador.
- **Cuerpo:**
  - `product_id` (obligatorio).
  - `application_type` (obligatorio: `FREE_SAMPLE`, `SAMPLE_COUPON`, `SAMPLE_CAMPAIGN`).
  - `application_id` (para `FREE_SAMPLE`).
  - `main_order_id` (para `SAMPLE_COUPON`, `SAMPLE_CAMPAIGN` o `REFUNDABLE_SAMPLE`, o cuando falta `application_id`).
- **Respuesta:** `sample_application{id, create_time, sample_product{…}, main_order_id, activity_id, type, status, creator_fulfillment{id, expiration_time, total_suspend_duration, status (incluye REPEATED)}}`.
- **Errores:** `36009003`.
- **Límites:** una solicitud por llamada.
- **¿Sirve a Corte?** Sí, en uso.
- **Valor:** medio (`create_time` y la recuperación de solicitudes).
- **Fuente:** [LOCAL] `get-creator-sample-application-detail-202412.txt`; [SPEC] `getCreatorSampleApplicationDetail`; [DOC] `get-creator-sample-application-detail-202412`.

#### 11. ⭐ Creator Search Sample Application Fulfillments
- **Método y path:** `POST /affiliate_creator/202409/sample_applications/fulfillments/search`
- **Scope:** Read Creator Affiliate Collaborations.
- **Quién:** token de creador.
- **Query:** `sort_order` (`ASC` por defecto, `DESC`) y `sort_field` (`expired_time` por defecto, `create_time`).
- **Cuerpo:** `fulfillment_statuses[]` (obligatorio): `PENDING`, `ONGOING`, `SUCCEED`, `FAILED`, `OVERDUE`, `SUSPEND`, `CANCELLED`, `EXEMPTED`.
- **Respuesta:** `fulfillments[]`:
  - `id`, `shop_id`, `application_id`, `product_id`.
  - `sample_application_type` (FREE_SAMPLE|SAMPLE_COUPON|SAMPLE_CAMPAIGN|PLATFORM_FREE_SAMPLE|REFUNDABLE_SAMPLE|UNSPECIFIED).
  - `expiration_time` = recepción + 14 días + suspensión.
  - `total_suspend_duration`, `status`.
  - `bound_product_status` (UNKNOWN|LIVE|OUT_OF_STOCK|SELLER_DEACTIVATE|PLATFORM_DEACTIVATE|NO_PLAN|PERMANENT_DELETED).
- **Límites:** **no tiene paginación documentada** (ni `page_size` ni `page_token`). Observado por Corte: en estados cerrados, `expiration_time` = la hora de la consulta.
- **¿Sirve a Corte?** Sí, en uso.
- **Valor:** alto (fechas límite y `shop_id`).
- **Fuente:** [LOCAL] `creator-search-sample-application-fulfillments-202409.txt`; [SPEC] `creatorSearchSampleApplicationFulfillments`; [DOC] `creator-search-sample-application-fulfillments-202409`.

#### 12. Check Creator Sample Eligibility
- **Método y path:** `GET /affiliate_creator/202412/samples/labels`
- **Scope:** Read Creator Affiliate Collaborations.
- **Quién:** token de creador.
- **Query:** `product_id` (obligatorio).
- **Respuesta:** `label`:
  - `can_apply`, `status` (UNKNOWN|TO_APPLY|ONGOING|COMPLETE), `application_id`.
  - `reach_limit`: el creador llegó al tope de solicitudes.
  - `sample_product.sample_sku_list[]{id, sale_property_value_ids, price{amount, currency}, sale_properties[]{id, name, value_id, value_name}, is_available, unavailable_reason (IS_PREORDER|IS_GIFT|OUT_OF_STOCK|EXCEED_CB_PRICE_THRESHOLD|ALREADY_APPLYED|UNKNOWN)}`.
- **Errores:** `36009003`.
- **Límites:** un producto por llamada.
- **¿Sirve a Corte?** Sí, en uso.
- **Valor:** medio. `reach_limit` sirve para avisar «ya no puedes pedir más muestras».
- **Fuente:** [LOCAL] `check-creator-sample-eligibility-202412.txt`; [SPEC] `checkCreatorSampleEligibility`; [DOC] `check-creator-sample-eligibility-202412`.

### Pedidos

#### 13. ⭐ Search Creator Affiliate Orders
- **Método y path:** `POST /affiliate_creator/202410/orders/search`
- **Scope:** Read Creator Affiliate Collaborations.
- **Quién:** token de creador.
- **Query:** `page_size` (obligatorio, 1–100, 20 por defecto) y `page_token`.
- **Cuerpo:** `create_time_ge` y `create_time_lt`, en **segundos**. Si solo se pasa `ge`, `lt` toma la hora actual; si solo se pasa `lt`, `ge` toma la fecha más antigua.
- **Respuesta:**
  - `orders[]{id, create_time, delivery_time, status (UNSPECIFIED|AWAITING PAYMENT|To-SETTLE|SETTLED|REFUNDED|FROZEN)}`.
  - `skus[]`:
    - Producto y colaboración: `id`, `campaign_id`, `open_collaboration_id`, `target_collaboration_id`, `product_name`, `product_id`, `price{amount,currency}`, `shop_name`.
    - Contenido y cantidades: `content_type` (SHOP|VIDEO|LIVE|PRE_LIVE|PROMOTION_PAGE|LINKSHARE), `content_id`, `quantity`, `returned_quantity`, `refunded_quantity`.
    - Tasas: `commission_rate` (total), `commission_tier_setting`, `commission_model`, `commission_bonus_rate`, `standard_commission_rate`, `shop_ads_commission_rate`.
    - Comisiones estimadas y reales (base, estándar, bono, shop ads y total): `estimated_*` y `actual_*`.
    - Recompensa de partner: `creator_commission_reward_rate`, `estimated_creator_commission_reward_fee`, `actual_creator_commission_reward_fee`.
    - Impuestos: **`isr`, `iva` (solo México)**, `pit`, `shared_with_partner`.
    - Otros: `trace_info{id,type}`, `tag`, `last_update_time`, `is_carousel`.
  - `next_page_token`, `total_count` (cuenta líneas SKU, no pedidos).
- **Límites:** `page_size` cuenta filas SKU antes de agruparlas en pedidos. Observado por Corte, no documentado: sin `create_time_ge` solo trae unos 30 días, por eso pide ventanas semanales. No hay filtro por fecha de actualización.
- **¿Sirve a Corte?** Sí, en uso. Corte ya guarda `isr`, `iva`, `is_carousel`, `last_update_time` y las **tasas** del desglose (estándar, shop ads, bono), no sus importes. Desde la rev. 7 (18/11/2026) también guarda `trace_info.type` por línea, nunca `trace_info.id` (ver `docs/ORDER_TRACE_RETIREMENT.md`).
- **Valor:** alto (ya capturado).
- **Fuente:** [LOCAL] `search-creator-affiliate-orders-202410.txt`; [SPEC] `searchCreatorAffiliateOrders`; [DOC] `search-creator-affiliate-orders-202410`.

#### 14. ⭐ Search Affiliate Orders by Creator (trace)
- **Método y path:** `POST /affiliate_creator/202505/orders/trace/search`
- **Scope:** **Read Affiliate Share Link → `creator.affiliate.share_link.read`**, según `x-tts-scopes` del [SPEC]. Es el scope que le falta al token de Corte, y coincide con el `105005` que el hub ya registra.
- **Quién:** token de creador.
- **Query:** `page_size` (obligatorio, 1–100) y `page_token`.
- **Cuerpo:**
  - `time_ge` y `time_lt`: obligatorios, en **milisegundos**.
  - `time_type`: `PAY_TIME`, `DELIVERY_TIME`, `SETTLE_TIME` o `CREATE_TIME` (por defecto).
- **Respuesta:**
  - `orders[]`:
    - `id`: el esquema lo da como **int64 numérico**. Supera 2^53, así que en TypeScript se pierde precisión si no se trata como texto.
    - `status` (UNSPECIFIED|ORDERED|SETTLED|REFUNDED|FROZEN|**DEDUCTED**), `create_time`, `delivery_time`.
  - `skus[]`:
    - Producto: `id`, `product_id`, `product_name`, `shop_name`, `campaign_id`, `price`.
    - Cantidades: `quantity`, `returned_quantity`, `refunded_quantity`.
    - Tasas: `commission_rate` (de la colaboración), `shop_ads_commission_rate`, `commission_bonus_rate`, `creator_commission_reward_rate`.
    - Contenido: `delivery_time`, `content_type`, `content_id`, `trace{id,type GENERAL|SPECIFIC}`.
    - Montos estimados y reales: base, comisión, bono, shop ads y recompensa de partner.
  - `next_page_token`, `total_count`.
- **Diferencias con el #13:**
  - **No trae** `isr`, `iva`, `tag`, `is_carousel`, `open_collaboration_id`, `target_collaboration_id` ni la comisión estándar.
  - `actual_commission` incluye bono y recompensa, pero no shop ads.
  - En `REFUNDED`, los montos reales llegan como cero localizado.
- **Límites:** no se documenta una ventana máxima; Corte usa 7 días. El límite de frecuencia tampoco se documenta.
- **¿Sirve a Corte?** **Sí, con un requisito: reautorizar para obtener `creator.affiliate.share_link.read`.** El código ya está integrado (fase «trazas»).
- **Valor:** alto. Datos nuevos:
  1. Filtrar por **`SETTLE_TIME`** da «lo que te liquidaron en este periodo» y permite conciliar con los pagos. Hoy Corte solo sabe que un pedido está `SETTLED`, pero no cuándo se liquidó.
  2. Filtrar por `PAY_TIME`.
  3. El estado **`DEDUCTED`** (deducciones extra al saldo) no existe en el #13.
- **Sin verificar:** si devuelve **todos** los pedidos o solo los que vienen de share links. La descripción dice «affiliate orders attributed to the creator» y su `content_type` incluye VIDEO y LIVE, pero el nombre y el scope apuntan a share links. Solo se sabrá al llamarlo con el scope.
- **Fuente:** [LOCAL] `search-affiliate-orders-by-creator-202505.txt`; [SPEC] `searchAffiliateOrdersByCreator`; [DOC] `search-affiliate-orders-by-creator-202505`.

### Enlaces para compartir (share links)

#### 15. Generate Publisher Sharing Links in Batch
- **Método y path:** `POST /affiliate_creator/202504/affiliate_sharing_links/publisher/{publisher_id}/generate_batch`
- **Scope:** Read Affiliate Share Link (`creator.affiliate.share_link.read`).
- **Quién:** token de creador. La descripción lo orienta a una **agencia** que comparte enlaces con un *publisher*. El producto debe estar ya en la campaña, agregado con «Generate Multi Affiliate Partner Campaign Product Links», que pertenece a la familia de partner.
- **Parámetros:**
  - Path: `publisher_id` (obligatorio; id del publisher en el sistema del partner).
  - Cuerpo: `material{ids[] (1–50 para PRODUCT), type (PRODUCT|CAMPAIGN), promotion_campaign_schema (si CAMPAIGN)}`, `campaign_id` (opcional), `link_type` (`TOKO`, solo agencias de Tokopedia).
- **Respuesta:** `sharing_links[]{material_id (int64), sharing_link, deep_link, one_link}` y `failed_materials[]{material_id (texto), fail_reason}`.
- **¿Sirve a Corte?** Sí con requisitos: el scope que falta y un producto metido en una campaña de partner (TAP). La app tiene aprobados `partner.tap_campaign.*`, pero eso es otra familia y otro token.
- **Valor:** bajo para un creador individual. En los pedidos, `trace.type=SPECIFIC` y `trace.id=publisher_id`.
- **Fuente:** [SPEC] `generatePublisherSharingLinksInBatch`; [DOC] `generate-publisher-sharing-links-in-batch-202504`.

#### 16. Generate General Sharing Links
- **Método y path:** `POST /affiliate_creator/202505/affiliate_sharing_links/general_publishers/generate_batch`
- **Scope:** Read Affiliate Share Link.
- **Quién:** token de creador. Tiene el mismo requisito de producto en campaña que el #15.
- **Cuerpo:** `material{ids[] (1–50), type (solo PRODUCT por ahora), promotion_campaign_schema}`, `campaign_id`, `link_type` (`TOKO`).
- **Respuesta:**
  - `sharing_links[]`:
    - `material_id`.
    - `sharing_link`: se le pueden agregar `event_id`, `publisher_id`, `publisher_name`, `device_type` (1 móvil, 2 escritorio), `device_id` y `referrer_src`.
    - `deep_link` y `one_link`: hay que reemplazar `o_event_id` por un id único en cada clic.
  - `failed_materials[]{material_id, fail_reason}`.
- **¿Sirve a Corte?** Sí con requisitos (los mismos que el #15).
- **Valor:** bajo (medio si opera como agencia/TAP). Dato nuevo posible: enlaces rastreables fuera de TikTok (WhatsApp, Instagram). Sus pedidos llegan con `content_type=LINKSHARE` y `trace.type=GENERAL`, con `trace.id`=`event_id`, y se podrían separar ventas por canal.
- **Fuente:** [SPEC] `generateGeneralSharingLinks`; [DOC] `generate-general-sharing-links-202505`.

### Publicación de contenido (scope «Content Posting» = `creator.video.write`, verificado por el revisor)

> **[Nota del revisor]** Las fichas 17–24 se escribieron con la hipótesis `creator.affiliate.link.write`. Esa hipótesis es incorrecta: el `api_meta` oficial da `creator.video.write` para todos estos endpoints, y la app no tiene ese scope. Además, Upload Shoppable Video File y Post Shoppable Video solo aceptan apps de categoría «Shoppable Content» o «TikTok Shop Seller» con registro MX y mercado MX. Donde las fichas dicen «confirmar la clave», léase: **pedir `creator.video.write` y usar una app de categoría permitida**. No se verificó si una app registrada fuera de MX tiene otra lista de categorías (la consulta US→MX devolvió `available: true` sin categorías).

#### 17. ⭐ Upload Shoppable Video File
- **Método y path:** `POST /affiliate_creator/202505/videos/video_files`
- **Scope:** Content Posting.
- **Quién:** token de creador.
- **Cuerpo:** `multipart/form-data` con `data` (archivo binario, obligatorio).
  - Formatos MP4, MOV, MKV, WMV, WEBM, AVI, 3GP, FLV y MPEG.
  - **Máximo 10 MB**; más grande requiere el proceso «Large File Uploads», cuyo path no se verificó.
  - Relación de aspecto de 9:16 a 16:9. Se recomienda 720p o más y más de 30 s.
- **Respuesta:** `video_file{id, md5}`.
- **¿Sirve a Corte?** ~~Sí con requisito: confirmar que «Content Posting» = `creator.affiliate.link.write`.~~ **[Revisor] No hoy:** el scope es `creator.video.write` (no aprobado) y en MX→MX solo pueden llamarlo apps de categoría «Shoppable Content» o «TikTok Shop Seller» (`callable_categories` de `api_basic_id 7502362897129981697`). Encajaría con el hub en la PC, donde están los archivos de video.
- **Valor:** alto como primer paso obligatorio del #20.
- **Fuente:** [SPEC] `uploadShoppableVideoFile`; [DOC] `upload-shoppable-video-file-202505`.

#### 18. Create Video Precheck Task
- **Método y path:** `POST /affiliate_creator/202511/videos/precheck_task`
- **Scope:** Content Posting.
- **Quién:** token de creador.
- **Cuerpo:** `video_info{file_id}` (obligatorio) y `product_link_info{product_id, title}` (obligatorios; el título del ancla tiene **≤ 29 caracteres** y no admite puntuación ni emoji).
- **Respuesta:** `precheck{task_id}`.
- **Errores relevantes:**
  - `170001019`: cuota diaria de revisión previa agotada.
  - `170001013`: se rebasó el límite de productos en la vitrina.
  - `170001005`: términos no firmados.
  - `170001008`: falta verificación de edad.
  - `16011007` / `16011009` / `16011069`: problemas con el título.
- **¿Sirve a Corte?** Sí, con el mismo requisito que el #17.
- **Valor:** medio. Revisa infracciones antes de publicar.
- **Fuente:** [SPEC] `createVideoPrecheckTask`; [DOC] `create-video-precheck-task-202511`.

#### 19. Get Shoppable Video Precheck Result
- **Método y path:** `GET /affiliate_creator/202601/videos/precheck_tasks/{task_id}`
- **Scope:** Content Posting.
- **Quién:** token de creador.
- **Parámetros:** path `task_id` (obligatorio).
- **Respuesta:** `precheck_task{id, violation_check_result{status SUCCESS|FAIL|PROCESSING, issues[]{risk, suggestions}}, good_quality_check_result{status, issues[]{code, suggestions}}}`. El segundo bloque se omite si la revisión de calidad está deshabilitada.
- **Nota:** la descripción del #18 apunta a `GET /affiliate_creator/202511/videos/precheck_tasks/{task_id}`, pero el path real en la spec es **202601**. También existen los webhooks `video_precheck_result` (55) y `shoppable_video_precheck_tasks_result` (59).
- **¿Sirve a Corte?** Igual que el #17.
- **Valor:** medio.
- **Fuente:** [SPEC] `getShoppableVideoPrecheckResult`; [DOC] `get-shoppable-video-precheck-result-202601`.

#### 20. ⭐ Post Shoppable Video
- **Método y path:** `POST /affiliate_creator/202603/videos`
- **Scope:** Content Posting.
- **Quién:** token de creador.
- **Cuerpo:**
  - `video_info`:
    - `file_id` (obligatorio, del #17).
    - `title` (obligatorio en el esquema; hasta 2200 runas UTF-16).
    - `cover_uri` (del #22) o `cover_timestamp_ms`. Si llegan los dos, gana `cover_uri`.
    - `music_id` (de «Search Music», que no está verificado).
  - `product_link_info`: `product_id` (obligatorio; de Get Showcase Products o Get Shop Products) y `title` (obligatorio, ≤ 29 caracteres).
- **Respuesta:** `video{id}`; el estado se consulta con el #21.
- **Errores relevantes:**
  - Cuotas: `170001020` (frecuencia), `170001060` / `61` / `62` (por infracciones, periodo de novato o límite de la plataforma).
  - Producto: `170001063` (solo subasta), `170001013` (límite de productos en vitrina).
  - Cuenta: `170001030` / `31` (cuenta bloqueada o sin permiso de publicar).
- **¿Sirve a Corte?** **[Revisor] No hoy.** Necesitaría (1) el scope `creator.video.write` aprobado y autorizado, (2) una app de categoría permitida («Shoppable Content» en MX→MX, según `callable_categories` de `api_basic_id 7502333053755541265`) y (3) el producto en la vitrina.
- **Valor:** alto (funcional). Corte podría publicar desde la PC el video del producto de una **muestra adeudada** con su ancla de producto, que es justo el problema de «quedar bien con las tiendas». **No verificado:** que un video publicado por API cuente para el cumplimiento de la muestra. La doc de cumplimientos solo dice que `ONGOING` = contenido creado y en evaluación. El campo `is_ai_generated` existe en fotos (#23), pero **no aparece** en el esquema de video.
- **Fuente:** [SPEC] `postShoppableVideo`; [DOC] `post-shoppable-video-202603`.

#### 21. Get Shoppable Video Status
- **Método y path:** `GET /affiliate_creator/202509/videos/{video_id}/status`
- **Scope:** Content Posting.
- **Quién:** token de creador.
- **Parámetros:** path `video_id` (obligatorio; del #20).
- **Respuesta:** `video{id, post_status SUCCESS|FAIL|PROCESSING, post_time}`. `post_time` viene en segundos y solo si `SUCCESS`.
- **Errores:** `170001016` (el video no es del creador), `38007001`.
- **¿Sirve a Corte?** Igual que el #17; solo para videos publicados por API.
- **Valor:** medio. **No da métricas** (vistas ni ventas).
- **Fuente:** [SPEC] `getShoppableVideoStatus`; [DOC] `get-shoppable-video-status-202509`.

#### 22. Upload Shoppable Photo File
- **Método y path:** `POST /affiliate_creator/202511/photos/photo_files`
- **Scope:** Content Posting.
- **Quién:** token de creador.
- **Cuerpo:** `multipart/form-data` con `data` (obligatorio). Formatos JPG, JPEG, PNG, WEBP, HEIC y BMP; máximo 10 MiB; no admite archivos de 0 bytes; relación de 9:16 a 16:9.
- **Respuesta:** `photo_file{photo_uri}`, que se usa como `cover_uri` en el #20 o en `photo_file_uris` del #23.
- **Errores:** `36009003`.
- **¿Sirve a Corte?** Igual que el #17.
- **Valor:** bajo (portada personalizada del video).
- **Fuente:** [SPEC] `uploadShoppablePhotoFile`; [DOC] `upload-shoppable-photo-file-202511`.

#### 23. Post Shoppable Photos
- **Método y path:** `POST /affiliate_creator/202610/photos`
- **Scope:** Content Posting.
- **Quién:** token de creador.
- **Cuerpo:**
  - `photos_info[]{photo_file_uris}` (obligatorio).
  - `music_id`.
  - `title` (hasta 5000 runas UTF-16; admite hashtags).
  - `link_info{post_type (obligatorio: 1 producto, 2 tienda, 3 una foto–un producto), shop_info{shop_id, group_type (1 inicio, 2 categoría, 3 colección), group_id}, links[]{product_id, link_title (≤ 29)}}`.
  - `is_ai_generated` (booleano; muestra la etiqueta de contenido generado por IA).
- **Respuesta:** `photo{photo_post_id}` y `quota` (por ejemplo, «3/day»).
- **¿Sirve a Corte?** Dudoso. El perfil enumera `PHOTO_SHOPPABLE_PERMISSION_PRODUCT/SHOP` y no todas las cuentas de creador los tienen. Es inferencia: la spec no dice que sean obligatorios.
- **Valor:** bajo.
- **Fuente:** [SPEC] `postShoppablePhotos`; [DOC] `post-shoppable-photos-202610`.

#### 24. Get Shop Products
- **Método y path:** `GET /affiliate_creator/202509/shop_products`
- **Scope:** Content Posting en la spec; «Affiliate Information» en la tabla local, que es más vieja.
- **Quién:** token de creador **con tienda vinculada** («The creator must have a bound shop»).
- **Query:**
  - `title_keyword`.
  - `sort_field` (`PRODUCT_ID` por defecto, `PRICE`, `SALE`) y `sort_order` (`DESC` por defecto, `ASC`).
  - `page_size` (obligatorio, 1–100; se recomienda 20) y `page_token`.
- **Respuesta:** `products[]{id, title, price{amount,currency}, added_status (ADDABLE|ADDED|REJECTED), brand_name, images[]{url,width,height}, sales_count}`, `total_count`, `next_page_token`.
- **¿Sirve a Corte?** **No.** Es para creadores que también son vendedores; un creador afiliado sin tienda propia no lo puede usar.
- **Valor:** ninguno.
- **Fuente:** [SPEC] `getShopProducts`; [DOC] `get-shop-products-202509`; [LOCAL] `affiliate-integration.txt` (línea 82).

### Tokopedia (Indonesia)

#### 25. Map Tokopedia to TikTok Shop Product IDs
- **Método y path:** `GET /affiliate_creator/202606/toko_product_mappers`, con cuerpo JSON en un GET.
- **Scope:** Read Creator Affiliate Collaborations.
- **Quién:** token de creador.
- **Cuerpo:** `toko_pids[]` (enteros).
- **Respuesta:** `product[]{toko_pid, tts_pid}` y `error{code, message}`.
- **Límites:** no documentados.
- **¿Sirve a Corte?** No; solo aplica a productos de Tokopedia (Indonesia).
- **Valor:** ninguno.
- **Fuente:** [SPEC] `mapTokopediaToTikTokShopProductIDs`; [DOC] `map-tokopedia-to-tiktok-shop-product-ids-202606`.

#### 26. Get Tokopedia and TikTok Shop Product ID Mappings
- **Método y path:** `POST /affiliate_creator/202607/map_toko_product`
- **Scope:** Read Affiliate Share Link.
- **Quién:** token de creador.
- **Cuerpo:** `toko_pids[]`.
- **Respuesta:** la misma que el #25.
- **¿Sirve a Corte?** No.
- **Valor:** ninguno.
- **Fuente:** [SPEC] `getTokopediaAndTikTokShopProductIDMappings`; [DOC] `get-tokopedia-and-tiktok-shop-product-id-mappings-202607`.

---

## No verificados (citados, pero sin path ni ficha)

| # | Nombre | Dónde aparece | Por qué no se verifica |
|---|---|---|---|
| N1 | Get Live Room Info | `affiliate-integration.txt`, línea 82: tabla oficial de scopes, bajo «Affiliate Information» (ID 434372) | No hay ninguna ruta `/affiliate_creator/*live*` en la spec. La búsqueda web solo devolvió scrapers de terceros. Podría estar retirado o renombrado. Sería el único dato de LIVE en esta familia. |
| N2 | Check Anchor Content | La misma tabla | La spec no tiene la ruta ni la operación. |
| N3 | Check Anchor Prerequisites | La misma tabla | La spec no tiene la ruta ni la operación. Sus errores podrían parecerse a los `170001xxx` del #18 y el #20 (inferencia). |
| N4 | Search Music | La descripción de `music_id` en el #20 cita `GET /affiliate_creator/202602/music/search` | No existe como operación en la spec (2026.11.13) y la vista renderizada da 404. |
| N5 | Post Shoppable Video (202505) | La descripción del #17 cita `POST /affiliate_creator/202505/videos` | La spec solo tiene la versión 202603. Probablemente es la versión anterior; sin ficha. |
| N6 | Get Shop Category And Collection | La descripción de `group_id` en el #23 | No tiene path en la spec y no se sabe a qué familia pertenece. |

## Anexo: webhooks del lado creador (no son endpoints, pero dan datos)

Fuente: [SPEC], sección `webhooks:` y esquemas `*Webhook`.

- ⭐ **`shoppable_content_posting` (tipo 17).** Se dispara cuando el creador **agrega, actualiza o quita un producto en un video o LIVE**. Solo llega si el creador autorizó «Read Creator Affiliate Collaborations», que el token ya tiene.
  - Contenido: `type`, `tts_notification_id`, `creator_open_id`, `timestamp`, `data{product_id, event{type ADD|UPDATE|REMOVE, scene VIDEO, content_id}}`.
  - **Dato nuevo para Corte:** la lista de videos publicados con ancla de producto, **aunque no tengan ventas**. Hoy Corte solo conoce videos que ya generaron pedidos (`content_id`). También permitiría detectar al momento el video que salda una muestra.
  - **Requisito:** un receptor HTTPS público que reciba los avisos. El hub de Corte es local y su Redirect URL es una página estática; la configuración exacta de webhooks en Partner Center no se verificó en esta investigación.
- **`creator_deauthorization` (20):** el creador quitó todo el acceso a la app. El esquema de su contenido no se pudo leer (no se encontró `CreatorDeauthorizationWebhook` en los tramos revisados).
- **`sample_application_status_change` (56):** cambio de estado de una solicitud de muestra; trae `application_id`, `new_status`, `creator[]{creator_open_id}` y `product[]{id, sku_id}`. **Trae `shop_id`, así que parece del lado vendedor.** No se verificó que llegue con autorización de creador.
- **`video_precheck_result` (55) y `shoppable_video_precheck_tasks_result` (59):** resultados de la revisión previa (#18 y #19).
- **`upcoming_authorization_expiration` (7):** su texto habla de `shop_id` y del vendedor. No se verificó que aplique al token de creador.

## Huecos

1. **No hay endpoints de rendimiento de contenido** (vistas, likes ni GMV por video o por LIVE) en `creator.*`. El rendimiento por video se sigue infiriendo de pedidos (`content_id`). Las métricas de video tendrían que salir de otras familias (Display API de TikTok for Developers o Business), que no se revisaron aquí.
2. Get Live Room Info, Check Anchor Content y Check Anchor Prerequisites figuran en la tabla oficial de scopes, pero no tienen path documentado.
3. ~~La clave de «Content Posting» no está verificada.~~ **[Revisor]** Verificada: `creator.video.write` (no aprobada en la app). Lo que queda sin endpoint es `creator.affiliate.link.write`. Sobre «O» o «Y» con dos scopes, el uso real de Corte apunta a «O» (ver nota en «Convenciones»).
4. No hay API para **solicitar una muestra, retirarla ni pedir suspensión o prórroga del cumplimiento**. La doc de cumplimientos menciona «apply for fulfillment suspension», pero no hay endpoint.
5. `fulfillments/search` no documenta paginación; si un creador tiene muchos cumplimientos, no se sabe si la respuesta se corta.
6. `orders/trace/search`: no está claro si devuelve todos los pedidos o solo los de share links, y no se documenta la ventana máxima de tiempo.
7. No hay listado global de colaboraciones dirigidas: hay que iterar tienda por tienda con `shop_id`.
8. «Large File Uploads» (videos de más de 10 MB) no tiene path verificado.
9. `orders/search 202410` no filtra por fecha de actualización, así que no se puede sincronizar de forma incremental por `last_update_time`.
10. `creator.*` no tiene endpoint de saldo ni de pagos del creador; la conciliación depende de `SETTLED` y de trace con `SETTLE_TIME`.
11. Las páginas oficiales `docv2` no se pudieron leer con WebFetch porque se arman con JS. La spec se genera de ellas, pero no es oficial: los campos que no estaban en `[LOCAL]` vienen solo de la spec.

## Fuentes

- Docs locales (oficiales, ya descargadas): `research\tiktok-docs\`:
  - `get-creator-profile-202508.txt`, `get-showcase-products-202405.txt`, `search-creator-target-collaborations-202405.txt`.
  - `search-creator-sample-applications-202412.txt`, `get-creator-sample-application-detail-202412.txt`, `creator-search-sample-application-fulfillments-202409.txt`, `check-creator-sample-eligibility-202412.txt`.
  - `search-creator-affiliate-orders-202410.txt`, `search-affiliate-orders-by-creator-202505.txt`.
  - `affiliate-integration.txt`, `affiliate-creator-api-overview.txt`, `creator-authorization-guide.txt`, `access-scope.txt`.
- Spec OpenAPI (dato, no instrucciones): https://raw.githubusercontent.com/isaackogan/TikTok-Shop-Api-SDKs/main/.openapi/tiktok-shop.openapi.yaml (`info.version 2026.11.13`; tramos leídos: 0–100k, 1.44M–1.6M, 3.3M–3.4M, 3.7M–3.8M).
- Vista renderizada del mismo spec, solo como lector: `https://ttspa.docs.isaackogan.com/openapi/reference/operations/<operación>/`.
- URLs oficiales (`x-tts-docs-url`, citadas, no legibles sin JS): `https://partner.tiktokshop.com/docv2/page/<slug>`, con el slug indicado en cada ficha.
- Código de Corte, para confirmar el uso y el `105005`: `hub\creatorhub\sincronizador.py` y `sincronizador_ficha.py`.
